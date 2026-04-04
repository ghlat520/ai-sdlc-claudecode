#!/usr/bin/env bash
# =============================================================================
# ai-review-checker.sh — AI-Powered Quality Gate Checker
#
# Performs semantic evaluation of stage outputs using claude --print.
# Three checker types:
#   1. PRD Checker (S1) — validates requirements completeness & clarity
#   2. Architecture Checker (S2) — validates design soundness
#   3. Code Quality Checker (S3-S5) — validates implementation quality
#
# Returns JSON with scores per dimension, overall pass/fail, and feedback.
#
# Usage:
#   ./ai-review-checker.sh <stage_id> <output_json_path> [--model <model>]
#
# Example:
#   ./ai-review-checker.sh S1 docs/pipeline/health-check/S1-requirements/output.json
#   ./ai-review-checker.sh S3 docs/pipeline/health-check/S3-backend/output.json --model haiku
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/events.sh
source "${SCRIPT_DIR}/lib/events.sh"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# --- Defaults ---
DEFAULT_MODEL="haiku"
PASS_THRESHOLD=70  # minimum score (0-100) to pass

usage() {
    cat <<EOF
Usage: $(basename "$0") <stage_id> <output_json_path> [options]

Arguments:
  stage_id            Stage to review (S1, S2, S3, S4, S5, S3b, S4b, S4c, S7-S10)
  output_json_path    Path to the stage output JSON file

Options:
  --model <model>     Claude model to use (default: ${DEFAULT_MODEL})
  --threshold <N>     Pass threshold 0-100 (default: ${PASS_THRESHOLD})
  --feature-id <id>   Feature ID for event logging
  --mock              Return synthetic scores (80/100) without calling Claude (for CI)
  --dry-run           Show prompt without calling Claude

Example:
  $(basename "$0") S1 docs/pipeline/health-check/S1-requirements/output.json
  $(basename "$0") S3 docs/pipeline/health-check/S3-backend/output.json --model sonnet
EOF
    exit 1
}

# --- Build review prompt based on stage type ---
build_review_prompt() {
    local stage_id="$1"
    local output_json="$2"

    local output_content
    output_content=$(cat "$output_json")

    local prompt=""

    case "$stage_id" in
        S1)
            prompt="You are a senior Product Manager reviewing a PRD (Product Requirements Document).

Evaluate the following PRD output on these dimensions (score each 0-100):

1. **completeness** — Are all required sections present? (FR, NFR, user stories, acceptance criteria)
2. **clarity** — Are requirements unambiguous and testable?
3. **consistency** — Do user stories align with FRs? Do ACs cover all FRs?
4. **feasibility** — Are requirements technically achievable within reasonable constraints?
5. **prioritization** — Are MoSCoW priorities assigned and reasonable?

