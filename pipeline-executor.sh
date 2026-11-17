#!/usr/bin/env bash
# =============================================================================
# pipeline-executor.sh — SDLC Pipeline DAG Executor
#
# Reads pipeline-dag.json, executes stages sequentially with:
#   - Schema-validated handoffs between stages
#   - Gate checking (auto / ai-review / human-required)
#   - Retry budget with dead-letter fallback
#   - Cost tracking with hard limits
#   - Structured JSONL event logging
#   - Per-feature state tracking (not global MEMORY.md)
#
# Usage:
#   ./pipeline-executor.sh <feature_id> <feature_description> [--dry-run]
#
# Example:
#   ./pipeline-executor.sh health-check "Add a /health endpoint that returns service status"
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PROJECT_ROOT  # needed by post_commands (e.g., completeness-check)
DAG_FILE="${PIPELINE_DAG_FILE:-${SCRIPT_DIR}/pipeline-dag.json}"
export PIPELINE_DAG_FILE="$DAG_FILE"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate-handoff.sh"

if [[ -n "${PIPELINE_STAGE_TIMEOUT_SECONDS:-}" && ! "${PIPELINE_STAGE_TIMEOUT_SECONDS}" =~ ^(0|[1-9][0-9]*)$ ]]; then
    echo 'PIPELINE_STAGE_TIMEOUT_SECONDS must be an integer number of seconds; 0 disables the stage limit.' >&2
    exit 2
fi

# shellcheck source=lib/events.sh
source "${SCRIPT_DIR}/lib/events.sh"
# shellcheck source=lib/protocol.sh
source "${SCRIPT_DIR}/lib/protocol.sh"
# Parallel executor (sourced for execute_parallel_group function)
PARALLEL_SCRIPT="${SCRIPT_DIR}/orchestrate-parallel.sh"

# --- Evolve mode: always enabled (P0 optimization: ErrorEngine default-on) ---
# EVOLVE_ERRORS_DIR is set by runner.py or defaults to per-feature evolve dir

# --- Config from DAG (single python3 call to parse all config + stage metadata) ---
export PIPELINE_ROOT="${PIPELINE_ROOT:-${PROJECT_ROOT}/docs/pipeline}"

# Cache DAG config and per-stage metadata in shell variables (P4: replaces ~60 python3 calls)
eval "$(DAG_PATH="$DAG_FILE" python3 << 'PYEOF'
import json, os, shlex, re

with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)

def assignment(key, value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError("invalid DAG identifier")
    print(key + "=" + shlex.quote(str(value)))
cfg = dag['config']
assignment("MAX_RETRIES", int(cfg["max_retries_per_stage"]))
assignment("COST_LIMIT", float(cfg["cost_limit_usd"]))
assignment("CONTEXT_BUDGET", int(cfg["context_budget_tokens"]))

for name, s in dag['stages'].items():
    sid = s['id']
    agent = s['agents'][0]
    model = agent.get('model', 'sonnet')
    timeout = s.get('timeout_seconds', cfg.get('default_stage_timeout_seconds', 600))
    max_r = s.get('max_retries', cfg['max_retries_per_stage'])
    gate = s['gate']['type']
    agent_type = agent['type']
    deps = ' '.join(s.get('dependencies', []))
    # Shell-safe variable names: replace - with _ in stage names
    safe_name = name.replace('-', '_')
    assignment(f'DAG_{safe_name}_id', f'{sid}')
    assignment(f'DAG_{safe_name}_model', f'{model}')
    assignment(f'DAG_{safe_name}_timeout', int(timeout))
    assignment(f'DAG_{safe_name}_max_retries', int(max_r))
    assignment(f'DAG_{safe_name}_gate', f'{gate}')
    assignment(f'DAG_{safe_name}_agent_type', f'{agent_type}')
    assignment(f'DAG_{safe_name}_deps', f'{deps}')
    post_cmds = json.dumps(s.get('post_commands', []))
    assignment(f'DAG_{safe_name}_post_commands', f'{post_cmds}')
    # Review passes: sequential review agents that critique and revise primary output
    rp = s.get('review_passes', [])
    print(f'DAG_{safe_name}_review_pass_count={len(rp)}')
    for i, rpass in enumerate(rp):
        assignment(f'DAG_{safe_name}_rp{i}_role', f'{rpass.get("role", "reviewer")}')
        assignment(f'DAG_{safe_name}_rp{i}_model', f'{rpass.get("model", "sonnet")}')
        assignment(f'DAG_{safe_name}_rp{i}_prompt', f'{rpass.get("prompt_file", "")}')

# Export tech_stack_commands as TECH_CMD_<key> variables
ts = cfg.get('tech_stack', 'node-typescript')
cmds = cfg.get('tech_stack_commands', {}).get(ts, {})
for key, val in cmds.items():
    assignment(f'TECH_CMD_{key}', f'{val}')

# Export evidence_required config
assignment(f'EVIDENCE_REQUIRED', f'{str(cfg.get("evidence_required", False)).lower()}')
PYEOF
)"

# --- DAG cache helpers ---
# Get cached DAG value: dag_get <stage_name> <field>
# Fields: id, model, timeout, max_retries, gate, agent_type, deps
dag_get() {
    local name="${1//-/_}"  # replace - with _
    local field="$2"
    local var="DAG_${name}_${field}"
    echo "${!var}"
}

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
MAGENTA='\033[0;35m'
NC='\033[0m'
DIM='\033[2m'

