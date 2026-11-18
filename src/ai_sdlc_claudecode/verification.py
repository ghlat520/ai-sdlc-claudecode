"""Execute declared module checks using each target's existing toolchain.

Commands and paths are trusted project configuration. This is evidence collection,
not process isolation or an authorization service.
"""

import argparse
from contextlib import suppress
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from .acceptance import REVIEW_COMMAND, REVIEW_REPORT, _names, fingerprint


TOOL_ROOT = Path(__file__).resolve().parents[2]


def run_bounded(command_text, directory, timeout, env=None, stream=None):
    process = subprocess.Popen(command_text, cwd=directory, shell=True, executable='/bin/bash',
        env=env, stdout=stream if stream is not None else subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
    except BaseException:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            process.communicate(timeout=2)
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    return subprocess.CompletedProcess(command_text, process.returncode, output)


def validate_mutations(config):
    if (not isinstance(config, dict) or set(config) - {'inputs', 'mutable_inputs', 'test_inputs', 'command', 'validate_command', 'result_file', 'result_env', 'cases', 'mutants', 'timeout_seconds'}):
        raise ValueError('Invalid mutation configuration')
    _names(config.get('inputs'), 'mutation.inputs'); _names(config.get('cases'), 'mutation.cases')
    _names(config.get('mutable_inputs'), 'mutation.mutable_inputs'); _names(config.get('test_inputs'), 'mutation.test_inputs')
    for name in [*config['inputs'], *config['mutable_inputs'], *config['test_inputs']]:
        relative(name)
    relative(config.get('result_file'))
    for name in ('command', 'validate_command', 'result_env'):
        if not isinstance(config.get(name), str) or not config[name].strip():
            raise ValueError(f'Mutation testing requires {name}')
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*', config['result_env']) or config['result_env'] in ('HOME', 'PATH', 'PYTHONPATH', 'CODEX_HOME'):
        raise ValueError('Invalid mutation result environment variable')
    if type(config.get('timeout_seconds')) not in (int, float) or not 0 < config['timeout_seconds'] <= 120:
        raise ValueError('Mutation timeout must be positive and at most 120 seconds')
    mutants = config.get('mutants')
    if not isinstance(mutants, list) or not 1 <= len(mutants) <= 16:
        raise ValueError('Declare one to sixteen bounded mutants')
    _names([m.get('id') for m in mutants], 'mutation IDs')
    for mutant in mutants:
        if type(mutant.get('critical')) is not bool or not isinstance(mutant.get('reason'), str) or not mutant['reason'].strip():
            raise ValueError('Mutation requires critical flag and independently reviewable non-equivalence reason')
        if mutant.get('classification', 'non_equivalent') not in ('non_equivalent', 'equivalent'):
            raise ValueError('Unknown mutation equivalence classification')
        if mutant.get('classification') == 'equivalent' and mutant['critical']:
            raise ValueError('Critical mutants must be confirmed non-equivalent')
        changes = mutant.get('changes')
        if not isinstance(changes, list) or not changes:
            raise ValueError('Mutation requires changes')
        for change in changes:
            relative(change.get('path'))
            path = Path(change['path']).as_posix()
            matches = lambda selected: any(path == Path(name).as_posix() or path.startswith(Path(name).as_posix().rstrip('/') + '/') for name in selected)
            if not matches(config['mutable_inputs']) or matches(config['test_inputs']):
                raise ValueError('Mutations may change only declared production inputs; tests/expectations are frozen')
            if any(not isinstance(change.get(k), str) or not change[k] for k in ('old', 'new')):
                raise ValueError('Mutation replacements must be nonempty strings')


def run_mutations(config, project, archive):
    """A nonzero command is a kill only when valid target assertions actually fail."""
    validate_mutations(config)
    archive = Path(archive).resolve(); root = Path(project).resolve(strict=True)
    before = fingerprint(root, config['inputs'])
    frozen = fingerprint(root, config['test_inputs'])
    original = dict(project_dir=str(root), paths=config['inputs'], manifest=before)
    for name in config['inputs']:
        source = inside(root, name)
        if source.is_dir() and source in archive.resolve().parents:
            raise ValueError('Mutation archive must be outside its selected input directories')

    def execute_copy(name, changes):
        directory = archive / name
        directory.mkdir(parents=True, exist_ok=False)
        for input_name in config['inputs']:
            source = inside(root, input_name); destination = directory / input_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, ignore=shutil.ignore_patterns('node_modules', '.git', '.artifacts', '__pycache__', '*.pyc'))
            else: shutil.copy2(source, destination)
        for change in changes:
            destination = inside(directory, change['path']); text = destination.read_text()
            if text.count(change['old']) != 1:
                return dict(status='invalid_mutation', reason='Replacement does not match exactly once')
            destination.write_text(text.replace(change['old'], change['new'], 1))
        result_file = directory / config['result_file']
        if fingerprint(directory, config['test_inputs']) != frozen:
            return dict(status='invalid_mutation', reason='Frozen tests/expectations changed')
        result_file.unlink(missing_ok=True)
        env = dict(os.environ, **{config['result_env']: str(result_file)})
        for phase, value in [('validation', config['validate_command']), ('assertions', config['command'])]:
            log = archive / (name + '-' + phase + '.log')
            try:
                with log.open('w') as stream:
                    command_result = run_bounded(value, directory, config['timeout_seconds'], env, stream)
            except subprocess.TimeoutExpired:
                return dict(status='timeout', phase=phase, log=str(log))
            code = command_result.returncode
            if fingerprint(directory, config['test_inputs']) != frozen:
                return dict(status='execution_error', reason='Frozen tests/expectations changed', log=str(log))
            if phase == 'validation':
                if code: return dict(status='invalid_mutation', log=str(log), exit_code=code)
                continue
            try:
                from .acceptance import _unique_object
                observed = json.loads(result_file.read_text(), object_pairs_hook=_unique_object)['checks']
                if (not isinstance(observed, dict) or not set(config['cases']) <= set(observed)
                        or any(s not in ('passed', 'failed') for s in observed.values())):
                    raise ValueError('Missing, skipped or erroneous mutation assertions')
                failed = any(observed[name] == 'failed' for name in config['cases'])
                if code not in (0, 1):
                    raise ValueError('Only an assertion-failure exit (1) can kill a mutation')
                if (code == 0) == failed:
                    raise ValueError('Assertion status and command exit disagree')
                return dict(status='killed' if failed else 'survived', checks=observed,
                            exit_code=code, result_path=str(result_file), log=str(log))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return dict(status='execution_error', reason=str(exc), exit_code=code, log=str(log))

    baseline = execute_copy('baseline', [])
    result = dict(run_id=os.environ.get('PIPELINE_RUN_ID'), attempt_id=os.environ.get('PIPELINE_ATTEMPT_ID'),
                  source_binding=original, baseline=baseline, mutants=[], status='failed')
    if baseline['status'] == 'survived':
        for index, mutant in enumerate(config['mutants']):
            if mutant.get('classification') == 'equivalent':
                observed = dict(status='equivalent_declared', reason=mutant['reason'])
            else:
                observed = execute_copy(f'mutant-{index}', mutant['changes'])
            result['mutants'].append(dict(id=mutant['id'], critical=mutant['critical'], **observed))
        result['status'] = 'passed' if all(
            m['status'] == 'killed' if m['critical'] else m['status'] in ('killed', 'survived', 'equivalent_declared')
            for m in result['mutants']) else 'failed'
    else:
        result['reason'] = 'Original candidate did not pass its assertions; mutation evidence unavailable'
    if fingerprint(root, config['inputs']) != before:
        result.update(status='failed', reason='Original candidate changed during mutation testing')
    return result


