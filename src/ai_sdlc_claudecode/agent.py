"""Dispatch configured model requests without changing host trust or approval policy.

Prompts travel over stdin. Raw CLI output stays in private temporary files; a
receipt records requested configuration separately from runtime observations.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


class _Interrupted(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


def _stop_process(process: subprocess.Popen) -> dict:
    cleanup = {"scope": "process_group", "group_signal_errors": [], "direct_signal_errors": []}
    for signum in (signal.SIGTERM, signal.SIGKILL):
        # The CLI may exit before a descendant that ignored SIGTERM.
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            cleanup["scope"] = "direct_child"
            cleanup["group_signal_errors"].append({"signal": signum, "error": str(exc)})
            if process.poll() is None:
                try:
                    process.send_signal(signum)
                except ProcessLookupError:
                    pass
                except PermissionError as child_exc:
                    cleanup["direct_signal_errors"].append({"signal": signum, "error": str(child_exc)})
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    cleanup["direct_child_exited"] = process.poll() is not None
    return cleanup


def _write_private(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def _codex_result(path: Path) -> dict:
    result = {"result": "", "usage": None, "session_id": None,
              "actual_model": None, "completed": False, "error": None}
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("event must be an object")
            except (ValueError, TypeError):
                result["error"] = f"Invalid Codex JSONL event at line {number}"
                continue
            kind = event.get("type")
            if kind == "thread.started":
                result["session_id"] = event.get("thread_id")
            if isinstance(event.get("model"), str):
                result["actual_model"] = event["model"]
            if kind == "item.completed":
                item = event.get("item", {})
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    if isinstance(item.get("text"), str):
                        result["result"] = item["text"]
            if kind == "turn.completed":
                result["completed"] = True
                result["usage"] = event.get("usage")
            # CLI retry progress is nonterminal; final completion and process exit remain required.
            reconnecting = kind == "error" and isinstance(event.get("message"), str) and event["message"].startswith("Reconnecting... ")
            if kind == "turn.failed" or (kind == "error" and not reconnecting):
                result["error"] = "Codex reported a failed turn"
    if not result["completed"] or not result["result"].strip():
        result["error"] = result["error"] or "Codex did not complete with a final message"
    return result


def _usage(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    # Codex input_tokens includes its cached subset; Claude reports it separately.
    cached = raw.get("cached_input_tokens", 0)
    incoming = raw.get("input_tokens", 0)
    outgoing = raw.get("output_tokens", 0)
    if any(type(value) is not int or value < 0 for value in (cached, incoming, outgoing)):
        raise ValueError("Invalid Codex token usage")
    if cached > incoming:
        raise ValueError("Cached token usage exceeds input token usage")
    return {"input_tokens": incoming - cached, "output_tokens": outgoing,
            "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0}


def _claude_result(path: Path) -> dict:
    raw = path.read_text()
    result = {"result": raw, "usage": None, "session_id": None,
              "actual_model": None, "completed": bool(raw.strip()),
              "error": None if raw.strip() else "Claude returned an empty response",
              "total_cost_usd": None}
    try:
        envelope = json.loads(raw)
    except ValueError:
        return result  # Old Claude binaries may still return plain text.
    if not isinstance(envelope, dict) or envelope.get("type") != "result":
        return result
    result.update({key: envelope.get(key) for key in ("result", "usage", "session_id", "total_cost_usd")})
    result["actual_model"] = envelope.get("model")
    if envelope.get("is_error") or not isinstance(result["result"], str) or not result["result"].strip():
        result.update(completed=False, error="Claude returned an error or missing final message")
    cost = result["total_cost_usd"]
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        raise ValueError("Invalid measured Claude cost")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dag", type=Path, required=True)
    parser.add_argument("--model", help="Requested model; defaults to config.review_model or haiku")
    parser.add_argument("--inspect", choices=("model", "provider", "configured"),
                        help="Resolve routing without invoking a model")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="workspace-write")
    parser.add_argument("--output-format", choices=("json", "text"), default="json")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--timeout", type=float, help="Wall-clock seconds; 0 disables the limit")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.dag.read_text()).get("config", {})
        args.model = args.model or config.get("review_model", "haiku")
        if not isinstance(args.model, str) or not args.model:
            raise ValueError("model must be a nonempty string")
        routes = config.get("model_routes", {})
        route = routes.get(args.model, {"provider": "claude"})
        provider = route.get("provider", "claude")
        if provider not in ("codex", "claude"):
            raise ValueError(f"Unsupported provider: {provider}")
        if args.inspect:
            values = {"model": args.model, "provider": provider,
                      "configured": str(args.model in routes).lower()}
            print(values[args.inspect])
            return 0
        profile = route.get("profile")
        effort = route.get("reasoning_effort", "max") if provider == "codex" else None
        if provider == "codex" and (not isinstance(effort, str) or not effort):
            raise ValueError("reasoning_effort must be a nonempty string")
        if profile is not None and (not isinstance(profile, str) or not profile):
            raise ValueError("profile must be a nonempty string")
        if args.sandbox == "workspace-write":
            args.project_dir.mkdir(parents=True, exist_ok=True)
        project = args.project_dir.resolve(strict=True)
        if provider == "codex":
            command = ["codex", "exec", "--json", "-C", str(project),
                       "--sandbox", args.sandbox, "-m", args.model,
                       "-c", "model_reasoning_effort=" + json.dumps(effort)]
            if profile:
                command.extend(["--profile", profile])
            command.append("-")
        else:
            command = ["claude", "--print", "--model", args.model]
            if args.output_format == "json" and os.environ.get("AI_SDLC_CLAUDE_JSON", "1") != "0":
                command.extend(["--output-format", "json"])
    except (ValueError, OSError, AttributeError) as exc:
        print(f"Model routing failed: {exc}", file=sys.stderr)
        return 1

    raw_dir = Path(tempfile.mkdtemp(prefix="ai-sdlc-agent-", dir="/private/tmp"))
    raw_path, stderr_path = raw_dir / "stdout.jsonl", raw_dir / "stderr.log"
    receipt = args.receipt or raw_dir / "receipt.json"
    record = {"provider": provider, "requested_model": args.model,
              "actual_model": None, "profile": profile, "reasoning_effort": effort,
              "sandbox": args.sandbox, "project_dir": str(project),
              "session_id": None, "status": "failed", "completed": False,
              "usage": None, "total_cost_usd": None,
              "raw_output_path": str(raw_path), "stderr_path": str(stderr_path),
              "started_at": datetime.now(timezone.utc).isoformat()}
    start = time.monotonic()
    timeout = None if args.timeout == 0 else args.timeout
    record["timeout_seconds"] = timeout
    code, error, normalized, output = 1, None, {}, ""
    process = None

    def interrupted(signum, _frame):
        raise _Interrupted(signum)

    previous_handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with raw_path.open("w") as stdout, stderr_path.open("w") as stderr:
            os.fchmod(stdout.fileno(), 0o600)
            os.fchmod(stderr.fileno(), 0o600)
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout,
                                       stderr=stderr, text=True, cwd=project,
                                       start_new_session=True)
            try:
                process.communicate(sys.stdin.read(), timeout=timeout)
                code = process.returncode
            except subprocess.TimeoutExpired:
                code, error = 124, "Model invocation timed out"
                record["cleanup"] = _stop_process(process)
        parsed = _codex_result(raw_path) if provider == "codex" else _claude_result(raw_path)
        record.update({key: parsed[key] for key in ("session_id", "actual_model", "usage", "completed")})
        record["total_cost_usd"] = parsed.get("total_cost_usd")
        normalized = _usage(parsed["usage"]) if provider == "codex" else parsed["usage"] or {}
        output = parsed["result"]
        error = error or parsed["error"]
        if error and code == 0:
            code = 1
        if code != 0:
            error = error or f"Model CLI exited with status {code}"
    except (OSError, ValueError) as exc:
        code, error = 1, str(exc)
        if process is not None:
            record["cleanup"] = _stop_process(process)
    except BaseException as exc:
        # Codex has its own process group; forward shutdown rather than orphan it.
        for sig in previous_handlers:
            signal.signal(sig, signal.SIG_IGN)
        if process is not None:
            record["cleanup"] = _stop_process(process)
        if not isinstance(exc, _Interrupted):
            raise
        code, error = 128 + exc.signum, f"Model invocation interrupted by signal {exc.signum}"
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    record.update({"status": "complete" if code == 0 else "failed", "exit_code": code,
                   "error": error, "duration_seconds": round(time.monotonic() - start, 3)})
    _write_private(receipt, record)
    envelope = {"type": "result", "is_error": code != 0,
                "result": output if code == 0 else error, "provider": provider,
                "usage": normalized, "total_cost_usd": record["total_cost_usd"],
                "session_id": record["session_id"], "requested_model": args.model,
                "actual_model": record["actual_model"], "receipt_path": str(receipt)}
    if args.output_format == "json":
        print(json.dumps(envelope, ensure_ascii=False))
    elif code == 0:
        print(output)
    if code:
        print(f"Model invocation failed; receipt: {receipt}", file=sys.stderr)
    return code if 0 <= code <= 255 else 1


if __name__ == "__main__":
    raise SystemExit(main())
