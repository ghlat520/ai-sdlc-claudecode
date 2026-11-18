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

    def test_legacy_pass_is_unverified(self, executor_path: Path, pipeline_root: Path) -> None:
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
        assert runner.get_stages_passed("feat1") == 0


class TestAutoApprove:
    def test_approves_pending(self, executor_path: Path, pipeline_root: Path) -> None:
        runner = PipelineRunner(executor_path, pipeline_root)
        stage_dir = pipeline_root / "feat1" / "S6-deployment"
        stage_dir.mkdir(parents=True)
        (stage_dir / "APPROVAL_REQUIRED").write_text("waiting")

        with pytest.raises(PermissionError):
            runner.auto_approve_gates("feat1")

        assert (stage_dir / "APPROVAL_REQUIRED").exists()
        assert not (stage_dir / "APPROVED").exists()


class TestRunResult:
    def test_immutable(self) -> None:
        r = RunResult("f", 0, "", "", 13, 13, 1.0, 60.0, True)
        with pytest.raises(AttributeError):
            r.exit_code = 1  # type: ignore[misc]


class TestNotFound:
    def test_missing_executor(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            PipelineRunner(tmp_path / "nonexistent.sh", tmp_path)


def test_agent_runs_only_requested_feature_phase():
    from ai_sdlc_claudecode.cli import EvolvingAgent
    agent = EvolvingAgent.__new__(EvolvingAgent)
    agent.start_phase = 2
    calls = []
    agent._preflight = agent._banner = agent._finalize = lambda: None
    agent._phase = lambda *args, **kwargs: calls.append((args, kwargs))
    agent.run()
    assert len(calls) == 1
    assert calls[0][0][0] == 2
    assert 'feature_override' not in calls[0][1]


@pytest.mark.parametrize('outcome', ['human_waiting', 'paused', 'partial', 'simulated', 'unverified'])
def test_agent_checkpoints_without_advancing_or_approving(tmp_path, monkeypatch, outcome):
    from unittest.mock import Mock
    import ai_sdlc_claudecode.cli as cli
    from ai_sdlc_claudecode.state import EvolveState
    agent = cli.EvolvingAgent.__new__(cli.EvolvingAgent)
    agent.feature_id, agent.description = 'feature', 'local'
    agent.errors_dir = tmp_path / 'errors'
    agent.state = EvolveState.create(tmp_path / 'evolve-state.json')
    agent.engine = Mock()
    agent.engine.read_failures.return_value = []
    agent.runner = Mock()
    agent.runner.run.return_value = RunResult('feature', 3, '', '', 0, 1, 0.25, 1, False, outcome)
    monkeypatch.setattr(cli, 'resolve_pipeline_root', lambda: tmp_path)
    agent._phase(2, 'fixture')
    assert agent.runner.run.call_count == 1
    agent.runner.auto_approve_gates.assert_not_called()
    agent.engine.promote_to_skill.assert_not_called()
    agent.engine.mark_success.assert_not_called()
    assert agent.state.cost_spent_usd == 0.25
    assert agent.state.phases[2].status != 'complete'


def test_runner_never_reuses_success_after_entrypoint_fails(tmp_path):
    executor = tmp_path / 'pipeline-executor.sh'
    executor.write_text('#!/bin/sh\nexit 1\n')
    pipeline = tmp_path / 'pipeline'
    sf = pipeline / 'feature' / 'state.json'
    sf.parent.mkdir(parents=True)
    sf.write_text(json.dumps({'run_id': 'old', 'scope': ['S1'], 'pipeline_state': 'complete'}))
    result = PipelineRunner(executor, pipeline).run('feature', 'fixture')
    assert not result.all_passed
    assert result.run_id is None
    assert result.outcome == 'failed'


def test_cli_run_preserves_executor_failure_exit(tmp_path):
    """A real local executor failure must reach the public CLI process boundary."""
    import os
    import subprocess
    import sys

    executor = tmp_path / 'pipeline-executor.sh'
    executor.write_text('#!/bin/sh\nexit 7\n')
    driver = tmp_path / 'local-cli.py'
    driver.write_text(
        'import runpy, sys\n'
        'from pathlib import Path\n'
        'import ai_sdlc_claudecode.cli as cli\n'
        f'cli.resolve_executor = lambda: Path({str(executor)!r})\n'
        f'cli.resolve_pipeline_root = lambda: Path({str(tmp_path / "pipeline")!r})\n'
        'cli.EvolvingAgent._preflight = lambda self: None\n'
        'cli.MAX_ITERATIONS_PER_PHASE = 1\n'
        'sys.argv = ["ai-sdlc", "run", "--phase", "2", "--feature-id", "local-case"]\n'
        'runpy.run_module("ai_sdlc_claudecode", run_name="__main__")\n'
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(driver)], text=True, capture_output=True, timeout=15,
        env={**os.environ, 'PYTHONPATH': str(root / 'src')},
    )
    assert result.returncode == 7, result.stdout + result.stderr
    checkpoint = json.loads((tmp_path / 'pipeline/local-case/ai-sdlc-state.json').read_text())
    assert checkpoint['current_iteration'] == 1
    assert checkpoint['phases']['2']['status'] == 'iteration_limit'