def validate_journey(observed, expected, binding):
    if not isinstance(observed, dict):
        raise ValueError('Missing required terminal journey')
    if any(observed.get(key) != binding.get(key) for key in ('run_id', 'attempt_id', 'candidate_sha256')):
        raise ValueError('Journey evidence belongs to a different execution/candidate')
    if observed.get('target') != expected['target']:
        raise ValueError('Journey evidence is from another terminal target')
    if not isinstance(observed.get('identity'), dict) or any(observed['identity'].get(k) != v for k, v in expected['identity'].items()):
        raise ValueError('Journey runtime/device identity does not match the declared target')
    steps = observed.get('steps')
    if (not isinstance(steps, list) or len(steps) < expected['min_steps']
            or any(not isinstance(step, dict) or not isinstance(step.get('action'), str) or not step['action'].strip()
                   or step.get('status') != 'passed' for step in steps)):
        raise ValueError('Required journey has missing, failed or skipped steps')
    archive = Path(binding['report_path']).parent.resolve(strict=True)
    evidence = observed.get('evidence')
    if not isinstance(evidence, dict):
        raise ValueError('Missing terminal journey artifact map')
    for kind in ('trace', 'screenshot', 'requests', 'data'):
        artifact = evidence.get(kind, {})
        if not isinstance(artifact, dict):
            raise ValueError(f'Invalid journey artifact: {kind}')
        path = Path(artifact.get('path', ''))
        if path.is_symlink():
            raise ValueError('Journey artifacts must not be symlinks')
        path = path.resolve(strict=True)
        path.relative_to(archive)
        if not path.is_file() or not path.stat().st_size or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get('sha256'):
            raise ValueError(f'Missing or changed journey artifact: {kind}')
    for name, maximum in expected.get('max_metrics', {}).items():
        if not isinstance(observed.get('metrics'), dict):
            raise ValueError('Missing measured journey metrics')
        value = observed.get('metrics', {}).get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > maximum:
            raise ValueError(f'Journey metric {name} is missing or exceeds {maximum}')
    return observed


