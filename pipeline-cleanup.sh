#!/usr/bin/env bash
# =============================================================================
# pipeline-cleanup.sh — Archive/cleanup completed feature pipelines
#
# Moves completed features (>N days old) to docs/pipeline/.archive/
# and cleans up temporary workspace artifacts.
#
# Usage:
#   ./pipeline-cleanup.sh                    # Archive features >30 days old
#   ./pipeline-cleanup.sh --days 7           # Archive features >7 days old
#   ./pipeline-cleanup.sh --dry-run          # Preview what would be archived
#   ./pipeline-cleanup.sh --clean-workspaces # Only clean up .pipeline-workspaces
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PIPELINE_ROOT="${PROJECT_ROOT}/docs/pipeline"
ARCHIVE_DIR="${PIPELINE_ROOT}/.archive"
WORKSPACE_DIR="${PROJECT_ROOT}/.pipeline-workspaces"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --days <N>           Archive features older than N days (default: 30)
  --dry-run            Preview archivable features without moving anything
  --clean-workspaces   Clean up stale .pipeline-workspaces only
  --all                Archive ALL completed features regardless of age
  --clean-debug        Move incomplete/failed runs to _debug/ directory
  --help               Show this help

Examples:
  $(basename "$0") --dry-run         # Preview what would be archived
  $(basename "$0") --days 7          # Archive completed features >7 days old
  $(basename "$0") --clean-workspaces  # Remove stale workspace dirs
EOF
    exit 0
}

# Check if a feature is eligible for archival
# Returns 0 if eligible, 1 if not
check_archivable() {
    local state_file="$1"
    local max_age_days="$2"
    local archive_all="$3"

    python3 -c "
import json, os, sys
from datetime import datetime, timedelta

with open('${state_file}') as f:
    state = json.load(f)

# Must have all stages passed or be explicitly completed
stages = state.get('stages', {})
passed = sum(1 for s in stages.values() if s.get('status') == 'passed')
pipeline_state = state.get('pipeline_state', '')

# Consider archivable if: all 13 passed, or pipeline_state is 'completed'
is_complete = passed >= 13 or pipeline_state == 'completed'

if not is_complete:
    sys.exit(1)

if '${archive_all}' == 'true':
    sys.exit(0)

# Check age
updated = state.get('updated_at', state.get('created_at', ''))
if not updated:
    sys.exit(1)

try:
    updated_dt = datetime.fromisoformat(updated.rstrip('Z'))
    age = datetime.utcnow() - updated_dt
    if age.days >= int('${max_age_days}'):
        sys.exit(0)
    else:
        sys.exit(1)
except (ValueError, TypeError):
    sys.exit(1)
" 2>/dev/null
}

