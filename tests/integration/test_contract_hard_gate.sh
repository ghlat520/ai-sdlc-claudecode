#!/usr/bin/env bash
# Integration smoke test for the Contract Hard Gate.
#
# Simulates the pipeline-executor.sh S3/S3b gate path using fixtures,
# without calling the Claude API. Verifies:
#   1. contracts.json is discovered in the expected S2 output location.
#   2. contract_validator runs and detects ai-media-platform's C2/H1/H3.
#   3. The gate produces a non-zero exit and a structured violations report.
#
# Usage:  bash tests/integration/test_contract_hard_gate.sh
# Exits 0 on success, non-zero on failure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RED="\033[0;31m"; GREEN="\033[0;32m"; YELLOW="\033[0;33m"; NC="\033[0m"

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; exit 1; }

# --- Fixtures ---

FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT

PIPELINE_ROOT="${FIXTURE_ROOT}/pipeline"
FEATURE_ID="smoke-001"
STAGE_DIR="${PIPELINE_ROOT}/${FEATURE_ID}/S2-architecture"
OUTPUT_DIR="${FIXTURE_ROOT}/output/S3"
CODE_ROOT="/Applications/soft/CodeSpace/ai-media-platform"

mkdir -p "$STAGE_DIR" "$OUTPUT_DIR"

# Hand-written contracts.json covering ai-media-platform's declared surface.
cat > "${STAGE_DIR}/contracts.json" <<'JSON'
{
  "stage_id": "S2",
  "feature_id": "smoke-001",
  "timestamp": "2026-04-19T00:00:00Z",
  "contracts": {
    "services": [
      {"name": "biz-service", "responsibility": "core", "language": "node", "port": 3001},
      {"name": "publisher-service", "responsibility": "publish", "language": "node", "port": 3002}
    ],
    "api_endpoints": [],
    "cross_service_messages": [],
    "encryption_pairs": [],
    "shared_models": [],
    "external_refs": {
      "ai_models": [
        {"provider": "anthropic", "model_id": "claude-opus-4-7", "used_in_service": "biz-service"}
      ],
      "npm_packages_forbidden": ["crypto"]
    }
  }
}
JSON

[[ ! -d "$CODE_ROOT" ]] && { echo "ai-media-platform not at $CODE_ROOT — skipping real-project smoke."; exit 0; }

echo "=== Contract Hard Gate smoke test ==="
echo "Fixture: $FIXTURE_ROOT"
echo "Code:    $CODE_ROOT"
echo

# --- Assertion 1: executor locates contracts.json via the same glob ---

echo "[1] Locate contracts.json via executor's find pattern"
contracts_json=$(find "${PIPELINE_ROOT}/${FEATURE_ID}" -path "*/S2-*/contracts.json" -type f 2>/dev/null | head -1)
[[ -n "$contracts_json" && -f "$contracts_json" ]] || fail "contracts.json not discovered"
pass "Found: $contracts_json"

# --- Assertion 2: validator runs and produces structured output ---

echo
echo "[2] Run contract_validator against ai-media-platform"
report_json="${OUTPUT_DIR}/contract_violations.json"
report_err="${OUTPUT_DIR}/contract_violations.txt"
contract_exit=0
PYTHONPATH="${SCRIPT_DIR}/src" python3 -m ai_sdlc_claudecode.contract_validator \
    "$contracts_json" "$CODE_ROOT" > "$report_json" 2> "$report_err" || contract_exit=$?

[[ -s "$report_json" ]] || fail "validator wrote no report"
pass "Report written ($(wc -c < "$report_json") bytes)"

# --- Assertion 3: exit code signals blocking violations ---

echo
echo "[3] Exit code reflects blocking violations"
[[ $contract_exit -eq 1 ]] || fail "expected exit 1 (blocking), got $contract_exit"
pass "Exit code = 1 (blocking)"

# --- Assertion 4: report structure is well-formed ---

echo
echo "[4] Report JSON shape"
python3 - <<PY
import json, sys
d = json.load(open("${report_json}"))
assert d["total"] > 0, "expected total > 0"
assert d["blocking"] > 0, "expected blocking > 0"
assert isinstance(d["violations"], list)
assert all("check" in v and "severity" in v and "service" in v for v in d["violations"])
print(f"  total={d['total']} blocking={d['blocking']} by_severity={d['by_severity']}")
PY
pass "Report schema looks valid"

# --- Assertion 5: known ai-media-platform bugs are caught ---

echo
echo "[5] Catches ai-media-platform's known C2/H1/H3 bugs"
python3 - <<PY
import json
d = json.load(open("${report_json}"))
checks = {v["check"] for v in d["violations"]}
expected = {"duplicate_services", "forbidden_npm_package", "hallucinated_model_id"}
missing = expected - checks
assert not missing, f"missing checks: {missing}"
print(f"  hit: {sorted(checks)}")
PY
pass "C2/H1/H3 all surfaced"

# --- Assertion 6: error output has the retry hint the executor would feed back ---

echo
echo "[6] Stderr has human-readable violation summary (for LLM retry context)"
grep -q "blocking violation" "$report_err" || fail "expected 'blocking violation' hint in stderr"
pass "stderr summary present"

echo
echo -e "${GREEN}=== ALL ASSERTIONS PASSED ===${NC}"
