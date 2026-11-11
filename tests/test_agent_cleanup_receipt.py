"""OS signal failures must retain the public failed-invocation receipt."""

import errno
import io
import json
import os
import signal
import subprocess

import pytest

from ai_sdlc_claudecode import agent


@pytest.mark.parametrize("denied_signal, deny_child", [
    (signal.SIGTERM, False),
    (signal.SIGKILL, False),
    (signal.SIGTERM, True),
])
def test_timeout_retains_receipt_when_group_signalling_is_denied(
    tmp_path, monkeypatch, capsys, denied_signal, deny_child
):
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n/bin/cat >/dev/null\nexec /bin/sleep 20\n")
    executable.chmod(0o755)
    dag = tmp_path / "dag.json"
    dag.write_text(json.dumps({"config": {"model_routes": {
        "glm-5.3": {"provider": "codex", "profile": "glm", "reasoning_effort": "max"}
    }}}))
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(agent.sys, "stdin", io.StringIO("fixture prompt"))
    real_popen, real_killpg = subprocess.Popen, os.killpg
    children = []

    def start(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        send_signal = process.send_signal
        children.append((process, send_signal))
        if deny_child:
            def denied(_signal):
                raise PermissionError(errno.EPERM, "fixture child signal denied")
            process.send_signal = denied
        return process

    def signal_group(pid, signum):
        if signum == denied_signal or deny_child:
            raise PermissionError(errno.EPERM, "fixture group signal denied")
        real_killpg(pid, signum)

    monkeypatch.setattr(agent.subprocess, "Popen", start)
    monkeypatch.setattr(agent.os, "killpg", signal_group)
    try:
        code = agent.main([
            "--dag", str(dag), "--project-dir", str(tmp_path), "--model", "glm-5.3",
            "--receipt", str(receipt), "--timeout", "0.15", "--output-format", "json"
        ])
        record = json.loads(receipt.read_text())
        assert code == record["exit_code"] == 124
        assert record["status"] == "failed"
        assert record["error"] == "Model invocation timed out"
        assert json.loads(capsys.readouterr().out)["is_error"] is True
        assert record["cleanup"]["scope"] == "direct_child"
        assert record["cleanup"]["group_signal_errors"]
        assert record["cleanup"]["direct_child_exited"] is (not deny_child)
        assert receipt.stat().st_mode & 0o077 == 0
    finally:
        for process, send_signal in children:
            if process.poll() is None:
                send_signal(signal.SIGKILL)
                process.wait(timeout=3)
