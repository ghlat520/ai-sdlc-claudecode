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
The retained TODO, API-path, seed and mock-data scans are advisory text heuristics.
Declared S2 rules and actual wire probes supply the hard contract checks; legitimate
Promise operations and test fixtures are not rejected merely by those marker strings.

The regression seam is the actual shell entrypoint and supervisor, plus an isolated HTTP
create/replay API through S1 and final acceptance. The model is deterministic in these
fixtures; their success demonstrates framework behavior, not autonomous product delivery.

## Module checks, executable rules and terminal/mutation evidence (T4–T9)

`config.modules` selects real execution targets. A stage's `module_checks` maps module
IDs to a nonempty list of named commands. Example fragments:

```json
{
  "config": {
    "modules": {
      "api": {
        "path": "backend",
        "tech_stack": "python",
        "inputs": ["src", "pyproject.toml"],
        "root_inputs": ["uv.lock"],
        "artifacts": [],
        "commands": {
          "compile": "python3 -m compileall -q src",
          "lint": "ruff check src",
          "test": "python3 -m pytest",
          "coverage": "python3 -m pytest --cov=src --cov-report=term"
        },
        "coverage_threshold": 80
      }
    }
  },
  "stages": {
    "backend": {"module_checks": {"api": ["compile", "lint"]}},
    "unit": {"module_checks": {"api": ["test", "coverage"]}}
  }
}
```

These are additions to the existing complete DAG, not a new DAG schema. Module paths
and `root_inputs` are relative to the project; `inputs` and `artifacts` are relative to
the module. Shared locks and configuration belong in `root_inputs`. A module command
wins over `config.tech_stack_commands[module.tech_stack]`. A CLI `--tech-stack` selects
the default for unscoped `{{compile}}`/`{{lint}}`/`{{test}}` commands at execution time;
it does not overwrite an explicitly declared module stack. Module S4/S4b/S4c checks
must include coverage, using the same cwd and stack. Projects may use their existing
build/test/coverage tools through these command adapters.

The collector records cwd, command, exit and duration, source/shared-input hashes and
full artifact hashes. Generated caches and declared outputs do not count as source
changes. Missing inputs/outputs, unsupported paths, unknown modules, empty commands,
missing tools and failed commands block. Source, lock or artifact drift invalidates a
previous pass. Coverage commands cannot reuse an unchanged old file report. This is
local execution evidence; commands are trusted project configuration with the same
filesystem authority as the supervisor.

S2 may declare `contracts.quality_rules` (see `schemas/contracts-output.json`). Each
rule has an ID, authoritative source, failure message and explicit input paths:

```json
{
  "id": "ARCH-RENDERER-01", "kind": "imports", "language": "typescript",
  "paths": ["frontend/src"], "exclude": ["frontend/src/tests/*"],
  "forbidden": ["backend/*", "demo/*"],
  "source": "approved architecture, renderer process boundary",
  "message": "Production renderer uses the supported API"
}
```

TypeScript/JavaScript/Vue script imports use the target's TypeScript parser. Relative
paths and statically resolvable TS path aliases are compared with their resolved path
as well as the literal import. Python uses AST imports, package-relative imports and
statically resolvable `importlib.import_module` calls, including ordinary import aliases.
For a Python `src/` layout declare `import_root: "src"`. Explicit test/demo exclusions
apply before parsing. Unresolved dynamic calls in the supported import forms, parse
errors, missing parsers and zero selected files remain unverified. This checks the
supported static forms; arbitrary user-defined loaders, runtime monkey-patching and
native dependencies need the project's own analyzer/build/runtime checks. Java rule
adapters can continue using tools such as the project's existing dependency checks;
this iteration does not claim a Java AST dependency analyzer.

A `wire` rule references one S2 API endpoint with `{service, method, path}` and executes
its `command` from the project root. That adapter must perform the actual serializer or
HTTP request and emit `{method, path, status, request, response}`. The collector verifies
the endpoint, successful status, required fields and primitive JSON types. Legitimate
internal aliases are allowed. Semantic values, authorization, date formats and business
invariants remain the adapter's actual assertions. A command failure or invalid probe
output blocks. Selected rule source bytes are bound to the stage and rechecked on resume.
The full-chain regression uses a real local HTTP probe, not a stored JSON response.

