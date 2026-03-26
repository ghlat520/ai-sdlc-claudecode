"""CLI entry point — `ai-sdlc run`, `ai-sdlc status`, `ai-sdlc report`.

Usage:
    ai-sdlc run --max-cost 50 --max-hours 4
    ai-sdlc run --phase 1 --max-cost 10          # mock only
    ai-sdlc status                                # show current state
    ai-sdlc report                                # generate markdown report
    ai-sdlc reset                                 # clear state for fresh start
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from ai_sdlc_claudecode.config import (
    BOLD, CYAN, GREEN, MAX_ITERATIONS_PER_PHASE, NC, RED, YELLOW,
    resolve_executor, resolve_pipeline_root,
)
from ai_sdlc_claudecode.engine import ErrorEngine
from ai_sdlc_claudecode.runner import PipelineRunner
from ai_sdlc_claudecode.state import EvolveState


def _log(msg: str, color: str = NC) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"{color}[{ts}] {msg}{NC}", flush=True)


# ---------------------------------------------------------------------------
# ai-sdlc run
# ---------------------------------------------------------------------------

class EvolvingAgent:
    """Self-evolving autonomous agent that runs pipeline iterations and learns."""

    def __init__(
        self,
        max_cost: float,
        max_hours: float,
        max_failures: int,
        start_phase: int,
        feature_id: str,
        description: str,
    ) -> None:
        self.feature_id = feature_id
        self.description = description
        self.start_phase = start_phase

        pipeline_root = resolve_pipeline_root()
        executor = resolve_executor()

        self.errors_dir = pipeline_root / feature_id / "evolve"
        self.state_path = pipeline_root / "ai-sdlc-state.json"
        self.report_path = pipeline_root / "ai-sdlc-report.md"

        self.engine = ErrorEngine(self.errors_dir)
        self.state = EvolveState.create(
            state_file=self.state_path,
            max_cost=max_cost,
            max_hours=max_hours,
            max_failures=max_failures,
            start_phase=start_phase,
        )
        self.runner = PipelineRunner(
            executor_path=executor,
            pipeline_root=pipeline_root,
        )

        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def run(self) -> None:
        self._preflight()
        self._banner()

        try:
            if self.start_phase <= 1:
                self._phase(1, "Mock Mode (structure validation)", mock_review=True)
            if self.start_phase <= 2:
                self._phase(2, "Real Claude CLI (13 stages)")
            if self.start_phase <= 3:
                self._phase(
                    3, "ai-media-platform (S3-S10)",
                    start_from="S3",
                    feature_override="ai-media-platform",
                    description_override="Build ai-media-platform features S3-S10",
                )
        finally:
            self._finalize()

    def _phase(
        self,
        phase: int,
        label: str,
        mock_review: bool = False,
        start_from: Optional[str] = None,
        feature_override: Optional[str] = None,
        description_override: Optional[str] = None,
    ) -> None:
        _log(f"{'=' * 60}", BOLD)
        _log(f"Phase {phase}: {label}", BOLD + CYAN)
        _log(f"{'=' * 60}", BOLD)

        feat = feature_override or self.feature_id
        desc = description_override or self.description
        pipeline_root = resolve_pipeline_root()

        for iteration in range(MAX_ITERATIONS_PER_PHASE):
            ok, reason = self.state.check_budget()
            if not ok:
                _log(f"Budget exceeded: {reason}", RED)
                break

            if self.state.check_stall():
                _log(f"Stalled: {self.state.consecutive_no_improve} iterations without improvement", YELLOW)
                break

            _log(f"Phase {phase}, Iteration {iteration + 1}/{MAX_ITERATIONS_PER_PHASE}", CYAN)

            self.engine.write_augments()
            self.runner.auto_approve_gates(feat)

            result = self.runner.run(
                feature_id=feat,
                description=desc,
                mock_review=mock_review,
                resume=(iteration > 0),
                start_from=start_from if iteration == 0 else None,
                evolve_errors_dir=self.errors_dir,
                cost_limit=self.state.max_cost_usd - self.state.cost_spent_usd,
            )

            new_errors = self.engine.read_failures(iteration, phase, feat)

            if result.stages_passed > 0:
                self._mark_passed(feat, pipeline_root)

            cost_delta = max(result.cost_usd - self._last_cost(feat, pipeline_root), 0.0)

            self.state = self.state.update_iteration(
                phase=phase,
                stages_passed=result.stages_passed,
                errors_learned=len(new_errors),
                cost_delta=cost_delta,
            )
            self.state.checkpoint()

            promoted = self.engine.promote_to_skill()
            if promoted:
                _log(f"Promoted {len(promoted)} fixes to skills", GREEN)

            _log(
                f"Stages: {result.stages_passed}/{result.total_stages}, "
                f"Errors: {len(new_errors)}, Cost: ${self.state.cost_spent_usd:.2f}",
                GREEN if result.all_passed else YELLOW,
            )

            if result.all_passed:
                _log(f"Phase {phase} COMPLETE!", GREEN + BOLD)
                self.state = self.state.complete_phase(phase)
                self.state.checkpoint()
                break
        else:
            _log(f"Phase {phase}: max iterations reached", YELLOW)

    def _preflight(self) -> None:
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                _log(f"Claude CLI: {r.stdout.strip()}", GREEN)
            else:
                _log("Claude CLI unavailable (mock mode only)", YELLOW)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _log("Claude CLI not found (mock mode only)", YELLOW)

        _log(f"Executor: {self.runner.executor_path}", GREEN)

    def _banner(self) -> None:
        print(f"\n{BOLD}{CYAN}")
        print("  ╔══════════════════════════════════════════════════╗")
        print("  ║     Self-Evolving Autonomous Agent System       ║")
        print("  ║     Learn from errors. Never repeat mistakes.   ║")
        print("  ╚══════════════════════════════════════════════════╝")
        print(NC)
        _log(f"Cost limit: ${self.state.max_cost_usd:.2f}", CYAN)
        _log(f"Time limit: {self.state.max_runtime_hours:.1f}h", CYAN)
        _log(f"Stall threshold: {self.state.max_consecutive_failures} iterations", CYAN)
        _log(f"Feature: {self.feature_id}", CYAN)
        stats = self.engine.get_stats()
        if stats["total_errors"] > 0:
            _log(f"Resuming: {stats['total_errors']} known errors", YELLOW)
        print()

    def _mark_passed(self, feature_id: str, pipeline_root: Path) -> None:
        sf = pipeline_root / feature_id / "state.json"
        if not sf.exists():
            return
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            for sid, sd in data.get("stages", {}).items():
                if sd.get("status") == "passed":
                    self.engine.mark_success(sid)
        except (json.JSONDecodeError, OSError):
            pass

    def _last_cost(self, feature_id: str, pipeline_root: Path) -> float:
        sf = pipeline_root / feature_id / "state.json"
        if not sf.exists():
            return 0.0
        try:
            return json.loads(sf.read_text(encoding="utf-8")).get("cost", {}).get("estimated_usd", 0.0)
        except (json.JSONDecodeError, OSError):
            return 0.0

    def _shutdown(self, signum: int, frame: object) -> None:
        _log("Shutdown signal received, saving checkpoint...", YELLOW)
        self.state.checkpoint()
        self.state.generate_report(self.report_path)
        _log(f"Report: {self.report_path}", GREEN)
        sys.exit(0)

    def _finalize(self) -> None:
        self.state.checkpoint()
        self.state.generate_report(self.report_path)
        stats = self.engine.get_stats()
        print(f"\n{BOLD}{CYAN}{'=' * 60}{NC}")
        _log("Evolution Complete", BOLD + GREEN)
        _log(f"Iterations: {self.state.current_iteration}", CYAN)
        _log(f"Cost: ${self.state.cost_spent_usd:.2f}", CYAN)
        _log(f"Errors learned: {stats['total_errors']}", CYAN)
        _log(f"Fixes promoted: {stats['promoted_fixes']}", CYAN)
        _log(f"Report: {self.report_path}", CYAN)
        print(f"{BOLD}{CYAN}{'=' * 60}{NC}\n")


def _cmd_run(args: argparse.Namespace) -> None:
    agent = EvolvingAgent(
        max_cost=args.max_cost,
        max_hours=args.max_hours,
        max_failures=args.max_failures,
        start_phase=args.phase,
        feature_id=args.feature_id,
        description=args.description,
    )
    agent.run()


# ---------------------------------------------------------------------------
# ai-sdlc status
# ---------------------------------------------------------------------------

def _cmd_status(args: argparse.Namespace) -> None:
    pipeline_root = resolve_pipeline_root()
    state_file = pipeline_root / "ai-sdlc-state.json"

    if not state_file.exists():
        print("No state found. Run `ai-sdlc run` first.")
        return

    data = json.loads(state_file.read_text(encoding="utf-8"))

    print(f"\n{BOLD}{CYAN}AI-SDLC Agent Status{NC}")
    print(f"  Started:    {data.get('start_time', 'N/A')}")
    print(f"  Phase:      {data.get('current_phase', '?')}")
    print(f"  Iteration:  {data.get('current_iteration', 0)}")
    print(f"  Cost:       ${data.get('cost_spent_usd', 0):.2f} / ${data.get('max_cost_usd', 0):.2f}")
    print(f"  Elapsed:    {data.get('elapsed_hours', 0):.2f}h / {data.get('max_runtime_hours', 0):.1f}h")
    print(f"  Stalls:     {data.get('consecutive_no_improve', 0)}")

    phases = data.get("phases", {})
    if phases:
        print(f"\n  {'Phase':<8} {'Status':<12} {'Iters':<8} {'Best':<8} {'Errors':<8}")
        print(f"  {'─' * 44}")
        for num in sorted(phases, key=int):
            p = phases[num]
            sp = p.get("stages_passed", [])
            best = max(sp) if sp else 0
            print(f"  {num:<8} {p['status']:<12} {p.get('iterations', 0):<8} {best:<8} {p.get('errors_learned', 0):<8}")

    trend = data.get("improvement_trend", [])
    if trend:
        print(f"\n  Trend: {' -> '.join(str(s) for s in trend)}")
    print()


# ---------------------------------------------------------------------------
# ai-sdlc report
# ---------------------------------------------------------------------------

def _cmd_report(args: argparse.Namespace) -> None:
    pipeline_root = resolve_pipeline_root()
    state_file = pipeline_root / "ai-sdlc-state.json"
    report_path = pipeline_root / "ai-sdlc-report.md"

    if not state_file.exists():
        print("No state found. Run `ai-sdlc run` first.")
        return

    state = EvolveState.create(state_file)
    state.generate_report(report_path)
    print(f"Report generated: {report_path}")


# ---------------------------------------------------------------------------
# ai-sdlc extract-json
# ---------------------------------------------------------------------------

def _cmd_extract_json(args: argparse.Namespace) -> None:
    from ai_sdlc_claudecode.extract import extract_and_save

    text: Optional[str] = None
    input_path: Optional[str] = args.input_file

    if input_path is None:
        # Read from stdin
        text = sys.stdin.read()

    ok = extract_and_save(args.output_path, input_path=input_path, text=text)
    if ok:
        print(f"Extracted JSON to {args.output_path}")
    else:
        print("WARNING: Could not extract JSON from input", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# ai-sdlc reset
# ---------------------------------------------------------------------------

def _cmd_reset(args: argparse.Namespace) -> None:
    pipeline_root = resolve_pipeline_root()
    state_file = pipeline_root / "ai-sdlc-state.json"

    if not state_file.exists():
        print("Nothing to reset.")
        return

    if not args.force:
        answer = input(f"Delete {state_file}? [y/N] ")
        if answer.lower() != "y":
            print("Cancelled.")
            return

    state_file.unlink()
    print(f"Deleted: {state_file}")

    report = pipeline_root / "ai-sdlc-report.md"
    if report.exists():
        report.unlink()
        print(f"Deleted: {report}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ai-sdlc",
        description="Self-Evolving Autonomous Agent System",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    sub = parser.add_subparsers(dest="command", required=True)

    # ai-sdlc run
    run_p = sub.add_parser("run", help="Start the evolving agent")
    run_p.add_argument("--max-cost", type=float, default=50.0, help="Max cost in USD (default: 50)")
    run_p.add_argument("--max-hours", type=float, default=4.0, help="Max runtime in hours (default: 4)")
    run_p.add_argument("--max-failures", type=int, default=5, help="Max stall iterations (default: 5)")
    run_p.add_argument("--phase", type=int, default=1, choices=[1, 2, 3], help="Start phase (1=mock, 2=real, 3=ai-media)")
    run_p.add_argument("--feature-id", default="ai-sdlc-test", help="Feature ID (default: ai-sdlc-test)")
    run_p.add_argument("--description", default="Self-evolving agent test run", help="Feature description")
    run_p.set_defaults(func=_cmd_run)

    # ai-sdlc status
    status_p = sub.add_parser("status", help="Show current state")
    status_p.set_defaults(func=_cmd_status)

    # ai-sdlc report
    report_p = sub.add_parser("report", help="Generate markdown report")
    report_p.set_defaults(func=_cmd_report)

    # ai-sdlc extract-json
    extract_p = sub.add_parser("extract-json", help="Extract JSON from Claude output")
    extract_p.add_argument("output_path", help="Path to write extracted JSON")
    extract_p.add_argument("-f", "--input-file", help="Read from file instead of stdin")
    extract_p.set_defaults(func=_cmd_extract_json)

    # ai-sdlc reset
    reset_p = sub.add_parser("reset", help="Clear state for fresh start")
    reset_p.add_argument("-f", "--force", action="store_true", help="Skip confirmation")
    reset_p.set_defaults(func=_cmd_reset)

    args = parser.parse_args()
    args.func(args)
