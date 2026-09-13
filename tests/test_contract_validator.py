"""Tests for ai_sdlc_claudecode.contract_validator.

Uses the real ai-media-platform bug patterns (C1/C2/C3/H1/H3) as fixtures
so we verify the validator would have caught what Pipeline Phase 2 shipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sdlc_claudecode.contract_validator import validate


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_package_json(dir_path: Path, deps: dict[str, str] | None = None) -> None:
    data = {"name": dir_path.name, "version": "0.1.0", "dependencies": deps or {}}
    write(dir_path / "package.json", json.dumps(data))


def make_contracts(**overrides) -> dict:
    base = {
        "stage_id": "S2",
        "feature_id": "test",
        "timestamp": "2026-04-18T00:00:00Z",
        "contracts": {
            "services": [
                {"name": "biz-service", "responsibility": "core business", "language": "node", "port": 3000},
                {"name": "publisher-service", "responsibility": "publish to third-party", "language": "node", "port": 3001},
            ],
            "api_endpoints": [],
            "cross_service_messages": [],
            "encryption_pairs": [],
            "shared_models": [],
            "external_refs": {
                "ai_models": [
                    {"provider": "anthropic", "model_id": "claude-sonnet-4-6", "used_in_service": "biz-service"}
                ],
                "npm_packages_forbidden": ["crypto"],
            },
        },
    }
    base["contracts"].update(overrides)
    return base


# --- C2: duplicate / undeclared services --------------------------------

def test_detects_undeclared_service_directory(tmp_path: Path) -> None:
    contracts = make_contracts()
    # Create declared services
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    # Create an UNDECLARED duplicate (ai-media-platform C2 pattern)
    write_package_json(tmp_path / "ai-media-biz-service")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    hits = [v for v in report.violations if v.check == "duplicate_services"]
    assert len(hits) == 1
    assert "ai-media-biz-service" in hits[0].service
    assert "biz-service" in hits[0].message  # overlap detection


def test_accepts_only_declared_services(tmp_path: Path) -> None:
    contracts = make_contracts()
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    assert not [v for v in report.violations if v.check == "duplicate_services"]


# --- H1: forbidden npm packages -----------------------------------------

def test_detects_crypto_placeholder_package(tmp_path: Path) -> None:
    contracts = make_contracts()
    write_package_json(tmp_path / "biz-service", deps={"crypto": "^1.0.1", "express": "^4.18.0"})
    write_package_json(tmp_path / "publisher-service")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    hits = [v for v in report.violations if v.check == "forbidden_npm_package"]
    assert len(hits) == 1
    assert "crypto" in hits[0].message


# --- H3: hallucinated model IDs -----------------------------------------

def test_detects_hallucinated_model_id(tmp_path: Path) -> None:
    contracts = make_contracts()
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    # ai-media-platform used claude-opus-4-5-20251001 which never existed
    write(tmp_path / "biz-service" / "modelRouter.js",
          "const MODEL = 'claude-opus-4-5-20251001';\n")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    hits = [v for v in report.violations if v.check == "hallucinated_model_id"]
    assert len(hits) >= 1
    assert "claude-opus-4-5" in hits[0].evidence


def test_whitelisted_model_id_passes(tmp_path: Path) -> None:
    contracts = make_contracts()
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    write(tmp_path / "biz-service" / "modelRouter.js",
          "const MODEL = 'claude-sonnet-4-6';\n")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    assert not [v for v in report.violations if v.check == "hallucinated_model_id"]


# --- C1: encryption chain -----------------------------------------------

def test_detects_ciphertext_used_without_decrypt(tmp_path: Path) -> None:
    contracts = make_contracts(
        encryption_pairs=[
            {
                "field_name": "credentialsEncrypted",
                "algorithm": "aes-256-gcm",
                "key_env_var": "ENCRYPTION_KEY",
                "encrypt_in_service": "biz-service",
                "decrypt_in_services": ["publisher-service"],
            }
        ]
    )
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    # Writer encrypts
    write(tmp_path / "biz-service" / "platformAccountService.js",
          "const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);\n"
          "const credentialsEncrypted = cipher.update(plaintext);\n")
    # Reader ships ciphertext directly via axios — the exact ai-media-platform C1 bug
    write(tmp_path / "publisher-service" / "wechat.js",
          "const { credentialsEncrypted } = account;\n"
          "await axios.post('https://api.weixin.qq.com/publish', "
          "{ access_token: credentialsEncrypted });\n")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    hits = [v for v in report.violations if v.check == "missing_decrypt_before_use"]
    assert len(hits) == 1
    assert hits[0].service == "publisher-service"
    assert hits[0].severity == "CRITICAL"


def test_decrypt_present_passes(tmp_path: Path) -> None:
    contracts = make_contracts(
        encryption_pairs=[
            {
                "field_name": "credentialsEncrypted",
                "algorithm": "aes-256-gcm",
                "key_env_var": "ENCRYPTION_KEY",
                "encrypt_in_service": "biz-service",
                "decrypt_in_services": ["publisher-service"],
            }
        ]
    )
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    write(tmp_path / "biz-service" / "svc.js",
          "crypto.createCipheriv('aes-256-gcm', key, iv);\n")
    write(tmp_path / "publisher-service" / "wechat.js",
          "const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);\n"
          "const token = decipher.update(credentialsEncrypted);\n"
          "await axios.post('https://api.weixin.qq.com/publish', { access_token: token });\n")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    assert not [v for v in report.violations if v.check == "missing_decrypt_before_use"]


def test_detects_missing_encrypt_call(tmp_path: Path) -> None:
    contracts = make_contracts(
        encryption_pairs=[
            {
                "field_name": "credentialsEncrypted",
                "algorithm": "aes-256-gcm",
                "key_env_var": "ENCRYPTION_KEY",
                "encrypt_in_service": "biz-service",
                "decrypt_in_services": ["publisher-service"],
            }
        ]
    )
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    # Writer forgot to encrypt — stores plaintext as "credentialsEncrypted"
    write(tmp_path / "biz-service" / "svc.js",
          "const credentialsEncrypted = plaintext; // TODO: encrypt\n")
    write(tmp_path / "publisher-service" / "wechat.js", "// no-op\n")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    hits = [v for v in report.violations if v.check == "missing_encrypt_call"]
    assert len(hits) == 1
    assert hits[0].service == "biz-service"


# --- C3: cross-service message field drift ------------------------------

def test_detects_consumer_field_drift(tmp_path: Path) -> None:
    contracts = make_contracts(
        cross_service_messages=[
            {
                "queue_name": "publish-queue",
                "producer_service": "biz-service",
                "consumer_service": "publisher-service",
                "transport": "bullmq",
                "payload_fields": [
                    {"name": "publishTaskId", "type": "string", "required": True},
                    {"name": "platform", "type": "string", "required": True},
                ],
            }
        ]
    )
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    # Producer uses contract field names
    write(tmp_path / "biz-service" / "publishQueue.js",
          "await queue.add('publish-queue', { publishTaskId: id, platform: 'wechat' });\n")
    # Consumer renamed to 'taskId' — ai-media-platform C3
    write(tmp_path / "publisher-service" / "worker.js",
          "worker.process('publish-queue', async job => {\n"
          "  const { taskId, platform } = job.data;\n"
          "});\n")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    hits = [v for v in report.violations if v.check == "consumer_field_drift"]
    assert hits, f"expected consumer_field_drift, got {[v.check for v in report.violations]}"
    assert any("taskId" in h.message for h in hits)


# --- C2b: duplicate shared model registration ---------------------------

def test_detects_duplicate_mongoose_model_registration(tmp_path: Path) -> None:
    contracts = make_contracts(
        shared_models=[
            {
                "model_name": "Article",
                "owner_service": "biz-service",
                "storage": "mongodb",
                "fields": [{"name": "title", "type": "string"}],
            }
        ]
    )
    write_package_json(tmp_path / "biz-service")
    write_package_json(tmp_path / "publisher-service")
    # Owner defines the model — OK
    write(tmp_path / "biz-service" / "models.js",
          "mongoose.model('Article', schema);\n")
    # Non-owner redefines — VIOLATION
    write(tmp_path / "publisher-service" / "models.js",
          "mongoose.model('Article', differentSchema);\n")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    hits = [v for v in report.violations if v.check == "duplicate_model_registration"]
    assert len(hits) == 1
    assert hits[0].service == "publisher-service"


# --- Integration: happy path --------------------------------------------

def test_clean_project_has_no_blocking_violations(tmp_path: Path) -> None:
    contracts = make_contracts()
    write_package_json(tmp_path / "biz-service", deps={"express": "^4.18.0"})
    write_package_json(tmp_path / "publisher-service", deps={"axios": "^1.6.0"})

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    assert not report.blocking(), \
        f"expected clean, got {[(v.check, v.message) for v in report.blocking()]}"


def test_aggregate_report_structure(tmp_path: Path) -> None:
    contracts = make_contracts()
    write_package_json(tmp_path / "biz-service", deps={"crypto": "^1.0.1"})
    write_package_json(tmp_path / "publisher-service")

    contracts_path = tmp_path / "contracts.json"
    write(contracts_path, json.dumps(contracts))

    report = validate(contracts_path, tmp_path)
    d = report.as_dict()
    assert d["total"] >= 1
    assert d["by_severity"]["HIGH"] >= 1
    assert isinstance(d["violations"], list)
