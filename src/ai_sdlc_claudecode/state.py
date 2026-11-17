"""Evolve State Manager — iteration progress, budgets, stall detection.

All updates return new state instances (immutable pattern).
Checkpoints are atomic writes to disk.
"""

from __future__ import annotations

import json
import math
import tempfile
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from . import acceptance, quality, verification


@dataclass(frozen=True)
class PhaseState:
    """Immutable state for a single phase."""

    status: str  # "pending" | "running" | "complete" | "stalled" | "budget_exceeded"
    iterations: int = 0
    stages_passed: tuple[int, ...] = ()
    errors_learned: int = 0


@dataclass(frozen=True)
class EvolveState:
    """Immutable state of the evolving agent."""

    state_file: Path
    start_time: float
    current_phase: int
    current_iteration: int
    max_cost_usd: float
    max_runtime_hours: float
    max_consecutive_failures: int
    cost_spent_usd: float = 0.0
    elapsed_hours: float = 0.0
    phases: dict[int, PhaseState] = field(default_factory=dict)
    consecutive_no_improve: int = 0

    # ---- factory ----

    @classmethod
    def create(
        cls,
        state_file: Path,
        max_cost: float = 50.0,
        max_hours: float = 4.0,
        max_failures: int = 5,
        start_phase: int = 1,
    ) -> EvolveState:
        """Create fresh state or resume from checkpoint."""
        if state_file.exists():
            return cls._load(state_file, max_cost, max_hours, max_failures)
        return cls(
            state_file=state_file,
            start_time=time.time(),
            current_phase=start_phase,
            current_iteration=0,
            max_cost_usd=max_cost,
            max_runtime_hours=max_hours,
            max_consecutive_failures=max_failures,
        )

    @classmethod
    def _load(cls, path: Path, max_cost: float, max_hours: float, max_failures: int) -> EvolveState:
        data = json.loads(path.read_text(encoding="utf-8"))
        phases = {
            int(k): PhaseState(
                status=v["status"],
                iterations=v.get("iterations", 0),
                stages_passed=tuple(v.get("stages_passed", [])),
                errors_learned=v.get("errors_learned", 0),
            )
            for k, v in data.get("phases", {}).items()
        }
        return cls(
            state_file=path,
            start_time=data.get("start_time_epoch", time.time()),
            current_phase=data.get("current_phase", 1),
            current_iteration=data.get("current_iteration", 0),
            max_cost_usd=max_cost,
            max_runtime_hours=max_hours,
            max_consecutive_failures=max_failures,
            cost_spent_usd=data.get("cost_spent_usd", 0.0),
            elapsed_hours=data.get("elapsed_hours", 0.0),
            phases=phases,
            consecutive_no_improve=data.get("consecutive_no_improve", 0),
        )

    # ---- immutable updates ----

    def update_iteration(
        self, phase: int, stages_passed: int, errors_learned: int, cost_delta: float,
    ) -> EvolveState:
        """Record an iteration result. Returns new state."""
        new_phases = deepcopy(self.phases)
        old = new_phases.get(phase, PhaseState(status="running"))
        new_sp = old.stages_passed + (stages_passed,)

        improved = len(old.stages_passed) == 0 or stages_passed > old.stages_passed[-1]

        new_phases[phase] = PhaseState(
            status="running",
            iterations=old.iterations + 1,
            stages_passed=new_sp,
            errors_learned=old.errors_learned + errors_learned,
        )

        return EvolveState(
            state_file=self.state_file,
            start_time=self.start_time,
            current_phase=phase,
            current_iteration=self.current_iteration + 1,
            max_cost_usd=self.max_cost_usd,
            max_runtime_hours=self.max_runtime_hours,
            max_consecutive_failures=self.max_consecutive_failures,
            cost_spent_usd=self.cost_spent_usd + cost_delta,
            elapsed_hours=(time.time() - self.start_time) / 3600.0,
            phases=new_phases,
            consecutive_no_improve=0 if improved else self.consecutive_no_improve + 1,
        )

    def complete_phase(self, phase: int) -> EvolveState:
        """Mark a phase as complete. Returns new state."""
        new_phases = deepcopy(self.phases)
        old = new_phases.get(phase, PhaseState(status="running"))
        new_phases[phase] = PhaseState(
            status="complete",
            iterations=old.iterations,
            stages_passed=old.stages_passed,
            errors_learned=old.errors_learned,
        )
        return EvolveState(
            state_file=self.state_file,
            start_time=self.start_time,
            current_phase=self.current_phase,
            current_iteration=self.current_iteration,
            max_cost_usd=self.max_cost_usd,
            max_runtime_hours=self.max_runtime_hours,
            max_consecutive_failures=self.max_consecutive_failures,
            cost_spent_usd=self.cost_spent_usd,
            elapsed_hours=self.elapsed_hours,
            phases=new_phases,
            consecutive_no_improve=self.consecutive_no_improve,
        )

    # ---- checks ----

    def check_budget(self) -> tuple[bool, str]:
        """Returns (within_budget, reason)."""
        elapsed = (time.time() - self.start_time) / 3600.0
        if self.cost_spent_usd >= self.max_cost_usd:
            return False, f"Cost limit: ${self.cost_spent_usd:.2f} >= ${self.max_cost_usd:.2f}"
        if elapsed >= self.max_runtime_hours:
            return False, f"Time limit: {elapsed:.1f}h >= {self.max_runtime_hours:.1f}h"
        return True, f"OK: ${self.cost_spent_usd:.2f}/${self.max_cost_usd:.2f}, {elapsed:.1f}h/{self.max_runtime_hours:.1f}h"

    def check_stall(self, window: int = 3) -> bool:
        """True if no improvement in the last `window` iterations."""
        return self.consecutive_no_improve >= window

    # ---- persistence ----

    def checkpoint(self) -> None:
        """Atomic write state to disk."""
        data = {
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.start_time)),
            "start_time_epoch": self.start_time,
            "current_phase": self.current_phase,
            "current_iteration": self.current_iteration,
            "max_cost_usd": self.max_cost_usd,
            "max_runtime_hours": self.max_runtime_hours,
            "cost_spent_usd": round(self.cost_spent_usd, 4),
            "elapsed_hours": round((time.time() - self.start_time) / 3600.0, 4),
            "phases": {
                str(k): {
                    "status": v.status,
                    "iterations": v.iterations,
                    "stages_passed": list(v.stages_passed),
                    "errors_learned": v.errors_learned,
                }
                for k, v in self.phases.items()
            },
            "improvement_trend": list(
                self.phases.get(self.current_phase, PhaseState(status="pending")).stages_passed
            ),
            "consecutive_no_improve": self.consecutive_no_improve,
        }

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self.state_file.parent), suffix=".tmp")
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            Path(tmp_path).replace(self.state_file)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    # ---- reporting ----

    def generate_report(self, output_path: Path) -> None:
        """Generate a markdown report."""
        elapsed = (time.time() - self.start_time) / 3600.0
        lines = [
            "# Self-Evolving Agent Report",
            "",
            f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            f"**Duration**: {elapsed:.2f} hours",
            f"**Cost**: ${self.cost_spent_usd:.2f} / ${self.max_cost_usd:.2f}",
            f"**Total iterations**: {self.current_iteration}",
            f"**Consecutive stalls**: {self.consecutive_no_improve}",
            "",
            *PipelineState.format_summary(PipelineState(self.state_file.with_name('state.json')).summary(), markdown=True),
            "",
            "## Phase Summary",
            "",
            "| Phase | Status | Iterations | Best Stages | Errors Learned |",
            "|-------|--------|------------|-------------|----------------|",
        ]
        for num in sorted(self.phases):
            ps = self.phases[num]
            best = max(ps.stages_passed) if ps.stages_passed else 0
            lines.append(f"| {num} | {ps.status} | {ps.iterations} | {best} | {ps.errors_learned} |")

        lines.extend(["", "## Improvement Trend", ""])
        for num in sorted(self.phases):
            ps = self.phases[num]
            if ps.stages_passed:
                lines.append(f"- **Phase {num}**: {' -> '.join(str(s) for s in ps.stages_passed)}")

        lines.extend([
            "", "## Budget Usage", "",
            f"- Cost: ${self.cost_spent_usd:.2f} ({self.cost_spent_usd / max(self.max_cost_usd, 0.01) * 100:.0f}%)",
            f"- Time: {elapsed:.2f}h ({elapsed / max(self.max_runtime_hours, 0.01) * 100:.0f}%)",
            "",
        ])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")


