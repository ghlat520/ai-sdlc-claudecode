# AI management and project acceptance

The existing DAG remains the delivery coordinator. Agents implement and review assigned
work; the local supervisor computes acceptance from the declared project contract and
collected execution evidence. A stage finishing is a different claim from a product
passing its acceptance checks. Neither grants permission to deploy.

## Responsibilities and context

| Owner | Responsibility | Completion boundary |
| --- | --- | --- |
| Product owner | Intent, priorities, tradeoffs, important authorization | Business decisions and any required human acceptance |
| Coordinator | Source discovery, scope, dependencies, next owner/action | Arrange verification; cannot override failed evidence |
| Implementer | Bounded changes, equivalent call sites, focused self-checks | Candidate submitted with actual tested scope |
| Reviewer | Original contract, counterexamples, same-rule entrypoints | Independently verified scope and remaining findings |
| Supervisor | Run checks, bind inputs/results, calculate current status | Acceptance of the declared candidate and check set |

These are responsibilities, not a requirement to start five agents. Important delivery
uses independent review; simple work can use a single implementer. Parallel work still
requires independent ownership and existing authorization. The current executor does
not enforce identity separation between an implementer and a reviewer.

Every rendered stage prompt includes these responsibilities. Existing
`config.project_completion` metadata is included as project intent and source references:

```json
{
  "project_completion": {
    "goal": "A repeated order request has one durable result",
    "authority": ["docs/approved-spec.md", "api/openapi.yaml"],
    "excluded_until_approved": ["production rollout"]
  }
}
```

Keep source references short and authoritative. Agents read the underlying sources and
report relevant versions. Do not place credentials or customer records in this metadata.
The project owns business expectations and permitted file/module scope.

## Opt in through the project's DAG

Add an optional `config.project_acceptance` object and use the existing final stage's
`post_commands` to run an acceptance adapter. The final stage can have any ID; it does
not have to be S10. Example policy:

```json
{
  "scope": "orders-v1",
  "stage_id": "S9",
  "candidate_inputs": ["src", "tests/acceptance", "scripts/accept_orders.py", "uv.lock"],
  "required_checks": {
    "orders": ["create", "replay", "reject_invalid_return"]
  },
  "blocking_findings": {"ORDER-17": ["orders"]}
}
```

The stage's `post_commands` can contain `python3 scripts/accept_orders.py`. Commands run
in the selected `--project-dir`; they retain real exit codes. Required case IDs must be
nonempty and unique within each check. A configured policy requires a real stage and at
least one post-command. An invalid policy cannot silently become opt-out.

`candidate_inputs` are project-relative files or directories. Include the application,
test driver, relevant tests, lockfiles, nonsecret configuration, and exported package when
the package is what you accept. The supervisor hashes actual bytes, including untracked
and newly added files, before commands run and again when evaluating their results.
Changing/removing a bound file or adding one under a declared directory invalidates the
old evidence. Do not write acceptance output into these input directories.

Generated directories `.git`, `.artifacts`, `.venv`, `node_modules`, `__pycache__`,
`.pytest_cache`, `.mypy_cache`, `.ruff_cache` and `.pyc`/`.pyo` files are excluded.
Each input must contain at least one included file. Absolute paths, parent traversal,
paths resolving outside the project and directory symlinks are rejected. Declare real
source directories instead of directory symlinks. This is a local evidence boundary,
not a hostile-process sandbox.

## Adapter report

The supervisor gives post-commands `PIPELINE_RUN_ID`, `PIPELINE_ATTEMPT_ID` and
`PIPELINE_ACCEPTANCE_REPORT`. The last variable is an attempt-specific JSON path.
The adapter writes this format after executing the real checks:

```json
{
  "run_id": "value from PIPELINE_RUN_ID",
  "attempt_id": "value from PIPELINE_ATTEMPT_ID",
  "checks": {
    "orders": {
      "create": "passed",
      "replay": "passed",
      "reject_invalid_return": "passed"
    }
  },
  "findings": {
    "ORDER-17": {"status": "verified_closed", "checks": ["orders"]}
  }
}
```

