"""Tests for ai_sdlc_claudecode.config — path resolution."""

from pathlib import Path

from ai_sdlc_claudecode.config import resolve_executor, resolve_dag


class TestResolve:
    def test_executor_found(self) -> None:
        p = resolve_executor()
        assert p.exists()
        assert p.name == "pipeline-executor.sh"

    def test_dag_found(self) -> None:
        p = resolve_dag()
        assert p.exists()
        assert p.name == "pipeline-dag.json"
