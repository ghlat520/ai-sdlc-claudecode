#!/usr/bin/env bash
# Parallel scheduling reuses exactly the sequential executor and locked state writer.
execute_parallel_group() {
    local feature="$1" description="$2"
    shift 2
    local stage pid result=0 code=0
    local pids=()
    for stage in "$@"; do
        (execute_stage "$stage" "$feature" "$description") &
        pids+=("$!")
    done
    for pid in "${pids[@]}"; do
        code=0
        wait "$pid" || code=$?
        [[ $code -eq 0 ]] || result="$code"
    done
    return "$result"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    set -euo pipefail
    root="$(cd "$(dirname "$0")" && pwd)"
    exec bash "${root}/pipeline-executor.sh" "$1" "$2" --stages "$3" "${@:4}"
fi
