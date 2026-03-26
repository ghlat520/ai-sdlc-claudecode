#!/usr/bin/env bash
# =============================================================================
# validate-handoff.sh — Stage output schema validator
# Validates that a stage's output JSON conforms to its StageOutput schema.
# Uses Python's jsonschema for validation (pip install jsonschema).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMAS_DIR="${SCRIPT_DIR}/schemas"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    echo "Usage: $0 <stage_id> <output_json_path>"
    echo ""
    echo "Arguments:"
    echo "  stage_id          Stage identifier (S1-S6)"
    echo "  output_json_path  Path to the stage output JSON file"
    echo ""
    echo "Example:"
    echo "  $0 S1 docs/pipeline/health-check/S1-requirements/requirements.json"
    exit 1
}

# --- Map stage ID to schema file ---
get_schema_path() {
    local stage_id="$1"
    case "$stage_id" in
        S1)  echo "${SCHEMAS_DIR}/requirements-output.json" ;;
        S2)  echo "${SCHEMAS_DIR}/architecture-output.json" ;;
        S3)  echo "${SCHEMAS_DIR}/backend-output.json" ;;
        S3b) echo "${SCHEMAS_DIR}/frontend-output.json" ;;
        S4)  echo "${SCHEMAS_DIR}/testing-output.json" ;;
        S4b) echo "${SCHEMAS_DIR}/integration-test-output.json" ;;
        S4c) echo "${SCHEMAS_DIR}/e2e-test-output.json" ;;
        S5)  echo "${SCHEMAS_DIR}/review-output.json" ;;
        S6)  echo "${SCHEMAS_DIR}/deployment-output.json" ;;
        S7)  echo "${SCHEMAS_DIR}/monitoring-output.json" ;;
        S8)  echo "${SCHEMAS_DIR}/documentation-output.json" ;;
        S9)  echo "${SCHEMAS_DIR}/performance-output.json" ;;
        S10) echo "${SCHEMAS_DIR}/release-output.json" ;;
        *)   echo ""; return 1 ;;
    esac
}

# --- Validate JSON syntax ---
validate_json_syntax() {
    local json_path="$1"
    if ! python3 -c "import json; json.load(open('${json_path}'))" 2>/dev/null; then
        echo -e "${RED}[FAIL]${NC} Invalid JSON syntax in: ${json_path}"
        return 1
    fi
    return 0
}

# --- Validate against schema ---
validate_schema() {
    local schema_path="$1"
    local json_path="$2"

    python3 -c "
import json
import sys

try:
    from jsonschema import validate, ValidationError, Draft202012Validator
except ImportError:
    print('ERROR: jsonschema not installed. Run: pip install jsonschema')
    sys.exit(2)

with open('${schema_path}') as f:
    schema = json.load(f)
with open('${json_path}') as f:
    data = json.load(f)

validator = Draft202012Validator(schema)
errors = list(validator.iter_errors(data))

if errors:
    print(f'VALIDATION FAILED: {len(errors)} error(s)')
    for i, err in enumerate(errors, 1):
        path = ' -> '.join(str(p) for p in err.absolute_path) if err.absolute_path else '(root)'
        print(f'  [{i}] {path}: {err.message}')
    sys.exit(1)
else:
    print('VALIDATION PASSED')
    sys.exit(0)
"
}

# --- Check required fields for specific stage gates ---
check_gate_requirements() {
    local stage_id="$1"
    local json_path="$2"
    local failed=0

    case "$stage_id" in
        S1)
            # PRD completeness checks
            local fr_count
            fr_count=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(len(d.get('prd', {}).get('functional_requirements', [])))
" 2>/dev/null || echo "0")
            local nfr_count
            nfr_count=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(len(d.get('prd', {}).get('non_functional_requirements', [])))
" 2>/dev/null || echo "0")
            local us_count
            us_count=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(len(d.get('prd', {}).get('user_stories', [])))
" 2>/dev/null || echo "0")
            local ac_count
            ac_count=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(len(d.get('prd', {}).get('acceptance_criteria', [])))
" 2>/dev/null || echo "0")

            echo -e "  Gate checks:"
            [[ "$fr_count" -gt 0 ]] && echo -e "    ${GREEN}✓${NC} prd_has_functional_requirements ($fr_count)" || { echo -e "    ${RED}✗${NC} prd_has_functional_requirements"; ((failed++)); }
            [[ "$nfr_count" -gt 0 ]] && echo -e "    ${GREEN}✓${NC} prd_has_non_functional_requirements ($nfr_count)" || { echo -e "    ${RED}✗${NC} prd_has_non_functional_requirements"; ((failed++)); }
            [[ "$us_count" -gt 0 ]] && echo -e "    ${GREEN}✓${NC} prd_has_user_stories ($us_count)" || { echo -e "    ${RED}✗${NC} prd_has_user_stories"; ((failed++)); }
            [[ "$ac_count" -gt 0 ]] && echo -e "    ${GREEN}✓${NC} prd_has_acceptance_criteria ($ac_count)" || { echo -e "    ${RED}✗${NC} prd_has_acceptance_criteria"; ((failed++)); }
            ;;
        S3)
            # Compile check
            local compile_ok
            compile_ok=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('implementation', {}).get('compile_result', {}).get('success', False))
" 2>/dev/null || echo "False")

            echo -e "  Gate checks:"
            [[ "$compile_ok" == "True" ]] && echo -e "    ${GREEN}✓${NC} mvn_compile_passes" || { echo -e "    ${RED}✗${NC} mvn_compile_passes"; ((failed++)); }
            ;;
        S4)
            # Test results check
            local test_failed
            test_failed=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('testing', {}).get('test_results', {}).get('failed', -1))
