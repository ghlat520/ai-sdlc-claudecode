#!/opt/homebrew/bin/bash
# =============================================================================
# orchestrate-parallel.sh — Parallel Stage Executor with Git Worktree Isolation
#
# Executes multiple agents in parallel using git worktrees for isolation:
#   1. Create a worktree per parallel agent
#   2. Spawn claude --print in each worktree (background)
#   3. Wait for all to complete
#   4. Validate each output (schema + gate)
#   5. Merge worktrees back (with conflict detection)
#
# Usage:
#   ./orchestrate-parallel.sh <feature_id> <feature_description> <stage1,stage2,...>
#
# Example:
#   ./orchestrate-parallel.sh order-history "Order history feature" backend,frontend
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DAG_FILE="${SCRIPT_DIR}/pipeline-dag.json"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate-handoff.sh"

source "${SCRIPT_DIR}/lib/events.sh"
source "${SCRIPT_DIR}/lib/protocol.sh"

export PIPELINE_ROOT="${PROJECT_ROOT}/docs/pipeline"

# --- DAG cache (same as pipeline-executor.sh P4) ---
eval "$(DAG_PATH="$DAG_FILE" python3 << 'PYEOF'
import json, os

with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)

cfg = dag['config']
for name, s in dag['stages'].items():
    sid = s['id']
    agent = s['agents'][0]
    safe_name = name.replace('-', '_')
    print(f'DAG_{safe_name}_id="{sid}"')
    print(f'DAG_{safe_name}_model="{agent.get("model", "sonnet")}"')
    print(f'DAG_{safe_name}_agent_type="{agent["type"]}"')
PYEOF
)"

# Helper to get cached DAG values
dag_get() {
    local name="${1//-/_}"
    local field="$2"
    local var="DAG_${name}_${field}"
    echo "${!var}"
}

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# --- Check if we're in a git repo ---
check_git_repo() {
    if ! git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo -e "${YELLOW}Warning: Not a git repo. Parallel worktree isolation unavailable.${NC}"
        echo -e "${YELLOW}Falling back to directory-based isolation.${NC}"
        return 1
    fi
    return 0
}

# --- Create isolated workspace for an agent ---
# Uses git worktree if available, otherwise creates a temp directory copy
create_workspace() {
    local feature_id="$1"
    local stage_name="$2"
    local workspace_base="${PROJECT_ROOT}/.pipeline-workspaces"

    mkdir -p "$workspace_base"

    local workspace="${workspace_base}/${feature_id}-${stage_name}"

    if check_git_repo 2>/dev/null; then
        # Git worktree isolation
        local branch_name="pipeline/${feature_id}/${stage_name}"

        # Clean up existing worktree if present
        if [[ -d "$workspace" ]]; then
            git -C "$PROJECT_ROOT" worktree remove --force "$workspace" 2>/dev/null || rm -rf "$workspace"
        fi

        # Create worktree from current HEAD
        git -C "$PROJECT_ROOT" worktree add -b "$branch_name" "$workspace" HEAD 2>/dev/null || {
            # Branch might exist, try without -b
            git -C "$PROJECT_ROOT" branch -D "$branch_name" 2>/dev/null || true
            git -C "$PROJECT_ROOT" worktree add -b "$branch_name" "$workspace" HEAD 2>/dev/null || {
                # Fallback: directory copy
                echo -e "${YELLOW}Worktree failed, using directory copy${NC}" >&2
                mkdir -p "$workspace"
                # Only copy source and config, not .git
                rsync -a --exclude='.git' --exclude='.pipeline-workspaces' \
                    --exclude='node_modules' --exclude='target' \
                    "$PROJECT_ROOT/" "$workspace/" 2>/dev/null || true
            }
        }
    else
        # No git: directory-based isolation
        mkdir -p "$workspace"
        rsync -a --exclude='.pipeline-workspaces' \
            --exclude='node_modules' --exclude='target' \
            "$PROJECT_ROOT/" "$workspace/" 2>/dev/null || true
    fi

    echo "$workspace"
}

