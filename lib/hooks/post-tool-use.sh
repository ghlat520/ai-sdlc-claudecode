#!/usr/bin/env bash
# =============================================================================
# post-tool-use.sh — Sensitive Directory Protection Hook
#
# Prevents agent from writing into dangerous or polluted directories:
#   node_modules, .git, target, dist, build, __pycache__, .venv, .nuxt,
#   coverage, test-results, .pytest_cache, .mvn, vendor
#
# Registered as PreToolUse hook for Edit|Write (exit 2 = block with message).
# Bypass with: ALLOW_SENSITIVE_WRITES=1
#
# Exit codes:
#   0 = allow
#   2 = block with message
# =============================================================================

# Bypass switch (for intentional writes e.g. during cleanup)
if [[ "${ALLOW_SENSITIVE_WRITES:-0}" == "1" ]]; then
    exit 0
fi

# Read tool input from stdin (JSON with file_path)
INPUT=$(cat)
FILE_PATH=$(python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('file_path') or data.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
" <<< "$INPUT" 2>/dev/null)

# Empty path — allow (not a file operation)
if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Sensitive directory patterns (path segments, not prefixes)
SENSITIVE_DIRS=(
    "node_modules"
    ".git"
    "target"
    "dist"
    "build"
    "__pycache__"
    ".venv"
    ".nuxt"
    ".next"
    "coverage"
    "test-results"
    ".pytest_cache"
    ".mvn"
    "vendor"
    ".DS_Store"
)

for dir in "${SENSITIVE_DIRS[@]}"; do
    # Match /DIR/ or /DIR$ (segment match, not substring)
    if [[ "$FILE_PATH" == */"$dir"/* ]] || [[ "$FILE_PATH" == */"$dir" ]]; then
        echo "BLOCKED: Writing to sensitive directory '$dir' is prohibited." >&2
        echo "File: $FILE_PATH" >&2
        echo "Bypass (if intentional): set ALLOW_SENSITIVE_WRITES=1" >&2
        exit 2
    fi
done

exit 0
