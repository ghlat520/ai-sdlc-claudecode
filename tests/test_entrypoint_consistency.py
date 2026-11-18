"""Public execution and reporting agree on a fixed candidate's actual checks."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_sdlc_claudecode.state import PipelineState
from tests.test_pipeline_contract import executor_case, project_acceptance_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('blocked', [True, False], ids=['fixed-bad', 'legal-control'])
def test_public_entrypoints_preserve_candidate_verdict(project_acceptance_case, blocked):
    """Local model protocol fixture; real Bash, CLI, checks, state and readers."""
    dag, dag_path, env, run, project, driver = project_acceptance_case
    del dag['stages']['first']
    dag['execution_order'] = [{'stage': 'second', 'mode': 'sequential'}]
    policy = dag['config']['project_acceptance']
    policy['blocking_findings'] = {'R1': ['business']}
    (project / 'app/application.py').write_text(f'VERSION = {0 if blocked else 1}\n')
    driver.write_text('''import json, os, runpy, sys
from pathlib import Path
passed = runpy.run_path('app/application.py')['VERSION'] == 1
report = {
    'run_id': os.environ['PIPELINE_RUN_ID'],
    'attempt_id': os.environ['PIPELINE_ATTEMPT_ID'],
    'checks': {'business': {case: 'passed' if passed else 'failed'
                            for case in ('create', 'replay')}},
    'findings': {'R1': {'status': 'verified_closed' if passed else 'open',
                        'checks': ['business']}},
}
Path(os.environ['PIPELINE_ACCEPTANCE_REPORT']).write_text(json.dumps(report))
sys.exit(0 if passed else 1)
''')
    expected_exit = 1 if blocked else 0
    expected_execution = 'failed' if blocked else 'complete'
    expected_acceptance = 'failed' if blocked else 'passed'
    state = PipelineState(Path(env['PIPELINE_ROOT']) / 'fixture/state.json')
    original_candidate = hashlib.sha256((project / 'app/application.py').read_bytes()).hexdigest()
    observations = []
    previous_run = previous_attempt = candidate_sha = None

    # The first public invocation also persists --project-dir for the CLI run.
    for entrypoint in ('bash', 'python-cli'):
        if entrypoint == 'bash':
            result, data = run('--stages', 'S9')
        else:
            result = subprocess.run(
                [sys.executable, '-m', 'ai_sdlc_claudecode', 'run', '--phase', '2',
                 '--feature-id', 'fixture'],
                env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=35,
            )
            data = state.read()
            checkpoint = json.loads(state.path.with_name('ai-sdlc-state.json').read_text())
            assert 1 <= checkpoint['current_iteration'] <= 10
            assert (checkpoint['phases']['2']['status'] == 'complete') is (not blocked)
        (project / f'{entrypoint}-execution.log').write_text(result.stdout + result.stderr)
        assert result.returncode == expected_exit, result.stdout + result.stderr
        summary = state.summary()
        acceptance = summary['project_acceptance']
        record = data['stages']['S9']
        assert data['executor_exit']['exit_code'] == expected_exit
        assert data['executor_exit']['run_id'] == data['run_id']
        assert acceptance['run_id'] == record['run_id']
        assert data['executor_exit']['invocation_id'] == data['invocation_id']
        assert data['pipeline_state'] == summary['execution_outcome'] == expected_execution
        assert acceptance['status'] == expected_acceptance
        assert acceptance['passed_cases'] == (0 if blocked else 2)
        assert acceptance['required_cases'] == 2
        assert acceptance['attempt_id'] == record['attempt_id']
        assert data['run_id'] != previous_run
        if blocked:
            assert record['attempt_id'] != previous_attempt
            assert record['run_id'] == data['run_id']
        assert acceptance['candidate_sha256'] == (candidate_sha or acceptance['candidate_sha256'])
        candidate_sha = acceptance['candidate_sha256']
        previous_run, previous_attempt = data['run_id'], record['attempt_id']
        report = json.loads(Path(acceptance['report_path']).read_text())
        assert report['findings']['R1']['status'] == ('open' if blocked else 'verified_closed')
        assert report['run_id'] == record['run_id'] and report['attempt_id'] == record['attempt_id']

        display_env = {key: value for key, value in env.items() if key != 'PIPELINE_DAG_FILE'}
        commands = [
            ('python-status', [sys.executable, '-m', 'ai_sdlc_claudecode', 'status', '--feature-id', 'fixture']),
            ('python-report', [sys.executable, '-m', 'ai_sdlc_claudecode', 'report', '--feature-id', 'fixture']),
            ('bash-status', ['bash', str(ROOT / 'pipeline-status.sh'), 'fixture']),
            ('bash-monitor', ['bash', str(ROOT / 'pipeline-monitor.sh'), 'fixture']),
            ('bash-list', ['bash', str(ROOT / 'pipeline-list.sh')]),
            ('bash-list-verbose', ['bash', str(ROOT / 'pipeline-list.sh'), '--verbose']),
            ('bash-list-json', ['bash', str(ROOT / 'pipeline-list.sh'), '--json']),
        ]
        frozen_state = state.path.read_bytes()
        for name, command in commands:
            read = subprocess.run(command, env=display_env, capture_output=True, text=True, timeout=10)
            (project / f'{entrypoint}-{name}.log').write_text(read.stdout + read.stderr)
            assert read.returncode == 0, name + read.stderr
            if name == 'bash-list-json':
                rows = json.loads(read.stdout)
                assert len(rows) == 1
                row = rows[0]
                assert row['project_acceptance']['run_id'] == record['run_id']
                assert row['pipeline_state'] == expected_execution
                assert row['project_acceptance'] == acceptance
                assert row['stages_passed'] == (0 if blocked else 1)
                assert row['stages_total'] == 1
            else:
                content = (state.path.with_name('ai-sdlc-report.md').read_text()
                           if name == 'python-report' else read.stdout)
                plain = content.replace('**', '')
                for line in (f'Execution: {expected_execution}',
                             f'Project acceptance: {expected_acceptance}',
                             'Acceptance scope: fixture-business',
                             f'Candidate: {candidate_sha}',
                             f'Verified stages: {0 if blocked else 1}/1 (configured scope)'):
                    assert line in plain, (name, line, content)
                if blocked:
                    assert 'Blocking finding not verified closed: R1' in content
            assert state.path.read_bytes() == frozen_state, name + ' changed the execution state'
            observations.append(dict(entrypoint=entrypoint, reader=name, exit_code=read.returncode,
                                     run_id=data['run_id'], attempt_id=record['attempt_id'],
                                     execution=expected_execution, acceptance=expected_acceptance,
                                     candidate_sha256=candidate_sha))
        assert hashlib.sha256((project / 'app/application.py').read_bytes()).hexdigest() == original_candidate
    (project / 'entrypoint-observations.json').write_text(json.dumps(observations, indent=2))
