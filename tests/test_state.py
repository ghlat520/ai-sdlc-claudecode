"""Tests for ai_sdlc_claudecode.state — EvolveState and PhaseState."""

import json
from pathlib import Path

import pytest

from ai_sdlc_claudecode.state import EvolveState, PhaseState


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


class TestCreate:
    def test_fresh_state(self, state_file: Path) -> None:
        state = EvolveState.create(state_file, max_cost=50, max_hours=4)
        assert state.current_iteration == 0
        assert state.cost_spent_usd == 0.0

    def test_resume_from_checkpoint(self, state_file: Path) -> None:
        s1 = EvolveState.create(state_file, max_cost=50, max_hours=4)
        s2 = s1.update_iteration(1, 5, 2, 1.5)
        s2.checkpoint()

        resumed = EvolveState.create(state_file, max_cost=50, max_hours=4)
        assert resumed.current_iteration == 1
        assert resumed.cost_spent_usd == 1.5


class TestImmutability:
    def test_update_returns_new_state(self, state_file: Path) -> None:
        s1 = EvolveState.create(state_file, max_cost=50, max_hours=4)
        s2 = s1.update_iteration(1, 5, 2, 1.5)
        assert s1.current_iteration == 0  # original unchanged
        assert s2.current_iteration == 1

    def test_frozen_dataclass(self, state_file: Path) -> None:
        state = EvolveState.create(state_file)
        with pytest.raises(AttributeError):
            state.cost_spent_usd = 100  # type: ignore[misc]


class TestBudget:
    def test_within_budget(self, state_file: Path) -> None:
        state = EvolveState.create(state_file, max_cost=50, max_hours=4)
        ok, _ = state.check_budget()
        assert ok

    def test_cost_exceeded(self, state_file: Path) -> None:
        state = EvolveState.create(state_file, max_cost=1.0, max_hours=4)
        s2 = state.update_iteration(1, 5, 0, 2.0)
        ok, reason = s2.check_budget()
        assert not ok
        assert "Cost limit" in reason


class TestStall:
    def test_no_stall_initially(self, state_file: Path) -> None:
        state = EvolveState.create(state_file)
        assert not state.check_stall()

    def test_stall_detection(self, state_file: Path) -> None:
        state = EvolveState.create(state_file)
        # Same stages_passed each time = no improvement
        for _ in range(5):
            state = state.update_iteration(1, 5, 0, 0.1)
        assert state.check_stall(window=3)

    def test_improvement_resets_stall(self, state_file: Path) -> None:
        state = EvolveState.create(state_file)
        state = state.update_iteration(1, 5, 0, 0.1)
        state = state.update_iteration(1, 5, 0, 0.1)  # no improvement
        state = state.update_iteration(1, 8, 0, 0.1)  # improvement!
        assert not state.check_stall(window=3)


class TestCheckpoint:
    def test_atomic_write(self, state_file: Path) -> None:
        state = EvolveState.create(state_file)
        state = state.update_iteration(1, 5, 2, 1.0)
        state.checkpoint()

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["current_iteration"] == 1
        assert data["cost_spent_usd"] == 1.0


class TestCompletePhase:
    def test_marks_complete(self, state_file: Path) -> None:
        state = EvolveState.create(state_file)
        state = state.update_iteration(1, 13, 0, 1.0)
        state = state.complete_phase(1)
        assert state.phases[1].status == "complete"


class TestReport:
    def test_generates_markdown(self, state_file: Path, tmp_path: Path) -> None:
        state = EvolveState.create(state_file)
        state = state.update_iteration(1, 5, 2, 1.0)
        report = tmp_path / "report.md"
        state.generate_report(report)

        assert report.exists()
        content = report.read_text()
        assert "Self-Evolving Agent Report" in content
        assert "Phase Summary" in content
