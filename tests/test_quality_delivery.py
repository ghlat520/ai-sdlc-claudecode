"""Actual supervisor checks over small, isolated mixed-language applications."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_pipeline_contract import executor_case, project_acceptance_case, function_map_case
from ai_sdlc_claudecode.state import PipelineState


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_text_heuristics_do_not_block_valid_javascript(tmp_path):
    (tmp_path/'node_modules').symlink_to(ROOT/'node_modules',target_is_directory=True)
    (tmp_path/'load.js').write_text('export const load = () => Promise.resolve({label: "value"});')
    result=subprocess.run(['bash',str(ROOT/'scripts/completeness-check.sh'),str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


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


@pytest.fixture
def pilot_project(tmp_path):
    """A runnable local reference application, not an autonomous-model benchmark."""
    app = tmp_path / 'backend'
    app.mkdir()
    (app / 'server.py').write_text('''import json, os, secrets, sqlite3, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
class Server(ThreadingHTTPServer):
    def __init__(self, database):
        super().__init__(('127.0.0.1', 0), Handler)
        self.database = str(database); self.sessions = set(); self.dropped = set(); self.lock = threading.Lock()
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, request_id TEXT UNIQUE, label TEXT, quantity INTEGER)')
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, status, data, cookie=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        if cookie: self.send_header('Set-Cookie', 'session=' + cookie + '; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers(); self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
        if self.path in ('/', '/client.js'):
            name = 'index.html' if self.path == '/' else 'dist/client.js'
            self.send_response(200); self.send_header('Content-Type','text/html' if self.path == '/' else 'application/javascript'); self.end_headers()
            self.wfile.write((Path(__file__).parent.parent / 'frontend' / name).read_bytes()); return
        if self.path != '/items': self.reply(404, {}); return
        if self.headers.get('Cookie', '').removeprefix('session=') not in self.server.sessions:
            self.reply(401, {'error':'authentication required'}); return
        with sqlite3.connect(self.server.database) as db:
            rows = db.execute('SELECT id, request_id, label, quantity FROM items ORDER BY id').fetchall()
        self.reply(200, {'items':[dict(zip(('id','request_id','label','quantity'),row)) for row in rows]})
    def do_POST(self):
        try: body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        except (ValueError, TypeError): self.reply(400, {'error':'invalid JSON'}); return
        if self.path == '/login':
            token = secrets.token_hex(16); self.server.sessions.add(token); self.reply(200, {'user':'reference-user'}, token); return
        if self.path != '/items': self.reply(404, {}); return
        if self.headers.get('Cookie', '').removeprefix('session=') not in self.server.sessions:
            self.reply(401, {'error':'authentication required'}); return
        if (not isinstance(body, dict) or not isinstance(body.get('request_id'), str) or not body['request_id']
            or not isinstance(body.get('label'), str) or not body['label'].strip()
            or type(body.get('quantity')) is not int or body['quantity'] <= 0):
            self.reply(422, {'error':'invalid input'}); return
        with sqlite3.connect(self.server.database, timeout=5) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id, label, quantity FROM items WHERE request_id=?', (body['request_id'],)).fetchone()
            status = 200 if row else 201
            if row and (row[1],row[2]) != (body['label'],body['quantity']):
                self.reply(409, {'error':'idempotency conflict'}); return
            if not row:
                cursor = db.execute('INSERT INTO items(request_id,label,quantity) VALUES(?,?,?)',
                                    (body['request_id'],body['label'],body['quantity']))
                row = (cursor.lastrowid, body['label'], body['quantity'])
            db.commit()
        if self.headers.get('X-Drop-Response') == 'true':
            with self.server.lock:
                if body['request_id'] not in self.server.dropped:
                    self.server.dropped.add(body['request_id']); self.close_connection = True; return
        delayed = self.headers.get('X-Delay-Response') == 'true'
        if delayed: time.sleep(0.15)
        try: self.reply(status, {'id':row[0], 'label':row[1], 'quantity':row[2]})
        except BrokenPipeError:
            if not delayed: raise
''')
    (tmp_path / 'api_checks.py').write_text('''import concurrent.futures, hashlib, http.client, json, os, random, socket, sqlite3, tempfile, threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from backend.server import Server
def request(server, path, body=None, token=None, drop=False, delay=False, timeout=5):
    headers = {'Content-Type':'application/json'}
    if token: headers['Cookie'] = token
    if drop: headers['X-Drop-Response'] = 'true'
    if delay: headers['X-Delay-Response'] = 'true'
    req = Request('http://127.0.0.1:%s%s' % (server.server_port,path),
                  data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as r: return r.status, json.load(r), r.headers.get('Set-Cookie')
    except HTTPError as r: return r.code, json.load(r), None
def checks():
    results = {}; seed = 271828
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory)/'items.sqlite'; server = Server(database)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            status, _, token = request(server,'/login',{}); token = token.split(';')[0]
            def count():
                with sqlite3.connect(database) as db: return db.execute('SELECT count(*) FROM items').fetchone()[0]
            def stored(key):
                with sqlite3.connect(database) as db:
                    row=db.execute('SELECT id,label,quantity FROM items WHERE request_id=?',(key,)).fetchone()
                return dict(zip(('id','label','quantity'),row)) if row else None
            payload = {'request_id':'first','label':'Notebook','quantity':1}
            def case(name, condition): results[name] = 'passed' if condition else 'failed'
            case('unauthorized', request(server,'/items',payload)[0] == 401 and count() == 0)
            case('invalid', all(request(server,'/items',dict(payload,quantity=q),token)[0] == 422 for q in (True,0,-1)) and count() == 0)
            first = request(server,'/items',payload,token); replay = request(server,'/items',payload,token)
            case('create_replay', first[0] == 201 and replay[0] == 200 and first[1] == replay[1] and count() == 1)
            case('conflict', request(server,'/items',dict(payload,quantity=2),token)[0] == 409 and count() == 1)
            concurrent_payload = dict(payload,request_id='concurrent')
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(lambda _:request(server,'/items',concurrent_payload,token),range(8)))
            case('concurrent', sum(r[0] == 201 for r in responses) == 1 and len({r[1]['id'] for r in responses}) == 1 and count() == 2)
            lost = dict(payload,request_id='lost'); dropped = False
            try: request(server,'/items',lost,token,True)
            except (http.client.RemoteDisconnected, URLError): dropped = True
            retry = request(server,'/items',lost,token)
            case('response_lost_retry', dropped and retry[0] == 200 and retry[1] == stored('lost') and count() == 3)
            timed = dict(payload,request_id='timed'); timed_out = False
            try: request(server,'/items',timed,token,delay=True,timeout=0.03)
            except socket.timeout: timed_out = True
            retry = request(server,'/items',timed,token)
            case('timeout_retry', timed_out and retry[0] == 200 and retry[1] == stored('timed') and count() == 4)
            expected = {'first','concurrent','lost','timed'}; rng = random.Random(seed)
            original_responses={}; sequence_valid=True
            for index in range(20):
                key = 'seq-' + str(rng.randrange(5)); expected.add(key); is_replay=key in original_responses
                status,response,_=request(server,'/items',dict(payload,request_id=key),token)
                sequence_valid = sequence_valid and status == (200 if is_replay else 201) and response == stored(key)
                if is_replay: sequence_valid = sequence_valid and response == original_responses[key]
                else: original_responses[key]=response
            with sqlite3.connect(database) as db: keys={row[0] for row in db.execute('SELECT request_id FROM items')}
            case('sequence', sequence_valid and keys == expected and count() == len(expected))
            visible = request(server,'/items',token=token)[1]['items']
            with sqlite3.connect(database) as db: stored = db.execute('SELECT id,request_id,label,quantity FROM items ORDER BY id').fetchall()
            case('persistence', [tuple(row[k] for k in ('id','request_id','label','quantity')) for row in visible] == stored)
            return {'checks':results,'seed':seed,'stored_rows':stored,'http_rows':visible,'run_id':os.environ.get('PIPELINE_RUN_ID'),'attempt_id':os.environ.get('PIPELINE_ATTEMPT_ID'),'source_manifest':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['backend/server.py','api_checks.py']}}
        finally: server.shutdown(); server.server_close(); thread.join()
if __name__ == '__main__':
    import os
    result = checks()
    destination = os.environ.get('API_RESULTS')
    if destination: Path(destination).write_text(json.dumps(result))
    print(json.dumps(result)); raise SystemExit(0 if all(s == 'passed' for s in result['checks'].values()) else 1)
''')
    return tmp_path


def test_failure_concurrency_and_retry_verify_sqlite(pilot_project):
    destination = pilot_project / 'actual-results.json'
    result = subprocess.run([sys.executable, 'api_checks.py'], cwd=pilot_project,
        env={**os.environ, 'API_RESULTS': str(destination)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(destination.read_text())
    assert set(report['checks']) == {'unauthorized','invalid','create_replay','conflict','concurrent','response_lost_retry','timeout_retry','sequence','persistence'}
    assert all(status == 'passed' for status in report['checks'].values())
    assert len(report['stored_rows']) == 9


def test_seeded_sequence_rejects_wrong_response_with_correct_storage(pilot_project):
    source=pilot_project/'backend/server.py'
    source.write_text(source.read_text().replace("try: self.reply(status, {'id':row[0]", "try: self.reply(status, {'id':row[0] + (1 if body['request_id'].startswith('seq-') else 0)"))
    destination=pilot_project/'actual-results.json'
    result=subprocess.run([sys.executable,'api_checks.py'],cwd=pilot_project,env={**os.environ,'API_RESULTS':str(destination)},capture_output=True,text=True,timeout=30)
    assert result.returncode==1,result.stdout+result.stderr
    report=json.loads(destination.read_text())
    assert report['checks']['sequence']=='failed'
    assert report['checks']['persistence']=='passed'
    assert len(report['stored_rows'])==9


@pytest.fixture
def browser_project(pilot_project):
    project = pilot_project
    front = project / 'frontend'; front.mkdir()
    (project / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    (front / 'index.html').write_text('''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<html lang="en"><title>Quality reference</title><main><h1>Reference notebook</h1>
<button id="login">Sign in</button><button id="save" disabled>Save notebook</button>
<p role="status" id="status">Signed out</p><p id="count">0 stored</p></main><script src="/client.js"></script></html>''')
    (front / 'client.ts').write_text('''let signedIn = false;
const statusNode = document.getElementById('status')!;
const save = document.getElementById('save') as HTMLButtonElement;
const key = sessionStorage.getItem('request') || crypto.randomUUID(); sessionStorage.setItem('request',key);
async function refresh() {
  const response = await fetch('/items'); if (!response.ok) return;
  const value = await response.json(); document.getElementById('count')!.textContent = value.items.length + ' stored';
}
document.getElementById('login')!.onclick = async () => {
  const response = await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if (response.ok) { signedIn = true; save.disabled = false; statusNode.textContent = 'Signed in'; await refresh(); }
};
save.onclick = async () => {
  if (!signedIn) return; save.disabled = true; statusNode.textContent = 'Saving';
  try {
    const response = await fetch('/items',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({request_id:key,label:'Notebook',quantity:1})});
    if (!response.ok) throw new Error('save failed');
    statusNode.textContent = 'Saved'; await refresh();
  } catch { statusNode.textContent = 'Save failed; retry'; }
  finally { save.disabled = false; }
};
''')
    (project / 'browser.cjs').write_text('''const {chromium} = require('playwright-core');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const assert = require('node:assert/strict');
(async () => {
 const root = process.env.BROWSER_EVIDENCE; fs.mkdirSync(root,{recursive:true});
 const target = process.env.BROWSER_TARGET;
 const viewport = JSON.parse(process.env.BROWSER_VIEWPORT);
 const browser = await chromium.launch({channel:'chrome',headless:true});
 const context = await browser.newContext({viewport,isMobile:target === 'h5-browser-emulation',hasTouch:target === 'h5-browser-emulation'});
 await context.tracing.start({screenshots:true,snapshots:true,sources:true});
 const page = await context.newPage(), requests = [], steps = [], errors = [];
 page.on('request',r => requests.push({method:r.method(),url:r.url()}));
 page.on('pageerror',e => errors.push(e.message));
 const step = action => steps.push({action,status:'passed'});
 try {
  await page.goto(process.env.BROWSER_URL); await page.getByRole('heading',{name:'Reference notebook'}).waitFor(); step('open app');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Signed in'}).waitFor(); step('sign in with server session');
  let failed = false;
  await page.route('**/items',route => { if(route.request().method()==='POST' && !failed) {failed=true; return route.abort();} return route.continue(); });
  await page.getByRole('button',{name:'Save notebook',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Save failed; retry'}).waitFor(); step('observe network failure and retry feedback');
  const started = performance.now();
  await page.getByRole('button',{name:'Save notebook',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Saved'}).waitFor();
  await page.locator('#count').filter({hasText:'1 stored'}).waitFor(); step('retry same request and observe durable result');
  const create_elapsed_ms = performance.now()-started;
  const response = await context.request.get(process.env.BROWSER_URL+'/items'); assert.equal(response.status(),200);
  const data = await response.json(); assert.equal(data.items.length,1); assert.equal(data.items[0].label,'Notebook'); step('read back API state');
  assert.deepEqual(errors,[]);
  const files = {trace:path.join(root,'trace.zip'),screenshot:path.join(root,'page.png'),requests:path.join(root,'requests.json'),data:path.join(root,'data.json')};
  await page.screenshot({path:files.screenshot,fullPage:true});
  fs.writeFileSync(files.requests,JSON.stringify(requests)); fs.writeFileSync(files.data,JSON.stringify(data));
  await context.tracing.stop({path:files.trace});
  const evidence = Object.fromEntries(Object.entries(files).map(([key,file])=>[key,{path:file,sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')} ]));
  const observed = {run_id:process.env.PIPELINE_RUN_ID,attempt_id:process.env.PIPELINE_ATTEMPT_ID,
    candidate_sha256:process.env.PIPELINE_CANDIDATE_SHA256,target,
    identity:{browser:'chromium',version:browser.version(),viewport,is_mobile:target==='h5-browser-emulation'},steps,evidence,metrics:{create_elapsed_ms}};
  fs.writeFileSync(path.join(root,'journey.json'),JSON.stringify(observed));
 } finally {await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
''')
    (project / 'browser_checks.py').write_text('''import hashlib, json, os, sqlite3, subprocess, tempfile, threading
from pathlib import Path
from backend.server import Server
report_path = Path(os.environ['PIPELINE_ACCEPTANCE_REPORT']); checks = {}; journeys = {}
for name,target,viewport in [('pc_web','pc-web',{'width':1280,'height':800}),('h5','h5-browser-emulation',{'width':390,'height':844})]:
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp)/'items.sqlite'; server = Server(database)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        evidence = report_path.parent/name
        try:
            result = subprocess.run(['node','browser.cjs'],env={**os.environ,'BROWSER_URL':'http://127.0.0.1:'+str(server.server_port),
                'BROWSER_TARGET':target,'BROWSER_VIEWPORT':json.dumps(viewport),'BROWSER_EVIDENCE':str(evidence)},timeout=30)
            if result.returncode: raise SystemExit(result.returncode)
            observed = json.loads((evidence/'journey.json').read_text())
            with sqlite3.connect(database) as db: rows = db.execute('SELECT label,quantity FROM items').fetchall()
            if rows != [('Notebook',1)]: raise SystemExit('Browser state and SQLite differ')
            data = evidence/'data.json'; value=json.loads(data.read_text()); value['sqlite_rows']=rows; data.write_text(json.dumps(value))
            observed['evidence']['data']['sha256'] = hashlib.sha256(data.read_bytes()).hexdigest()
            checks[name] = {'login_retry_persistence':'passed'}; journeys[name] = observed
        finally: server.shutdown(); server.server_close(); thread.join()
report_path.write_text(json.dumps({'run_id':os.environ['PIPELINE_RUN_ID'],'attempt_id':os.environ['PIPELINE_ATTEMPT_ID'],
    'checks':checks,'findings':{},'journeys':journeys}))
''')
    compiled = subprocess.run(['node', str(ROOT/'node_modules/typescript/bin/tsc'), 'client.ts','--outDir','dist','--lib','es2020,dom','--strict','--skipLibCheck'],
        cwd=front, capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return project


def test_real_pc_and_h5_journeys_bind_artifacts(browser_project):
    from ai_sdlc_claudecode.acceptance import digest, fingerprint
    from ai_sdlc_claudecode.verification import validate_journey
    project = browser_project; archive = project/'.artifacts/journey-attempt'; archive.mkdir(parents=True)
    report = archive/'acceptance.json'
    candidate = digest(fingerprint(project,['backend/server.py','frontend','browser.cjs','browser_checks.py']))
    env = {**os.environ,'PIPELINE_RUN_ID':'browser-run','PIPELINE_ATTEMPT_ID':'browser-attempt',
           'PIPELINE_CANDIDATE_SHA256':candidate,'PIPELINE_ACCEPTANCE_REPORT':str(report)}
    result = subprocess.run([sys.executable,'browser_checks.py'],cwd=project,env=env,capture_output=True,text=True,timeout=70)
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(report.read_text())
    binding = dict(run_id='browser-run',attempt_id='browser-attempt',candidate_sha256=candidate,report_path=str(report))
    for name,target in [('pc_web','pc-web'),('h5','h5-browser-emulation')]:
        spec = {'target':target,'identity':{'browser':'chromium','is_mobile':name=='h5'},'min_steps':5}
        assert validate_journey(observed['journeys'][name], spec, binding)
    assert observed['journeys']['pc_web']['identity']['viewport']['width'] == 1280
    assert observed['journeys']['h5']['identity']['viewport']['width'] == 390
    from copy import deepcopy
    for change in ('skip', 'zero', 'wrong_target', 'wrong_candidate', 'stale_artifact'):
        altered = deepcopy(observed['journeys']['pc_web'])
        if change == 'skip': altered['steps'][0]['status'] = 'skipped'
        elif change == 'zero': altered['steps'] = []
        elif change == 'wrong_target': altered['target'] = 'native-ios'
        elif change == 'wrong_candidate': altered['candidate_sha256'] = 'old'
        else: altered['evidence']['data']['sha256'] = 'old'
        with pytest.raises((ValueError, OSError)):
            validate_journey(altered, {'target':'pc-web','identity':{'browser':'chromium'},'min_steps':5}, binding)


def mutation_configuration():
    return {'inputs':['backend/server.py','api_checks.py'], 'mutable_inputs':['backend/server.py'], 'test_inputs':['api_checks.py'], 'command':'python3 api_checks.py',
        'validate_command':'''python3 -c "compile(open('backend/server.py').read(), 'backend/server.py', 'exec')"''',
        'result_file':'actual-mutation.json','result_env':'API_RESULTS',
        'cases':['unauthorized','invalid','create_replay','conflict','concurrent','response_lost_retry','timeout_retry','sequence','persistence'],
        'timeout_seconds':20, 'mutants':[
            {'id':'AUTH-REMOVED','critical':True,'reason':'Unauthenticated writes become possible', 'changes':[
                {'path':'backend/server.py','old':"        if self.path != '/items': self.reply(404, {}); return\n        if self.headers.get('Cookie', '').removeprefix('session=') not in self.server.sessions:\n            self.reply(401, {'error':'authentication required'}); return\n        if (",
                 'new':"        if self.path != '/items': self.reply(404, {}); return\n        if False:\n            self.reply(401, {'error':'authentication required'}); return\n        if ("}]},
            {'id':'INVALID-BOUNDARY','critical':True,'reason':'Zero quantity becomes accepted','changes':[
                {'path':'backend/server.py','old':"body['quantity'] <= 0",'new':"body['quantity'] < 0"}]},
            {'id':'IDEMPOTENCY-REMOVED','critical':True,'reason':'Replaying the same request creates extra rows','changes':[
                {'path':'backend/server.py','old':'request_id TEXT UNIQUE','new':'request_id TEXT'},
                {'path':'backend/server.py','old':'WHERE request_id=?', 'new':'WHERE request_id=? AND 0'}]},
            {'id':'LOST-WRITE','critical':True,'reason':'HTTP claims a result that never persists','changes':[
                {'path':'backend/server.py','old':'            db.commit()','new':'            db.rollback()'}]},
        ]}


def test_key_business_mutants_are_killed_by_actual_assertions(pilot_project):
    from ai_sdlc_claudecode.verification import run_mutations
    archive = pilot_project/'.artifacts/mutations'; archive.mkdir(parents=True)
    config = mutation_configuration()
    result = run_mutations(config,pilot_project,archive)
    assert result['baseline']['status'] == 'survived', result
    assert result['status'] == 'passed', result
    assert {m['id']:m['status'] for m in result['mutants']} == {
        'AUTH-REMOVED':'killed','INVALID-BOUNDARY':'killed','IDEMPOTENCY-REMOVED':'killed','LOST-WRITE':'killed'}


@pytest.mark.parametrize('replacement,expected', [('return 7','survived'),('return (','invalid_mutation'),
                                                ('raise RuntimeError("tool failure")','execution_error'),
                                                ('__import__("time").sleep(3); return 7','timeout')])
def test_mutation_tool_failures_do_not_count_as_kills(tmp_path,replacement,expected):
    from ai_sdlc_claudecode.verification import run_mutations
    (tmp_path/'value.py').write_text('def value():\n    return 7\n')
    (tmp_path/'check.py').write_text('''import json,os
from pathlib import Path
from value import value
ok = value() == 7
Path(os.environ['MUTATION_RESULT']).write_text(json.dumps({'checks':{'value':'passed' if ok else 'failed'}}))
raise SystemExit(0 if ok else 1)
''')
    config = {'inputs':['value.py','check.py'],'mutable_inputs':['value.py'],'test_inputs':['check.py'],'command':'python3 check.py',
        'validate_command':'''python3 -c "compile(open('value.py').read(),'value.py','exec')"''',
        'result_file':'result.json','result_env':'MUTATION_RESULT','cases':['value'],'timeout_seconds':1,
        'mutants':[{'id':'one','critical':True,'reason':'Deliberate control for classifier',
                    'changes':[{'path':'value.py','old':'return 7','new':replacement}]}]}
    result = run_mutations(config,tmp_path,tmp_path/'.artifacts')
    assert result['mutants'][0]['status'] == expected
    assert result['status'] == 'failed'
    if expected=='survived':
        config['mutants'][0]['changes']=[{'path':'check.py','old':'value() == 7','new':'value() == 8'}]
        with pytest.raises(ValueError,match='tests/expectations are frozen'):
            run_mutations(config,tmp_path,tmp_path/'.artifacts/frozen')
        config.update(mutable_inputs=['value.py','check.py'],test_inputs=['./check.py'])
        with pytest.raises(ValueError,match='tests/expectations are frozen'):
            run_mutations(config,tmp_path,tmp_path/'.artifacts/alias')


@pytest.fixture
def full_delivery_case(function_map_case, browser_project):
    dag,path,env,run,project,old_driver,requirements = function_map_case
    (project/'jvm').mkdir()
    (project/'jvm/Value.java').write_text('public class Value { public static void main(String[] args) { if (Math.max(0,42) != 42) throw new AssertionError(); } }')
    (project/'wire_probe.py').write_text('''import json,tempfile,threading
from pathlib import Path
from api_checks import request,Server
with tempfile.TemporaryDirectory() as temp:
 server=Server(Path(temp)/'items.sqlite'); thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  _,_,token=request(server,'/login',{});token=token.split(';')[0]
  body={'request_id':'wire','label':'Notebook','quantity':1};status,response,_=request(server,'/items',body,token)
  print(json.dumps({'method':'POST','path':'/items','status':status,'request':body,'response':response}))
 finally: server.shutdown();server.server_close();thread.join()
''')
    (project/'final_acceptance.py').write_text('''import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path.cwd(); state=json.loads((Path(os.environ['PIPELINE_ROOT'])/'fixture/state.json').read_text())
stage=state['stages']['S4c']; mutations=stage['mutation_checks']
for name,expected in mutations['source_binding']['manifest'].items():
 if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected: raise SystemExit('Stale mutation candidate')
api=json.loads((root/'.artifacts/api-results.json').read_text())
if api['run_id']!=os.environ['PIPELINE_RUN_ID'] or api['attempt_id']!=stage['attempt_id']: raise SystemExit('Stale API attempt')
for name,expected in api['source_manifest'].items():
 if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected: raise SystemExit('Stale API candidate')
result=subprocess.run([sys.executable,'browser_checks.py'])
if result.returncode: raise SystemExit(result.returncode)
path=Path(os.environ['PIPELINE_ACCEPTANCE_REPORT']);report=json.loads(path.read_text())
report['checks']['api']=api['checks']
report['checks']['mutations']={m['id']:'passed' if m['status']=='killed' else 'failed' for m in mutations['mutants']}
report['evidence_sources']={'api':str(root/'.artifacts/api-results.json'),'mutations':str(Path(stage['archive'])/'mutations.json')}
path.write_text(json.dumps(report))
''')
    contracts={'services':[{'name':name,'language':language,'port':port,'responsibility':'Reference module for bounded quality verification'}
        for name,language,port in [('backend','python',8081),('frontend','typescript',8082),('jvm','java',8083)]],
        'api_endpoints':[{'service':'backend','method':'POST','path':'/items',
          'request_fields':[{'name':key,'type':kind} for key,kind in [('request_id','string'),('label','string'),('quantity','integer')]],
          'response_fields':[{'name':key,'type':kind} for key,kind in [('id','integer'),('label','string'),('quantity','integer')]]}],
        'cross_service_messages':[],'encryption_pairs':[],'shared_models':[],
        'external_refs':{'ai_models':[],'npm_packages_forbidden':[]},
        'quality_rules':[{'id':'ARCH-RENDERER','kind':'imports','language':'typescript','paths':['frontend'],
            'exclude':[],'forbidden':['backend/*','demo/*'],'source':'FR-1 reference architecture',
            'message':'The renderer may not import backend or demonstration providers'},
          {'id':'API-FIELDS','kind':'wire','paths':['backend/server.py','wire_probe.py','api_checks.py'],
            'endpoint':{'service':'backend','method':'POST','path':'/items'},'command':'python3 wire_probe.py',
            'source':'AC-1 observable wire contract','message':'HTTP JSON fields and types match S2'}]}
    names=[('requirements','S1'),('architecture','S2'),('backend','S3'),('frontend','S3b'),
           ('unit','S4'),('integration','S4b'),('e2e','S4c'),('browser','S4e')]
    template=dict(dag['stages']['second']); stages={}; outputs={}
    for index,(name,sid) in enumerate(names):
        stages[name]={**template,'id':sid,'dependencies':[names[index-1][0]] if index else [],
            'agents':[{'type':'local-fixture','model':'haiku','prompt_template':'FAKE_STAGE:'+sid}], 'post_commands':['true']}
        outputs[sid]={'stage_id':sid,'status':'complete','summary':'Reference artifact; actual supervisor checks decide acceptance',
            'implementation':{'compile_result':{'success':True},'build_result':{'success':True}},
            'testing':{'test_results':{'failed':0},'coverage':{'line_percent':100}}}
    stages['requirements']['output_schema']=str(ROOT/'schemas/requirements-output.json')
    stages['architecture']['output_schema']=str(ROOT/'schemas/architecture-output.json')
    outputs['S2']={'stage_id':'S2','feature_id':'fixture','timestamp':'2026-11-18T00:00:00Z','status':'complete','summary':'Reference architecture',
        'architecture':{'affected_modules':[{'module_name':'backend','change_type':'new','description':'Reference API'}],
                        'api_contracts':[],'data_model':{'tables':[]},'sequence_flows':[{'name':'create','steps':[]}]},'contracts':contracts}
    dag['stages']=stages;dag['execution_order']=[{'stage':name,'mode':'sequential'} for name,_ in names]
    dag['config']['tech_stack_commands']={'python':{'compile':'''python3 -c "compile(open('backend/server.py').read(),'backend/server.py','exec')"''',
        'test':'mkdir -p .artifacts && API_RESULTS=.artifacts/api-results.json python3 api_checks.py',
        'coverage':'mkdir -p .artifacts && API_RESULTS=.artifacts/api-results.json python3 -m coverage run --source=backend api_checks.py && python3 -m coverage report'},
        'java-maven':{'compile':'javac -d classes Value.java && jar --create --file value.jar -C classes .','test':'java -cp classes Value'},
        'node-typescript':{'compile':'node ../node_modules/typescript/bin/tsc client.ts --outDir dist --lib es2020,dom --strict --skipLibCheck'}}
    dag['config']['modules']={
        'backend':{'path':'.','tech_stack':'python','inputs':['backend/server.py','api_checks.py'],'artifacts':[]},
        'jvm':{'path':'jvm','tech_stack':'java-maven','inputs':['Value.java'],'artifacts':['classes/Value.class','value.jar']},
        'frontend':{'path':'frontend','tech_stack':'node-typescript','inputs':['client.ts','index.html'],'artifacts':['dist/client.js']}}
    stages['backend']['module_checks']={'backend':['compile'],'jvm':['compile','test']}
    stages['frontend']['module_checks']={'frontend':['compile']}
    for name in ('unit','integration','e2e'): stages[name]['module_checks']={'backend':['test','coverage']}
    stages['e2e']['mutation_checks']=mutation_configuration()
    cases={'api':mutation_configuration()['cases'],'mutations':[m['id'] for m in mutation_configuration()['mutants']],
           'pc_web':['login_retry_persistence'],'h5':['login_retry_persistence']}
    stages['browser']['post_commands']=['python3 final_acceptance.py']
    definition=dag['config']['project_acceptance']
    definition.update(scope='local-quality-reference',stage_id='S4e',candidate_inputs=[
        'backend/server.py','jvm','frontend/client.ts','frontend/index.html','frontend/dist/client.js',
        'api_checks.py','browser.cjs','browser_checks.py','wire_probe.py','final_acceptance.py'],required_checks=cases)
    definition['journeys']={name:{'target':target,'identity':{'browser':'chromium','is_mobile':name=='h5'},'min_steps':5}
        for name,target in [('pc_web','pc-web'),('h5','h5-browser-emulation')]}
    value=json.loads(requirements.read_text()); sample=value['function_map']['behaviors'][0]; value['function_map']['behaviors']=[]; value['prd']['acceptance_criteria']=[]
    value['prd']['functional_requirements'].append({'id':'FR-2','priority':'must','description':'Critical production mistakes are detected without changing the original candidate or tests'})
    scenarios={
        'unauthorized':('No session; empty isolated store','0 rows','POST without a session','0 rows','No write','HTTP 401; sign in before retry'),
        'invalid':('Authenticated; empty isolated store','0 rows','POST boolean, zero or negative quantity','0 rows','No write','HTTP 422; correct input before retry'),
        'create_replay':('Authenticated; empty isolated store','0 rows','POST twice with the same request ID','1 row','One durable item','HTTP 201 then 200 with identical item'),
        'conflict':('Authenticated; request ID already stored','1 row','Reuse the ID with a different quantity','1 unchanged row','No second write','HTTP 409; use a new request for a new intent'),
        'concurrent':('Authenticated; a fresh request ID','1 existing row','8 simultaneous POSTs for one new ID','2 rows total','One new item for that ID','Exactly one 201; every caller sees the same item ID'),
        'response_lost_retry':('Authenticated; response is dropped after commit','2 rows','Retry after losing the committed response','3 rows total','Exactly one additional item','Connection closes; retry returns the stored item with 200'),
        'timeout_retry':('Authenticated; server delays its response after commit','3 rows','Client times out and retries the same ID','4 rows total','Exactly one additional item','Timeout followed by HTTP 200 and the stored item'),
        'sequence':('Authenticated; four IDs are already stored; seed 271828','4 rows','20 seeded operations over five additional IDs','9 distinct rows','One row per distinct accepted ID','Every replay returns its original item'),
        'persistence':('Authenticated; seeded sequence finished','9 SQLite rows','GET items and read SQLite through a fresh connection','Same 9 rows','No write','HTTP rows equal stored IDs, labels and quantities'),
    }
    for index,(check,case) in enumerate((check,case) for check,values in cases.items() for case in values):
        ac='AC-'+str(index+1); value['prd']['acceptance_criteria'].append({'id':ac,'given':'Isolated reference project','when':case,'then':'Agreed invariant holds'})
        if check=='api':
            before_condition,before,event,after,change,feedback=scenarios[case]
            details=dict(role='API caller',preconditions=before_condition,state_before=before,event=event,state_after=after,
                data_changes=change,feedback=feedback,failure_retry=feedback,expected=feedback+'; '+after)
        elif check=='mutations':
            details=dict(role='Verification engineer',preconditions='Original candidate passes; tests and expected values frozen',
                state_before='Original source and test hashes recorded',event='Change production behavior in an isolated copy: '+case,
                state_after='Original unchanged; critical mutant rejected by the same target assertions',data_changes='Only disposable mutant data',
                failure_retry='Invalid mutation, tool error or timeout cannot count as killed',feedback='Report killed with failed target case and assertion exit 1',expected='Valid critical mutant is killed by unchanged tests')
        else:
            details=dict(role='Signed-in user',preconditions='Fresh browser context and isolated SQLite store on '+check,
                state_before='Signed out; 0 rows',event='Sign in, save during network failure, then retry',state_after='Saved; 1 row',
                data_changes='Exactly one Notebook item',failure_retry='Show retry feedback; retain request identity',
                feedback='Signed in → Save failed; retry → Saved / 1 stored',expected='Page, HTTP response and SQLite agree on one item')
        value['prd']['acceptance_criteria'][-1].update(given=details['preconditions'],when=details['event'],then=details['expected'])
        value['function_map']['behaviors'].append(dict(sample,**details,id='B-'+str(index+1),acceptance_id=ac,
            requirement_id='FR-2' if check=='mutations' else 'FR-1',check_id=check,case_id=case,
            target='frontend' if check in ('pc_web','h5') else 'backend/server.py',command='python3 final_acceptance.py'))
    outputs['S1']=value; requirements.write_text(json.dumps(value))
    artifacts=project/'fixture-artifacts.json';artifacts.write_text(json.dumps(outputs))
    fake=Path(env['PATH'].split(os.pathsep)[0])/'claude';text=fake.read_text();needle="with open(os.environ['FAKE_CALLS'], 'a') as log:"
    text=text.replace(needle,f"if stage != 'S1':\n    print(json.dumps(json.load(open({str(artifacts)!r}))[stage]));sys.exit(0)\n"+needle);fake.write_text(text)
    dag['config']['quality_tracking']={'sample_kind':'framework_fixture','technology':['java','typescript','python'],
        'risk':'low','task_size':'small','observation_window':'frozen-local-reference-v1','tool_version':'quality-t4-t9-v1'}
    return dag,path,env,run,project,requirements


def test_same_candidate_full_delivery_chain(full_delivery_case):
    dag,path,env,run,project,requirements=full_delivery_case
    result,data=run()
    assert result.returncode==0,result.stdout+result.stderr
    state=PipelineState(Path(env['PIPELINE_ROOT'])/'fixture/state.json')
    report=state.project_acceptance()
    assert report['status']=='passed',report
    assert report['required_cases']==15 and report['passed_cases']==15
    assert set(data['stages'])=={'S1','S2','S3','S3b','S4','S4b','S4c','S4e'}
    assert len(data['stages']['S4c']['mutation_checks']['mutants'])==4
    assert state.summary()['execution_outcome']=='complete'
    from ai_sdlc_claudecode.quality import build_report
    quality=build_report([state.path])
    assert quality['tasks'][0]['first_candidate_status']=='passed'
    assert quality['tasks'][0]['contexts'][0]['sample_kind']=='framework_fixture'
    for relative in ('backend/server.py','jvm/value.jar','frontend/dist/client.js'):
        target=project/relative; previous=target.read_bytes(); target.write_bytes(previous+b'\nchanged')
        assert state.project_acceptance()['status']=='incomplete'
        target.write_bytes(previous)
    assert state.project_acceptance()['status']=='passed'
    original=json.loads(path.read_text());altered=json.loads(path.read_text());altered['config']['context_budget_tokens']+=1
    path.write_text(json.dumps(altered));assert state.project_acceptance()['status']=='incomplete'
    path.write_text(json.dumps(original))


@pytest.mark.parametrize('variant', ['input_boundary','forbidden_import','missing_case','skipped_case','zero_journey','wrong_terminal','missing_trace','stale_run','open_blocker'])
def test_full_delivery_rejects_bad_candidates(full_delivery_case,variant):
    dag,path,env,run,project,requirements=full_delivery_case
    if variant=='input_boundary':
        source=project/'backend/server.py';source.write_text(source.read_text().replace("body['quantity'] <= 0","body['quantity'] < 0"))
    elif variant=='forbidden_import':
        source=project/'frontend/client.ts';source.write_text('import {fake} from "demo/provider";\n'+source.read_text())
    else:
        source=project/'final_acceptance.py'
        change={'missing_case':"del report['checks']['api']['persistence']",'skipped_case':"report['checks']['api']['persistence']='skipped'",
            'zero_journey':"report['journeys']['pc_web']['steps']=[]",'wrong_terminal':"report['journeys']['h5']['target']='native-ios'",
            'missing_trace':"del report['journeys']['pc_web']['evidence']['trace']",'stale_run':"report['run_id']='old-run'",
            'open_blocker':"report['findings']={'REGRESSION-1':{'status':'open','blocking':True,'checks':['api']}}"}[variant]
        source.write_text(source.read_text()+"\n"+change+"\npath.write_text(json.dumps(report))\n")
    result,data=run()
    assert result.returncode!=0,result.stdout+result.stderr
    state=PipelineState(Path(env['PIPELINE_ROOT'])/'fixture/state.json')
    assert state.project_acceptance()['status']!='passed'
    if variant=='forbidden_import':
        assert data['stages']['S3']['status'] in ('failed','dead_letter')
        assert 'S3b' not in data['stages']
