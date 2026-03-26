# SDLC Pipeline + Self-Evolving Agent

AI-driven full-lifecycle software delivery pipeline with a self-evolving autonomous agent that learns from errors and never repeats mistakes.

## Quick Start

```bash
# 1. Install (zero external dependencies)
pip install -e .

# 2. Run the evolving agent
ai-sdlc run --feature-id my-feature --description "Add user login" --max-cost 50

# 3. Check status
ai-sdlc status
```

## SDLC Pipeline

### 13-Stage DAG

The pipeline executes software delivery as a directed acyclic graph across 13 stages:

| ID | Stage | Gate | Mode |
|----|-------|------|------|
| S1 | Requirements Analysis | ai-review | sequential |
| S2 | Architecture Design | ai-review | sequential |
| S3 | Backend Development | auto | parallel with S3b |
| S3b | Frontend Development | auto | parallel with S3 |
| S4 | Unit Testing | auto | parallel with S4b, S4c |
| S4b | Integration Testing | auto | parallel with S4, S4c |
| S4c | E2E Testing | auto | parallel with S4, S4b |
| S5 | Code Review + Security | auto | sequential |
| S6 | Deployment | human-required | sequential |
| S7 | Monitoring & Observability | ai-review | parallel with S8 |
| S8 | Documentation | ai-review | parallel with S7 |
| S9 | Performance Testing | ai-review | sequential |
| S10 | Release & Rollout | human-required | sequential |

### Execution Flow

```
S1 Requirements
  └─> S2 Architecture
        ├─> S3 Backend ──┬─> S4 Unit Test ────┐
        └─> S3b Frontend ├─> S4b Integration ──├─> S5 Review
                          └─> S4c E2E Test ────┘     └─> S6 Deploy
                                                           ├─> S7 Monitoring ──┐
                                                           ├─> S8 Docs ────────├─> S10 Release
                                                           └─> S9 Performance ─┘
```

### Gate Types

| Type | Behavior | Example |
|------|----------|---------|
| `auto` | Runs commands, checks pass/fail automatically | compile passes, tests pass |
| `ai-review` | AI agent evaluates output against checks | PRD covers NFRs, architecture has API contracts |
| `human-required` | Blocks until human approval | deployment approval, release sign-off |

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
- **Mock Mode** — validate structure without calling Claude CLI
- **Cost Tracking** — token estimation per stage, USD accumulation, hard limit ($150 default)
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

The agent **never repeats the same mistake** — every failure is recorded, analyzed, and injected as context into subsequent iterations.

### 3-Phase Execution

| Phase | Description | What Happens |
|-------|-------------|--------------|
| 1 | Mock Mode | Structure validation, no Claude CLI calls |
| 2 | Real Claude CLI | Full 13-stage pipeline execution |
| 3 | Production | Target project (e.g. ai-media-platform S3-S10) |

### Budget Controls

| Guard | Default | Flag |
|-------|---------|------|
| Max cost | $50 | `--max-cost` |
| Max runtime | 4 hours | `--max-hours` |
| Stall detection | 5 iterations without improvement | `--max-failures` |

The agent saves an **atomic checkpoint** after every iteration. On SIGTERM/SIGINT, it performs graceful shutdown — saves state and generates a report before exiting.

## Project Structure

```
ai-sdlc-claudecode/
├── pipeline-dag.json          # 13-stage DAG definition
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

### `ai-sdlc status`

Display current state: phase, iteration, cost, elapsed time, improvement trend.

### `ai-sdlc report`

Generate a markdown report at `docs/pipeline/ai-sdlc-report.md`.

### `ai-sdlc reset`

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
