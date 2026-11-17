#!/usr/bin/env bash
# Exit 0: configured scan passed; 1: violation; 2: scanner/tool/input error.
set -euo pipefail
if [[ $# -ne 1 ]] || [[ ! -d "$1" ]]; then
    echo 'Usage: completeness-check.sh <existing-project-dir>' >&2
    exit 2
fi
if ! command -v node >/dev/null 2>&1; then
    echo '[ERROR] completeness-check requires Node.js' >&2
    exit 2
fi
exec node "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/completeness-check.cjs" "$1"