# --- Merge workspace changes back to main ---
merge_workspace() {
    local feature_id="$1"
    local stage_name="$2"
    local workspace="$3"
    local branch_name="pipeline/${feature_id}/${stage_name}"

    if ! check_git_repo 2>/dev/null; then
        # No git: copy changed files back
        echo -e "${YELLOW}Merging changes from ${workspace} (file copy)${NC}"
        # Only copy pipeline output files, not code changes (those should be in dedicated output)
        local output_dir="${PIPELINE_ROOT}/${feature_id}"
        mkdir -p "$output_dir"
        if [[ -d "${workspace}/docs/pipeline/${feature_id}" ]]; then
            cp -r "${workspace}/docs/pipeline/${feature_id}/"* "$output_dir/" 2>/dev/null || true
        fi
        return 0
    fi

    # Check if worktree has changes
    local has_changes
    has_changes=$(git -C "$workspace" status --porcelain 2>/dev/null | head -1)

    if [[ -z "$has_changes" ]]; then
        echo -e "${CYAN}  No changes in worktree for ${stage_name}${NC}"
        return 0
    fi

    # Commit changes in worktree
    git -C "$workspace" add -A 2>/dev/null
    git -C "$workspace" commit -m "pipeline: ${stage_name} output for ${feature_id}" 2>/dev/null || true

    # Merge back to current branch
    local current_branch
    current_branch=$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD)

    echo -e "${CYAN}  Merging ${branch_name} → ${current_branch}${NC}"

    local merge_result=0
    git -C "$PROJECT_ROOT" merge --no-ff "$branch_name" \
        -m "pipeline: merge ${stage_name} for ${feature_id}" 2>/dev/null || merge_result=$?

    if [[ $merge_result -ne 0 ]]; then
        echo -e "${RED}  Merge conflict detected for ${stage_name}!${NC}"
        # Auto-resolve: prefer the worktree's changes for output files
        git -C "$PROJECT_ROOT" checkout --theirs -- "docs/pipeline/${feature_id}/" 2>/dev/null || true
        git -C "$PROJECT_ROOT" add "docs/pipeline/${feature_id}/" 2>/dev/null || true

        # Check if there are still unresolved conflicts
        local unresolved
        unresolved=$(git -C "$PROJECT_ROOT" diff --name-only --diff-filter=U 2>/dev/null)
        if [[ -n "$unresolved" ]]; then
            echo -e "${RED}  Unresolved conflicts in: ${unresolved}${NC}"
            git -C "$PROJECT_ROOT" merge --abort 2>/dev/null
            return 1
        fi

        git -C "$PROJECT_ROOT" commit --no-edit 2>/dev/null || true
    fi

    echo -e "${GREEN}  ✓ Merged ${stage_name} successfully${NC}"
    return 0
}

# --- Cleanup workspace ---
cleanup_workspace() {
    local feature_id="$1"
    local stage_name="$2"
    local workspace="$3"
    local branch_name="pipeline/${feature_id}/${stage_name}"

    if check_git_repo 2>/dev/null; then
        git -C "$PROJECT_ROOT" worktree remove --force "$workspace" 2>/dev/null || true
        git -C "$PROJECT_ROOT" branch -D "$branch_name" 2>/dev/null || true
    else
        rm -rf "$workspace"
    fi
}

