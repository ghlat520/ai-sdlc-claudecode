"""Path resolution and constants.

All paths are resolved relative to the package's bash/ directory,
which contains the pipeline executor and supporting scripts.
"""

from __future__ import annotations

from pathlib import Path

# Package root: src/ai_sdlc_claudecode/
PACKAGE_DIR = Path(__file__).resolve().parent

# Bash scripts are symlinked/bundled alongside the package
BASH_DIR = PACKAGE_DIR / "bash"

# Fallback: if running from the pipeline directory directly
_PIPELINE_DIR = PACKAGE_DIR.parent.parent  # ai-sdlc-claudecode/

MAX_ITERATIONS_PER_PHASE = 10

# ANSI colors
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def resolve_executor() -> Path:
    """Find pipeline-executor.sh, checking bundled then fallback."""
    candidates = [
        BASH_DIR / "pipeline-executor.sh",
        _PIPELINE_DIR / "pipeline-executor.sh",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "pipeline-executor.sh not found. "
        "Run from ai-sdlc-claudecode/ or ensure bash/ symlink exists."
    )


def resolve_dag() -> Path:
    """Find pipeline-dag.json."""
    candidates = [
        BASH_DIR / "pipeline-dag.json",
        _PIPELINE_DIR / "pipeline-dag.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("pipeline-dag.json not found.")


def resolve_project_root() -> Path:
    """Find the project root (one level above ai-sdlc-claudecode/)."""
    executor = resolve_executor()
    return executor.parent.parent


def resolve_pipeline_root() -> Path:
    """Resolve docs/pipeline/ output directory."""
    return resolve_project_root() / "docs" / "pipeline"
