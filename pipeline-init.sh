#!/usr/bin/env bash
# =============================================================================
# pipeline-init.sh — Initialize a new feature pipeline
#
# Scaffolds the feature directory with all stage subdirs, initializes state.json,
# validates DAG, and prints the execution plan.
#
# Usage:
#   ./pipeline-init.sh <feature_id> <feature_description> [--tech-stack <stack>]
#
# Example:
#   ./pipeline-init.sh ai-media-platform "AI self-media content platform"
#   ./pipeline-init.sh health-check "Add /health endpoint" --tech-stack golang
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DAG_FILE="${SCRIPT_DIR}/pipeline-dag.json"

# shellcheck source=lib/events.sh
source "${SCRIPT_DIR}/lib/events.sh"

export PIPELINE_ROOT="${PROJECT_ROOT}/docs/pipeline"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") <feature_id> <feature_description> [options]

Arguments:
  feature_id          Unique identifier (e.g., "ai-media-platform")
  feature_description Brief description of the feature

Options:
  --tech-stack <S>    Technology stack (default: from DAG config)
                      Options: java-maven, node-typescript, python, golang
  --force             Overwrite existing feature directory

Examples:
  $(basename "$0") ai-media-platform "AI self-media content platform"
  $(basename "$0") health-check "Add /health endpoint" --tech-stack golang
  $(basename "$0") order-export "Order export batch job" --force
EOF
    exit 1
}

main() {
    local feature_id=""
    local feature_description=""
    local tech_stack=""
    local force=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tech-stack) tech_stack="$2"; shift 2 ;;
            --force) force=true; shift ;;
            --help|-h) usage ;;
            *)
                if [[ -z "$feature_id" ]]; then
                    feature_id="$1"
                elif [[ -z "$feature_description" ]]; then
                    feature_description="$1"
                fi
                shift ;;
        esac
    done

    if [[ -z "$feature_id" || -z "$feature_description" ]]; then
        usage
    fi

    local feature_dir="${PIPELINE_ROOT}/${feature_id}"

    # Check existing
    if [[ -d "$feature_dir" ]] && ! $force; then
        echo -e "${RED}ERROR: Feature directory already exists: ${feature_dir}${NC}"
        echo -e "${YELLOW}Use --force to overwrite${NC}"
        exit 1
    fi

    # Read tech_stack from DAG if not specified
    if [[ -z "$tech_stack" ]]; then
        tech_stack=$(python3 -c "import json; print(json.load(open('${DAG_FILE}')).get('config', {}).get('tech_stack', 'java-maven'))" 2>/dev/null)
    fi

    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║  Pipeline Init: ${feature_id}${NC}"
    echo -e "${BOLD}${CYAN}║  Tech Stack: ${tech_stack}${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════╝${NC}"

    # Validate DAG first
    echo -e "\n${YELLOW}[1/4] Validating DAG...${NC}"
    DAG_PATH="$DAG_FILE" SCHEMAS_BASE="$SCRIPT_DIR" python3 << 'PYEOF'
import json, os, sys
with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)
stages = dag['stages']
for name, stage in stages.items():
    schema_path = os.path.join(os.environ['SCHEMAS_BASE'], stage['output_schema'])
    if not os.path.exists(schema_path):
        print(f'ERROR: Schema not found: {schema_path}')
        sys.exit(1)