Case results are `passed`, `failed`, `error`, or `skipped`. The adapter maps existing
project JSON/JUnit results into these stable IDs; the framework does not discover tests
or infer success from a total count. No report, a wrong run/attempt, missing/zero cases,
skipped required cases, execution errors and failed cases cannot pass. Any reported
failed/error case, including an additional check, blocks acceptance. Duplicate JSON keys
are rejected rather than allowing a later value to hide a failure.

The adapter must execute the actual target path, retain raw test logs, preserve nonzero
exits, and emit only cases present in that run's results. Do not initialize every case to
passed, copy old reports, or infer that zero tests means success. Review its mapping and
business assertions independently. Binding an adapter's bytes does not prove its assertions
are correct. Package, service version, authenticated journey, database and human acceptance
need their own declared checks and actual readback; a source digest cannot establish them.

Findings use `open`, `fix_submitted`, or `verified_closed`. Blocking is the default; an
explicit `blocking: false` is only for newly observed nonblocking findings. A known blocker
cannot be downgraded or omitted by a later report. Closure requires references to passing
required checks; policy-defined references must all be present. New blockers from an
identity-matching collected report survive retries in the same acceptance scope, including
when source drift makes that report insufficient to pass. A new scope is a deliberate
contract change; preserve unresolved obligations when migrating it.

## One current verdict

`PipelineState.summary()` is the common calculation used by the runner, CLI, status/list
scripts, both terminal panels and Markdown report. It recomputes validity from current
inputs, policy, attempt-bound reports and stage evidence. The stored `pipeline_state` and
historical end events are not current acceptance proofs.

The Python runner also persists its process exit under the state lock. A unique invocation
ID is established before launch and recorded by that executor; a rejected concurrent caller
cannot attribute its failure to another run. A nonzero terminal exit cannot leave the shared
verdict at complete/passed, and a new invocation clears the previous process outcome.

| Project status | Meaning | Next owner |
| --- | --- | --- |
| `not_evaluated` | No policy, no execution record, or simulation | Coordinator declares the intended acceptance when needed |
| `incomplete` | Missing/stale evidence, incomplete scope, or pending approval | Coordinator obtains the missing evidence |
| `failed` | Actual check failure or an unresolved known blocker | Implementer repairs and resubmits to verification |
| `passed` | Same candidate, all named necessary cases, closed blockers, verified requested stages | Product owner makes any remaining business/release decisions |

Every report shows the execution result, verified stages in the configured scope,
acceptance scope/status, candidate digest when available, remaining reasons and next action.
Source drift invalidates the affected final acceptance, while unrelated upstream artifacts
remain reusable. Resume re-runs invalid evidence. Serial and parallel stages use the same
collector. Human-required gates remain `human_waiting`; no bare approval marker or agent
statement grants approval. Old DAGs still run with project acceptance `not_evaluated`.

```bash
PIPELINE_ROOT=/path/to/runs PIPELINE_DAG_FILE=/path/to/project-dag.json \
  bash pipeline-executor.sh orders-v1 "Verify the agreed order behavior" --project-dir /path/to/project
PIPELINE_ROOT=/path/to/runs bash pipeline-status.sh orders-v1
PIPELINE_ROOT=/path/to/runs python3 -m ai_sdlc_claudecode report --feature-id orders-v1
```

The displayed report is a snapshot at read time. A long-running service can change after
that read. Use a deployment/runtime adapter and fresh readback before making a release
claim; this version does not add a runtime monitor or trusted approval service.

## Bounded repair and learning

Reuse the DAG, retry limits, timeouts, dead letters and ErrorEngine. Acceptance failures
return concrete reasons through the existing repair feedback. The prompt asks for a causal
probe after two attempts at the same blocker; this is an agent instruction, not an enforced
cross-run scheduler. An implementer's successful self-check does not clear a known blocker.

