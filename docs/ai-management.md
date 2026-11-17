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
