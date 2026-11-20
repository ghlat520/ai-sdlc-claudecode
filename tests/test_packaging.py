"""Installed distributions contain the pipeline's runtime resources."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_DIRS = ("lib", "schemas", "prompts", "scripts")


@pytest.mark.parametrize("distribution", ["wheel", "sdist"])
def test_installed_distribution_contains_pipeline_runtime(tmp_path, distribution):
    source = tmp_path / "source"
    source.mkdir()
    for directory in ("src", *RESOURCE_DIRS):
        shutil.copytree(
            PROJECT_ROOT / directory, source / directory, symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
        )
    inputs = [*PROJECT_ROOT.glob("*.sh"), PROJECT_ROOT / "pipeline-dag.json"]
    for name in ("pyproject.toml", "README.md", "setup.py", "setup.cfg", "MANIFEST.in"):
        if (PROJECT_ROOT / name).is_file():
            inputs.append(PROJECT_ROOT / name)
    for path in inputs:
        shutil.copy2(path, source / path.name)

    resources = [*source.glob("*.sh"), source / "pipeline-dag.json"]
    for directory in RESOURCE_DIRS:
        resources.extend(path for path in (source / directory).rglob("*") if path.is_file())
    expected = {path.relative_to(source).as_posix(): path.read_bytes() for path in resources}

    environment = {
        key: value for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "PROJECT_ROOT"}
        and not key.startswith("PIPELINE_")
    }
    environment.update(PYTHONDONTWRITEBYTECODE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    records = tmp_path / "commands"
    records.mkdir()

    def run(name, command, cwd, expected_exit=0):
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(
            [str(part) for part in command], cwd=cwd, env=environment,
            text=True, capture_output=True, timeout=120,
        )
        (records / f"{name}.stdout.txt").write_text(result.stdout)
        (records / f"{name}.stderr.txt").write_text(result.stderr)
        (records / f"{name}.json").write_text(json.dumps({
            "command": [str(part) for part in command], "cwd": str(cwd),
            "started_at": started, "ended_at": datetime.now(timezone.utc).isoformat(),
            "exit_code": result.returncode, "expected_exit": expected_exit,
            "environment": {key: environment.get(key) for key in (
                "PATH", "PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE",
                "PIPELINE_DAG_FILE", "PIPELINE_ROOT", "PIP_DISABLE_PIP_VERSION_CHECK",
            )},
        }, indent=2))
        assert result.returncode == expected_exit, (
            f"{name}: exit {result.returncode}; logs in {records}\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )
        return result

    dist = tmp_path / "dist"
    dist.mkdir()
    build_input = source
    if distribution == "sdist":
        run("sdist", [
            sys.executable, "-c",
            "import sys; from setuptools.build_meta import build_sdist; build_sdist(sys.argv[1])",
            dist,
        ], source)
        build_input, = dist.glob("*.tar.gz")
    run("wheel-build", [
        sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
        "--no-index", "--wheel-dir", dist, build_input,
    ], tmp_path)
    wheel, = dist.glob("*.whl")
    prefix = "ai_sdlc_claudecode/bash/"
    with ZipFile(wheel) as archive:
        packaged = {name.removeprefix(prefix) for name in archive.namelist() if name.startswith(prefix)}
        assert packaged == set(expected), f"missing runtime resources: {sorted(set(expected) - packaged)}"
        for name, content in expected.items():
            assert archive.read(prefix + name) == content, f"changed runtime resource: {name}"
    (tmp_path / "artifacts.json").write_text(json.dumps({
        "distribution": distribution,
        "artifacts": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in dist.iterdir()},
        "resources": {name: hashlib.sha256(content).hexdigest() for name, content in expected.items()},
    }, indent=2))

    install = tmp_path / "installed"
    run("venv", [sys.executable, "-m", "venv", install], tmp_path)
    python = install / "bin/python"
    run("install", [python, "-m", "pip", "install", "--no-index", "--no-deps", wheel], tmp_path)
    environment["PATH"] = str(install / "bin") + os.pathsep + environment["PATH"]
    outside = tmp_path / "outside"
    outside.mkdir()
    result = run("resolvers", [python, "-c", """
import json
from pathlib import Path
from ai_sdlc_claudecode import config
print(json.dumps({
    "config": str(Path(config.__file__).resolve()),
    "executor": str(config.resolve_executor().resolve()),
    "dag": str(config.resolve_dag().resolve()),
}))
"""], outside)
    resolved = json.loads(result.stdout)
    package = Path(resolved["config"]).parent
    assert package.is_relative_to(install)
    assert Path(resolved["executor"]) == package / "bash/pipeline-executor.sh"
    assert Path(resolved["dag"]) == package / "bash/pipeline-dag.json"
    for name, content in expected.items():
        assert (package / "bash" / name).read_bytes() == content
    console = run("console-help", [install / "bin/ai-sdlc", "--help"], outside)
    assert "usage: ai-sdlc" in console.stdout
    executor = run("executor-help", ["bash", resolved["executor"], "--help"], outside, expected_exit=1)
    assert "Usage:" in executor.stdout
    assert executor.stderr == ""
