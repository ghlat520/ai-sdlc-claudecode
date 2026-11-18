"""Pipeline Runner — Python wrapper around pipeline-executor.sh.

Invokes the bash executor via subprocess, parses results from state.json,
and reports verified execution scope without granting human approval.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .state import PipelineState


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
    outcome: str = "unverified"
    run_id: Optional[str] = None
    project_acceptance: Optional[dict] = None


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

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", feature_id):
            raise ValueError("invalid feature_id")
        state = PipelineState(self.pipeline_root / feature_id / "state.json")
        previous = state.read()
        previous_run = previous.get("run_id")
        env = os.environ.copy()
        if resume:
            dag = env.get('PIPELINE_DAG_FILE') or previous.get('dag_path')
            if dag:
                env['PIPELINE_DAG_FILE'] = str(Path(dag).resolve())
        invocation = uuid.uuid4().hex
        env['PIPELINE_INVOCATION_ID'] = invocation
        env["PIPELINE_ROOT"] = str(self.pipeline_root)
        # Always set EVOLVE_ERRORS_DIR — ErrorEngine is default-on
        default_evolve_dir = self.pipeline_root / feature_id / "evolve"
        env["EVOLVE_ERRORS_DIR"] = str(evolve_errors_dir or default_evolve_dir)

        start_time = time.time()

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env, cwd=str(self.executor_path.parent.parent), start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            # Let dispatchers stop their detached model groups before escalation.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
            exit_code = 124
            stderr += f"\nPipeline timed out after {timeout_seconds}s"

        except BaseException as error:
            # Interrupt/shutdown must not leave an autonomous child running.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
            data = state.read()
            if data.get('invocation_id') == invocation:
                code = 130
                if isinstance(error, SystemExit) and isinstance(error.code, int) and error.code:
                    code = error.code
                state.record_executor_exit(data['run_id'], invocation, code)
            raise

        duration = time.time() - start_time
        data = state.read()
        fresh = (bool(data.get("run_id")) and data["run_id"] != previous_run
                 and data.get('invocation_id') == invocation)
        if fresh:
            fresh = state.record_executor_exit(data['run_id'], invocation, exit_code)
        summary = state.summary()
        fresh = fresh and summary['run_id'] == data['run_id']
        stages_passed = summary['stages_passed'] if fresh else 0
        total_stages = summary['stages_total'] or self._get_total_stages()
        outcome = summary['execution_outcome'] if fresh else "unverified"
        project = summary['project_acceptance'] if fresh else dict(status='not_evaluated', reasons=['No fresh run'])
        if exit_code not in (0, 3, 4):
            outcome = "failed"
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
            all_passed=(fresh and outcome == "complete" and exit_code == 0),
            outcome=outcome, run_id=data.get("run_id") if fresh else None,
            project_acceptance=project,
        )

    def auto_approve_gates(self, feature_id: str) -> None:
        """Compatibility entrypoint: the runner has no authority to approve human gates."""
        raise PermissionError("human approval requires a trusted external decision")

    def get_stages_passed(self, feature_id: str) -> int:
        """Count only current verified artifacts within the requested scope."""
        state = PipelineState(self.pipeline_root / feature_id / "state.json")
        try:
            return state.summary()['stages_passed']
        except (ValueError, OSError):
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
            return 0
        try:
            return len(json.loads(dag_file.read_text(encoding="utf-8")).get("stages", {}))
        except (json.JSONDecodeError, OSError):
            return 0

    def _get_cost(self, feature_id: str) -> float:
        state_file = self.pipeline_root / feature_id / "state.json"
        if not state_file.exists():
            return 0.0
        try:
            return json.loads(state_file.read_text(encoding="utf-8")).get("cost", {}).get("estimated_usd", 0.0)
        except (json.JSONDecodeError, OSError):
            return 0.0
