"""Execution provenance, fail-closed verification and replay invariants.

These fixtures exercise local files only; no real model or external action.
"""

import json
from pathlib import Path

import pytest

from ai_sdlc_claudecode.state import PipelineState


@pytest.fixture
def contract(tmp_path):
    dag = tmp_path / "dag.json"
    dag.write_text(json.dumps({
        "stages": {"example": {
            "id": "S1", "gate": {"type": "ai-review"},
            "post_commands": [], "dependencies": [],
        }},
        "execution_order": [{"stage": "example", "mode": "sequential"}],
    }))
    state = PipelineState(tmp_path / "feature" / "state.json")
    run = state.start_run("feature", dag, ["S1"])
    output_dir = tmp_path / "feature" / "S1-example"
    output_dir.mkdir(exist_ok=True)
    return state, run, dag, output_dir


def verified_attempt(contract):
    state, run, dag, output_dir = contract
    attempt = state.begin_attempt(run, "S1", output_dir)
    output = output_dir / "output.json"
    output.write_text(json.dumps({"stage_id": "S1", "summary": "local fixture"}))
    for check in ("schema", "gate"):
        state.add_evidence(run, "S1", attempt, check, 0, output)
    record = state.finish_attempt(run, "S1", attempt, "passed", output)
    return record


def test_pass_has_execution_evidence_and_policy_scope(contract):
    state, run, dag, output_dir = contract
    record = verified_attempt(contract)
    assert record["run_id"] == run
    assert record["attempt_id"]
    assert record["result"]["sha256"]
    assert record["verification"]["status"] == "verified"
    assert record["verification"]["scope"] == "configured_stage_checks"
    assert record["authorization"]["scope"] == "accept_stage_artifact"
    assert record["business_acceptance"] == "not_evaluated"
    assert state.is_verified(record, dag)
    assert state.project_acceptance()['status'] == 'not_evaluated'


def test_no_receipts_cannot_become_passed(contract):
    state, run, dag, output_dir = contract
    attempt = state.begin_attempt(run, "S1", output_dir)
    output = output_dir / "output.json"
    output.write_text('{"stage_id":"S1", "verified":true}')
    with pytest.raises(ValueError, match="evidence|verification"):
        state.finish_attempt(run, "S1", attempt, "passed", output)


def test_failed_checker_cannot_become_passed(contract):
    state, run, dag, output_dir = contract
    attempt = state.begin_attempt(run, "S1", output_dir)
    output = output_dir / "output.json"
    output.write_text('{"stage_id":"S1"}')
    state.add_evidence(run, "S1", attempt, "schema", 0, output)
    state.add_evidence(run, "S1", attempt, "gate", 1, output)
    with pytest.raises(ValueError, match="evidence|verification"):
        state.finish_attempt(run, "S1", attempt, "passed", output)


def test_legacy_pass_is_not_verified(contract):
    state, run, dag, output_dir = contract
    assert not state.is_verified({"status": "passed"}, dag)


def test_artifact_change_invalidates_verification(contract):
    state, run, dag, output_dir = contract
    record = verified_attempt(contract)
    Path(record["result"]["path"]).write_text('{"stage_id":"S1", "changed":true}')
    assert not state.is_verified(record, dag)


def test_policy_change_invalidates_verification(contract):
    state, run, dag, output_dir = contract
    record = verified_attempt(contract)
    dag.write_text(dag.read_text() + "\n")
    assert not state.is_verified(record, dag)


def test_receipt_for_previous_attempt_is_rejected(contract):
    state, run, dag, output_dir = contract
    old_attempt = state.begin_attempt(run, "S1", output_dir)
    state.begin_attempt(run, "S1", output_dir)
    output = output_dir / "output.json"
    output.write_text('{"stage_id":"S1"}')
    with pytest.raises(ValueError, match="attempt"):
        state.add_evidence(run, "S1", old_attempt, "schema", 0, output)

