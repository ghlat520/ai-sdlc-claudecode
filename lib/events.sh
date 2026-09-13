#!/usr/bin/env bash
# =============================================================================
# events.sh — Structured event logging for pipeline execution
# Writes JSONL events to docs/pipeline/{feature_id}/events.jsonl
# =============================================================================

# Ensure jq-less JSON generation
_json_escape() {
    python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$1" 2>/dev/null || echo "\"$1\""
}

# Write a structured event
# Usage: emit_event <feature_id> <event_type> <stage_id> <message> [extra_json]
emit_event() {
    local feature_id="$1"
    local event_type="$2"
    local stage_id="$3"
    local message="$4"
    local extra="${5:-}"
    [[ -n "$extra" ]] || extra='{}'
    local pipeline_root="${PIPELINE_ROOT:-docs/pipeline}"
    local event_dir="${pipeline_root}/${feature_id}"
    local event_file="${event_dir}/events.jsonl"

    mkdir -p "$event_dir"

    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    python3 - "$event_file" "$timestamp" "$event_type" "$stage_id" "$feature_id" "$message" "$extra" <<'PY_EVENT'
import fcntl, json, os, sys
path, timestamp, kind, stage, feature, message, extra = sys.argv[1:]
with open(path, "a") as out:
    fcntl.flock(out, fcntl.LOCK_EX)
    out.write(json.dumps(dict(timestamp=timestamp, event_type=kind, stage_id=stage,
                             feature_id=feature, message=message, extra=json.loads(extra),
                             run_id=os.environ.get("PIPELINE_RUN_ID"),
                             attempt_id=os.environ.get("PIPELINE_ATTEMPT_ID")), ensure_ascii=False)+"\n")
PY_EVENT

    # Also print to stderr for real-time visibility
    case "$event_type" in
        stage_start)    echo -e "\033[0;36m[${timestamp}] ▶ ${stage_id}: ${message}\033[0m" >&2 ;;
        stage_pass)     echo -e "\033[0;32m[${timestamp}] ✓ ${stage_id}: ${message}\033[0m" >&2 ;;
        stage_fail)     echo -e "\033[0;31m[${timestamp}] ✗ ${stage_id}: ${message}\033[0m" >&2 ;;
        gate_pass)      echo -e "\033[0;32m[${timestamp}] ◉ ${stage_id}: Gate passed\033[0m" >&2 ;;
        gate_fail)      echo -e "\033[0;33m[${timestamp}] ◎ ${stage_id}: Gate failed\033[0m" >&2 ;;
        retry)          echo -e "\033[0;33m[${timestamp}] ↻ ${stage_id}: ${message}\033[0m" >&2 ;;
        dead_letter)    echo -e "\033[0;31m[${timestamp}] ☠ ${stage_id}: ${message}\033[0m" >&2 ;;
        cost_update)    echo -e "\033[0;35m[${timestamp}] $ ${message}\033[0m" >&2 ;;
        pipeline_start) echo -e "\033[1;36m[${timestamp}] ═══ Pipeline started: ${feature_id} ═══\033[0m" >&2 ;;
        pipeline_end)   echo -e "\033[1;32m[${timestamp}] ═══ Pipeline stopped: ${feature_id} ═══\033[0m" >&2 ;;
        pipeline_pause) echo -e "\033[1;33m[${timestamp}] ⏸ Pipeline paused: ${feature_id}\033[0m" >&2 ;;
        pipeline_resume) echo -e "\033[1;36m[${timestamp}] ▶ Pipeline resumed: ${feature_id}\033[0m" >&2 ;;
        human_wait)     echo -e "\033[1;33m[${timestamp}] ⏸ ${stage_id}: Waiting for human approval\033[0m" >&2 ;;
        ai_review_start) echo -e "\033[0;35m[${timestamp}] 🔍 ${stage_id}: ${message}\033[0m" >&2 ;;
        ai_review_done) echo -e "\033[0;35m[${timestamp}] 🔍 ${stage_id}: ${message}\033[0m" >&2 ;;
        ai_review_fail) echo -e "\033[0;31m[${timestamp}] 🔍 ${stage_id}: ${message}\033[0m" >&2 ;;
        post_cmd_pass)  echo -e "\033[0;32m[${timestamp}] ⚙ ${stage_id}: ${message}\033[0m" >&2 ;;
        post_cmd_fail)  echo -e "\033[0;31m[${timestamp}] ⚙ ${stage_id}: ${message}\033[0m" >&2 ;;
        evidence_found) echo -e "\033[0;32m[${timestamp}] 📋 ${stage_id}: ${message}\033[0m" >&2 ;;
        evidence_missing) echo -e "\033[0;33m[${timestamp}] 📋 ${stage_id}: ${message}\033[0m" >&2 ;;
        *)              echo -e "[${timestamp}] ${stage_id}: ${message}" >&2 ;;
    esac
}