ErrorEngine continues to attribute stage outcomes to the exact attempt and injected fix
IDs. Stage success is not a product-success learning sample. Preserve a useful correction
as trigger, cause, minimal fix, original failure now passing, equivalent-entrypoint coverage
and limits. Prefer regression tests for mechanical failures and short project review rules
for judgment. Do not automatically promote a case into a global Skill.

## Validation and limits

`tests/test_pipeline_contract.py` drives the real Bash supervisor with a deterministic
fake model and local acceptance commands. It exercises successful candidates, stale
sources/reports, required-case failures and omissions, blocker retention, reporting,
resume, parallel execution and human/simulation boundaries. It does not establish real
model performance or acceptance of any downstream product.

Reject this design's effectiveness claim if a covered stale/partial candidate is accepted,
or if a complete valid candidate cannot pass. Fix the contract/adapter and add the actual
counterexample before broadening autonomy. Rollback is the scoped implementation commit;
preserve attempt archives. Rolling back removes these acceptance guards and cannot certify
old reports. The next measurement is a real project's frozen-candidate pilot, with denominators
for first-pass acceptance, reopened defects and required user interventions; no savings
percentage is claimed from framework fixtures.

## Executable S1 function maps

Opt in with `"function_map": {"source_stage_id": "S1"}` inside the existing
`config.project_acceptance`. Keep its `candidate_inputs`, `required_checks`, acceptance
stage and post-commands. S1 emits the optional `function_map` property described in
`schemas/requirements-output.json`; old DAGs need no new fields and gain no new verdict.

Each behavior includes `id`, existing `requirement_id`/`acceptance_id`, `role`,
`preconditions`, `state_before`, `event`, `state_after`, `data_changes`, `failure_retry`,
`feedback`, `target`, `check_id`, `case_id`, `command`, `expected`, and
`evidence: "supervisor_report"`. These values are nonempty strings; `target` is a
candidate-relative source path, and `command` is an exact acceptance post-command.
All must-have FRs and all ACs must be mapped. The map's check/case pairs must equal
`required_checks`, not merely overlap it. A source/driver written later is fingerprinted
before its checks execute. The adapter still owns the actual business assertions.

After verified S1 execution, the supervisor freezes the normalized behavior contract
and its hash in `state.json`. Each acceptance attempt binds that contract, its S1 artifact,
candidate bytes, report and named case outcomes. The final verdict exposes FR/AC-to-case
results and report paths. Missing, failed, error and skipped cases cannot close a behavior.
Changing the S1 artifact invalidates old evidence. Within the same task, deleting cases,
changing expectations or removing the map is rejected even across resume. An approved
scope change needs a separate task and an explicit disposition of old obligations; this
version intentionally has no automatic contract-amendment or blocker-clearing path.

## First-attempt quality accounting

Every new attempt records its start, original terminal result, candidate/contract identity,
model receipt hashes, resource estimates and execution context. A later retry or dead-letter
label does not replace that original result. Existing archives remain the source; no second
execution engine or network service is introduced. Old attempts without these fields stay
incomplete history rather than being reconstructed as first-pass successes.

Declare comparison dimensions before execution, for example:

```json
{"quality_tracking": {
  "sample_kind": "framework_fixture",
  "technology": ["python"],
  "risk": "low",
  "task_size": "small",
  "observation_window": "quality-fixture-v1",
  "tool_version": "pinned-project-toolchain"
}}
```

This object belongs in DAG `config`. Other sample kinds are `model_task` and `business_run`.
Missing classification stays `unclassified`; skeleton execution is always `simulation`.
These declarations describe provenance, not a proof that a fake provider is a real model.
Changed DAG, scope, model route/version, budget or observation window makes the task
incomparable. Missing comparison dimensions or actual model identity also prevents a real
model/business comparison. Framework fixtures are reported separately.