import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('source,expected', [
    ('export const answer = () => {\n return 42;\n};', 0),
    ('export const answer = () => {};', 1),
    ('export function answer() { /* unfinished */ }', 1),
    ('export const answer = () => {;};', 1),
    ('listen(() => { /* completeness-allow-empty: optional notification hook */ });', 0),
    ('export const answer = () => { /* completeness-allow-empty: not a callback */ };', 1),
    ('export const text = "() => {}";', 0),
    ('class Value { constructor(public value: number) {} }', 0),
    ('export const answer = ( => {};', 2),
])
def test_completeness_checks_function_body(tmp_path, source, expected):
    (tmp_path / 'sample.ts').write_text(source)
    (tmp_path / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    result = subprocess.run(['bash', str(ROOT / 'scripts/completeness-check.sh'), str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == expected, result.stdout + result.stderr


def test_completeness_parser_absence_and_vue(tmp_path):
    target = tmp_path / 'source'
    target.mkdir()
    (target / 'sample.vue').write_text('<script setup lang="ts">const answer = () => {};</script>')
    command = ['bash', str(ROOT / 'scripts/completeness-check.sh'), str(target)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'Required parser typescript unavailable' in result.stderr
    (target / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'B-Stub sample.vue:1' in result.stdout


@pytest.mark.parametrize('source,code', [('export const answer = () => 42;', 0),
                                       ('export const answer = () => {};', 1),
                                       ('export const answer = ( => {};', 1)])
def test_default_completeness_command_runs_in_supervisor(executor_case, tmp_path, source, code):
    dag, path, env, run = executor_case
    (tmp_path / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    (tmp_path / 'sample.ts').write_text(source)
    default = json.loads((ROOT / 'pipeline-dag.json').read_text())
    command = next(c for s in default['stages'].values() for c in s.get('post_commands', [])
                   if 'completeness-check.sh' in c)
    dag['stages']['first']['post_commands'] = [command]
    result, data = run('--stages', 'S8')
    assert result.returncode == code, result.stdout + result.stderr
    log = Path(data['stages']['S8']['output_dir'], 'post-commands.log').read_text()
    assert '[CHECK]' in log or '[ERROR]' in log
    assert 'No such file' not in log


@pytest.fixture
def executor_case(tmp_path):
    """Real supervisor/validator; only the model is a deterministic local executable."""
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    fake = bindir / 'claude'
    fake.write_text('''#!/usr/bin/env python3
import json, os, re, sys
prompt = sys.stdin.read() or sys.argv[-1]
mode = os.environ.get('FAKE_MODE', 'valid')
if prompt == 'Reply with exactly: OK':
    print('OK')
    sys.exit(0)
if 'FAKE_STAGE:' not in prompt:
    if mode == 'checker_error': sys.exit(2)
    score = 20 if mode == 'review_reject' else 90
    print(json.dumps({'scores': {'correctness': score}, 'overall_score': score,
                      'passed': score >= 70, 'summary': 'local fixture', 'issues': []}))
    sys.exit(0)
stage = re.search(r'FAKE_STAGE:(S[0-9A-Za-z]+)', prompt).group(1)
with open(os.environ['FAKE_CALLS'], 'a') as log: log.write(stage + '\\n')
if mode == 'empty':
    print('no structured result')
elif mode == 'agent_error':
    print('actual model invocation error')
    sys.exit(2)
elif mode == 'block':
    from pathlib import Path
    import time
    Path(os.environ['FAKE_READY']).write_text(str(os.getpid()))
    time.sleep(30)
else:
    print(json.dumps({'stage_id': stage, 'status': 'complete', 'summary': 'fixture'} if mode != 'bad_schema' else {'stage_id': stage}))
''')
    fake.chmod(0o755)
    schema = tmp_path / 'schema.json'
    schema.write_text(json.dumps({'type': 'object', 'required': ['stage_id', 'status', 'summary'],
                                  'properties': {'status': {'const': 'complete'}}}))
    dag = {'config': {'max_retries_per_stage': 0, 'cost_limit_usd': 50,
                       'context_budget_tokens': 10000, 'tech_stack': 'node-typescript'},
           'stages': {}, 'execution_order': []}
    for name, sid in [('first', 'S8'), ('second', 'S9')]:
        dag['stages'][name] = {'id': sid, 'gate': {'type': 'auto', 'commands': ['true']},
            'output_schema': str(schema), 'dependencies': [], 'post_commands': ['true'],
            'agents': [{'type': 'fixture', 'model': 'haiku', 'prompt_template': f'FAKE_STAGE:{sid}'}]}
        dag['execution_order'].append({'stage': name, 'mode': 'sequential'})
    dag_path = tmp_path / 'dag.json'
    env = {**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
           'PIPELINE_ROOT': str(tmp_path / 'pipeline'), 'PIPELINE_DAG_FILE': str(dag_path),
           'AI_SDLC_CLAUDE_JSON': '0', 'FAKE_CALLS': str(tmp_path / 'calls'),
           'PYTHONPATH': str(ROOT / 'src')}

    def run(*flags, mode='valid'):
        dag_path.write_text(json.dumps(dag))
        result = subprocess.run(['bash', str(ROOT / 'pipeline-executor.sh'), 'fixture', 'local only',
                                 '--project-dir', str(tmp_path), *flags], env={**env, 'FAKE_MODE': mode},
                                capture_output=True, text=True, timeout=max(25, 5 * len(dag['stages'])))
        state_file = tmp_path / 'pipeline' / 'fixture' / 'state.json'
        data = json.loads(state_file.read_text()) if state_file.exists() else {}
        (tmp_path / 'last-output.log').write_text(result.stdout + result.stderr)
        return result, data
    return dag, dag_path, env, run


@pytest.mark.parametrize('signal_name,expected_code', [('SIGTERM', 143), ('SIGINT', 130)])
def test_bash_interruption_persists_exit_and_stops_running_stage(executor_case, tmp_path, signal_name, expected_code):
    """Real Bash entry and dispatcher; the model executable is local and blocking."""
    import signal
    import time

    dag, path, env, run = executor_case
    path.write_text(json.dumps(dag))
    ready = tmp_path / 'blocked-model.pid'
    process = subprocess.Popen(
        ['bash', str(ROOT / 'pipeline-executor.sh'), 'fixture', 'local interrupt',
         '--stages', 'S8', '--project-dir', str(tmp_path)],
        env={**env, 'FAKE_MODE': 'block', 'FAKE_READY': str(ready)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), 'local model fixture did not reach the running stage'
        os.killpg(process.pid, getattr(signal, signal_name))
        stdout, stderr = process.communicate(timeout=10)
        state = PipelineState(tmp_path / 'pipeline/fixture/state.json')
        data = state.read()
        assert data['pipeline_state'] == 'failed', stdout + stderr
        assert data['stages']['S8']['status'] == 'failed'
        assert data['owner_pid'] is None
        assert process.returncode == expected_code
        assert data['executor_exit']['exit_code'] == expected_code
        assert data['executor_exit']['run_id'] == data['run_id']
        assert state.summary()['execution_outcome'] == 'failed'
        assert state.summary()['project_acceptance']['status'] == 'not_evaluated'
        with pytest.raises(ProcessLookupError):
            os.kill(int(ready.read_text()), 0)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        if ready.exists():
            try:
                os.kill(int(ready.read_text()), 0)
            except ProcessLookupError:
                pass
            else:
                os.kill(int(ready.read_text()), signal.SIGKILL)

    resumed, after = run('--resume')
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert after['run_id'] != data['run_id']
    assert after['scope'] == ['S8']
    assert after['stages']['S8']['attempt_id'] != data['stages']['S8']['attempt_id']
    assert after['stages']['S8']['status'] == 'passed'
    assert after['executor_exit']['exit_code'] == 0
    assert any(record['attempt_id'] == data['stages']['S8']['attempt_id']
               and record['status'] == 'failed' for record in after['history'])


@pytest.mark.parametrize("template_has_description", [False, True])
def test_code_stage_can_write_source_and_returns_metadata(executor_case, template_has_description):
    dag, path, env, run = executor_case
    if template_has_description:
        dag["stages"]["first"]["agents"][0]["prompt_template"] += "\n{{feature_description}}"
    dag['stages']['first']['writes_code'] = True
    dag['config']['project_completion'] = {
        'goal': 'A repeatable purchase has one durable result',
        'authority': ['docs/approved-spec.md'], 'excluded_until_approved': ['production rollout'],
    }
    fake_cli = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake_cli.write_text(fake_cli.read_text().replace(
        "mode = os.environ.get('FAKE_MODE', 'valid')",
        "Path(os.environ['FAKE_CALLS'] + '.prompt').write_text(prompt)\nmode = os.environ.get('FAKE_MODE', 'valid')"
    ).replace('import json, os, re, sys', 'import json, os, re, sys\nfrom pathlib import Path'))
    result, data = run('--stages', 'S8')
    assert result.returncode == 0, result.stdout + result.stderr
    prompt = Path(env['FAKE_CALLS'] + '.prompt').read_text()
    assert 'Write implementation and test source files' in prompt
    assert 'Do NOT attempt to write files.' not in prompt
    assert 'metadata JSON' in prompt
    assert prompt.count('local only') == 1
    assert 'Delivery responsibilities' in prompt
    assert 'docs/approved-spec.md' in prompt
    assert 'production rollout' in prompt
    assert 'The supervisor decides acceptance' in prompt


def test_imported_architecture_materializes_configured_contracts(executor_case, tmp_path):
    dag, path, env, run = executor_case
    dag['stages']['architecture'] = {**dag['stages']['first'], 'id': 'S2'}
    dag['stages']['first']['dependencies'] = ['architecture']
    dag['config']['imported_contracts'] = {
        'services': [{'name': 'backend', 'responsibility': 'Linji modular monolith application',
                      'language': 'java', 'port': 8080}],
        'api_endpoints': [], 'cross_service_messages': [], 'encryption_pairs': [],
        'shared_models': [], 'external_refs': {'ai_models': [], 'npm_packages_forbidden': []},
    }
    plan = tmp_path / 'approved-design.md'
    plan.write_text('Existing approved architecture; do not redesign.')
    result, data = run('--stages', 'S8', '--plan-file', str(plan))
    assert result.returncode == 0, result.stdout + result.stderr
    imported = Path(env['PIPELINE_ROOT']) / 'fixture' / 'S2-architecture'
    artifact = json.loads((imported / 'contracts.json').read_text())
    output = json.loads((imported / 'output.json').read_text())
    assert artifact['contracts'] == dag['config']['imported_contracts']
    assert artifact['stage_id'] == 'S2'
    assert artifact['feature_id'] == 'fixture'
    assert 'contracts.json' in output['artifacts']
    assert output['contracts_sha256']
    assert data['stages']['S2']['status'] == 'imported'


@pytest.fixture
def generated_architecture(executor_case, tmp_path):
    dag, path, env, run = executor_case
    dag['stages'] = {'architecture': {
        **dag['stages']['first'], 'id': 'S2',
        'output_schema': str(ROOT / 'schemas/architecture-output.json'),
        'agents': [{'type': 'fixture', 'model': 'haiku', 'prompt_template': 'FAKE_STAGE:S2'}],
    }, 'second': {**dag['stages']['second'], 'dependencies': ['architecture']}}
    dag['execution_order'] = [{'stage': name, 'mode': 'sequential'} for name in dag['stages']]
    document = {
        'stage_id': 'S2', 'feature_id': 'fixture', 'timestamp': '2026-11-11T00:00:00Z',
        'status': 'complete', 'summary': 'Generated architecture',
        'architecture': {'affected_modules': [{'module_name': 'backend', 'change_type': 'new',
                                              'description': 'Application backend'}],
                         'api_contracts': [], 'data_model': {'tables': []},
                         'sequence_flows': [{'name': 'health', 'steps': []}]},
        'contracts': {'services': [{'name': 'backend', 'responsibility': 'Application backend',
                                    'language': 'java', 'port': 8080}],
                      'api_endpoints': [], 'cross_service_messages': [], 'encryption_pairs': [],
                      'shared_models': [], 'external_refs': {'ai_models': [], 'npm_packages_forbidden': []}},
    }
    source = tmp_path / 'architecture.json'
    source.write_text(json.dumps(document))
    env['FAKE_ARCHITECTURE'] = str(source)
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake.write_text(fake.read_text().replace(
        "if 'FAKE_STAGE:' not in prompt:",
        "if '## Primary Agent Output (to review and revise)' in prompt:\n"
        "    print(open(os.environ['FAKE_REFINED_ARCHITECTURE']).read())\n    sys.exit(0)\n"
        "if 'FAKE_STAGE:' not in prompt:"
    ).replace(
        "if mode == 'empty':",
        "if stage == 'S2':\n"
        "    open(os.environ['FAKE_ARCHITECTURE'] + '.prompt', 'w').write(prompt)\n"
        "    print(open(os.environ['FAKE_ARCHITECTURE']).read())\n    sys.exit(0)\nif mode == 'empty':"))
    return dag, path, env, run, document, source


@pytest.mark.parametrize('refined', [False, True])
def test_generated_architecture_hands_off_validated_bound_contracts(generated_architecture, refined):
    """The normal S2 path must produce the contract consumed by later stages."""
    import hashlib

    dag, path, env, run, document, source = generated_architecture
    if refined:
        dag['stages']['architecture']['review_passes'] = [{'role': 'contracts', 'model': 'haiku'}]
        document['contracts']['services'][0]['port'] = 8090
        revision = source.with_name('refined-architecture.json')
        revision.write_text(json.dumps(document))
        env['FAKE_REFINED_ARCHITECTURE'] = str(revision)

    result, data = run('--stages', 'S2,S9')
    assert result.returncode == 0, result.stdout + result.stderr
    output_dir = Path(env['PIPELINE_ROOT']) / 'fixture' / 'S2-architecture'
    contracts_path = output_dir / 'contracts.json'
    assert contracts_path.exists(), 'Generated S2 passed without its downstream contract artifact'
    contracts = json.loads(contracts_path.read_text())
    assert contracts['contracts'] == document['contracts']
    output = json.loads((output_dir / 'output.json').read_text())
    assert output['contracts_sha256'] == hashlib.sha256(contracts_path.read_bytes()).hexdigest()
    assert 'contracts.json' in output['artifacts']
    assert PipelineState.is_verified(data['stages']['S2'], path)
    receipts = data['stages']['S2']['verification']['evidence']
    assert {r['check'] for r in receipts} >= {'contracts', 'schema', 'post_commands', 'gate'}
    assert all(r['artifact_sha256'] == hashlib.sha256((output_dir / 'output.json').read_bytes()).hexdigest()
               for r in receipts)
    if refined:
        assert 'refinement' in {r['check'] for r in receipts}
    prompt = Path(str(source) + '.prompt').read_text()
    assert 'S2 Cross-Service Contracts Output' in prompt
    assert data['stages']['S9']['status'] == 'passed'
    contracts_path.write_text('{}')
    assert not PipelineState.is_verified(data['stages']['S2'], path)


@pytest.mark.parametrize('case', ['missing', 'invalid', 'stale', 'refined_missing'])
def test_generated_architecture_rejects_unusable_contracts(generated_architecture, case):
    dag, path, env, run, document, source = generated_architecture
    # Imported contracts are only an input to the explicitly imported-plan path.
    dag['config']['imported_contracts'] = document['contracts']
    output_dir = Path(env['PIPELINE_ROOT']) / 'fixture' / 'S2-architecture'
    if case == 'stale':
        output_dir.mkdir(parents=True)
        (output_dir / 'contracts.json').write_text(json.dumps(document))
    if case == 'invalid':
        document['contracts'] = {'services': []}
    else:
        del document['contracts']
    if case == 'refined_missing':
        dag['stages']['architecture']['review_passes'] = [{'role': 'contracts', 'model': 'haiku'}]
        source = source.with_name('refined-architecture.json')
        env['FAKE_REFINED_ARCHITECTURE'] = str(source)
    source.write_text(json.dumps(document))

    result, data = run('--stages', 'S2,S9')
    assert result.returncode != 0, result.stdout + result.stderr
    record = data['stages']['S2']
    assert record['status'] == 'dead_letter'
    assert not PipelineState.is_verified(record, path)
    assert any(r['check'] == 'contracts' and r['exit_code'] != 0
               for r in record['verification']['evidence'])
    assert Path(env['FAKE_CALLS']).read_text().splitlines() == ['S2']
    assert 'S9' not in data['stages']
    assert not (output_dir / 'contracts.json').exists()


def test_generated_architecture_contracts_are_enforced_downstream(generated_architecture, tmp_path):
    dag, path, env, run, document, source = generated_architecture
    document['contracts']['external_refs']['npm_packages_forbidden'] = ['forbidden-fixture-package']
    source.write_text(json.dumps(document))
    dag['stages']['second'].update(id='S3', agents=[{
        'type': 'fixture', 'model': 'haiku', 'prompt_template': 'FAKE_STAGE:S3',
    }])
    backend = tmp_path / 'backend'
    backend.mkdir()
    (backend / 'package.json').write_text(json.dumps({'dependencies': {'forbidden-fixture-package': '1.0'}}))
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake.write_text(fake.read_text().replace(
        "'status': 'complete', 'summary': 'fixture'",
        "'status': 'complete', 'summary': 'fixture', 'implementation': {'compile_result': {'success': True}}"))

    result, data = run('--stages', 'S2,S3')
    assert result.returncode != 0, result.stdout + result.stderr
    assert PipelineState.is_verified(data['stages']['S2'], path)
    assert data['stages']['S3']['status'] == 'dead_letter'
    violations = json.loads((Path(env['PIPELINE_ROOT']) / 'fixture/S3-second/contract_violations.json').read_text())
    assert any(v['check'] == 'forbidden_npm_package' for v in violations['violations'])


def test_executor_coverage_check_uses_project_dag_and_workdir(executor_case, tmp_path):
    dag, path, env, run = executor_case
    dag['stages']['first'].update(id='S4b', agents=[{
        'type': 'fixture', 'model': 'haiku', 'prompt_template': 'FAKE_STAGE:S4b',
    }])
    dag['config'].update(tech_stack='java-maven', tech_stack_commands={'java-maven': {
        'coverage_workdir': 'backend',
        'coverage': "test -f pom.xml && mkdir -p target/site/jacoco && "
                    "printf 'INSTRUCTION_MISSED,INSTRUCTION_COVERED\\n10,90\\n' > target/site/jacoco/jacoco.csv",
    }})
    backend = tmp_path / 'backend'
    backend.mkdir()
    (backend / 'pom.xml').write_text('<project/>')
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake.write_text(fake.read_text().replace(
        "'status': 'complete', 'summary': 'fixture'",
        "'status': 'complete', 'summary': 'fixture', 'testing': {'test_results': {'failed': 0}}"))

    result, data = run('--stages', 'S4b')
    assert result.returncode == 0, result.stdout + result.stderr
    assert PipelineState.is_verified(data['stages']['S4b'], path)
    log = (Path(env['PIPELINE_ROOT']) / 'fixture/S4b-first/tdd.log').read_text()
    assert f'Working directory: {backend}' in log
    assert 'Coverage: 90.0%' in log
    assert not (tmp_path / 'target').exists()


@pytest.mark.parametrize('group_mode', ['sequential', 'parallel'])
def test_dry_run_renders_stage_groups_without_execution(executor_case, group_mode):
    dag, path, env, run = executor_case
    dag['execution_order'] = [{'stages': ['first', 'second'], 'mode': group_mode}]
    fake_cli = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake_cli.write_text('''#!/usr/bin/env python3
import os
from pathlib import Path
Path(os.environ['FAKE_CALLS']).write_text('unexpected model call')
raise SystemExit(99)
''')
    result, data = run('--dry-run')

    assert result.returncode == 0, result.stdout + result.stderr
    plan = result.stdout.split('=== Dry Run: Execution Plan ===', 1)[1]
    if group_mode == 'sequential':
        assert '1. S8 first ' in plan
        assert '2. S9 second ' in plan
    else:
        assert '1. PARALLEL [S8 first + S9 second]' in plan
    assert data == {}
    assert not Path(env['FAKE_CALLS']).exists()
    assert not Path(env['PIPELINE_ROOT']).exists()


def test_actual_executor_records_success_and_scope(executor_case):
    dag, path, env, run = executor_case
    result, data = run('--stages', 'S8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data['pipeline_state'] == 'complete'
    assert data['scope'] == ['S8']
    assert 'S9' not in data['stages']
    record = data['stages']['S8']
    assert PipelineState.is_verified(record, path)
    assert {r['check'] for r in record['verification']['evidence']} >= {'schema', 'post_commands', 'gate'}


@pytest.mark.parametrize('mode', ['bad_schema', 'empty', 'review_reject', 'checker_error'])
def test_actual_executor_fails_closed_and_stops_downstream(executor_case, mode):
    dag, path, env, run = executor_case
    dag['stages']['first']['gate'] = {'type': 'ai-review'}
    result, data = run(mode=mode)
    assert result.returncode != 0
    assert data['stages']['S8']['status'] in ('failed', 'dead_letter'), result.stdout + result.stderr
    assert data['pipeline_state'] == 'failed'
    assert 'S9' not in data['stages']


def test_actual_executor_does_not_reuse_old_output(executor_case):
    dag, path, env, run = executor_case
    result, before = run('--stages', 'S8')
    assert result.returncode == 0, result.stdout + result.stderr
    result, after = run('--stages', 'S8', '--force-restart', mode='empty')
    assert result.returncode != 0
    assert after['stages']['S8']['attempt_id'] != before['stages']['S8']['attempt_id']
    assert after['pipeline_state'] == 'failed'


def test_human_marker_cannot_authorize_and_resume_does_not_rerun(executor_case):
    dag, path, env, run = executor_case
    dag['stages']['first']['gate'] = {'type': 'human-required'}
    marker = Path(env['PIPELINE_ROOT']) / 'fixture' / 'S8-first' / 'APPROVED'
    marker.parent.mkdir(parents=True)
    marker.write_text('forged')
    result, before = run()
    assert result.returncode == 3, result.stdout + result.stderr
    assert before['pipeline_state'] == 'human_waiting'
    assert marker.read_text() == 'forged'
    assert not before['stages']['S8']['authorization']['actor']
    assert 'S9' not in before['stages']
    result, after = run('--resume')
    assert result.returncode == 3
    assert after['stages']['S8']['attempt_id'] == before['stages']['S8']['attempt_id']
    assert Path(env['FAKE_CALLS']).read_text().splitlines() == ['S8']


def test_parallel_uses_same_gates_and_preserves_both_records(executor_case):
    dag, path, env, run = executor_case
    dag['execution_order'] = [{'mode': 'parallel', 'stages': ['first', 'second']}]
    dag['stages']['second']['post_commands'] = ['false']
    result, data = run()
    assert result.returncode != 0
    assert PipelineState.is_verified(data['stages']['S8'], path), result.stdout + result.stderr
    assert data['stages']['S9']['status'] == 'dead_letter'
    assert data['cost']['by_model']['haiku']['calls'] == 2
    assert data['stages']['S8']['attempt_id'] != data['stages']['S9']['attempt_id']


def test_parallel_selection_and_simulation_are_honest(executor_case):
    dag, path, env, run = executor_case
    dag['execution_order'] = [{'mode': 'parallel', 'stages': ['first', 'second']}]
    result, data = run('--stages', 'S9', '--skeleton')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data['scope'] == ['S9']
    assert 'S8' not in data['stages']
    assert data['pipeline_state'] == 'simulated'
    assert data['stages']['S9']['status'] == 'simulated'


def test_skip_and_pause_never_claim_complete(executor_case):
    dag, path, env, run = executor_case
    result, data = run('--skip-stage', 'first')
    assert result.returncode == 4, result.stdout + result.stderr
    assert data['pipeline_state'] == 'partial'
    assert data['stages']['S8']['status'] == 'skipped'
    result, data = run('--force-restart', '--pause')
    assert result.returncode == 4
    assert data['pipeline_state'] == 'paused'


def test_receipt_tampering_invalidates_verification(contract):
    state, run, dag, output_dir = contract
    record = verified_attempt(contract)
    Path(record['verification']['evidence'][0]['path']).write_text('changed')
    assert not state.is_verified(record, dag)


def test_learning_is_once_per_attempt_across_engine_restart(contract, tmp_path):
    from ai_sdlc_claudecode.engine import ErrorEngine
    state, run, dag, output_dir = contract
    engine = ErrorEngine(tmp_path / 'errors')
    error = engine.capture('feature', 'S1', 'example', 'schema validation error', 1, 0, 1)
    fix_id = error.variants[0]['id']
    record = verified_attempt(contract)
    record['applied_fix_ids'] = [fix_id]
    engine.record_outcome(record)
    ErrorEngine(engine.errors_dir).record_outcome(record)
    reloaded = ErrorEngine(engine.errors_dir).index['S1'][0]
    assert reloaded.success_after_apply == 1
    assert reloaded.variants[0]['success'] == 1
    assert reloaded.applied_count == 1
    record['status'] = 'skipped'
    ErrorEngine(engine.errors_dir).record_outcome(record)
    assert ErrorEngine(engine.errors_dir).index['S1'][0].success_after_apply == 1


def test_actual_ai_review_success_and_score_boolean_conflict(executor_case):
    dag, path, env, run = executor_case
    dag['stages']['first']['gate'] = {'type': 'ai-review'}
    result, data = run('--stages', 'S8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert PipelineState.is_verified(data['stages']['S8'], path)
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake.write_text(fake.read_text().replace("'passed': score >= 70", "'passed': True"))
    result, data = run('--stages', 'S8', '--force-restart', mode='review_reject')
    assert result.returncode != 0
    assert data['stages']['S8']['status'] == 'dead_letter'


def test_pending_prerequisite_cannot_be_bypassed_with_start_from(executor_case):
    dag, path, env, run = executor_case
    dag['stages']['second']['dependencies'] = ['first']
    result, data = run('--start-from', 'S9')
    assert result.returncode == 4, result.stdout + result.stderr
    assert data['stages']['S9']['status'] == 'unverified'
    assert not Path(env['FAKE_CALLS']).exists()


def test_live_feature_owner_rejects_concurrent_start(contract):
    state, run, dag, output_dir = contract
    state.start_run('feature', dag, ['S1'], owner_pid=os.getpid())
    with pytest.raises(ValueError, match='live execution owner'):
        state.start_run('feature', dag, ['S1'], owner_pid=os.getpid())


def test_explicit_goal_scope_survives_start_from_subset(executor_case):
    dag, path, env, run = executor_case
    result, original = run('--stages', 'S8,S9')
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = original['stages']['S8']
    previous_attempt = original['stages']['S9']['attempt_id']
    result, data = run('--stages', 'S8,S9', '--start-from', 'S9')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data['scope'] == ['S8', 'S9'], 'The authoritative goal must not shrink to the rerun subset'
    assert data['execution_scope'] == ['S9']
    assert data['stages']['S8'] == prefix, 'Verified prefix evidence must remain unchanged'
    assert data['stages']['S9']['attempt_id'] != previous_attempt
    assert Path(env['FAKE_CALLS']).read_text().splitlines() == ['S8', 'S9', 'S9']
    result, data = run('--resume')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data['execution_scope'] == ['S8', 'S9']
    assert Path(env['FAKE_CALLS']).read_text().splitlines() == ['S8', 'S9', 'S9']


def test_missing_prefix_keeps_full_goal_partial_after_subset_passes(executor_case):
    dag, path, env, run = executor_case
    result, data = run('--stages', 'S8,S9', '--start-from', 'S9')
    assert result.returncode == 4, result.stdout + result.stderr
    assert data['scope'] == ['S8', 'S9']
    assert data['execution_scope'] == ['S9']
    assert data['pipeline_state'] == 'partial'
    assert PipelineState.is_verified(data['stages']['S9'], path)
    assert not PipelineState.is_verified(data['stages'].get('S8', {}), path)
    assert Path(env['FAKE_CALLS']).read_text().splitlines() == ['S9']


def test_execution_scope_cannot_escape_goal_scope(contract):
    state, run, dag, output_dir = contract
    before = state.path.read_bytes()
    with pytest.raises(ValueError, match='execution scope'):
        state.start_run('feature', dag, ['S1'], execution_scope=['OTHER'])
    assert state.path.read_bytes() == before


def test_resume_from_suffix_preserves_unfinished_goal(executor_case):
    dag, path, env, run = executor_case
    result, data = run('--stages', 'S8,S9', '--start-from', 'S9')
    assert result.returncode == 4, result.stdout + result.stderr
    result, data = run('--resume', '--start-from', 'S9')
    assert result.returncode == 4, result.stdout + result.stderr
    assert data['scope'] == ['S8', 'S9']
    assert data['execution_scope'] == ['S9']
    assert data['pipeline_state'] == 'partial'
    assert 'S8' not in data['stages']
    assert Path(env['FAKE_CALLS']).read_text().splitlines() == ['S9']


@pytest.fixture
def project_acceptance_case(executor_case, tmp_path):
    dag, path, env, run = executor_case
    (tmp_path / 'app').mkdir()
    (tmp_path / 'app/application.py').write_text('VERSION = 1\n')
    driver = tmp_path / 'acceptance_driver.py'
    driver.write_text('''import json, os
from pathlib import Path
report = {
    'run_id': os.environ['PIPELINE_RUN_ID'],
    'attempt_id': os.environ['PIPELINE_ATTEMPT_ID'],
    'checks': {'business': {'create': 'passed', 'replay': 'passed'}},
    'findings': {},
}
Path(os.environ['PIPELINE_ACCEPTANCE_REPORT']).write_text(json.dumps(report))
''')
    dag['config']['project_acceptance'] = {
        'scope': 'fixture-business', 'stage_id': 'S9',
        'candidate_inputs': ['app', 'acceptance_driver.py'],
        'required_checks': {'business': ['create', 'replay']},
        'blocking_findings': {},
    }
    dag['stages']['second']['post_commands'] = ['python3 acceptance_driver.py']
    return dag, path, env, run, tmp_path, driver


@pytest.fixture
def function_map_case(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    dag['stages']['first']['id'] = 'S1'
    dag['stages']['first']['output_schema'] = str(ROOT / 'schemas/requirements-output.json')
    dag['stages']['first']['agents'][0]['prompt_template'] = 'FAKE_STAGE:S1'
    dag['stages']['second']['dependencies'] = ['first']
    dag['config']['project_acceptance']['function_map'] = {'source_stage_id': 'S1'}
    behaviors = []
    for case, ac, event, expected in [('create', 'AC-1', 'POST /items', '201 and one stored item'),
                                     ('replay', 'AC-2', 'Repeat POST /items', '200 and still one stored item')]:
        behaviors.append(dict(id=f'B-{case}', requirement_id='FR-1', acceptance_id=ac,
            role='API caller', preconditions='Empty isolated store; request key A',
            state_before='No item' if case == 'create' else 'One item', event=event,
            state_after='One item', data_changes='Exactly one item with key A',
            failure_retry='Retry with same request key', feedback='HTTP status and JSON list',
            target='app/application.py', check_id='business', case_id=case,
            command='python3 acceptance_driver.py', expected=expected, evidence='supervisor_report'))
    requirements = {'stage_id': 'S1', 'feature_id': 'fixture', 'timestamp': '2026-11-17T00:00:00Z',
                    'status': 'complete', 'summary': 'API item contract',
                    'prd': {'title': 'Idempotent API', 'summary': 'An API caller creates one item and can retry the same key without duplicating that item.',
                            'functional_requirements': [{'id': 'FR-1', 'priority': 'must', 'description': 'Create idempotently'}],
                            'non_functional_requirements': [{'id': 'NFR-1', 'category': 'reliability', 'description': 'Repeat safe', 'metric': 'one item'}],
                            'user_stories': [{'id': 'US-1', 'as_a': 'caller', 'i_want': 'retry', 'so_that': 'one item'}],
                            'acceptance_criteria': [{'id': 'AC-1', 'given': 'empty', 'when': 'create', 'then': 'one item'},
                                                    {'id': 'AC-2', 'given': 'one item', 'when': 'retry', 'then': 'same item'}]},
                    'function_map': {'version': '1', 'behaviors': behaviors}}
    source = project / 'requirements-input.json'
    source.write_text(json.dumps(requirements))
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake.write_text(fake.read_text().replace(
        "with open(os.environ['FAKE_CALLS'], 'a') as log:",
        f"if stage == 'S1':\n    print(open({str(source)!r}).read()); sys.exit(0)\nwith open(os.environ['FAKE_CALLS'], 'a') as log:"))
    (project / 'app/application.py').write_text('''import json
from http.server import BaseHTTPRequestHandler
items = []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        key = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['key']
        status = 200 if key in items else 201
        if key not in items: items.append(key)
        self.send_response(status); self.end_headers()
        self.wfile.write(json.dumps(items).encode())
''')
    driver.write_text('''import json, os, threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from app.application import Handler
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
checks = {}
try:
    for case, expected in [('create', 201), ('replay', 200)]:
        request = Request('http://127.0.0.1:%s/items' % server.server_port,
                          data=b'{"key":"A"}', headers={'Content-Type':'application/json'})
        with urlopen(request, timeout=3) as response:
            checks[case] = 'passed' if response.status == expected and json.load(response) == ['A'] else 'failed'
finally:
    server.shutdown(); server.server_close(); thread.join()
report = {'run_id': os.environ['PIPELINE_RUN_ID'], 'attempt_id': os.environ['PIPELINE_ATTEMPT_ID'],
          'checks': {'business': checks}, 'findings': {}}
Path(os.environ['PIPELINE_ACCEPTANCE_REPORT']).write_text(json.dumps(report))
''')
    return dag, path, env, run, project, driver, source


def test_function_map_traces_s1_to_executed_api(function_map_case):
    dag, path, env, run, project, driver, source = function_map_case
    result, data = run('--stages', 'S1,S9')
    assert result.returncode == 0, result.stdout + result.stderr
    report = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json').project_acceptance()
    assert report['status'] == 'passed'
    assert report['function_map_sha256'] == data['function_map_contract']['sha256']
    assert [(row['acceptance_id'], row['status']) for row in report['behaviors']] == [
        ('AC-1', 'passed'), ('AC-2', 'passed')]


@pytest.mark.parametrize('change', ['missing_behavior', 'missing_feedback', 'unknown_ac', 'wrong_command'])
def test_function_map_rejects_unbound_requirements(function_map_case, change):
    dag, path, env, run, project, driver, source = function_map_case
    value = json.loads(source.read_text())
    behaviors = value['function_map']['behaviors']
    if change == 'missing_behavior': behaviors.pop()
    elif change == 'missing_feedback': del behaviors[0]['feedback']
    elif change == 'unknown_ac': behaviors[0]['acceptance_id'] = 'AC-99'
    else: behaviors[0]['command'] = 'true'
    source.write_text(json.dumps(value))
    result, data = run('--stages', 'S1,S9')
    assert result.returncode == 1
    assert data['stages'].get('S9', {}).get('status') != 'passed'


@pytest.mark.parametrize('mode,expected', [('failed', 'failed'), ('missing', 'incomplete'), ('skipped', 'incomplete')])
def test_function_map_api_failure_missing_or_skipped_cannot_pass(function_map_case, mode, expected):
    dag, path, env, run, project, driver, source = function_map_case
    if mode == 'failed':
        app = project / 'app/application.py'
        app.write_text(app.read_text().replace('if key not in items: items.append(key)', 'items.append(key)'))
    else:
        expression = "del checks['replay']" if mode == 'missing' else "checks['replay'] = 'skipped'"
        driver.write_text(driver.read_text().replace('report = {', expression + '\nreport = {'))
    result, data = run('--stages', 'S1,S9')
    assert result.returncode == 1
    report = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json').project_acceptance()
    assert report['status'] == expected
    assert report['behaviors'][1]['status'] == mode


def test_function_map_drift_invalidates_evidence_and_cannot_erase_obligations(function_map_case):
    dag, path, env, run, project, driver, source = function_map_case
    result, data = run('--stages', 'S1,S9')
    assert result.returncode == 0, result.stdout + result.stderr
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    artifact = Path(data['stages']['S1']['result']['path'])
    altered = json.loads(artifact.read_text())
    altered['function_map']['behaviors'][0]['expected'] = 'anything'
    artifact.write_text(json.dumps(altered))
    assert state.project_acceptance()['status'] == 'incomplete'
    source.write_text(json.dumps(altered))
    result, after = run('--stages', 'S1,S9', '--resume')
    assert result.returncode == 1
    assert after['function_map_contract']['sha256'] == data['function_map_contract']['sha256']
    dag['config']['project_acceptance']['required_checks']['business'].remove('replay')
    result, _ = run('--stages', 'S1,S9', '--resume')
    assert result.returncode == 1
    assert 'Cannot change frozen' in result.stdout + result.stderr


def test_function_map_scope_rename_cannot_remove_blocker(function_map_case):
    dag, path, env, run, project, driver, source = function_map_case
    dag['config']['project_acceptance']['blocking_findings'] = {'R1': ['business']}
    first, before = run('--stages', 'S1,S9')
    assert first.returncode == 1
    assert 'R1' in before['stages']['S9']['project_acceptance']['known_findings']
    dag['config']['project_acceptance']['scope'] = 'renamed-scope'
    dag['config']['project_acceptance']['blocking_findings'] = {}
    second, after = run('--stages', 'S1,S9', '--resume')
    assert second.returncode == 1
    assert 'Cannot change frozen acceptance contract or scope' in second.stdout + second.stderr
    assert after['function_map_contract']['sha256'] == before['function_map_contract']['sha256']
    assert 'R1' in after['stages']['S9']['project_acceptance']['known_findings']


def test_quality_keeps_first_failure_and_all_attempts(function_map_case):
    dag, path, env, run, project, driver, source = function_map_case
    dag['config']['quality_tracking'] = {'sample_kind': 'framework_fixture', 'technology': ['python'],
        'risk': 'low', 'task_size': 'small', 'observation_window': 'fixture-v1', 'tool_version': 'test-v1'}
    app = project / 'app/application.py'
    valid = app.read_text()
    app.write_text(valid.replace('if key not in items: items.append(key)', 'items.append(key)'))
    failed, before = run('--stages', 'S1,S9')
    assert failed.returncode == 1
    app.write_text(valid)
    passed, after = run('--stages', 'S1,S9', '--resume')
    assert passed.returncode == 0, passed.stdout + passed.stderr
    output = project / 'quality-report.json'
    state = Path(env['PIPELINE_ROOT']) / 'fixture/state.json'
    command = [sys.executable, '-m', 'ai_sdlc_claudecode.quality', str(state), str(state), '--output', str(output)]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    task = report['tasks'][0]
    assert len(report['tasks']) == 1
    assert task['attempt_count'] == 3
    assert task['first_candidate_status'] == 'failed'
    assert task['current_acceptance'] == 'passed'
    assert task['repair_attempts'] == 1
    assert task['cost']['actual_total_usd'] is None
    assert task['cost']['estimated_usd'] > 0
    assert report['cohorts'][0]['metrics']['first_independent_pass_rate']['status'] == 'unavailable'
    original = output.read_bytes()
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert output.read_bytes() == original
    assert all(report['cohorts'][0]['metrics'][name]['status'] == 'unavailable' for name in (
        'bad_candidate_leak_rate', 'legitimate_candidate_block_rate', 'defect_recurrence'))
    candidates = [a for a in task['attempts'] if a['candidate_sha256']]
    evidence = project / 'independent-fixture-evidence.txt'
    evidence.write_text('Fixture oracle: repeated create must retain one item. This is framework test metadata.')
    common = {'task_id': task['task_id'], 'reviewer': 'fixture-oracle',
              'independence_basis': 'Frozen expected values in the framework test; not a real product review',
              'evidence': {'path': evidence.name, 'sha256': __import__('hashlib').sha256(evidence.read_bytes()).hexdigest()}}
    observations = []
    for index, candidate in enumerate(candidates):
        bound = {**common, **{key: candidate[key] for key in ('attempt_id', 'candidate_sha256', 'policy_sha256')}}
        observations.extend([
            {**bound, 'kind': 'oracle', 'classification': 'known_bad' if index == 0 else 'known_good'},
            {**bound, 'kind': 'independent_review', 'verdict': 'failed' if index == 0 else 'passed'},
        ])
    observations.append({**bound, 'kind': 'defect_followup', 'rule_id': 'duplicate-create', 'rule_version': '1',
                         'applicable': True, 'observed': True, 'recurred': True, 'defect_count': 2})
    observations.append({**bound, 'kind': 'human_intervention', 'count': 1})
    annotations = project / 'observations.json'
    annotations.write_text(json.dumps({'observations': observations + observations}))
    command += ['--observations', str(annotations)]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    metrics = json.loads(output.read_text())['cohorts'][0]['metrics']
    assert metrics['bad_candidate_leak_rate']['value'] == 0
    assert metrics['bad_candidate_leak_rate']['denominator'] == 1
    assert metrics['legitimate_candidate_block_rate']['value'] == 0
    assert metrics['first_independent_pass_rate']['value'] == 0
    assert metrics['first_independent_pass_rate']['denominator'] == 1
    assert metrics['defect_recurrence']['by_rule']['duplicate-create@1']['value'] == 1
    accepted = metrics['rework_and_cost']['accepted_tasks'][0]
    assert accepted['repair_attempts'] == 1
    assert accepted['cost']['estimated_usd'] == task['cost']['estimated_usd']
    assert accepted['human_interventions'] == 1
    evidence.write_text('changed after review')
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'evidence missing or changed' in result.stderr


def test_quality_scope_or_budget_changes_are_not_comparable(function_map_case):
    dag, path, env, run, project, driver, source = function_map_case
    first, _ = run('--stages', 'S1,S9')
    assert first.returncode == 0
    dag['config']['cost_limit_usd'] = 60
    second, _ = run('--stages', 'S1,S9', '--resume')
    assert second.returncode == 0, second.stdout + second.stderr
    from ai_sdlc_claudecode.quality import build_report
    report = build_report([Path(env['PIPELINE_ROOT']) / 'fixture/state.json'])
    assert report['tasks'][0]['comparable'] is False
    assert report['cohorts'][0]['comparable'] is False
    assert len(report['tasks'][0]['contexts']) == 2


def test_quality_measured_cost_is_distinct_and_replay_is_idempotent(executor_case):
    dag, path, env, run = executor_case
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    content = fake.read_text()
    start = content.index("    print(json.dumps({'stage_id': stage")
    fake.write_text(content[:start] + '''    document = {'stage_id': stage, 'status': 'complete', 'summary': 'fixture'}
    print(json.dumps({'type': 'result', 'result': json.dumps(document), 'model': 'fixture-model-v1',
                      'total_cost_usd': 0.125, 'usage': {'input_tokens': 100, 'output_tokens': 20}}))
''')
    result, data = run('--stages', 'S8')
    assert result.returncode == 0, result.stdout + result.stderr
    from ai_sdlc_claudecode.quality import build_report
    state = Path(env['PIPELINE_ROOT']) / 'fixture/state.json'
    task = build_report([state])['tasks'][0]
    assert task['cost']['actual_total_usd'] == 0.125
    assert task['cost']['estimated_usd'] is None
    record = data['stages']['S8']
    entry = next(iter(record['cost_entries']))
    command = [sys.executable, '-m', 'ai_sdlc_claudecode.state', 'cost', str(state),
               'actual', 'haiku', '0.125', '100', '20', '0', '0']
    replay = subprocess.run(command, env={**env, 'PIPELINE_RUN_ID': data['run_id'],
        'PIPELINE_ATTEMPT_ID': record['attempt_id'], 'PIPELINE_COST_ID': entry}, capture_output=True, text=True)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(state.read_text())['cost']['actual_usd'] == 0.125
    assert build_report([state])['tasks'][0]['cost']['actual_total_usd'] == 0.125


def test_quality_waiting_is_not_active_execution(executor_case):
    dag, path, env, run = executor_case
    dag['stages']['first']['gate'] = {'type': 'human-required'}
    result, data = run('--stages', 'S8')
    assert result.returncode == 3
    from ai_sdlc_claudecode.quality import build_report
    task = build_report([Path(env['PIPELINE_ROOT']) / 'fixture/state.json'])['tasks'][0]
    assert task['attempts'][0]['status'] == 'human_waiting'
    assert task['active_attempt_seconds'] >= 0
    assert task['authorization_wait_seconds'] is None
    assert task['current_acceptance'] == 'not_evaluated'


@pytest.mark.parametrize('has_attempt_id', [False, True])
def test_quality_legacy_failure_cannot_become_first_pass(project_acceptance_case, has_attempt_id):
    dag, path, env, run, project, driver = project_acceptance_case
    dag['config']['quality_tracking'] = {'sample_kind': 'framework_fixture', 'technology': ['python'],
        'risk': 'low', 'task_size': 'small', 'observation_window': 'fixture-v1', 'tool_version': 'test-v1'}
    first, data = run('--stages', 'S8,S9')
    assert first.returncode == 0
    legacy = {'stage_id': 'S9', 'status': 'failed'}
    if has_attempt_id:
        legacy['attempt_id'] = 'legacy-attempt'
    data.setdefault('history', []).insert(0, legacy)
    state = Path(env['PIPELINE_ROOT']) / 'fixture/state.json'
    state.write_text(json.dumps(data))
    from ai_sdlc_claudecode.quality import build_report
    report = build_report([state])
    task = report['tasks'][0]
    assert task['attempt_count'] == 3
    assert task['incomplete_attempts'] == 1
    assert task['first_candidate_status'] == 'unavailable'
    assert task['first_candidate_attempt_id'] is None
    assert task['repair_attempts'] == (1 if has_attempt_id else None)
    assert task['comparable'] is False
    assert report['cohorts'][0]['metrics']['first_independent_pass_rate']['status'] == 'unavailable'


def test_quality_skip_cannot_erase_first_failure(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    valid = driver.read_text()
    driver.write_text(valid.replace("'create': 'passed'", "'create': 'failed'"))
    first, before = run('--stages', 'S8,S9')
    assert first.returncode == 1
    original_attempt = before['stages']['S9']['attempt_id']
    skipped, _ = run('--stages', 'S8,S9', '--resume', '--skip-stage', 'S9')
    assert skipped.returncode == 4
    driver.write_text(valid)
    passed, _ = run('--stages', 'S8,S9', '--resume')
    assert passed.returncode == 0
    from ai_sdlc_claudecode.quality import build_report
    task = build_report([Path(env['PIPELINE_ROOT']) / 'fixture/state.json'])['tasks'][0]
    assert task['first_candidate_attempt_id'] == original_attempt
    assert task['first_candidate_status'] == 'failed'
    assert task['attempt_count'] == 3
    assert task['repair_attempts'] == 1


def test_quality_independent_acceptance_cannot_cross_contract(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    dag['config']['project_acceptance']['required_checks'] = {'business': ['create']}
    first, _ = run('--stages', 'S8,S9')
    assert first.returncode == 0
    from ai_sdlc_claudecode.quality import build_report
    state = Path(env['PIPELINE_ROOT']) / 'fixture/state.json'
    task = build_report([state])['tasks'][0]
    candidate = next(a for a in task['attempts'] if a['candidate_sha256'])
    evidence = project / 'review.txt'
    evidence.write_text('Independent fixture verdict for the create-only contract')
    observations = project / 'observations.json'
    observations.write_text(json.dumps({'observations': [{
        'kind': 'independent_review', 'verdict': 'passed', 'task_id': task['task_id'],
        **{key: candidate[key] for key in ('attempt_id', 'candidate_sha256', 'policy_sha256')},
        'reviewer': 'fixture-reviewer', 'independence_basis': 'Framework fixture with frozen expectations',
        'evidence': {'path': evidence.name, 'sha256': __import__('hashlib').sha256(evidence.read_bytes()).hexdigest()},
    }]}))
    assert len(build_report([state], observations)['cohorts'][0]['metrics']['rework_and_cost']['accepted_tasks']) == 1
    dag['config']['project_acceptance']['required_checks']['business'].append('replay')
    second, _ = run('--stages', 'S8,S9', '--resume')
    assert second.returncode == 0
    report = build_report([state], observations)
    assert report['tasks'][0]['current_candidate_sha256'] == candidate['candidate_sha256']
    assert report['tasks'][0]['current_policy_sha256'] != candidate['policy_sha256']
    assert report['cohorts'][0]['metrics']['rework_and_cost']['accepted_tasks'] == []
    assert len(report['cohorts'][0]['metrics']['rework_and_cost']['incomplete_tasks']) == 1


def test_project_acceptance_binds_actual_checks_to_current_candidate(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    result, data = run('--stages', 'S8,S9')
    assert result.returncode == 0, result.stdout + result.stderr
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    acceptance = state.project_acceptance()
    assert acceptance['status'] == 'passed'
    assert acceptance['scope'] == 'fixture-business'
    assert acceptance['candidate_sha256']
    assert acceptance['passed_cases'] == 2
    assert PipelineState.is_verified(data['stages']['S9'], path)


@pytest.mark.parametrize('mutation', ['changed', 'added', 'deleted', 'report', 'package', 'config'])
def test_candidate_or_receipt_drift_invalidates_only_final_acceptance(project_acceptance_case, mutation):
    dag, path, env, run, project, driver = project_acceptance_case
    if mutation in ('package', 'config'):
        bound_input = project / mutation
        bound_input.write_text('original candidate input\n')
        dag['config']['project_acceptance']['candidate_inputs'].append(mutation)
    result, data = run('--stages', 'S8,S9')
    assert result.returncode == 0, result.stdout + result.stderr
    source = project / 'app/application.py'
    if mutation == 'changed':
        source.write_text('VERSION = 2\n')
    elif mutation == 'added':
        (source.parent / 'new_untracked.py').write_text('NEW = True\n')
    elif mutation == 'deleted':
        source.unlink()
    elif mutation == 'report':
        Path(data['stages']['S9']['project_acceptance']['report_path']).write_text('{}')
    else:
        bound_input.write_text('modified candidate input\n')
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.project_acceptance()['status'] == 'incomplete'
    assert state.outcome() == 'partial'
    assert PipelineState.is_verified(data['stages']['S8'], path)
    assert not PipelineState.is_verified(data['stages']['S9'], path)


@pytest.mark.parametrize('change, expected', [
    ("report['checks']['business']['replay'] = 'failed'", 'failed'),
    ("report['checks']['business'] = {}", 'incomplete'),
    ("report['checks']['business']['replay'] = 'skipped'", 'incomplete'),
    ("report['attempt_id'] = 'previous-attempt'", 'incomplete'),
    ("report['findings'] = {'R1': {'status': 'fix_submitted'}}", 'failed'),
    ("report['checks']['extra'] = {'discovered_failure': 'failed'}", 'failed'),
    ("report['checks']['business'] = {'create': 'failed'}", 'failed'),
    ("report['run_id'] = 'previous-run'", 'incomplete'),
])
def test_project_acceptance_rejects_incomplete_or_failed_results(project_acceptance_case, change, expected):
    dag, path, env, run, project, driver = project_acceptance_case
    driver.write_text(driver.read_text().replace("Path(os.environ", change + "\nPath(os.environ"))
    result, data = run('--stages', 'S8,S9')
    assert result.returncode != 0, result.stdout + result.stderr
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.project_acceptance()['status'] == expected
    assert not PipelineState.is_verified(data['stages']['S9'], path)


def test_known_blocker_survives_repair_attempt_until_verified(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    original = driver.read_text()
    driver.write_text(original.replace("Path(os.environ", "report['findings'] = {'R1': {'status': 'open'}}\nPath(os.environ"))
    result, _ = run('--stages', 'S8,S9')
    assert result.returncode != 0
    driver.write_text(original)
    result, _ = run('--resume')
    assert result.returncode != 0, 'Omitting an already observed blocker must not close it'
    driver.write_text(original.replace("Path(os.environ", "report['findings'] = {'R1': {'status': 'verified_closed', 'checks': ['business']}}\nPath(os.environ"))
    result, _ = run('--resume')
    assert result.returncode == 0, result.stdout + result.stderr
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.project_acceptance()['status'] == 'passed'


def test_drift_does_not_erase_a_newly_observed_blocker(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    original = driver.read_text()
    driver.write_text(original.replace("Path(os.environ", "Path('app/application.py').write_text('VERSION = 2\\n')\n"
                      "report['findings'] = {'R1': {'status': 'open'}}\nPath(os.environ"))
    result, data = run('--stages', 'S8,S9')
    assert result.returncode != 0
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.project_acceptance()['status'] == 'incomplete'
    driver.write_text(original)
    result, _ = run('--resume')
    assert result.returncode != 0, 'A stale report must still preserve observed blocking findings'
    assert 'R1' in state.project_acceptance()['known_findings']


def test_candidate_directory_symlink_is_not_silently_omitted(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    shared = project / 'shared'
    shared.mkdir()
    (shared / 'lib.py').write_text('VERSION = 1\n')
    (project / 'app/shared').symlink_to(shared, target_is_directory=True)
    result, data = run('--stages', 'S8,S9')
    assert result.returncode != 0, 'Unsupported source traversal must fail closed'
    assert not PipelineState.is_verified(data['stages']['S9'], path)


def test_duplicate_case_keys_cannot_hide_a_failure(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    driver.write_text(driver.read_text().replace('json.dumps(report)',
        '''json.dumps(report).replace('"create": "passed"', '"create": "failed", "create": "passed"')'''))
    result, data = run('--stages', 'S8,S9')
    assert result.returncode != 0
    assert not PipelineState.is_verified(data['stages']['S9'], path)


@pytest.mark.parametrize('mode, expected_exit, expected_acceptance', [
    ('subset', 0, 'incomplete'), ('skip', 4, 'incomplete'),
    ('simulation', 0, 'not_evaluated'), ('human', 3, 'incomplete'),
    ('missing_report', 1, 'incomplete'), ('command_error', 1, 'failed'),
    ('command_error_no_report', 1, 'failed'), ('command_error_bad_report', 1, 'failed'),
])
def test_project_acceptance_scope_and_execution_boundaries(project_acceptance_case, mode, expected_exit, expected_acceptance):
    dag, path, env, run, project, driver = project_acceptance_case
    flags = ['--stages', 'S8,S9']
    if mode == 'subset':
        flags = ['--stages', 'S8']
    elif mode == 'skip':
        flags += ['--skip-stage', 'S9']
    elif mode == 'simulation':
        flags += ['--mock-review']
    elif mode == 'human':
        dag['stages']['second']['gate'] = {'type': 'human-required'}
    elif mode == 'missing_report':
        dag['stages']['second']['post_commands'] = ['true']
    elif mode == 'command_error_no_report':
        dag['stages']['second']['post_commands'] = ['exit 7']
    elif mode == 'command_error_bad_report':
        driver.write_text(driver.read_text().replace('json.dumps(report)', "'invalid JSON'"))
        dag['stages']['second']['post_commands'].append('exit 7')
    else:
        dag['stages']['second']['post_commands'].append('exit 2')
    result, _ = run(*flags)
    assert result.returncode == expected_exit, result.stdout + result.stderr
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.project_acceptance()['status'] == expected_acceptance


@pytest.mark.parametrize('fails', [False, True])
def test_parallel_project_acceptance_uses_the_same_gate(project_acceptance_case, fails):
    dag, path, env, run, project, driver = project_acceptance_case
    dag['execution_order'] = [{'stages': ['first', 'second'], 'mode': 'parallel'}]
    if fails:
        driver.write_text(driver.read_text().replace("'replay': 'passed'", "'replay': 'failed'"))
    result, data = run('--stages', 'S8,S9')
    assert (result.returncode == 0) is not fails, result.stdout + result.stderr
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.project_acceptance()['status'] == ('failed' if fails else 'passed')
    assert PipelineState.is_verified(data['stages']['S8'], path)


def test_resume_reverifies_changed_candidate_without_redoing_unrelated_stage(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    result, before = run('--stages', 'S8,S9')
    assert result.returncode == 0
    (project / 'app/application.py').write_text('VERSION = 2\n')
    result, after = run('--resume')
    assert result.returncode == 0, result.stdout + result.stderr
    assert before['stages']['S8']['attempt_id'] == after['stages']['S8']['attempt_id']
    assert before['stages']['S9']['attempt_id'] != after['stages']['S9']['attempt_id']
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.project_acceptance()['status'] == 'passed'
    record = after['stages']['S9']
    for operation, extra in [(state.prepare_acceptance, ()), (state.collect_acceptance, (0,))]:
        with pytest.raises(ValueError, match='terminal'):
            operation(record['run_id'], 'S9', record['attempt_id'], *extra)


def test_runner_exposes_project_acceptance_separately(project_acceptance_case, monkeypatch):
    from ai_sdlc_claudecode.runner import PipelineRunner
    dag, path, env, run, project, driver = project_acceptance_case
    result, _ = run('--stages', 'S8,S9')
    assert result.returncode == 0
    # Resume retrieves the original project directory through the real runner entrypoint.
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    (project / 'app/application.py').write_text('VERSION = 2\n')
    runner = PipelineRunner(ROOT / 'pipeline-executor.sh', Path(env['PIPELINE_ROOT']))
    result = runner.run('fixture', 'local only', resume=True, timeout_seconds=25)
    assert result.all_passed and result.outcome == 'complete', result.stdout + result.stderr
    assert result.project_acceptance['status'] == 'passed'
    assert result.project_acceptance['run_id'] == result.run_id
    driver.write_text(driver.read_text().replace("'replay': 'passed'", "'replay': 'failed'"))
    result = runner.run('fixture', 'local only', resume=True, timeout_seconds=25)
    assert not result.all_passed and result.outcome == 'failed'
    assert result.project_acceptance['status'] == 'failed'


def test_runner_terminal_failure_is_visible_in_every_summary(project_acceptance_case, monkeypatch):
    import shlex
    from ai_sdlc_claudecode.runner import PipelineRunner
    dag, path, env, run, project, driver = project_acceptance_case
    path.write_text(json.dumps(dag))
    wrapper = project / 'wrapper.sh'
    wrapper.write_text('bash ' + shlex.quote(str(ROOT / 'pipeline-executor.sh'))
                       + ' "$@" --project-dir ' + shlex.quote(str(project)) + '\nexit 7\n')
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    result = PipelineRunner(wrapper, Path(env['PIPELINE_ROOT'])).run('fixture', 'local only', timeout_seconds=25)
    assert result.exit_code == 7 and result.outcome == 'failed'
    assert result.project_acceptance['status'] == 'incomplete'
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.summary()['execution_outcome'] == result.outcome
    assert state.summary()['project_acceptance']['status'] == result.project_acceptance['status']
    # The next real invocation owns a new process outcome and may reuse valid stage proofs.
    result, _ = run('--resume')
    assert result.returncode == 0, result.stdout + result.stderr
    assert state.summary()['project_acceptance']['status'] == 'passed'


def test_reports_recompute_acceptance_after_candidate_changes(project_acceptance_case):
    dag, path, env, run, project, driver = project_acceptance_case
    result, data = run('--stages', 'S8,S9')
    assert result.returncode == 0, result.stdout + result.stderr
    (project / 'app/application.py').write_text('VERSION = 2\n')
    status = subprocess.run([sys.executable, '-m', 'ai_sdlc_claudecode', 'status', '--feature-id', 'fixture'],
                            env=env, text=True, capture_output=True, timeout=10)
    assert status.returncode == 0, status.stderr
    assert 'Project acceptance: incomplete' in status.stdout
    assert 'Execution: partial' in status.stdout
    report = subprocess.run([sys.executable, '-m', 'ai_sdlc_claudecode', 'report', '--feature-id', 'fixture'],
                            env=env, text=True, capture_output=True, timeout=10)
    assert report.returncode == 0, report.stderr
    report_path = Path(env['PIPELINE_ROOT']) / 'fixture/ai-sdlc-report.md'
    content = report_path.read_text()
    assert '**Project acceptance**: incomplete' in content
    assert '**Execution**: partial' in content
    assert '1/2' in content
    assert '/13' not in content
    # Displays must use the run's DAG, even when no caller supplies its path.
    display_env = {key: value for key, value in env.items() if key != 'PIPELINE_DAG_FILE'}
    for missing_dag in (False, True):
        if missing_dag:
            path.unlink()
        for script, args in [('pipeline-status.sh', ['fixture']), ('pipeline-monitor.sh', ['fixture']),
                             ('pipeline-list.sh', []), ('pipeline-list.sh', ['--verbose']),
                             ('pipeline-list.sh', ['--json'])]:
            result = subprocess.run(['bash', str(ROOT / script), *args], env=display_env,
                                    capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, script + '\n' + result.stderr
            if '--json' in args:
                row = json.loads(result.stdout)[0]
                assert row['pipeline_state'] == 'partial'
                assert row['project_acceptance']['status'] == 'incomplete'
                assert row['stages_passed'] == (0 if missing_dag else 1) and row['stages_total'] == 2
            else:
                assert 'Project acceptance: incomplete' in result.stdout, script + result.stdout
                assert 'Execution: partial' in result.stdout
                assert ('0/2' if missing_dag else '1/2') in result.stdout
                assert 'Remaining:' in result.stdout and 'Next: Coordinator:' in result.stdout


def test_concurrent_supervisor_cost_writers_preserve_stage_records(contract):
    from concurrent.futures import ThreadPoolExecutor
    state, run, dag, output_dir = contract
    record = verified_attempt(contract)
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PIPELINE_RUN_ID': run}
    def write_cost(_):
        subprocess.run([sys.executable, '-m', 'ai_sdlc_claudecode.state', 'cost', str(state.path),
                        'actual', 'fixture', '0.125', '2', '3', '5', '7'], env=env, check=True,
                       capture_output=True, text=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write_cost, range(24)))
    data = state.read()
    assert data['cost']['actual_usd'] == 3
    assert data['cost']['total_tokens'] == 24 * 17
    assert data['cost']['by_model']['fixture']['calls'] == 24
    assert data['stages']['S1'] == record


def test_required_check_list_cannot_be_weakened_in_record(contract):
    state, run, dag, output_dir = contract
    record = verified_attempt(contract)
    record['required_checks'] = ['schema']
    record['verification']['evidence'] = record['verification']['evidence'][:1]
    assert not state.is_verified(record, dag)


def test_learning_failure_is_idempotent_and_cannot_turn_into_success(contract, tmp_path):
    from ai_sdlc_claudecode.engine import ErrorEngine
    state, run, dag, output_dir = contract
    engine = ErrorEngine(tmp_path / 'errors')
    error = engine.capture('feature', 'S1', 'example', 'schema validation error', 1, 0, 1)
    record = verified_attempt(contract)
    record.update(status='failed', applied_fix_ids=[error.variants[0]['id']])
    engine.record_outcome(record)
    ErrorEngine(engine.errors_dir).record_outcome(record)
    record['status'] = 'passed'
    ErrorEngine(engine.errors_dir).record_outcome(record)
    current = ErrorEngine(engine.errors_dir).index['S1'][0]
    assert current.variants[0]['fail'] == 1
    assert current.success_after_apply == 0
    assert current.applied_count == 1


def test_duplicate_error_records_do_not_multiply_fix_samples(contract, tmp_path):
    from ai_sdlc_claudecode.engine import ErrorEngine
    engine = ErrorEngine(tmp_path / 'errors')
    one = engine.capture('feature', 'S1', 'example', 'schema validation error', 1, 0, 1)
    engine.capture('feature', 'S1', 'example', 'schema validation error', 1, 1, 1)
    record = verified_attempt(contract)
    record['applied_fix_ids'] = [one.variants[0]['id']]
    engine.record_outcome(record)
    aggregate = {v['id']: v for v in engine._aggregate_variants('S1')}
    assert aggregate[one.variants[0]['id']]['success'] == 1
    engine.write_augments()
    engine.write_augments()
    assert {v['id']: v for v in engine._aggregate_variants('S1')}[one.variants[0]['id']]['success'] == 1


def test_supervisor_resume_replays_an_unattributed_terminal_result_once(contract, tmp_path):
    from ai_sdlc_claudecode.engine import ErrorEngine
    state, run, dag, output_dir = contract
    engine = ErrorEngine(tmp_path / 'errors')
    error = engine.capture('feature', 'S1', 'example', 'schema validation error', 1, 0, 1)
    record = verified_attempt(contract)
    state.finish_attempt(run, 'S1', record['attempt_id'], 'passed', output_dir / 'output.json', [error.variants[0]['id']])
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'EVOLVE_ERRORS_DIR': str(engine.errors_dir)}
    for _ in range(2):
        subprocess.run([sys.executable, '-m', 'ai_sdlc_claudecode.state', 'replay', str(state.path)], env=env, check=True,
                       capture_output=True, text=True)
    assert ErrorEngine(engine.errors_dir).index['S1'][0].success_after_apply == 1


def test_failed_refinement_is_a_required_check(executor_case):
    dag, path, env, run = executor_case
    dag['stages']['first']['review_passes'] = [{'role': 'reviewer', 'prompt_file': 'missing-prompt.md'}]
    result, data = run('--stages', 'S8')
    assert result.returncode != 0
    record = data['stages']['S8']
    assert record['status'] == 'dead_letter'
    assert record['verification']['evidence'][0]['check'] == 'refinement'
    assert record['verification']['evidence'][0]['exit_code'] != 0


def test_prose_in_protocol_is_opaque_data(tmp_path):
    import shlex
    marker = tmp_path / 'injected'
    payload = "quote ' and newline\n\"); __import__('pathlib').Path(" + repr(str(marker)) + ").touch(); #"
    env = {**os.environ, 'PIPELINE_ROOT': str(tmp_path), 'PIPELINE_RUN_ID': 'run', 'PIPELINE_ATTEMPT_ID': 'attempt'}
    cmd = f'source {shlex.quote(str(ROOT / "lib/protocol.sh"))}\nsend_message fixture Commander Agent request "$1"'
    subprocess.run(['bash', '-c', cmd, 'fixture', payload], env=env, check=True, capture_output=True)
    record = json.loads((tmp_path / 'fixture/communication.jsonl').read_text())
    assert record['content'] == payload
    assert record['run_id'] == 'run' and record['attempt_id'] == 'attempt'
    assert not marker.exists()


def test_status_commands_use_verified_scope(executor_case):
    dag, path, env, run = executor_case
    result, data = run('--stages', 'S8')
    assert result.returncode == 0
    for script, args in [('pipeline-list.sh', ['--json']), ('pipeline-status.sh', ['fixture']),
                         ('pipeline-monitor.sh', ['fixture'])]:
        result = subprocess.run(['bash', str(ROOT / script), *args], env=env,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, script + '\n' + result.stderr
        if script == 'pipeline-list.sh':
            row = json.loads(result.stdout)[0]
            assert row['stages_passed'] == row['stages_total'] == 1


def test_rejected_concurrent_runner_cannot_overwrite_winning_run(project_acceptance_case, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from ai_sdlc_claudecode.runner import PipelineRunner
    dag, path, env, run, project, driver = project_acceptance_case
    path.write_text(json.dumps(dag))
    import shlex
    wrapper = project / 'wrapper.sh'
    wrapper.write_text('bash ' + shlex.quote(str(ROOT / 'pipeline-executor.sh'))
                       + ' "$@" --project-dir ' + shlex.quote(str(project)) + '\n')
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake.write_text(fake.read_text().replace('stage = re.search', 'import time\ntime.sleep(1)\nstage = re.search'))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Both real invocations observe the same baseline before either launches.
    original_read = PipelineState.read
    barrier, local = threading.Barrier(2), threading.local()
    def read_baseline(self):
        data = original_read(self)
        if not getattr(local, 'started', False):
            local.started = True
            barrier.wait(timeout=10)
        return data
    monkeypatch.setattr(PipelineState, 'read', read_baseline)
    def invoke(_):
        return PipelineRunner(wrapper, Path(env['PIPELINE_ROOT'])).run('fixture', 'local only', timeout_seconds=25)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, range(2)))
    monkeypatch.setattr(PipelineState, 'read', original_read)
    winner = [result for result in results if result.exit_code == 0]
    assert len(winner) == 1, [(result.exit_code, result.stderr) for result in results]
    loser = next(result for result in results if result.exit_code != 0)
    assert loser.run_id is None and not loser.all_passed
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    assert state.summary()['project_acceptance']['status'] == 'passed'
    assert state.read()['executor_exit']['exit_code'] == 0
    before = state.read()
    assert not state.record_executor_exit(before['run_id'], 'another-invocation', 7)
    assert state.read() == before


def test_runner_does_not_attribute_successor_summary_to_its_own_run(project_acceptance_case, monkeypatch):
    import shlex
    from ai_sdlc_claudecode.runner import PipelineRunner
    dag, path, env, run, project, driver = project_acceptance_case
    path.write_text(json.dumps(dag))
    wrapper = project / 'wrapper.sh'
    wrapper.write_text('bash ' + shlex.quote(str(ROOT / 'pipeline-executor.sh'))
                       + ' "$@" --project-dir ' + shlex.quote(str(project)) + '\nexit 7\n')
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    original_summary = PipelineState.summary
    successor = []
    def summary_after_successor_starts(self):
        # A real state transition at the precise gap between exit write and readback.
        successor.append(self.start_run('fixture', path, ['S8', 'S9'],
                                       invocation_id='successor', project_dir=str(project)))
        return original_summary(self)
    monkeypatch.setattr(PipelineState, 'summary', summary_after_successor_starts)
    result = PipelineRunner(wrapper, Path(env['PIPELINE_ROOT'])).run('fixture', 'local only', timeout_seconds=25)
    assert result.exit_code == 7 and not result.all_passed
    assert result.run_id is None
    assert result.project_acceptance['status'] == 'not_evaluated'
    assert PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json').read()['run_id'] == successor[0]