print(f'DAG valid: {len(stages)} stages')
PYEOF

    # Create directory structure
    echo -e "\n${YELLOW}[2/4] Creating directory structure...${NC}"
    mkdir -p "$feature_dir"

    # Create stage subdirs
    local stage_dirs
    stage_dirs=$(python3 -c "
import json
with open('${DAG_FILE}') as f:
    dag = json.load(f)
for name, stage in dag['stages'].items():
    print(f\"{stage['id']}-{name}\")
" 2>/dev/null)

    while IFS= read -r subdir; do
        mkdir -p "${feature_dir}/${subdir}"
        echo -e "  ${GREEN}+${NC} ${feature_id}/${subdir}/"
    done <<< "$stage_dirs"

    # Initialize state.json
    echo -e "\n${YELLOW}[3/4] Initializing state...${NC}"

    local cost_limit
    cost_limit=$(python3 -c "import json; print(json.load(open('${DAG_FILE}'))['config']['cost_limit_usd'])" 2>/dev/null)
    local max_retries
    max_retries=$(python3 -c "import json; print(json.load(open('${DAG_FILE}'))['config']['max_retries_per_stage'])" 2>/dev/null)

    python3 -c "
import json
from datetime import datetime

state = {
    'feature_id': '${feature_id}',
    'feature_description': '${feature_description}',
    'tech_stack': '${tech_stack}',
    'pipeline_state': 'initialized',
    'stages': {},
    'cost': {'total_tokens': 0, 'estimated_usd': 0.0},
    'config': {
        'cost_limit_usd': float('${cost_limit}'),
        'max_retries': int('${max_retries}')
    },
    'created_at': datetime.utcnow().isoformat() + 'Z',
    'updated_at': datetime.utcnow().isoformat() + 'Z'
}

with open('${feature_dir}/state.json', 'w') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
print('  state.json initialized')
" 2>/dev/null

    # Write initial event
    emit_event "$feature_id" "pipeline_init" "PIPE" \
        "Pipeline initialized: ${feature_description} (tech_stack: ${tech_stack})"

    # Create README
    cat > "${feature_dir}/README.md" <<READMEEOF
# Pipeline: ${feature_id}

**Description**: ${feature_description}
**Tech Stack**: ${tech_stack}
**Created**: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

## Run

\`\`\`bash
# Full run
./ai-sdlc-claudecode/pipeline-executor.sh ${feature_id} "${feature_description}"

# Dry run
./ai-sdlc-claudecode/pipeline-executor.sh ${feature_id} "${feature_description}" --dry-run

# Resume from last checkpoint
./ai-sdlc-claudecode/pipeline-executor.sh ${feature_id} "${feature_description}" --resume

# Skip frontend (backend-only)
./ai-sdlc-claudecode/pipeline-executor.sh ${feature_id} "${feature_description}" --skip-stage S3b,S4c

# Status
./ai-sdlc-claudecode/pipeline-status.sh ${feature_id}
\`\`\`

## Stages

| ID | Stage | Status |
|----|-------|--------|
| S1 | Requirements | pending |
| S2 | Architecture | pending |
| S3 | Backend | pending |
| S3b | Frontend | pending |
| S4 | Unit Testing | pending |
| S4b | Integration Testing | pending |
| S4c | E2E Testing | pending |
| S5 | Code Review | pending |
| S6 | Deployment | pending |
| S7 | Monitoring | pending |
| S8 | Documentation | pending |
| S9 | Performance | pending |
| S10 | Release | pending |
READMEEOF

    echo -e "  ${GREEN}+${NC} README.md"

    # Show execution plan
    echo -e "\n${YELLOW}[4/4] Execution plan:${NC}"
    bash "${SCRIPT_DIR}/pipeline-executor.sh" "$feature_id" "$feature_description" --dry-run 2>&1 | grep -E '^\s+\d+\.' | head -20

    # Summary
    echo -e "\n${BOLD}${GREEN}Pipeline initialized successfully!${NC}"
    echo -e "  Feature:     ${feature_id}"
    echo -e "  Directory:   ${feature_dir}"
    echo -e "  Tech Stack:  ${tech_stack}"
    echo -e "  Stages:      $(echo "$stage_dirs" | wc -l | tr -d ' ')"
    echo -e "\n${CYAN}Next step:${NC}"
    echo -e "  ./ai-sdlc-claudecode/pipeline-executor.sh ${feature_id} \"${feature_description}\""
}

main "$@"
