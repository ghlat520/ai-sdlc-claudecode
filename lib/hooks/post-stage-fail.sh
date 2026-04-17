#!/usr/bin/env bash
# =============================================================================
# post-stage-fail.sh — Dead Letter Enrichment Hook
#
# Called by pipeline-executor.sh when a stage hits dead_letter state.
# Captures structured failure context for ErrorEngine + sends optional
# notifications (hermes-mcp, webhook).
#
# Usage:  bash lib/hooks/post-stage-fail.sh <feature_id> <stage_id> <retry_count> <reason>
#
# Env vars honored:
#   EVOLVE_ERRORS_DIR        — override dead_letters output dir
#   HERMES_NOTIFY_CHANNEL    — feishu:oc_xxx / telegram:chat_id, forwards via hermes MCP
#   POST_STAGE_FAIL_DISABLED — set to 1 to skip this hook entirely
# =============================================================================

set -u

[[ "${POST_STAGE_FAIL_DISABLED:-0}" == "1" ]] && exit 0

FEATURE_ID="${1:-unknown}"
STAGE_ID="${2:-unknown}"
RETRY_COUNT="${3:-0}"
REASON="${4:-unspecified}"

PIPELINE_ROOT="${PIPELINE_ROOT:-docs/pipeline}"
EVOLVE_DIR="${EVOLVE_ERRORS_DIR:-${PIPELINE_ROOT}/${FEATURE_ID}/evolve}"
DEAD_LETTERS_DIR="${EVOLVE_DIR}/dead_letters"
mkdir -p "${DEAD_LETTERS_DIR}"

TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
OUT_FILE="${DEAD_LETTERS_DIR}/${STAGE_ID}-$(date +%s).json"

# Collect last 50 lines from stage log if available
LOG_FILE="${PIPELINE_ROOT}/${FEATURE_ID}/logs/${STAGE_ID}.log"
LOG_TAIL=""
if [[ -f "${LOG_FILE}" ]]; then
    LOG_TAIL="$(tail -n 50 "${LOG_FILE}" 2>/dev/null || true)"
fi

# Escape for JSON via python
python3 - "$FEATURE_ID" "$STAGE_ID" "$RETRY_COUNT" "$REASON" "$TIMESTAMP" "$OUT_FILE" "$LOG_TAIL" <<'PY'
import json, sys
feature_id, stage_id, retry, reason, ts, out_file, log_tail = sys.argv[1:8]
record = {
    "feature_id": feature_id,
    "stage_id": stage_id,
    "retry_count": int(retry) if retry.isdigit() else 0,
    "reason": reason,
    "timestamp": ts,
    "log_tail": log_tail[-4000:] if log_tail else "",
    "requires_human": True,
}
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(record, f, indent=2, ensure_ascii=False)
PY

echo "[post-stage-fail] Dead letter recorded: ${OUT_FILE}" >&2

# Optional: forward to hermes-mcp if channel configured
if [[ -n "${HERMES_NOTIFY_CHANNEL:-}" ]] && command -v hermes >/dev/null 2>&1; then
    MSG="⚠️ Pipeline dead_letter: ${FEATURE_ID}/${STAGE_ID} after ${RETRY_COUNT} retries — ${REASON}"
    hermes mcp send-message \
        --target "${HERMES_NOTIFY_CHANNEL}" \
        --message "${MSG}" 2>/dev/null || true
fi

exit 0