# --- Live Dashboard ---
# Renders the status panel inline during pipeline execution.
# Called after each stage completes or fails.
# Shows: progress, stage list, skip reasons, agent details, input sources,
#        fix summary, elapsed time, cost, tokens.
render_dashboard() {
    local feature_id="$1"
    FEATURE_ID="$feature_id" \
    PIPELINE_ROOT="$PIPELINE_ROOT" \
    DAG_FILE="$DAG_FILE" \
    STATE_FILE="${PIPELINE_ROOT}/${feature_id}/state.json" \
    EVENTS_FILE="${PIPELINE_ROOT}/${feature_id}/events.jsonl" \
    python3 << 'DASHEOF' 2>/dev/null || true
import json, os, unicodedata
from datetime import datetime, timezone

feature_id = os.environ["FEATURE_ID"]
pipeline_root = os.environ["PIPELINE_ROOT"]
dag_file = os.environ["DAG_FILE"]
state_file = os.environ["STATE_FILE"]
events_file = os.environ["EVENTS_FILE"]

with open(state_file) as f:
    state = json.load(f)
with open(dag_file) as f:
    dag = json.load(f)

events = []
if os.path.exists(events_file):
    with open(events_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try: events.append(json.loads(line))
                except: pass

# ── Stage metadata from DAG ──
CN = {
    "strategic-review": "战略审查", "requirements": "需求分析",
    "architecture": "架构设计", "backend": "后端开发",
    "frontend": "前端开发", "testing": "单元测试",
    "integration-testing": "集成测试", "e2e-testing": "E2E测试",
    "review": "代码评审", "deployment": "部署",
    "monitoring": "监控", "documentation": "文档",
    "performance": "性能测试", "release": "发布"
}

stages_meta = []
for name, sdef in dag["stages"].items():
    stages_meta.append({
        "id": sdef["id"], "name": name, "cn": CN.get(name, name),
        "agent": sdef["agents"][0]["type"],
        "model": sdef["agents"][0].get("model", "sonnet"),
        "gate": sdef.get("gate", {}).get("type", "auto"),
        "timeout": sdef.get("timeout_seconds", dag["config"].get("default_stage_timeout_seconds", 600)),
        "deps": sdef.get("dependencies", []),
    })

def sort_key(s):
    sid = s["id"]
    base = sid.replace("S", "").rstrip("bc")
    suffix = sid.replace("S", "").lstrip("0123456789")
    return (int(base) if base else 0, suffix)
stages_meta.sort(key=sort_key)

stages_state = state.get("stages", {})
cost = state.get("cost", {})

# ── Elapsed time ──
start_ev = next((e for e in events if e.get("event_type") == "pipeline_start"), None)
if start_ev:
    try:
        start_dt = datetime.fromisoformat(start_ev["timestamp"].replace("Z", "+00:00"))
        elapsed = datetime.now(timezone.utc) - start_dt
        total_sec = int(elapsed.total_seconds())
        if total_sec >= 3600:
            elapsed_str = f"{total_sec // 3600}:{(total_sec % 3600) // 60:02d}:{total_sec % 60:02d}"
        else:
            elapsed_str = f"{total_sec // 60}:{total_sec % 60:02d}"
    except: elapsed_str = "??:??"
else:
    elapsed_str = "00:00"

# ── Counts ──
from ai_sdlc_claudecode.state import PipelineState
scope = state.get("scope", [])
total = len(scope)
passed_ids = [sid for sid in scope if PipelineState.is_verified(stages_state.get(sid, {}), dag_file)]
skipped_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") == "skipped"]
running_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") in ("running", "gate_checking")]
failed_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") in ("failed", "dead_letter")]
waiting_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") == "human_waiting"]

effective_done = len(passed_ids)
pct = int(effective_done / total * 100) if total > 0 else 0
bar_len = 30
filled = int(bar_len * effective_done / total) if total > 0 else 0
bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

# Skip description for progress bar
skip_desc = ""
if skipped_ids:
    skip_desc = f" ({'+'.join(skipped_ids)} 跳过)"

# ── Event index: skip reasons, retry reasons, fix keywords ──
skip_reasons = {}   # stage_id → reason
retry_reasons = {}  # stage_id → last reason
fix_keywords = []   # collected fix descriptions

for ev in events:
    etype = ev.get("event_type", "")
    sid = ev.get("stage_id", "")
    msg = ev.get("message", "")

    if "skip" in etype:
        skip_reasons[sid] = msg[:40]
    if etype == "retry":
        retry_reasons[sid] = msg[:40]
    if etype == "evolve_capture" or "fix" in msg.lower() or "修复" in msg:
        kw = msg[:50]
        if kw not in fix_keywords:
            fix_keywords.append(kw)

# ── Parallel groups ──
par_groups = {}
for entry in dag.get("execution_order", []):
    if entry.get("mode") == "parallel":
        for gs in entry.get("stages", []):
            par_groups[gs] = entry["stages"]

# ── Display width (CJK + emoji aware) ──
def dw(s):
    w = 0
    for c in s:
        cp = ord(c)
        if cp in (0xFE0F, 0xFE0E, 0x200D): continue
        ea = unicodedata.east_asian_width(c)
        if ea in ('W', 'F'): w += 2
        elif 0x1F300 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF: w += 2
        else: w += 1
    return w

W = 68
def bx(text):
    pad = W - min(dw(text), W)
    return f"\u2551  {text}{' ' * max(0, pad)}\u2551"

def sep():
    return f"\u2560{'═' * (W + 2)}\u2563"

# ── Icons ──
ICONS = {
    "passed": "\u2705", "running": "\U0001f535", "gate_checking": "\U0001f50d",
    "failed": "\u274c", "dead_letter": "\U0001f480", "retrying": "\U0001f501",
    "human_waiting": "\u23f8\ufe0f", "skipped": "\u23ed\ufe0f", "pending": "\u23f3",
}

# ═══════════════ RENDER ═══════════════

# Title
print(f"\n\u2554{'═' * (W + 2)}\u2557")
print(bx(f"AI-SDLC Pipeline: {feature_id:<24s} {elapsed_str:>8s}"))
print(sep())

# Progress bar
print(bx(""))
print(bx(f"进度: [{bar}] {pct:3d}%{skip_desc}"))
print(bx(""))

# Stage list with rich status
for sm in stages_meta:
    sid = sm["id"]
    sdata = stages_state.get(sid, {})
    st = sdata.get("status", "pending")
    ic = ICONS.get(st, "?")
    retry = sdata.get("retry_count", 0)

    # ── Status detail (the key info per stage) ──
    if st == "running":
        detail = f"Claude CLI ({sm['model']}) 执行中..."
    elif st == "skipped":
        reason = skip_reasons.get(sid, "")
        if reason:
            detail = f"skipped ({reason[:30]})"
        else:
            detail = "skipped (从后续恢复)"
    elif st == "passed":
        detail = "passed"
    elif st == "failed":
        detail = f"failed (retry {retry})" if retry > 0 else "failed"
    elif st == "dead_letter":
        detail = f"dead (retry {retry}次后放弃)"
    elif st == "human_waiting":
        detail = "等待人工审核..."
    elif st == "gate_checking":
        detail = f"Gate 检查中 ({sm['gate']})"
    elif st == "retrying":
        reason = retry_reasons.get(sid, "")
        detail = f"重试中... ({reason[:25]})" if reason else "重试中..."
    else:
        detail = st

    # Parallel group bracket
    pm = ""
    if sm["name"] in par_groups:
        g = par_groups[sm["name"]]
        if sm["name"] == g[0]: pm = "┌ "
        elif sm["name"] == g[-1]: pm = "└ "
        else: pm = "│ "

    print(bx(f"{pm}{sid:<4s} {sm['cn']:<8s}  {ic}  {detail}"))

# ── Footer section ──
print(bx(""))

# Line 1: Runtime + Cost + Tokens
usd = cost.get("estimated_usd", 0.0)
tokens = cost.get("total_tokens", 0)
print(bx(f"运行时间: {elapsed_str}  |  估计总成本: ~${usd:.2f}"))

# Line 2: Fix summary (from events)
if fix_keywords:
    fix_summary = f"修复汇总: {len(fix_keywords)} 个 ({', '.join(fix_keywords[:3])})"
    if len(fix_summary) > W - 2:
        fix_summary = fix_summary[:W - 5] + "..."
    print(bx(fix_summary))

# Line 3+: Running stage agent details + input sources
for sm in stages_meta:
    sid = sm["id"]
    if stages_state.get(sid, {}).get("status") in ("running", "gate_checking"):
        print(bx(f"{sid} Agent: {sm['agent']} ({sm['model']}, timeout {sm['timeout']}s)"))

        # Input sources from dependencies
        for dep in sm["deps"]:
            dep_stage = dag["stages"].get(dep, {})
            dep_id = dep_stage.get("id", dep)
            dep_out = f"{pipeline_root}/{feature_id}/{dep_id}-{dep}/output.json"
            if os.path.exists(dep_out):
                sz = os.path.getsize(dep_out) / 1024
                dep_cn = CN.get(dep, dep)
                action = "正在生成" + CN.get(sm["name"], sm["name"])
                print(bx(f"输入: {dep_id}-{dep}/output.json ({sz:.0f}KB) → {action}"))

# Bottom border
print(f"\u255a{'═' * (W + 2)}\u255d")
DASHEOF
}

# --- Usage ---
usage() {
    cat <<EOF
Usage: $(basename "$0") <feature_id> <feature_description> [options]

Arguments:
  feature_id          Unique identifier for the feature (e.g., "health-check")
  feature_description Brief description of the feature to implement

Options:
  --dry-run          Validate DAG and show execution plan without running
  --resume           Auto-resume from last passed stage (reads state.json)
  --start-from <S>   Resume from stage S (e.g., S3)
  --stages <S1,S2>   Run only specific stages
  --cost-limit <N>   Override cost limit in USD (default: ${COST_LIMIT})
  --tech-stack <S>   Override tech stack (default: from DAG config)
  --skip-stage <S>   Skip specific stages (comma-separated, e.g., S3b,S4c)
  --mock-review      Use mock AI reviews (for CI without Claude CLI)
  --pause            Pause after current stage completes
  --force-restart    Force restart even if state.json exists (overwrites previous state)
  --spec-file <F>    Use external spec file as S1 output (skip S1, e.g. Superpowers brainstorm output)
  --plan-file <F>    Use external plan file as S2 output (skip S2, e.g. Superpowers writing-plans output)

Examples:
  $(basename "$0") health-check "Add /health endpoint returning service status"
  $(basename "$0") health-check "Add /health endpoint" --dry-run
  $(basename "$0") health-check "Add /health endpoint" --start-from S3
  $(basename "$0") health-check "Add /health endpoint" --resume
EOF
    exit 1
}

# --- DAG Validation ---
validate_dag() {
    echo -e "${CYAN}Validating DAG...${NC}"
    DAG_PATH="$DAG_FILE" SCHEMAS_BASE="$SCRIPT_DIR" python3 << 'PYEOF'
import json, sys, os

dag_path = os.environ['DAG_PATH']
schemas_base = os.environ['SCHEMAS_BASE']

with open(dag_path) as f:
    dag = json.load(f)

stages = dag['stages']
stage_ids = set(stages.keys())
errors = []

for name, stage in stages.items():
    for dep in stage.get('dependencies', []):
        if dep not in stage_ids:
            errors.append('{} depends on unknown stage: {}'.format(name, dep))

def has_cycle(node, visited, rec_stack):
    visited.add(node)
    rec_stack.add(node)
    for dep in stages[node].get('dependencies', []):
        if dep not in visited:
            if has_cycle(dep, visited, rec_stack):
                return True
        elif dep in rec_stack:
            errors.append('Cycle detected: {} -> {}'.format(node, dep))
            return True
    rec_stack.discard(node)
    return False

visited = set()
for stage_name in stages:
    if stage_name not in visited:
        has_cycle(stage_name, visited, set())

for name, stage in stages.items():
    schema_path = os.path.join(schemas_base, stage['output_schema'])
    if not os.path.exists(schema_path):
        errors.append('{}: schema not found at {}'.format(name, schema_path))

if errors:
    for e in errors:
        print('ERROR: ' + e)
    sys.exit(1)
else:
    print('DAG valid: {} stages, no cycles, all schemas present'.format(len(stages)))
    sys.exit(0)
PYEOF
}

# --- Cost estimation ---
estimate_cost() {
    local feature_id="$1"
    echo -e "\n${CYAN}=== Cost Estimate ===${NC}"
    DAG_PATH="$DAG_FILE" COST_LIM="$COST_LIMIT" python3 << 'PYEOF'
import json, os

with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)

cost_limit = float(os.environ['COST_LIM'])

# Pricing per 1M tokens (input / output separate)
PRICING = {
    'opus':   {'input': 15.0,  'output': 75.0},
    'sonnet': {'input': 3.0,   'output': 15.0},
    'haiku':  {'input': 0.80,  'output': 4.0},
}

total_tokens = 0
total_cost = 0.0
unknown_cost_stages = 0

for name, stage in dag['stages'].items():
    est = stage.get('estimated_tokens', {})
    input_tok = est.get('input', 20000)
    output_tok = est.get('output', 10000)
    total_tok = est.get('total', input_tok + output_tok)
    model = stage['agents'][0].get('model', 'sonnet')
    provider = dag['config'].get('model_routes', {}).get(model, {}).get('provider', 'claude')
    rates = PRICING.get(model) if provider == 'claude' else None
    total_tokens += int(total_tok * 1.5)
    if rates is None:
        unknown_cost_stages += 1
        print('  {} {:22s} ~{:>7,} tok  {}  USD cost unknown'.format(
            stage['id'], name, total_tok, model))
        continue

    cost_input = (input_tok / 1_000_000) * rates['input']
    cost_output = (output_tok / 1_000_000) * rates['output']
    cost = cost_input + cost_output
    cost_with_retries = cost * 1.5
    total_cost += cost_with_retries
    print('  {} {:22s} ~{:>7,} tok  {:6s}  ${:.3f} (w/retry: ${:.3f})'.format(
        stage['id'], name, total_tok, model, cost, cost_with_retries))

print('')
print('  {:22s}   Tokens: ~{:>7,}; known price subtotal: ${:.2f}'.format('', total_tokens, total_cost))
print('  {:22s}   Limit: ${:.2f}'.format('', cost_limit))
if unknown_cost_stages:
    print('  USD cost unavailable for {} stages; dollar limit covers known costs only.'.format(unknown_cost_stages))

if total_cost > cost_limit * 0.8:
    print('  Warning: Estimated cost is >80% of limit!')
PYEOF
}