@pytest.mark.parametrize('outcome,native_exit,complete,expected_exit', [
    ('complete', 0, True, 0),
    ('failed', 0, False, 1),
    ('human_waiting', 3, False, 3),
    ('paused', 4, False, 4),
    ('partial', 0, False, 4),
    ('simulated', 0, False, 4),
    ('unverified', 0, False, 1),
])
def test_cli_exit_requires_completed_scope(tmp_path, outcome, native_exit, complete, expected_exit):
    """Controlled runner receipts exercise CLI exit and checkpoint semantics."""
    import os
    import subprocess
    import sys

    executor = tmp_path / 'pipeline-executor.sh'
    executor.write_text('#!/bin/sh\nexit 99\n')
    driver = tmp_path / 'controlled-cli.py'
    driver.write_text(
        'import runpy, sys\n'
        'from pathlib import Path\n'
        'import ai_sdlc_claudecode.cli as cli\n'
        'from ai_sdlc_claudecode.runner import RunResult\n'
        f'cli.resolve_executor = lambda: Path({str(executor)!r})\n'
        f'cli.resolve_pipeline_root = lambda: Path({str(tmp_path / "pipeline")!r})\n'
        'cli.EvolvingAgent._preflight = lambda self: None\n'
        'cli.MAX_ITERATIONS_PER_PHASE = 1\n'
        'cli.PipelineRunner.run = lambda *args, **kwargs: RunResult('\
        f'"local-case", {native_exit}, "", "", {int(complete)}, 1, 0, 0, {complete}, {outcome!r})\n'
        'sys.argv = ["ai-sdlc", "run", "--phase", "2", "--feature-id", "local-case"]\n'
        'runpy.run_module("ai_sdlc_claudecode", run_name="__main__")\n'
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(driver)], text=True, capture_output=True, timeout=15,
        env={**os.environ, 'PYTHONPATH': str(root / 'src')},
    )
    assert result.returncode == expected_exit, result.stdout + result.stderr
    checkpoint = json.loads((tmp_path / 'pipeline/local-case/ai-sdlc-state.json').read_text())
    assert checkpoint['phases']['2']['status'] == ('iteration_limit' if outcome == 'failed' else outcome)
    assert checkpoint['current_iteration'] == 1


def test_cli_budget_stop_before_execution_is_not_success(tmp_path):
    import os
    import subprocess
    import sys

    executor = tmp_path / 'pipeline-executor.sh'
    state_dir = tmp_path / 'pipeline/local-case'
    state_dir.mkdir(parents=True)
    (state_dir / 'ai-sdlc-state.json').write_text(json.dumps({'current_phase': 1}))
    marker = tmp_path / 'unexpected-execution'
    executor.write_text('#!/bin/sh\ntouch ' + str(marker) + '\nexit 0\n')
    driver = tmp_path / 'budget-cli.py'
    driver.write_text(
        'import runpy, sys\n'
        'from pathlib import Path\n'
        'import ai_sdlc_claudecode.cli as cli\n'
        f'cli.resolve_executor = lambda: Path({str(executor)!r})\n'
        f'cli.resolve_pipeline_root = lambda: Path({str(tmp_path / "pipeline")!r})\n'
        'cli.EvolvingAgent._preflight = lambda self: None\n'
        'sys.argv = ["ai-sdlc", "run", "--phase", "2", "--feature-id", "local-case", "--max-cost", "0"]\n'
        'runpy.run_module("ai_sdlc_claudecode", run_name="__main__")\n'
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(driver)], text=True, capture_output=True, timeout=15,
        env={**os.environ, 'PYTHONPATH': str(root / 'src')},
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert not marker.exists()
    checkpoint = json.loads((tmp_path / 'pipeline/local-case/ai-sdlc-state.json').read_text())
    assert checkpoint['current_iteration'] == 0
    assert checkpoint['current_phase'] == 2
    assert checkpoint['phases']['2']['status'] == 'budget_exceeded'
    assert 'Cost limit' in checkpoint['phases']['2']['stop_reason']


