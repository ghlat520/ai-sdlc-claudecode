"""Actual supervisor checks over isolated mixed-language applications."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.test_pipeline_contract import executor_case
from ai_sdlc_claudecode.state import PipelineState
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('code,blocked', [
    ('import {secret} from "../backend/secret"; export const label = secret;', True),
    ('import {items} from "demo/catalog"; export const label = items;', True),
    ('// import {items} from "demo/catalog";\nexport const label = "../backend/secret";', False),
    ('export const load = () => import("../backend/secret");', True),
])
def test_s2_dependency_rules_use_import_syntax(tmp_path, code, blocked):
    (tmp_path / 'frontend').mkdir()
    (tmp_path / 'frontend/node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    (tmp_path / 'frontend/value.ts').write_text(code)
    contract = tmp_path / 'contracts.json'
    contract.write_text(json.dumps({'services': [], 'quality_rules': [{
        'id': 'ARCH-PROD-01', 'kind': 'imports', 'language': 'typescript', 'paths': ['frontend'],
        'exclude': [], 'forbidden': ['../backend/*', 'demo/*'], 'source': 'approved architecture',
        'message': 'Renderer uses API and cannot import backend or demo providers',
    }]}))
    result = subprocess.run([sys.executable, '-m', 'ai_sdlc_claudecode.contract_validator', str(contract), str(tmp_path)],
                            capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    assert result.returncode == (1 if blocked else 0), result.stdout + result.stderr
    if blocked: assert 'ARCH-PROD-01' in result.stdout


@pytest.mark.parametrize('code,blocked', [('import app.demo.provider',True),('from .demo import provider',True),('from . import demo',True),
    ("import importlib; value=importlib.import_module('.demo.provider',package='app')",True),
    ("from importlib import import_module as load; value=load('.demo.provider',package='app')",True),('from . import safe',False)])
def test_relative_imports_cannot_bypass_package_boundary(tmp_path,code,blocked):
    from ai_sdlc_claudecode.contract_validator import validate
    (tmp_path/'app').mkdir(); (tmp_path/'app/main.py').write_text(code)
    source=tmp_path/'contracts.json';source.write_text(json.dumps({'services':[], 'quality_rules':[
        {'id':'PROD-PACKAGE','kind':'imports','language':'python','paths':['app'],'exclude':[],
         'forbidden':['app.demo','app.demo.*'],'source':'package boundary','message':'production excludes demo providers'}]}))
    assert bool(validate(source,tmp_path).blocking()) is blocked


@pytest.mark.parametrize('language,filename,code', [('python','dynamic.py','import importlib\nimportlib.import_module(module_name)'),
    ('typescript','dynamic.ts','export const load = name => import(name);')])
def test_excluded_test_files_are_excluded_before_parsing(tmp_path,language,filename,code):
    from ai_sdlc_claudecode.contract_validator import validate
    (tmp_path/'app/tests').mkdir(parents=True);(tmp_path/'app/tests'/filename).write_text(code)
    (tmp_path/'app/node_modules').symlink_to(ROOT/'node_modules',target_is_directory=True)
    (tmp_path/'app'/('main.py' if language=='python' else 'main.ts')).write_text('value = 42' if language=='python' else 'export const value = 42;')
    source=tmp_path/'contracts.json';source.write_text(json.dumps({'services':[],'quality_rules':[
        {'id':'PROD-EXCLUDE','kind':'imports','language':language,'paths':['app'],'exclude':['app/tests/*'],
         'forbidden':['demo.*','demo/*'],'source':'explicit test exclusion','message':'production uses actual providers'}]}))
    assert not validate(source,tmp_path).blocking()


@pytest.mark.parametrize('wire,blocked', [
    ({'id': 3, 'label': 'valid alias mapping'}, False),
    ({'item_id': 3, 'label': 'drift'}, True),
    ({'id': True, 'label': 'boolean is not integer'}, True),
])
def test_wire_rules_check_actual_serialization(tmp_path, wire, blocked):
    # The adapter executes a real JSON serializer; HTTP probes use this same wire shape below.
    (tmp_path / 'serialize.py').write_text('import json\ninternal_name = ' + repr(wire) + '\nprint(json.dumps({"method":"POST","path":"/items","status":201,"request":{"label":"input"},"response":internal_name}))')
    contract = {'services': [], 'api_endpoints': [{'service': 'backend', 'method': 'POST', 'path': '/items',
        'request_fields': [{'name': 'label', 'type': 'string'}],
        'response_fields': [{'name': 'id', 'type': 'integer'}, {'name': 'label', 'type': 'string'}]}],
        'quality_rules': [{'id': 'API-01', 'kind': 'wire', 'source': 'FR-1 / AC-1',
            'message': 'Published JSON fields must match S2', 'paths': ['serialize.py'],
            'endpoint': {'service': 'backend', 'method': 'POST', 'path': '/items'}, 'command': 'python3 serialize.py'}]}
    source = tmp_path / 'contracts.json'; source.write_text(json.dumps(contract))
    result = subprocess.run([sys.executable, '-m', 'ai_sdlc_claudecode.contract_validator', str(source), str(tmp_path)],
        capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    assert result.returncode == (1 if blocked else 0), result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['rules'][0]['id'] == 'API-01'
    assert report['source_binding']['manifest']


def test_production_import_rule_respects_explicit_test_scope(executor_case, tmp_path):
    dag, path, env, run = executor_case
    (tmp_path / 'app').mkdir(); (tmp_path / 'app/tests').mkdir()
    (tmp_path / 'app/main.py').write_text('import json as wire\n')
    (tmp_path / 'app/tests/test_main.py').write_text('import demo.provider\n')
    rule = {'id': 'PROD-01', 'kind': 'imports', 'language': 'python', 'paths': ['app'],
        'exclude': ['app/tests/*'], 'forbidden': ['demo.*'], 'source': 'approved production boundary',
        'message': 'Production must not import demonstration providers'}
    contract = tmp_path / 'contracts.json'; contract.write_text(json.dumps({'services': [], 'quality_rules': [rule]}))
    dag['config']['modules'] = {'application': {'path': 'app', 'tech_stack': 'python', 'inputs': ['main.py', 'tests'],
        'artifacts': [], 'commands': {'rules': 'python3 -m ai_sdlc_claudecode.contract_validator ../contracts.json ..'}}}
    dag['stages']['first']['module_checks'] = {'application': ['rules']}
    dag['stages']['first']['gate'] = {'type': 'ai-review'}
    result, data = run('--stages', 'S8')
    assert result.returncode == 0, result.stdout + result.stderr
    (tmp_path / 'app/main.py').write_text('import demo.provider\n')
    result, data = run('--stages', 'S8', '--resume')
    assert result.returncode == 1
    assert 'PROD-01' in Path(data['stages']['S8']['output_dir'], 'post-commands.log').read_text()


@pytest.fixture
def module_case(executor_case, tmp_path):
    dag, path, env, run = executor_case
    for name in ('backend', 'frontend', 'worker'):
        (tmp_path / name).mkdir()
    (tmp_path / 'backend/Value.java').write_text('public class Value { public static int value() { return 42; } }')
    (tmp_path / 'frontend/value.ts').write_text('export const value: number = 42;')
    (tmp_path / 'frontend/node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    (tmp_path / 'worker/value.py').write_text('def value():\n    return 42\n')
    dag['config']['tech_stack_commands'] = {'java-maven': {'compile': 'javac -d classes Value.java'},
        'node-typescript': {'compile': 'node node_modules/typescript/bin/tsc value.ts --outDir dist --strict --skipLibCheck'},
        'python': {'compile': 'python3 -c "import py_compile; py_compile.compile(\'value.py\', \'value.pyc\', doraise=True)"' }}
    dag['config']['modules'] = {
        'backend': {'path': 'backend', 'tech_stack': 'java-maven', 'inputs': ['Value.java'], 'artifacts': ['classes/Value.class']},
        'frontend': {'path': 'frontend', 'tech_stack': 'node-typescript', 'inputs': ['value.ts'], 'artifacts': ['dist/value.js']},
        'worker': {'path': 'worker', 'tech_stack': 'python', 'inputs': ['value.py'], 'artifacts': []},
    }
    dag['stages']['first']['module_checks'] = {name: ['compile'] for name in dag['config']['modules']}
    return dag, path, env, run, tmp_path


def test_mixed_modules_run_their_own_compilers(module_case):
    dag, path, env, run, project = module_case
    result, data = run('--stages', 'S8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / 'backend/classes/Value.class').exists()
    assert (project / 'frontend/dist/value.js').exists()
    assert (project / 'worker/value.pyc').exists()
    binding = data['stages']['S8']['module_checks']
    assert set(binding['modules']) == {'backend', 'frontend', 'worker'}
    assert binding['modules']['worker']['tech_stack'] == 'python'
    (project / 'frontend/dist/value.js').write_text('broken artifact')
    assert not PipelineState.is_verified(data['stages']['S8'], path)


@pytest.mark.parametrize('change', ['unknown_module', 'empty_checks', 'wrong_directory', 'missing_tool', 'empty_command', 'missing_input'])
def test_module_check_configuration_or_tool_failure_cannot_pass(module_case, change):
    dag, path, env, run, project = module_case
    stage = dag['stages']['first']
    if change == 'unknown_module': stage['module_checks'] = {'absent': ['compile']}
    elif change == 'empty_checks': stage['module_checks'] = {}
    elif change == 'wrong_directory': dag['config']['modules']['backend']['path'] = 'absent'
    elif change == 'missing_tool': dag['config']['modules']['backend']['commands'] = {'compile': 'nonexistent-quality-compiler'}
    elif change == 'empty_command': dag['config']['modules']['backend']['commands'] = {'compile': ''}
    else: dag['config']['modules']['backend']['inputs'].append('missing-lock.json')
    result, data = run('--stages', 'S8')
    assert result.returncode != 0
    assert data.get('stages', {}).get('S8', {}).get('status') != 'passed'


def test_cli_stack_override_selects_post_command_at_execution_time(executor_case, tmp_path):
    dag, path, env, run = executor_case
    (tmp_path / 'value.py').write_text('answer = 42')
    dag['config']['tech_stack'] = 'java-maven'
    dag['config']['tech_stack_commands'] = {
        'java-maven': {'compile': 'exit 99'},
        'python': {'compile': 'python3 -c "import py_compile; py_compile.compile(\'value.py\', \'value.pyc\', doraise=True)"' },
    }
    dag['stages']['first']['post_commands'] = ['{{compile}}']
    result, _ = run('--stages', 'S8', '--tech-stack', 'python')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'value.pyc').exists()


def test_generated_bytecode_does_not_change_declared_source(executor_case,tmp_path):
    dag,path,env,run=executor_case
    (tmp_path/'worker/src').mkdir(parents=True);(tmp_path/'worker/src/value.py').write_text('value=42')
    (tmp_path/'shared.lock').write_text('dependency version 1')
    dag['config']['modules']={'worker':{'path':'worker','tech_stack':'python','inputs':['src'],
        'root_inputs':['shared.lock'],'artifacts':['src/value.pyc'],
        'commands':{'compile':'''python3 -c "import py_compile; py_compile.compile('src/value.py','src/value.pyc',doraise=True)"'''}}}
    dag['stages']['first']['module_checks']={'worker':['compile']}
    result,data=run('--stages','S8');assert result.returncode==0,result.stdout+result.stderr
    assert PipelineState.is_verified(data['stages']['S8'],path)
    (tmp_path/'shared.lock').write_text('dependency version 2')
    assert not PipelineState.is_verified(data['stages']['S8'],path)


def test_module_coverage_uses_same_module_and_stack(module_case):
    dag, path, env, run, project = module_case
    (project / 'worker/test_value.py').write_text('from value import value\ndef test_value():\n    assert value() == 42\n')
    dag['config']['modules']['worker']['commands'] = {
        'test': 'python3 -m pytest test_value.py -q',
        'coverage': 'python3 -m pytest test_value.py --cov=value --cov-report=term -q',
    }
    dag['config']['modules']['worker']['inputs'].append('test_value.py')
    dag['stages']['first']['id'] = 'S4'
    dag['stages']['first']['agents'][0]['prompt_template'] = 'FAKE_STAGE:S4'
    dag['stages']['first']['module_checks'] = {'worker': ['test', 'coverage']}
    # S4 handoff gate requires a minimal test report, supplied at the model boundary.
    fake = Path(env['PATH'].split(os.pathsep)[0]) / 'claude'
    fake.write_text(fake.read_text().replace("'summary': 'fixture'", "'summary': 'fixture', 'testing': {'test_results': {'failed':0}, 'coverage': {'line_percent':100}}"))
    result, data = run('--stages', 'S4')
    assert result.returncode == 0, result.stdout + result.stderr
    record = data['stages']['S4']
    log = (Path(record['output_dir']) / 'post-commands.log').read_text()
    assert 'Tech stack: python' in log
    assert 'Coverage: 100' in log
    assert PipelineState.is_verified(record, path)