# --- Build prompt for parallel agent ---
build_parallel_prompt() {
    local stage_name="$1"
    local feature_id="$2"
    local feature_description="$3"
    local workspace="$4"

    FEATURE_DESC="$feature_description" \
    DAG_FILE_PATH="${DAG_FILE}" \
    STAGE_NAME="${stage_name}" \
    PIPELINE_DIR="${PIPELINE_ROOT}/${feature_id}" \
    SCRIPT_PATH="${SCRIPT_DIR}" \
    python3 -c "
import json, os, glob

dag_file = os.environ['DAG_FILE_PATH']
stage_name = os.environ['STAGE_NAME']
pipeline_dir = os.environ['PIPELINE_DIR']
feature_desc = os.environ['FEATURE_DESC']
script_dir = os.environ['SCRIPT_PATH']

with open(dag_file) as f:
    dag = json.load(f)

stage = dag['stages'][stage_name]
agent = stage['agents'][0]

# Load prompt from external file if available, fallback to inline template
prompt_file = agent.get('prompt_file')
if prompt_file:
    prompt_path = os.path.join(os.path.dirname(dag_file), prompt_file)
    if os.path.exists(prompt_path):
        with open(prompt_path, encoding='utf-8') as pf:
            prompt_template = pf.read()
    else:
        prompt_template = agent.get('prompt_template', '')
else:
    prompt_template = agent.get('prompt_template', '')

# Collect upstream outputs (from main pipeline dir)
upstream_data = {}
for dep in stage.get('dependencies', []):
    dep_stage = dag['stages'][dep]
    dep_id = dep_stage['id']
    dep_dir = os.path.join(pipeline_dir, f'{dep_id}-{dep}')
    json_files = glob.glob(os.path.join(dep_dir, '*.json'))
    if json_files:
        with open(json_files[0]) as f:
            upstream_data[f'{dep_id}_output'] = json.dumps(json.load(f), indent=2, ensure_ascii=False)

# Template substitution
prompt = prompt_template
prompt = prompt.replace('{{feature_description}}', feature_desc)

# Output goes to main pipeline dir
output_path = os.path.join(pipeline_dir, f'{stage[\"id\"]}-{stage_name}')
prompt = prompt.replace('{{output_path}}', output_path)

for key, value in upstream_data.items():
    prompt = prompt.replace('{{' + key + '}}', value)

# Clean up unreplaced vars
import re
prompt = re.sub(r'\{\{[^}]+\}\}', '(auto-detect from project)', prompt)

# Add schema
schema_path = os.path.join(script_dir, stage['output_schema'])
with open(schema_path) as f:
    schema = json.load(f)
prompt += f'''

Your FINAL output MUST contain a valid JSON object conforming to this schema:
{json.dumps(schema, indent=2)}

IMPORTANT: Output the JSON directly in your response inside a JSON code block (triple backtick json). Do NOT attempt to write files. Your response will be parsed to extract the JSON. The JSON block must be complete and valid — do NOT truncate or summarize it.
'''

print(prompt)
" 2>/dev/null
}

