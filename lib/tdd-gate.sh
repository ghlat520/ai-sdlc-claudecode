#!/usr/bin/env bash
# =============================================================================
# tdd-gate.sh — TDD Hard Gate for pipeline S4 (Unit Testing) stage
# Validates that test coverage meets the required threshold (default 80%).
# If coverage is below threshold, the gate rejects the stage.
#
# Usage: tdd-gate.sh <feature_id> <tech_stack> [threshold]
#   feature_id  — pipeline feature identifier
#   tech_stack  — one of: java-maven, node-typescript, python, golang
#   threshold   — minimum coverage % (default: 80)
#
# Exit codes:
#   0 = PASS (coverage >= threshold)
#   1 = FAIL (coverage < threshold)
#   2 = WARN (could not determine coverage)
#   Coverage command failures retain their non-zero exit code.
# =============================================================================
set -euo pipefail

# --- Path setup ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAG_FILE="${PIPELINE_DAG_FILE:-${SCRIPT_DIR}/pipeline-dag.json}"

# --- Constants ---
PREFIX="[TDD-GATE]"
DEFAULT_THRESHOLD=80

# --- Argument parsing ---
FEATURE_ID="${1:-}"
TECH_STACK="${2:-}"
THRESHOLD="${3:-$DEFAULT_THRESHOLD}"

if [[ -z "$FEATURE_ID" || -z "$TECH_STACK" ]]; then
    echo "${PREFIX} ERROR: Missing required arguments"
    echo "Usage: tdd-gate.sh <feature_id> <tech_stack> [threshold]"
    exit 2
fi

# --- Validate DAG file exists ---
if [[ ! -f "$DAG_FILE" ]]; then
    echo "${PREFIX} ERROR: pipeline-dag.json not found at ${DAG_FILE}"
    exit 2
fi

# --- Look up coverage command from DAG config ---
lookup_coverage_config() {
    local stack="$1"
    local field="${2:-coverage}"
    python3 - "$DAG_FILE" "$stack" "$field" <<'PY_COVERAGE'
import json, sys
with open(sys.argv[1]) as f:
    dag = json.load(f)
commands = dag.get('config', {}).get('tech_stack_commands', {})
stack_cfg = commands.get(sys.argv[2])
if not stack_cfg:
    print('ERROR:unknown_stack', end='')
    sys.exit(0)
value = stack_cfg.get(sys.argv[3], '')
if sys.argv[3] == 'coverage' and not value:
    print('ERROR:no_coverage_cmd', end='')
    sys.exit(0)
print(value, end='')
PY_COVERAGE
}

# --- Parse coverage from Java/Maven (jacoco) ---
parse_java_coverage() {
    # Try CSV first (more reliable parsing), fall back to XML
    local jacoco_csv="target/site/jacoco/jacoco.csv"
    local jacoco_xml="target/site/jacoco/jacoco.xml"

    if [[ -f "$jacoco_csv" ]]; then
        # CSV format: GROUP,PACKAGE,CLASS,INSTRUCTION_MISSED,INSTRUCTION_COVERED,...
        # Sum INSTRUCTION_MISSED and INSTRUCTION_COVERED across all rows (skip header)
        python3 -c "
import csv, sys
missed = 0
covered = 0
with open('${jacoco_csv}') as f:
    reader = csv.DictReader(f)
    for row in reader:
        missed += int(row.get('INSTRUCTION_MISSED', 0))
        covered += int(row.get('INSTRUCTION_COVERED', 0))
total = missed + covered
if total == 0:
    print('0.0', end='')
else:
    print(f'{(covered / total) * 100:.1f}', end='')
" 2>/dev/null
        return
    fi

    if [[ -f "$jacoco_xml" ]]; then
        # XML: <counter type="INSTRUCTION" missed="X" covered="Y"/>
        python3 -c "
import xml.etree.ElementTree as ET, sys
tree = ET.parse('${jacoco_xml}')
root = tree.getroot()
for counter in root.findall('.//counter'):
    if counter.get('type') == 'INSTRUCTION':
        missed = int(counter.get('missed', 0))
        covered = int(counter.get('covered', 0))
        total = missed + covered
        if total > 0:
            print(f'{(covered / total) * 100:.1f}', end='')
            sys.exit(0)
print('', end='')
" 2>/dev/null
        return
    fi

    echo ""
}

