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
