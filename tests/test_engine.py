"""Tests for ai_sdlc_claudecode.engine — ErrorEngine and ErrorRecord."""

import json
import tempfile
from pathlib import Path

import pytest

from ai_sdlc_claudecode.engine import (
    CATEGORY_AI_OUTPUT,
    CATEGORY_COMPILATION,
    CATEGORY_CONTEXT_OVERFLOW,
    CATEGORY_COST,
    CATEGORY_SCHEMA,
    CATEGORY_TIMEOUT,
    ErrorEngine,
    ErrorRecord,
)


@pytest.fixture
def engine(tmp_path: Path) -> ErrorEngine:
    return ErrorEngine(tmp_path / "errors")


class TestClassify:
    def test_cost_overrun(self, engine: ErrorEngine) -> None:
        assert engine.classify("COST LIMIT exceeded", 0) == CATEGORY_COST

    def test_timeout_exit_code(self, engine: ErrorEngine) -> None:
        assert engine.classify("something happened", 124) == CATEGORY_TIMEOUT

    def test_timeout_text(self, engine: ErrorEngine) -> None:
        assert engine.classify("request timed out", 1) == CATEGORY_TIMEOUT

    def test_compilation(self, engine: ErrorEngine) -> None:
        assert engine.classify("cannot find symbol Foo", 1) == CATEGORY_COMPILATION

    def test_schema(self, engine: ErrorEngine) -> None:
        assert engine.classify("missing required property 'stage_id'", 1) == CATEGORY_SCHEMA

    def test_default_ai_output(self, engine: ErrorEngine) -> None:
        assert engine.classify("random garbage", 1) == CATEGORY_AI_OUTPUT

    def test_empty_input(self, engine: ErrorEngine) -> None:
        assert engine.classify("", 0) == CATEGORY_AI_OUTPUT

    def test_none_input(self, engine: ErrorEngine) -> None:
        assert engine.classify(None, 0) == CATEGORY_AI_OUTPUT  # type: ignore[arg-type]

    def test_context_overflow_window(self, engine: ErrorEngine) -> None:
        assert engine.classify("context window exceeded", 1) == CATEGORY_CONTEXT_OVERFLOW

    def test_context_overflow_token_limit(self, engine: ErrorEngine) -> None:
        assert engine.classify("token limit reached", 1) == CATEGORY_CONTEXT_OVERFLOW

    def test_context_overflow_max_context(self, engine: ErrorEngine) -> None:
        assert engine.classify("maximum context length exceeded", 1) == CATEGORY_CONTEXT_OVERFLOW

    def test_context_overflow_prompt_too_long(self, engine: ErrorEngine) -> None:
        assert engine.classify("prompt is too long for model", 1) == CATEGORY_CONTEXT_OVERFLOW


class TestCapture:
    def test_creates_record(self, engine: ErrorEngine) -> None:
        rec = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        assert isinstance(rec, ErrorRecord)
        assert rec.category == CATEGORY_COMPILATION
        assert rec.stage_id == "S3"
        assert rec.fix_pattern["injection"]

    def test_truncates_long_errors(self, engine: ErrorEngine) -> None:
        long_error = "x" * 5000
        rec = engine.capture("feat", "S1", "requirements", long_error, 1, 0, 1)
        assert len(rec.raw_error) == 2000

    def test_persists_to_disk(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "error", 1, 0, 1)
        records_dir = engine.errors_dir / "records"
        assert len(list(records_dir.glob("*.json"))) == 1

    def test_record_is_immutable(self, engine: ErrorEngine) -> None:
        rec = engine.capture("feat", "S1", "req", "err", 1, 0, 1)
        with pytest.raises(AttributeError):
            rec.category = "other"  # type: ignore[misc]


