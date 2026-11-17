"""Read-only quality accounting over original supervisor attempts and cited observations.

An independent verdict/oracle is supplied with evidence; a role label is not proof
of independence. This module neither grants acceptance nor calls a model.
"""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from .acceptance import _unique_object, digest


def tracking_context(dag, metadata):
    tracking = dag.get('config', {}).get('quality_tracking', {})
    allowed = {'sample_kind', 'technology', 'risk', 'task_size', 'observation_window', 'tool_version'}
    if not isinstance(tracking, dict) or set(tracking) - allowed:
        raise ValueError('Invalid quality_tracking fields')
    if tracking.get('sample_kind', 'unclassified') not in (
            'unclassified', 'framework_fixture', 'model_task', 'business_run'):
        raise ValueError('Unknown quality sample kind')
    for key in allowed - {'technology'}:
        if key in tracking and (not isinstance(tracking[key], str) or not tracking[key].strip()):
            raise ValueError(f'quality_tracking.{key} must be a nonempty string')
    technology = tracking.get('technology')
    if technology is not None and (not isinstance(technology, list) or not technology
                                   or any(not isinstance(v, str) or not v for v in technology)):
        raise ValueError('quality_tracking.technology must be a nonempty list')
    return dict(sample_kind='simulation' if metadata.get('simulation') else tracking.get('sample_kind', 'unclassified'),
                technology=technology, risk=tracking.get('risk'), task_size=tracking.get('task_size'),
                observation_window=tracking.get('observation_window'), tool_version=tracking.get('tool_version'),
                budget=metadata.get('config'), scope=metadata.get('scope'),
                dag_sha256=digest(dag), model_routes=dag.get('config', {}).get('model_routes', {}),
                requested_models=sorted({a['model'] for s in dag['stages'].values() for a in s.get('agents', [])}))


def capture_attempt(record, ended_at):
    """Capture once, before later retries can replace source or acceptance results."""
    binding = record.get('project_acceptance', {})
    receipts = []
    for path in sorted(Path(record['archive']).glob('*-model.json')):
        raw = path.read_bytes()
        item = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
        try:
            receipt = json.loads(raw)
            amount = receipt.get('total_cost_usd')
            if amount is not None and (type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0):
                raise ValueError('Invalid model cost')
            item.update(actual_usd=amount, requested_model=receipt.get('requested_model'),
                        actual_model=receipt.get('actual_model'), provider=receipt.get('provider'),
                        profile=receipt.get('profile'), reasoning_effort=receipt.get('reasoning_effort'))
        except (ValueError, TypeError, AttributeError) as exc:
            item.update(actual_usd=None, error=str(exc))
        receipts.append(item)
    return dict(run_id=record['run_id'], attempt_id=record['attempt_id'], stage_id=record['stage_id'],
                status=record['status'], started_at=record['started_at_epoch'], ended_at=ended_at,
                active_seconds=round(max(0, ended_at - record['started_at_epoch']), 6),
                context=record['quality_context'], candidate_sha256=binding.get('candidate_sha256'),
                policy_sha256=binding.get('policy_sha256'), function_map_sha256=(binding.get('function_map') or {}).get('sha256'),
                acceptance=binding.get('result_at_collection'), resources=receipts,
                cost_entries=list(record.get('cost_entries', {}).values()))


def _cost(attempts):
    resources = [r for a in attempts for r in a.get('resources', [])]
    actual = sum(r['actual_usd'] for r in resources if r.get('actual_usd') is not None)
    estimates = [c['usd'] for a in attempts for c in a.get('cost_entries', []) if c['kind'] == 'estimated']
    unpriced = sum(r.get('actual_usd') is None for r in resources)
    unrecorded = sum(not a.get('resources') for a in attempts)
    return dict(scope='recorded_model_calls', known_actual_usd=round(actual, 6) if any(r.get('actual_usd') is not None for r in resources) else None,
                actual_total_usd=round(actual, 6) if resources and not unpriced and not unrecorded else None,
                estimated_usd=round(sum(estimates), 6) if estimates else None,
                unpriced_calls=unpriced, attempts_without_model_receipts=unrecorded)