# --- Build Agent prompt ---
build_prompt() {
    local stage_name="$1"
    local feature_id="$2"
    local feature_description="$3"

    local stage_output_dir="${PIPELINE_ROOT}/${feature_id}"
    local shared_context_file="${PIPELINE_ROOT}/${feature_id}/shared-context.json"

    DAG_PATH="$DAG_FILE" STG_NAME="$stage_name" OUT_DIR="$stage_output_dir" \
    FEAT_DESC="$feature_description" SCHEMAS_BASE="$SCRIPT_DIR" \
    SHARED_CTX="$shared_context_file" python3 << 'PYEOF'
import json, os, glob, sys

dag_path = os.environ['DAG_PATH']
stg_name = os.environ['STG_NAME']
out_dir = os.environ['OUT_DIR']
feat_desc = os.environ['FEAT_DESC']
schemas_base = os.environ['SCHEMAS_BASE']
shared_ctx_path = os.environ.get('SHARED_CTX', '')

with open(dag_path) as f:
    dag = json.load(f)

stage = dag['stages'][stg_name]
stage_id = stage['id']
agent = stage['agents'][0]

# Load prompt from external file if available, fallback to inline template
prompt_file = agent.get('prompt_file')
if prompt_file:
    prompt_path = os.path.join(os.path.dirname(dag_path), prompt_file)
    if os.path.exists(prompt_path):
        with open(prompt_path, encoding='utf-8') as pf:
            prompt_template = pf.read()
    else:
        prompt_template = agent.get('prompt_template', '')
else:
    prompt_template = agent.get('prompt_template', '')

# P1: Use StageSummarizer for intelligent context trimming
try:
    sys.path.insert(0, os.path.join(os.path.dirname(dag_path), 'src'))
    from ai_sdlc_claudecode.summarizer import StageSummarizer
    summarizer = StageSummarizer()
    upstream_context = summarizer.build_context(stage_id, out_dir)
except Exception:
    upstream_context = None

# Collect upstream outputs (fallback if summarizer fails)
upstream_data = {}
for dep in stage.get('dependencies', []):
    dep_stage = dag['stages'][dep]
    dep_id = dep_stage['id']
    dep_dir = os.path.join(out_dir, '{}-{}'.format(dep_id, dep))
    json_files = [os.path.join(dep_dir, 'output.json')] if os.path.isfile(os.path.join(dep_dir, 'output.json')) else []
    if json_files:
        with open(json_files[0]) as f:
            upstream_data['{}_output'.format(dep_id)] = json.dumps(json.load(f), indent=2, ensure_ascii=False)

# Template substitution
prompt = prompt_template
prompt = prompt.replace('{{feature_description}}', feat_desc)
prompt = prompt.replace('{{output_path}}', os.path.join(out_dir, '{}-{}'.format(stage_id, stg_name)))

if upstream_context:
    # P1: Smart context injection — replace template vars with summarized context
    for key, value in upstream_data.items():
        prompt = prompt.replace('{{' + key + '}}', '')  # clear template vars
    # Inject the smart context as a block
    prompt += '\n\n## Upstream Context (smart-trimmed)\n' + upstream_context
else:
    # Fallback: original truncation logic
    max_upstream_chars = int(dag.get('config', {}).get('max_upstream_chars_in_prompt', 8000))
    for key, value in upstream_data.items():
        if len(value) > max_upstream_chars:
            value = value[:max_upstream_chars] + '\n... [TRUNCATED: {} chars total, showing first {}]'.format(len(value), max_upstream_chars)
        prompt = prompt.replace('{{' + key + '}}', value)

prompt = prompt.replace('{{context_files}}', '(see project codebase)')
prompt = prompt.replace('{{module_list}}', '(auto-detect from pom.xml)')
prompt = prompt.replace('{{table_list}}', '(auto-detect from existing mappers)')
prompt = prompt.replace('{{project_dir}}', os.environ.get('PROJECT_CODE_DIR', ''))

# Inject quality lessons from accumulated deployment retrospectives
quality_lessons_path = os.path.join(os.path.dirname(dag_path), 'prompts', 'quality-lessons.md')
if os.path.exists(quality_lessons_path):
    with open(quality_lessons_path) as ql:
        prompt = prompt.replace('{{quality_lessons}}', ql.read())
else:
    prompt = prompt.replace('{{quality_lessons}}', '(no quality lessons yet)')

# Add output schema requirements
schema_path = os.path.join(schemas_base, stage['output_schema'])
with open(schema_path) as f:
    schema = json.load(f)

output_path = os.path.join(out_dir, '{}-{}'.format(stage_id, stg_name))
# P0: Inject methodology prompt fragments (Superpowers-inspired)
methods_dir = os.path.join(os.path.dirname(dag_path), 'prompts', 'methods')
methods_map_path = os.path.join(methods_dir, 'stage-methods.json')
if os.path.exists(methods_map_path):
    try:
        with open(methods_map_path) as f:
            methods_map = json.load(f)
        method_names = methods_map.get(stage_id, [])
        for method_name in method_names:
            method_file = os.path.join(methods_dir, method_name + '.md')
            if os.path.exists(method_file):
                with open(method_file) as f:
                    prompt += '\n\n' + f.read()
    except Exception:
        pass  # graceful fallback: no methods injected

prompt += '\n\nCRITICAL: Your FINAL output MUST contain a valid JSON object conforming to this schema:\n'
prompt += json.dumps(schema, indent=2)
if stage_id == 'S2':
    with open(os.path.join(schemas_base, 'schemas/contracts-output.json')) as f:
        contracts_schema = json.load(f)
    prompt += '\n\nInclude the top-level contracts payload in that SAME final JSON. '
    prompt += 'It must also satisfy this contracts schema. The supervisor will validate and '
    prompt += 'materialize contracts.json from your final JSON after refinement; do not write that file.\n'
    prompt += json.dumps(contracts_schema, indent=2)
if stage.get('writes_code', stage_id in ('S3', 'S3b')):
    prompt += '\n\nWrite implementation and test source files in the project directory within the assigned scope. '
    prompt += 'Return the stage metadata JSON in your final response; the supervisor writes output.json. '
    prompt += 'Do not claim checks passed unless you actually ran them.\n'
else:
    prompt += '\n\nDo NOT attempt to write files. Return the requested artifact JSON in your final response.\n'
prompt += '\nIMPORTANT: Output the complete metadata JSON directly inside a ```json code block. Your response will be parsed; do not truncate it.\n'
prompt += 'Output format:\n```json\n{...your complete JSON here...}\n```\n'

# P0: Inject shared memory context from parallel agents
if shared_ctx_path and os.path.exists(shared_ctx_path):
    try:
        from ai_sdlc_claudecode.memory import MemoryStore
        memory_summary = MemoryStore(shared_ctx_path).summarize()
        if memory_summary:
            prompt += '\n\n## Other Agent Progress\n' + memory_summary + '\n'
    except Exception:
        pass

if '{{feature_description}}' not in prompt_template:
    prompt += '\n\n## Current user request\n' + feat_desc + '\n'

print(prompt)
PYEOF
}

# --- Run post-commands (Layer 1: objective hard gate) ---
# Resolves {{compile}}, {{test}}, {{lint}} templates from TECH_CMD_* variables
# Returns 0 if all pass (or no commands), 1 if any fail
run_post_commands() {
    local stage_name="$1" feature_id="$2" stage_id="$3"
    local templates tmpl resolved key var cmd_exit cmd_dir
    templates=$(dag_get "$stage_name" post_commands) || return 1
    local log_file="${output_dir}/post-commands.log"
    : > "$log_file"
    local all_pass=0
    while IFS= read -r tmpl; do
        [[ -n "$tmpl" ]] || continue
        resolved="$tmpl"
        if [[ "$tmpl" =~ ^\{\{([a-z_]+)\}\}$ ]]; then
            key="${BASH_REMATCH[1]}"
            var="TECH_CMD_${key}"
            resolved="${!var:-}"
            if [[ -z "$resolved" ]]; then
                printf 'Missing configured command: %s\n' "$tmpl" >> "$log_file"
                all_pass=1
                continue
            fi
        fi
        printf 'Command: %s\n' "$resolved" >> "$log_file"
        cmd_exit=0
        cmd_dir="${PROJECT_CODE_DIR:-$PROJECT_ROOT}"
        (cd "$cmd_dir" && eval "$resolved") >> "$log_file" 2>&1 || cmd_exit=$?
        printf 'Exit: %s\n' "$cmd_exit" >> "$log_file"
        [[ $cmd_exit -eq 0 ]] || all_pass=1
    done < <(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "$templates")
    collect_evidence "$feature_id" "$stage_id" post_commands "$all_pass" "$log_file" || return 1
    POST_CMD_ERROR_OUTPUT=$(tail -40 "$log_file")
    return "$all_pass"
}

