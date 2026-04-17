#!/usr/bin/env bash
# =============================================================================
# stop.sh — Session End Summary Hook
#
# Invoked by Claude Code on session end (Stop hook). Surfaces a compact
# summary of recent pipeline activity and flags any unresolved dead_letters
# or pending wiki-distill work so the next session starts informed.
#
# Non-blocking: always exits 0.
# =============================================================================

set -u

PIPELINE_ROOT="${PIPELINE_ROOT:-docs/pipeline}"

# Skip if no pipeline artifacts
if [[ ! -d "${PIPELINE_ROOT}" ]]; then
    exit 0
fi

# Count dead letters across all features (last 7 days only)
DEAD_LETTER_COUNT=0
if command -v find >/dev/null 2>&1; then
    DEAD_LETTER_COUNT=$(find "${PIPELINE_ROOT}" -type f -path "*/evolve/dead_letters/*.json" -mtime -7 2>/dev/null | wc -l | tr -d ' ')
fi

# Check for unprocessed wiki-distill raw files
RAW_COUNT=0
if [[ -d "${HOME}/.claude/llm-wiki/raw" ]]; then
    RAW_COUNT=$(find "${HOME}/.claude/llm-wiki/raw" -type f -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
fi

# Count recent pipeline runs (feature directories with state.json modified in last 1 day)
RECENT_RUNS=0
if command -v find >/dev/null 2>&1; then
    RECENT_RUNS=$(find "${PIPELINE_ROOT}" -maxdepth 3 -name "ai-sdlc-state.json" -mtime -1 2>/dev/null | wc -l | tr -d ' ')
fi

# Emit compact summary to stderr (visible in Claude Code transcript)
{
    echo ""
    echo "─── ai-sdlc session summary ───"
    [[ "${RECENT_RUNS}" -gt 0 ]] && echo "  • Recent pipeline runs (24h): ${RECENT_RUNS}"
    if [[ "${DEAD_LETTER_COUNT}" -gt 0 ]]; then
        echo "  ⚠ Unresolved dead_letters (7d): ${DEAD_LETTER_COUNT}"
        echo "    → inspect via: find ${PIPELINE_ROOT} -path '*/evolve/dead_letters/*.json' -mtime -7"
    fi
    if [[ "${RAW_COUNT}" -gt 0 ]]; then
        echo "  ℹ llm-wiki: ${RAW_COUNT} raw files pending distill"
        echo "    → run: wiki-distill  (needs Opus)"
    fi
    echo "───────────────────────────────"
} >&2

exit 0
