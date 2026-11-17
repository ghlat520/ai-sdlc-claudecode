# Unattended execution: state and evidence contract (v1)

## 1. Definition

The existing Bash DAG and Python runner must report each stage result with its execution identity, collected verification evidence, and authorization source. The runner may advance only on verified results in the requested scope. Reporting must not turn skipped, imported, simulated, or unverified work into executed success.

The user selected these constraints on 2026-09-13: retain the execution skeleton; clarify what finished, the evidence, who authorized it, and which execution produced it; defer external runtime feedback.

## 2. Constraints and scope

- Reuse pipeline-executor.sh, orchestrate-parallel.sh, lib/events.sh, state.py, runner.py, engine.py and existing tests.
- Keep DAG stage definitions, retries and concurrent groups. Sequential and concurrent stages use the same checks.
- Preserve the existing uncommitted contract-validator work.
- No production deployment, external notification, remote push, global skill promotion, or monitoring integration is authorized by this change or its validation.
- v1 establishes the executor's state semantics. It does not supply a sandbox, an identity provider, or production business acceptance.
- A policy gate can accept a stage artifact; it does not authorize arbitrary tool actions or production access. A human-required gate remains pending; an editable APPROVED marker is not independently verified authorization. A trusted approval integration is deferred and cannot be simulated by the executor.

## 3. Inputs

- Existing CLI feature ID, description, selected stages, resume/import/simulation options and DAG configuration.
- A feature ID must be a simple identifier, not a path or shell fragment.
- Each invocation receives a fresh run_id; each stage execution/retry receives a fresh attempt_id. Reusing a verified prerequisite preserves its original execution identity.
- Stage scope and DAG digest are recorded. Artifacts and collected evidence are hashed. Prior evidence with a different artifact or DAG is unverified.
- Agent prose is diagnostic data. Only the executor's command exits, actual output validation and independent gate results can establish verification.
- Evidence checks are fail closed. Missing tools, unsupported checks, invalid output and checker errors are unsuccessful verification, not fallback success.

## 4. Outputs

Retain state.json and events.jsonl. Stage records include:

| Field | Meaning |
|---|---|
| contract_version | Version 2 identifies records with the new semantics |
| run_id / attempt_id | Invocation and stage attempt that produced the record |
| status | Existing execution state plus skipped, imported, simulated and unverified |
| result | Stage artifact path, digest and explicitly limited result scope |
| verification | Status, configured-stage-check scope, collector and evidence references |
| authorization | Policy source/digest and scope, or a pending human decision with no claimed approver |
| applied_fix_ids | Exact correction variants injected for this attempt |

Evidence receipts retain command/validator names, exit codes, timestamps and digests. Output logs remain local. A stage PASS proves only its configured checks; business_acceptance remains not_evaluated.

An optional `config.project_acceptance` policy now adds a separate scoped verdict. The
designated stage runs the project's existing acceptance adapter through `post_commands`.
Its attempt record binds actual candidate inputs, policy, named cases, known blockers
and collected report. `PipelineState.summary()` recalculates both execution and project
acceptance for all reporting paths. No policy means `not_evaluated`; old records are not
retroactively certified. See [the integration contract](ai-management.md) for the format,
source exclusions, roles, retry semantics and remaining runtime/human boundaries.

Pipeline outcomes distinguish complete, partial, simulated, human_waiting, paused and failed. Only verified requested stages yield complete. A simulated run is explicitly labelled and contributes no production pass or learning sample.

## 5. Flow

1. Validate input and resolve the requested stage scope in DAG order.
2. Initialize or load state under a file lock. Preserve prior records and their provenance on resume; old records without provenance become unverified for execution decisions.
3. Create a fresh attempt, empty its evidence, and run the existing agent/command path.
4. Validate output, execute configured checks and collect their results. Missing or failed required checks stop the attempt.
5. Policy gates may accept the artifact with the policy digest recorded. Human-required gates write a pending request, checkpoint, and return without polling or generating approvals.
6. Finalize the attempt under the same locked atomic state writer. Concurrent stages must not overwrite one another or cost updates.
7. Attribute one terminal verified outcome per attempt to the exact injected fix IDs. Repeated reads, resumes and skipped/imported/simulated stages do not create samples. No automatic promotion to global skills.
8. Report scope-aware results. A failed or pending phase cannot advance automatically into another project or phase.

