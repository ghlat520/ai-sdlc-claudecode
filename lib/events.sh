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
    local extra="${5:-{}}"
    local pipeline_root="${PIPELINE_ROOT:-docs/pipeline}"
    local event_dir="${pipeline_root}/${feature_id}"
    local event_file="${event_dir}/events.jsonl"

    mkdir -p "$event_dir"

    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local escaped_msg
    escaped_msg=$(_json_escape "$message")

    local event_line
    event_line=$(python3 -c "
import json, sys
event = {
    'timestamp': '${timestamp}',
    'event_type': '${event_type}',
    'stage_id': '${stage_id}',
    'feature_id': '${feature_id}',
    'message': ${escaped_msg},
    'extra': json.loads(sys.argv[1]) if sys.argv[1] != '{}' else {}
}
print(json.dumps(event, ensure_ascii=False))
" "$extra" 2>/dev/null)

    echo "$event_line" >> "$event_file"

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
        pipeline_end)   echo -e "\033[1;32m[${timestamp}] ═══ Pipeline complete: ${feature_id} ═══\033[0m" >&2 ;;
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

# Read state from state file
# Usage: get_stage_state <feature_id> <stage_id>
get_stage_state() {
    local feat_id="$1"
    local stg_id="$2"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local s_file="${p_root}/${feat_id}/state.json"

    if [[ ! -f "$s_file" ]]; then
        echo "pending"
        return
    fi

    python3 -c "
import json
with open('${s_file}') as f:
    state = json.load(f)
print(state.get('stages', {}).get('${stg_id}', {}).get('status', 'pending'))
" 2>/dev/null || echo "pending"
}

# Update state file
# Usage: set_stage_state <feature_id> <stage_id> <status> [retry_count]
set_stage_state() {
    local feat_id="$1"
    local stg_id="$2"
    local stg_status="$3"
    local retry_cnt="${4:-0}"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local s_file="${p_root}/${feat_id}/state.json"

    mkdir -p "$(dirname "$s_file")"

    python3 -c "
import json, os
from datetime import datetime

state_file = '${s_file}'
if os.path.exists(state_file):
    with open(state_file) as f:
        state = json.load(f)
else:
    state = {'feature_id': '${feat_id}', 'stages': {}, 'cost': {'total_tokens': 0, 'estimated_usd': 0.0}}

state['stages']['${stg_id}'] = {
    'status': '${stg_status}',
    'retry_count': int('${retry_cnt}'),
    'updated_at': datetime.utcnow().isoformat() + 'Z'
}
state['updated_at'] = datetime.utcnow().isoformat() + 'Z'

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
" 2>/dev/null
}

# Update cost tracking
# Usage: update_cost <feature_id> <tokens_used> <model>
update_cost() {
    local feature_id="$1"
    local tokens_used="$2"
    local model="${3:-sonnet}"
    local pipeline_root="${PIPELINE_ROOT:-docs/pipeline}"
    local state_file="${pipeline_root}/${feature_id}/state.json"

    _UC_STATE_FILE="$state_file" _UC_FEATURE_ID="$feature_id" \
    _UC_TOKENS="$tokens_used" _UC_MODEL="$model" \
    python3 << 'PYEOF' 2>/dev/null
import json, os

# Pricing per 1M tokens (blended input+output average)
PRICING = {
    'opus': 45.0,     # avg($15 input + $75 output)
    'sonnet': 9.0,    # avg($3 input + $15 output)
    'haiku': 2.4      # avg($0.80 input + $4 output)
}

state_file = os.environ['_UC_STATE_FILE']
feature_id = os.environ['_UC_FEATURE_ID']
tokens_used = int(os.environ['_UC_TOKENS'])
model = os.environ['_UC_MODEL']

if os.path.exists(state_file):
    with open(state_file) as f:
        state = json.load(f)
else:
    state = {'feature_id': feature_id, 'stages': {}, 'cost': {'total_tokens': 0, 'estimated_usd': 0.0}}

rate = PRICING.get(model, 0.015)
cost_increment = (tokens_used / 1_000_000) * rate

state['cost']['total_tokens'] = state['cost'].get('total_tokens', 0) + tokens_used
state['cost']['estimated_usd'] = round(state['cost'].get('estimated_usd', 0.0) + cost_increment, 4)

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"Tokens: +{tokens_used} | Total: {state['cost']['total_tokens']} | USD: ${state['cost']['estimated_usd']}")
PYEOF
}

# Set pipeline-level pause/resume state
# Usage: set_pipeline_state <feature_id> <state> [reason]
set_pipeline_state() {
    local feat_id="$1"
    local pipe_state="$2"
    local reason="${3:-}"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local s_file="${p_root}/${feat_id}/state.json"

    python3 -c "
import json, os
from datetime import datetime

state_file = '${s_file}'
if os.path.exists(state_file):
    with open(state_file) as f:
        state = json.load(f)
else:
    state = {'feature_id': '${feat_id}', 'stages': {}, 'cost': {'total_tokens': 0, 'estimated_usd': 0.0}}

state['pipeline_state'] = '${pipe_state}'
state['pipeline_state_reason'] = '${reason}'
state['pipeline_state_at'] = datetime.utcnow().isoformat() + 'Z'
state['updated_at'] = datetime.utcnow().isoformat() + 'Z'

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
" 2>/dev/null
}

# Get last passed stage for resume
# Usage: get_resume_point <feature_id>
# Returns the stage_id of the first non-passed stage
get_resume_point() {
    local feat_id="$1"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local s_file="${p_root}/${feat_id}/state.json"

    if [[ ! -f "$s_file" ]]; then
        echo ""
        return
    fi

    # Resolve DAG file path reliably
    local dag_path
    local events_dir
    events_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    dag_path="$(cd "${events_dir}/.." && pwd)/pipeline-dag.json"

    DAG_PATH="$dag_path" STATE_PATH="$s_file" python3 -c "
import json, os

with open(os.environ['STATE_PATH']) as f:
    state = json.load(f)

# All 13 stage IDs as defined in DAG
all_stage_ids = ['S1','S2','S3','S3b','S4','S4b','S4c','S5','S6','S7','S8','S9','S10']
try:
    with open(os.environ['DAG_PATH']) as f:
        dag = json.load(f)
    all_stage_ids = sorted(
        [s['id'] for s in dag.get('stages', {}).values()],
        key=lambda x: (len(x), x)
    )
except Exception:
    pass

stages = state.get('stages', {})
for sid in all_stage_ids:
    if stages.get(sid, {}).get('status') != 'passed':
        print(sid)
        break
else:
    print('')
" 2>/dev/null
}

# Send webhook notification
# Usage: send_notification <feature_id> <event_type> <message>
send_notification() {
    local feat_id="$1"
    local event_type="$2"
    local message="$3"
    local dag_file="${SCRIPT_DIR:-ai-sdlc-claudecode}/pipeline-dag.json"

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
