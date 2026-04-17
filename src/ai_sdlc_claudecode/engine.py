"""Error Learning Engine — core innovation of the self-evolving agent system.

Captures errors, classifies them deterministically (no LLM), extracts fix patterns,
and augments prompts with learned fixes. Mature fixes get promoted to skills.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ErrorRecord:
    """Immutable record of a captured error and its fix pattern.

    variants: list of alternative injections for Thompson-Sampling based A/B testing.
    Each variant: {"id": str, "injection": str, "success": int, "fail": int, "retired": bool}
    Legacy records without variants synthesize one from fix_pattern on demand.
    """

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
    variants: tuple[dict, ...] = field(default_factory=tuple)  # Thompson-Sampling pool


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

# Variant retirement: a variant with fail-rate above threshold AND sufficient trials
# is removed from sampling to avoid repeating known-bad fixes.
RETIRE_FAIL_RATE = 0.70
RETIRE_MIN_TRIALS = 5

# Exploration epsilon: proportion of time we pick a random non-retired variant
# (instead of Thompson-sampled argmax) to ensure all variants get tried.
EPSILON_EXPLORE = 0.10


def _make_fix_id(category: str, injection: str) -> str:
    """Stable 8-char id derived from category+injection (same content = same id)."""
    return hashlib.sha256(f"{category}::{injection}".encode("utf-8")).hexdigest()[:8]


def _new_variant(category: str, injection: str, **extras) -> dict:
    """Factory for a fresh variant dict with stable id and zeroed counters."""
    v = {
        "id": _make_fix_id(category, injection),
        "injection": injection,
        "success": 0,
        "fail": 0,
        "retired": False,
    }
    v.update(extras)
    return v


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
        variants = self.extract_variants(category, raw_output, stage_id)
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
            variants=tuple(variants),
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

    def extract_variants(self, category: str, raw_output: str, stage_id: str) -> list[dict]:
        """Generate 2-3 alternative injection variants per category for A/B testing.

        Variant 0 (conservative) mirrors extract_pattern's wording; variant 1+ are
        alternative phrasings explored via Thompson Sampling (Beta posterior).
        Returns list of variant dicts with stable `id` and zeroed success/fail counters.
        """
        if category == CATEGORY_SCHEMA:
            missing = self._extract_missing_fields(raw_output)
            hint = f" Missing fields detected: {', '.join(missing)}." if missing else ""
            return [
                _new_variant(category,
                    "CRITICAL: Your output MUST be a single valid JSON object. "
                    "Include ALL required fields from the schema. "
                    "Do NOT wrap in markdown code blocks. "
                    f"Do NOT include any text before or after the JSON.{hint}\n\n"),
                _new_variant(category,
                    "Schema validation failed. Re-read the JSON schema for this stage. "
                    "For every `required` field, emit a key-value pair in your output. "
                    "Double-check types (string vs. number, object vs. array).\n\n"),
            ]

        if category == CATEGORY_AI_OUTPUT:
            return [
                _new_variant(category,
                    "IMPORTANT: Output ONLY valid JSON. No explanations, no markdown, "
                    "no code blocks. Start your response with { and end with }. "
                    "Every string value must be properly escaped.\n\n"),
                _new_variant(category,
                    "The previous attempt produced malformed output. "
                    "Emit ONE JSON object. Ensure every string has matching quotes, "
                    "every object has matching braces, no trailing commas.\n\n"),
            ]

        if category == CATEGORY_COMPILATION:
            snippet = self._extract_error_lines(raw_output, max_lines=5)
            ctx = f": {snippet}" if snippet else "."
            return [
                _new_variant(category,
                    "IMPORTANT: After generating code, verify it compiles. "
                    "Run 'mvn clean compile test-compile' mentally before finalizing. "
                    f"Previous attempt had compilation errors{ctx}. "
                    "Fix these issues in your output.\n\n"),
                _new_variant(category,
                    "Compilation failed. Before emitting any code, trace every import, "
                    "class reference, and method signature. If unsure whether a symbol "
                    f"exists, prefer writing it explicitly. Errors{ctx}\n\n"),
            ]

        if category == CATEGORY_TIMEOUT:
            return [
                _new_variant(category,
                    "IMPORTANT: Keep your response concise and focused. "
                    "Previous attempt timed out. Reduce output length, "
                    "avoid unnecessary explanations.\n\n",
                    model_suggestion="haiku"),
                _new_variant(category,
                    "Time budget exceeded. Split the task mentally: emit ONLY the "
                    "core deliverable in this turn; skip commentary, examples, and "
                    "alternatives. Prioritize the JSON over prose.\n\n",
                    model_suggestion="haiku"),
            ]

        if category == CATEGORY_COST:
            return [
                _new_variant(category,
                    "COST ALERT: Use minimal tokens. Be extremely concise. "
                    "Output only the required JSON, nothing else.\n\n",
                    model_suggestion="haiku"),
                _new_variant(category,
                    "Token budget is tight. Strip every non-essential word. "
                    "No preambles, no summaries — only the required JSON object.\n\n",
                    model_suggestion="haiku"),
            ]

        if category == CATEGORY_CONTEXT_OVERFLOW:
            return [
                _new_variant(category,
                    "CONTEXT OVERFLOW: Previous attempt exceeded context window. "
                    "Reduce upstream input by using summary mode. "
                    "Keep your output concise — only essential JSON fields.\n\n",
                    context_reduction=True),
                _new_variant(category,
                    "Context window is full. Treat this request as a summarization: "
                    "produce only the distilled JSON result; do not echo input back.\n\n",
                    context_reduction=True),
            ]

        return []

    def select_variant(
        self, stage_id: str, category: Optional[str] = None
    ) -> Optional[dict]:
        """Pick the best variant for a stage using Thompson Sampling.

        Strategy:
          * Aggregate live variants across all records for this stage (by variant id).
          * With EPSILON_EXPLORE probability: pick uniformly at random (explore).
          * Otherwise: for each variant, sample theta ~ Beta(success+1, fail+1);
            return the argmax (exploit + exploration via posterior uncertainty).
          * Retired variants (fail_rate > 70% and >= 5 trials) are excluded.

        If `category` is provided, restrict to variants for that category.
        Returns None if no viable variants exist.
        """
        pool = self._aggregate_variants(stage_id, category)
        live = [v for v in pool if not v.get("retired")]
        if not live:
            return None

        if random.random() < EPSILON_EXPLORE:
            return random.choice(live)

        def _sample(v: dict) -> float:
            return random.betavariate(v.get("success", 0) + 1, v.get("fail", 0) + 1)

        return max(live, key=_sample)

    def _aggregate_variants(
        self, stage_id: str, category: Optional[str] = None
    ) -> list[dict]:
        """Merge variants across all records for a stage, summing success/fail per id.

        Legacy records without variants synthesize a single variant from fix_pattern
        so the Thompson pool is never empty for stages learned before this upgrade.
        """
        agg: dict[str, dict] = {}
        for rec in self.index.get(stage_id, []):
            if category and rec.category != category:
                continue
            source = list(rec.variants) if rec.variants else [
                _new_variant(rec.category, rec.fix_pattern.get("injection", ""))
            ] if rec.fix_pattern.get("injection") else []
            for v in source:
                vid = v.get("id") or _make_fix_id(rec.category, v.get("injection", ""))
                slot = agg.setdefault(vid, {
                    "id": vid,
                    "injection": v.get("injection", ""),
                    "category": rec.category,
                    "success": 0,
                    "fail": 0,
                    "retired": False,
                })
                slot["success"] += int(v.get("success", 0))
                slot["fail"] += int(v.get("fail", 0))
                if v.get("retired"):
                    slot["retired"] = True
                # carry through any hints
                for k in ("model_suggestion", "context_reduction"):
                    if v.get(k) is not None and k not in slot:
                        slot[k] = v[k]
        # apply retirement rule
        for v in agg.values():
            trials = v["success"] + v["fail"]
            if trials >= RETIRE_MIN_TRIALS and trials > 0:
                if v["fail"] / trials >= RETIRE_FAIL_RATE:
                    v["retired"] = True
        return list(agg.values())

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

    def mark_success(
        self, stage_id: str, applied_fix_ids: Optional[list[str]] = None
    ) -> None:
        """Increment success counters.

        If `applied_fix_ids` is provided, only variants whose id is in the list
        get success+1 (attribution). Otherwise falls back to legacy behavior:
        any record with applied_count>0 gets success_after_apply+1.
        """
        records = self.index.get(stage_id, [])
        fix_ids_set = set(applied_fix_ids or [])

        new_records: list[ErrorRecord] = []
        for rec in records:
            new_variants = self._score_variants(
                rec.variants or (), fix_ids_set, success=True
            )
            # Legacy success counter: bump if either applied_count>0 OR we matched any variant
            matched = any(
                (v.get("id") in fix_ids_set) for v in (rec.variants or ())
            )
            if applied_fix_ids is None:
                # Legacy behavior: bump by applied_count presence
                new_succ = (
                    rec.success_after_apply + 1 if rec.applied_count > 0
                    else rec.success_after_apply
                )
            else:
                new_succ = rec.success_after_apply + (1 if matched else 0)
            new_records.append(
                replace(rec, success_after_apply=new_succ, variants=new_variants)
            )
        self.index[stage_id] = new_records
        self._persist_all_records(stage_id)

    def mark_failed(
        self, stage_id: str, applied_fix_ids: Optional[list[str]] = None
    ) -> None:
        """Increment fail counters for applied variants (no-op if none provided)."""
        if not applied_fix_ids:
            return
        records = self.index.get(stage_id, [])
        fix_ids_set = set(applied_fix_ids)
        self.index[stage_id] = [
            replace(rec, variants=self._score_variants(
                rec.variants or (), fix_ids_set, success=False
            ))
            for rec in records
        ]
        self._persist_all_records(stage_id)

    def _score_variants(
        self, variants: tuple[dict, ...], fix_ids: set, *, success: bool
    ) -> tuple[dict, ...]:
        """Return a new tuple where variants matching fix_ids have success/fail bumped."""
        out: list[dict] = []
        for v in variants:
            if v.get("id") in fix_ids:
                nv = dict(v)
                key = "success" if success else "fail"
                nv[key] = int(nv.get(key, 0)) + 1
                trials = int(nv.get("success", 0)) + int(nv.get("fail", 0))
                if (
                    trials >= RETIRE_MIN_TRIALS
                    and int(nv.get("fail", 0)) / max(trials, 1) >= RETIRE_FAIL_RATE
                ):
                    nv["retired"] = True
                out.append(nv)
            else:
                out.append(dict(v))
        return tuple(out)

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
        """Write augment files for bash to read.

        Writes two formats side-by-side (writer-side backward compat):
          * augments/{stage_id}.txt  — concatenated injections (legacy consumers)
          * augments/{stage_id}.json — {"fix_ids": [...], "injection": "...", ...}
            for attribution-aware consumers (new pipeline-executor path)

        Selection: per category, Thompson-sample one variant; concatenate selected
        injections across categories. Falls back to lookup_fix for legacy records
        with no variants.
        """
        augments_dir = self.errors_dir / "augments"
        augments_dir.mkdir(exist_ok=True)

        for stage_id in self.index:
            categories = {rec.category for rec in self.index[stage_id]}
            chosen: list[dict] = []
            for cat in categories:
                v = self.select_variant(stage_id, category=cat)
                if v and v.get("injection"):
                    chosen.append(v)

            # Fallback: if no variants (pure-legacy records), use lookup_fix
            if not chosen:
                fixes = self.lookup_fix(stage_id)
                for f in fixes:
                    if f.get("injection"):
                        chosen.append({
                            "id": _make_fix_id("legacy", f["injection"]),
                            "injection": f["injection"],
                            "category": "legacy",
                        })

            if not chosen:
                continue

            injection_text = "".join(v["injection"] for v in chosen)
            (augments_dir / f"{stage_id}.txt").write_text(
                injection_text, encoding="utf-8"
            )
            (augments_dir / f"{stage_id}.json").write_text(
                json.dumps({
                    "stage_id": stage_id,
                    "fix_ids": [v["id"] for v in chosen],
                    "injection": injection_text,
                    "variants_applied": [
                        {"id": v["id"], "category": v.get("category", "?")}
                        for v in chosen
                    ],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, indent=2, ensure_ascii=False),
                encoding="utf-8",
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
        # Write augment immediately using Thompson Sampling (+ JSON with fix_ids).
        # write_augments() handles both legacy .txt and new .json formats.
        self.write_augments()
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
            "variants": list(record.variants),
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
                    variants=tuple(data.get("variants", [])),
                )
                self.index.setdefault(record.stage_id, []).append(record)
            except (json.JSONDecodeError, KeyError, OSError):
                continue
