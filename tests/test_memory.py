"""Tests for ai_sdlc_claudecode.memory — SharedMemory and MemoryStore."""

import json
import time
import threading
from pathlib import Path

import pytest

from ai_sdlc_claudecode.memory import MemoryStore, SharedMemory, VALID_TYPES


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "shared-context.json")


class TestWrite:
    def test_creates_record(self, store: MemoryStore) -> None:
        rec = store.write("S3", "backend", "progress", "Started API routes")
        assert isinstance(rec, SharedMemory)
        assert rec.agent_id == "S3"
        assert rec.stage_id == "backend"
        assert rec.memory_type == "progress"
        assert rec.content == "Started API routes"

    def test_persists_to_disk(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "artifact", "Done")
        assert store.store_path.exists()
        data = json.loads(store.store_path.read_text())
        assert len(data) == 1
        assert data[0]["agent_id"] == "S3"

    def test_append_multiple(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "progress", "Step 1")
        store.write("S3b", "frontend", "finding", "Found pattern")
        entries = store.read_all(exclude_expired=False)
        assert len(entries) == 2

    def test_record_is_immutable(self, store: MemoryStore) -> None:
        rec = store.write("S3", "backend", "progress", "test")
        with pytest.raises(AttributeError):
            rec.content = "mutated"  # type: ignore[misc]

    def test_rejects_invalid_type(self, store: MemoryStore) -> None:
        with pytest.raises(ValueError, match="Invalid memory_type"):
            store.write("S3", "backend", "invalid_type", "test")

    def test_rejects_empty_content(self, store: MemoryStore) -> None:
        with pytest.raises(ValueError, match="content must not be empty"):
            store.write("S3", "backend", "progress", "")

    def test_truncates_long_content(self, store: MemoryStore) -> None:
        long_content = "x" * 5000
        rec = store.write("S3", "backend", "progress", long_content)
        assert len(rec.content) == 2000

    def test_all_valid_types_accepted(self, store: MemoryStore) -> None:
        for t in VALID_TYPES:
            rec = store.write("S3", "backend", t, f"content for {t}")
            assert rec.memory_type == t


class TestRead:
    def test_read_all_empty(self, store: MemoryStore) -> None:
        assert store.read_all() == []

    def test_read_all_returns_entries(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "progress", "A")
        store.write("S3b", "frontend", "finding", "B")
        entries = store.read_all()
        assert len(entries) == 2

    def test_read_by_stage(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "progress", "A")
        store.write("S3b", "frontend", "finding", "B")
        store.write("S3", "backend", "artifact", "C")
        backend = store.read_by_stage("backend")
        assert len(backend) == 2
        frontend = store.read_by_stage("frontend")
        assert len(frontend) == 1

    def test_read_excludes_expired(self, store: MemoryStore) -> None:
        # Write with TTL=1 second
        store.write("S3", "backend", "progress", "quick", ttl=1)
        time.sleep(1.5)
        entries = store.read_all(exclude_expired=True)
        assert len(entries) == 0

    def test_read_includes_expired_when_asked(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "progress", "quick", ttl=1)
        time.sleep(1.5)
        entries = store.read_all(exclude_expired=False)
        assert len(entries) == 1


class TestSummarize:
    def test_empty_summary(self, store: MemoryStore) -> None:
        assert store.summarize() == ""

    def test_formats_entries(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "progress", "API routes done")
        summary = store.summarize()
        assert "S3:backend" in summary
        assert "progress" in summary
        assert "API routes done" in summary

    def test_respects_max_chars(self, store: MemoryStore) -> None:
        for i in range(50):
            store.write(f"S{i}", f"stage{i}", "progress", f"Content number {i} " * 10)
        summary = store.summarize(max_chars=500)
        assert len(summary) <= 600  # some slack for the "... more" line


class TestCleanup:
    def test_removes_expired(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "progress", "old", ttl=1)
        store.write("S3b", "frontend", "finding", "new", ttl=3600)
        time.sleep(1.5)
        removed = store.cleanup()
        assert removed == 1
        remaining = store.read_all(exclude_expired=False)
        assert len(remaining) == 1
        assert remaining[0]["stage_id"] == "frontend"

    def test_no_expired(self, store: MemoryStore) -> None:
        store.write("S3", "backend", "progress", "fresh", ttl=3600)
        assert store.cleanup() == 0


class TestConcurrency:
    def test_concurrent_writes(self, store: MemoryStore) -> None:
        """Multiple threads writing simultaneously should not corrupt data."""
        errors: list[Exception] = []

        def writer(agent_id: str) -> None:
            try:
                for i in range(10):
                    store.write(agent_id, "test", "progress", f"msg {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"agent{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        entries = store.read_all(exclude_expired=False)
        assert len(entries) == 50  # 5 threads × 10 writes


class TestCorruptFile:
    def test_handles_corrupt_json(self, store: MemoryStore) -> None:
        store.store_path.write_text("not json {{{")
        assert store.read_all() == []
        # Can still write after corruption
        store.write("S3", "backend", "progress", "recovered")
        assert len(store.read_all()) == 1

    def test_handles_missing_file(self, store: MemoryStore) -> None:
        assert store.read_all() == []