PRD Output:
\`\`\`json
${output_content}
\`\`\`

Respond ONLY with a valid JSON object (no markdown, no explanation outside JSON):
{
  \"stage_id\": \"S1\",
  \"review_type\": \"prd\",
  \"scores\": {
    \"completeness\": <0-100>,
    \"clarity\": <0-100>,
    \"consistency\": <0-100>,
    \"feasibility\": <0-100>,
    \"prioritization\": <0-100>
  },
  \"overall_score\": <weighted average>,
  \"passed\": <true if overall >= ${PASS_THRESHOLD}>,
  \"issues\": [
    {\"severity\": \"critical|high|medium|low\", \"description\": \"...\", \"suggestion\": \"...\"}
  ],
  \"summary\": \"One-paragraph assessment\"
}"
            ;;

        S2)
            prompt="You are a senior Software Architect reviewing a system architecture design.

Evaluate the following architecture output on these dimensions (score each 0-100):

1. **nfr_coverage** — Does the design address all non-functional requirements?
2. **modularity** — Is the design modular with clear boundaries?
3. **api_design** — Are API contracts well-defined and RESTful?
4. **data_model** — Is the data model normalized and indexed properly?
5. **scalability** — Can this design handle 10x growth?
6. **breaking_changes** — Are breaking changes identified with migration plans?

Architecture Output:
\`\`\`json
${output_content}
\`\`\`

Respond ONLY with a valid JSON object (no markdown, no explanation outside JSON):
{
  \"stage_id\": \"S2\",
  \"review_type\": \"architecture\",
  \"scores\": {
    \"nfr_coverage\": <0-100>,
    \"modularity\": <0-100>,
    \"api_design\": <0-100>,
    \"data_model\": <0-100>,
    \"scalability\": <0-100>,
    \"breaking_changes\": <0-100>
  },
  \"overall_score\": <weighted average>,
  \"passed\": <true if overall >= ${PASS_THRESHOLD}>,
  \"issues\": [
    {\"severity\": \"critical|high|medium|low\", \"description\": \"...\", \"suggestion\": \"...\"}
  ],
  \"summary\": \"One-paragraph assessment\"
}"
            ;;

        S3|S3b|S4|S4b|S4c|S5)
            local review_focus=""
            case "$stage_id" in
                S3)  review_focus="backend implementation" ;;
                S3b) review_focus="frontend implementation" ;;
                S4)  review_focus="unit test coverage and quality" ;;
                S4b) review_focus="integration test coverage" ;;
                S4c) review_focus="end-to-end test coverage" ;;
                S5)  review_focus="code review findings and security audit" ;;
            esac

            # Load PRD (S1 output) as cross-reference baseline
            local prd_context=""
            local prd_dir
            prd_dir="$(dirname "$(dirname "$output_json")")"
            local prd_file="${prd_dir}/S1-requirements/output.json"
            if [[ -f "$prd_file" ]]; then
                prd_context="
## Requirements Specification (S1 PRD) — Cross-Reference Baseline
You MUST compare the implementation against this PRD to score requirements_conformance, defect_rate, and completion_deviation.
\`\`\`json
$(cat "$prd_file")
\`\`\`
"
            fi

            prompt="You are a senior engineer reviewing ${review_focus} output.
${prd_context}

Evaluate the following output on these dimensions (score each 0-100):

**A. Code Quality Dimensions (implementation quality)**
1. **correctness** — Does the implementation/test correctly address requirements?
2. **code_quality** — Clean code, proper naming, small functions, no deep nesting?
3. **security** — No hardcoded secrets, input validation, OWASP compliance?
4. **performance** — No obvious N+1 queries, proper indexing, efficient algorithms?
5. **immutability** — Immutable patterns used, no mutation of shared state?
6. **error_handling** — Comprehensive error handling, no swallowed exceptions?
7. **verification_evidence** — Does the output contain concrete verification evidence (command outputs, test results, coverage numbers)? No evidence = 0.
8. **methodology_compliance** — Did the agent follow the expected methodology? S3: code + tests written together? S4: TDD red-green-refactor? S5: two-phase review (code quality + security)? No methodology adherence = 0.

**B. Requirements Conformance Dimensions (PRD cross-reference)**
9. **requirements_conformance** — What percentage of PRD functional requirements are correctly implemented? Count each FR: fully implemented=100, partially=50, missing=0, then average. If no PRD available, score based on stated scope.
10. **defect_rate** — Inverse of potential defect density: 100 = no potential defects found, 0 = every requirement has a defect. Check: missing validation, wrong business logic, unhandled edge cases, incorrect API contracts vs PRD.
11. **completion_deviation** — How close is the implementation to the PRD scope? 100 = exact match, deduct for: missing features (-10 each), scope creep/extra features (-5 each), deviating API signatures (-10 each).

**C. Risk & Improvement**
12. **risk_score** — Overall production risk: 100 = no risk, 0 = critical risk. Consider: data loss scenarios, security vulnerabilities, performance cliffs, single points of failure.

Output:
\`\`\`json
${output_content}
\`\`\`

Respond ONLY with a valid JSON object (no markdown, no explanation outside JSON):
{
  \"stage_id\": \"${stage_id}\",
  \"review_type\": \"code_quality\",
  \"scores\": {
    \"correctness\": <0-100>,
    \"code_quality\": <0-100>,
    \"security\": <0-100>,
    \"performance\": <0-100>,
    \"immutability\": <0-100>,
    \"error_handling\": <0-100>,
    \"verification_evidence\": <0-100>,
    \"methodology_compliance\": <0-100>,
    \"requirements_conformance\": <0-100>,
    \"defect_rate\": <0-100>,
    \"completion_deviation\": <0-100>,
    \"risk_score\": <0-100>
  },
  \"overall_score\": <weighted average>,
  \"passed\": <true if overall >= ${PASS_THRESHOLD}>,
  \"requirements_detail\": {
    \"total_frs\": <number of FRs in PRD>,
    \"implemented\": <number fully implemented>,
    \"partial\": <number partially implemented>,
    \"missing\": <number missing>,
    \"extra\": <number of features not in PRD (scope creep)>
  },
  \"defects\": [
    {\"fr_id\": \"FR-X\", \"description\": \"...\", \"severity\": \"critical|high|medium|low\", \"type\": \"logic|validation|contract|edge_case\"}
  ],
  \"risks\": [
    {\"risk\": \"...\", \"likelihood\": \"high|medium|low\", \"impact\": \"high|medium|low\", \"mitigation\": \"...\"}
  ],
  \"improvements\": [
    {\"priority\": \"P0|P1|P2\", \"area\": \"...\", \"suggestion\": \"...\", \"effort\": \"small|medium|large\"}
  ],
  \"issues\": [
    {\"severity\": \"critical|high|medium|low\", \"description\": \"...\", \"suggestion\": \"...\"}
  ],
  \"summary\": \"One-paragraph assessment\"
}"
            ;;

        S6|S7|S8|S9|S10)
            prompt="You are a senior DevOps/SRE engineer reviewing stage ${stage_id} output.

Evaluate the following output on these dimensions (score each 0-100):

1. **completeness** — Are all required deliverables present?
2. **correctness** — Is the content technically accurate?
3. **actionability** — Can someone execute based on this output alone?
4. **risk_coverage** — Are risks, rollback plans, and failure modes addressed?

Output:
\`\`\`json
${output_content}
\`\`\`

Respond ONLY with a valid JSON object (no markdown, no explanation outside JSON):
{
  \"stage_id\": \"${stage_id}\",
  \"review_type\": \"ops_quality\",
  \"scores\": {
    \"completeness\": <0-100>,
    \"correctness\": <0-100>,
    \"actionability\": <0-100>,
    \"risk_coverage\": <0-100>
  },
  \"overall_score\": <weighted average>,
  \"passed\": <true if overall >= ${PASS_THRESHOLD}>,
  \"issues\": [
    {\"severity\": \"critical|high|medium|low\", \"description\": \"...\", \"suggestion\": \"...\"}
  ],
  \"summary\": \"One-paragraph assessment\"
}"
            ;;

        *)
            echo "ERROR: Unknown stage_id: ${stage_id}" >&2
            return 1
            ;;
    esac

    echo "$prompt"
}

# --- Parse AI review result ---
parse_review_result() {
    local result_text="$1"
    local output_path="$2"

    python3 -c "
import json, re, sys

text = sys.stdin.read()

# Extract JSON from response
patterns = [
    r'\`\`\`json\n(.*?)\n\`\`\`',
    r'(\{[^{}]*\"review_type\"[^}]*\"summary\"[^}]*\})',
    r'(\{.*\})'
]

for pattern in patterns:
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        for match in matches:
            try:
                data = json.loads(match)
                if 'scores' in data and 'overall_score' in data:
                    with open('${output_path}', 'w') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print(json.dumps(data, indent=2))
                    sys.exit(0)
            except json.JSONDecodeError:
                continue

print('ERROR: Could not parse AI review response', file=sys.stderr)
sys.exit(1)
" <<< "$result_text"
}

# --- Display review summary ---
display_review() {
    local review_json="$1"

    python3 -c "
import json, sys

with open('${review_json}') as f:
    data = json.load(f)

GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[0;33m'
CYAN = '\033[0;36m'
BOLD = '\033[1m'
NC = '\033[0m'

overall = data['overall_score']
passed = data['passed']

status_icon = f'{GREEN}PASS{NC}' if passed else f'{RED}FAIL{NC}'
print(f'\n  {BOLD}AI Review Result: {status_icon}{NC}')
print(f'  Overall Score: {overall}/100')
print()

# Scores — grouped by category
code_dims = ['correctness','code_quality','security','performance','immutability','error_handling','verification_evidence','methodology_compliance']
req_dims = ['requirements_conformance','defect_rate','completion_deviation']
risk_dims = ['risk_score']
scores = data.get('scores', {})

def print_scores(title, dims):
    subset = {k: v for k, v in scores.items() if k in dims}
    if not subset:
        return
    print(f'  {CYAN}{title}:{NC}')
    for dim, score in subset.items():
        bar_len = score // 5
        bar = '=' * bar_len + '-' * (20 - bar_len)
        color = GREEN if score >= 70 else (YELLOW if score >= 50 else RED)
        print(f'    {dim:28s} {color}{score:3d}{NC} [{bar}]')

print_scores('A. Code Quality', code_dims)
print_scores('B. Requirements Conformance', req_dims)
print_scores('C. Risk Assessment', risk_dims)

# Other dimensions not in known categories
other_dims = [k for k in scores if k not in code_dims + req_dims + risk_dims]
if other_dims:
    print_scores('Other', other_dims)

# Requirements detail
req_detail = data.get('requirements_detail', {})
if req_detail and req_detail.get('total_frs', 0) > 0:
    total = req_detail['total_frs']
    impl = req_detail.get('implemented', 0)
    partial = req_detail.get('partial', 0)
    missing = req_detail.get('missing', 0)
    extra = req_detail.get('extra', 0)
    print(f'\n  {CYAN}Requirements Coverage:{NC}')
    print(f'    Total FRs: {total}  |  Implemented: {GREEN}{impl}{NC}  |  Partial: {YELLOW}{partial}{NC}  |  Missing: {RED}{missing}{NC}  |  Scope creep: {YELLOW}{extra}{NC}')
    if total > 0:
        pct = (impl * 100 + partial * 50) // total
        print(f'    Conformance rate: {pct}%')

# Defects
defects = data.get('defects', [])
if defects:
    print(f'\n  {RED}Defects ({len(defects)}):{NC}')
    for d in defects:
        sev = d.get('severity', 'medium')
        sev_color = RED if sev in ('critical', 'high') else YELLOW
        print(f'    {sev_color}[{sev.upper()}]{NC} {d.get(\"fr_id\",\"\")} {d[\"description\"]} ({d.get(\"type\",\"\")})')

# Risks
risks = data.get('risks', [])
if risks:
    print(f'\n  {YELLOW}Risks ({len(risks)}):{NC}')
    for r in risks:
        lh = r.get('likelihood', '?')
        imp = r.get('impact', '?')
        color = RED if imp == 'high' else YELLOW
        print(f'    {color}[L:{lh}/I:{imp}]{NC} {r[\"risk\"]}')
        if r.get('mitigation'):
            print(f'           Mitigation: {r[\"mitigation\"]}')

# Improvements
improvements = data.get('improvements', [])
if improvements:
    print(f'\n  {CYAN}Improvements ({len(improvements)}):{NC}')
    for imp in improvements:
        pri = imp.get('priority', 'P2')
        pri_color = RED if pri == 'P0' else (YELLOW if pri == 'P1' else CYAN)
        print(f'    {pri_color}[{pri}]{NC} {imp.get(\"area\",\"\")}: {imp[\"suggestion\"]} ({imp.get(\"effort\",\"\")})')

# Issues (legacy format, still supported)
issues = data.get('issues', [])
if issues:
    print(f'\n  {YELLOW}Issues ({len(issues)}):{NC}')
    for issue in issues:
        sev = issue.get('severity', 'medium')
        sev_color = RED if sev in ('critical', 'high') else YELLOW
        print(f'    {sev_color}[{sev.upper()}]{NC} {issue[\"description\"]}')
        if issue.get('suggestion'):
            print(f'           Fix: {issue[\"suggestion\"]}')

# Summary
print(f'\n  {CYAN}Summary:{NC} {data.get(\"summary\", \"N/A\")}')
" 2>/dev/null
}

# --- Estimate diff lines from output JSON ---
estimate_diff_lines() {
    local output_json="$1"
    python3 -c "
import json, sys

try:
    with open('${output_json}') as f:
        data = json.load(f)

    # Count lines from files_changed, code blocks, or raw content
    total = 0
    # Check files_changed array
    for fc in data.get('files_changed', data.get('files', [])):
        if isinstance(fc, dict):
            total += fc.get('lines_added', 0) + fc.get('lines_removed', 0)
            # Fallback: count lines in content
            if total == 0 and 'content' in fc:
                total += len(str(fc['content']).splitlines())

    # Fallback: estimate from JSON size
    if total == 0:
        total = len(json.dumps(data)) // 80  # rough estimate: 80 chars per line

    print(total)
except Exception:
    print(0)
" 2>/dev/null
}

# --- Load adversarial config from DAG ---
get_adversarial_config() {
    local stage_id="$1"
    local dag_file="${SCRIPT_DIR}/pipeline-dag.json"

    if [[ ! -f "$dag_file" ]]; then
        echo ""
        return
    fi

    python3 -c "
import json, sys

with open('${dag_file}') as f:
    dag = json.load(f)

for stage_name, stage in dag.get('stages', {}).items():
    if stage.get('id') == '${stage_id}':
        adv = stage.get('gate', {}).get('adversarial', {})
        if adv.get('enabled', False):
            print(json.dumps(adv))
        else:
            print('')
        sys.exit(0)

print('')
" 2>/dev/null
}

# --- Build adversarial review prompt ---
build_adversarial_prompt() {
    local stage_id="$1"
    local output_json="$2"
    local focus="$3"

    local output_content
    output_content=$(cat "$output_json")

    # Load adversarial-review.md methodology if available
    local method_file="${SCRIPT_DIR}/prompts/methods/adversarial-review.md"
    local method_content=""
    if [[ -f "$method_file" ]]; then
        method_content=$(cat "$method_file")
    fi

    cat <<ADVERSARIAL_EOF
You are an ADVERSARIAL code reviewer. Your job is to BREAK this code — find every way it can fail in production.

${method_content}

## Your Focus for This Review
${focus}

## Code Output to Attack
\`\`\`json
${output_content}
\`\`\`

Respond ONLY with a valid JSON object (no markdown, no explanation outside JSON):
{
  "stage_id": "${stage_id}",
  "review_type": "adversarial",
  "scores": {
    "data_corruption_risk": <0-100, higher=safer>,
    "security_attack_surface": <0-100, higher=safer>,
    "race_condition_risk": <0-100, higher=safer>,
    "edge_case_coverage": <0-100, higher=safer>,
    "performance_cliff_risk": <0-100, higher=safer>
  },
  "overall_score": <weighted average>,
  "passed": <true if overall >= ${PASS_THRESHOLD}>,
  "findings": [
    {"severity": "CRITICAL|HIGH|MEDIUM|LOW", "what": "...", "how": "concrete trigger scenario", "impact": "...", "fix": "minimal code change"}
  ],
  "summary": "One-paragraph adversarial assessment"
}
ADVERSARIAL_EOF
}

# --- Run adversarial review (dual-pass: structural + adversarial) ---
run_adversarial_review() {
    local stage_id="$1"
    local output_json="$2"
    local structural_score="$3"
    local review_dir="$4"
    local feature_id="$5"

    # Load adversarial config from DAG
    local adv_config
    adv_config=$(get_adversarial_config "$stage_id")

    if [[ -z "$adv_config" ]]; then
        return 0  # No adversarial config, skip
    fi

    # Check diff line threshold
    local min_diff_lines
    min_diff_lines=$(python3 -c "import json; print(json.loads('${adv_config}').get('min_diff_lines', 200))" 2>/dev/null)
    local actual_diff_lines
    actual_diff_lines=$(estimate_diff_lines "$output_json")

    if [[ "$actual_diff_lines" -lt "$min_diff_lines" ]]; then
        echo -e "  ${YELLOW}Adversarial review skipped: ${actual_diff_lines} diff lines < ${min_diff_lines} threshold${NC}"
        return 0
    fi

    echo -e "\n  ${BOLD}${CYAN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "  ${BOLD}${CYAN}║  Adversarial Review: ${stage_id} (${actual_diff_lines} diff lines)${NC}"
    echo -e "  ${BOLD}${CYAN}╚══════════════════════════════════════════════╝${NC}"

    # Get adversarial pass config
    local adv_model adv_focus
    adv_model=$(python3 -c "
import json
config = json.loads('${adv_config}')
passes = config.get('passes', [])
for p in passes:
    if p.get('role') == 'adversarial':
        print(p.get('model', 'sonnet'))
        break
else:
    print('sonnet')
" 2>/dev/null)

    adv_focus=$(python3 -c "
import json
config = json.loads('${adv_config}')
passes = config.get('passes', [])
for p in passes:
    if p.get('role') == 'adversarial':
        print(p.get('focus', 'edge cases, race conditions, failure modes'))
        break
else:
    print('edge cases, race conditions, failure modes')
" 2>/dev/null)

    # Build adversarial prompt
    local adv_prompt
    adv_prompt=$(build_adversarial_prompt "$stage_id" "$output_json" "$adv_focus")

    # Call Claude with adversarial model
    echo -e "  ${YELLOW}Invoking Claude (${adv_model}) for adversarial review...${NC}"
    local adv_start
    adv_start=$(date +%s)

    local adv_output=""
    local adv_exit=0
    adv_output=$(claude --print --model "${adv_model}" "$adv_prompt" 2>&1) || adv_exit=$?

    local adv_end
    adv_end=$(date +%s)
    local adv_duration=$((adv_end - adv_start))

    if [[ $adv_exit -ne 0 ]]; then
        echo -e "  ${RED}Adversarial review invocation failed (exit: ${adv_exit})${NC}"
        echo -e "  ${YELLOW}Falling back to structural review score only${NC}"
        return 0  # Don't block on adversarial failure
    fi

    # Parse adversarial result
    local adv_review_file="${review_dir}/ai-review-adversarial-${stage_id}.json"
    if parse_review_result "$adv_output" "$adv_review_file" >/dev/null 2>&1; then
        echo -e "\n  ${BOLD}Adversarial Review Results:${NC}"
        display_review "$adv_review_file"

        # Merge scores: take minimum of structural and adversarial
        local adv_score
        adv_score=$(python3 -c "import json; print(json.load(open('${adv_review_file}'))['overall_score'])" 2>/dev/null)

        local final_score
        final_score=$(python3 -c "print(min(${structural_score}, ${adv_score}))" 2>/dev/null)
        local final_passed
        final_passed=$(python3 -c "print(${final_score} >= ${PASS_THRESHOLD})" 2>/dev/null)

        echo -e "\n  ${CYAN}Score Merge: structural=${structural_score}, adversarial=${adv_score} → final=${final_score} (min)${NC}"

        if [[ -n "$feature_id" ]]; then
            emit_event "$feature_id" "adversarial_review_done" "$stage_id" \
                "Adversarial review: structural=${structural_score}, adversarial=${adv_score}, final=${final_score}, duration=${adv_duration}s"
        fi

        # Return final score via stdout for caller to use
        echo "ADVERSARIAL_FINAL_SCORE=${final_score}"
        echo "ADVERSARIAL_FINAL_PASSED=${final_passed}"
        return 0
    else
        echo -e "  ${RED}Failed to parse adversarial review response${NC}"
        echo "$adv_output" > "${review_dir}/ai-review-adversarial-raw-${stage_id}.txt"
        echo -e "  ${YELLOW}Falling back to structural review score only${NC}"
        return 0
    fi
}

# --- Main ---
main() {
    local stage_id=""
    local output_json=""
    local model="$DEFAULT_MODEL"
    local threshold="$PASS_THRESHOLD"
    local feature_id=""
    local dry_run=false
    local mock_mode=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model) model="$2"; shift 2 ;;
            --threshold) threshold="$2"; shift 2 ;;
            --feature-id) feature_id="$2"; shift 2 ;;
            --mock) mock_mode=true; shift ;;
            --dry-run) dry_run=true; shift ;;
            --help|-h) usage ;;
            *)
                if [[ -z "$stage_id" ]]; then
                    stage_id="$1"
                elif [[ -z "$output_json" ]]; then
                    output_json="$1"
                fi
                shift ;;
        esac
    done

    if [[ -z "$stage_id" || -z "$output_json" ]]; then
        usage
    fi

    if [[ ! -f "$output_json" ]]; then
        echo -e "${RED}ERROR: Output file not found: ${output_json}${NC}"
        exit 1
    fi

    PASS_THRESHOLD="$threshold"

    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════╗${NC}"
    local display_model="$model"
    $mock_mode && display_model="MOCK"
    echo -e "${BOLD}${CYAN}║  AI Review: ${stage_id} (model: ${display_model})${NC}"
    echo -e "${BOLD}${CYAN}║  Threshold: ${threshold}/100${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${NC}"

    # Mock mode: return synthetic scores without calling Claude
    if $mock_mode; then
        local review_dir
        review_dir="$(dirname "$output_json")"
        local review_file="${review_dir}/ai-review-${stage_id}.json"

        python3 -c "
import json, sys
from datetime import datetime

stage_id = '${stage_id}'
threshold = int('${threshold}')

# Determine dimensions based on stage
if stage_id == 'S1':
    dims = {'completeness': 80, 'clarity': 82, 'consistency': 78, 'feasibility': 85, 'prioritization': 80}
    rtype = 'prd'
elif stage_id == 'S2':
    dims = {'nfr_coverage': 80, 'modularity': 82, 'api_design': 85, 'data_model': 78, 'scalability': 80, 'breaking_changes': 90}
    rtype = 'architecture'
elif stage_id in ('S7', 'S8', 'S9', 'S10'):
    dims = {'completeness': 80, 'correctness': 82, 'actionability': 78, 'risk_coverage': 80}
    rtype = 'ops_quality'
else:
    dims = {'correctness': 80, 'code_quality': 82, 'security': 78, 'performance': 80, 'immutability': 85, 'error_handling': 80, 'verification_evidence': 80, 'methodology_compliance': 80, 'requirements_conformance': 82, 'defect_rate': 85, 'completion_deviation': 80, 'risk_score': 78}
    rtype = 'code_quality'

overall = sum(dims.values()) // len(dims)
result = {
    'stage_id': stage_id,
    'review_type': rtype,
    'scores': dims,
    'overall_score': overall,
    'passed': overall >= threshold,
    'issues': [],
    'summary': f'[MOCK] Synthetic review for {stage_id}. All dimensions scored at ~80/100. No real AI analysis performed.'
}

with open('${review_file}', 'w') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print(json.dumps(result, indent=2))
" 2>/dev/null

        display_review "$review_file"
        echo -e "\n  ${YELLOW}[MOCK MODE] Synthetic scores returned without Claude API call${NC}"

        if [[ -n "$feature_id" ]]; then
            emit_event "$feature_id" "ai_review_done" "$stage_id" \
                "AI review complete (MOCK): score=80, passed=true"
        fi
        exit 0
    fi

    # Build prompt
    local prompt
    prompt=$(build_review_prompt "$stage_id" "$output_json")

    if $dry_run; then
        echo -e "\n${YELLOW}=== Dry Run: Review Prompt ===${NC}"
        echo "$prompt"
        echo -e "\n${GREEN}Dry run complete.${NC}"
        exit 0
    fi

    # Log event
    if [[ -n "$feature_id" ]]; then
        emit_event "$feature_id" "ai_review_start" "$stage_id" \
            "Starting AI review (model: ${model}, threshold: ${threshold})"
    fi

    # Pre-check: verify Claude CLI and model connectivity
    echo -e "  ${YELLOW}Checking Claude model (${model}) connectivity...${NC}"
    local precheck_exit=0
    local precheck_output=""
    precheck_output=$(timeout 30 claude --print --model "${model}" "Reply with exactly: OK" 2>&1) || precheck_exit=$?

    if [[ $precheck_exit -ne 0 ]] || ! echo "$precheck_output" | grep -qi "OK"; then
        echo -e "  ${RED}Model '${model}' is not reachable (exit: ${precheck_exit})${NC}"

        # Try fallback to sonnet
        if [[ "$model" != "sonnet" ]]; then
            echo -e "  ${YELLOW}Falling back to 'sonnet' model...${NC}"
            local fallback_exit=0
            timeout 30 claude --print --model "sonnet" "Reply with exactly: OK" >/dev/null 2>&1 || fallback_exit=$?
            if [[ $fallback_exit -eq 0 ]]; then
                echo -e "  ${GREEN}Fallback to 'sonnet' succeeded${NC}"
                model="sonnet"
            else
                echo -e "  ${RED}Fallback to 'sonnet' also failed. Cannot perform AI review.${NC}"
                if [[ -n "$feature_id" ]]; then
                    emit_event "$feature_id" "ai_review_fail" "$stage_id" \
                        "No Claude model reachable (tried ${model}, sonnet)"
                fi
                exit 1
            fi
        else
            echo -e "  ${RED}Cannot reach Claude. AI review unavailable.${NC}"
            if [[ -n "$feature_id" ]]; then
                emit_event "$feature_id" "ai_review_fail" "$stage_id" \
                    "Claude model '${model}' not reachable"
            fi
            exit 1
        fi
    else
        echo -e "  ${GREEN}Model '${model}' is reachable${NC}"
    fi

    # Call Claude
    echo -e "  ${YELLOW}Invoking Claude (${model}) for semantic review...${NC}"
    local start_time
    start_time=$(date +%s)

    local claude_output=""
    local claude_exit=0
    claude_output=$(claude --print --model "${model}" "$prompt" 2>&1) || claude_exit=$?

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [[ $claude_exit -ne 0 ]]; then
        echo -e "  ${RED}Claude invocation failed (exit: ${claude_exit})${NC}"
        if [[ -n "$feature_id" ]]; then
            emit_event "$feature_id" "ai_review_fail" "$stage_id" \
                "AI review failed (exit: ${claude_exit})"
        fi
        exit 1
    fi

    # Parse result
    local review_dir
    review_dir="$(dirname "$output_json")"
    local review_file="${review_dir}/ai-review-${stage_id}.json"

    if parse_review_result "$claude_output" "$review_file" >/dev/null 2>&1; then
        display_review "$review_file"

        # Check pass/fail
        local passed
        passed=$(python3 -c "import json; print(json.load(open('${review_file}'))['passed'])" 2>/dev/null)
        local overall_score
        overall_score=$(python3 -c "import json; print(json.load(open('${review_file}'))['overall_score'])" 2>/dev/null)

        if [[ -n "$feature_id" ]]; then
            emit_event "$feature_id" "ai_review_done" "$stage_id" \
                "AI review complete: score=${overall_score}, passed=${passed}, duration=${duration}s" \
                "{\"score\": ${overall_score}, \"passed\": ${passed}, \"duration\": ${duration}}"
        fi

        if [[ "$passed" == "True" ]]; then
            # Structural review passed — check if adversarial review is needed
            local adv_result
            adv_result=$(run_adversarial_review "$stage_id" "$output_json" "$overall_score" "$review_dir" "$feature_id" 2>&1)
            local adv_exit=$?

            # Check if adversarial review produced a final score
            local adv_final_score
            adv_final_score=$(echo "$adv_result" | grep "^ADVERSARIAL_FINAL_SCORE=" | cut -d= -f2)
            local adv_final_passed
            adv_final_passed=$(echo "$adv_result" | grep "^ADVERSARIAL_FINAL_PASSED=" | cut -d= -f2)

            # Print adversarial output (excluding control lines)
            echo "$adv_result" | grep -v "^ADVERSARIAL_FINAL_"

            if [[ -n "$adv_final_score" ]]; then
                # Adversarial review ran — use merged score
                if [[ "$adv_final_passed" == "True" ]]; then
                    echo -e "\n  ${GREEN}AI Review Gate: PASSED (merged ${adv_final_score}/100 >= ${threshold})${NC}"
                    exit 0
                else
                    echo -e "\n  ${RED}AI Review Gate: FAILED (merged ${adv_final_score}/100 < ${threshold})${NC}"
                    exit 1
                fi
            else
                # No adversarial review — use structural score
                echo -e "\n  ${GREEN}AI Review Gate: PASSED (${overall_score}/100 >= ${threshold})${NC}"
                exit 0
            fi
        else
            echo -e "\n  ${RED}AI Review Gate: FAILED (${overall_score}/100 < ${threshold})${NC}"
            exit 1
        fi
    else
        echo -e "  ${RED}Failed to parse AI review response${NC}"
        echo "$claude_output" > "${review_dir}/ai-review-raw-${stage_id}.txt"
        echo -e "  ${YELLOW}Raw response saved to: ${review_dir}/ai-review-raw-${stage_id}.txt${NC}"

        if [[ -n "$feature_id" ]]; then
            emit_event "$feature_id" "ai_review_fail" "$stage_id" \
                "Failed to parse AI review response"
        fi
        exit 1
    fi
}

main "$@"