Required terminal checks opt in through `project_acceptance.journeys`, keyed by existing
required check IDs. Example: `"pc_web": {"target": "pc-web", "identity": {"browser":
"chromium", "is_mobile": false}, "min_steps": 5, "max_metrics": {"create_elapsed_ms":
2000}}`. Declare only budgets the project actually requires and can measure. The report's
`journeys.pc_web` records that exact target and identity, run/attempt/candidate, actual
`steps` with `action` and `status`, optional measured `metrics`, and `evidence` entries
for `trace`, `screenshot`, `requests` and `data`. Each artifact is `{path, sha256}` beneath
the current acceptance attempt archive. The supervisor supplies `PIPELINE_CANDIDATE_SHA256`
with `PIPELINE_ACCEPTANCE_REPORT`; tools must retain these identities.

Missing/zero/skipped steps, mismatched terminal/candidate/run, stale artifacts and missing
or excessive declared metrics cannot pass. Trace bytes alone do not prove an adapter's
business assertions or a device's identity: independently inspect the driver and raw
results. PC Chromium and H5 Chromium viewport/touch emulation are verified reference
paths here. Real WebViews, native mobile packages and Electron/native desktop targets
remain project-specific integrations until actually exercised; one target cannot certify
another.

A stage may add bounded `mutation_checks`:

```json
{
  "inputs": ["src", "tests", "run_assertions.py"], "mutable_inputs": ["src"],
  "test_inputs": ["tests", "run_assertions.py"],
  "command": "python3 run_assertions.py", "validate_command": "python3 -m compileall -q src",
  "result_env": "MUTATION_RESULT", "result_file": "result.json",
  "cases": ["reject_zero"], "timeout_seconds": 30,
  "mutants": [{
    "id": "ZERO-BOUNDARY", "critical": true, "classification": "non_equivalent",
    "reason": "Zero quantity would become a valid request",
    "changes": [{"path": "src/value.py", "old": "quantity <= 0", "new": "quantity < 0"}]
  }]
}
```

The assertion adapter is included in both copied inputs and frozen test inputs. It writes `{"checks": {"reject_zero": "passed"}}` to
the path in `MUTATION_RESULT` and uses exit 0 for success or 1 for a real assertion failure.
The original candidate must pass before mutation. Copies retain original test hashes;
only explicitly mutable production paths can change. Path aliases cannot weaken that
boundary. The source candidate and its tests remain unchanged. One to sixteen selected
mutants run with a timeout of at most 120 seconds each; timed-out process groups are
terminated. This bounded adapter can wrap existing PIT/other tooling, but no PIT
integration is claimed without a real project run.

Results distinguish `killed`, `survived`, `invalid_mutation`, `execution_error`, `timeout`
and independently declared `equivalent_declared`. A valid build plus actual failed target
assertions with exit 1 is required for `killed`; arbitrary nonzero exits are not kills.
All confirmed non-equivalent critical mutants must be killed. Compile errors, tool crashes,
missing/skipped cases, changed expectations and timeouts cannot satisfy that requirement.
The stage stores the mutation report as a required receipt and rechecks the original
source binding on resume.

`tests/test_quality_delivery.py` provides the reproducible reference project and chain.
It generates isolated Java, TypeScript and Python modules; uses actual JDK compilation,
jar packaging, TypeScript compilation, HTTP/SQLite checks, deterministic operation sequences,
critical production mutations, and real Chrome traces. Stage model output is a local
fixture so no project content or credentials are sent to a model. Run just the full-chain
slice with `python3 -m pytest tests/test_quality_delivery.py -k same_candidate_full -q`.
Tests require local JDK tools, Python pytest/coverage, Node, the parser packages described
above, `playwright-core` and an installed Chrome channel. Missing prerequisites fail
visibly; they are not silently skipped or installed during a run.

The T9 fixture receipt reports its fixed good/bad candidate matrix, required behavior
coverage, drift/replay checks and five-metric data availability. It demonstrates the
framework's declared paths. A real product/model outcome study additionally needs an
approved project, frozen independent expectations, a stable observation window and model/
tool budgets; no fixture result supplies defect reduction or savings percentages for it.