# The Bash supervisor owns these records. They are local audit evidence, not IAM.
import fcntl
import hashlib
import os
import re
import uuid
from contextlib import contextmanager


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@contextmanager
def locked_json(path):
    """Serialize the complete read/modify/replace operation across processes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {}
        try:
            yield data
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-")
            try:
                with os.fdopen(fd, "w") as out:
                    json.dump(data, out, indent=2, ensure_ascii=False)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, path)
            finally:
                Path(tmp).unlink(missing_ok=True)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class PipelineState:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    @staticmethod
    def ordered(dag):
        return [name for item in dag["execution_order"]
                for name in item.get("stages", [item.get("stage")]) if name]

    def start_run(self, feature, dag_path, scope, **metadata):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", feature):
            raise ValueError("feature_id must be a simple identifier")
        dag_path = Path(dag_path).resolve()
        dag = json.loads(dag_path.read_text())
        acceptance.policy(dag)
        verification.validate_modules(dag)
        ids = {s["id"] for s in dag["stages"].values()}
        if not scope or not set(scope) <= ids:
            raise ValueError("empty or unknown execution scope")
        execution_scope = list(metadata.pop("execution_scope", scope))
        if not execution_scope or not set(execution_scope) <= set(scope):
            raise ValueError("execution scope must stay within the goal scope")
        run = uuid.uuid4().hex
        quality_context = quality.tracking_context(dag, dict(metadata, scope=list(scope)))
        with locked_json(self.path) as data:
            owner = data.get("owner_pid")
            if owner:
                try:
                    os.kill(owner, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise ValueError("feature already has a live execution owner")
            data.setdefault("stages", {})
            data.setdefault("cost", {})
            if data.get('function_map_contract'):
                definition = acceptance.policy(dag)
                if not definition or not definition.get('function_map'):
                    raise ValueError('Cannot remove a frozen function-map obligation from this task')
                if definition['required_checks'] != data['function_map_contract']['contract']['required_checks']:
                    raise ValueError('Cannot change frozen function-map required checks in this task')
                frozen_policy = data['function_map_contract']['contract'].get('acceptance_policy')
                if not frozen_policy or acceptance.digest(definition) != acceptance.digest(frozen_policy):
                    raise ValueError('Cannot change frozen acceptance contract or scope in this task')
            data.pop('executor_exit', None)
            data.update(feature_id=feature, contract_version=2, run_id=run,
                        invocation_id=metadata.pop('invocation_id', None),
                        dag_path=str(dag_path), dag_sha256=_sha(dag_path),
                        scope=list(scope), execution_scope=execution_scope,
                        pipeline_state="running", updated_at=_now())
            data.update(metadata)
            data.setdefault('quality_task_id', acceptance.digest(dict(feature_id=feature,
                            project_dir=str(Path(data.get('project_dir', self.path.parent)).resolve()))))
            data['quality_context'] = quality_context
            data["invoked_by"] = {"os_uid": os.getuid(), "process_id": metadata.get("owner_pid"),
                                  "mechanism": "local_cli", "identity_assurance": "same_user_process"}
        return run

    def begin_attempt(self, run, stage, output_dir, retry=0):
        attempt = uuid.uuid4().hex
        output_dir = Path(output_dir).resolve()
        with locked_json(self.path) as data:
            if data.get("run_id") != run:
                raise ValueError("stale run")
            old = data["stages"].get(stage)
            if old:
                old['superseded_at_epoch'] = time.time()
                data.setdefault("history", []).append(old)
            dag = json.loads(Path(data["dag_path"]).read_text())
            config = next(s for s in dag["stages"].values() if s["id"] == stage)
            checks = sorted(self.expected_checks(config, dag))
            archive = output_dir / ".attempts" / attempt
            archive.mkdir(parents=True, exist_ok=False)
            # Old output is retained in its previous result archive, never reused as new work.
            previous_output = output_dir / "output.json"
            if previous_output.exists():
                (archive / "previous-output.json").write_bytes(previous_output.read_bytes())
            for name in ("output.json", "evidence.json", f"ai-review-{stage}.json"):
                (output_dir / name).unlink(missing_ok=True)
            if stage == "S2":
                (output_dir / "contracts.json").unlink(missing_ok=True)
            data["stages"][stage] = dict(
                contract_version=2, run_id=run, attempt_id=attempt, stage_id=stage,
                status="running", retry_count=retry, updated_at=_now(),
                started_at_epoch=time.time(), quality_context=data['quality_context'],
                dag_sha256=data["dag_sha256"], output_dir=str(output_dir),
                archive=str(archive), required_checks=checks,
                verification={"status": "pending", "scope": "configured_stage_checks",
                              "collector": "pipeline_supervisor", "evidence": []},
                authorization={"source": data["dag_path"], "sha256": data["dag_sha256"],
                               "type": config["gate"]["type"], "decision": "pending",
                               "actor": None, "scope": "accept_stage_artifact"},
                business_acceptance="not_evaluated", applied_fix_ids=[], dependencies=[],
                simulation=data.get("simulation", False))
            for name in config.get("dependencies", []):
                sid = dag["stages"][name]["id"]
                dep_path = self.path.parent / f"{sid}-{name}" / "output.json"
                if dep_path.exists():
                    data["stages"][stage]["dependencies"].append(
                        dict(stage_id=sid, path=str(dep_path), sha256=_sha(dep_path)))
        return attempt

    @staticmethod
    def _attempt(data, run, stage, attempt):
        record = data.get("stages", {}).get(stage, {})
        if data.get("run_id") != run or record.get("run_id") != run or record.get("attempt_id") != attempt:
            raise ValueError("stale run or attempt")
        return record

    def add_evidence(self, run, stage, attempt, check, exit_code, evidence_file):
        with locked_json(self.path) as data:
            record = self._attempt(data, run, stage, attempt)
            if record["status"] not in ("running", "gate_checking"):
                raise ValueError("attempt is already terminal")
            evidence = record["verification"]["evidence"]
            source = Path(evidence_file)
            snapshot = Path(record["archive"]) / f"check-{len(evidence)}.log"
            snapshot.write_bytes(source.read_bytes())
            output = Path(record["output_dir"]) / "output.json"
            evidence.append(dict(check=check, exit_code=int(exit_code), path=str(snapshot),
                                 sha256=_sha(snapshot), timestamp=_now(), run_id=run,
                                 attempt_id=attempt,
                                 artifact_sha256=_sha(output) if output.exists() else None))
            modules = Path(record['archive']) / 'module-checks.json'
            if check == 'post_commands' and modules.exists():
                record['module_checks'] = json.loads(modules.read_text())
            if check == 'contracts' and stage in ('S3', 'S3b'):
                report = json.loads(source.read_text())
                if report.get('source_binding'):
                    record['contract_source'] = report['source_binding']
            if check == 'mutations':
                record['mutation_checks'] = json.loads(source.read_text())

    def finish_attempt(self, run, stage, attempt, status, output=None, fix_ids=()):
        with locked_json(self.path) as data:
            record = self._attempt(data, run, stage, attempt)
            if status == "passed" and (data.get("simulation") or
                                        record["authorization"]["type"] == "human-required"):
                raise ValueError("simulation or human-required authorization cannot pass")
            record["status"] = status
            record["updated_at"] = _now()
            record["applied_fix_ids"] = list(fix_ids)
            if output and Path(output).exists():
                snapshot = Path(record["archive"]) / "output.json"
                snapshot.write_bytes(Path(output).read_bytes())
                record["result"] = {"path": str(Path(output).resolve()), "sha256": _sha(output),
                                    "archive": str(snapshot), "scope": "stage_artifact"}
            if status == "passed":
                record["authorization"].update(decision="accepted", actor="configured_policy")
                record["verification"]["status"] = "verified"
                if not self.is_verified(record, data["dag_path"]):
                    raise ValueError("missing, failed or stale verification evidence")
                definition = acceptance.policy(json.loads(Path(data['dag_path']).read_text()))
                if stage == 'S1' and definition and definition.get('function_map'):
                    self.freeze_function_map(data, definition)
            elif status != "gate_checking":
                record["verification"]["status"] = "unverified"
            if status in ('passed', 'failed', 'dead_letter', 'human_waiting', 'simulated') and 'quality_snapshot' not in record:
                record['quality_snapshot'] = quality.capture_attempt(record, time.time())
            return deepcopy(record)

    @staticmethod
    def expected_checks(config, dag=None):
        checks = {"schema", "gate"}
        if config.get("post_commands") or config.get('module_checks'):
            checks.add("post_commands")
        if config.get('mutation_checks'):
            checks.update(('post_commands', 'mutations'))
        if config.get("review_passes"):
            checks.add("refinement")
        if config["id"] in ("S2", "S3", "S3b"):
            checks.add("contracts")
        if config["id"] in ("S4", "S4b", "S4c"):
            checks.add("tdd")
        definition = acceptance.policy(dag) if dag else None
        if definition and definition['stage_id'] == config['id']:
            checks.add('project_acceptance')
        return checks

    @staticmethod
    def is_verified(record, dag_path):
        try:
            if (record.get("contract_version") != 2 or record.get("status") != "passed"
                    or not record.get("run_id") or not record.get("attempt_id")
                    or record["dag_sha256"] != _sha(dag_path)
                    or record["authorization"]["type"] == "human-required"
                    or record["authorization"]["decision"] != "accepted"
                    or record["verification"]["status"] != "verified"):
                return False
            result = record["result"]
            if result["sha256"] != _sha(result["path"]):
                return False
            if record["stage_id"] == "S2":
                output = json.loads(Path(result["path"]).read_text())
                if output["contracts_sha256"] != _sha(Path(result["path"]).with_name("contracts.json")):
                    return False
            dag = json.loads(Path(dag_path).read_text())
            config = next(s for s in dag["stages"].values() if s["id"] == record["stage_id"])
            if record["authorization"]["type"] != config["gate"]["type"]:
                return False
            if record["authorization"]["sha256"] != _sha(dag_path):
                return False
            if any(d["sha256"] != _sha(d["path"]) for d in record.get("dependencies", [])):
                return False
            if config.get('module_checks') and not verification.modules_current(record.get('module_checks', {})):
                return False
            if record.get('contract_source'):
                source = record['contract_source']
                if acceptance.fingerprint(source['project_dir'], source['paths']) != source['manifest']:
                    return False
            if config.get('mutation_checks'):
                mutation = record.get('mutation_checks', {})
                if mutation.get('status') != 'passed' or mutation.get('attempt_id') != record['attempt_id']:
                    return False
                source = mutation['source_binding']
                if acceptance.fingerprint(source['project_dir'], source['paths']) != source['manifest']:
                    return False
            receipts = record["verification"]["evidence"]
            if not PipelineState.expected_checks(config, dag) <= {r["check"] for r in receipts}:
                return False
            definition = acceptance.policy(dag)
            if definition and definition['stage_id'] == record['stage_id']:
                if acceptance.evaluate(record.get('project_acceptance', {}), definition, record)['status'] != 'passed':
                    return False
            return bool(receipts) and all(
                r["exit_code"] == 0 and r["run_id"] == record["run_id"]
                and r["attempt_id"] == record["attempt_id"] and r["sha256"] == _sha(r["path"])
                and r["artifact_sha256"] == result["sha256"] for r in receipts)
        except (KeyError, OSError, TypeError, ValueError, StopIteration):
            return False

    def freeze_function_map(self, data, definition):
        source = data['stages'].get('S1', {})
        if not self.is_verified(source, data['dag_path']):
            raise ValueError('Function map requires a verified S1 requirements artifact')
        artifact = source['result']
        output = json.loads(Path(artifact['path']).read_text())
        dag = json.loads(Path(data['dag_path']).read_text())
        config = next(s for s in dag['stages'].values() if s['id'] == definition['stage_id'])
        contract = acceptance.function_contract(output, definition, config['post_commands'])
        frozen = dict(contract=contract, sha256=acceptance.digest(contract),
                      source=dict(path=artifact['path'], sha256=artifact['sha256'],
                                  run_id=source['run_id'], attempt_id=source['attempt_id']))
        previous = data.get('function_map_contract')
        if previous and previous['sha256'] != frozen['sha256']:
            raise ValueError('Frozen function map changed; retain the original task obligations')
        data['function_map_contract'] = frozen
        return frozen

    def prepare_acceptance(self, run, stage, attempt):
        with locked_json(self.path) as data:
            record = self._attempt(data, run, stage, attempt)
            if record['status'] not in ('running', 'gate_checking'):
                raise ValueError('Cannot prepare acceptance for a terminal attempt')
            definition = acceptance.policy(json.loads(Path(data['dag_path']).read_text()))
            if not definition or definition['stage_id'] != stage:
                return ''
            if data['dag_sha256'] != _sha(data['dag_path']):
                raise ValueError('Acceptance policy changed during execution')
            known = {}
            for previous in data.get('history', []):
                evidence = previous.get('project_acceptance', {})
                if evidence.get('scope') == definition['scope']:
                    known.update(evidence.get('known_findings', {}))
            known.update(definition.get('blocking_findings', {}))
            function_map = self.freeze_function_map(data, definition) if definition.get('function_map') else None
            record['project_acceptance'] = acceptance.prepare(definition, record, data['project_dir'], known, function_map)
            return record['project_acceptance']['report_path']

    def collect_acceptance(self, run, stage, attempt, command_exit):
        with locked_json(self.path) as data:
            record = self._attempt(data, run, stage, attempt)
            if record['status'] not in ('running', 'gate_checking'):
                raise ValueError('Cannot collect acceptance for a terminal attempt')
            definition = acceptance.policy(json.loads(Path(data['dag_path']).read_text()))
            binding = record['project_acceptance']
            acceptance.collect(binding, command_exit)
            result = acceptance.evaluate(binding, definition, record)
            binding['known_findings'] = result['known_findings']
            binding['result_at_collection'] = result
            return result

    def project_acceptance(self, data=None):
        data = self.read() if data is None else data
        if not data.get('dag_path'):
            return dict(status='not_evaluated', scope=None, reasons=['No project execution record'])
        try:
            definition = acceptance.policy(json.loads(Path(data['dag_path']).read_text()))
            if definition is None or data.get('simulation'):
                return dict(status='not_evaluated', scope=None, reasons=['No executed project acceptance'])
            stage = definition['stage_id']
            if stage not in data.get('scope', []):
                return dict(status='incomplete', scope=definition['scope'], reasons=['Acceptance stage is outside requested scope'])
            record = data.get('stages', {}).get(stage, {})
            result = acceptance.evaluate(record.get('project_acceptance', {}), definition, record)
            if result['status'] == 'passed' and self.outcome(data) != 'complete':
                result.update(status='incomplete', reasons=['Requested execution scope is not verified complete'])
            return result
        except (KeyError, OSError, ValueError, TypeError) as exc:
            return dict(status='incomplete', scope=None, reasons=[str(exc)])

    def summary(self):
        data = self.read()
        scope = data.get('scope', [])
        statuses = {}
        for stage in dict.fromkeys([*scope, *data.get('stages', {})]):
            record = data.get('stages', {}).get(stage, {})
            status = record.get('status', 'pending')
            if status == 'passed' and not self.is_verified(record, data.get('dag_path', '')):
                status = 'unverified'
            statuses[stage] = status
        return dict(feature_id=data.get('feature_id'), run_id=data.get('run_id'),
                    scope=scope, execution_scope=data.get('execution_scope', scope),
                    execution_outcome=self.outcome(data) if data.get('dag_path') else 'unverified',
                    stage_statuses=statuses, stages_passed=sum(statuses[s] == 'passed' for s in scope),
                    stages_total=len(scope), project_acceptance=self.project_acceptance(data))

    def record_executor_exit(self, run, invocation, code):
        """Persist the supervising process result without overwriting another run."""
        with locked_json(self.path) as data:
            if (not invocation or data.get('run_id') != run
                    or data.get('invocation_id') != invocation):
                return False
            data['executor_exit'] = dict(run_id=run, invocation_id=invocation,
                                         exit_code=code, observed_at=_now())
            return True

    @staticmethod
    def format_summary(summary, markdown=False):
        project = summary['project_acceptance']
        values = [('Execution', summary['execution_outcome']),
                  ('Verified stages', f"{summary['stages_passed']}/{summary['stages_total']} (configured scope)"),
                  ('Project acceptance', project['status']),
                  ('Acceptance scope', project.get('scope') or 'not declared')]
        if project.get('candidate_sha256'):
            values.append(('Candidate', project['candidate_sha256']))
        if project.get('reasons'):
            values.append(('Remaining', '; '.join(project['reasons'])))
        else:
            values.append(('Remaining', 'None within the declared acceptance contract'))
        if project['status'] == 'failed':
            values.append(('Next', 'Implementer: repair the reported failures and resubmit for verification'))
        elif project['status'] == 'incomplete':
            values.append(('Next', 'Coordinator: resolve the missing or stale evidence in the declared scope'))
        elif project['status'] == 'not_evaluated':
            values.append(('Next', 'Coordinator: declare and execute project acceptance when required by the goal'))
        else:
            values.append(('Next', 'Product owner: review the accepted scope and any separately authorized release decision'))
        return [f"{'**' if markdown else ''}{key}{'**' if markdown else ''}: {value}" for key, value in values]

    def outcome(self, data=None):
        data = self.read() if data is None else data
        process = data.get('executor_exit', {})
        if process.get('run_id') == data.get('run_id') and process.get('exit_code', 0) != 0:
            code = process['exit_code']
            if code == 3:
                return 'human_waiting'
            if code == 4:
                return 'paused' if data.get('pipeline_state') == 'paused' else 'partial'
            return 'failed'
        stages = [data.get("stages", {}).get(s, {}) for s in data.get("scope", [])]
        statuses = {s.get("status", "pending") for s in stages}
        if "human_waiting" in statuses:
            return "human_waiting"
        if statuses & {"failed", "dead_letter"}:
            return "failed"
        if data.get("pipeline_state") == "paused":
            return "paused"
        if data.get("pipeline_state") == "failed":
            return "failed"
        if data.get("simulation"):
            return "simulated" if stages and statuses <= {"simulated"} else "partial"
        return ("complete" if stages and all(self.is_verified(s, data["dag_path"]) for s in stages)
                else "partial")


def _pipeline_cli():
    import sys
    command, path, *args = sys.argv[1:]
    state = PipelineState(path)
    if command == "start":
        feature, dag_path, selected, start_from, simulation, project, owner, description, cost, retries = args
        dag = json.loads(Path(dag_path).read_text())
        ordered = state.ordered(dag)
        names = ordered
        if selected:
            selectors = set(selected.split(","))
            known = {v for n in names for v in (n, dag["stages"][n]["id"])}
            if not selectors <= known:
                raise ValueError("unknown selected stages")
            names = [n for n in names if selectors & {n, dag["stages"][n]["id"]}]
        execution_names = names
        if start_from:
            offset = next(i for i, n in enumerate(ordered)
                          if start_from in (n, dag["stages"][n]["id"]))
            remaining = set(ordered[offset:])
            execution_names = [n for n in names if n in remaining]
            if not selected:
                names = execution_names
        print(state.start_run(feature, dag_path, [dag["stages"][n]["id"] for n in names],
                              execution_scope=[dag["stages"][n]["id"] for n in execution_names],
                              simulation=simulation == "true", project_dir=project, owner_pid=int(owner),
                              invocation_id=os.environ.get('PIPELINE_INVOCATION_ID'),
                              feature_description=description,
                              config={"cost_limit_usd":float(cost), "max_retries":int(retries)}))
    elif command == "replay":
        from .engine import ErrorEngine
        data = state.read()
        errors = Path(os.environ.get("EVOLVE_ERRORS_DIR", str(state.path.parent / "evolve")))
        engine = ErrorEngine(errors)
        for record in data.get("stages", {}).values():
            if record.get("status") == "passed" and not state.is_verified(record, data["dag_path"]):
                continue
            engine.record_outcome(record)
    elif command == "begin":
        print(state.begin_attempt(*args[:3], retry=int(args[3])))
    elif command == "evidence":
        run, stage, attempt, check, code, source = args
        state.add_evidence(run, stage, attempt, check, int(code), source)
    elif command == 'acceptance-prepare':
        print(state.prepare_acceptance(*args))
    elif command == 'acceptance-collect':
        result = state.collect_acceptance(*args[:3], int(args[3]))
        print(json.dumps(result))
        sys.exit(0 if result['status'] == 'passed' else 1)
    elif command == 'summary':
        print(json.dumps(state.summary()))
    elif command == "stage":
        run, stage, attempt, status, retry, fixes = args
        if status in ("skipped", "imported"):
            with locked_json(path) as data:
                if data.get("run_id") != run:
                    raise ValueError("stale stage writer")
                old = data["stages"].get(stage, {})
                if status == "skipped" and old.get("status") == "imported":
                    return
                if old and old.get('status') not in ('skipped', 'imported', 'pending'):
                    old['superseded_at_epoch'] = time.time()
                    data.setdefault('history', []).append(old)
                data["stages"][stage] = dict(contract_version=2, run_id=run, attempt_id=None,
                                             status=status, verification={"status": "unverified"},
                                             authorization={"decision": "not_evaluated"},
                                             business_acceptance="not_evaluated", updated_at=_now())
                if status == "imported":
                    dag = json.loads(Path(data["dag_path"]).read_text())
                    name = next(n for n, s in dag["stages"].items() if s["id"] == stage)
                    output = state.path.parent / f"{stage}-{name}" / "output.json"
                    data["stages"][stage]["result"] = dict(path=str(output), sha256=_sha(output), scope="imported_input")
        else:
            output = Path(state.read()["stages"][stage]["output_dir"]) / "output.json"
            record = state.finish_attempt(run, stage, attempt, status, output,
                                          [f for f in fixes.split(",") if f])
            if status in ("passed", "failed", "dead_letter") and record["applied_fix_ids"]:
                from .engine import ErrorEngine
                errors = Path(os.environ.get("EVOLVE_ERRORS_DIR", str(state.path.parent / "evolve")))
                ErrorEngine(errors).record_outcome(record)
    elif command == "get":
        stage, dag_path = args
        record = state.read().get("stages", {}).get(stage, {})
        status = record.get("status", "pending")
        print("unverified" if status == "passed" and not state.is_verified(record, dag_path) else status)
    elif command == "resume":
        dag_path = args[0]
        dag = json.loads(Path(dag_path).read_text())
        data = state.read()
        for name in state.ordered(dag):
            sid = dag["stages"][name]["id"]
            if not state.is_verified(data.get("stages", {}).get(sid, {}), dag_path):
                print(sid)
                break
    elif command == "dependencies":
        stage, dag_path = args
        data = state.read()
        dag = json.loads(Path(dag_path).read_text())
        config = next(s for s in dag["stages"].values() if s["id"] == stage)
        for name in config.get("dependencies", []):
            dep = data.get("stages", {}).get(dag["stages"][name]["id"], {})
            imported = dep.get("status") == "imported" and dep.get("result")
            if imported:
                imported = dep["result"]["sha256"] == _sha(dep["result"]["path"])
            simulated = data.get("simulation") and dep.get("status") == "simulated"
            if not (state.is_verified(dep, dag_path) or imported or simulated):
                print("unverified prerequisite: " + name, file=sys.stderr)
                sys.exit(1)
    elif command == "selected":
        data = state.read()
        scope = data.get("scope", [])
        execution_scope = data.get("execution_scope", scope)
        sys.exit(0 if args[0] in scope and args[0] in execution_scope else 1)
    elif command == "pipeline":
        with locked_json(path) as data:
            if os.environ.get("PIPELINE_RUN_ID") != data.get("run_id"):
                raise ValueError("stale pipeline writer")
            data.update(pipeline_state=args[0], pipeline_state_reason=args[1], updated_at=_now())
    elif command == "finish":
        outcome = state.outcome()
        with locked_json(path) as data:
            if os.environ.get("PIPELINE_RUN_ID") != data.get("run_id"):
                raise ValueError("stale finalization writer")
            data.update(pipeline_state=outcome, owner_pid=None, updated_at=_now())
        print(outcome)
    elif command == "cost":
        kind, model, usd, tin, tout, cr, cc = args
        tin, tout, cr, cc = map(int, (tin, tout, cr, cc))
        with locked_json(path) as data:
            if os.environ.get("PIPELINE_RUN_ID") != data.get("run_id"):
                raise ValueError("stale cost writer")
            amount = float(usd) if kind == "actual" else tin / 1e6 * {"opus":45, "sonnet":9, "haiku":2.4}.get(model, 9)
            if kind not in ('actual', 'estimated') or not math.isfinite(amount) or amount < 0:
                raise ValueError('Invalid cost update')
            attempt_id = os.environ.get('PIPELINE_ATTEMPT_ID')
            cost_id = os.environ.get('PIPELINE_COST_ID')
            record = next((r for r in data['stages'].values() if r.get('attempt_id') == attempt_id), None) if attempt_id else None
            if attempt_id and (record is None or record['run_id'] != data['run_id']):
                raise ValueError('stale attempt cost writer')
            if record is not None and cost_id:
                entries = record.setdefault('cost_entries', {})
                entry = dict(kind=kind, model=model, usd=amount, input_tokens=tin, output_tokens=tout,
                             cache_read_tokens=cr, cache_creation_tokens=cc, source=cost_id)
                if cost_id in entries:
                    if entries[cost_id] != entry:
                        raise ValueError('Conflicting repeated cost entry')
                    return
                if 'quality_snapshot' in record:
                    raise ValueError('Cannot add costs to a finalized attempt')
                entries[cost_id] = entry
            c = data.setdefault("cost", {})
            for key, value in (("total_tokens", tin+tout+cr+cc), ("input_tokens", tin),
                               ("output_tokens", tout), ("cache_read_input_tokens", cr),
                               ("cache_creation_input_tokens", cc)):
                c[key] = c.get(key, 0) + value
            c["estimated_usd"] = round(c.get("estimated_usd", 0) + amount, 6)
            if kind == "actual":
                c["actual_usd"] = round(c.get("actual_usd", 0) + amount, 6)
            c["source"] = kind if c.get("source", kind) == kind else "mixed"
            bm = c.setdefault("by_model", {}).setdefault(model, {"usd":0, "calls":0})
            bm["usd"] = round(bm["usd"] + amount, 6)
            bm["calls"] += 1
    else:
        raise ValueError("unknown state command")


if __name__ == "__main__":
    _pipeline_cli()