def command(dag, name, stack, overrides=None):
    values = {**dag.get('config', {}).get('tech_stack_commands', {}).get(stack, {}), **(overrides or {})}
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Missing {stack} command: {name}')
    return value


def validate_modules(dag):
    modules = dag.get('config', {}).get('modules', {})
    if not isinstance(modules, dict):
        raise ValueError('modules must be an object')
    for name, module in modules.items():
        if (not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]*', name) or not isinstance(module, dict)
                or set(module) - {'path', 'tech_stack', 'commands', 'inputs', 'root_inputs', 'artifacts', 'coverage_threshold'}):
            raise ValueError(f'Invalid module definition: {name}')
        if not isinstance(module.get('tech_stack'), str) or not module['tech_stack'].strip():
            raise ValueError(f'Missing module tech_stack: {name}')
        relative(module.get('path'))
        _names(module.get('inputs'), f'{name}.inputs')
        if not isinstance(module.get('artifacts'), list):
            raise ValueError(f'{name}.artifacts must explicitly list outputs (or [])')
        if not isinstance(module.get('root_inputs', []), list):
            raise ValueError('root_inputs must be a list of project-relative shared inputs')
        for path in [*module['inputs'], *module['artifacts'], *module.get('root_inputs', [])]:
            relative(path)
        threshold = module.get('coverage_threshold', 80)
        if type(threshold) not in (int, float) or not 0 <= threshold <= 100:
            raise ValueError('Invalid module coverage threshold')
    for stage in dag['stages'].values():
        if stage.get('mutation_checks') is not None:
            validate_mutations(stage['mutation_checks'])
        checks = stage.get('module_checks')
        if checks is None:
            continue
        if not isinstance(checks, dict) or not checks:
            raise ValueError('module_checks must contain modules and named commands')
        for name, kinds in checks.items():
            if name not in modules:
                raise ValueError(f'Unknown module: {name}')
            _names(kinds, f'{name}.checks')
            for kind in kinds:
                command(dag, kind, modules[name]['tech_stack'], modules[name].get('commands'))
            if stage['id'] in ('S4', 'S4b', 'S4c') and 'coverage' not in kinds:
                raise ValueError(f'{stage["id"]} module {name} requires its coverage check')


def relative(value):
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError(f'Expected a project-relative path: {value}')
    return Path(value)


def inside(root, value):
    root = Path(root).resolve(strict=True)
    target = (root / relative(value)).resolve(strict=True)
    target.relative_to(root)
    return target


def manifest(root, inputs):
    """Retain declared build outputs too (including bytecode), unlike source exclusions."""
    result = {}
    for name in inputs:
        target = inside(root, name)
        files = [target] if target.is_file() else [p for p in sorted(target.rglob('*')) if p.is_file()]
        if not files:
            raise ValueError(f'Empty declared input/artifact: {name}')
        for path in files:
            path.resolve(strict=True).relative_to(root)
            if path.is_symlink():
                raise ValueError(f'Unsupported artifact symlink: {path}')
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def module_sources(root, inputs, artifacts):
    outputs = [Path(name).as_posix().rstrip('/') for name in artifacts]
    return {name: value for name, value in fingerprint(root, inputs).items()
            if not any(name == output or name.startswith(output + '/') for output in outputs)}


