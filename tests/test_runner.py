"""Tests for ai_sdlc_claudecode.runner — PipelineRunner."""

import json
from pathlib import Path

import pytest

from ai_sdlc_claudecode.runner import PipelineRunner, RunResult


@pytest.fixture
def executor_path() -> Path:
    """Real executor path."""
    p = Path(__file__).resolve().parent.parent / "pipeline-executor.sh"
    if not p.exists():
        pytest.skip("pipeline-executor.sh not found")
    return p


@pytest.fixture
def pipeline_root(tmp_path: Path) -> Path:
    return tmp_path / "pipeline"


class TestBuildCommand:
    def test_basic(self, executor_path: Path, pipeline_root: Path) -> None:
        runner = PipelineRunner(executor_path, pipeline_root)
        cmd = runner._build_command("feat", "desc")
        assert cmd[:2] == ["bash", str(executor_path)]
        assert "feat" in cmd
        assert "desc" in cmd

    def test_with_options(self, executor_path: Path, pipeline_root: Path) -> None:
        runner = PipelineRunner(executor_path, pipeline_root)
        cmd = runner._build_command(
            "feat", "desc",
            mock_review=True, resume=True,
            start_from="S3", cost_limit=10.0,
        )
        assert "--mock-review" in cmd
        assert "--resume" in cmd
        assert "--start-from" in cmd
        assert "S3" in cmd
        assert "--cost-limit" in cmd
        assert "10.0" in cmd


class TestGetStagesPassed:
    def test_no_state_file(self, executor_path: Path, pipeline_root: Path) -> None:
        runner = PipelineRunner(executor_path, pipeline_root)
        assert runner.get_stages_passed("nonexistent") == 0

    def test_counts_passed(self, executor_path: Path, pipeline_root: Path) -> None:
        runner = PipelineRunner(executor_path, pipeline_root)
        feat_dir = pipeline_root / "feat1"
        feat_dir.mkdir(parents=True)
        (feat_dir / "state.json").write_text(json.dumps({
            "stages": {
                "S1": {"status": "passed"},
                "S2": {"status": "passed"},
                "S3": {"status": "failed"},
            }
        }))
        assert runner.get_stages_passed("feat1") == 2


class TestAutoApprove:
    def test_approves_pending(self, executor_path: Path, pipeline_root: Path) -> None:
        runner = PipelineRunner(executor_path, pipeline_root)
        stage_dir = pipeline_root / "feat1" / "S6-deployment"
        stage_dir.mkdir(parents=True)
        (stage_dir / "APPROVAL_REQUIRED").write_text("waiting")

        runner.auto_approve_gates("feat1")

        assert not (stage_dir / "APPROVAL_REQUIRED").exists()
        assert (stage_dir / "APPROVED").exists()


class TestRunResult:
    def test_immutable(self) -> None:
        r = RunResult("f", 0, "", "", 13, 13, 1.0, 60.0, True)
        with pytest.raises(AttributeError):
            r.exit_code = 1  # type: ignore[misc]


class TestNotFound:
    def test_missing_executor(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            PipelineRunner(tmp_path / "nonexistent.sh", tmp_path)