# Required checks collect their own exits; agent self-reports are not acceptance receipts.
verify_stage() {
    local stage_name="$1" feature_id="$2" stage_id="$3" output_dir="$4" gate_type="$5"
    local output_json="${output_dir}/output.json" code=0 log_file="${output_dir}/schema.log"
    bash "$VALIDATE_SCRIPT" "$stage_id" "$output_json" > "$log_file" 2>&1 || code=$?
    collect_evidence "$feature_id" "$stage_id" schema "$code" "$log_file" || return 1
    [[ $code -eq 0 ]] || return 1
    run_post_commands "$stage_name" "$feature_id" "$stage_id" || return 1
    if [[ "$stage_id" == S3 || "$stage_id" == S3b ]]; then
        local contracts_json="${PIPELINE_ROOT}/${feature_id}/S2-architecture/contracts.json"
        code=0
        python3 -m ai_sdlc_claudecode.contract_validator "$contracts_json" "${PROJECT_CODE_DIR:-$PROJECT_ROOT}" \
            > "${output_dir}/contract_violations.json" 2> "${output_dir}/contract_violations.txt" || code=$?
        collect_evidence "$feature_id" "$stage_id" contracts "$code" "${output_dir}/contract_violations.json" || return 1
        [[ $code -eq 0 ]] || return 1
    fi
    if [[ "$stage_id" == S4 || "$stage_id" == S4b || "$stage_id" == S4c ]]; then
        code=0
        PROJECT_CODE_DIR="${PROJECT_CODE_DIR:-$PROJECT_ROOT}" PIPELINE_DAG_FILE="$DAG_FILE" \
            bash "${SCRIPT_DIR}/lib/tdd-gate.sh" "$feature_id" "${PIPELINE_TECH_STACK:-node-typescript}" 80 \
            > "${output_dir}/tdd.log" 2>&1 || code=$?
        collect_evidence "$feature_id" "$stage_id" tdd "$code" "${output_dir}/tdd.log" || return 1
        [[ $code -eq 0 ]] || return 1
    fi
    if [[ "$gate_type" == human-required ]]; then
        printf 'Approval pending for run %s, attempt %s.\nTrusted approval integration is required; local marker files do not grant authorization.\n' \
            "$PIPELINE_RUN_ID" "$PIPELINE_ATTEMPT_ID" > "${output_dir}/APPROVAL_REQUIRED"
        return 3
    fi
    log_file="${output_dir}/gate.log"
    : > "$log_file"
    code=0
    case "$gate_type" in
        auto|auto+ai-review)
            local commands cmd
            commands=$(python3 - "$DAG_FILE" "$stage_name" <<'PY_GATE'
import json, sys
commands = json.load(open(sys.argv[1]))['stages'][sys.argv[2]]['gate'].get('commands', [])
if not commands:
    raise ValueError('automatic gate requires actual commands')
print('\n'.join(commands))
PY_GATE
) || code=$?
            if [[ $code -eq 0 ]]; then
                while IFS= read -r cmd; do
                    printf 'Command: %s\n' "$cmd" >> "$log_file"
                    (cd "${PROJECT_CODE_DIR:-$PROJECT_ROOT}" && eval "$cmd") >> "$log_file" 2>&1 || code=$?
                done <<< "$commands"
            fi
            ;;
        ai-review) ;;
        *) code=2; printf 'Unknown gate type\n' >> "$log_file" ;;
    esac
    if [[ $code -eq 0 && ( "$gate_type" == ai-review || "$gate_type" == auto+ai-review ) ]]; then
        bash "${SCRIPT_DIR}/ai-review-checker.sh" "$stage_id" "$output_json" --feature-id "$feature_id" \
            >> "$log_file" 2>&1 || code=$?
    fi
    collect_evidence "$feature_id" "$stage_id" gate "$code" "$log_file" || return 1
    return "$code"
}

