# SDLC Pipeline + Self-Evolving Agent

AI-driven full-lifecycle software delivery pipeline with an execution supervisor that records verification evidence and reuses learned guidance.

## Quick Start

```bash
# 1. Install (includes required JSON Schema validation)
pip install -e .

# 2. Run the evolving agent
ai-sdlc run --feature-id my-feature --description "Add user login" --max-cost 50

# 3. Check status
ai-sdlc status --feature-id my-feature
```

## SDLC Pipeline

### Execution and acceptance contract

A stage `passed` means its artifact passed the configured supervisor checks. It does not prove a deployed version or business acceptance. Each result binds a `run_id`, `attempt_id`, artifact hash, DAG hash, collected check receipts and the artifact acceptance policy. Legacy `passed` records are unverified until rerun.

`complete`, `partial`, `simulated`, `human_waiting`, `paused` and `failed` describe the requested execution scope. Skips and imported inputs never count as executed passes. Parallel and sequential stages use the same verifier and locked atomic state writer.

Human gates checkpoint and return exit 3; editable `APPROVED` files are not accepted as authorization. This version has no trusted approval integration, OS sandbox or production IAM enforcement. S6 and S10 prepare artifacts; accepting those artifacts does not authorize a production release. External runtime/business feedback remains deferred.

See [the state contract and five-stage mapping](docs/unattended-state-contract.md) for the evidence boundary, invariants, verification matrix and remaining integration work.

### Model routing and existing project inputs

Project DAGs can route models to Codex while retaining the existing Claude path for unmapped models:

```json
{
  "config": {
    "review_model": "gpt-6.1-sol",
    "model_routes": {
      "gpt-6.1-sol": {"provider": "codex", "reasoning_effort": "max"},
      "glm-5.3": {"provider": "codex", "profile": "glm", "reasoning_effort": "max"}
    }
  }
}
```

The selected Codex profile must already be configured. Invocation preserves host approval, hook trust and Git checks; code runs in the project workspace sandbox and review calls use read-only mode. Prompts use stdin. Each attempt records the requested model/profile/effort, observed completion and usage, plus references to private raw logs. `actual_model` remains unknown when the CLI does not report it. Codex dollar cost is unknown rather than zero; displayed cost is a known-cost subtotal, not an all-in billing cap.

Set `writes_code: true` on implementation/test nodes so the model writes source while returning metadata JSON for the supervisor. Standard S3/S3b code nodes already use this behavior; artifact-only nodes retain response-only output. When importing an existing architecture with `--plan-file`, optional `config.imported_contracts` supplies the validated contracts object for `S2-architecture/contracts.json`; its digest is included in the imported metadata. Imported inputs remain `imported`, never executed passes.

### 18-Stage DAG

The current `pipeline-dag.json` is authoritative:

| ID | Stage | Gate | Mode |
|---|---|---|---|
| S0p | product-discovery | human-required | sequential |
| S0 | strategic-review | human-required | sequential |
| S1 | requirements | ai-review | sequential |
| S2 | architecture | ai-review | sequential |
| S2b | ui-design | ai-review | sequential |
| S3 | backend | ai-review | sequential |
| S3b | frontend | ai-review | sequential |
| S4 | testing | ai-review | parallel |
| S4b | integration-testing | ai-review | parallel |
| S4c | e2e-testing | auto+ai-review | parallel |
| S4d | smoke-test | auto | sequential |
| S4e | browser-qa | ai-review | sequential |
| S5 | review | ai-review | sequential |
| S6 | deployment | ai-review | sequential |
| S7 | monitoring | ai-review | parallel |
| S8 | documentation | ai-review | parallel |
| S9 | performance | ai-review | parallel |
| S10 | release | ai-review | sequential |

### Gate Types

| Type | Behavior | Example |
|------|----------|---------|
| `auto` | Runs commands, checks pass/fail automatically | compile passes, tests pass |
| `ai-review` | AI agent evaluates output against checks | PRD covers NFRs, architecture has API contracts |
| `human-required` | Checkpoints as pending; requires trusted approval integration | product intent and scope decisions |

### Multi-Tech Stack

Configure `tech_stack` in `pipeline-dag.json`:

| Stack | Compile | Test | Lint |
|-------|---------|------|------|
| `java-maven` | `mvn clean compile test-compile -q` | `mvn clean test` | `mvn checkstyle:check -q` |
| `node-typescript` | `npm run build` | `npm test` | `npm run lint` |
| `python` | `python -m py_compile` | `pytest` | `ruff check .` |
| `golang` | `go build ./...` | `go test ./...` | `golangci-lint run` |

### Key Features

- **Resume/Pause** — `--start-from S3` to resume from any stage
- **Simulation** — `--skeleton` avoids model calls; `--mock-review` still runs generation but cannot produce verified passes
- **Cost Tracking** — records actual usage when available, otherwise labels estimates; checks the budget before each stage call
- **Dead Letter** — after 3 retries, stage enters dead letter queue for human intervention
- **Notifications** — webhook support (DingTalk) for human_wait, dead_letter, pipeline_end

## Self-Evolving Agent

The `ai-sdlc` command wraps the SDLC pipeline with an autonomous learning loop.

### Core Concept

```
Run Pipeline ──> Collect Failures ──> Learn Patterns ──> Augment Next Run
     ^                                                        |
     └────────────────────────────────────────────────────────┘
```

