"""The pilot's task card and actual dispatch text share one source inventory."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def validator():
    path = Path(__file__).resolve().parents[1] / "scripts/validate-model-context.py"
    spec = importlib.util.spec_from_file_location("model_context", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def context(tmp_path):
    root = tmp_path / "candidate"
    files = {"pilot/task.md": "Read [source](backend-python/app/main.py).",
             "backend-python/app/main.py": "print('synthetic')\n",
             "backend-python/tests/conftest.py": "# shared runtime fixture\n",
             "backend-python/tests/test_case.py": "def test_case(): pass\n"}
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return {"candidate_root": str(root), "task_card": "pilot/task.md",
            "proposed_model_read_files": {
                name: {"sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
                for name in files}, "allowed_mutations": ["backend-python/tests/test_case.py"]}


def test_task_card_and_actual_prompt_use_approved_sources(context):
    guard = validator()
    result = guard.check_context(context)
    assert result["task_references"] == ["backend-python/app/main.py"]
    result = guard.check_text(
        "Read pilot/task.md and app/main.py. Case tests/test_case.py::test_case.", context)
    assert set(result) == {"pilot/task.md", "backend-python/app/main.py",
                           "backend-python/tests/test_case.py"}


@pytest.mark.parametrize("path", [
    "../task-dag.json", "docs/am-iso-01-startup.md",
    "docs/ai-management-evaluation-20261117.md", "docs/ai-management.md",
    "../old/PILOT-RECEIPT.md", "../old/freeze-manifest.json",
    "../old/candidate-manifest-v2.json", "../old/candidate-v2/pilot-contract.json",
    "../old/candidate-v2/pilot_acceptance.py", "%2e%2e/outside.md",
    "file:///etc/passwd", "https://example.test/private.md",
    "/etc/passwd", "../.env", "../private.csv", "private/data.custom", "../PRIVATE.MD",
    ".env", "private.csv", "secret.custom",
])
def test_outside_paths_rejected_in_card_and_final_dispatch(context, path):
    guard = validator()
    for text in (f"Read [source]({path}).", f"Upstream source_refs: {json.dumps([path])}"):
        with pytest.raises(ValueError, match="source"):
            guard.check_text(text, context)


def test_reference_links_rejected_when_target_outside(context):
    with pytest.raises(ValueError, match="source"):
        validator().check_text("Read [design][ref].\n\n[ref]: ../design.md", context)


def test_task_reference_drift_rejected_before_model(context):
    path = Path(context["candidate_root"]) / "pilot/task.md"
    path.write_text("Read [old](../task-dag.json).")
    context["proposed_model_read_files"]["pilot/task.md"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="source"):
        validator().check_context(context)


def test_inventory_symlink_cannot_escape_candidate(context, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("synthetic = True\n")
    path = Path(context["candidate_root"]) / "backend-python/app/main.py"
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="source"):
        validator().check_context(context)


def test_immutable_source_bytes_pinned_and_allowed_repair_remains_possible(context):
    guard = validator()
    root = Path(context["candidate_root"])
    (root / "backend-python/tests/test_case.py").write_text("def test_case(): assert True\n")
    guard.check_context(context)
    (root / "backend-python/app/main.py").write_text("unexpected = True\n")
    with pytest.raises(ValueError, match="source"):
        guard.check_context(context)


def test_model_source_refs_are_checked_again_after_execution(context):
    guard = validator()
    assert guard.check_source_refs(["pilot/task.md:1; original card"], context) == ["pilot/task.md"]
    for refs in (["../task-dag.json; unapproved"], ["entire repository"], []):
        with pytest.raises(ValueError, match="source"):
            guard.check_source_refs(refs, context)


def test_schema_identifier_and_supervisor_sink_are_metadata(context):
    assert validator().check_text(
        'Return output.json using {"$schema":"https://json-schema.org/draft/2020-12/schema"}.',
        context) == []


def test_http_parameter_values_are_data_and_not_file_references(context):
    assert validator().check_text(
        '"tests/test_case.py::test_case[/api/x-/api]"', context) == ["backend-python/tests/test_case.py"]


def test_handoff_prose_resolves_unique_approved_filename(context):
    guard = validator()
    assert guard.check_text(
        "No conftest.py change is currently justified. Read test_case.py:1.", context
    ) == ["backend-python/tests/conftest.py", "backend-python/tests/test_case.py"]
    with pytest.raises(ValueError, match="source"):
        guard.check_source_refs(["conftest.py; abbreviated structured source"], context)
    with pytest.raises(ValueError, match="source"):
        guard.check_text("Read [fixture](conftest.py).", context)


def test_handoff_prose_rejects_ambiguous_approved_filename(context):
    root = Path(context["candidate_root"])
    other = "backend-python/app/conftest.py"
    (root / other).write_text("# different fixture\n")
    context["proposed_model_read_files"][other] = {
        "sha256": hashlib.sha256((root / other).read_bytes()).hexdigest()
    }
    with pytest.raises(ValueError, match="source"):
        validator().check_text("Read conftest.py.", context)


def test_handoff_filename_cannot_hide_an_unapproved_root_file(context):
    (Path(context["candidate_root"]) / "conftest.py").write_text("# outside the inventory\n")
    with pytest.raises(ValueError, match="source"):
        validator().check_text("Read conftest.py.", context)


def test_declared_database_field_is_data_in_handoff_prose(context):
    context["data_identifiers"] = ["market_user.phone"]
    assert validator().check_text(
        "Registration maps a market_user.phone integrity conflict to HTTP 409. "
        "No conftest.py change is currently justified.", context
    ) == ["backend-python/tests/conftest.py"]


@pytest.mark.parametrize("text", [
    "Read [source](market_user.phone).",
    'Upstream source_refs: ["market_user.phone"]',
    'Upstream source_refs: ["conftest.py"]',
    "Read ./market_user.phone.",
])
def test_database_data_declaration_cannot_authorize_a_file_reference(context, text):
    context["data_identifiers"] = ["market_user.phone"]
    with pytest.raises(ValueError, match="source"):
        validator().check_text(text, context)


@pytest.mark.parametrize("identifiers", [
    "market_user.phone", ["../market_user.phone"], ["market_user.phone:1"],
    ["market_user.phone", "market_user.phone"], [12],
])
def test_invalid_data_identifier_declarations_rejected(context, identifiers):
    context["data_identifiers"] = identifiers
    with pytest.raises(ValueError, match="identifier"):
        validator().check_text("Return the task summary.", context)


@pytest.mark.parametrize("symlink", [False, True])
def test_declared_database_field_cannot_hide_a_root_file(context, tmp_path, symlink):
    context["data_identifiers"] = ["market_user.phone"]
    path = Path(context["candidate_root"]) / "market_user.phone"
    if symlink:
        path.symlink_to(tmp_path / "outside-data")
    else:
        path.write_text("outside the approved file inventory\n")
    with pytest.raises(ValueError, match="source"):
        validator().check_text("Open market_user.phone.", context)


def test_authorized_root_filename_remains_canonical_when_nested_name_matches(context):
    root = Path(context["candidate_root"])
    (root / "conftest.py").write_text("# approved root fixture\n")
    context["proposed_model_read_files"]["conftest.py"] = {
        "sha256": hashlib.sha256((root / "conftest.py").read_bytes()).hexdigest()
    }
    guard = validator()
    assert guard.check_text("Read [root](conftest.py).", context) == ["conftest.py"]
    assert guard.check_source_refs(["conftest.py; approved root"], context) == ["conftest.py"]


@pytest.mark.parametrize("refs", [
    "conftest.py", [], {"file": "conftest.py"},
    ["pilot/task.md; inspect ../outside.custom"],
])
def test_embedded_references_use_the_decoded_structured_source_contract(context, refs):
    payload = json.dumps({"source_refs": refs}).replace(".", "\\u002e")
    with pytest.raises(ValueError, match="source"):
        validator().check_text(payload, context)


def test_inline_source_reference_schema_remains_metadata(context):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "type": "object", "properties": {"source_refs": {
        "type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}
    }}}
    assert validator().check_text(json.dumps(schema), context) == []


def test_declared_data_identifier_with_file_like_suffix_is_still_data(context):
    context["data_identifiers"] = ["market_user.env"]
    assert validator().check_text("The field market_user.env is a string.", context) == []


def test_escaped_source_reference_key_cannot_become_prose(context):
    text = '{"source\\u005frefs": ["conftest.py"]}'
    with pytest.raises(ValueError, match="source"):
        validator().check_text(text, context)


def test_schema_shaped_source_reference_value_is_still_a_bad_reference(context):
    text = json.dumps({"source_refs": {
        "type": "array", "items": {"type": "string"}, "references": ["conftest.py"]
    }})
    with pytest.raises(ValueError, match="source"):
        validator().check_text(text, context)


def test_schema_metadata_description_is_checked_after_json_decoding(context):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "type": "object", "properties": {"source_refs": {
                  "type": "array", "items": {"type": "string"},
                  "description": "Read ../outside.custom"
              }}}
    text = json.dumps(schema).replace(".", "\\u002e").replace("/", "\\u002f")
    with pytest.raises(ValueError, match="source"):
        validator().check_text(text, context)


def test_source_reference_label_in_ordinary_prose_is_not_a_json_document(context):
    assert validator().check_text(
        "About source_refs: keep the approved entries.", context) == []
