#!/usr/bin/env bash
# =============================================================================
# check-scope.sh — Scope Lock for Pipeline Execution
#
# Restricts file edits to allowed directories during pipeline stage execution.
# Activated by PIPELINE_SCOPE_LOCK env var (comma-separated allowed path prefixes).
#
# Used as a PreToolUse hook for Edit/Write tools.
#
# Exit codes:
#   0 = allow (file within scope or no lock active)
#   2 = block with message (file outside allowed scope)
# =============================================================================

SCOPE_LOCK="${PIPELINE_SCOPE_LOCK:-}"

# No lock set — allow everything
if [[ -z "$SCOPE_LOCK" ]]; then
    exit 0
fi

# Read tool input from stdin (JSON with file_path)
INPUT=$(cat)
FILE_PATH=$(python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    # Handle both Edit (file_path) and Write (file_path) tool inputs
    print(data.get('file_path', ''))
except Exception:
    print('')
" <<< "$INPUT" 2>/dev/null)

# Empty file path — allow (not a file operation)
if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Check if file_path starts with any allowed prefix
IFS=',' read -ra ALLOWED <<< "$SCOPE_LOCK"
for prefix in "${ALLOWED[@]}"; do
    # Trim whitespace
    prefix=$(echo "$prefix" | xargs)
    if [[ -n "$prefix" && "$FILE_PATH" == "$prefix"* ]]; then
        exit 0
    fi
done

echo "BLOCKED: File '$FILE_PATH' is outside allowed scope. Allowed: ${SCOPE_LOCK}" >&2
exit 2
