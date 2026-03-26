"""Pipeline Runner — Python wrapper around pipeline-executor.sh.

Invokes the bash executor via subprocess, parses results from state.json,
and handles auto-approval of human gates.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RunResult:
    """Immutable result of a pipeline run."""

    feature_id: str
    exit_code: int
    stdout: str
    stderr: str
    stages_passed: int
    total_stages: int
    cost_usd: float
    duration_seconds: float
    all_passed: bool


class PipelineRunner:
    """Wraps pipeline-executor.sh for invocation from Python."""

    def __init__(self, executor_path: Path, pipeline_root: Path) -> None:
        self.executor_path = executor_path
        self.pipeline_root = pipeline_root

        if not self.executor_path.exists():
            raise FileNotFoundError(f"Executor not found: {executor_path}")

    def run(
        self,
        feature_id: str,
        description: str,
        *,
        mock_review: bool = False,
        resume: bool = False,
        start_from: Optional[str] = None,
        skip_stages: Optional[str] = None,
        cost_limit: Optional[float] = None,
        evolve_errors_dir: Optional[Path] = None,
        timeout_seconds: int = 3600,
    ) -> RunResult:
        """Execute pipeline-executor.sh and parse the result."""
        cmd = self._build_command(
            feature_id, description,
            mock_review=mock_review, resume=resume,
            start_from=start_from, skip_stages=skip_stages,
            cost_limit=cost_limit,
        )

        env = os.environ.copy()
        # Always set EVOLVE_ERRORS_DIR — ErrorEngine is default-on
        default_evolve_dir = self.pipeline_root / feature_id / "evolve"
        env["EVOLVE_ERRORS_DIR"] = str(evolve_errors_dir or default_evolve_dir)

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                cwd=str(self.executor_path.parent.parent),  # project root
            )
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired:
            exit_code = 124
            stdout = ""
            stderr = f"Pipeline timed out after {timeout_seconds}s"

        duration = time.time() - start_time
        stages_passed = self.get_stages_passed(feature_id)
        total_stages = self._get_total_stages()
        cost_usd = self._get_cost(feature_id)

        return RunResult(
            feature_id=feature_id,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            stages_passed=stages_passed,
            total_stages=total_stages,
            cost_usd=cost_usd,
            duration_seconds=duration,
            all_passed=(stages_passed >= total_stages and exit_code == 0),
        )

    def auto_approve_gates(self, feature_id: str) -> None:
        """Create APPROVED files for human-required gates."""
        feature_dir = self.pipeline_root / feature_id
        if not feature_dir.exists():
            return
        for approval_file in feature_dir.rglob("APPROVAL_REQUIRED"):
            stage_dir = approval_file.parent
            approval_file.unlink(missing_ok=True)
            (stage_dir / "APPROVED").write_text(
                f"Auto-approved at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n",
                encoding="utf-8",
            )

    def get_stages_passed(self, feature_id: str) -> int:
        """Count passed stages from state.json."""
        state_file = self.pipeline_root / feature_id / "state.json"
        if not state_file.exists():
            return 0
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return sum(1 for s in data.get("stages", {}).values() if s.get("status") == "passed")
        except (json.JSONDecodeError, OSError):
            return 0

    def _build_command(
        self, feature_id: str, description: str, *,
        mock_review: bool = False, resume: bool = False,
        start_from: Optional[str] = None, skip_stages: Optional[str] = None,
        cost_limit: Optional[float] = None,
    ) -> list[str]:
        cmd = ["bash", str(self.executor_path), feature_id, description]
        if mock_review:
            cmd.append("--mock-review")
        if resume:
            cmd.append("--resume")
        if start_from:
            cmd.extend(["--start-from", start_from])
        if skip_stages:
            cmd.extend(["--skip-stage", skip_stages])
        if cost_limit is not None:
            cmd.extend(["--cost-limit", str(cost_limit)])
        return cmd

    def _get_total_stages(self) -> int:
        dag_file = self.executor_path.parent / "pipeline-dag.json"
        if not dag_file.exists():
            return 13
        try:
            return len(json.loads(dag_file.read_text(encoding="utf-8")).get("stages", {}))
        except (json.JSONDecodeError, OSError):
            return 13

    def _get_cost(self, feature_id: str) -> float:
        state_file = self.pipeline_root / feature_id / "state.json"
        if not state_file.exists():
            return 0.0
        try:
            return json.loads(state_file.read_text(encoding="utf-8")).get("cost", {}).get("estimated_usd", 0.0)
        except (json.JSONDecodeError, OSError):
            return 0.0
