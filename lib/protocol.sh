#!/usr/bin/env bash
# =============================================================================
# protocol.sh — MetaGPT-style Communication Protocol for Agent Pipeline
#
# Implements structured message passing between agents:
#   Commander → Agent: "Create PRD"
#   Agent → Commander: "PRD complete, path: /path/prd.json"
#
# This gives us MetaGPT-equivalent communication with:
#   - Typed messages (request/response/handoff/error)
#   - Artifact references (output file paths)
#   - Communication log (auditable trail)
#   - Central dispatcher routing (Commander role)
#
# MetaGPT equivalent mapping:
#   Mike (PM)     → Commander (pipeline-executor)
#   Alice (PM)    → Product Manager agent (S1)
#   Bob (Arch)    → Software Architect agent (S2)
#   Alex (Dev)    → Senior Developer agent (S3)
#   Eve (QA)      → tdd-guide agent (S4)
#
# Key difference from MetaGPT:
#   MetaGPT: Python async/await + in-memory message queue
#   Ours:    Bash DAG executor + file-based message log + schema validation
#   Result:  Same semantics, different runtime
# =============================================================================

# --- Message Types ---
MSG_REQUEST="request"       # Commander → Agent: do this task
MSG_RESPONSE="response"     # Agent → Commander: task done, here's output
MSG_HANDOFF="handoff"       # Commander routes output from Agent A to Agent B
MSG_ERROR="error"           # Agent → Commander: task failed
MSG_GATE="gate"             # Commander: gate check result
MSG_PARALLEL="parallel"     # Commander: launching parallel group

# Send a protocol message (append to communication log)
# Usage: send_message <feature_id> <from> <to> <msg_type> <content> [artifact_path] [priority]
send_message() {
    local feat_id="$1"
    local from_agent="$2"
    local to_agent="$3"
    local msg_type="$4"
    local content="$5"
    local artifact_path="${6:-}"
    local priority="${7:-info}"  # info | warning | critical
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local comm_log="${p_root}/${feat_id}/communication.jsonl"

    mkdir -p "$(dirname "$comm_log")"

    python3 -c "
import json
from datetime import datetime

msg = {
    'timestamp': datetime.utcnow().isoformat() + 'Z',
    'from': '${from_agent}',
    'to': '${to_agent}',
    'type': '${msg_type}',
    'priority': '${priority}',
    'content': $(python3 -c "import json; print(json.dumps('${content}'))" 2>/dev/null || echo "\"${content}\""),
    'artifact': '${artifact_path}' if '${artifact_path}' else None
}
print(json.dumps({k:v for k,v in msg.items() if v is not None}, ensure_ascii=False))
" 2>/dev/null >> "$comm_log"

    # Pretty print to stderr
    local arrow="→"
    local color=""
    case "$msg_type" in
        request)  color="\033[0;36m" ;;   # cyan
        response) color="\033[0;32m" ;;   # green
        handoff)  color="\033[0;35m" ;;   # magenta
        error)    color="\033[0;31m" ;;   # red
        gate)     color="\033[0;33m" ;;   # yellow
        parallel) color="\033[1;36m" ;;   # bold cyan
    esac

    local artifact_info=""
    if [[ -n "$artifact_path" ]]; then
        artifact_info=" [artifact: ${artifact_path}]"
    fi

    echo -e "${color}[Protocol] ${from_agent} ${arrow} ${to_agent}: ${content}${artifact_info}\033[0m" >&2
}

# Send a signal file (stage completion marker)
# Usage: send_signal <feature_id> <stage_id> [status]
send_signal() {
    local feat_id="$1"
    local stage_id="$2"
    local status="${3:-done}"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local signal_dir="${p_root}/${feat_id}/signals"

    mkdir -p "$signal_dir"
    echo "$status" > "${signal_dir}/${stage_id}.done"
}

# Wait for a signal file (poll-based, with timeout)
# Usage: wait_for_signal <feature_id> <stage_id> [timeout_seconds]
wait_for_signal() {
    local feat_id="$1"
    local stage_id="$2"
    local timeout="${3:-600}"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local signal_file="${p_root}/${feat_id}/signals/${stage_id}.done"

    local waited=0
    local interval=2

    while [[ $waited -lt $timeout ]]; do
        if [[ -f "$signal_file" ]]; then
            cat "$signal_file"
            return 0
        fi
        sleep "$interval"
        ((waited += interval))
    done

    echo "timeout"
    return 1
}

# Route upstream output to downstream agent (MetaGPT-style handoff)
# Usage: route_handoff <feature_id> <from_stage> <to_stage> <artifact_path>
route_handoff() {
    local feat_id="$1"
    local from_stage="$2"
    local to_stage="$3"
    local artifact_path="$4"

    send_message "$feat_id" "Commander" "$to_stage" "$MSG_HANDOFF" \
        "Routing output from ${from_stage}: use as input" "$artifact_path"
}