@pytest.mark.parametrize('signum', [2, 15])
def test_cli_shutdown_preserves_signal_exit(tmp_path, signum):
    import os
    import subprocess
    import sys

    executor = tmp_path / 'pipeline-executor.sh'
    executor.write_text('#!/bin/sh\nexit 99\n')
    driver = tmp_path / 'signal-cli.py'
    driver.write_text(
        'import os\n'
        'from pathlib import Path\n'
        'import ai_sdlc_claudecode.cli as cli\n'
        f'cli.resolve_executor = lambda: Path({str(executor)!r})\n'
        f'cli.resolve_pipeline_root = lambda: Path({str(tmp_path / "pipeline")!r})\n'
        'agent = cli.EvolvingAgent(50, 4, 5, 2, "local-case", "local signal fixture")\n'
        f'os.kill(os.getpid(), {signum})\n'
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(driver)], text=True, capture_output=True, timeout=15,
        env={**os.environ, 'PYTHONPATH': str(root / 'src')},
    )
    assert result.returncode == 128 + signum, result.stdout + result.stderr
    checkpoint = json.loads((tmp_path / 'pipeline/local-case/ai-sdlc-state.json').read_text())
    assert checkpoint['current_iteration'] == 0
    assert checkpoint['phases']['2']['status'] == 'interrupted'
    assert (tmp_path / 'pipeline/local-case/ai-sdlc-report.md').exists()


def test_runner_timeout_terminates_stage_children(tmp_path):
    import time
    executor = tmp_path / 'pipeline-executor.sh'
    marker = tmp_path / 'child-finished'
    executor.write_text('#!/bin/bash\n(sleep 1; touch child-finished) &\nwait\n')
    # Runner runs in executor.parent.parent, so use an absolute marker.
    executor.write_text(executor.read_text().replace('touch child-finished', "touch '" + str(marker) + "'"))
    result = PipelineRunner(executor, tmp_path / 'pipeline').run('feature', 'fixture', timeout_seconds=0.1)
    time.sleep(1.2)
    assert result.exit_code == 124
    assert not result.all_passed
    assert not marker.exists()


def test_runner_timeout_allows_dispatcher_to_stop_detached_model(tmp_path, monkeypatch):
    import os
    import shlex
    import signal
    import sys

    project = tmp_path / 'project'
    project.mkdir()
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    pid_file = tmp_path / 'model.pid'
    codex = bindir / 'codex'
    codex.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(pid_file)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
    codex.chmod(0o755)
    dag = tmp_path / 'dag.json'
    dag.write_text(json.dumps({'config': {'model_routes': {
        'gpt-6.1-sol': {'provider': 'codex', 'reasoning_effort': 'max'},
    }}}))
    receipt = tmp_path / 'receipt.json'
    command = [sys.executable, '-m', 'ai_sdlc_claudecode.agent', '--dag', str(dag),
               '--model', 'gpt-6.1-sol', '--project-dir', str(project), '--receipt', str(receipt)]
    executor = tmp_path / 'pipeline-executor.sh'
    executor.write_text('#!/bin/bash\n' + ' '.join(shlex.quote(arg) for arg in command) + " <<<'fixture prompt' &\nwait\n")
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('PYTHONPATH', str(root / 'src'))
    monkeypatch.setenv('PATH', str(bindir) + os.pathsep + os.environ['PATH'])
    try:
        result = PipelineRunner(executor, tmp_path / 'pipeline').run('fixture', 'local only', timeout_seconds=1)
        assert pid_file.exists(), 'fake model must have started before the runner timeout'
        pid = int(pid_file.read_text())
        assert result.exit_code == 124
        assert not result.all_passed
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert receipt.exists(), result.stdout + result.stderr
        assert json.loads(receipt.read_text())['status'] == 'failed'
    finally:
        if pid_file.exists():
            try:
                os.killpg(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
