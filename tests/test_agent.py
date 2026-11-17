"""Model dispatch through real subprocess boundaries, without paid model calls."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import signal

import pytest

from tests.test_pipeline_contract import executor_case


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def agent_case(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls.jsonl"
    executable = bindir / "codex"
    executable.write_text('''#!/usr/bin/env python3
import json, os, sys
prompt = sys.stdin.read()
with open(os.environ['FAKE_CALLS'], 'a') as stream:
    stream.write(json.dumps({'argv': sys.argv[1:], 'prompt': prompt}) + '\\n')
print(json.dumps({'type': 'thread.started', 'thread_id': 'fixture-session'}))
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'first line\\nsecond line\\tvalue'}}))
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 4}}))
''')
    executable.chmod(0o755)
    dag = tmp_path / "dag.json"
    dag.write_text(json.dumps({"config": {"model_routes": {
        "gpt-6.1-sol": {"provider": "codex", "reasoning_effort": "max"},
        "glm-5.3": {"provider": "codex", "profile": "glm", "reasoning_effort": "max"},
    }}}))
    receipt = tmp_path / "receipt.json"
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "FAKE_CALLS": str(calls), "PYTHONPATH": str(ROOT / "src")}

    def run(model="gpt-6.1-sol", *args, prompt="private prompt", **env_overrides):
        return subprocess.run(
            [sys.executable, "-m", "ai_sdlc_claudecode.agent", "--dag", str(dag),
             "--project-dir", str(tmp_path), "--model", model, "--receipt", str(receipt),
             *args], input=prompt, text=True, capture_output=True,
            env={**env, **env_overrides}, timeout=15,
        )

    return run, executable, calls, receipt, dag


@pytest.mark.parametrize("model,profile", [("gpt-6.1-sol", None), ("glm-5.3", "glm")])
def test_codex_route_requests_model_effort_and_reports_completion(agent_case, model, profile):
    run, _, calls, receipt, _ = agent_case
    result = run(model, "--output-format", "json", "--sandbox", "workspace-write")
    assert result.returncode == 0, result.stderr
    call = json.loads(calls.read_text())
    argv = call["argv"]
    assert argv[:2] == ["exec", "--json"]
    assert argv[argv.index("-m") + 1] == model
    assert argv[argv.index("-c") + 1] == 'model_reasoning_effort="max"'
    assert argv[argv.index("-C") + 1] == str(receipt.parent)
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert call["prompt"] == "private prompt"
    assert "private prompt" not in argv
    assert not any("bypass" in value or "ignore" in value or "skip" in value for value in argv)
    if profile:
        assert argv[argv.index("--profile") + 1] == profile
    else:
        assert "--profile" not in argv
    response = json.loads(result.stdout)
    assert response["result"] == "first line\nsecond line\tvalue"
    assert response["total_cost_usd"] is None
    assert response["usage"]["input_tokens"] == 80
    record = json.loads(receipt.read_text())
    assert record["requested_model"] == model
    assert record["actual_model"] is None
    assert record["profile"] == profile
    assert record["reasoning_effort"] == "max"
    assert record["session_id"] == "fixture-session"
    assert record["status"] == "complete"
    assert record["usage"]["input_tokens"] == 100
    assert Path(record["raw_output_path"]).stat().st_mode & 0o077 == 0
    assert receipt.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("legacy", [False, True])
def test_unmapped_models_keep_claude_envelope_and_legacy_support(agent_case, legacy):
    run, executable, calls, receipt, _ = agent_case
    claude = executable.with_name("claude")
    claude.write_text('''#!/usr/bin/env python3
import json, os, sys
prompt = sys.stdin.read()
with open(os.environ['FAKE_CALLS'], 'a') as stream:
    stream.write(json.dumps({'argv': sys.argv[1:], 'prompt': prompt}) + '\\n')
if '--output-format' in sys.argv:
    print(json.dumps({'type': 'result', 'result': 'line one\\nline two\\ttab',
                      'session_id': 'claude-session', 'total_cost_usd': 0.125,
                      'usage': {'input_tokens': 30, 'output_tokens': 9}}))
else:
    print('legacy response')
''')
    claude.chmod(0o755)
    result = run("sonnet", AI_SDLC_CLAUDE_JSON="0" if legacy else "1")
    assert result.returncode == 0, result.stderr
    call = json.loads(calls.read_text())
    assert call["argv"][:3] == ["--print", "--model", "sonnet"]
    assert call["prompt"] == "private prompt"
    assert ("--output-format" in call["argv"]) is not legacy
    response = json.loads(result.stdout)
    assert response["provider"] == "claude"
    assert response["result"] == ("legacy response\n" if legacy else "line one\nline two\ttab")
    assert response["total_cost_usd"] == (None if legacy else 0.125)
    record = json.loads(receipt.read_text())
    assert record["status"] == "complete"
    assert record["session_id"] == (None if legacy else "claude-session")


def test_review_model_selection_is_explicit_and_defaults_to_haiku(agent_case):
    run, _, calls, receipt, dag = agent_case
    def inspect(*args):
        return subprocess.run(
            [sys.executable, "-m", "ai_sdlc_claudecode.agent", "--dag", str(dag),
             "--inspect", *args], text=True, capture_output=True,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=5,
        )
    default = inspect("model")
    assert default.returncode == 0, default.stderr
    assert default.stdout.strip() == "haiku"
    data = json.loads(dag.read_text())
    data["config"]["review_model"] = "glm-5.3"
    dag.write_text(json.dumps(data))
    assert inspect("model").stdout.strip() == "glm-5.3"
    assert inspect("provider").stdout.strip() == "codex"
    assert inspect("configured").stdout.strip() == "true"
    assert not calls.exists()
    assert not receipt.exists()


def test_write_invocation_creates_fresh_project_but_read_only_never_does(agent_case):
    run, _, calls, receipt, _ = agent_case
    project = receipt.parent / "new-project"
    denied = run("gpt-6.1-sol", "--project-dir", str(project), "--sandbox", "read-only")
    assert denied.returncode != 0
    assert not project.exists()
    assert not calls.exists()
    allowed = run("gpt-6.1-sol", "--project-dir", str(project), "--sandbox", "workspace-write")
    assert allowed.returncode == 0, allowed.stderr
    assert project.is_dir()
    args = json.loads(calls.read_text())["argv"]
    assert args[args.index("-C") + 1] == str(project)


@pytest.mark.parametrize("mode", ["exit", "incomplete", "missing_final", "turn_failed", "malformed", "missing_cli", "timeout"])
def test_codex_failures_never_become_success(agent_case, mode):
    run, executable, _, receipt, _ = agent_case
    bodies = {
        "exit": "raise SystemExit(7)",
        "incomplete": "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'partial'}}))",
        "missing_final": "print(json.dumps({'type':'turn.completed'}))",
        "turn_failed": "print(json.dumps({'type':'turn.failed','error':{'message':'fixture error'}}))",
        "malformed": "print('invalid json')",
        "timeout": "import time; time.sleep(4)",
    }
    if mode == "missing_cli":
        executable.unlink()
        # Stop lookup before the host's paid Codex executable can be reached.
        result = run(PATH=str(executable.parent))
    else:
        executable.write_text("#!" + sys.executable + "\nimport json,sys\nsys.stdin.read()\n" + bodies[mode] + "\n")
        executable.chmod(0o755)
        result = run("gpt-6.1-sol", "--timeout", "0.1" if mode == "timeout" else "3")
    assert result.returncode != 0
    assert json.loads(result.stdout)["is_error"] is True
    record = json.loads(receipt.read_text())
    assert record["status"] == "failed"
    assert record["exit_code"] != 0
    assert record["total_cost_usd"] is None


def test_completed_turn_with_cli_shutdown_timeout_still_fails_closed(agent_case):
    """A final model result must not conceal a CLI that missed its exit deadline."""
    run, executable, _, receipt, _ = agent_case
    executable.write_text(
        "#!/bin/sh\n/bin/cat >/dev/null\n"
        "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"cleanup-fixture\"}' "
        "'{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"completed result\"}}' "
        "'{\"type\":\"turn.completed\"}'\n/bin/sleep 30\n"
    )
    executable.chmod(0o755)
    # Allow the fixture to emit its final event before exercising stuck cleanup.
    result = run("gpt-6.1-sol", "--timeout", "2")
    record = json.loads(receipt.read_text())
    assert result.returncode == 124
    assert record["completed"] is True
    assert record["status"] == "failed"
    assert json.loads(result.stdout)["is_error"] is True
    assert 'completed result' in Path(record["raw_output_path"]).read_text()


@pytest.mark.parametrize("ending,exit_code,expected_success", [
    ("completed", 0, True),
    ("turn_failed", 0, False),
    ("incomplete", 0, False),
    ("completed", 7, False),
    ("fatal_then_completed", 0, False),
])
def test_reconnect_progress_requires_successful_cli_and_final_turn(agent_case, ending, exit_code, expected_success):
    run, executable, _, receipt, _ = agent_case
    events = [
        {"type": "thread.started", "thread_id": "reconnecting-fixture"},
        {"type": "turn.started"},
        {"type": "error", "message": "Reconnecting... 1/5 (stream disconnected before completion: request timed out)"},
    ]
    if ending == "fatal_then_completed":
        events.append({"type": "error", "message": "Model request was rejected"})
    if ending in ("completed", "fatal_then_completed"):
        events.extend([
            {"type": "item.completed", "item": {"type": "agent_message", "text": "finished after reconnect"}},
            {"type": "turn.completed"},
        ])
    elif ending == "turn_failed":
        events.append({"type": "turn.failed", "error": {"message": "Retries exhausted"}})
    executable.write_text(
        "#!" + sys.executable + "\nimport json,sys\nsys.stdin.read()\n"
        + "events = json.loads(" + repr(json.dumps(events)) + ")\n"
        + "for event in events: print(json.dumps(event))\n"
        + "raise SystemExit(" + str(exit_code) + ")\n"
    )
    executable.chmod(0o755)
    result = run("glm-5.3")
    record = json.loads(receipt.read_text())
    assert (result.returncode == 0) is expected_success
    assert record["status"] == ("complete" if expected_success else "failed")
    assert json.loads(result.stdout)["is_error"] is not expected_success
    assert "Reconnecting..." in Path(record["raw_output_path"]).read_text()


def test_executor_routes_main_refinement_and_ai_gate_through_codex(executor_case):
    dag, path, env, run = executor_case
    dag["config"].update({"review_model": "glm-5.3", "model_routes": {
        "gpt-6.1-sol": {"provider": "codex", "reasoning_effort": "max"},
        "glm-5.3": {"provider": "codex", "profile": "glm", "reasoning_effort": "max"},
    }})
    dag["stages"]["first"]["agents"][0]["model"] = "gpt-6.1-sol"
    dag["stages"]["first"]["gate"] = {"type": "ai-review", "adversarial": {
        "enabled": True, "min_diff_lines": 0,
        "passes": [{"role": "adversarial", "model": "gpt-6.1-sol"}],
    }}
    dag["stages"]["first"]["review_passes"] = [{"role": "audit", "model": "glm-5.3"}]
    calls = path.with_name("model-calls.jsonl")
    env["FAKE_ROUTING_CALLS"] = str(calls)
    codex = Path(env["PATH"].split(os.pathsep)[0]) / "codex"
    codex.write_text('''#!/usr/bin/env python3
import json, os, sys
prompt = sys.stdin.read()
kind = 'probe' if prompt == 'Reply with exactly: OK' else 'refinement' if '## Primary Agent Output' in prompt else 'main' if 'FAKE_STAGE:' in prompt else 'adversarial' if 'You are an ADVERSARIAL' in prompt else 'gate'
with open(os.environ['FAKE_ROUTING_CALLS'], 'a') as stream:
    stream.write(json.dumps({'argv': sys.argv[1:], 'kind': kind}) + '\\n')
text = 'OK' if kind == 'probe' else json.dumps({'stage_id':'S8','status':'complete','summary':'line one\\nline two\\ttab'}) if kind in ('main','refinement') else json.dumps({'scores':{'correctness':90},'overall_score':90,'passed':True,'summary':'fixture review','issues':[]})
print(json.dumps({'type':'thread.started','thread_id':'executor-session'}))
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':20,'output_tokens':4}}))
''')
    codex.chmod(0o755)
    result, state = run("--stages", "S8")
    assert result.returncode == 0, result.stdout + result.stderr
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [call["kind"] for call in recorded] == ["main", "refinement", "probe", "gate", "adversarial"]
    for call in recorded:
        args = call["argv"]
        assert args[args.index("-m") + 1] == ("gpt-6.1-sol" if call["kind"] in ("main", "adversarial") else "glm-5.3")
        assert args[args.index("--sandbox") + 1] == ("workspace-write" if call["kind"] == "main" else "read-only")
    assert state["stages"]["S8"]["status"] == "passed"
    output_dir = Path(env["PIPELINE_ROOT"]) / "fixture" / "S8-first"
    assert json.loads((output_dir / "output.json").read_text())["summary"] == "line one\nline two\ttab"
    receipts = list((output_dir / ".attempts").glob("*/*model*.json"))
    assert len(receipts) == 5
    assert all(json.loads(receipt.read_text())["total_cost_usd"] is None for receipt in receipts)
    events = [json.loads(line) for line in (output_dir.parent / "events.jsonl").read_text().splitlines()]
    assert not any(event.get("data", {}).get("source") == "claude_json" for event in events)
    assert "gpt-6.1-sol  USD cost unknown" in result.stdout
    assert "dollar limit covers known costs only" in result.stdout


def test_configured_gate_probe_failure_stops_without_claude_fallback(agent_case):
    _, executable, calls, _, dag = agent_case
    config = json.loads(dag.read_text())
    config["config"]["review_model"] = "glm-5.3"
    dag.write_text(json.dumps(config))
    executable.write_text("#!" + sys.executable + "\nraise SystemExit(9)\n")
    executable.chmod(0o755)
    claude = executable.with_name("claude")
    claude.write_text("#!" + sys.executable + "\nfrom pathlib import Path\nPath(" + repr(str(calls)) + ").touch()\nraise SystemExit(0)\n")
    claude.chmod(0o755)
    output = dag.with_name("output.json")
    output.write_text('{"stage_id":"S8","status":"complete","summary":"fixture"}')
    result = subprocess.run(
        ["bash", str(ROOT / "ai-review-checker.sh"), "S8", str(output)],
        text=True, capture_output=True, timeout=10,
        env={**os.environ, "PATH": str(executable.parent) + os.pathsep + os.environ["PATH"],
             "PIPELINE_DAG_FILE": str(dag), "PROJECT_CODE_DIR": str(dag.parent)},
    )
    assert result.returncode != 0
    assert "Configured model route failed" in result.stdout
    assert not calls.exists()
    receipt = output.parent / ".attempts" / "standalone" / "gate-probe-model.json"
    assert json.loads(receipt.read_text())["status"] == "failed"


@pytest.mark.parametrize("termination_signal", [signal.SIGINT, signal.SIGTERM])
def test_interruption_stops_detached_model_process(agent_case, termination_signal):
    _, executable, _, receipt, dag = agent_case
    child_pid = receipt.with_name("child.pid")
    executable.write_text("#!" + sys.executable + "\nimport os,time\nfrom pathlib import Path\nPath(" + repr(str(child_pid)) + ").write_text(str(os.getpid()))\ntime.sleep(30)\n")
    executable.chmod(0o755)
    process = subprocess.Popen(
        [sys.executable, "-m", "ai_sdlc_claudecode.agent", "--dag", str(dag),
         "--model", "gpt-6.1-sol", "--project-dir", str(receipt.parent), "--receipt", str(receipt)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "PATH": str(executable.parent) + os.pathsep + os.environ["PATH"],
             "PYTHONPATH": str(ROOT / "src")},
    )
    try:
        deadline = time.monotonic() + 5
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid.exists(), "model process did not start"
        pid = int(child_pid.read_text())
        process.send_signal(termination_signal)
        stdout, stderr = process.communicate("fixture prompt", timeout=5)
        assert process.returncode != 0
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        record = json.loads(receipt.read_text())
        assert record["status"] == "failed"
        assert record["exit_code"] == 128 + termination_signal
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        if child_pid.exists():
            try:
                os.killpg(int(child_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
