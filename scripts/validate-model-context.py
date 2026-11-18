#!/usr/bin/env python3
"""Check declared project sources at the task, dispatch and returned-reference seams.

This validates input consistency. It does not intercept model tool calls or replace
an operating-system file-read sandbox. Relative references use the candidate root.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote


LINK = re.compile(r"\]\(\s*<?([^\s)>]+)>?(?:\s+[^)]*)?\)|^\s*\[[^\]]+\]:\s*<?([^\s>]+)", re.M)
TOKEN = re.compile(
    r"(?:https?|file)://[^\s<>\"'`)]+|"
    r"(?<![\w])(?:[A-Za-z]:[\\/]|/|\.{1,2}/)?"
    r"(?:[\w@%+~.\-]+[\\/])*[\w@%+~.\-]+"
    r"\.(?:py|md|json|toml|ya?ml|sh|txt|pem|sqlite3?|db|env)(?::\d+(?:[,\-]\d+)*)?", re.I
)
EXPLICIT = re.compile(r'''(?<![^\s"'`(<])(?:[A-Za-z]:[\\/]|/|\.{1,2}/)[^\s<>"'`()\[\]{};,|]+''')
RELATIVE_FILE = re.compile(r'''(?<![^\s"'`(<])(?:[\w@%+~.\-]+/)+[\w@%+~.\-]+\.[\w.\-]+''')
BARE_FILE = re.compile(r'''(?<![^\s"'`(<])(?:\.[A-Za-z][\w.\-]*|[\w@%+~\-][\w@%+~.\-]*\.[A-Za-z][\w.\-]{1,15})(?![\w/])''')
SOURCE_REFS = re.compile(r'''(?<!\w)["']?source_refs["']?\s*:\s*(?=\[)''')
SCHEMA_ID = "https://json-schema.org/draft/2020-12/schema"


def source_path(token, context, *, prose=False):
    raw = token.strip("<>`\"' ")
    for _ in range(3):
        raw = unquote(raw)
    raw = re.sub(r":\d+(?:[,\-]\d+)*$", "", raw.split("::", 1)[0].split("#", 1)[0])
    raw = raw.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", raw) or "://" in raw:
        raise ValueError("Unapproved project source: " + token)
    root = Path(context["candidate_root"]).resolve(strict=True)
    if prose and "/" not in raw and not raw.startswith("."):
        if raw not in context["proposed_model_read_files"] and ((root / raw).exists() or (root / raw).is_symlink()):
            raise ValueError("Unapproved project source: " + token)
        matches = [name for name in context["proposed_model_read_files"] if Path(name).name == raw]
        if len(matches) > 1:
            raise ValueError("Ambiguous project source: " + token)
        if matches:
            raw = matches[0]
    path = Path(raw)
    if not path.is_absolute():
        # Original pytest contracts express node IDs relative to backend-python.
        if raw.startswith(("tests/", "acceptance/", "app/")):
            path = Path("backend-python") / path
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError:
        raise ValueError("Outside project source: " + token)
    if relative not in context["proposed_model_read_files"] or not resolved.is_file():
        raise ValueError("Unapproved project source: " + token)
    if path.absolute() != resolved:
        raise ValueError("Non-canonical or symlink project source: " + token)
    return relative


def check_text(text, context):
    # Explicitly declared business symbols apply only to bare prose, never file links or source_refs.
    identifiers = context.get("data_identifiers", [])
    if (not isinstance(identifiers, list)
            or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", value)
                   for value in identifiers)
            or len(identifiers) != len(set(identifiers))):
        raise ValueError("Invalid data identifier declaration")
    references = set()
    for match in SOURCE_REFS.finditer(text):
        refs, _ = json.JSONDecoder().raw_decode(text[match.end():])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("Model source_refs must contain approved project paths")
        for ref in refs:
            references.add(source_path(ref.split(";", 1)[0], context))
    for link in LINK.finditer(text):
        target = link.group(1) or link.group(2)
        if not target.startswith("#"):
            references.add(source_path(target, context))
    for match in TOKEN.finditer(text):
        token = match.group(0).rstrip(".,;")
        # The schema URL is an identifier; output.json is the supervisor-owned sink.
        if token in (SCHEMA_ID, "output.json"):
            continue
        references.add(source_path(token, context, prose=True))
    for pattern in (EXPLICIT, RELATIVE_FILE, BARE_FILE):
        for match in pattern.finditer(text):
            token = match.group(0).rstrip(".,;")
            if pattern is BARE_FILE and token in identifiers:
                continue
            if token != 'output.json':
                references.add(source_path(token, context, prose=True))
    return sorted(references)


def check_context(context):
    root = Path(context["candidate_root"]).resolve(strict=True)
    allowed = context["proposed_model_read_files"]
    mutable = set(context.get("allowed_mutations", []))
    if not mutable <= set(allowed):
        raise ValueError("Mutation paths exceed project source inventory")
    for relative, identity in allowed.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Non-canonical inventory source: " + relative)
        path = root / relative
        if source_path(str(path), context) != relative:
            raise ValueError("Source alias changes inventory identity: " + relative)
        if relative not in mutable and hashlib.sha256(path.read_bytes()).hexdigest() != identity["sha256"]:
            raise ValueError("Immutable project source changed: " + relative)
    card = context.get("task_card", "pilot/task.md")
    source_path(card, context)
    return {"project_files": len(allowed), "task_references": check_text((root / card).read_text(), context)}


def check_source_refs(refs, context):
    if not isinstance(refs, list) or not refs:
        raise ValueError("Model source_refs must contain approved project paths")
    results = set()
    for ref in refs:
        if not isinstance(ref, str):
            raise ValueError("Model source reference must be a string")
        # Descriptions may follow ';'; the first field is the auditable source identity.
        results.add(source_path(ref.split(";", 1)[0], context))
        check_text(ref, context)
    return sorted(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--text", type=Path)
    parser.add_argument("--source-refs", type=Path)
    args = parser.parse_args()
    context = json.loads(args.context.read_text())
    result = check_context(context)
    if args.text:
        result["text_references"] = check_text(args.text.read_text(), context)
    if args.source_refs:
        result["returned_references"] = check_source_refs(json.loads(args.source_refs.read_text()), context)
    print(json.dumps({"context_consistency": "passed", **result}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit("Context rejected: " + str(error))
