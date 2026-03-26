"""Error Learning Engine — core innovation of the self-evolving agent system.

Captures errors, classifies them deterministically (no LLM), extracts fix patterns,
and augments prompts with learned fixes. Mature fixes get promoted to skills.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ErrorRecord:
    """Immutable record of a captured error and its fix pattern."""

    error_id: str
    timestamp: str
    iteration: int
    phase: int
    stage_id: str
    stage_name: str
    category: str
    raw_error: str  # truncated to MAX_RAW_ERROR_LEN
    fix_pattern: dict  # {"type": "prompt_augmentation", "injection": "...", "position": "prepend"}
    applied_count: int = 0
    success_after_apply: int = 0


# --- Error categories (deterministic, no LLM) ---
CATEGORY_SCHEMA = "schema_validation"
CATEGORY_AI_OUTPUT = "ai_output_quality"
CATEGORY_COMPILATION = "compilation"
CATEGORY_TIMEOUT = "timeout"
CATEGORY_COST = "cost_overrun"
CATEGORY_CONTEXT_OVERFLOW = "context_overflow"

ALL_CATEGORIES = (
    CATEGORY_SCHEMA,
    CATEGORY_AI_OUTPUT,
    CATEGORY_COMPILATION,
    CATEGORY_TIMEOUT,
    CATEGORY_COST,
    CATEGORY_CONTEXT_OVERFLOW,
)

MAX_RAW_ERROR_LEN = 2000
PROMOTE_THRESHOLD = 3


class ErrorEngine:
    """Learns from pipeline failures and augments prompts to prevent recurrence."""

    def __init__(self, errors_dir: Path) -> None:
        self.errors_dir = errors_dir
        self.errors_dir.mkdir(parents=True, exist_ok=True)
        (self.errors_dir / "augments").mkdir(exist_ok=True)
        (self.errors_dir / "failures").mkdir(exist_ok=True)
        (self.errors_dir / "records").mkdir(exist_ok=True)

        self.index: dict[str, list[ErrorRecord]] = {}  # stage_id -> records
        self._load_index()

    # ---- public API ----

    def capture(
        self,
        feature_id: str,
        stage_id: str,
        stage_name: str,
        raw_output: str,
        exit_code: int,
        iteration: int,
        phase: int,
    ) -> ErrorRecord:
        """Capture a failure, classify it, extract a fix pattern, and persist."""
        category = self.classify(raw_output, exit_code)
        fix_pattern = self.extract_pattern(category, raw_output, stage_id)
        truncated = raw_output[:MAX_RAW_ERROR_LEN] if raw_output else ""

        error_id = hashlib.sha256(
            f"{stage_id}:{category}:{iteration}:{time.time()}".encode()
        ).hexdigest()[:12]

        record = ErrorRecord(
            error_id=error_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            iteration=iteration,
            phase=phase,
            stage_id=stage_id,
            stage_name=stage_name,
            category=category,
            raw_error=truncated,
            fix_pattern=fix_pattern,
        )

        self.index.setdefault(stage_id, []).append(record)
        self._persist_record(record)
        return record

    def classify(self, raw_output: str, exit_code: int) -> str:
        """Deterministic classification — no LLM call."""
        text = (raw_output or "").lower()

        if "cost limit" in text or "cost_limit" in text or "budget exceeded" in text:
            return CATEGORY_COST
        if exit_code == 124 or "timed out" in text or "timeout" in text:
            return CATEGORY_TIMEOUT

        context_signals = [
            "context window", "token limit", "maximum context", "too long",
            "context length", "max_tokens", "context_length_exceeded",
            "prompt is too long", "input too large",
        ]
        if any(sig in text for sig in context_signals):
            return CATEGORY_CONTEXT_OVERFLOW

        compilation_signals = [
            "cannot find symbol", "compilation failure", "build failure",
            "compile error", "mvn compile", "syntax error",
            "cannot resolve", "error: ", "failed to compile",
        ]
        if any(sig in text for sig in compilation_signals):
            return CATEGORY_COMPILATION

        schema_signals = [
            "schema", "validation", "missing required",
            "jsonschemavalidation", "required property",
            "not valid under", "stage_id",
        ]
        if any(sig in text for sig in schema_signals):
            return CATEGORY_SCHEMA

        return CATEGORY_AI_OUTPUT

    def extract_pattern(self, category: str, raw_output: str, stage_id: str) -> dict:
        """Generate a deterministic fix pattern based on category."""
        base = {"type": "prompt_augmentation", "position": "prepend"}

        if category == CATEGORY_SCHEMA:
            missing = self._extract_missing_fields(raw_output)
            hint = f" Missing fields detected: {', '.join(missing)}." if missing else ""
            return {
                **base,
                "injection": (
                    "CRITICAL: Your output MUST be a single valid JSON object. "
                    "Include ALL required fields from the schema. "
                    "Do NOT wrap in markdown code blocks. "
                    f"Do NOT include any text before or after the JSON.{hint}\n\n"
                ),
            }

        if category == CATEGORY_AI_OUTPUT:
            return {
                **base,
                "injection": (
                    "IMPORTANT: Output ONLY valid JSON. No explanations, no markdown, "
                    "no code blocks. Start your response with { and end with }. "
                    "Every string value must be properly escaped.\n\n"
                ),
            }

        if category == CATEGORY_COMPILATION:
            snippet = self._extract_error_lines(raw_output, max_lines=5)
            return {
                **base,
                "injection": (
                    "IMPORTANT: After generating code, verify it compiles. "
                    "Run 'mvn clean compile test-compile' mentally before finalizing. "
                    "Previous attempt had compilation errors"
                    f"{': ' + snippet if snippet else '.'}. "
                    "Fix these issues in your output.\n\n"
                ),
            }

        if category == CATEGORY_TIMEOUT:
            return {
                **base,
                "injection": (
                    "IMPORTANT: Keep your response concise and focused. "
                    "Previous attempt timed out. Reduce output length, "
                    "avoid unnecessary explanations.\n\n"
                ),
                "model_suggestion": "haiku",
            }

        if category == CATEGORY_COST:
            return {
                **base,
                "injection": (
                    "COST ALERT: Use minimal tokens. Be extremely concise. "
                    "Output only the required JSON, nothing else.\n\n"
                ),
                "model_suggestion": "haiku",
            }

        if category == CATEGORY_CONTEXT_OVERFLOW:
            return {
                **base,
                "injection": (
                    "CONTEXT OVERFLOW: Previous attempt exceeded context window. "
                    "Reduce upstream input by using summary mode. "
                    "Keep your output concise — only essential JSON fields.\n\n"
                ),
                "context_reduction": True,
            }

        return base

    def lookup_fix(self, stage_id: str) -> list[dict]:
        """Return best fixes for a stage, sorted by success rate descending."""
        records = self.index.get(stage_id, [])
        if not records:
            return []

        best_by_category: dict[str, ErrorRecord] = {}
        for rec in records:
            existing = best_by_category.get(rec.category)
            if existing is None or rec.success_after_apply > existing.success_after_apply:
                best_by_category[rec.category] = rec

        return [
            rec.fix_pattern
            for rec in sorted(
                best_by_category.values(),
                key=lambda r: r.success_after_apply,
                reverse=True,
            )
            if rec.fix_pattern.get("injection")
        ]

    def augment_prompt(self, original_prompt: str, stage_id: str) -> str:
        """Inject learned fixes into the prompt for a stage."""
        fixes = self.lookup_fix(stage_id)
        if not fixes:
            return original_prompt

        injections = [
            fix["injection"]
            for fix in fixes
            if fix.get("injection") and fix["injection"] not in original_prompt
        ]
        if not injections:
            return original_prompt

        return "".join(injections) + original_prompt

    def mark_success(self, stage_id: str) -> None:
        """Increment success counters for applied fixes."""
        records = self.index.get(stage_id, [])
        self.index[stage_id] = [
            replace(rec, success_after_apply=rec.success_after_apply + 1)
            if rec.applied_count > 0
            else rec
            for rec in records
        ]
        self._persist_all_records(stage_id)

    def mark_applied(self, stage_id: str) -> None:
        """Mark that fixes for a stage have been applied (before retry)."""
        records = self.index.get(stage_id, [])
        self.index[stage_id] = [
            replace(rec, applied_count=rec.applied_count + 1)
            for rec in records
        ]

    def promote_to_skill(self, skills_dir: Optional[Path] = None) -> list[str]:
        """Promote mature fixes (success >= threshold) to skill files."""
        if skills_dir is None:
            skills_dir = Path.home() / ".claude" / "skills" / "saved"
        skills_dir.mkdir(parents=True, exist_ok=True)

        promoted: list[str] = []
        for records in self.index.values():
            for rec in records:
                if rec.success_after_apply >= PROMOTE_THRESHOLD:
                    name = f"ai-sdlc-fix-{rec.category}-{rec.stage_id}.md"
                    path = skills_dir / name
                    if not path.exists():
                        path.write_text(self._format_skill(rec), encoding="utf-8")
                        promoted.append(str(path))
        return promoted

    def write_augments(self) -> None:
        """Write augment files for bash to read: augments/{stage_id}.txt."""
        augments_dir = self.errors_dir / "augments"
        augments_dir.mkdir(exist_ok=True)

        for stage_id in self.index:
            fixes = self.lookup_fix(stage_id)
            injections = [f["injection"] for f in fixes if f.get("injection")]
            if injections:
                (augments_dir / f"{stage_id}.txt").write_text(
                    "".join(injections), encoding="utf-8"
                )
                self.mark_applied(stage_id)

    def read_failures(self, iteration: int, phase: int, feature_id: str) -> list[ErrorRecord]:
        """Read failure files written by bash and process them."""
        failures_dir = self.errors_dir / "failures"
        if not failures_dir.exists():
            return []

        records: list[ErrorRecord] = []
        for txt_path in sorted(failures_dir.glob("*.txt")):
            stage_id = txt_path.stem.rsplit("-", 1)[0]  # S3-1710756000 -> S3
            exit_path = txt_path.with_suffix(".exit")
            exit_code = 1
            if exit_path.exists():
                try:
                    exit_code = int(exit_path.read_text().strip())
                except (ValueError, OSError):
                    pass

            raw_output = txt_path.read_text(encoding="utf-8", errors="replace")
            record = self.capture(
                feature_id=feature_id,
                stage_id=stage_id,
                stage_name=stage_id,
                raw_output=raw_output,
                exit_code=exit_code,
                iteration=iteration,
                phase=phase,
            )
            records.append(record)

            txt_path.unlink(missing_ok=True)
            exit_path.unlink(missing_ok=True)

        return records

    def capture_realtime(
        self,
        stage_id: str,
        exit_code: int,
        error_output: str,
        feature_id: str = "unknown",
        iteration: int = 0,
        phase: int = 1,
    ) -> ErrorRecord:
        """Capture and classify an error immediately (not waiting for iteration end).

        Called by bash executor within the retry loop for real-time error learning.
        Also writes the augment file immediately so the next retry benefits.
        """
        record = self.capture(
            feature_id=feature_id,
            stage_id=stage_id,
            stage_name=stage_id,
            raw_output=error_output,
            exit_code=exit_code,
            iteration=iteration,
            phase=phase,
        )
        # Write augment immediately so next retry can use it
        fixes = self.lookup_fix(stage_id)
        injections = [f["injection"] for f in fixes if f.get("injection")]
        if injections:
            augments_dir = self.errors_dir / "augments"
            augments_dir.mkdir(exist_ok=True)
            (augments_dir / f"{stage_id}.txt").write_text(
                "".join(injections), encoding="utf-8"
            )
            self.mark_applied(stage_id)
        return record

    def get_stats(self) -> dict:
        """Return summary statistics."""
        total = sum(len(recs) for recs in self.index.values())
        categories: dict[str, int] = {}
        promoted = 0
        for records in self.index.values():
            for rec in records:
                categories[rec.category] = categories.get(rec.category, 0) + 1
                if rec.success_after_apply >= PROMOTE_THRESHOLD:
                    promoted += 1
        return {
            "total_errors": total,
            "stages_affected": len(self.index),
            "by_category": categories,
            "promoted_fixes": promoted,
        }

    # ---- private ----

    def _extract_missing_fields(self, raw_output: str) -> list[str]:
        patterns = [
            r"missing required propert(?:y|ies)[:\s]+(['\"][\w_]+['\"](?:,\s*['\"][\w_]+['\"])*)",
            r"required property '(\w+)'",
            r"'(\w+)' is a required property",
        ]
        fields: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, raw_output or "", re.IGNORECASE):
                field = match.group(1).strip("'\"")
                if field not in fields:
                    fields.append(field)
        return fields

    def _extract_error_lines(self, raw_output: str, max_lines: int = 5) -> str:
        keywords = ["error", "cannot find", "failed", "failure"]
        lines = (raw_output or "").split("\n")
        errors = [
            ln.strip() for ln in lines
            if any(kw in ln.lower() for kw in keywords)
        ]
        return "; ".join(errors[:max_lines])

    def _format_skill(self, record: ErrorRecord) -> str:
        return (
            f"---\n"
            f"name: ai-sdlc-fix-{record.category}-{record.stage_id}\n"
            f"description: Auto-learned fix for {record.category} errors in stage {record.stage_id}\n"
            f"type: reference\n"
            f"---\n\n"
            f"# Auto-learned Fix: {record.category} in {record.stage_id}\n\n"
            f"**Category**: {record.category}\n"
            f"**Stage**: {record.stage_id} ({record.stage_name})\n"
            f"**Success rate**: {record.success_after_apply} consecutive successes\n\n"
            f"## Fix Pattern\n\n"
            f"```\n{record.fix_pattern.get('injection', 'N/A')}\n```\n\n"
            f"## Original Error (sample)\n\n"
            f"```\n{record.raw_error[:500]}\n```\n"
        )

    def _persist_record(self, record: ErrorRecord) -> None:
        path = self.errors_dir / "records" / f"{record.error_id}.json"
        path.write_text(json.dumps({
            "error_id": record.error_id,
            "timestamp": record.timestamp,
            "iteration": record.iteration,
            "phase": record.phase,
            "stage_id": record.stage_id,
            "stage_name": record.stage_name,
            "category": record.category,
            "raw_error": record.raw_error,
            "fix_pattern": record.fix_pattern,
            "applied_count": record.applied_count,
            "success_after_apply": record.success_after_apply,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    def _persist_all_records(self, stage_id: str) -> None:
        for rec in self.index.get(stage_id, []):
            self._persist_record(rec)

    def _load_index(self) -> None:
        records_dir = self.errors_dir / "records"
        if not records_dir.exists():
            return
        for path in records_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record = ErrorRecord(
                    error_id=data["error_id"],
                    timestamp=data["timestamp"],
                    iteration=data["iteration"],
                    phase=data["phase"],
                    stage_id=data["stage_id"],
                    stage_name=data["stage_name"],
                    category=data["category"],
                    raw_error=data["raw_error"],
                    fix_pattern=data["fix_pattern"],
                    applied_count=data.get("applied_count", 0),
                    success_after_apply=data.get("success_after_apply", 0),
                )
                self.index.setdefault(record.stage_id, []).append(record)
            except (json.JSONDecodeError, KeyError, OSError):
                continue