def modules_current(binding):
    try:
        root = Path(binding['project_dir']).resolve(strict=True)
        for value in binding['modules'].values():
            module_root = inside(root, value['path'])
            if module_sources(module_root, value['input_paths'], value['artifact_paths']) != value['inputs']:
                return False
            shared = value.get('root_input_paths', [])
            if (fingerprint(root, shared) if shared else {}) != value.get('root_inputs', {}):
                return False
            if manifest(module_root, value['artifact_paths']) != value['artifacts']:
                return False
            if not value['commands'] or any(r['exit_code'] != 0 for r in value['commands']):
                return False
        return bool(binding['modules'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def execute(dag, stage, project, log, report, stack=None):
    validate_modules(dag)
    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Project directory must exist')
    binding = dict(project_dir=str(root), run_id=os.environ.get('PIPELINE_RUN_ID'),
                   attempt_id=os.environ.get('PIPELINE_ATTEMPT_ID'), modules={})
    acceptance = dag.get('config', {}).get('project_acceptance') or {}
    review = acceptance.get('independent_review') if stage.get('id') == acceptance.get('stage_id') else None
    failure = 0

    def run(value, directory, stream, env=None):
        stream.write(f'Working directory: {directory}\nCommand: {value}\n'); stream.flush()
        started = time.monotonic()
        try:
            result = run_bounded(value, directory, 600, env, stream)
            code = result.returncode
        except subprocess.TimeoutExpired:
            stream.write('Command timed out\n'); code = 124
        stream.write(f'Exit: {code}\n'); stream.flush()
        return dict(command=value, exit_code=code, duration_seconds=round(time.monotonic()-started, 6))

    with Path(log).open('w') as stream:
        for name, kinds in stage.get('module_checks', {}).items():
            config = dag['config']['modules'][name]
            directory = inside(root, config['path'])
            if not directory.is_dir():
                raise ValueError(f'Module path is not a directory: {name}')
            before = module_sources(directory, config['inputs'], config['artifacts'])
            shared = config.get('root_inputs', [])
            shared_before = fingerprint(root, shared) if shared else {}
            item = dict(path=config['path'], tech_stack=config['tech_stack'], inputs=before,
                        input_paths=config['inputs'], artifact_paths=config['artifacts'], artifacts={}, commands=[],
                        root_input_paths=shared, root_inputs=shared_before)
            binding['modules'][name] = item
            for kind in kinds:
                value = command(dag, kind, config['tech_stack'], config.get('commands'))
                env = dict(os.environ)
                if kind == 'coverage':
                    import shlex
                    env.update(PROJECT_CODE_DIR=str(directory), PIPELINE_COVERAGE_COMMAND=value,
                               PIPELINE_COVERAGE_WORKDIR='')
                    value = ' '.join(map(shlex.quote, ['bash', str(TOOL_ROOT / 'lib/tdd-gate.sh'),
                            'module-' + name, config['tech_stack'], str(config.get('coverage_threshold', 80))]))
                receipt = run(value, directory, stream, env)
                receipt['kind'] = kind
                item['commands'].append(receipt)
                failure = failure or receipt['exit_code']
                if receipt['exit_code']:
                    break
            if not failure:
                item['artifacts'] = manifest(directory, config['artifacts'])
            if before != module_sources(directory, config['inputs'], config['artifacts']):
                raise ValueError(f'Module inputs changed while checking: {name}')
            if shared_before != (fingerprint(root, shared) if shared else {}):
                raise ValueError(f'Shared lock/config inputs changed while checking: {name}')
        selected = stack or dag.get('config', {}).get('tech_stack', 'node-typescript')
        for template in stage.get('post_commands', []):
            if not isinstance(template, str) or not template.strip():
                raise ValueError('Empty post command is not a check')
            match = re.fullmatch(r'\{\{([a-z_]+)\}\}', template)
            value = command(dag, match[1], selected) if match else template
            if review and value.strip() == review['command'].strip():
                raise ValueError('Independent review requires a distinct executable command')
            receipt = run(value, root, stream)
            failure = failure or receipt['exit_code']
        if review:
            report_path = Path(os.environ['PIPELINE_ACCEPTANCE_REPORT']).with_name(REVIEW_REPORT)
            command_path = report_path.with_name(REVIEW_COMMAND)
            report_path.unlink(missing_ok=True)
            command_path.unlink(missing_ok=True)
            env = dict(os.environ, PIPELINE_ACCEPTANCE_REPORT=str(report_path))
            receipt = run(review['command'], root, stream, env)
            receipt.update(run_id=binding['run_id'], attempt_id=binding['attempt_id'],
                           candidate_sha256=os.environ['PIPELINE_CANDIDATE_SHA256'])
            with command_path.open('x', encoding='utf-8') as command_file:
                json.dump(receipt, command_file, indent=2)
            failure = failure or receipt['exit_code']
    if binding['modules']:
        Path(report).write_text(json.dumps(binding, indent=2))
    if stage.get('mutation_checks') is not None:
        result = run_mutations(stage['mutation_checks'], root, Path(report).parent / 'mutation-work')
        Path(report).with_name('mutations.json').write_text(json.dumps(result, indent=2))
        with Path(log).open('a') as stream:
            stream.write('Mutation results: ' + json.dumps(result) + '\n')
        if result['status'] != 'passed': failure = 1
    return failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dag', required=True, type=Path)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--log', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    try:
        dag = json.loads(args.dag.read_text())
        result = execute(dag, dag['stages'][args.stage], args.project, args.log, args.report,
                         os.environ.get('PIPELINE_TECH_STACK'))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        with args.log.open('a') as log:
            log.write(f'Verification tool error: {exc}\n')
        parser.exit(2, f'Verification tool error: {exc}\n')
    raise SystemExit(0 if result == 0 else 1)


def _exit_on_signal(signum, _frame):
    signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGINT, signal.SIGTERM))
    raise SystemExit(128 + signum)


if __name__ == '__main__':
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _exit_on_signal)
    main()