class TestLookupAndAugment:
    def test_lookup_returns_fixes(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        fixes = engine.lookup_fix("S3")
        assert len(fixes) == 1
        assert "injection" in fixes[0]

    def test_lookup_empty_stage(self, engine: ErrorEngine) -> None:
        assert engine.lookup_fix("S99") == []

    def test_augment_injects_fix(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        result = engine.augment_prompt("Original prompt", "S3")
        assert "Original prompt" in result
        assert len(result) > len("Original prompt")

    def test_augment_no_fix_returns_original(self, engine: ErrorEngine) -> None:
        result = engine.augment_prompt("prompt", "S99")
        assert result == "prompt"

    def test_deduplicates_by_category(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol A", 1, 0, 1)
        engine.capture("feat", "S3", "backend", "cannot find symbol B", 1, 1, 1)
        fixes = engine.lookup_fix("S3")
        assert len(fixes) == 1  # same category, deduped


class TestSuccessAndPromote:
    def test_mark_success_increments(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        engine.mark_applied("S3")
        engine.mark_success("S3")
        assert engine.index["S3"][0].success_after_apply == 1

    def test_promote_after_threshold(self, engine: ErrorEngine, tmp_path: Path) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        engine.mark_applied("S3")
        for _ in range(3):
            engine.mark_success("S3")
        skills_dir = tmp_path / "skills"
        promoted = engine.promote_to_skill(skills_dir)
        assert len(promoted) == 1
        assert Path(promoted[0]).exists()

    def test_promote_not_ready(self, engine: ErrorEngine, tmp_path: Path) -> None:
        engine.capture("feat", "S3", "backend", "err", 1, 0, 1)
        assert engine.promote_to_skill(tmp_path / "skills") == []


class TestWriteAugments:
    def test_writes_files(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        engine.write_augments()
        assert (engine.errors_dir / "augments" / "S3.txt").exists()


class TestReadFailures:
    def test_reads_and_cleans(self, engine: ErrorEngine) -> None:
        failures = engine.errors_dir / "failures"
        (failures / "S3-12345.txt").write_text("cannot find symbol")
        (failures / "S3-12345.exit").write_text("1")

        records = engine.read_failures(0, 1, "feat")
        assert len(records) == 1
        assert records[0].category == CATEGORY_COMPILATION
        assert not (failures / "S3-12345.txt").exists()  # cleaned up


class TestStats:
    def test_empty_stats(self, engine: ErrorEngine) -> None:
        stats = engine.get_stats()
        assert stats["total_errors"] == 0

    def test_stats_after_capture(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "err", 1, 0, 1)
        engine.capture("feat", "S1", "req", "schema", 1, 0, 1)
        stats = engine.get_stats()
        assert stats["total_errors"] == 2
        assert stats["stages_affected"] == 2


class TestCaptureRealtime:
    def test_captures_and_writes_augment(self, engine: ErrorEngine) -> None:
        record = engine.capture_realtime("S3", 1, "cannot find symbol Foo", "feat")
        assert record.category == CATEGORY_COMPILATION
        augment_file = engine.errors_dir / "augments" / "S3.txt"
        assert augment_file.exists()
        assert "compilation" in augment_file.read_text().lower() or "compile" in augment_file.read_text().lower()

    def test_context_overflow_fix(self, engine: ErrorEngine) -> None:
        record = engine.capture_realtime("S2", 1, "context window exceeded", "feat")
        assert record.category == CATEGORY_CONTEXT_OVERFLOW
        assert "context_reduction" in record.fix_pattern

    def test_marks_applied(self, engine: ErrorEngine) -> None:
        engine.capture_realtime("S3", 1, "schema validation failed", "feat")
        # After capture_realtime, fix should be marked as applied
        records = engine.index.get("S3", [])
        assert len(records) == 1
        assert records[0].applied_count == 1


class TestPersistAndReload:
    def test_reload_from_disk(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "err", 1, 0, 1)

        # Create new engine pointing to same dir
        engine2 = ErrorEngine(engine.errors_dir)
        assert len(engine2.index.get("S3", [])) == 1
