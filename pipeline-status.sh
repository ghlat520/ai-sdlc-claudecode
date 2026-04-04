#!/usr/bin/env bash
# =============================================================================
# pipeline-status.sh — Terminal status panel for pipeline execution
# Reads events.jsonl + state.json to render a live status view.
#
# Usage:
#   ./pipeline-status.sh <feature_id>
#   ./pipeline-status.sh <feature_id> --watch    # Auto-refresh every 5s
#   ./pipeline-status.sh <feature_id> --events    # Show event log
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PIPELINE_ROOT="${PROJECT_ROOT}/docs/pipeline"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

usage() {
    echo "Usage: $0 <feature_id> [--watch|--events|--cost]"
    exit 1
}

status_icon() {
    case "$1" in
        passed)         echo -e "${GREEN}✓${NC}" ;;
        running)        echo -e "${CYAN}▶${NC}" ;;
        gate_checking)  echo -e "${YELLOW}◎${NC}" ;;
        failed)         echo -e "${RED}✗${NC}" ;;
        retrying)       echo -e "${YELLOW}↻${NC}" ;;
        dead_letter)    echo -e "${RED}☠${NC}" ;;
        human_waiting)  echo -e "${YELLOW}⏸${NC}" ;;
        pending)        echo -e "${DIM}○${NC}" ;;
        *)              echo -e "${DIM}?${NC}" ;;
    esac
}

