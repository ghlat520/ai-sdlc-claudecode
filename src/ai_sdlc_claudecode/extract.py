"""Unified JSON extraction with multi-level fallback and repair.

Replaces duplicated inline Python in pipeline-executor.sh and
orchestrate-parallel.sh with a single, testable module.

Strategy (each level tried in order):
    1. Direct json.loads on entire text
    2. Regex extraction of ```json ... ``` code blocks
    3. Brace-balanced extraction of outermost { ... }
    4. JSON repair (trailing commas, BOM, single quotes, etc.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


def extract_json(text: str) -> Optional[dict]:
    """Extract a JSON object from *text* using multi-level fallback.

    Returns the parsed dict on success, or ``None`` if no valid JSON found.
    """
    if not text or not text.strip():
        return None

    stripped = text.strip()

    # Level 1: entire text is valid JSON
    result = _try_parse(stripped)
    if result is not None:
        return result

    # Level 2: ```json ... ``` markdown code blocks (prefer last match)
    code_blocks = re.findall(r"```json\s*\n(.*?)\n\s*```", stripped, re.DOTALL)
    for block in reversed(code_blocks):
        result = _try_parse(block.strip())
        if result is not None:
            return result

    # Level 3: brace-balanced extraction (handles nested objects)
    result = _extract_balanced_json(stripped)
    if result is not None:
        return result

    # Level 4: repair common issues and retry
    candidates = [b.strip() for b in reversed(code_blocks)] if code_blocks else []
    balanced = _find_balanced_substring(stripped)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        result = _try_parse(_repair_json_text(candidate))
        if result is not None:
            return result

    return None


def extract_and_save(
    output_path: str,
    *,
    input_path: Optional[str] = None,
    text: Optional[str] = None,
) -> bool:
    """Extract JSON from file or text, save to *output_path*.

    Returns ``True`` on success, ``False`` on failure.
    """
    if text is None:
        if input_path is None:
            raise ValueError("Either input_path or text must be provided")
        text = Path(input_path).read_text(encoding="utf-8", errors="replace")

    data = extract_json(text)
    if data is None:
        return False

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_parse(text: str) -> Optional[dict]:
    """Try ``json.loads``; return dict or None."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _extract_balanced_json(text: str) -> Optional[dict]:
    """Find the last brace-balanced ``{ ... }`` and parse it."""
    substring = _find_balanced_substring(text)
    if substring is not None:
        return _try_parse(substring)
    return None


def _find_balanced_substring(text: str) -> Optional[str]:
    """Return the last brace-balanced ``{ ... }`` substring, or None."""
    # Walk backwards to find the last top-level '{' ... '}'
    # We scan forward from each '{' candidate, tracking brace depth.
    last_match: Optional[str] = None
    i = 0
    length = len(text)
    in_string = False
    escape_next = False

    while i < length:
        ch = text[i]

        if ch == "{" and not in_string:
            # Try to find balanced close from here
            result = _scan_balanced(text, i)
            if result is not None:
                last_match = result
                # Jump past this match to find later ones
                i += len(result)
                continue

        i += 1

    return last_match


def _scan_balanced(text: str, start: int) -> Optional[str]:
    """Scan from *start* (which must be '{') and return balanced substring."""
    depth = 0
    in_string = False
    escape_next = False
    i = start

    while i < len(text):
        ch = text[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if ch == "\\" and in_string:
            escape_next = True
            i += 1
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            i += 1
            continue

        if not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        i += 1

    return None


def _repair_json_text(text: str) -> str:
    """Apply common JSON repairs to *text*."""
    if not text:
        return text

    # Remove BOM
    repaired = text.lstrip("\ufeff")

    # Remove trailing commas before } or ]
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

    # Replace single quotes with double quotes (outside existing double-quoted strings)
    # Only if no double quotes present (simple heuristic to avoid breaking valid JSON)
    if '"' not in repaired and "'" in repaired:
        repaired = repaired.replace("'", '"')

    # Strip JavaScript-style comments (// ... and /* ... */)
    repaired = re.sub(r"//[^\n]*", "", repaired)
    repaired = re.sub(r"/\*.*?\*/", "", repaired, flags=re.DOTALL)

    return repaired