def _rate(numerator, denominator, missing=0):
    return dict(status='available' if denominator and not missing else 'unavailable',
                numerator=numerator, denominator=denominator, missing=missing,
                value=numerator / denominator if denominator and not missing else None)


def load_tasks(paths):
    from .state import PipelineState
    tasks = {}
    for path in dict.fromkeys(Path(p).resolve() for p in paths):
        if not path.is_file():
            raise ValueError(f'Missing state file: {path}')
        state = PipelineState(path)
        data = state.read()
        task_id = data.get('quality_task_id') or digest({'state': str(path)})
        raw_records = [*data.get('history', []), *data.get('stages', {}).values()]
        legacy = [r for r in raw_records if r and not r.get('attempt_id')
                  and r.get('status') not in ('imported', 'skipped', 'pending')]
        records = {r['attempt_id']: r for r in raw_records
                   if r.get('attempt_id')}
        attempts = sorted((r['quality_snapshot'] for r in records.values() if r.get('quality_snapshot')),
                          key=lambda a: (a['started_at'], a['attempt_id']))
        candidates = [a for a in attempts if a.get('candidate_sha256')]
        contexts = list({digest(a['context']): a['context'] for a in attempts}.values())
        models = defaultdict(set)
        for attempt in attempts:
            for receipt in attempt['resources']:
                models[receipt.get('requested_model')].add(receipt.get('actual_model'))
        model_drift = any(len(versions) > 1 for versions in models.values())
        models_known = bool(models) and all(None not in versions for versions in models.values())
        classified = len(contexts) == 1 and contexts[0].get('sample_kind') not in ('unclassified', 'simulation')
        dimensions_known = len(contexts) == 1 and all(contexts[0].get(key) for key in
                            ('technology', 'risk', 'task_size', 'observation_window', 'tool_version'))
        incomplete_history = len(legacy) + sum(not r.get('quality_snapshot') for r in records.values())
        integrity_errors = []
        for a in attempts:
            for receipt in a['resources']:
                source = Path(receipt['path'])
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != receipt['sha256']:
                    integrity_errors.append(f'Model receipt missing or changed: {source}')
        current = state.project_acceptance(data)
        first = candidates[0] if candidates else None
        by_stage = defaultdict(int)
        for r in records.values():
            by_stage[r.get('stage_id', 'unknown')] += 1
        waits = [r for r in records.values() if r.get('quality_snapshot', {}).get('status') == 'human_waiting']
        waiting_complete = all('superseded_at_epoch' in r for r in waits)
        waiting = sum(max(0, r['superseded_at_epoch'] - r['quality_snapshot']['ended_at'])
                      for r in waits if 'superseded_at_epoch' in r)
        cost = _cost(attempts)
        known_repairs = sum(max(0, count - 1) for count in by_stage.values())
        if integrity_errors or incomplete_history:
            cost['actual_total_usd'] = None
        task = dict(task_id=task_id, feature_id=data.get('feature_id'), state_path=str(path),
                    attempt_count=len(records) + len(legacy), attempts=attempts, contexts=contexts,
                    comparable=classified and dimensions_known and not incomplete_history and not model_drift
                               and (models_known or contexts[0]['sample_kind'] == 'framework_fixture'),
                    model_observations={str(model): sorted(versions, key=str) for model, versions in models.items()},
                    incomplete_attempts=incomplete_history, integrity_errors=integrity_errors,
                    first_candidate_attempt_id=first['attempt_id'] if first and not incomplete_history else None,
                    first_candidate_status=(first.get('acceptance') or {}).get('status', 'unavailable') if first and not incomplete_history else 'unavailable',
                    current_acceptance=current['status'], current_candidate_sha256=current.get('candidate_sha256'),
                    current_policy_sha256=current.get('policy_sha256'),
                    repair_attempts=known_repairs if not legacy else None, known_repair_attempts=known_repairs,
                    active_attempt_seconds=round(sum(a['active_seconds'] for a in attempts), 6),
                    authorization_wait_seconds=round(waiting, 6) if waiting_complete else None,
                    known_authorization_wait_seconds=round(waiting, 6), cost=cost)
        if task_id in tasks and tasks[task_id] != task:
            raise ValueError(f'Conflicting state copies for task {task_id}')
        tasks[task_id] = task
    return list(tasks.values())


