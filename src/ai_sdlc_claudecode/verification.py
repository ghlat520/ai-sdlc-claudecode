"""Execute declared module checks using each target's existing toolchain.

Commands and paths are trusted project configuration. This is evidence collection,
not process isolation or an authorization service.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from .acceptance import _names, fingerprint


TOOL_ROOT = Path(__file__).resolve().parents[2]


def run_bounded(command_text, directory, timeout, env=None, stream=None):
    process = subprocess.Popen(command_text, cwd=directory, shell=True, executable='/bin/bash',
        env=env, stdout=stream if stream is not None else subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass  # It exited between timeout and group termination.
        process.communicate()
        raise
    return subprocess.CompletedProcess(command_text, process.returncode, output)


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
            receipt = run(value, root, stream)
            failure = failure or receipt['exit_code']
    if binding['modules']:
        Path(report).write_text(json.dumps(binding, indent=2))
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


if __name__ == '__main__':
    main()