" 2>/dev/null || echo "-1")
            local coverage
            coverage=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('testing', {}).get('coverage', {}).get('line_percent', 0))
" 2>/dev/null || echo "0")

            echo -e "  Gate checks:"
            [[ "$test_failed" == "0" ]] && echo -e "    ${GREEN}✓${NC} all_tests_pass" || { echo -e "    ${RED}✗${NC} all_tests_pass (${test_failed} failed)"; ((failed++)); }
            python3 -c "exit(0 if float('${coverage}') >= 80 else 1)" 2>/dev/null && echo -e "    ${GREEN}✓${NC} coverage_above_80 (${coverage}%)" || { echo -e "    ${RED}✗${NC} coverage_above_80 (${coverage}%)"; ((failed++)); }
            ;;
        S5)
            # Review checks
            local critical_count
            critical_count=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('review', {}).get('summary', {}).get('critical_count', -1))
" 2>/dev/null || echo "-1")
            local sec_critical
            sec_critical=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
issues = d.get('review', {}).get('security_review', {}).get('issues', [])
print(len([i for i in issues if i.get('severity') in ('critical', 'high')]))
" 2>/dev/null || echo "-1")

            echo -e "  Gate checks:"
            [[ "$critical_count" == "0" ]] && echo -e "    ${GREEN}✓${NC} zero_critical_issues" || { echo -e "    ${RED}✗${NC} zero_critical_issues (${critical_count})"; ((failed++)); }
            [[ "$sec_critical" == "0" ]] && echo -e "    ${GREEN}✓${NC} zero_high_security_issues" || { echo -e "    ${RED}✗${NC} zero_high_security_issues (${sec_critical})"; ((failed++)); }
            ;;
        S3b)
            # Frontend build check
            local build_ok
            build_ok=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('implementation', {}).get('build_result', {}).get('success', False))
" 2>/dev/null || echo "False")
            echo -e "  Gate checks:"
            [[ "$build_ok" == "True" ]] && echo -e "    ${GREEN}✓${NC} build_passes" || { echo -e "    ${RED}✗${NC} build_passes"; ((failed++)); }
            ;;
        S4b)
            # Integration test results
            local int_failed
            int_failed=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('testing', {}).get('test_results', {}).get('failed', -1))
" 2>/dev/null || echo "-1")
            echo -e "  Gate checks:"
            [[ "$int_failed" == "0" ]] && echo -e "    ${GREEN}✓${NC} all_integration_tests_pass" || { echo -e "    ${RED}✗${NC} all_integration_tests_pass (${int_failed} failed)"; ((failed++)); }
            ;;
        S4c)
            # E2E test results
            local e2e_failed
            e2e_failed=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('testing', {}).get('test_results', {}).get('failed', -1))
" 2>/dev/null || echo "-1")
            echo -e "  Gate checks:"
            [[ "$e2e_failed" == "0" ]] && echo -e "    ${GREEN}✓${NC} all_e2e_tests_pass" || { echo -e "    ${RED}✗${NC} all_e2e_tests_pass (${e2e_failed} failed)"; ((failed++)); }
            ;;
        S7|S8|S9|S10)
            # Generic completeness check
            local status_val
            status_val=$(python3 -c "
import json
with open('${json_path}') as f: d = json.load(f)
print(d.get('status', 'failed'))
" 2>/dev/null || echo "failed")
            echo -e "  Gate checks:"
            [[ "$status_val" == "complete" ]] && echo -e "    ${GREEN}✓${NC} output_complete" || { echo -e "    ${RED}✗${NC} output_complete (status: ${status_val})"; ((failed++)); }
            ;;
    esac

    return $failed
}

# --- Main ---
main() {
    if [[ $# -lt 2 ]]; then
        usage
    fi

    local stage_id="$1"
    local json_path="$2"

    echo -e "${CYAN}=== Handoff Validation: ${stage_id} ===${NC}"
    echo -e "  File: ${json_path}"

    # Check file exists
    if [[ ! -f "$json_path" ]]; then
        echo -e "${RED}[FAIL]${NC} Output file not found: ${json_path}"
        exit 1
    fi

    # Get schema
    local schema_path
    schema_path=$(get_schema_path "$stage_id")
    if [[ -z "$schema_path" ]]; then
        echo -e "${RED}[FAIL]${NC} Unknown stage: ${stage_id}"
        exit 1
    fi
    if [[ ! -f "$schema_path" ]]; then
        echo -e "${RED}[FAIL]${NC} Schema not found: ${schema_path}"
        exit 1
    fi

    # Step 1: JSON syntax
    echo -e "\n${YELLOW}[1/3]${NC} Checking JSON syntax..."
    if ! validate_json_syntax "$json_path"; then
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Valid JSON"

    # Step 2: Schema validation
    echo -e "\n${YELLOW}[2/3]${NC} Validating against schema..."
    local schema_result
    schema_result=$(validate_schema "$schema_path" "$json_path" 2>&1) || true
    echo "  $schema_result"

    if echo "$schema_result" | grep -q "VALIDATION FAILED"; then
        echo -e "\n${RED}[FAIL]${NC} Schema validation failed"
        exit 1
    fi

    # Step 3: Gate checks
    echo -e "\n${YELLOW}[3/3]${NC} Checking gate requirements..."
    if check_gate_requirements "$stage_id" "$json_path"; then
        echo -e "\n${GREEN}[PASS]${NC} All validations passed for ${stage_id}"
        exit 0
    else
        echo -e "\n${RED}[FAIL]${NC} Gate checks failed for ${stage_id}"
        exit 1
    fi
}

main "$@"
