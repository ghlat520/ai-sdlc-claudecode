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
                                capture_output=True, text=True, timeout=25)
        state_file = tmp_path / 'pipeline' / 'fixture' / 'state.json'
        data = json.loads(state_file.read_text()) if state_file.exists() else {}
        (tmp_path / 'last-output.log').write_text(result.stdout + result.stderr)
        return result, data
    return dag, dag_path, env, run


@pytest.mark.parametrize("template_has_description", [False, True])
def test_code_stage_can_write_source_and_returns_metadata(executor_case, template_has_description):
    dag, path, env, run = executor_case
    if template_has_description:
        dag["stages"]["first"]["agents"][0]["prompt_template"] += "\n{{feature_description}}"
    dag['stages']['first']['writes_code'] = True
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
