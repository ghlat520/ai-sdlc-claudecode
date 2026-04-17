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

    def test_reload_preserves_variants(self, engine: ErrorEngine) -> None:
        rec = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        assert len(rec.variants) >= 2

        engine2 = ErrorEngine(engine.errors_dir)
        records = engine2.index.get("S3", [])
        assert len(records) == 1
        assert len(records[0].variants) >= 2
        ids_before = {v["id"] for v in rec.variants}
        ids_after = {v["id"] for v in records[0].variants}
        assert ids_before == ids_after


class TestVariantsAndThompsonSampling:
    """Coverage for the self-evolution loop: variants, selection, attribution."""

    def test_capture_populates_variants(self, engine: ErrorEngine) -> None:
        rec = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        assert len(rec.variants) >= 2, "compilation should have multiple variants"
        for v in rec.variants:
            assert "id" in v and len(v["id"]) == 8
            assert "injection" in v and v["injection"]
            assert v["success"] == 0 and v["fail"] == 0
            assert not v.get("retired")

    def test_variant_id_is_stable(self, engine: ErrorEngine) -> None:
        r1 = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        r2 = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 1, 1)
        ids1 = {v["id"] for v in r1.variants}
        ids2 = {v["id"] for v in r2.variants}
        assert ids1 == ids2, "same category+injection must yield same fix_id"

    def test_select_variant_returns_one(self, engine: ErrorEngine) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        selected = engine.select_variant("S3")
        assert selected is not None
        assert "id" in selected and "injection" in selected

    def test_select_variant_empty_stage(self, engine: ErrorEngine) -> None:
        assert engine.select_variant("S99") is None

    def test_mark_success_with_fix_ids_credits_only_matching(
        self, engine: ErrorEngine
    ) -> None:
        rec = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        target_id = rec.variants[0]["id"]
        other_id = rec.variants[1]["id"]

        engine.mark_success("S3", applied_fix_ids=[target_id])
        updated = engine.index["S3"][0]
        by_id = {v["id"]: v for v in updated.variants}
        assert by_id[target_id]["success"] == 1
        assert by_id[other_id]["success"] == 0
        assert updated.success_after_apply == 1

    def test_mark_failed_increments_fail_counter(self, engine: ErrorEngine) -> None:
        rec = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        vid = rec.variants[0]["id"]
        engine.mark_failed("S3", applied_fix_ids=[vid])
        v = {v["id"]: v for v in engine.index["S3"][0].variants}[vid]
        assert v["fail"] == 1
        assert not v.get("retired")  # 1 trial, below RETIRE_MIN_TRIALS

    def test_variant_retires_after_high_fail_rate(self, engine: ErrorEngine) -> None:
        rec = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        vid = rec.variants[0]["id"]
        for _ in range(6):
            engine.mark_failed("S3", applied_fix_ids=[vid])
        v = {v["id"]: v for v in engine.index["S3"][0].variants}[vid]
        assert v["retired"] is True, "6 fails >= RETIRE_MIN_TRIALS and fail_rate 100%"

    def test_retired_variant_excluded_from_selection(self, engine: ErrorEngine) -> None:
        rec = engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        for v in rec.variants:
            for _ in range(6):
                engine.mark_failed("S3", applied_fix_ids=[v["id"]])
        # all variants retired → select_variant returns None
        assert engine.select_variant("S3") is None

    def test_write_augments_emits_json_with_fix_ids(
        self, engine: ErrorEngine
    ) -> None:
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        engine.write_augments()
        json_file = engine.errors_dir / "augments" / "S3.json"
        txt_file = engine.errors_dir / "augments" / "S3.txt"
        assert json_file.exists()
        assert txt_file.exists()
        data = json.loads(json_file.read_text())
        assert data["stage_id"] == "S3"
        assert len(data["fix_ids"]) >= 1
        assert all(len(fid) == 8 for fid in data["fix_ids"])
        assert data["injection"] == txt_file.read_text()

    def test_mark_success_without_fix_ids_preserves_legacy(
        self, engine: ErrorEngine
    ) -> None:
        """Legacy callers (no applied_fix_ids) must still get success+1 after apply."""
        engine.capture("feat", "S3", "backend", "cannot find symbol", 1, 0, 1)
        engine.mark_applied("S3")
        engine.mark_success("S3")
        assert engine.index["S3"][0].success_after_apply == 1