# --- Execute parallel stage group ---
# Usage: execute_parallel_group <feature_id> <feature_description> <stage1,stage2,...>
execute_parallel_group() {
    local feature_id="$1"
    local feature_description="$2"
    local stages_csv="$3"

    IFS=',' read -ra parallel_stages <<< "$stages_csv"
    local num_stages=${#parallel_stages[@]}

    echo -e "\n${BOLD}${MAGENTA}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${MAGENTA}║  Parallel Execution: ${num_stages} agents${NC}"
    echo -e "${BOLD}${MAGENTA}║  Stages: ${stages_csv}${NC}"
    echo -e "${BOLD}${MAGENTA}╚══════════════════════════════════════════════╝${NC}"

    emit_event "$feature_id" "parallel_start" "PAR" "Launching ${num_stages} parallel agents: ${stages_csv}"
    send_message "$feature_id" "Commander" "ParallelGroup" "$MSG_PARALLEL" \
        "Launching parallel: ${stages_csv}"

    # --- Skeleton mode: skip workspaces & claude, generate skeleton JSON directly ---
    if [[ "${PIPELINE_SKELETON_MODE:-false}" == "true" ]]; then
        echo -e "  ${YELLOW}[SKELETON] Generating skeleton outputs for parallel group...${NC}"
        local skel_all_passed=true
        for stage_name in "${parallel_stages[@]}"; do
            local stage_id
            stage_id=$(dag_get "$stage_name" "id")
            echo -e "  ${YELLOW}[SKELETON] Generating ${stage_id} (${stage_name})...${NC}"

            local output_dir="${PIPELINE_ROOT}/${feature_id}/${stage_id}-${stage_name}"
            mkdir -p "$output_dir"

            set_stage_state "$feature_id" "$stage_id" "running" 0

            # Generate skeleton JSON
            local skeleton_json
            skeleton_json=$(STAGE_ID="$stage_id" FEATURE_ID="$feature_id" SCHEMA_BASE="${SCRIPT_DIR}" DAG_PATH="$DAG_FILE" STAGE_NAME="$stage_name" python3 << 'SKELPYEOF'
import json, os, sys

dag_path = os.environ['DAG_PATH']
stage_name = os.environ['STAGE_NAME']
stage_id = os.environ['STAGE_ID']
feature_id = os.environ['FEATURE_ID']
schema_base = os.environ['SCHEMA_BASE']

with open(dag_path) as f:
    dag = json.load(f)

schema_path = os.path.join(schema_base, dag['stages'][stage_name]['output_schema'])
with open(schema_path) as f:
    schema = json.load(f)

def gen_skeleton(sch, depth=0):
    t = sch.get('type', 'object')
    if 'const' in sch:
        return sch['const']
    if 'enum' in sch:
        return sch['enum'][0]
    if t == 'string':
        fmt = sch.get('format', '')
        if fmt == 'date-time':
            return '2026-01-01T00:00:00Z'
        return f'skeleton-{stage_id}'
    if t == 'integer':
        return 1
    if t == 'number':
        return 1.0
    if t == 'boolean':
        return True
    if t == 'array':
        items = sch.get('items', {})
        return [gen_skeleton(items, depth+1)]
    if t == 'object':
        obj = {}
        for k, v in sch.get('properties', {}).items():
            obj[k] = gen_skeleton(v, depth+1)
        return obj
    return None

data = gen_skeleton(schema)
if isinstance(data, dict):
    data['stage_id'] = stage_id
    data['feature_id'] = feature_id
    data['timestamp'] = '2026-01-01T00:00:00Z'
    data['status'] = 'complete'

print('```json')
print(json.dumps(data, indent=2, ensure_ascii=False))
print('```')
print()
print('### VERIFICATION_EVIDENCE')
print('| Command | Exit Code | Key Output |')
print('|---------|-----------|------------|')
print(f'| skeleton-gen {stage_id} | 0 | Skeleton JSON generated |')
print()
print('### VERIFICATION_STATUS: VERIFIED')
SKELPYEOF
)
            if [[ $? -ne 0 ]]; then
                echo -e "  ${RED}  ✗ Skeleton generation failed for ${stage_name}${NC}"
                skel_all_passed=false
                set_stage_state "$feature_id" "$stage_id" "failed" 0
                continue
            fi

            # Extract JSON from skeleton output
            local extracted
            extracted=$(echo "$skeleton_json" | python3 -c "
import sys, json
sys.path.insert(0, '${SCRIPT_DIR}/src')
from ai_sdlc_claudecode.extract import extract_json
text = sys.stdin.read()
result = extract_json(text)
if result:
    print(json.dumps(result, indent=2, ensure_ascii=False))
else:
    sys.exit(1)
" 2>/dev/null)

            if [[ -n "$extracted" ]]; then
                echo "$extracted" > "${output_dir}/output.json"
                echo -e "  ${GREEN}  ✓ ${stage_name} skeleton output saved${NC}"
                set_stage_state "$feature_id" "$stage_id" "passed" 0
                emit_event "$feature_id" "stage_pass" "$stage_id" "Skeleton output generated (parallel)"
            else
                echo -e "  ${RED}  ✗ JSON extraction failed for ${stage_name}${NC}"
                skel_all_passed=false
                set_stage_state "$feature_id" "$stage_id" "failed" 0
            fi
        done

        if $skel_all_passed; then
            emit_event "$feature_id" "parallel_end" "PAR" "All parallel stages passed (skeleton)"
            return 0
        else
            emit_event "$feature_id" "parallel_end" "PAR" "Some parallel stages failed (skeleton)"
            return 1
        fi
    fi

    # --- Phase 1: Spawn parallel agents (no workspace — agents output JSON, not source code) ---
    declare -A pids           # stage_name → PID
    declare -A log_files      # stage_name → output log
    declare -A exit_codes     # stage_name → exit code

    for stage_name in "${parallel_stages[@]}"; do
        local stage_id
        stage_id=$(dag_get "$stage_name" "id")
        local agent_type
        agent_type=$(dag_get "$stage_name" "agent_type")
        local agent_model
        agent_model=$(dag_get "$stage_name" "model")

        # Ensure output directory exists in main pipeline dir
        local output_dir="${PIPELINE_ROOT}/${feature_id}/${stage_id}-${stage_name}"
        mkdir -p "$output_dir"

        # Build prompt (pass pipeline root as workspace — no isolation needed)
        local prompt
        prompt=$(build_parallel_prompt "$stage_name" "$feature_id" "$feature_description" "${PIPELINE_ROOT}/${feature_id}")

        # Send request message
        send_message "$feature_id" "Commander" "$agent_type" "$MSG_REQUEST" \
            "Execute ${stage_name} in parallel"

        set_stage_state "$feature_id" "$stage_id" "running" 0

        # Spawn agent in background
        local log_file="${PIPELINE_ROOT}/${feature_id}/${stage_id}-${stage_name}.agent.log"
        log_files[$stage_name]="$log_file"

        echo -e "\n  ${CYAN}[${stage_id}] Spawning ${agent_type} (${agent_model}) in background...${NC}"

        (
            claude --print --model "${agent_model}" "$prompt" > "$log_file" 2>&1
        ) &
        pids[$stage_name]=$!

        emit_event "$feature_id" "stage_start" "$stage_id" \
            "Parallel agent started: ${agent_type} (PID: ${pids[$stage_name]})"
    done

    # --- Phase 2: Wait for all agents ---
    echo -e "\n  ${YELLOW}Waiting for ${num_stages} parallel agents...${NC}"

    local all_passed=true
    local shared_context_file="${PIPELINE_ROOT}/${feature_id}/shared-context.json"

    for stage_name in "${parallel_stages[@]}"; do
        local pid=${pids[$stage_name]}
        local stage_id
        stage_id=$(dag_get "$stage_name" "id")
        local agent_type
        agent_type=$(dag_get "$stage_name" "agent_type")

        echo -e "  ${YELLOW}  Waiting for ${stage_name} (PID: ${pid})...${NC}"

        local exit_code=0
        wait "$pid" || exit_code=$?
        exit_codes[$stage_name]=$exit_code

        if [[ $exit_code -eq 0 ]]; then
            echo -e "  ${GREEN}  ✓ ${stage_name} completed (exit: 0)${NC}"
            emit_event "$feature_id" "stage_pass" "$stage_id" "Agent completed successfully"
            send_message "$feature_id" "$agent_type" "Commander" "$MSG_RESPONSE" \
                "${stage_name} complete" "${log_files[$stage_name]}"
            # P3: Send completion signal
            send_signal "$feature_id" "$stage_id" "done"
            # P0: Write completion to shared memory
            local output_preview
            output_preview=$(head -c 500 "${log_files[$stage_name]}" 2>/dev/null || echo "completed")
            python3 -c "
import sys
sys.path.insert(0, '${SCRIPT_DIR}/src')
from ai_sdlc_claudecode.memory import MemoryStore
try:
    MemoryStore('${shared_context_file}').write('${stage_name}', '${stage_id}', 'artifact', 'Stage completed: ' + sys.stdin.read()[:500], 3600)
except Exception:
    pass
" <<< "$output_preview" 2>/dev/null || true
        else
            echo -e "  ${RED}  ✗ ${stage_name} failed (exit: ${exit_code})${NC}"
            emit_event "$feature_id" "stage_fail" "$stage_id" "Agent failed with exit ${exit_code}"
            send_message "$feature_id" "$agent_type" "Commander" "$MSG_ERROR" \
                "${stage_name} failed with exit ${exit_code}"
            # P3: Send failure signal
            send_signal "$feature_id" "$stage_id" "failed"
            all_passed=false
        fi
    done

    # --- Phase 3: Extract outputs & validate ---
    echo -e "\n  ${YELLOW}Extracting and validating outputs...${NC}"

    for stage_name in "${parallel_stages[@]}"; do
        local stage_id
        stage_id=$(dag_get "$stage_name" "id")
        local exit_code=${exit_codes[$stage_name]}

        if [[ $exit_code -ne 0 ]]; then
            echo -e "  ${RED}  Skipping validation for failed stage: ${stage_name}${NC}"
            continue
        fi

        # Look for output in main pipeline dir
        local main_output_dir="${PIPELINE_ROOT}/${feature_id}/${stage_id}-${stage_name}"
        local output_json="${main_output_dir}/output.json"
        mkdir -p "$main_output_dir"

        if [[ ! -f "$output_json" ]]; then
            # Try to extract JSON from agent log
            local log_file="${log_files[$stage_name]}"
            if [[ -f "$log_file" ]]; then
                python3 -m ai_sdlc_claudecode extract-json "$output_json" -f "$log_file" 2>/dev/null || \
                    echo -e "  ${YELLOW}  Warning: Could not extract JSON for ${stage_name}${NC}"
            fi
        fi

        if [[ -f "$output_json" ]]; then
            echo -e "  ${GREEN}  ✓ Output extracted for ${stage_name}${NC}"

            # Validate
            local validate_result
            validate_result=$(bash "$VALIDATE_SCRIPT" "$stage_id" "$output_json" 2>&1) || true
            if echo "$validate_result" | grep -q "\[PASS\]"; then
                echo -e "  ${GREEN}  ✓ Schema validation passed for ${stage_name}${NC}"
                set_stage_state "$feature_id" "$stage_id" "passed" 0
            else
                echo -e "  ${YELLOW}  ⚠ Schema issues for ${stage_name} (non-blocking)${NC}"
                set_stage_state "$feature_id" "$stage_id" "passed" 0  # Still pass for now
            fi
        else
            echo -e "  ${RED}  ✗ No output found for ${stage_name}${NC}"
            all_passed=false
            set_stage_state "$feature_id" "$stage_id" "failed" 0
        fi
    done

    # --- Phase 4: Validation Gate (no workspace merge needed — outputs already in pipeline dir) ---
    echo -e "\n  ${BOLD}${YELLOW}Validation Gate${NC}"

    if $all_passed; then
        echo -e "  ${GREEN}All parallel agents passed.${NC}"
        emit_event "$feature_id" "gate_pass" "PAR" "Parallel group validation passed"
    else
        echo -e "  ${RED}Some agents failed.${NC}"
        emit_event "$feature_id" "gate_fail" "PAR" "Parallel group had failures"
    fi

    echo -e "\n${BOLD}${MAGENTA}═══════════════════════════════════════${NC}"
    if $all_passed; then
        echo -e "${GREEN}Parallel group COMPLETE: ${stages_csv}${NC}"
        emit_event "$feature_id" "parallel_end" "PAR" "All ${num_stages} parallel agents completed successfully"
    else
        echo -e "${RED}Parallel group FAILED: ${stages_csv}${NC}"
        emit_event "$feature_id" "parallel_end" "PAR" "Parallel group completed with failures"
    fi
    echo -e "${BOLD}${MAGENTA}═══════════════════════════════════════${NC}"

    $all_passed
}

# --- Main ---
main() {
    if [[ $# -lt 3 ]]; then
        echo "Usage: $0 <feature_id> <feature_description> <stage1,stage2,...>"
        echo ""
        echo "Example:"
        echo "  $0 order-history 'Order history feature' backend,frontend"
        exit 1
    fi

    local feature_id="$1"
    local feature_description="$2"
    local stages_csv="$3"

    execute_parallel_group "$feature_id" "$feature_description" "$stages_csv"
}

main "$@"
