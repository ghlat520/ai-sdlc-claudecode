"""
Cross-Service Contract Validator.

Consumed after S3/S3b to detect drift between the strong contracts emitted
by S2 (contracts.json) and the code actually produced downstream. Catches
the class of bugs that ai-media-platform shipped on 2026-03-19:

  C1. Encrypt/decrypt chain broken — writer encrypts, reader ships ciphertext.
  C2. Duplicate services with divergent schemas.
  C3. Cross-service message field-name drift (publishTaskId vs taskId).
  H1. Hallucinated npm packages (e.g. "crypto": "^1.0.1").
  H3. Hallucinated LLM model IDs (e.g. claude-opus-4-5-20251001).

Usage:
    python -m lib.contract_validator CONTRACTS_JSON CODE_ROOT

Exits 0 on pass, 1 on any CRITICAL/HIGH violation. Prints a machine-readable
JSON report to stdout and a human summary to stderr.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable


SEVERITY_BLOCKING = {"CRITICAL", "HIGH"}


@dataclass
class Violation:
    check: str
    severity: str
    service: str
    message: str
    evidence: str = ""
    file: str = ""
    line: int = 0


@dataclass
class Report:
    violations: list[Violation] = field(default_factory=list)

    def add(self, v: Violation) -> None:
        self.violations.append(v)

    def blocking(self) -> list[Violation]:
        return [v for v in self.violations if v.severity in SEVERITY_BLOCKING]

    def as_dict(self) -> dict:
        return {
            "total": len(self.violations),
            "blocking": len(self.blocking()),
            "by_severity": {
                sev: sum(1 for v in self.violations if v.severity == sev)
                for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
            },
            "violations": [asdict(v) for v in self.violations],
        }


CODE_SUFFIXES = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".py", ".java", ".go"}
SKIP_DIRS = {"node_modules", "dist", "build", "target", ".git", "__pycache__", ".venv", "venv"}


def iter_code_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def service_root(code_root: Path, service_name: str) -> Path | None:
    candidate = code_root / service_name
    return candidate if candidate.is_dir() else None


def grep_lines(path: Path, pattern: re.Pattern) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f, 1):
                if pattern.search(line):
                    hits.append((idx, line.rstrip("\n")))
    except OSError:
        pass
    return hits


# --- Individual checks ---------------------------------------------------

def check_duplicate_services(contracts: dict, code_root: Path, report: Report) -> None:
    """C2: Every code directory that looks like a service must match contracts.services[]."""
    declared = {s["name"] for s in contracts["services"]}
    if not code_root.is_dir():
        return
    for child in code_root.iterdir():
        if not child.is_dir() or child.name in SKIP_DIRS:
            continue
        has_manifest = (child / "package.json").exists() or (child / "pyproject.toml").exists() or (child / "pom.xml").exists() or (child / "requirements.txt").exists()
        if not has_manifest:
            continue
        if child.name not in declared:
            overlap = [d for d in declared if d in child.name or child.name in d]
            msg = f"Undeclared service directory '{child.name}'."
            if overlap:
                msg += f" Looks like a duplicate of declared {overlap} — collapse into one."
            report.add(Violation(
                check="duplicate_services",
                severity="CRITICAL",
                service=child.name,
                message=msg,
                file=str(child),
            ))


def check_forbidden_npm(contracts: dict, code_root: Path, report: Report) -> None:
    """H1: Any package in external_refs.npm_packages_forbidden must not appear in any package.json."""
    forbidden = set(contracts.get("external_refs", {}).get("npm_packages_forbidden", []))
    if not forbidden:
        return
    for pj in code_root.rglob("package.json"):
        if any(part in SKIP_DIRS for part in pj.parts):
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for dep in (data.get(section) or {}):
                if dep in forbidden:
                    report.add(Violation(
                        check="forbidden_npm_package",
                        severity="HIGH",
                        service=pj.parent.name,
                        message=f"Forbidden package '{dep}' in {section}.",
                        evidence=f"{dep}: {data[section][dep]}",
                        file=str(pj),
                    ))


def check_ai_model_ids(contracts: dict, code_root: Path, report: Report) -> None:
    """H3: Any claude-* / gpt-* identifier in code must appear in external_refs.ai_models[]."""
    whitelist = {m["model_id"] for m in contracts.get("external_refs", {}).get("ai_models", [])}
    id_pattern = re.compile(r"(claude-[a-z0-9][a-z0-9.-]+|gpt-[a-z0-9][a-z0-9.-]+|gemini-[a-z0-9][a-z0-9.-]+)")
    for path in iter_code_files(code_root):
        for line_no, line in grep_lines(path, id_pattern):
            for match in id_pattern.findall(line):
                m = match.rstrip("'\"`,);")
                if whitelist and m not in whitelist:
                    report.add(Violation(
                        check="hallucinated_model_id",
                        severity="HIGH",
                        service=_infer_service(path, code_root),
                        message=f"Model ID '{m}' not in contracts.external_refs.ai_models whitelist.",
                        evidence=line.strip(),
                        file=str(path),
                        line=line_no,
                    ))


def check_encryption_pairs(contracts: dict, code_root: Path, report: Report) -> None:
    """C1: Every decrypt_in_services must call decrypt before using the encrypted field."""
    for pair in contracts.get("encryption_pairs", []):
        field_name = pair["field_name"]
        encrypt_svc = pair["encrypt_in_service"]
        decrypt_svcs = pair.get("decrypt_in_services", [])

        # Writer side must have encrypt / cipher
        enc_root = service_root(code_root, encrypt_svc)
        if enc_root and not _has_crypto_call(enc_root, kind="encrypt"):
            report.add(Violation(
                check="missing_encrypt_call",
                severity="CRITICAL",
                service=encrypt_svc,
                message=f"Service '{encrypt_svc}' declared as encrypt_in_service for '{field_name}' but no encrypt()/cipher call found.",
            ))

        # Reader side: for each consumer, any use of field_name must be preceded by decrypt() in the same file
        field_pat = re.compile(rf"\b{re.escape(field_name)}\b")
        for svc in decrypt_svcs:
            svc_root = service_root(code_root, svc)
            if not svc_root:
                continue
            offenders = _find_ciphertext_direct_use(svc_root, field_name, field_pat)
            for off in offenders:
                report.add(Violation(
                    check="missing_decrypt_before_use",
                    severity="CRITICAL",
                    service=svc,
                    message=f"Service '{svc}' uses encrypted field '{field_name}' without a decrypt() call in the same file. Ciphertext leaking to external caller.",
                    evidence=off[1],
                    file=str(off[0]),
                    line=off[2],
                ))


def check_message_field_alignment(contracts: dict, code_root: Path, report: Report) -> None:
    """C3: Producer and consumer of a queue must reference identical payload field names."""
    for msg in contracts.get("cross_service_messages", []):
        expected = {f["name"] for f in msg["payload_fields"] if f.get("required", True)}
        queue = msg["queue_name"]
        producer = msg["producer_service"]
        consumer = msg["consumer_service"]

        prod_root = service_root(code_root, producer)
        cons_root = service_root(code_root, consumer)

        prod_fields = _fields_near_token(prod_root, queue) if prod_root else set()
        cons_fields = _fields_near_token(cons_root, queue) if cons_root else set()

        # Fields required by contract but absent on producer side
        missing_on_producer = expected - prod_fields if prod_fields else set()
        # Fields present in consumer code but not in contract → possible alias drift
        consumer_drift = cons_fields - expected - prod_fields if cons_fields else set()

        for f in missing_on_producer:
            report.add(Violation(
                check="producer_missing_field",
                severity="HIGH",
                service=producer,
                message=f"Queue '{queue}': producer '{producer}' does not set required field '{f}'.",
            ))
        for f in consumer_drift:
            report.add(Violation(
                check="consumer_field_drift",
                severity="CRITICAL",
                service=consumer,
                message=f"Queue '{queue}': consumer '{consumer}' destructures '{f}' but it is not in the contract payload (likely renamed — e.g. taskId vs publishTaskId).",
            ))


def check_shared_model_single_owner(contracts: dict, code_root: Path, report: Report) -> None:
    """C2b: mongoose.model('X')/Base.metadata registrations only in owner_service."""
    for model in contracts.get("shared_models", []):
        name = model["model_name"]
        owner = model["owner_service"]
        mongoose_pat = re.compile(rf"""mongoose\.model\(\s*['"]{re.escape(name)}['"]""")
        owners_found: list[Path] = []
        others_found: list[Path] = []
        for path in iter_code_files(code_root):
            if not grep_lines(path, mongoose_pat):
                continue
            svc = _infer_service(path, code_root)
            if svc == owner:
                owners_found.append(path)
            else:
                others_found.append(path)
        for path in others_found:
            report.add(Violation(
                check="duplicate_model_registration",
                severity="CRITICAL",
                service=_infer_service(path, code_root),
                message=f"Model '{name}' redefined outside owner_service '{owner}'. Import it instead.",
                file=str(path),
            ))


# --- Helpers -------------------------------------------------------------

def _infer_service(path: Path, code_root: Path) -> str:
    try:
        rel = path.relative_to(code_root)
    except ValueError:
        return "?"
    return rel.parts[0] if rel.parts else "?"


def _has_crypto_call(root: Path, kind: str) -> bool:
    patterns = {
        "encrypt": re.compile(r"(createCipheriv|\.encrypt\(|cipher\.update|AES\.encrypt|Fernet\(.*\)\.encrypt)"),
        "decrypt": re.compile(r"(createDecipheriv|\.decrypt\(|decipher\.update|AES\.decrypt|Fernet\(.*\)\.decrypt)"),
    }
    pat = patterns[kind]
    for path in iter_code_files(root):
        if grep_lines(path, pat):
            return True
    return False


def _find_ciphertext_direct_use(root: Path, field_name: str, field_pat: re.Pattern) -> list[tuple[Path, str, int]]:
    """Return (file, line_text, line_no) for files that use field_name without calling decrypt() nearby."""
    decrypt_pat = re.compile(r"(createDecipheriv|\.decrypt\(|decipher\.update|AES\.decrypt|decryptCredentials|decryptField)")
    offenders: list[tuple[Path, str, int]] = []
    for path in iter_code_files(root):
        hits = grep_lines(path, field_pat)
        if not hits:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        has_decrypt = bool(decrypt_pat.search(text))
        # Heuristic: if file references field_name AND makes an outbound HTTP call AND does not decrypt → offender
        if has_decrypt:
            continue
        outbound = re.search(r"(axios\.|fetch\(|got\(|requests\.|http\.request|https\.request)", text)
        if outbound:
            offenders.append((path, hits[0][1].strip(), hits[0][0]))
    return offenders


def _fields_near_token(root: Path, token: str) -> set[str]:
    """Collect likely field names appearing in the same file as `token` (queue name).

    Heuristic: look for object literal keys and destructuring patterns. False positives are OK —
    the check flags missing fields, so over-collection is safe; under-collection is risky.
    """
    fields: set[str] = set()
    token_pat = re.compile(re.escape(token))
    key_pat = re.compile(r"[\{\,]\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[:,}]")
    destr_pat = re.compile(r"\bconst\s*\{\s*([^}]+)\s*\}\s*=")
    for path in iter_code_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not token_pat.search(text):
            continue
        for m in key_pat.finditer(text):
            fields.add(m.group(1))
        for m in destr_pat.finditer(text):
            for name in re.split(r",|\s", m.group(1)):
                name = name.strip()
                if name and re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
                    fields.add(name)
    # Strip obvious non-fields
    return {f for f in fields if f not in {"const", "let", "var", "if", "return", "this", "from", "import"}}


# --- Entry point ---------------------------------------------------------

def validate(contracts_path: Path, code_root: Path) -> Report:
    contracts_doc = json.loads(contracts_path.read_text(encoding="utf-8"))
    contracts = contracts_doc.get("contracts", contracts_doc)
    report = Report()
    check_duplicate_services(contracts, code_root, report)
    check_forbidden_npm(contracts, code_root, report)
    check_ai_model_ids(contracts, code_root, report)
    check_encryption_pairs(contracts, code_root, report)
    check_message_field_alignment(contracts, code_root, report)
    check_shared_model_single_owner(contracts, code_root, report)
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("Usage: contract_validator.py CONTRACTS_JSON CODE_ROOT\n")
        return 2
    contracts_path = Path(argv[1])
    code_root = Path(argv[2])
    if not contracts_path.is_file():
        sys.stderr.write(f"contracts.json not found: {contracts_path}\n")
        return 2
    if not code_root.is_dir():
        sys.stderr.write(f"code root not a directory: {code_root}\n")
        return 2

    report = validate(contracts_path, code_root)
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))

    blocking = report.blocking()
    if blocking:
        sys.stderr.write(f"\n{len(blocking)} blocking violation(s):\n")
        for v in blocking:
            loc = f" ({v.file}:{v.line})" if v.line else (f" ({v.file})" if v.file else "")
            sys.stderr.write(f"  [{v.severity}] {v.check} @ {v.service}{loc}\n    {v.message}\n")
        return 1
    sys.stderr.write(f"\ncontract_validator: PASS ({len(report.violations)} non-blocking notes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