render_status() {
    local feature_id="$1"
    local state_file="${PIPELINE_ROOT}/${feature_id}/state.json"
    local events_file="${PIPELINE_ROOT}/${feature_id}/events.jsonl"

    if [[ ! -f "$state_file" ]]; then
        echo -e "${RED}No pipeline state found for: ${feature_id}${NC}"
        echo -e "  Expected: ${state_file}"
        return 1
    fi

    clear 2>/dev/null || true

    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║  SDLC Pipeline Status: ${feature_id}${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════╝${NC}"

    python3 -c "
import json, os
from datetime import datetime

with open('${state_file}') as f:
    state = json.load(f)

# Header info
desc = state.get('feature_description', 'N/A')
cost = state.get('cost', {})
print(f'  Description: {desc}')
print(f'  Cost: \${cost.get(\"estimated_usd\", 0):.2f} / \${state.get(\"config\", {}).get(\"cost_limit_usd\", 100):.2f}')
print(f'  Tokens: {cost.get(\"total_tokens\", 0):,}')
print()

# Stage order
STAGE_ORDER = [
    ('S1', 'requirements'),
    ('S2', 'architecture'),
    ('S3', 'backend'),
    ('S3b', 'frontend'),
    ('S4', 'testing'),
    ('S4b', 'integration-test'),
    ('S4c', 'e2e-testing'),
    ('S5', 'review'),
    ('S6', 'deployment'),
    ('S7', 'monitoring'),
    ('S8', 'documentation'),
    ('S9', 'performance'),
    ('S10', 'release'),
]

stages = state.get('stages', {})
print('  Stage          Status        Retries  Updated')
print('  ─────────────  ────────────  ───────  ───────────────────')

for sid, sname in STAGE_ORDER:
    sdata = stages.get(sid, {})
    status = sdata.get('status', 'pending')
    retries = sdata.get('retry_count', 0)
    updated = sdata.get('updated_at', '-')
    if updated != '-':
        updated = updated[:19].replace('T', ' ')

    # Status formatting
    icons = {
        'passed': '✓ passed', 'running': '▶ running', 'gate_checking': '◎ checking',
        'failed': '✗ failed', 'retrying': '↻ retrying', 'dead_letter': '☠ dead',
        'human_waiting': '⏸ waiting', 'pending': '○ pending'
    }
    status_str = icons.get(status, status)
    retry_str = str(retries) if retries > 0 else '-'

    print(f'  {sid} {sname:12s}  {status_str:14s}  {retry_str:>7s}  {updated}')

# Count summary
total = len(STAGE_ORDER)
passed = sum(1 for sid, _ in STAGE_ORDER if stages.get(sid, {}).get('status') == 'passed')
failed = sum(1 for sid, _ in STAGE_ORDER if stages.get(sid, {}).get('status') in ('failed', 'dead_letter'))
running = sum(1 for sid, _ in STAGE_ORDER if stages.get(sid, {}).get('status') in ('running', 'gate_checking'))
waiting = sum(1 for sid, _ in STAGE_ORDER if stages.get(sid, {}).get('status') == 'human_waiting')

print()
print(f'  Progress: {passed}/{total} passed | {running} running | {waiting} waiting | {failed} failed')

# Last event
events_file = '${events_file}'
if os.path.exists(events_file):
    with open(events_file) as f:
        lines = f.readlines()
    if lines:
        last = json.loads(lines[-1])
        print(f'  Last event: [{last[\"timestamp\"][:19]}] {last[\"event_type\"]}: {last[\"message\"]}')
" 2>/dev/null
}

show_events() {
    local feature_id="$1"
    local events_file="${PIPELINE_ROOT}/${feature_id}/events.jsonl"
    local limit="${2:-50}"

    if [[ ! -f "$events_file" ]]; then
        echo -e "${RED}No events found for: ${feature_id}${NC}"
        return 1
    fi

    echo -e "${BOLD}${CYAN}Event Log: ${feature_id}${NC}"
    echo ""

    python3 -c "
import json

with open('${events_file}') as f:
    lines = f.readlines()

for line in lines[-${limit}:]:
    event = json.loads(line)
    ts = event['timestamp'][:19].replace('T', ' ')
    etype = event['event_type']
    stage = event.get('stage_id', '-')
    msg = event['message']

    # Color by type
    colors = {
        'stage_start': '\033[0;36m', 'stage_pass': '\033[0;32m',
        'stage_fail': '\033[0;31m', 'gate_pass': '\033[0;32m',
        'gate_fail': '\033[0;33m', 'retry': '\033[0;33m',
        'dead_letter': '\033[0;31m', 'cost_update': '\033[0;35m',
        'pipeline_start': '\033[1;36m', 'pipeline_end': '\033[1;32m',
        'human_wait': '\033[1;33m'
    }
    color = colors.get(etype, '')
    reset = '\033[0m' if color else ''

    print(f'  {color}[{ts}] {stage:4s} {etype:16s} {msg}{reset}')
" 2>/dev/null
}

# --- Main ---
main() {
    if [[ $# -lt 1 ]]; then
        # List all features with pipeline state
        echo -e "${BOLD}${CYAN}Available Pipeline Runs:${NC}"
        if [[ -d "$PIPELINE_ROOT" ]]; then
            for state_file in "${PIPELINE_ROOT}"/*/state.json; do
                [[ -f "$state_file" ]] || continue
                local fid
                fid=$(basename "$(dirname "$state_file")")
                echo "  - ${fid}"
            done
        else
            echo "  (none)"
        fi
        echo ""
        usage
    fi

    local feature_id="$1"
    local mode="${2:-status}"

    case "$mode" in
        --events) show_events "$feature_id" ;;
        --watch)
            while true; do
                render_status "$feature_id"
                echo -e "\n${DIM}  Refreshing every 5s... (Ctrl+C to stop)${NC}"
                sleep 5
            done
            ;;
        --cost)
            python3 -c "
import json
with open('${PIPELINE_ROOT}/${feature_id}/state.json') as f:
    state = json.load(f)
cost = state.get('cost', {})
print(f'Total tokens: {cost.get(\"total_tokens\", 0):,}')
print(f'Estimated USD: \${cost.get(\"estimated_usd\", 0):.4f}')
print(f'Cost limit: \${state.get(\"config\", {}).get(\"cost_limit_usd\", 100):.2f}')
" 2>/dev/null
            ;;
        *) render_status "$feature_id" ;;
    esac
}

main "$@"