# --- Parse coverage from Node/TypeScript (istanbul/c8) ---
parse_node_coverage() {
    local summary="coverage/coverage-summary.json"

    if [[ ! -f "$summary" ]]; then
        echo ""
        return
    fi

    python3 -c "
import json, sys
with open('${summary}') as f:
    data = json.load(f)
total = data.get('total', {})
lines = total.get('lines', {})
pct = lines.get('pct', None)
if pct is not None:
    print(f'{float(pct):.1f}', end='')
else:
    print('', end='')
" 2>/dev/null
}

# --- Parse coverage from Python (pytest --cov stdout) ---
parse_python_coverage() {
    local output="$1"
    # Look for "TOTAL" line, e.g.: "TOTAL    1234    456    63%"
    local pct
    pct=$(echo "$output" | python3 -c "
import sys, re
for line in sys.stdin:
    if 'TOTAL' in line:
        match = re.search(r'(\d+(?:\.\d+)?)%', line)
        if match:
            print(match.group(1), end='')
            sys.exit(0)
print('', end='')
" 2>/dev/null)
    echo "$pct"
}

# --- Parse coverage from Go (go tool cover -func) ---
parse_golang_coverage() {
    if [[ ! -f "coverage.out" ]]; then
        echo ""
        return
    fi

    # `go tool cover -func=coverage.out` last line: "total: (statements) XX.X%"
    local output
    output=$(go tool cover -func=coverage.out 2>/dev/null || echo "")

    local pct
    pct=$(echo "$output" | python3 -c "
import sys, re
for line in sys.stdin:
    if 'total:' in line:
        match = re.search(r'(\d+(?:\.\d+)?)%', line)
        if match:
            print(match.group(1), end='')
            sys.exit(0)
print('', end='')
" 2>/dev/null)
    echo "$pct"
}

# --- Compare coverage against threshold (integer-safe with bc) ---
compare_coverage() {
    local coverage="$1"
    local threshold="$2"
    # Returns 0 if coverage >= threshold, 1 otherwise
    python3 -c "
import sys
cov = float('${coverage}')
thr = float('${threshold}')
sys.exit(0 if cov >= thr else 1)
" 2>/dev/null
}

# --- Compute deficit ---
compute_deficit() {
    local coverage="$1"
    local threshold="$2"
    python3 -c "
cov = float('${coverage}')
thr = float('${threshold}')
print(f'{thr - cov:.1f}', end='')
" 2>/dev/null
}

# --- Emit JSON result to stdout ---
emit_json_result() {
    local coverage="$1"
    local threshold="$2"
    local result="$3"
    local tech_stack="$4"
    python3 -c "
import json
print(json.dumps({
    'coverage': float('${coverage}'),
    'threshold': float('${threshold}'),
    'result': '${result}',
    'tech_stack': '${tech_stack}'
}))" 2>/dev/null
}

# =============================================================================
# Main
# =============================================================================

echo "${PREFIX} Tech stack: ${TECH_STACK}"

# Look up coverage command
COVERAGE_CMD=${PIPELINE_COVERAGE_COMMAND:-$(lookup_coverage_config "$TECH_STACK")}

if [[ "$COVERAGE_CMD" == "ERROR:unknown_stack" ]]; then
    echo "${PREFIX} ERROR: Unknown tech stack '${TECH_STACK}'"
    echo "${PREFIX} Supported: java-maven, node-typescript, python, golang"
    exit 2
fi

if [[ "$COVERAGE_CMD" == "ERROR:no_coverage_cmd" ]]; then
    echo "${PREFIX} ERROR: No coverage command defined for '${TECH_STACK}'"
    exit 2
fi

COVERAGE_WORKDIR=${PIPELINE_COVERAGE_WORKDIR-$(lookup_coverage_config "$TECH_STACK" coverage_workdir)}
cd "${PROJECT_CODE_DIR:-$PWD}"
if [[ -n "$COVERAGE_WORKDIR" ]]; then
    cd "$COVERAGE_WORKDIR"
fi
echo "${PREFIX} Working directory: $PWD"
echo "${PREFIX} Running coverage: ${COVERAGE_CMD}"

# A successful no-op must not reuse an older report as a new measurement.
coverage_report_identity() {
    python3 - "$TECH_STACK" <<'PY_FRESH'
import hashlib, json, pathlib, sys
names = {'java-maven':['target/site/jacoco/jacoco.csv','target/site/jacoco/jacoco.xml'],
         'node-typescript':['coverage/coverage-summary.json'], 'golang':['coverage.out']}.get(sys.argv[1], [])
result = {}
for name in names:
    p = pathlib.Path(name)
    if p.is_file():
        s = p.stat()
        result[name] = [s.st_mtime_ns, s.st_ctime_ns, hashlib.sha256(p.read_bytes()).hexdigest()]
        break  # Match the parser's CSV/XML priority; touching an unused report is insufficient.
print(json.dumps(result, sort_keys=True))
PY_FRESH
}
REPORT_BEFORE=$(coverage_report_identity)

# Run the coverage command and capture output
COV_OUTPUT=""
COV_EXIT=0
COV_OUTPUT=$(eval "$COVERAGE_CMD" 2>&1) || COV_EXIT=$?

if [[ $COV_EXIT -ne 0 ]]; then
    echo "${PREFIX} ERROR: Coverage command exited with code ${COV_EXIT}"
    echo "${PREFIX} Output (last 20 lines):"
    echo "$COV_OUTPUT" | tail -20
    emit_json_result "0" "$THRESHOLD" "fail" "$TECH_STACK"
    exit "$COV_EXIT"
fi

if [[ "$TECH_STACK" != python && "$(coverage_report_identity)" == "$REPORT_BEFORE" ]]; then
    echo "${PREFIX} ERROR: Coverage report was not refreshed by the command"
    exit 2
fi

# Parse coverage based on tech stack
COVERAGE=""
case "$TECH_STACK" in
    java-maven)
        COVERAGE=$(parse_java_coverage)
        ;;
    node-typescript)
        COVERAGE=$(parse_node_coverage)
        ;;
    python)
        COVERAGE=$(parse_python_coverage "$COV_OUTPUT")
        ;;
    golang)
        COVERAGE=$(parse_golang_coverage)
        ;;
esac

# Handle case where coverage could not be determined
if [[ -z "$COVERAGE" ]]; then
    echo "${PREFIX} Coverage: UNKNOWN"
    echo "${PREFIX} Threshold: ${THRESHOLD}%"
    echo "${PREFIX} Result: UNVERIFIED (could not determine required coverage)"
    emit_json_result "0" "$THRESHOLD" "warn" "$TECH_STACK"
    exit 2
fi

echo "${PREFIX} Coverage: ${COVERAGE}%"
echo "${PREFIX} Threshold: ${THRESHOLD}%"

# Compare and emit result
if compare_coverage "$COVERAGE" "$THRESHOLD"; then
    echo "${PREFIX} Result: PASS"
    emit_json_result "$COVERAGE" "$THRESHOLD" "pass" "$TECH_STACK"
    exit 0
else
    DEFICIT=$(compute_deficit "$COVERAGE" "$THRESHOLD")
    echo "${PREFIX} Result: FAIL (${DEFICIT}% below threshold)"
    emit_json_result "$COVERAGE" "$THRESHOLD" "fail" "$TECH_STACK"
    exit 1
fi
