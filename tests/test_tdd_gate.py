"""Exercise the coverage gate CLI with project-specific commands and paths."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_coverage_gate_uses_selected_dag_and_backend_directory(tmp_path):
    backend = tmp_path / 'backend'
    backend.mkdir()
    command = (
        "test -f pom.xml && mkdir -p target/site/jacoco && "
        "printf 'INSTRUCTION_MISSED,INSTRUCTION_COVERED\\n10,90\\n' > target/site/jacoco/jacoco.csv"
    )
    (backend / 'pom.xml').write_text('<project/>')
    dag = tmp_path / 'dag.json'
    dag.write_text(json.dumps({'config': {'tech_stack_commands': {'java-maven': {
        'coverage': command, 'coverage_workdir': 'backend',
    }}}}))
    root_report = tmp_path / 'target/site/jacoco/jacoco.csv'
    root_report.parent.mkdir(parents=True)
    root_report.write_text('INSTRUCTION_MISSED,INSTRUCTION_COVERED\n90,10\n')

    result = subprocess.run(
        ['bash', str(ROOT / 'lib/tdd-gate.sh'), 'fixture', 'java-maven', '80'],
        cwd=tmp_path.parent, env={**os.environ, 'PIPELINE_DAG_FILE': str(dag),
                           'PROJECT_CODE_DIR': str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Coverage: 90.0%' in result.stdout
    assert 'Result: PASS' in result.stdout
    assert (backend / 'target/site/jacoco/jacoco.csv').exists()
    assert root_report.read_text().endswith('90,10\n')


def test_coverage_gate_default_dag_uses_invoking_project_root(tmp_path):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    maven = bindir / 'mvn'
    maven.write_text("#!/bin/sh\n[ \"$*\" = jacoco:report ] || exit 17\n"
                     "mkdir -p target/site/jacoco\n"
                     "printf 'INSTRUCTION_MISSED,INSTRUCTION_COVERED\\n20,80\\n' > target/site/jacoco/jacoco.csv\n")
    maven.chmod(0o755)
    env = {**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH']}
    for key in ('PIPELINE_DAG_FILE', 'PROJECT_CODE_DIR'):
        env.pop(key, None)
    result = subprocess.run(
        ['bash', str(ROOT / 'lib/tdd-gate.sh'), 'fixture', 'java-maven'],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Coverage: 80.0%' in result.stdout
    assert 'Result: PASS' in result.stdout
    assert (tmp_path / 'target/site/jacoco/jacoco.csv').exists()


@pytest.mark.parametrize('command, expected_exit, expected_coverage', [
    ("mkdir -p target/site/jacoco && printf 'INSTRUCTION_MISSED,INSTRUCTION_COVERED\\n21,79\\n' > target/site/jacoco/jacoco.csv", 1, '79.0%'),
    ('exit 7', 7, None),
])
def test_coverage_gate_rejects_low_coverage_and_failed_command(tmp_path, command, expected_exit, expected_coverage):
    report = tmp_path / 'target/site/jacoco/jacoco.csv'
    report.parent.mkdir(parents=True)
    report.write_text('INSTRUCTION_MISSED,INSTRUCTION_COVERED\n0,100\n')
    dag = tmp_path / 'dag.json'
    dag.write_text(json.dumps({'config': {'tech_stack_commands': {'java-maven': {'coverage': command}}}}))
    result = subprocess.run(
        ['bash', str(ROOT / 'lib/tdd-gate.sh'), 'fixture', 'java-maven', '80'],
        cwd=tmp_path.parent, env={**os.environ, 'PIPELINE_DAG_FILE': str(dag), 'PROJECT_CODE_DIR': str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == expected_exit, result.stdout + result.stderr
    assert 'Result: PASS' not in result.stdout
    assert json.loads(result.stdout.splitlines()[-1])['result'] == 'fail'
    if expected_coverage:
        assert 'Coverage: ' + expected_coverage in result.stdout
    else:
        assert 'Coverage command exited with code 7' in result.stdout
        assert report.read_text().endswith('0,100\n')