archive_features() {
    local max_age_days="$1"
    local dry_run="$2"
    local archive_all="$3"

    if [[ ! -d "$PIPELINE_ROOT" ]]; then
        echo -e "${DIM}No pipeline directory found${NC}"
        return 0
    fi

    echo -e "${BOLD}${CYAN}Pipeline Cleanup${NC}"
    echo -e "  Archive threshold: ${max_age_days} days"
    echo -e "  Mode: $(if $dry_run; then echo 'DRY RUN'; else echo 'LIVE'; fi)"
    echo ""

    local archived=0
    local skipped=0

    for state_file in "${PIPELINE_ROOT}"/*/state.json; do
        [[ -f "$state_file" ]] || continue

        local feature_dir
        feature_dir=$(dirname "$state_file")
        local feature_id
        feature_id=$(basename "$feature_dir")

        # Skip .archive and _debug directories
        [[ "$feature_id" == ".archive" || "$feature_id" == "_debug" ]] && continue

        if check_archivable "$state_file" "$max_age_days" "$archive_all"; then
            local age_info
            age_info=$(python3 -c "
import json
from datetime import datetime
with open('${state_file}') as f:
    state = json.load(f)
updated = state.get('updated_at', state.get('created_at', '-'))
if updated and updated != '-':
    try:
        dt = datetime.fromisoformat(updated.rstrip('Z'))
        age = (datetime.utcnow() - dt).days
        print(f'{age} days old')
    except:
        print('unknown age')
else:
    print('unknown age')
" 2>/dev/null || echo "unknown age")

            if $dry_run; then
                echo -e "  ${YELLOW}[DRY RUN] Would archive: ${feature_id} (${age_info})${NC}"
            else
                mkdir -p "$ARCHIVE_DIR"
                mv "$feature_dir" "${ARCHIVE_DIR}/${feature_id}"
                echo -e "  ${GREEN}Archived: ${feature_id} (${age_info}) -> .archive/${feature_id}${NC}"
            fi
            ((archived++))
        else
            ((skipped++))
        fi
    done

    echo ""
    echo -e "  Archivable: ${archived}"
    echo -e "  Skipped:    ${skipped} (incomplete or too recent)"

    if $dry_run && [[ $archived -gt 0 ]]; then
        echo -e "\n  ${CYAN}Run without --dry-run to execute archival${NC}"
    fi
}

clean_debug_runs() {
    echo -e "${BOLD}${CYAN}Debug Run Cleanup${NC}"
    echo -e "  Moving incomplete/failed runs to _debug/"
    echo ""

    if [[ ! -d "$PIPELINE_ROOT" ]]; then
        echo -e "  ${DIM}No pipeline directory found${NC}"
        return 0
    fi

    local debug_dir="${PIPELINE_ROOT}/_debug"
    local moved=0
    local skipped=0

    for state_file in "${PIPELINE_ROOT}"/*/state.json; do
        [[ -f "$state_file" ]] || continue

        local feature_dir
        feature_dir=$(dirname "$state_file")
        local feature_id
        feature_id=$(basename "$feature_dir")

        # Skip special directories
        [[ "$feature_id" == ".archive" || "$feature_id" == "_debug" ]] && continue

        # Check if incomplete (not all stages passed and not explicitly completed)
        local is_complete
        is_complete=$(python3 -c "
import json, sys
with open('${state_file}') as f:
    state = json.load(f)
stages = state.get('stages', {})
passed = sum(1 for s in stages.values() if s.get('status') == 'passed')
pipeline_state = state.get('pipeline_state', '')
# Complete if all 13 passed or pipeline_state is 'completed'
if passed >= 13 or pipeline_state == 'completed':
    print('yes')
else:
    print('no')
" 2>/dev/null || echo "unknown")

        if [[ "$is_complete" == "no" ]]; then
            mkdir -p "$debug_dir"
            echo -e "  ${YELLOW}Moving to _debug/: ${feature_id} (incomplete)${NC}"
            mv "$feature_dir" "${debug_dir}/${feature_id}"
            ((moved++))
        else
            ((skipped++))
        fi
    done

    echo ""
    echo -e "  Moved to _debug: ${moved}"
    echo -e "  Kept (complete): ${skipped}"
}

clean_workspaces() {
    echo -e "${BOLD}${CYAN}Workspace Cleanup${NC}"

    if [[ ! -d "$WORKSPACE_DIR" ]]; then
        echo -e "  ${DIM}No workspaces found at: ${WORKSPACE_DIR}${NC}"
        return 0
    fi

    local count=0
    for ws in "${WORKSPACE_DIR}"/*/; do
        [[ -d "$ws" ]] || continue
        local ws_name
        ws_name=$(basename "$ws")
        echo -e "  ${YELLOW}Removing workspace: ${ws_name}${NC}"

        # Remove git worktree reference if applicable
        if git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
            git -C "$PROJECT_ROOT" worktree remove --force "$ws" 2>/dev/null || true
            # Clean up associated branch
            local branch_name="pipeline/${ws_name}"
            git -C "$PROJECT_ROOT" branch -D "$branch_name" 2>/dev/null || true
        fi

        rm -rf "$ws"
        ((count++))
    done

    rmdir "$WORKSPACE_DIR" 2>/dev/null || true

    echo -e "  ${GREEN}Cleaned ${count} workspace(s)${NC}"
}

# --- Main ---
main() {
    local max_age_days=30
    local dry_run=false
    local clean_ws_only=false
    local clean_debug_only=false
    local archive_all=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --days) max_age_days="$2"; shift 2 ;;
            --dry-run) dry_run=true; shift ;;
            --clean-workspaces) clean_ws_only=true; shift ;;
            --clean-debug) clean_debug_only=true; shift ;;
            --all) archive_all=true; shift ;;
            --help|-h) usage ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    if $clean_debug_only; then
        clean_debug_runs
    elif $clean_ws_only; then
        clean_workspaces
    else
        archive_features "$max_age_days" "$dry_run" "$archive_all"
        echo ""
        clean_debug_runs
        echo ""
        clean_workspaces
    fi
}

main "$@"