## 6. Invariants

- INV-1: passed implies a non-simulated attempt, validated artifact, successful required receipts, and a recorded acceptance policy; it never implies business acceptance.
- INV-2: skipped/imported/simulated/unverified never increment executed success or learning counters.
- INV-3: replaying an outcome for the same attempt is idempotent, including after process restart.
- INV-4: no executor path writes human approval or consumes a bare APPROVED marker as a verified human decision.
- INV-5: pending/failed/paused work cannot be reported as complete or advance to another feature automatically.
- INV-6: concurrent updates preserve all stage records and costs; old or tampered evidence cannot satisfy current checks.
- INV-7: a checker failure cannot be weakened to structural-only success. Sequential and concurrent execution enforce the same contract.

## 7. Test matrix and delivery

| Case | Expected | Validation |
|---|---|---|
| Valid artifact + actual successful checks | Provenance-rich passed record | Unit + real Bash executor with deterministic fake Claude |
| Missing/false/empty prose evidence | Prose cannot grant a pass | Unit + executor integration |
| Invalid schema / checker unavailable / AI review rejects | Failed, never structural fallback | Executor integration |
| Two successful reads of one attempt / restart | One learning outcome | Engine + runner regression |
| Skip/import/skeleton/mock-review | Distinct states; zero learning samples | Executor + runner regression |
| Human-required + forged/bare APPROVED file | human_waiting; marker untouched; no downstream execution | Executor integration |
| Legacy PASS or artifact/DAG digest mismatch | Unverified; no implicit resume success | State + runner regression |
| Concurrent stages and cost writers | No lost updates; identical gates | Process integration |
| Failure or pending phase | No follow-on phase/project | CLI regression |

Implementation is prepared and tested in an isolated copy, reviewed for correctness/security/silent failure, then applied only to the named source files after verifying the original worktree baseline still matches. No existing WIP is reverted. Rollback is the task-only patch; old history is not retroactively certified.

## Five-stage SDLC adoption

The supplied five-stage table maps responsibilities and evidence onto the existing DAG; its Markdown filenames are optional human-readable views, not a new executor architecture.

| Team stage | Existing stages / artifacts | Adopted now | Remaining integration |
|---|---|---|---|
| Plan / intent.md | S0p discovery, S0 strategic-review, S1 requirements output.json | Intent/scope remain human decisions; pending has an explicit identity and cannot advance | Trusted approval identity/transport and intent-to-acceptance traceability |
| Design / spec.md | S2 architecture/contracts, S2b UI design | Schema and required contract checks fail closed; preserve the existing contract-validator work | Team-specific design decision owners and traceable unresolved questions |
| Build / plan + code/tests | S3 backend, S3b frontend and existing DAG plan | Common serial/parallel verifier, actual post-command exits, bounded attempts | Worktree isolation where concurrent tasks write the same files; measured adjacent-feature regression |
| Test / REVIEW.md + eval/CI | S4 family, S5 review, S9 performance | Failed/unavailable required checks reject; one attempt is one learning sample | Separate product regressions from agent evals; versioned model/prompt/config eval CI |
| Deploy / approvals + versions | S6 deployment preparation, S10 release brief; S7 monitoring design | Artifact acceptance is explicit and cannot be reported as production/business acceptance | Production entrypoint authorization, staging rollback exercise, live version and business readback; external feedback deferred |

The current bottleneck is now controlled by withholding unproven completion. This does not establish that the entire intended product is correct or that a model cannot misuse credentials already available in its process. Before enabling production autonomy, demonstrate real entrypoint authorization and business readback under the intended deployment identity. A forged receipt/state by another process with the same filesystem authority is outside this local supervisor trust model.