# Print communication log (MetaGPT-style conversation view)
# Usage: show_communication_log <feature_id> [limit]
show_communication_log() {
    local feat_id="$1"
    local limit="${2:-50}"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local comm_log="${p_root}/${feat_id}/communication.jsonl"

    if [[ ! -f "$comm_log" ]]; then
        echo "No communication log found for: ${feat_id}"
        return 1
    fi

    echo -e "\033[1;36m╔══════════════════════════════════════════════════╗\033[0m"
    echo -e "\033[1;36m║  Agent Communication Log: ${feat_id}\033[0m"
    echo -e "\033[1;36m╚══════════════════════════════════════════════════╝\033[0m"
    echo ""

    python3 -c "
import json

COLORS = {
    'request':  '\033[0;36m',   # cyan
    'response': '\033[0;32m',   # green
    'handoff':  '\033[0;35m',   # magenta
    'error':    '\033[0;31m',   # red
    'gate':     '\033[0;33m',   # yellow
    'parallel': '\033[1;36m',   # bold cyan
}
RESET = '\033[0m'
DIM = '\033[2m'

with open('${comm_log}') as f:
    lines = f.readlines()

for line in lines[-${limit}:]:
    msg = json.loads(line)
    ts = msg['timestamp'][:19].replace('T', ' ')
    mtype = msg['type']
    color = COLORS.get(mtype, '')
    artifact = f\"  📎 {msg['artifact']}\" if msg.get('artifact') else ''

    print(f\"{DIM}{ts}{RESET}  {color}{msg['from']:20s} → {msg['to']:20s}{RESET}  {msg['content']}{artifact}\")
" 2>/dev/null
}

# Show communication log filtered by stage
# Usage: show_stage_communication <feature_id> <stage_id>
show_stage_communication() {
    local feat_id="$1"
    local stage_id="$2"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local comm_log="${p_root}/${feat_id}/communication.jsonl"

    if [[ ! -f "$comm_log" ]]; then
        echo "No communication log found for: ${feat_id}"
        return 1
    fi

    # Map stage IDs to human-readable names
    local stage_label
    stage_label=$(python3 -c "
STAGE_LABELS = {
    'S1': 'Requirements',     'S2': 'Architecture',
    'S3': 'Backend',          'S3b': 'Frontend',
    'S4': 'Unit Testing',     'S4b': 'Integration Testing',
    'S4c': 'E2E Testing',     'S5': 'Code Review',
    'S6': 'Deployment',       'S7': 'Monitoring',
    'S8': 'Documentation',    'S9': 'Performance',
    'S10': 'Release',
}
print(STAGE_LABELS.get('${stage_id}', '${stage_id}'))
" 2>/dev/null)

    echo -e "\033[1;36m╔══════════════════════════════════════════════════╗\033[0m"
    echo -e "\033[1;36m║  Stage Communication: ${stage_id} - ${stage_label}\033[0m"
    echo -e "\033[1;36m╚══════════════════════════════════════════════════╝\033[0m"
    echo ""

    # Map stage IDs to stage names for matching
    python3 -c "
import json

STAGE_NAMES = {
    'S1': 'requirements',     'S2': 'architecture',
    'S3': 'backend',          'S3b': 'frontend',
    'S4': 'testing',          'S4b': 'integration-testing',
    'S4c': 'e2e-testing',     'S5': 'review',
    'S6': 'deployment',       'S7': 'monitoring',
    'S8': 'documentation',    'S9': 'performance',
    'S10': 'release',
}

stage_id = '${stage_id}'
stage_name = STAGE_NAMES.get(stage_id, stage_id)

COLORS = {
    'request':  '\033[0;36m',
    'response': '\033[0;32m',
    'handoff':  '\033[0;35m',
    'error':    '\033[0;31m',
    'gate':     '\033[0;33m',
    'parallel': '\033[1;36m',
}
RESET = '\033[0m'
DIM = '\033[2m'

with open('${comm_log}') as f:
    lines = f.readlines()

found = 0
for line in lines:
    msg = json.loads(line)
    # Match messages involving this stage
    involves_stage = (
        stage_name in msg.get('from', '').lower() or
        stage_name in msg.get('to', '').lower() or
        stage_id in msg.get('content', '') or
        stage_name in msg.get('content', '')
    )
    if not involves_stage:
        continue

    found += 1
    ts = msg['timestamp'][:19].replace('T', ' ')
    mtype = msg['type']
    color = COLORS.get(mtype, '')
    artifact = f'  [artifact: {msg[\"artifact\"]}]' if msg.get('artifact') else ''

    print(f'{DIM}{ts}{RESET}  {color}{msg[\"from\"]:20s} -> {msg[\"to\"]:20s}{RESET}  {msg[\"content\"]}{artifact}')

if found == 0:
    print(f'  (no messages found for stage {stage_id})')
else:
    print(f'\n  Total: {found} messages')
" 2>/dev/null
}

# Generate MetaGPT-equivalent async execution summary
# Usage: generate_execution_trace <feature_id>
generate_execution_trace() {
    local feat_id="$1"
    local p_root="${PIPELINE_ROOT:-docs/pipeline}"
    local comm_log="${p_root}/${feat_id}/communication.jsonl"

    if [[ ! -f "$comm_log" ]]; then
        echo "No communication log found"
        return 1
    fi

    echo ""
    echo "# MetaGPT-equivalent execution trace"
    echo "# (what MetaGPT would do with async/await, we do with DAG + files)"
    echo ""

    python3 -c "
import json

with open('${comm_log}') as f:
    lines = f.readlines()

# Group into request/response pairs
for line in lines:
    msg = json.loads(line)
    mtype = msg['type']

    if mtype == 'request':
        print(f\"Commander → {msg['to']}: \\\"{msg['content']}\\\"\")
    elif mtype == 'response':
        artifact = f\", artifact: {msg['artifact']}\" if msg.get('artifact') else ''
        print(f\"{msg['from']} → Commander: \\\"{msg['content']}{artifact}\\\"\")
    elif mtype == 'handoff':
        print(f\"Commander routes: {msg['content']}\")
    elif mtype == 'parallel':
        print(f\"Commander ⚡ parallel: {msg['content']}\")
    elif mtype == 'gate':
        print(f\"Commander ◉ gate: {msg['content']}\")
" 2>/dev/null
}