# All state writers use the same locked, atomic Python implementation.
_pipeline_state() {
    local command="$1" feature="$2"
    shift 2
    local root
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    PYTHONPATH="${root}/src${PYTHONPATH:+:${PYTHONPATH}}" python3 -m ai_sdlc_claudecode.state \
        "$command" "${PIPELINE_ROOT:-docs/pipeline}/${feature}/state.json" "$@"
}

get_stage_state() {
    _pipeline_state get "$1" "$2" "${DAG_FILE:-${PIPELINE_DAG_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/pipeline-dag.json}}"
}

set_stage_state() {
    _pipeline_state stage "$1" "${PIPELINE_RUN_ID:-}" "$2" "${PIPELINE_ATTEMPT_ID:-}" "$3" "${4:-0}" "${PIPELINE_LAST_APPLIED_FIXES:-}"
}

collect_evidence() {
    _pipeline_state evidence "$1" "$PIPELINE_RUN_ID" "$2" "$PIPELINE_ATTEMPT_ID" "$3" "$4" "$5"
}

update_cost() {
    _pipeline_state cost "$1" estimated "${3:-sonnet}" 0 "$2" 0 0 0
}

update_cost_real() {
    _pipeline_state cost "$1" actual "${7:-unknown}" "$2" "${3:-0}" "${4:-0}" "${5:-0}" "${6:-0}"
}

set_pipeline_state() {
    _pipeline_state pipeline "$1" "$2" "${3:-}"
}

get_resume_point() {
    _pipeline_state resume "$1" "${DAG_FILE:-${PIPELINE_DAG_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/pipeline-dag.json}}"
}

# Send webhook notification
# Usage: send_notification <feature_id> <event_type> <message>
send_notification() {
    local feat_id="$1"
    local event_type="$2"
    local message="$3"
    local dag_file="${PIPELINE_DAG_FILE:-${SCRIPT_DIR:-ai-sdlc-claudecode}/pipeline-dag.json}"

    # Read webhook config
    local config
    config=$(python3 -c "
import json, os

dag_file = '${dag_file}'
if not os.path.exists(dag_file):
    # Try relative
    for p in ['ai-sdlc-claudecode/pipeline-dag.json', 'pipeline-dag.json']:
        if os.path.exists(p):
            dag_file = p
            break

if not os.path.exists(dag_file):
    exit(0)

with open(dag_file) as f:
    dag = json.load(f)
notif = dag.get('config', {}).get('notification', {})
url = notif.get('webhook_url', '')
wtype = notif.get('webhook_type', 'dingtalk')
notify_on = notif.get('notify_on', [])
print(f'{url}|{wtype}|{\",\".join(notify_on)}')
" 2>/dev/null)

    local webhook_url="${config%%|*}"
    local rest="${config#*|}"
    local webhook_type="${rest%%|*}"
    local notify_events="${rest#*|}"

    # Skip if no webhook URL or event not in notify list
    if [[ -z "$webhook_url" ]]; then
        return 0
    fi
    if ! echo "$notify_events" | tr ',' '\n' | grep -qw "$event_type"; then
        return 0
    fi

    # Send notification based on type
    case "$webhook_type" in
        dingtalk)
            curl -s -X POST "$webhook_url" \
                -H "Content-Type: application/json" \
                -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[Pipeline] ${feat_id}: ${message}\"}}" \
                >/dev/null 2>&1 || true
            ;;
        slack)
            curl -s -X POST "$webhook_url" \
                -H "Content-Type: application/json" \
                -d "{\"text\":\"[Pipeline] ${feat_id}: ${message}\"}" \
                >/dev/null 2>&1 || true
            ;;
        feishu)
            curl -s -X POST "$webhook_url" \
                -H "Content-Type: application/json" \
                -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"[Pipeline] ${feat_id}: ${message}\"}}" \
                >/dev/null 2>&1 || true
            ;;
    esac
}

# Check cost limit
# Usage: check_cost_limit <feature_id> <limit_usd>
# Returns 0 if under limit, 1 if over
check_cost_limit() {
    local feature_id="$1"
    local limit_usd="$2"
    local pipeline_root="${PIPELINE_ROOT:-docs/pipeline}"
    local state_file="${pipeline_root}/${feature_id}/state.json"

    python3 -c "
import json, os, sys

state_file = '${state_file}'
if not os.path.exists(state_file):
    sys.exit(0)

with open(state_file) as f:
    state = json.load(f)

current = state.get('cost', {}).get('estimated_usd', 0.0)
limit = float('${limit_usd}')

if current >= limit:
    print(f'COST LIMIT EXCEEDED: \${current:.2f} >= \${limit:.2f}')
    sys.exit(1)
else:
    print(f'Cost OK: \${current:.2f} / \${limit:.2f}')
    sys.exit(0)
" 2>/dev/null
}