```bash
PYTHONPATH=src python3 -m ai_sdlc_claudecode.quality \
  /path/to/task-a/state.json /path/to/task-b/state.json \
  --observations /path/to/review-observations.json --output /path/to/quality-report.json
```

`--observations` is optional. Without independent oracle/review data, the corresponding
metrics are `unavailable`, not zero or 100%. The input is `{"observations": [...]}`. Each
entry binds `task_id`, `attempt_id`, `candidate_sha256`, `policy_sha256`, `reviewer`,
`independence_basis`, and `evidence: {"path": "review.txt", "sha256": "..."}`. IDs are
available in the first report; evidence paths are relative to the observations file.
The report verifies evidence bytes, not a reviewer's identity or honesty. Reviewers must
independently check the frozen expectations and raw results. A label alone is insufficient.

| Observation kind | Additional fields and effect |
| --- | --- |
| `oracle` | `classification: known_bad / known_good`; a rejected good candidate also needs `rejection_cause: rule_false_positive / business_failure / environment_failure / other`. Unknown attribution keeps the false-block rate unavailable. |
| `independent_review` | `verdict: passed / failed / pending`. A pass cannot override a failed or incomplete supervisor result. Later green candidates cannot replace the first candidate's independent result. |
| `defect_followup` | `rule_id`, `rule_version`, booleans `applicable`, `observed`, `recurred`, and nonnegative `defect_count`. Report recurrence per rule/version and fixed observation window. |
| `human_intervention` | Nonnegative `count`, including explicit zero. Missing observations mean unknown intervention count. |

Bad/good rates count unique executed candidates with cited oracle data. Recurrence counts
observed applicable tasks and also reports defect counts. First independent pass reports
terminal first-candidate verdicts plus all included, unsubmitted and pending tasks. Duplicate
state paths and identical observations do not add samples; contradictory records are errors.

Rework includes all stage attempts, including failed attempts before acceptance. Costs are
for recorded model calls: measured receipt USD, estimated USD and unpriced calls are
separate. Unknown prices never become zero actual cost; incomplete histories and changed
receipts invalidate the total. Infrastructure and unreported human costs remain outside
this monetary total. Accepted and unfinished tasks are both listed. Active attempt seconds
are summed effort, not parallel wall-clock time. Authorization waiting is separate and is
unknown while a wait remains open. The report is read-only and never promotes a quality
measurement into product acceptance or release authority.

## Completeness scanner prerequisites and boundary

The default DAG resolves `scripts/completeness-check.sh` via `PIPELINE_TOOL_DIR`, separately
from the target `PROJECT_CODE_DIR`, with both paths quoted. JS/TS/JSX/TSX function bodies
use the target module's installed `typescript`; Vue scripts also use its
`@vue/compiler-sfc`. Tool versions used by the framework fixture are TypeScript 6.0.3,
Vue compiler 3.4.21 and Node 24.22.1. For framework development these packages must be
resolvable in root `node_modules` (for example, install them locally with
`npm install --no-save --package-lock=false typescript@6.0.3 @vue/compiler-sfc@3.4.21`).
No implicit package install or fallback regex parser runs during checks.

Exit 0 means the configured scan passed; 1 means a detected violation; 2 means missing
tools, invalid input, parse failure or an unsupported source layout. A direct empty callback
argument may use exactly `/* completeness-allow-empty: specific reason */` inside its body.
Exported empty implementations cannot use that exemption. Constructor parameter properties
count as initialization. Zero JS/TS/Vue sources is explicitly not applicable to this rule.
The retained TODO, API-path, seed and mock-data scans are legacy text heuristics; they do
not prove cross-language correctness. Module-specific checks remain the T4/T5 work.

The regression seam is the actual shell entrypoint and supervisor, plus an isolated HTTP
create/replay API through S1 and final acceptance. The model is deterministic in these
fixtures; their success demonstrates framework behavior, not autonomous product delivery.
