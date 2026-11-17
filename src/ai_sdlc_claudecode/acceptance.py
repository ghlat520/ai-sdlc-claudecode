"""Project acceptance over supervisor-bound candidates and named test results.

This is local execution evidence, not an approval or isolation mechanism.
Project adapters own business assertions; this module owns evidence consistency.
"""

import hashlib
import json
from pathlib import Path


_GENERATED = {'.git', '.artifacts', '.venv', 'node_modules', '__pycache__',
              '.pytest_cache', '.mypy_cache', '.ruff_cache'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate acceptance field: {key}')
        result[key] = value
    return result


def _names(value, label):
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError(f'{label} must contain unique nonempty names')
    return value


def policy(dag):
    value = dag.get('config', {}).get('project_acceptance')
    if value is None:
        return None
    allowed = {'scope', 'stage_id', 'candidate_inputs', 'required_checks', 'blocking_findings'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Invalid project_acceptance policy fields')
    for key in ('scope', 'stage_id'):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f'project_acceptance.{key} is required')
    _names(value.get('candidate_inputs'), 'candidate_inputs')
    checks = value.get('required_checks')
    if not isinstance(checks, dict) or not checks:
        raise ValueError('required_checks must declare named cases')
    for name, cases in checks.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Empty acceptance check ID')
        _names(cases, f'required_checks.{name}')
    findings = value.get('blocking_findings', {})
    if not isinstance(findings, dict):
        raise ValueError('blocking_findings must map IDs to required checks')
    for name, refs in findings.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Empty blocking finding ID')
        if not set(_names(refs, f'blocking_findings.{name}')) <= set(checks):
            raise ValueError(f'Unknown check for blocking finding {name}')
    stage = next((s for s in dag['stages'].values() if s['id'] == value['stage_id']), None)
    if stage is None or not stage.get('post_commands'):
        raise ValueError('Project acceptance requires a known stage with post_commands')
    return value


def fingerprint(project, inputs):
    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Candidate project must be a directory')
    manifest = {}
    for name in inputs:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Candidate inputs must stay inside the project')
        target = root / relative
        target.resolve(strict=True).relative_to(root)
        if target.is_symlink() and target.is_dir():
            raise ValueError(f'Candidate directory symlink is unsupported: {name}')
        files = [target] if target.is_file() else sorted(target.rglob('*'))
        count = 0
        for item in files:
            rel = item.relative_to(root)
            if set(rel.parts) & _GENERATED or item.suffix in ('.pyc', '.pyo'):
                continue
            item.resolve(strict=True).relative_to(root)
            if item.is_symlink() and item.is_dir():
                raise ValueError(f'Candidate directory symlink is unsupported: {rel}')
            if item.is_file():
                manifest[rel.as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
                count += 1
        if not count:
            raise ValueError(f'Candidate input contains no source files: {name}')
    return manifest


def prepare(definition, record, project, known_findings):
    manifest = fingerprint(project, definition['candidate_inputs'])
    return dict(scope=definition['scope'], policy_sha256=digest(definition),
                run_id=record['run_id'], attempt_id=record['attempt_id'],
                project_dir=str(Path(project).resolve()), candidate_manifest=manifest,
                candidate_sha256=digest(manifest), known_findings=dict(known_findings),
                report_path=str(Path(record['archive']) / 'project-acceptance.json'),
                collected=False)


def collect(binding, command_exit):
    binding['command_exit'] = int(command_exit)
    path = Path(binding['report_path'])
    binding['report_sha256'] = (hashlib.sha256(path.read_bytes()).hexdigest()
                                if path.is_file() and not path.is_symlink() else None)
    binding['collected'] = True


def evaluate(binding, definition, record):
    result = dict(status='incomplete', scope=definition['scope'], reasons=[],
                  run_id=binding.get('run_id'), attempt_id=binding.get('attempt_id'),
                  report_path=binding.get('report_path'),
                  candidate_sha256=binding.get('candidate_sha256'), passed_cases=0,
                  required_cases=sum(map(len, definition['required_checks'].values())),
                  known_findings=dict(binding.get('known_findings', {})))
    reasons = result['reasons']
    try:
        if (not binding.get('collected') or binding.get('policy_sha256') != digest(definition)
                or binding.get('run_id') != record.get('run_id')
                or binding.get('attempt_id') != record.get('attempt_id')):
            raise ValueError('Missing or stale acceptance attempt/policy')
        failed = binding['command_exit'] != 0
        if failed:
            result['status'] = 'failed'
            reasons.append(f'Acceptance command exited {binding["command_exit"]}')
        report_path = Path(binding['report_path'])
        if report_path.is_symlink():
            raise ValueError('Acceptance report must not be a symlink')
        raw = report_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != binding.get('report_sha256'):
            raise ValueError('Acceptance report changed after collection')
        report = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(report, dict):
            raise ValueError('Acceptance report must be an object')
        if (report.get('run_id') != record['run_id']
                or report.get('attempt_id') != record['attempt_id']):
            raise ValueError('Acceptance report belongs to another run/attempt')
        # Observed blockers survive even when missing cases or source drift prevent a pass.
        findings = report.get('findings', {})
        if not isinstance(findings, dict):
            raise ValueError('Invalid findings report')
        known = result['known_findings']
        known.update(definition.get('blocking_findings', {}))
        for name, finding in findings.items():
            if (not name.strip() or not isinstance(finding, dict)
                    or type(finding.get('blocking', True)) is not bool):
                raise ValueError(f'Invalid finding: {name}')
            refs = finding.get('checks', [])
            if refs != []:
                _names(refs, f'findings.{name}.checks')
            if finding.get('blocking', True):
                known[name] = list(dict.fromkeys([*known.get(name, []), *refs]))
        checks = report.get('checks')
        if not isinstance(checks, dict):
            raise ValueError('Missing named acceptance checks')
        for name, cases in checks.items():
            if (not name.strip() or not isinstance(cases, dict)
                    or any(not case.strip() for case in cases)
                    or any(status not in ('passed', 'failed', 'error', 'skipped') for status in cases.values())):
                raise ValueError(f'Invalid case result: {name}')
            if any(status in ('failed', 'error') for status in cases.values()):
                failed = True
                reasons.append(f'Failed cases: {name}')
        passed_checks = set()
        for name, required in definition['required_checks'].items():
            cases = checks.get(name)
            if not isinstance(cases, dict) or not set(required) <= set(cases):
                reasons.append(f'Missing required cases: {name}')
                continue
            result['passed_cases'] += sum(cases[case] == 'passed' for case in required)
            if any(status in ('failed', 'error') for status in cases.values()):
                continue
            elif any(cases[case] != 'passed' for case in required):
                reasons.append(f'Required cases skipped: {name}')
            else:
                passed_checks.add(name)
        for name, required_refs in known.items():
            finding = findings.get(name, {})
            refs = finding.get('checks', [])
            if (finding.get('status') != 'verified_closed' or not isinstance(refs, list)
                    or not refs or any(not isinstance(ref, str) for ref in refs)
                    or not set(required_refs) <= set(refs) or not set(refs) <= passed_checks):
                failed = True
                reasons.append(f'Blocking finding not verified closed: {name}')
        current = fingerprint(binding['project_dir'], definition['candidate_inputs'])
        if (current != binding['candidate_manifest']
                or digest(current) != binding['candidate_sha256']):
            raise ValueError('Candidate inputs changed; repeat affected acceptance')
        result['status'] = 'failed' if failed else ('incomplete' if reasons else 'passed')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        reasons.append(str(exc))
    return result