def load_observations(path, tasks):
    if path is None:
        return []
    path = Path(path)
    document = json.loads(path.read_text(), object_pairs_hook=_unique_object)
    rows = document.get('observations')
    if not isinstance(rows, list):
        raise ValueError('Observation input requires an observations list')
    attempts = {(t['task_id'], a['attempt_id']): a for t in tasks for a in t['attempts']}
    seen, result = {}, []
    for row in rows:
        attempt = attempts.get((row.get('task_id'), row.get('attempt_id')))
        if not attempt or not attempt['candidate_sha256']:
            raise ValueError('Observation has no recorded candidate attempt')
        for key in ('candidate_sha256', 'policy_sha256'):
            if row.get(key) != attempt[key]:
                raise ValueError(f'Observation {key} does not match the executed candidate')
        evidence = row.get('evidence', {})
        source = path.parent / evidence.get('path', '')
        if (not source.is_file() or source.is_symlink()
                or hashlib.sha256(source.read_bytes()).hexdigest() != evidence.get('sha256')):
            raise ValueError('Observation evidence missing or changed')
        for key in ('reviewer', 'independence_basis'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError('Independent observations require reviewer and independence_basis evidence')
        kind = row.get('kind')
        if kind == 'oracle':
            if row.get('classification') not in ('known_bad', 'known_good'):
                raise ValueError('Oracle must classify known_bad or known_good')
            if row.get('rejection_cause') not in (None, 'rule_false_positive', 'business_failure', 'environment_failure', 'other'):
                raise ValueError('Unknown rejection cause')
        elif kind == 'independent_review':
            if row.get('verdict') not in ('passed', 'failed', 'pending'):
                raise ValueError('Unknown independent verdict')
            if row['verdict'] == 'passed' and (attempt.get('acceptance') or {}).get('status') != 'passed':
                raise ValueError('Independent pass cannot override a failed/incomplete supervisor result')
        elif kind == 'defect_followup':
            if (not row.get('rule_id') or not row.get('rule_version')
                    or any(type(row.get(key)) is not bool for key in ('applicable', 'observed', 'recurred'))
                    or type(row.get('defect_count')) is not int or row['defect_count'] < 0
                    or row['recurred'] != (row['defect_count'] > 0)):
                raise ValueError('Invalid defect followup observation')
        elif kind == 'human_intervention':
            if type(row.get('count')) is not int or row['count'] < 0:
                raise ValueError('Intervention count must be a nonnegative integer')
        else:
            raise ValueError('Unknown observation kind')
        key = (row['task_id'], row['attempt_id'], kind, row.get('rule_id'))
        if key in seen:
            if seen[key] != row:
                raise ValueError('Conflicting observations for one candidate/kind')
            continue
        seen[key] = row
        result.append(row)
    return result


def build_report(paths, observations=None):
    tasks = load_tasks(paths)
    rows = load_observations(observations, tasks)
    cohorts = defaultdict(list)
    for task in tasks:
        context = dict(task['contexts'][0], observed_models=task['model_observations']) if task['comparable'] else {'not_comparable': task['task_id']}
        cohorts[digest(context)].append(task)
    output = []
    for cohort_id, members in cohorts.items():
        ids = {t['task_id'] for t in members}
        scoped = [row for row in rows if row['task_id'] in ids]
        attempts = {(t['task_id'], a['attempt_id']): a for t in members for a in t['attempts']}
        oracle_candidates = defaultdict(list)
        for row in scoped:
            if row['kind'] == 'oracle':
                oracle_candidates[(row['task_id'], row['candidate_sha256'], row['policy_sha256'])].append(row)
        bad = leaked = good = blocked = missing_cause = 0
        for group in oracle_candidates.values():
            labels = {r['classification'] for r in group}
            if len(labels) != 1:
                raise ValueError('Conflicting oracle labels for the same candidate')
            evaluated = [(r, (attempts[(r['task_id'], r['attempt_id'])].get('acceptance') or {}).get('status')) for r in group]
            if labels == {'known_bad'}:
                bad += 1
                leaked += any(status == 'passed' for _, status in evaluated)
            else:
                good += 1
                blocked += any(r.get('rejection_cause') == 'rule_false_positive' and status != 'passed' for r, status in evaluated)
                missing_cause += any(not r.get('rejection_cause') and status != 'passed' for r, status in evaluated)
        first_pass = first_terminal = pending = unsubmitted = 0
        accepted, incomplete = [], []
        for task in members:
            reviews = [r for r in scoped if r['task_id'] == task['task_id'] and r['kind'] == 'independent_review']
            first = next((r for r in reviews if r['attempt_id'] == task['first_candidate_attempt_id']), None)
            if first is None: unsubmitted += 1
            elif first['verdict'] == 'pending': pending += 1
            else:
                first_terminal += 1
                first_pass += first['verdict'] == 'passed'
            is_accepted = task['current_acceptance'] == 'passed' and any(
                r['verdict'] == 'passed' and r['candidate_sha256'] == task['current_candidate_sha256']
                and r['policy_sha256'] == task['current_policy_sha256'] for r in reviews)
            interventions = [r['count'] for r in scoped if r['task_id'] == task['task_id'] and r['kind'] == 'human_intervention']
            item = {key: task[key] for key in ('task_id', 'repair_attempts', 'active_attempt_seconds', 'authorization_wait_seconds', 'cost')}
            item['human_interventions'] = sum(interventions) if interventions else None
            (accepted if is_accepted else incomplete).append(item)
        followups = defaultdict(dict)
        for row in scoped:
            if row['kind'] == 'defect_followup':
                rule = row['rule_id'] + '@' + row['rule_version']
                if row['task_id'] in followups[rule] and followups[rule][row['task_id']] != row:
                    raise ValueError('Multiple followup outcomes for the same task/rule/window')
                followups[rule][row['task_id']] = row
        recurrence = {}
        for rule, by_task in followups.items():
            observed = [r for r in by_task.values() if r['applicable'] and r['observed']]
            value = _rate(sum(r['recurred'] for r in observed), len(observed))
            value['defect_count'] = sum(r['defect_count'] for r in observed)
            recurrence[rule] = value
        metrics = dict(bad_candidate_leak_rate=_rate(leaked, bad),
                       legitimate_candidate_block_rate=_rate(blocked, good, missing_cause),
                       defect_recurrence={'status': 'available' if any(v['status'] == 'available' for v in recurrence.values()) else 'unavailable', 'by_rule': recurrence},
                       first_independent_pass_rate={**_rate(first_pass, first_terminal),
                           'included_tasks': len(members), 'not_submitted': unsubmitted, 'pending': pending},
                       rework_and_cost={'accepted_tasks': accepted, 'incomplete_tasks': incomplete})
        candidates = {(task_id, a['candidate_sha256'], a['policy_sha256'])
                      for (task_id, _), a in attempts.items() if a.get('candidate_sha256')}
        comparable = all(t['comparable'] and not t['integrity_errors'] for t in members)
        if not comparable:
            for metric in metrics.values():
                metric['status'] = 'unavailable'
                if 'value' in metric: metric['value'] = None
        output.append(dict(cohort_id=cohort_id, comparable=comparable,
                           context=members[0]['contexts'][0] if comparable else None, metrics=metrics,
                           candidate_inventory=dict(evaluated=len(candidates), oracle_labeled=len(oracle_candidates),
                                                    unlabeled=len(candidates - set(oracle_candidates)))))
    return dict(schema_version=1, evidence_scope='supervisor snapshots plus supplied cited observations',
                tasks=tasks, cohorts=output, observations=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('states', nargs='+', type=Path)
    parser.add_argument('--observations', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.states, args.observations)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f'Quality report unavailable: {exc}\n')
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
