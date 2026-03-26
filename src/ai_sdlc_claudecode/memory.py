"""Shared Context Memory — real-time context sharing between parallel agents.

Agents write findings/progress to a shared JSON file. Other agents (and prompt
builders) read the summarized context to avoid redundant exploration.

Uses fcntl.flock() for concurrency safety and atomic writes (tmpfile + rename).
"""

from __future__ import annotations

import fcntl
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SharedMemory:
    """Immutable record of a single shared memory entry."""

    agent_id: str
    stage_id: str
    timestamp: str
    memory_type: str  # "progress" | "finding" | "warning" | "artifact"
    content: str
    ttl: int  # seconds until expiry


VALID_TYPES = ("progress", "finding", "warning", "artifact")


class MemoryStore:
    """Append-only shared memory store backed by a JSON file.

    Thread/process safe via fcntl.flock(). All writes are atomic.
    """

    def __init__(self, store_path: str | Path) -> None:
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        agent_id: str,
        stage_id: str,
        memory_type: str,
        content: str,
        ttl: int = 3600,
    ) -> SharedMemory:
        """Append a memory entry. Returns the created record."""
        if memory_type not in VALID_TYPES:
            raise ValueError(f"Invalid memory_type: {memory_type}. Must be one of {VALID_TYPES}")
        if not content:
            raise ValueError("content must not be empty")

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = SharedMemory(
            agent_id=agent_id,
            stage_id=stage_id,
            timestamp=timestamp,
            memory_type=memory_type,
            content=content[:2000],  # cap content length
            ttl=ttl,
        )

        entry = {
            "agent_id": record.agent_id,
            "stage_id": record.stage_id,
            "timestamp": record.timestamp,
            "type": record.memory_type,
            "content": record.content,
            "ttl": record.ttl,
        }

        self._append(entry)
        return record

    def read_all(self, exclude_expired: bool = True) -> list[dict]:
        """Read all entries, optionally filtering expired ones."""
        entries = self._load()
        if not exclude_expired:
            return entries
        now = time.time()
        return [e for e in entries if not self._is_expired(e, now)]

    def read_by_stage(self, stage_id: str) -> list[dict]:
        """Read non-expired entries for a specific stage."""
        return [e for e in self.read_all() if e.get("stage_id") == stage_id]

    def summarize(self, max_chars: int = 3000) -> str:
        """Generate a text summary of active memories for prompt injection."""
        entries = self.read_all(exclude_expired=True)
        if not entries:
            return ""

        lines: list[str] = []
        char_count = 0

        for entry in entries:
            line = f"- [{entry['agent_id']}:{entry['stage_id']}] ({entry['type']}) {entry['content']}"
            if char_count + len(line) + 1 > max_chars:
                lines.append(f"... ({len(entries) - len(lines)} more entries)")
                break
            lines.append(line)
            char_count += len(line) + 1

        return "\n".join(lines)

    def cleanup(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        entries = self._load()
        now = time.time()
        active = [e for e in entries if not self._is_expired(e, now)]
        removed = len(entries) - len(active)
        if removed > 0:
            self._write_all(active)
        return removed

    def _is_expired(self, entry: dict, now: Optional[float] = None) -> bool:
        """Check if an entry has expired based on its timestamp + ttl."""
        if now is None:
            now = time.time()
        try:
            import calendar
            ts = calendar.timegm(time.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%SZ"))
            return (now - ts) > entry.get("ttl", 3600)
        except (KeyError, ValueError, OverflowError):
            return False

    def _load(self) -> list[dict]:
        """Load entries from disk with file lock."""
        if not self.store_path.exists():
            return []
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, OSError):
            return []

    def _append(self, entry: dict) -> None:
        """Append an entry with exclusive lock + atomic write."""
        lock_path = self.store_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            try:
                entries = self._load_unlocked()
                entries.append(entry)
                self._atomic_write(entries)
            finally:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

    def _write_all(self, entries: list[dict]) -> None:
        """Overwrite all entries with exclusive lock + atomic write."""
        lock_path = self.store_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            try:
                self._atomic_write(entries)
            finally:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self) -> list[dict]:
        """Load without locking (caller must hold lock)."""
        if not self.store_path.exists():
            return []
        try:
            return json.loads(self.store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _atomic_write(self, entries: list[dict]) -> None:
        """Write entries via tmpfile + rename for atomicity."""
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self.store_path.parent), suffix=".tmp"
        )
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
            Path(tmp_path).replace(self.store_path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