Recorded failures can guide later attempts; guidance is not a guarantee of improvement. One executed attempt contributes at most one outcome per injected fix ID, including after restart and across duplicate error records. Reading results and preparing prompts do not create learning samples. The runtime does not automatically promote guidance into global skills.

### Explicit Phase Selection

| Phase | Description | What Happens |
|-------|-------------|--------------|
| 1 | Mock review | Generation with simulated acceptance; stops after the selected phase |
| 2 | Real Claude CLI | Selected feature, with actual configured checks and pending human gates |
| 3 | Later stages | The same selected feature from S3; verified/imported prerequisites are required |

### Budget Controls

| Guard | Default | Flag |
|-------|---------|------|
| Max cost | $50 | `--max-cost` |
| Max runtime | 4 hours | `--max-hours` |
| Stall detection | 5 iterations without improvement | `--max-failures` |

The agent saves an **atomic checkpoint** after every iteration. On SIGTERM/SIGINT, it performs checkpoint shutdown. The runner terminates child process groups on timeout; production supervision and external approval remain separate integration requirements.

## Project Structure

```
ai-sdlc-claudecode/
├── pipeline-dag.json          # 18-stage DAG definition
├── pipeline-executor.sh       # Main Bash executor
├── pipeline-init.sh           # Initialize feature pipeline
├── pipeline-status.sh         # Status dashboard
├── pipeline-list.sh           # List pipelines
├── pipeline-cleanup.sh        # Cleanup artifacts
├── orchestrate-parallel.sh    # Parallel stage orchestration
├── ai-review-checker.sh       # AI gate review logic
├── validate-handoff.sh        # Stage handoff validation
├── lib/
│   ├── events.sh              # JSONL event logging
│   └── protocol.sh            # Communication protocol
├── schemas/                   # JSON Schema per stage output
│   ├── requirements-output.json
│   ├── architecture-output.json
│   ├── backend-output.json
│   ├── frontend-output.json
│   ├── testing-output.json
│   ├── integration-test-output.json
│   ├── e2e-test-output.json
│   ├── review-output.json
│   ├── deployment-output.json
│   ├── monitoring-output.json
│   ├── documentation-output.json
│   ├── performance-output.json
│   └── release-output.json
├── pyproject.toml             # Python package definition
├── Makefile                   # Make targets
├── src/ai_sdlc_claudecode/
│   ├── cli.py                 # CLI entry point (ai-sdlc run/status/report/reset)
│   ├── config.py              # Configuration & path resolution
│   ├── engine.py              # Error learning engine
│   ├── runner.py              # Pipeline runner wrapper
│   └── state.py               # Immutable state management
├── tests/
│   ├── test_config.py
│   ├── test_engine.py
│   ├── test_runner.py
│   └── test_state.py
└── COMPARISON-metagpt.md      # Detailed MetaGPT comparison
```

## CLI Reference

### `ai-sdlc run`

```bash
ai-sdlc run [OPTIONS]

Options:
  --max-cost FLOAT       Max cost in USD (default: 50)
  --max-hours FLOAT      Max runtime in hours (default: 4)
  --max-failures INT     Max stall iterations (default: 5)
  --phase {1,2,3}        Start phase: 1=mock, 2=real, 3=production (default: 1)
  --feature-id TEXT      Feature ID (default: ai-sdlc-test)
  --description TEXT     Feature description
```

### `ai-sdlc status --feature-id <id>`

Display current state: phase, iteration, cost, elapsed time, improvement trend.

### `ai-sdlc report --feature-id <id>`

Generate a markdown report at `docs/pipeline/ai-sdlc-report.md`.

### `ai-sdlc reset --feature-id <id>`

Clear state for a fresh start. Use `-f` to skip confirmation.

### Make Targets

```bash
make install    # pip install -e .
make dev        # Install with dev dependencies (pytest, coverage)
make test       # Run tests with coverage
make run        # Run agent (use ARGS="--phase 1 --max-cost 10")
make status     # Show current state
make report     # Generate markdown report
make reset      # Clear state
make clean      # Remove build artifacts
```

## Architecture Highlights

### Zero External Dependencies

The Python package requires **nothing beyond stdlib** (`dependencies = []` in pyproject.toml). Dev dependencies (pytest, coverage) are optional.

The Bash pipeline requires only `bash`, `jq`, and `claude` CLI.

### Immutable Data

All state transitions use frozen dataclasses. `EvolveState.update_iteration()` returns a **new** state object — the original is never mutated.

### File System Protocol

Python and Bash communicate exclusively through the file system:
- `state.json` — pipeline execution state
- `communication.jsonl` — structured message log
- `ai-sdlc-state.json` — evolving agent checkpoint
- JSON Schema files — stage output contracts

This achieves **zero coupling** between languages while maintaining full auditability.

### Backward Compatibility

The `EVOLVE_ERRORS_DIR` environment variable allows external tools to inject error context into the pipeline without modifying any code.

## vs MetaGPT

| Dimension | MetaGPT | This Pipeline |
|-----------|---------|---------------|
| Communication | In-memory message queue | File-based JSONL (auditable, recoverable) |
| Agents | Fixed 5 roles | 160+ agent types |
| Cost control | None | Token tracking + USD limit + auto-stop |
| Gate system | None | auto / ai-review / human-required |
| Failure handling | try/except | Retry budget + dead letter + state machine |
| Resume | Start from scratch | `--start-from` any stage |
| Dependencies | `pip install metagpt` + Python ecosystem | Zero (stdlib only) |

For a detailed comparison, see [COMPARISON-metagpt.md](./COMPARISON-metagpt.md).

## License

MIT