# --- Review Passes: Sequential multi-agent review loop ---
# After primary agent generates output.json, run review agents that critique and revise
# Each review agent gets the primary output + its review prompt, and produces a revised output
run_review_passes() {
    local stage_name="$1"
    local feature_id="$2"
    local output_dir="$3"
    local stage_id="$4"

    local safe_name="${stage_name//-/_}"
    local pass_count_var="DAG_${safe_name}_review_pass_count"
    local pass_count="${!pass_count_var:-0}"

    [[ "$pass_count" -eq 0 ]] && return 0

    local output_json="${output_dir}/output.json"
    [[ ! -f "$output_json" ]] && return 0

    echo -e "  ${MAGENTA}Running ${pass_count} review pass(es)...${NC}"

    local i=0
    while [[ $i -lt $pass_count ]]; do
        local role_var="DAG_${safe_name}_rp${i}_role"
        local model_var="DAG_${safe_name}_rp${i}_model"
        local prompt_var="DAG_${safe_name}_rp${i}_prompt"
        local rp_role="${!role_var:-reviewer}"
        local rp_model="${!model_var:-sonnet}"
        local rp_prompt_file="${!prompt_var:-}"

        echo -e "  ${MAGENTA}  Review pass $((i+1))/${pass_count}: ${rp_role} (${rp_model})${NC}"

        # Build review prompt
        local review_prompt=""

        # Load review prompt from file
        if [[ -n "$rp_prompt_file" ]]; then
            local rp_path="${SCRIPT_DIR}/${rp_prompt_file}"
            [[ -f "$rp_path" ]] || return 1
            review_prompt=$(cat "$rp_path") || return 1
        fi

        # Inject the primary output as context
        local primary_output
        primary_output=$(cat "$output_json")

        local full_review_prompt
        full_review_prompt=$(cat <<REVIEW_EOF
${review_prompt}

## Primary Agent Output (to review and revise)

\`\`\`json
${primary_output}
\`\`\`

## Instructions

1. Review the primary output above through your ${rp_role} lens
2. Identify specific weaknesses, gaps, or errors
3. Produce a REVISED version of the JSON that fixes the issues you found
4. Your revised JSON must conform to the same schema as the original
5. Add a "review_${rp_role}" field to the top-level JSON documenting what you changed and why

CRITICAL: Output ONLY the revised JSON in a \`\`\`json code block. No other text.
REVIEW_EOF
)

        # Execute review agent
        local review_output
        local review_exit=0

        if [[ "${PIPELINE_SKELETON_MODE:-false}" == "true" ]]; then
            echo -e "    ${YELLOW}[SKELETON] Skipping review pass${NC}"
            i=$((i + 1))
            continue
        fi

        local rp_timeout=300  # 5 min per review pass
        local rp_receipt="${output_dir}/.attempts/${PIPELINE_ATTEMPT_ID}/refinement-${i}-model.json"
        review_output=$(printf '%s' "$full_review_prompt" | python3 -m ai_sdlc_claudecode.agent \
            --dag "$DAG_FILE" --model "$rp_model" --project-dir "${PROJECT_CODE_DIR:-$PROJECT_ROOT}" \
            --sandbox read-only --output-format text --timeout "$rp_timeout" --receipt "$rp_receipt" 2>&1) || review_exit=$?

        if [[ $review_exit -eq 0 ]]; then
            # Try to extract revised JSON and replace output.json
            local revised_json="${output_dir}/review-${rp_role}.json"
            rm -f "$revised_json"
            echo "$review_output" | python3 -m ai_sdlc_claudecode extract-json "$revised_json" 2>/dev/null || return 1

            if [[ -f "$revised_json" ]]; then
                # Validate the revised JSON has the correct stage_id
                if python3 -c "import json; d=json.load(open('${revised_json}')); assert d.get('stage_id') == '${stage_id}'" 2>/dev/null; then
                    cp "$revised_json" "$output_json"
                    echo -e "    ${GREEN}✓ Review pass ${rp_role}: output revised${NC}"
                    emit_event "$feature_id" "review_pass" "$stage_id" "Review pass ${rp_role} revised output"

                    local rp_provider
                    rp_provider=$(python3 -m ai_sdlc_claudecode.agent --dag "$DAG_FILE" --model "$rp_model" --inspect provider) || return 1
                    if [[ "$rp_provider" == codex ]]; then
                        emit_event "$feature_id" token_usage "$stage_id" "Refinement usage in ${rp_receipt}; USD cost unknown" || true
                    else
                        local rp_tokens=$(( (${#full_review_prompt} + ${#review_output}) / 4 ))
                        update_cost "$feature_id" "$rp_tokens" "$rp_model" || true
                    fi
                else
                    echo -e "    ${RED}Review pass ${rp_role}: invalid revision${NC}"
                    return 1
                fi
            else
                echo -e "    ${RED}Review pass ${rp_role}: no revision${NC}"
                return 1
            fi
        else
            echo -e "    ${RED}Review pass ${rp_role}: agent failed (exit ${review_exit})${NC}"
            return 1
        fi

        i=$((i + 1))
    done

    echo -e "  ${MAGENTA}Review passes complete${NC}"
    return 0
}

# --- Execute a single stage ---
execute_stage() {
    local stage_name="$1"
    local feature_id="$2"
    local feature_description="$3"
    local retry_count=0

    # Use cached DAG values (P4: zero python3 calls)
    local stage_id
    stage_id=$(dag_get "$stage_name" "id")
    local max_retry
    max_retry=$(dag_get "$stage_name" "max_retries")
    local agent_type
    agent_type=$(dag_get "$stage_name" "agent_type")
    local agent_model
    agent_model=$(dag_get "$stage_name" "model")
    local gate_type
    gate_type=$(dag_get "$stage_name" "gate")

    local output_dir="${PIPELINE_ROOT}/${feature_id}/${stage_id}-${stage_name}"
    mkdir -p "$output_dir"

    # Diagnostic retry: track previous failure context
    local prev_error_output=""
    local prev_exit_code=""

    echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║  Stage: ${stage_id} - ${stage_name}${NC}"
    echo -e "${BOLD}${CYAN}║  Agent: ${agent_type} (${agent_model})${NC}"
    echo -e "${BOLD}${CYAN}║  Gate:  ${gate_type}${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${NC}"

    while [[ $retry_count -le $max_retry ]]; do
        PIPELINE_ATTEMPT_ID=$(_pipeline_state begin "$feature_id" "$PIPELINE_RUN_ID" "$stage_id" "$output_dir" "$retry_count") || return 1
        export PIPELINE_ATTEMPT_ID
        if ! _pipeline_state dependencies "$feature_id" "$stage_id" "$DAG_FILE"; then
            set_stage_state "$feature_id" "$stage_id" unverified "$retry_count" || return 1
            return 4
        fi
        # Check cost limit
        if ! check_cost_limit "$feature_id" "$COST_LIMIT" >/dev/null 2>&1; then
            emit_event "$feature_id" "cost_exceeded" "$stage_id" "Cost limit exceeded, stopping pipeline"
            set_stage_state "$feature_id" "$stage_id" "dead_letter" "$retry_count"
            echo -e "${RED}[STOP] Cost limit (\$${COST_LIMIT}) exceeded${NC}"
            return 1
        fi

        if [[ $retry_count -gt 0 ]]; then
            echo -e "${YELLOW}  Retry ${retry_count}/${max_retry}...${NC}"
            emit_event "$feature_id" "retry" "$stage_id" "Retry ${retry_count}/${max_retry}"
        fi

        emit_event "$feature_id" "stage_start" "$stage_id" "Starting ${stage_name} (attempt $((retry_count + 1)))"

        # Protocol: Commander dispatches task to Agent
        send_message "$feature_id" "Commander" "$agent_type" "$MSG_REQUEST" \
            "Execute ${stage_name}: ${feature_description}"

        # Route upstream outputs (MetaGPT-style handoff) — using cached deps
        local deps_list
        deps_list=$(dag_get "$stage_name" "deps")
        for dep in $deps_list; do
            local dep_id
            dep_id=$(dag_get "$dep" "id")
            local dep_output="${PIPELINE_ROOT}/${feature_id}/${dep_id}-${dep}/output.json"
            if [[ -f "$dep_output" ]]; then
                route_handoff "$feature_id" "$dep" "$stage_name" "$dep_output"
            fi
        done

        # Build the prompt
        local prompt
        prompt=$(build_prompt "$stage_name" "$feature_id" "$feature_description")

        # --- Prompt layout (optimization 12: prefix-cache friendly) ---
        # STABLE PREFIX (cacheable across retries): base prompt = methods + template + upstream
        # VARIABLE SUFFIX (per-retry):              augment + diagnostic
        # Rationale: Anthropic prompt caching reuses the longest matching prefix across calls.
        # Prepending variable content invalidates the cache every retry; appending preserves it.
        # Expected impact: cache_read_input_tokens/input_tokens climbs ~5% → >60% → cost -40%.

        # Collect variable-suffix fragments (applied to prompt tail, not head)
        local evolve_dir="${EVOLVE_ERRORS_DIR:-${PIPELINE_ROOT}/${feature_id}/evolve}"
        unset PIPELINE_LAST_APPLIED_FIXES  # reset each attempt

        local aug_suffix=""
        if [[ -f "${evolve_dir}/augments/${stage_id}.json" ]]; then
            local augment_json aug_txt aug_ids
            augment_json="${output_dir}/.attempts/${PIPELINE_ATTEMPT_ID}/augment.json"
            cp "${evolve_dir}/augments/${stage_id}.json" "$augment_json" || return 1
            aug_txt=$(python3 -c "import json; d=json.load(open('${augment_json}')); print(d.get('injection',''), end='')" 2>/dev/null || cat "${evolve_dir}/augments/${stage_id}.txt" 2>/dev/null)
            aug_ids=$(python3 -c "import json; d=json.load(open('${augment_json}')); print(','.join(d.get('fix_ids',[])))" 2>/dev/null || echo "")
            if [[ -n "$aug_txt" ]]; then
                aug_suffix="$aug_txt"
                export PIPELINE_LAST_APPLIED_FIXES="$aug_ids"
            fi
        elif [[ -f "${evolve_dir}/augments/${stage_id}.txt" ]]; then
            aug_suffix=$(cat "${evolve_dir}/augments/${stage_id}.txt")
        fi

        local diag_suffix=""
        if [[ $retry_count -gt 0 && -n "$prev_error_output" ]]; then
            local diag_methods_dir="${SCRIPT_DIR}/prompts/methods"
            local diag_fragment=""
            if [[ -f "${diag_methods_dir}/diagnostic-retry.md" ]]; then
                diag_fragment=$(cat "${diag_methods_dir}/diagnostic-retry.md")
            fi
            diag_suffix=$(cat <<DIAG_EOF

## DIAGNOSTIC RETRY CONTEXT (Attempt $((retry_count + 1)))

**Previous attempt failed.** You MUST NOT repeat the same approach.

### Previous Failure Info
- **Exit code**: ${prev_exit_code}
- **Attempt**: ${retry_count} of ${max_retry}
- **Error output** (last 1000 chars):
\`\`\`
${prev_error_output: -1000}
\`\`\`

### <HARD-GATE>
If this is attempt 2+, you MUST change your approach. Doing the exact same thing
that failed before is PROHIBITED. Analyze the error, identify the root cause,
and apply a targeted fix.
</HARD-GATE>

${diag_fragment}
DIAG_EOF
)
            echo -e "  ${YELLOW}  [DIAGNOSTIC] Injected failure context from attempt ${retry_count}${NC}"
        fi

        # Append variable fragments to tail (STABLE prefix + VARIABLE suffix)
        if [[ -n "$aug_suffix" ]]; then
            prompt="${prompt}

---
## Learned Guidance (based on prior runs)
${aug_suffix}"
        fi
        if [[ -n "$diag_suffix" ]]; then
            prompt="${prompt}

---
${diag_suffix}"
        fi

        # Set scope lock to stage output directory + feature directory
        export PIPELINE_SCOPE_LOCK="${output_dir},${PIPELINE_ROOT}/${feature_id}"

        # Execute via claude --print (headless) or skeleton mode
        local start_time
        start_time=$(date +%s)

        # Get stage timeout (from DAG cache)
        local stage_timeout
        stage_timeout="${PIPELINE_STAGE_TIMEOUT_SECONDS:-$(dag_get "$stage_name" "timeout")}"

        local claude_output
        local claude_exit=0

        if [[ "${PIPELINE_SKELETON_MODE:-false}" == "true" ]]; then
            # Skeleton mode: generate minimal valid JSON from schema without Claude API
            echo -e "  ${YELLOW}[SKELETON] Generating skeleton output for ${stage_id}...${NC}"
            local skeleton_json
            skeleton_json=$(STAGE_ID="$stage_id" FEATURE_ID="$feature_id" SCHEMA_BASE="${SCRIPT_DIR}" DAG_PATH="$DAG_FILE" STAGE_NAME="$stage_name" python3 << 'SKELPYEOF'
import json, os, datetime

stage_id = os.environ['STAGE_ID']
feature_id = os.environ['FEATURE_ID']
dag_path = os.environ['DAG_PATH']
stage_name = os.environ['STAGE_NAME']
schema_base = os.environ['SCHEMA_BASE']

with open(dag_path) as f:
    dag = json.load(f)
stage = dag['stages'][stage_name]
schema_path = os.path.join(schema_base, stage['output_schema'])
with open(schema_path) as f:
    schema = json.load(f)

def gen_skeleton(schema, depth=0):
    """Generate minimal valid JSON from JSON Schema."""
    t = schema.get('type', 'object')
    if 'const' in schema:
        return schema['const']
    if 'enum' in schema:
        return schema['enum'][0]
    if t == 'object':
        obj = {}
        for prop in schema.get('required', []):
            prop_schema = schema.get('properties', {}).get(prop, {'type': 'string'})
            obj[prop] = gen_skeleton(prop_schema, depth+1)
        return obj
    elif t == 'array':
        items_schema = schema.get('items', {'type': 'string'})
        min_items = schema.get('minItems', 1)
        return [gen_skeleton(items_schema, depth+1) for _ in range(min_items)]
    elif t == 'string':
        if schema.get('format') == 'date-time':
            return datetime.datetime.now().isoformat()
        if schema.get('minLength', 0) > 0:
            return f'skeleton-{stage_id}'
        return f'skeleton-{stage_id}-placeholder'
    elif t == 'integer':
        return max(schema.get('minimum', 0), 1)
    elif t == 'number':
        return 1.0
    elif t == 'boolean':
        return True
    return None

skeleton = gen_skeleton(schema)
# Ensure stage_id and feature_id are correct
if isinstance(skeleton, dict):
    skeleton['stage_id'] = stage_id
    skeleton['feature_id'] = feature_id
    skeleton['timestamp'] = datetime.datetime.now().isoformat()
    skeleton['status'] = 'complete'

output = json.dumps(skeleton, indent=2, ensure_ascii=False)
print('```json')
print(output)
print('```')
print()
print('### VERIFICATION_EVIDENCE')
print('| Command | Exit Code | Key Output |')
print('|---------|-----------|------------|')
print(f'| skeleton-generator | 0 | SKELETON: {stage_id} generated from schema |')
print()
print('### VERIFICATION_STATUS: VERIFIED')
SKELPYEOF
) || claude_exit=$?
            claude_output="$skeleton_json"
        else
            local timeout_label="${stage_timeout}s"
            [[ "$stage_timeout" != 0 ]] || timeout_label="unlimited"
            echo -e "  ${YELLOW}Invoking model (${agent_model}, timeout: ${timeout_label})...${NC}"
            local response_file="${output_dir}/agent-response.json"
            local model_receipt="${output_dir}/.attempts/${PIPELINE_ATTEMPT_ID}/agent-model.json"
            local dispatch_log="${output_dir}/agent-dispatch.log"
            printf '%s' "$prompt" | python3 -m ai_sdlc_claudecode.agent \
                --dag "$DAG_FILE" --model "$agent_model" --project-dir "${PROJECT_CODE_DIR:-$PROJECT_ROOT}" \
                --sandbox workspace-write --output-format json --timeout "$stage_timeout" \
                --receipt "$model_receipt" > "$response_file" 2> "$dispatch_log" || claude_exit=$?

            local parsed_cost="" parsed_in="" parsed_out="" parsed_cr="" parsed_cc="" parsed_provider=""
            local metrics
            metrics=$(python3 - "$response_file" <<'PY_METRICS'
import json, sys
with open(sys.argv[1]) as stream:
    response = json.load(stream)
usage = response.get('usage') or {}
cost = response.get('total_cost_usd')
print(cost if cost is not None else 'unknown', usage.get('input_tokens', 0),
      usage.get('output_tokens', 0), usage.get('cache_read_input_tokens', 0),
      usage.get('cache_creation_input_tokens', 0), response.get('provider', 'unknown'), sep='\t')
PY_METRICS
) || metrics=""
            if [[ -n "$metrics" ]]; then
                IFS=$'\t' read -r parsed_cost parsed_in parsed_out parsed_cr parsed_cc parsed_provider <<< "$metrics"
                [[ "$parsed_cost" == unknown ]] && parsed_cost=""
                claude_output=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("result", ""))' "$response_file") || claude_exit=1
            else
                claude_output=$(cat "$dispatch_log" "$response_file")
                [[ $claude_exit -ne 0 ]] || claude_exit=1
            fi
            if [[ $claude_exit -eq 124 && "$stage_timeout" != 0 ]]; then
                echo -e "  ${RED}Stage timed out after ${stage_timeout}s${NC}"
                emit_event "$feature_id" "stage_timeout" "$stage_id" "Timed out after ${stage_timeout}s"
                set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
                send_notification "$feature_id" "dead_letter" "Stage ${stage_id} timed out after ${stage_timeout}s"
                prev_error_output="TIMEOUT after ${stage_timeout}s. ${claude_output: -500}"
                prev_exit_code="124 (timeout)"
                retry_count=$((retry_count + 1))
                continue
            fi
        fi

        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))

        # Cost tracking: prefer real usage from claude JSON, fallback to char/4 estimate
        if [[ -n "${parsed_cost:-}" ]]; then
            update_cost_real "$feature_id" "$parsed_cost" "$parsed_in" "$parsed_out" "$parsed_cr" "$parsed_cc" "$agent_model" || true
            local total_t=$((${parsed_in:-0} + ${parsed_out:-0} + ${parsed_cr:-0} + ${parsed_cc:-0}))
            emit_event "$feature_id" "cost_update" "$stage_id" "Real: \$${parsed_cost} (${total_t}t, cache_read=${parsed_cr:-0})" "{\"cost_usd\": ${parsed_cost}, \"input\": ${parsed_in:-0}, \"output\": ${parsed_out:-0}, \"cache_read\": ${parsed_cr:-0}, \"cache_creation\": ${parsed_cc:-0}, \"duration\": ${duration}, \"source\": \"claude_json\"}" || true
        elif [[ "${parsed_provider:-}" == codex ]]; then
            emit_event "$feature_id" token_usage "$stage_id" "Codex token usage recorded; USD cost unknown" \
                "{\"cost_usd\": null, \"input\": ${parsed_in:-0}, \"output\": ${parsed_out:-0}, \"cache_read\": ${parsed_cr:-0}, \"duration\": ${duration}, \"source\": \"codex_json\"}" || true
        else
            local est_tokens=$(( (${#prompt} + ${#claude_output}) / 4 ))
            update_cost "$feature_id" "$est_tokens" "$agent_model" || true
            emit_event "$feature_id" "cost_update" "$stage_id" "Est: ~${est_tokens}t" "{\"tokens\": ${est_tokens}, \"duration\": ${duration}, \"source\": \"estimated\"}" || true
        fi

        if [[ $claude_exit -ne 0 ]]; then
            printf '%s\n' "$claude_output" > "${output_dir}/agent-failure.log"
            collect_evidence "$feature_id" "$stage_id" agent "$claude_exit" "${output_dir}/agent-failure.log" || return 1
            echo -e "  ${RED}Model invocation failed (exit: ${claude_exit})${NC}"
            emit_event "$feature_id" "stage_fail" "$stage_id" "Agent failed with exit code ${claude_exit}"
            set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"

            # Capture for diagnostic retry
            prev_error_output="$claude_output"
            prev_exit_code="$claude_exit"

            if [[ "${PIPELINE_MOCK_REVIEW:-false}" == true ]]; then
                retry_count=$((retry_count + 1))
                continue
            fi
            # Real-time error capture for an actual failed invocation.
            local evolve_dir="${EVOLVE_ERRORS_DIR:-${PIPELINE_ROOT}/${feature_id}/evolve}"
            mkdir -p "${evolve_dir}/failures"
            local fail_ts
            fail_ts=$(date +%s)
            echo "$claude_output" > "${evolve_dir}/failures/${stage_id}-${fail_ts}.txt"
            echo "$claude_exit" > "${evolve_dir}/failures/${stage_id}-${fail_ts}.exit"

            # Immediate error analysis — learn from failure for next retry
            python3 -c "
import sys
sys.path.insert(0, '${SCRIPT_DIR}/src')
from ai_sdlc_claudecode.engine import ErrorEngine
from pathlib import Path
try:
    e = ErrorEngine(Path('${evolve_dir}'))
    e.capture_realtime('${stage_id}', ${claude_exit}, sys.stdin.read(), '${feature_id}')
except Exception:
    pass
" <<< "$claude_output" 2>/dev/null || true

            retry_count=$((retry_count + 1))
            continue
        fi

        # Try to extract JSON output from Claude's response
        # Check if output file was created, or try to extract from response
        local output_json="${output_dir}/output.json"
        if [[ "$stage_id" == S2 || ! -f "$output_json" ]]; then
            [[ "$stage_id" != S2 ]] || rm -f "$output_json"
            echo "$claude_output" | python3 -m ai_sdlc_claudecode extract-json "$output_json" 2>/dev/null || {
                echo -e "  ${YELLOW}Warning: Could not extract structured output${NC}"
                # Save raw output for debugging
                echo "$claude_output" > "${output_dir}/raw_output.txt"
            }
        fi

        if [[ "${PIPELINE_SKELETON_MODE:-false}" == true || "${PIPELINE_MOCK_REVIEW:-false}" == true ]]; then
            set_stage_state "$feature_id" "$stage_id" simulated "$retry_count" || return 1
            return 0
        fi

        # Refinement belongs to generation; only verify_stage accepts the final artifact.
        local refinement_exit=0
        run_review_passes "$stage_name" "$feature_id" "$output_dir" "$stage_id" > "${output_dir}/refinement.log" 2>&1 || refinement_exit=$?
        local contracts_exit=0
        if [[ "$stage_id" == S2 && $refinement_exit -eq 0 ]]; then
            # Finalize both artifacts before collecting any output-bound receipt.
            python3 - "$output_json" "${SCRIPT_DIR}/schemas/contracts-output.json" > "${output_dir}/contracts.log" 2>&1 <<'PY_CONTRACTS' || contracts_exit=$?
import hashlib, json, sys
from pathlib import Path
from jsonschema import Draft202012Validator

output_path, schema_path = map(Path, sys.argv[1:])
output = json.loads(output_path.read_text())
document = {key: output[key] for key in ('stage_id', 'feature_id', 'timestamp', 'contracts')}
Draft202012Validator(json.loads(schema_path.read_text())).validate(document)
contract_path = output_path.with_name('contracts.json')
contract_path.write_text(json.dumps(document, indent=2, ensure_ascii=False))
artifacts = output.setdefault('artifacts', [])
if 'contracts.json' not in artifacts:
    artifacts.append('contracts.json')
output['contracts_sha256'] = hashlib.sha256(contract_path.read_bytes()).hexdigest()
output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
print('Final S2 contracts validated and materialized')
PY_CONTRACTS
            collect_evidence "$feature_id" "$stage_id" contracts "$contracts_exit" "${output_dir}/contracts.log" || return 1
        fi
        if [[ $(dag_get "$stage_name" review_pass_count) -gt 0 ]]; then
            collect_evidence "$feature_id" "$stage_id" refinement "$refinement_exit" "${output_dir}/refinement.log" || return 1
        fi
        if [[ $refinement_exit -ne 0 ]]; then
            set_stage_state "$feature_id" "$stage_id" failed "$retry_count" || return 1
            prev_error_output="Configured refinement review failed"
            prev_exit_code="review_pass_failed"
            retry_count=$((retry_count + 1))
            continue
        fi
        local check_exit="$contracts_exit"
        if [[ $check_exit -eq 0 ]]; then
            verify_stage "$stage_name" "$feature_id" "$stage_id" "$output_dir" "$gate_type" || check_exit=$?
        fi
        if [[ $check_exit -eq 3 && "$gate_type" == human-required ]]; then
            set_stage_state "$feature_id" "$stage_id" human_waiting "$retry_count" || return 1
            set_pipeline_state "$feature_id" human_waiting "Approval required: ${stage_id}" || return 1
            emit_event "$feature_id" human_wait "$stage_id" "Approval request saved; no approval was granted"
            return 3
        elif [[ $check_exit -eq 0 ]]; then
            set_stage_state "$feature_id" "$stage_id" passed "$retry_count" || return 1
            emit_event "$feature_id" stage_pass "$stage_id" "Configured stage checks passed; business acceptance not evaluated"
            return 0
        fi
        set_stage_state "$feature_id" "$stage_id" failed "$retry_count" || return 1
        prev_error_output="Required verification failed (exit ${check_exit}); inspect ${output_dir}/*.log"
        prev_exit_code="$check_exit"
        retry_count=$((retry_count + 1))
    done

    # Max retries exceeded → dead letter
    emit_event "$feature_id" "dead_letter" "$stage_id" "Max retries (${max_retry}) exceeded"
    set_stage_state "$feature_id" "$stage_id" "dead_letter" "$retry_count"
    echo -e "  ${RED}[DEAD LETTER] Stage ${stage_id} failed after ${max_retry} retries${NC}"

    send_notification "$feature_id" "dead_letter" "Stage ${stage_id} (${stage_name}) failed after ${max_retry} retries. Manual intervention required."

    # Post-stage-fail hook (non-blocking, records structured dead_letter + optional hermes notify)
    if [[ -x "${PROJECT_ROOT}/lib/hooks/post-stage-fail.sh" ]]; then
        bash "${PROJECT_ROOT}/lib/hooks/post-stage-fail.sh" \
            "$feature_id" "$stage_id" "$retry_count" "max_retries_exceeded" \
            >/dev/null 2>&1 || true
    fi

    # Write dead letter
    local dead_letter_file="${output_dir}/DEAD_LETTER"
    cat > "$dead_letter_file" <<DL
Stage ${stage_id} (${stage_name}) exceeded max retries (${max_retry}).
Feature: ${feature_id}
Time: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

Manual intervention required. Review logs at:
  ${PIPELINE_ROOT}/${feature_id}/events.jsonl

To retry: ./pipeline-executor.sh ${feature_id} "${feature_description}" --start-from ${stage_id}
DL

    # Always capture failure for evolve learning
    local evolve_dir="${PIPELINE_ROOT}/${feature_id}/evolve/failures"
    mkdir -p "$evolve_dir"
    local fail_ts
    fail_ts=$(date +%s)
    cat > "${evolve_dir}/${stage_id}-${fail_ts}.json" <<EVOLVE_JSON
{
  "stage_id": "${stage_id}",
  "stage_name": "${stage_name}",
  "feature_id": "${feature_id}",
  "failure_type": "max_retries_exceeded",
  "max_retries": ${max_retry},
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "dead_letter_path": "${dead_letter_file}"
}
EVOLVE_JSON
    emit_event "$feature_id" "evolve_capture" "$stage_id" "Failure captured for evolve learning"

    return 1
}

# --- Main ---
main() {
    local feature_id=""
    local feature_description=""
    local dry_run=false
    local start_from=""
    local specific_stages=""
    local auto_resume=false
    local tech_stack=""
    local pause_after=false
    local skip_stages=""
    local mock_review=false
    local skeleton_mode=false
    local force_restart=false
    local spec_file=""
    local plan_file=""
    local project_dir=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) dry_run=true; shift ;;
            --resume) auto_resume=true; shift ;;
            --start-from) start_from="$2"; shift 2 ;;
            --stages) specific_stages="$2"; shift 2 ;;
            --cost-limit) COST_LIMIT="$2"; shift 2 ;;
            --tech-stack) tech_stack="$2"; shift 2 ;;
            --project-dir) project_dir="$2"; shift 2 ;;
            --skip-stage) skip_stages="$2"; shift 2 ;;
            --mock-review) mock_review=true; shift ;;
            --skeleton) skeleton_mode=true; mock_review=true; shift ;;
            --pause) pause_after=true; shift ;;
            --force-restart) force_restart=true; shift ;;
            --spec-file) spec_file="$2"; shift 2 ;;
            --plan-file) plan_file="$2"; shift 2 ;;
            --help|-h) usage ;;
            *)
                if [[ -z "$feature_id" ]]; then
                    feature_id="$1"
                elif [[ -z "$feature_description" ]]; then
                    feature_description="$1"
                else
                    echo "Unknown argument: $1"
                    usage
                fi
                shift ;;
        esac
    done

    if [[ -z "$feature_id" || -z "$feature_description" ]]; then
        usage
    fi

    if [[ ! "$feature_id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]]; then
        echo "Invalid feature_id: use letters, numbers, underscore or hyphen" >&2
        return 2
    fi

    # Resolve project_dir: CLI arg > state.json > default (sibling of ai-sdlc-claudecode)
    if [[ -z "$project_dir" ]]; then
        # Try reading from state.json
        local state_file="${PIPELINE_ROOT}/${feature_id}/state.json"
        if [[ -f "$state_file" ]]; then
            project_dir=$(python3 -c "import json; print(json.load(open('${state_file}')).get('project_dir', ''))" 2>/dev/null || echo "")
        fi
    fi
    if [[ -z "$project_dir" ]]; then
        project_dir="$(cd "${PROJECT_ROOT}/.." && pwd)/${feature_id}"
    fi
    export PROJECT_CODE_DIR="$project_dir"
    echo -e "${CYAN}Code output directory: ${PROJECT_CODE_DIR}${NC}"

    # Validate DAG
    if ! validate_dag; then
        echo -e "${RED}DAG validation failed. Aborting.${NC}"
        exit 1
    fi

    # Resume retains the originally selected scope; each invocation still has a fresh run ID.
    if $auto_resume && [[ -z "$specific_stages" && -f "${PIPELINE_ROOT}/${feature_id}/state.json" ]]; then
        specific_stages=$(python3 -c 'import json,sys; print(",".join(json.load(open(sys.argv[1])).get("scope", [])))' "${PIPELINE_ROOT}/${feature_id}/state.json")
    fi

    # Read tech_stack from DAG config if not overridden
    if [[ -z "$tech_stack" ]]; then
        tech_stack=$(python3 -c "import json; print(json.load(open('${DAG_FILE}')).get('config', {}).get('tech_stack', 'java-maven'))" 2>/dev/null || echo "java-maven")
    fi
    export PIPELINE_TECH_STACK="$tech_stack"
    export PIPELINE_MOCK_REVIEW="$mock_review"
    export PIPELINE_SKELETON_MODE="$skeleton_mode"

    # Get execution order
    local stages_ordered
    stages_ordered=$(DAG_PATH="$DAG_FILE" python3 -c "
import json, os
with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)
for item in dag['execution_order']:
    print(item.get('stage', ''))
")

    # Estimate cost
    estimate_cost "$feature_id"

    if $dry_run; then
        echo -e "\n${CYAN}=== Dry Run: Execution Plan ===${NC}"
        DAG_PATH="$DAG_FILE" python3 << 'PYEOF'
import json, os

with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)

idx = 1
for item in dag['execution_order']:
    mode = item.get('mode', 'sequential')
    if mode == 'parallel' and 'stages' in item:
        stages_list = item['stages']
        ids = [dag['stages'][s]['id'] for s in stages_list]
        deps = set()
        for s in stages_list:
            deps.update(dag['stages'][s].get('dependencies', []))
        pair_str = ' + '.join('{} {}'.format(i, n) for i, n in zip(ids, stages_list))
        dep_str = ', '.join(deps) or 'none'
        print('  {}. PARALLEL [{}] (depends: {})'.format(idx, pair_str, dep_str))
        idx += 1
    else:
        for s in item.get('stages', [item.get('stage')]):
            sid = dag['stages'][s]['id']
            d = ', '.join(dag['stages'][s].get('dependencies', [])) or 'none'
            gate = dag['stages'][s]['gate']['type']
            print('  {}. {} {} (depends: {}) [gate: {}]'.format(idx, sid, s, d, gate))
            idx += 1
PYEOF
        echo -e "\n  ${CYAN}Communication protocol: MetaGPT-style message passing enabled${NC}"
        echo -e "  ${CYAN}  Commander -> Agent: request with upstream artifacts${NC}"
        echo -e "  ${CYAN}  Agent -> Commander: response with output path${NC}"
        echo -e "  ${CYAN}  Commander -> Downstream: handoff with verified artifact${NC}"
        echo -e "\n${GREEN}Dry run complete. No changes made.${NC}"
        exit 0
    fi

    # Initialize pipeline
    mkdir -p "${PIPELINE_ROOT}/${feature_id}"

    local state_file="${PIPELINE_ROOT}/${feature_id}/state.json"

    # Detect existing state.json to prevent accidental overwrites
    if [[ -f "$state_file" && "$force_restart" != "true" && -z "$start_from" && "$auto_resume" != "true" ]]; then
        local existing_pipeline_state
        existing_pipeline_state=$(python3 -c "
import json
with open('${state_file}') as f:
    state = json.load(f)
stages = state.get('stages', {})
passed = sum(1 for s in stages.values() if s.get('status') == 'passed')
total = len(stages)
last_update = state.get('updated_at', 'unknown')
print(f'{passed}/{total} stages passed, last updated: {last_update}')
" 2>/dev/null || echo "unknown state")

        echo -e "${YELLOW}WARNING: Existing pipeline state found for '${feature_id}'${NC}"
        echo -e "${YELLOW}  Status: ${existing_pipeline_state}${NC}"
        echo -e "${YELLOW}  Options:${NC}"
        echo -e "${YELLOW}    --resume         Auto-resume from last passed stage${NC}"
        echo -e "${YELLOW}    --start-from <S> Resume from specific stage${NC}"
        echo -e "${YELLOW}    --force-restart  Overwrite existing state and start fresh${NC}"
        echo -e "${RED}Aborting to prevent duplicate pipeline_start. Use one of the options above.${NC}"
        exit 1
    fi

    PIPELINE_RUN_ID=$(_pipeline_state start "$feature_id" "$feature_id" "$DAG_FILE" "$specific_stages" "$start_from" "$mock_review" "$PROJECT_CODE_DIR" "$$" "$feature_description" "$COST_LIMIT" "$MAX_RETRIES") || return 1
    export PIPELINE_RUN_ID
    _pipeline_state replay "$feature_id" || return 1
    emit_event "$feature_id" pipeline_start PIPE "Starting requested execution scope"

    echo -e "\n${BOLD}Starting SDLC Pipeline${NC}"
    echo -e "  Feature:    ${feature_id}"
    echo -e "  Description: ${feature_description}"
    echo -e "  Cost limit: \$${COST_LIMIT}"
    echo -e "  Stages:     $(echo "$stages_ordered" | wc -l | tr -d ' ')"

    # --- Hybrid Mode: inject external spec/plan files ---
    if [[ -n "$spec_file" ]]; then
        if [[ ! -f "$spec_file" ]]; then
            echo -e "${RED}ERROR: --spec-file not found: ${spec_file}${NC}"
            exit 1
        fi
        local s1_dir="${PIPELINE_ROOT}/${feature_id}/S1-requirements"
        mkdir -p "$s1_dir"
        # Convert external spec to pipeline-compatible output.json
        SPEC_FILE="$spec_file" OUT_DIR="$s1_dir" python3 << 'PYEOF'
import json, os, datetime

spec_file = os.environ['SPEC_FILE']
out_dir = os.environ['OUT_DIR']

with open(spec_file, 'r') as f:
    spec_content = f.read()

# Wrap external spec into StageOutput schema
output = {
    "stage_id": "S1",
    "status": "completed",
    "summary": "Requirements imported from external spec (Superpowers brainstorm)",
    "source": "external:" + os.path.basename(spec_file),
    "timestamp": datetime.datetime.now().isoformat(),
    "content": spec_content,
    "artifacts": [os.path.basename(spec_file)]
}

with open(os.path.join(out_dir, 'output.json'), 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f'Imported spec from {spec_file}')
PYEOF
        set_stage_state "$feature_id" "S1" "imported" 0
        emit_event "$feature_id" "stage_skip" "S1" "Using external spec: ${spec_file}"
        echo -e "  ${GREEN}✓ S1 requirements: imported from ${spec_file}${NC}"
        # Auto-skip S1
        skip_stages="${skip_stages:+${skip_stages},}requirements"
    fi

    if [[ -n "$plan_file" ]]; then
        if [[ ! -f "$plan_file" ]]; then
            echo -e "${RED}ERROR: --plan-file not found: ${plan_file}${NC}"
            exit 1
        fi
        local s2_dir="${PIPELINE_ROOT}/${feature_id}/S2-architecture"
        mkdir -p "$s2_dir"
        # Convert external plan to pipeline-compatible output.json
        PLAN_FILE="$plan_file" OUT_DIR="$s2_dir" DAG_PATH="$DAG_FILE" FEATURE_ID="$feature_id" SCHEMA_BASE="$SCRIPT_DIR" python3 << 'PYEOF'
import json, os, datetime, hashlib
from pathlib import Path
from jsonschema import Draft202012Validator

plan_file = os.environ['PLAN_FILE']
out_dir = os.environ['OUT_DIR']

with open(plan_file, 'r') as f:
    plan_content = f.read()

output = {
    "stage_id": "S2",
    "status": "completed",
    "summary": "Architecture imported from external plan (Superpowers writing-plans)",
    "source": "external:" + os.path.basename(plan_file),
    "timestamp": datetime.datetime.now().isoformat(),
    "content": plan_content,
    "artifacts": [os.path.basename(plan_file)]
}

# Imported designs can reuse explicit, versioned contracts from the project DAG.
# Including the digest in the imported artifact binds the dependency to this input.
contracts = json.loads(Path(os.environ['DAG_PATH']).read_text()).get('config', {}).get('imported_contracts')
if contracts is not None:
    document = {
        'stage_id': 'S2', 'feature_id': os.environ['FEATURE_ID'],
        'timestamp': output['timestamp'], 'contracts': contracts,
    }
    schema = json.loads((Path(os.environ['SCHEMA_BASE']) / 'schemas/contracts-output.json').read_text())
    Draft202012Validator(schema).validate(document)
    contract_path = Path(out_dir) / 'contracts.json'
    contract_path.write_text(json.dumps(document, indent=2, ensure_ascii=False))
    output['artifacts'].append('contracts.json')
    output['contracts_sha256'] = hashlib.sha256(contract_path.read_bytes()).hexdigest()

with open(os.path.join(out_dir, 'output.json'), 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f'Imported plan from {plan_file}')
PYEOF
        set_stage_state "$feature_id" "S2" "imported" 0
        emit_event "$feature_id" "stage_skip" "S2" "Using external plan: ${plan_file}"
        echo -e "  ${GREEN}✓ S2 architecture: imported from ${plan_file}${NC}"
        # Auto-skip S2
        skip_stages="${skip_stages:+${skip_stages},}architecture"
    fi

    echo ""

    # Execute stages
    local skip_until=""
    if [[ -n "$start_from" ]]; then
        skip_until="$start_from"
        echo -e "${YELLOW}Resuming from stage ${start_from}${NC}"
    fi

    local pipeline_success=true

    # Parse execution order with parallel group support
    # execution_order items can be:
    #   {"stage": "name", "mode": "sequential"}
    #   {"stages": ["a","b"], "mode": "parallel"}
    local exec_items
    exec_items=$(DAG_PATH="$DAG_FILE" python3 << 'PYEOF'
import json, os
with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)
for item in dag['execution_order']:
    mode = item.get('mode', 'sequential')
    if mode == 'parallel' and 'stages' in item:
        print('parallel:' + '|'.join(item['stages']))
    elif 'stages' in item:
        # stages array with sequential mode — treat each as sequential
        for s in item['stages']:
            print('sequential:' + s)
    else:
        print('sequential:' + item['stage'])
PYEOF
)

    source "$PARALLEL_SCRIPT"
    while IFS= read -r exec_item <&3; do
        local exec_mode="${exec_item%%:*}" exec_target="${exec_item#*:}"
        local selected_names=() stage stage_id current
        local group_names=()
        IFS='|' read -ra group_names <<< "$exec_target"
        for stage in "${group_names[@]}"; do
            stage_id=$(dag_get "$stage" id)
            _pipeline_state selected "$feature_id" "$stage_id" || continue
            if [[ ",${skip_stages}," == *",${stage},"* || ",${skip_stages}," == *",${stage_id},"* ]]; then
                set_stage_state "$feature_id" "$stage_id" skipped 0 || return 1
                continue
            fi
            current=$(get_stage_state "$feature_id" "$stage_id") || return 1
            if $auto_resume && [[ "$current" == passed ]]; then
                continue
            fi
            if $auto_resume && [[ "$current" == human_waiting ]]; then
                break 2
            fi
            selected_names+=("$stage")
        done
        [[ ${#selected_names[@]} -gt 0 ]] || continue
        local stage_exit=0
        if [[ "$exec_mode" == parallel ]]; then
            execute_parallel_group "$feature_id" "$feature_description" "${selected_names[@]}" || stage_exit=$?
        else
            execute_stage "${selected_names[0]}" "$feature_id" "$feature_description" || stage_exit=$?
        fi
        render_dashboard "$feature_id"
        if [[ $stage_exit -ne 0 ]]; then
            if [[ $stage_exit -ne 3 && $stage_exit -ne 4 ]]; then
                set_pipeline_state "$feature_id" failed "Stage execution failed" || return 1
            fi
            break
        fi
        if $pause_after; then
            set_pipeline_state "$feature_id" paused "Paused after requested stage/group" || return 1
            break
        fi
    done 3<<< "$exec_items"

    local outcome
    outcome=$(_pipeline_state finish "$feature_id") || return 1
    emit_event "$feature_id" pipeline_end PIPE "Execution outcome: ${outcome} (configured stage checks only)"
    render_dashboard "$feature_id"
    printf '\nPipeline outcome: %s\nState: %s/%s/state.json\n' "$outcome" "$PIPELINE_ROOT" "$feature_id"
    case "$outcome" in
        complete|simulated) return 0 ;;
        human_waiting) return 3 ;;
        paused|partial) return 4 ;;
        *) return 1 ;;
    esac
}

main "$@"
