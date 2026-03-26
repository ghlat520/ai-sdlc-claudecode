"""Evolve State Manager — iteration progress, budgets, stall detection.

All updates return new state instances (immutable pattern).
Checkpoints are atomic writes to disk.
"""

from __future__ import annotations

import json
import tempfile
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PhaseState:
    """Immutable state for a single phase."""

    status: str  # "pending" | "running" | "complete" | "stalled" | "budget_exceeded"
    iterations: int = 0
    stages_passed: tuple[int, ...] = ()
    errors_learned: int = 0


@dataclass(frozen=True)
class EvolveState:
    """Immutable state of the evolving agent."""

    state_file: Path
    start_time: float
    current_phase: int
    current_iteration: int
    max_cost_usd: float
    max_runtime_hours: float
    max_consecutive_failures: int
    cost_spent_usd: float = 0.0
    elapsed_hours: float = 0.0
    phases: dict[int, PhaseState] = field(default_factory=dict)
    consecutive_no_improve: int = 0

    # ---- factory ----

    @classmethod
    def create(
        cls,
        state_file: Path,
        max_cost: float = 50.0,
        max_hours: float = 4.0,
        max_failures: int = 5,
        start_phase: int = 1,
    ) -> EvolveState:
        """Create fresh state or resume from checkpoint."""
        if state_file.exists():
            return cls._load(state_file, max_cost, max_hours, max_failures)
        return cls(
            state_file=state_file,
            start_time=time.time(),
            current_phase=start_phase,
            current_iteration=0,
            max_cost_usd=max_cost,
            max_runtime_hours=max_hours,
            max_consecutive_failures=max_failures,
        )

    @classmethod
    def _load(cls, path: Path, max_cost: float, max_hours: float, max_failures: int) -> EvolveState:
        data = json.loads(path.read_text(encoding="utf-8"))
        phases = {
            int(k): PhaseState(
                status=v["status"],
                iterations=v.get("iterations", 0),
                stages_passed=tuple(v.get("stages_passed", [])),
                errors_learned=v.get("errors_learned", 0),
            )
            for k, v in data.get("phases", {}).items()
        }
        return cls(
            state_file=path,
            start_time=data.get("start_time_epoch", time.time()),
            current_phase=data.get("current_phase", 1),
            current_iteration=data.get("current_iteration", 0),
            max_cost_usd=max_cost,
            max_runtime_hours=max_hours,
            max_consecutive_failures=max_failures,
            cost_spent_usd=data.get("cost_spent_usd", 0.0),
            elapsed_hours=data.get("elapsed_hours", 0.0),
            phases=phases,
            consecutive_no_improve=data.get("consecutive_no_improve", 0),
        )

    # ---- immutable updates ----

    def update_iteration(
        self, phase: int, stages_passed: int, errors_learned: int, cost_delta: float,
    ) -> EvolveState:
        """Record an iteration result. Returns new state."""
        new_phases = deepcopy(self.phases)
        old = new_phases.get(phase, PhaseState(status="running"))
        new_sp = old.stages_passed + (stages_passed,)

        improved = len(old.stages_passed) == 0 or stages_passed > old.stages_passed[-1]

        new_phases[phase] = PhaseState(
            status="running",
            iterations=old.iterations + 1,
            stages_passed=new_sp,
            errors_learned=old.errors_learned + errors_learned,
        )

        return EvolveState(
            state_file=self.state_file,
            start_time=self.start_time,
            current_phase=phase,
            current_iteration=self.current_iteration + 1,
            max_cost_usd=self.max_cost_usd,
            max_runtime_hours=self.max_runtime_hours,
            max_consecutive_failures=self.max_consecutive_failures,
            cost_spent_usd=self.cost_spent_usd + cost_delta,
            elapsed_hours=(time.time() - self.start_time) / 3600.0,
            phases=new_phases,
            consecutive_no_improve=0 if improved else self.consecutive_no_improve + 1,
        )

    def complete_phase(self, phase: int) -> EvolveState:
        """Mark a phase as complete. Returns new state."""
        new_phases = deepcopy(self.phases)
        old = new_phases.get(phase, PhaseState(status="running"))
        new_phases[phase] = PhaseState(
            status="complete",
            iterations=old.iterations,
            stages_passed=old.stages_passed,
            errors_learned=old.errors_learned,
        )
        return EvolveState(
            state_file=self.state_file,
            start_time=self.start_time,
            current_phase=self.current_phase,
            current_iteration=self.current_iteration,
            max_cost_usd=self.max_cost_usd,
            max_runtime_hours=self.max_runtime_hours,
            max_consecutive_failures=self.max_consecutive_failures,
            cost_spent_usd=self.cost_spent_usd,
            elapsed_hours=self.elapsed_hours,
            phases=new_phases,
            consecutive_no_improve=self.consecutive_no_improve,
        )

    # ---- checks ----

    def check_budget(self) -> tuple[bool, str]:
        """Returns (within_budget, reason)."""
        elapsed = (time.time() - self.start_time) / 3600.0
        if self.cost_spent_usd >= self.max_cost_usd:
            return False, f"Cost limit: ${self.cost_spent_usd:.2f} >= ${self.max_cost_usd:.2f}"
        if elapsed >= self.max_runtime_hours:
            return False, f"Time limit: {elapsed:.1f}h >= {self.max_runtime_hours:.1f}h"
        return True, f"OK: ${self.cost_spent_usd:.2f}/${self.max_cost_usd:.2f}, {elapsed:.1f}h/{self.max_runtime_hours:.1f}h"

    def check_stall(self, window: int = 3) -> bool:
        """True if no improvement in the last `window` iterations."""
        return self.consecutive_no_improve >= window

    # ---- persistence ----

    def checkpoint(self) -> None:
        """Atomic write state to disk."""
        data = {
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.start_time)),
            "start_time_epoch": self.start_time,
            "current_phase": self.current_phase,
            "current_iteration": self.current_iteration,
            "max_cost_usd": self.max_cost_usd,
            "max_runtime_hours": self.max_runtime_hours,
            "cost_spent_usd": round(self.cost_spent_usd, 4),
            "elapsed_hours": round((time.time() - self.start_time) / 3600.0, 4),
            "phases": {
                str(k): {
                    "status": v.status,
                    "iterations": v.iterations,
                    "stages_passed": list(v.stages_passed),
                    "errors_learned": v.errors_learned,
                }
                for k, v in self.phases.items()
            },
            "improvement_trend": list(
                self.phases.get(self.current_phase, PhaseState(status="pending")).stages_passed
            ),
            "consecutive_no_improve": self.consecutive_no_improve,
        }

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self.state_file.parent), suffix=".tmp")
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            Path(tmp_path).replace(self.state_file)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    # ---- reporting ----

    def generate_report(self, output_path: Path) -> None:
        """Generate a markdown report."""
        elapsed = (time.time() - self.start_time) / 3600.0
        lines = [
            "# Self-Evolving Agent Report",
            "",
            f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            f"**Duration**: {elapsed:.2f} hours",
            f"**Cost**: ${self.cost_spent_usd:.2f} / ${self.max_cost_usd:.2f}",
            f"**Total iterations**: {self.current_iteration}",
            f"**Consecutive stalls**: {self.consecutive_no_improve}",
            "",
            "## Phase Summary",
            "",
            "| Phase | Status | Iterations | Best Stages | Errors Learned |",
            "|-------|--------|------------|-------------|----------------|",
        ]
        for num in sorted(self.phases):
            ps = self.phases[num]
            best = max(ps.stages_passed) if ps.stages_passed else 0
            lines.append(f"| {num} | {ps.status} | {ps.iterations} | {best}/13 | {ps.errors_learned} |")

        lines.extend(["", "## Improvement Trend", ""])
        for num in sorted(self.phases):
            ps = self.phases[num]
            if ps.stages_passed:
                lines.append(f"- **Phase {num}**: {' -> '.join(str(s) for s in ps.stages_passed)}")

        lines.extend([
            "", "## Budget Usage", "",
            f"- Cost: ${self.cost_spent_usd:.2f} ({self.cost_spent_usd / max(self.max_cost_usd, 0.01) * 100:.0f}%)",
            f"- Time: {elapsed:.2f}h ({elapsed / max(self.max_runtime_hours, 0.01) * 100:.0f}%)",
            "",
        ])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
