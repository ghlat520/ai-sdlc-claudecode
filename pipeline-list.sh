#!/usr/bin/env bash
# =============================================================================
# pipeline-list.sh — List all feature pipelines with status summary
#
# Scans docs/pipeline/*/state.json and displays a table of all features
# with their progress, cost, and last update time.
#
# Usage:
#   ./pipeline-list.sh              # Table view
#   ./pipeline-list.sh --json       # JSON output
#   ./pipeline-list.sh --verbose    # Detailed per-stage breakdown
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PIPELINE_ROOT="${PROJECT_ROOT}/docs/pipeline"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --json       Output as JSON array
  --verbose    Show per-stage breakdown for each feature
  --help       Show this help

Examples:
  $(basename "$0")              # Summary table
  $(basename "$0") --json       # Machine-readable output
  $(basename "$0") --verbose    # Detailed breakdown
EOF
    exit 0
}

list_features_table() {
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║  SDLC Pipeline Features                                                          ║${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    if [[ ! -d "$PIPELINE_ROOT" ]]; then
        echo -e "  ${DIM}No pipeline directory found at: ${PIPELINE_ROOT}${NC}"
        return 0
    fi

    local found=false

    # Header
    printf "  ${BOLD}%-25s %-15s %-10s %-12s %-20s${NC}\n" \
        "FEATURE_ID" "TECH_STACK" "PROGRESS" "COST (USD)" "LAST_UPDATED"
    echo "  ─────────────────────── ─────────────── ────────── ──────────── ────────────────────"

    for state_file in "${PIPELINE_ROOT}"/*/state.json; do
        [[ -f "$state_file" ]] || continue
        found=true

        python3 -c "
import json, os

with open('${state_file}') as f:
    state = json.load(f)

feature_id = state.get('feature_id', os.path.basename(os.path.dirname('${state_file}')))
tech_stack = state.get('tech_stack', state.get('config', {}).get('tech_stack', 'unknown'))
cost = state.get('cost', {})
cost_usd = cost.get('estimated_usd', 0.0)
updated = state.get('updated_at', state.get('created_at', '-'))
if updated and updated != '-':
    updated = updated[:19].replace('T', ' ')

# Count stages
stages = state.get('stages', {})
total = 13  # Fixed 13-stage pipeline
passed = sum(1 for s in stages.values() if s.get('status') == 'passed')
failed = sum(1 for s in stages.values() if s.get('status') in ('failed', 'dead_letter'))
running = sum(1 for s in stages.values() if s.get('status') in ('running', 'gate_checking'))

progress = f'{passed}/{total}'
if failed > 0:
    progress += f' ({failed}F)'
if running > 0:
    progress += f' ({running}R)'

print(f'  {feature_id:<25s} {tech_stack:<15s} {progress:<10s} \${cost_usd:<11.2f} {updated}')
" 2>/dev/null
    done

    if ! $found; then
        echo -e "  ${DIM}(no features found)${NC}"
    fi

    echo ""
}

list_features_verbose() {
    if [[ ! -d "$PIPELINE_ROOT" ]]; then
        echo -e "  ${DIM}No pipeline directory found${NC}"
        return 0
    fi

    local stage_order=("S1:requirements" "S2:architecture" "S3:backend" "S3b:frontend"
        "S4:testing" "S4b:integration-test" "S4c:e2e-testing" "S5:review"
        "S6:deployment" "S7:monitoring" "S8:documentation" "S9:performance" "S10:release")

    for state_file in "${PIPELINE_ROOT}"/*/state.json; do
        [[ -f "$state_file" ]] || continue

        local feature_dir
        feature_dir=$(dirname "$state_file")
        local feature_id
        feature_id=$(basename "$feature_dir")

        echo -e "\n${BOLD}${CYAN}Feature: ${feature_id}${NC}"

        python3 -c "
import json

with open('${state_file}') as f:
    state = json.load(f)

desc = state.get('feature_description', '-')
tech = state.get('tech_stack', 'unknown')
cost = state.get('cost', {})
print(f'  Description: {desc}')
print(f'  Tech Stack:  {tech}')
print(f'  Cost:        \${cost.get(\"estimated_usd\", 0):.2f} ({cost.get(\"total_tokens\", 0):,} tokens)')
print()

STAGE_ORDER = [
    ('S1', 'requirements'), ('S2', 'architecture'), ('S3', 'backend'),
    ('S3b', 'frontend'), ('S4', 'testing'), ('S4b', 'integration-test'),
    ('S4c', 'e2e-testing'), ('S5', 'review'), ('S6', 'deployment'),
    ('S7', 'monitoring'), ('S8', 'documentation'), ('S9', 'performance'),
    ('S10', 'release'),
]

stages = state.get('stages', {})
icons = {
    'passed': '\033[0;32m+\033[0m', 'running': '\033[0;36m>\033[0m',
    'failed': '\033[0;31mx\033[0m', 'dead_letter': '\033[0;31m!\033[0m',
    'human_waiting': '\033[0;33m?\033[0m', 'pending': '\033[2m.\033[0m'
}

print('  Stages: ', end='')
for sid, sname in STAGE_ORDER:
    s = stages.get(sid, {})
    status = s.get('status', 'pending')
    icon = icons.get(status, '.')
    print(f'{icon}', end='')
print()
print('          S1 S2 S3 3b S4 4b 4c S5 S6 S7 S8 S9 S10')
" 2>/dev/null
    done
    echo ""
}

list_features_json() {
    if [[ ! -d "$PIPELINE_ROOT" ]]; then
        echo "[]"
        return 0
    fi

    python3 -c "
import json, os, glob

pipeline_root = '${PIPELINE_ROOT}'
features = []

for state_file in sorted(glob.glob(os.path.join(pipeline_root, '*/state.json'))):
    feature_dir = os.path.basename(os.path.dirname(state_file))
    # Skip special directories
    if feature_dir in ('.archive', '_debug'):
        continue

    with open(state_file) as f:
        state = json.load(f)

    feature_id = state.get('feature_id', feature_dir)
    stages = state.get('stages', {})
    cost = state.get('cost', {})

    features.append({
        'feature_id': feature_id,
        'tech_stack': state.get('tech_stack', 'unknown'),
        'stages_passed': sum(1 for s in stages.values() if s.get('status') == 'passed'),
        'stages_total': 13,
        'total_tokens': cost.get('total_tokens', 0),
        'total_cost_usd': cost.get('estimated_usd', 0.0),
        'pipeline_state': state.get('pipeline_state', 'unknown'),
        'last_updated': state.get('updated_at', '-'),
    })

print(json.dumps(features, indent=2, ensure_ascii=False))
" 2>/dev/null
}

# --- Main ---
main() {
    local mode="table"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --json) mode="json"; shift ;;
            --verbose) mode="verbose"; shift ;;
            --help|-h) usage ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    case "$mode" in
        table)   list_features_table ;;
        verbose) list_features_verbose ;;
        json)    list_features_json ;;
    esac
}

main "$@"
