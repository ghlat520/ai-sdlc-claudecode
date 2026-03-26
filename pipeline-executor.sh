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
DAG_FILE="${SCRIPT_DIR}/pipeline-dag.json"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate-handoff.sh"

# shellcheck source=lib/events.sh
source "${SCRIPT_DIR}/lib/events.sh"
# shellcheck source=lib/protocol.sh
source "${SCRIPT_DIR}/lib/protocol.sh"
# Parallel executor (sourced for execute_parallel_group function)
PARALLEL_SCRIPT="${SCRIPT_DIR}/orchestrate-parallel.sh"

# --- Evolve mode: always enabled (P0 optimization: ErrorEngine default-on) ---
# EVOLVE_ERRORS_DIR is set by runner.py or defaults to per-feature evolve dir

# --- Config from DAG (single python3 call to parse all config + stage metadata) ---
export PIPELINE_ROOT="${PROJECT_ROOT}/docs/pipeline"

# Cache DAG config and per-stage metadata in shell variables (P4: replaces ~60 python3 calls)
eval "$(DAG_PATH="$DAG_FILE" python3 << 'PYEOF'
import json, os

with open(os.environ['DAG_PATH']) as f:
    dag = json.load(f)

cfg = dag['config']
print(f'MAX_RETRIES={cfg["max_retries_per_stage"]}')
print(f'COST_LIMIT={cfg["cost_limit_usd"]}')
print(f'CONTEXT_BUDGET={cfg["context_budget_tokens"]}')

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
    print(f'DAG_{safe_name}_id="{sid}"')
    print(f'DAG_{safe_name}_model="{model}"')
    print(f'DAG_{safe_name}_timeout={timeout}')
    print(f'DAG_{safe_name}_max_retries={max_r}')
    print(f'DAG_{safe_name}_gate="{gate}"')
    print(f'DAG_{safe_name}_agent_type="{agent_type}"')
    print(f'DAG_{safe_name}_deps="{deps}"')
    post_cmds = '|'.join(s.get('post_commands', []))
    print(f'DAG_{safe_name}_post_commands="{post_cmds}"')

# Export tech_stack_commands as TECH_CMD_<key> variables
ts = cfg.get('tech_stack', 'node-typescript')
cmds = cfg.get('tech_stack_commands', {}).get(ts, {})
for key, val in cmds.items():
    print(f'TECH_CMD_{key}="{val}"')

# Export evidence_required config
print(f'EVIDENCE_REQUIRED="{str(cfg.get("evidence_required", False)).lower()}"')
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
total = len(stages_meta)
passed_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") == "passed"]
skipped_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") == "skipped"]
running_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") in ("running", "gate_checking")]
failed_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") in ("failed", "dead_letter")]
waiting_ids = [s["id"] for s in stages_meta if stages_state.get(s["id"], {}).get("status") == "human_waiting"]

effective_done = len(passed_ids) + len(skipped_ids)
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

for name, stage in dag['stages'].items():
    est = stage.get('estimated_tokens', {})
    input_tok = est.get('input', 20000)
    output_tok = est.get('output', 10000)
    total_tok = est.get('total', input_tok + output_tok)
    model = stage['agents'][0].get('model', 'sonnet')
    rates = PRICING.get(model, PRICING['sonnet'])

    cost_input = (input_tok / 1_000_000) * rates['input']
    cost_output = (output_tok / 1_000_000) * rates['output']
    cost = cost_input + cost_output
    cost_with_retries = cost * 1.5
    total_tokens += int(total_tok * 1.5)
    total_cost += cost_with_retries
    print('  {} {:22s} ~{:>7,} tok  {:6s}  ${:.3f} (w/retry: ${:.3f})'.format(
        stage['id'], name, total_tok, model, cost, cost_with_retries))

print('')
print('  {:22s}   Total: ~{:>7,} tok  ${:.2f}'.format('', total_tokens, total_cost))
print('  {:22s}   Limit: ${:.2f}'.format('', cost_limit))

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
    json_files = glob.glob(os.path.join(dep_dir, '*.json'))
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
prompt += '\n\nIMPORTANT: Output the JSON directly in your response inside a ```json code block. Do NOT attempt to write files. Your response will be parsed to extract the JSON. The JSON block must be complete and valid — do NOT truncate or summarize it.\n'
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

print(prompt)
PYEOF
}

# --- Run post-commands (Layer 1: objective hard gate) ---
# Resolves {{compile}}, {{test}}, {{lint}} templates from TECH_CMD_* variables
# Returns 0 if all pass (or no commands), 1 if any fail
run_post_commands() {
    local stage_name="$1"
    local feature_id="$2"
    local stage_id="$3"

    local post_cmds_raw
    post_cmds_raw=$(dag_get "$stage_name" "post_commands")
    [[ -z "$post_cmds_raw" ]] && return 0

    echo -e "  ${YELLOW}Running post-commands (evidence gate)...${NC}"

    local all_pass=true
    local cmd_output=""
    IFS='|' read -ra CMD_TEMPLATES <<< "$post_cmds_raw"
    for tmpl in "${CMD_TEMPLATES[@]}"; do
        [[ -z "$tmpl" ]] && continue
        # Resolve {{key}} to TECH_CMD_key
        local resolved="$tmpl"
        if [[ "$tmpl" =~ ^\{\{([a-z_]+)\}\}$ ]]; then
            local key="${BASH_REMATCH[1]}"
            local var="TECH_CMD_${key}"
            resolved="${!var}"
            if [[ -z "$resolved" ]]; then
                echo -e "    ${YELLOW}⚠ No command for {{${key}}} in tech stack ${PIPELINE_TECH_STACK}, skipping${NC}"
                continue
            fi
        fi
        echo -e "    Running: ${resolved}"
        local cmd_exit=0
        local cmd_result=""
        cmd_result=$(cd "$PROJECT_ROOT" && eval "$resolved" 2>&1) || cmd_exit=$?
        if [[ $cmd_exit -eq 0 ]]; then
            echo -e "    ${GREEN}✓ Passed${NC}"
        else
            echo -e "    ${RED}✗ Failed (exit: ${cmd_exit})${NC}"
            cmd_output+="Command '${resolved}' failed (exit ${cmd_exit}):\n${cmd_result}\n\n"
            all_pass=false
        fi
    done

    if $all_pass; then
        emit_event "$feature_id" "post_cmd_pass" "$stage_id" "All post-commands passed"
        return 0
    else
        emit_event "$feature_id" "post_cmd_fail" "$stage_id" "Post-command(s) failed"
        # Store output for caller to use as prev_error_output
        POST_CMD_ERROR_OUTPUT="$cmd_output"
        return 1
    fi
}

# --- Check evidence in agent output (Layer 2: evidence extraction) ---
# Looks for VERIFICATION_EVIDENCE block in claude output
# Writes evidence.json if found; emits warning if missing
check_evidence() {
    local claude_output="$1"
    local output_dir="$2"
    local feature_id="$3"
    local stage_id="$4"

    if echo "$claude_output" | grep -q "VERIFICATION_EVIDENCE"; then
        # Extract evidence table into JSON
        python3 -c "
import re, json, sys

text = sys.stdin.read()

# Find the VERIFICATION_EVIDENCE table
table_pattern = r'VERIFICATION_EVIDENCE.*?\n(\|.*\|[\s\S]*?\n)(?:\n|###|$)'
match = re.search(table_pattern, text)

evidence = {'found': True, 'entries': [], 'status': 'UNKNOWN'}

if match:
    lines = match.group(1).strip().split('\n')
    for line in lines:
        cols = [c.strip() for c in line.strip('|').split('|')]
        if len(cols) >= 3 and cols[0] not in ('Command', '---', ''):
            evidence['entries'].append({
                'command': cols[0],
                'exit_code': cols[1],
                'key_output': cols[2] if len(cols) > 2 else ''
            })

# Find VERIFICATION_STATUS
status_match = re.search(r'VERIFICATION_STATUS:\s*(VERIFIED|UNVERIFIED|PARTIAL)', text)
if status_match:
    evidence['status'] = status_match.group(1)

with open('${output_dir}/evidence.json', 'w') as f:
    json.dump(evidence, f, indent=2, ensure_ascii=False)
print('Evidence extracted')
" <<< "$claude_output" 2>/dev/null || true
        emit_event "$feature_id" "evidence_found" "$stage_id" "Verification evidence found in output"
        echo -e "  ${GREEN}✓ Verification evidence found${NC}"
    else
        emit_event "$feature_id" "evidence_missing" "$stage_id" "No VERIFICATION_EVIDENCE block in output"
        echo -e "  ${YELLOW}⚠ No VERIFICATION_EVIDENCE block in agent output${NC}"
        if [[ "$EVIDENCE_REQUIRED" == "true" ]]; then
            echo -e "  ${RED}✗ Evidence required but missing — blocking${NC}"
            return 1
        fi
    fi
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

        set_stage_state "$feature_id" "$stage_id" "running" "$retry_count"
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

        # Augment prompt with learned fixes from ErrorEngine
        local evolve_dir="${EVOLVE_ERRORS_DIR:-${PIPELINE_ROOT}/${feature_id}/evolve}"
        if [[ -f "${evolve_dir}/augments/${stage_id}.txt" ]]; then
            local augment
            augment=$(cat "${evolve_dir}/augments/${stage_id}.txt")
            prompt="${augment}${prompt}"
        fi

        # Diagnostic retry: inject previous failure context (replaces blind retry)
        if [[ $retry_count -gt 0 && -n "$prev_error_output" ]]; then
            local diag_methods_dir="${SCRIPT_DIR}/prompts/methods"
            local diag_fragment=""
            if [[ -f "${diag_methods_dir}/diagnostic-retry.md" ]]; then
                diag_fragment=$(cat "${diag_methods_dir}/diagnostic-retry.md")
            fi
            local diag_context
            diag_context=$(cat <<DIAG_EOF

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
            prompt="${diag_context}

${prompt}"
            echo -e "  ${YELLOW}  [DIAGNOSTIC] Injected failure context from attempt ${retry_count}${NC}"
        fi

        # Set scope lock to stage output directory + feature directory
        export PIPELINE_SCOPE_LOCK="${output_dir},${PIPELINE_ROOT}/${feature_id}"

        # Execute via claude --print (headless) or skeleton mode
        local start_time
        start_time=$(date +%s)

        # Get stage timeout (from DAG cache)
        local stage_timeout
        stage_timeout=$(dag_get "$stage_name" "timeout")

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
            echo -e "  ${YELLOW}Invoking Claude (${agent_model}, timeout: ${stage_timeout}s)...${NC}"

            if command -v timeout >/dev/null 2>&1; then
                claude_output=$(timeout "${stage_timeout}" claude --print --model "${agent_model}" "$prompt" 2>&1) || claude_exit=$?
                if [[ $claude_exit -eq 124 ]]; then
                    echo -e "  ${RED}Stage timed out after ${stage_timeout}s${NC}"
                    emit_event "$feature_id" "stage_timeout" "$stage_id" "Timed out after ${stage_timeout}s"
                    set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
                    send_notification "$feature_id" "dead_letter" "Stage ${stage_id} timed out after ${stage_timeout}s"
                    prev_error_output="TIMEOUT after ${stage_timeout}s. Partial output: ${claude_output: -500}"
                    prev_exit_code="124 (timeout)"
                    ((retry_count++))
                    continue
                fi
            else
                # macOS may not have timeout; use perl wrapper
                claude_output=$(perl -e 'alarm shift; exec @ARGV' "${stage_timeout}" claude --print --model "${agent_model}" "$prompt" 2>&1) || claude_exit=$?
            fi
        fi

        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))

        # Estimate tokens (rough: 4 chars per token)
        local est_tokens=$(( (${#prompt} + ${#claude_output}) / 4 ))
        update_cost "$feature_id" "$est_tokens" "$agent_model" || true
        emit_event "$feature_id" "cost_update" "$stage_id" "Tokens: ~${est_tokens}" "{\"tokens\": ${est_tokens}, \"duration\": ${duration}}" || true

        if [[ $claude_exit -ne 0 ]]; then
            echo -e "  ${RED}Claude invocation failed (exit: ${claude_exit})${NC}"
            emit_event "$feature_id" "stage_fail" "$stage_id" "Agent failed with exit code ${claude_exit}"
            set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"

            # Capture for diagnostic retry
            prev_error_output="$claude_output"
            prev_exit_code="$claude_exit"

            # Real-time error capture + augment (always enabled)
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

            ((retry_count++))
            continue
        fi

        # Try to extract JSON output from Claude's response
        # Check if output file was created, or try to extract from response
        local output_json="${output_dir}/output.json"
        if [[ ! -f "$output_json" ]]; then
            echo "$claude_output" | python3 -m ai_sdlc_claudecode extract-json "$output_json" 2>/dev/null || {
                echo -e "  ${YELLOW}Warning: Could not extract structured output${NC}"
                # Save raw output for debugging
                echo "$claude_output" > "${output_dir}/raw_output.txt"
            }
        fi

        # Layer 1: Post-commands hard gate (compile/test/lint)
        # Skip in skeleton mode — no real code to compile
        POST_CMD_ERROR_OUTPUT=""
        if [[ "${PIPELINE_SKELETON_MODE:-false}" == "true" ]]; then
            echo -e "  ${YELLOW}[SKELETON] Skipping post-commands${NC}"
        elif ! run_post_commands "$stage_name" "$feature_id" "$stage_id"; then
            prev_error_output="Post-command verification failed:\n${POST_CMD_ERROR_OUTPUT}"
            prev_exit_code="post_cmd_fail"
            set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
            ((retry_count++))
            continue
        fi

        # Layer 2: Evidence extraction (check agent output for verification proof)
        if ! check_evidence "$claude_output" "$output_dir" "$feature_id" "$stage_id"; then
            prev_error_output="VERIFICATION_EVIDENCE block missing from output. You MUST include verification evidence."
            prev_exit_code="evidence_missing"
            set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
            ((retry_count++))
            continue
        fi

        # Validate handoff
        echo -e "  ${YELLOW}Validating output...${NC}"
        set_stage_state "$feature_id" "$stage_id" "gate_checking" "$retry_count"

        if [[ -f "$output_json" ]]; then
            local validate_result
            validate_result=$(bash "$VALIDATE_SCRIPT" "$stage_id" "$output_json" 2>&1) || true

            if echo "$validate_result" | grep -q "\[PASS\]"; then
                echo -e "  ${GREEN}✓ Schema validation passed${NC}"
            else
                echo -e "  ${YELLOW}⚠ Schema validation issues (non-blocking for now):${NC}"
                echo "$validate_result" | head -10 | sed 's/^/    /'
            fi
        fi

        # TDD Hard Gate: enforce coverage threshold for testing stages (S4, S4b, S4c)
        if [[ "$stage_id" == "S4" || "$stage_id" == "S4b" || "$stage_id" == "S4c" ]]; then
            local tdd_gate_script="${SCRIPT_DIR}/lib/tdd-gate.sh"
            if [[ -f "$tdd_gate_script" ]]; then
                echo -e "  ${YELLOW}Running TDD Hard Gate (coverage check)...${NC}"
                local tdd_result=""
                local tdd_exit=0
                tdd_result=$(bash "$tdd_gate_script" "$feature_id" "${PIPELINE_TECH_STACK:-node-typescript}" 80 2>&1) || tdd_exit=$?

                echo "$tdd_result" | grep '^\[TDD-GATE\]' | sed 's/^/  /'

                if [[ $tdd_exit -eq 1 ]]; then
                    echo -e "  ${RED}✗ TDD Hard Gate FAILED — coverage below 80%${NC}"
                    emit_event "$feature_id" "tdd_gate_fail" "$stage_id" "Coverage below threshold"
                    prev_error_output="TDD Hard Gate: coverage below 80% threshold. ${tdd_result}"
                    prev_exit_code="tdd_gate_fail"
                    set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
                    ((retry_count++))
                    continue
                elif [[ $tdd_exit -eq 0 ]]; then
                    echo -e "  ${GREEN}✓ TDD Hard Gate PASSED${NC}"
                    emit_event "$feature_id" "tdd_gate_pass" "$stage_id" "Coverage meets threshold"
                else
                    echo -e "  ${YELLOW}⚠ TDD Hard Gate: could not determine coverage (non-blocking)${NC}"
                fi
            fi
        fi

        # Gate check
        echo -e "  ${YELLOW}Checking gate (${gate_type})...${NC}"
        case "$gate_type" in
            auto)
                # Run automatic commands
                local gate_commands
                gate_commands=$(DAG_PATH="$DAG_FILE" STG="$stage_name" python3 -c "
import json, os
stage = json.load(open(os.environ['DAG_PATH']))['stages'][os.environ['STG']]
cmds = stage.get('gate', {}).get('commands', [])
print('\n'.join(cmds))
" 2>/dev/null)

                local gate_pass=true
                if [[ -n "$gate_commands" ]]; then
                    while IFS= read -r cmd; do
                        [[ -z "$cmd" ]] && continue
                        echo -e "    Running: ${cmd}"
                        if eval "$cmd" >/dev/null 2>&1; then
                            echo -e "    ${GREEN}✓ Passed${NC}"
                        else
                            echo -e "    ${RED}✗ Failed${NC}"
                            gate_pass=false
                        fi
                    done <<< "$gate_commands"
                fi

                if $gate_pass; then
                    emit_event "$feature_id" "gate_pass" "$stage_id" "Auto gate passed"
                    set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                    send_message "$feature_id" "$agent_type" "Commander" "$MSG_RESPONSE" \
                        "${stage_name} complete, gate passed" "${output_dir}/output.json"
                    send_message "$feature_id" "Commander" "GateCheck" "$MSG_GATE" \
                        "${stage_id} auto gate: PASSED"
                    echo -e "  ${GREEN}✓ Gate PASSED${NC}"
                    return 0
                else
                    emit_event "$feature_id" "gate_fail" "$stage_id" "Auto gate failed"
                    set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
                    prev_error_output="Auto gate check failed. Gate commands did not pass."
                    prev_exit_code="gate_fail"
                    ((retry_count++))
                    continue
                fi
                ;;

            auto+ai-review)
                # Skeleton mode: skip auto commands and auto-pass
                if [[ "${PIPELINE_SKELETON_MODE:-false}" == "true" ]]; then
                    echo -e "  ${YELLOW}[SKELETON] Auto-passing auto+ai-review gate${NC}"
                    emit_event "$feature_id" "gate_pass" "$stage_id" "Auto+AI-review gate auto-passed (skeleton mode)"
                    set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                    echo -e "  ${GREEN}✓ Gate PASSED (auto+ai-review, skeleton)${NC}"
                    return 0
                fi
                # Phase 1: Run auto commands first
                local gate_commands_mixed
                gate_commands_mixed=$(DAG_PATH="$DAG_FILE" STG="$stage_name" python3 -c "
import json, os
stage = json.load(open(os.environ['DAG_PATH']))['stages'][os.environ['STG']]
cmds = stage.get('gate', {}).get('commands', [])
print('\n'.join(cmds))
" 2>/dev/null)

                local auto_pass=true
                if [[ -n "$gate_commands_mixed" ]]; then
                    echo -e "  ${YELLOW}Phase 1: Running auto commands...${NC}"
                    while IFS= read -r cmd; do
                        [[ -z "$cmd" ]] && continue
                        echo -e "    Running: ${cmd}"
                        if eval "$cmd" >/dev/null 2>&1; then
                            echo -e "    ${GREEN}✓ Passed${NC}"
                        else
                            echo -e "    ${RED}✗ Failed${NC}"
                            auto_pass=false
                        fi
                    done <<< "$gate_commands_mixed"
                fi

                if ! $auto_pass; then
                    emit_event "$feature_id" "gate_fail" "$stage_id" "Auto+AI-review gate failed (auto phase)"
                    set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
                    prev_error_output="Auto gate commands failed in auto+ai-review gate."
                    prev_exit_code="gate_fail"
                    ((retry_count++))
                    continue
                fi

                echo -e "  ${GREEN}Phase 1: Auto commands passed${NC}"
                echo -e "  ${YELLOW}Phase 2: Running AI review...${NC}"

                # Phase 2: AI review (same as ai-review gate)
                local ai_review_script_mixed="${SCRIPT_DIR}/ai-review-checker.sh"
                if [[ -f "$output_json" && -x "$ai_review_script_mixed" ]]; then
                    local ai_review_exit_mixed=0
                    local review_flags_mixed=(--model "haiku" --feature-id "$feature_id")
                    if [[ "${PIPELINE_MOCK_REVIEW:-false}" == "true" ]]; then
                        review_flags_mixed+=(--mock)
                    fi
                    bash "$ai_review_script_mixed" "$stage_id" "$output_json" \
                        "${review_flags_mixed[@]}" 2>&1 || ai_review_exit_mixed=$?

                    if [[ $ai_review_exit_mixed -eq 0 ]]; then
                        emit_event "$feature_id" "gate_pass" "$stage_id" "Auto+AI-review gate passed"
                        set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                        send_message "$feature_id" "$agent_type" "Commander" "$MSG_RESPONSE" \
                            "${stage_name} complete, auto+AI review passed" "${output_dir}/output.json"
                        send_message "$feature_id" "Commander" "GateCheck" "$MSG_GATE" \
                            "${stage_id} auto+ai-review gate: PASSED"
                        echo -e "  ${GREEN}✓ Gate PASSED (auto+ai-review)${NC}"
                        return 0
                    fi
                fi

                emit_event "$feature_id" "gate_fail" "$stage_id" "Auto+AI-review gate failed (AI phase)"
                prev_error_output="AI review phase failed in auto+ai-review gate."
                prev_exit_code="gate_fail"
                ((retry_count++))
                continue
                ;;

            ai-review)
                # AI-review gate: run semantic evaluation via ai-review-checker.sh
                local ai_review_script="${SCRIPT_DIR}/ai-review-checker.sh"
                if [[ -f "$output_json" && -x "$ai_review_script" ]]; then
                    local ai_review_exit=0
                    local review_flags=(--model "haiku" --feature-id "$feature_id")
                    if [[ "${PIPELINE_MOCK_REVIEW:-false}" == "true" ]]; then
                        review_flags+=(--mock)
                    fi
                    bash "$ai_review_script" "$stage_id" "$output_json" \
                        "${review_flags[@]}" 2>&1 || ai_review_exit=$?

                    if [[ $ai_review_exit -eq 0 ]]; then
                        emit_event "$feature_id" "gate_pass" "$stage_id" "AI-review gate passed"
                        set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                        send_message "$feature_id" "$agent_type" "Commander" "$MSG_RESPONSE" \
                            "${stage_name} complete, AI review passed" "${output_dir}/output.json"
                        send_message "$feature_id" "Commander" "GateCheck" "$MSG_GATE" \
                            "${stage_id} ai-review gate: PASSED"
                        echo -e "  ${GREEN}✓ Gate PASSED (AI-review)${NC}"
                        return 0
                    else
                        echo -e "  ${YELLOW}AI review failed, falling back to structural check...${NC}"
                        # Fallback: pass if output exists and has valid structure
                        if python3 -c "import json; d=json.load(open('${output_json}')); assert d.get('stage_id') == '${stage_id}'" 2>/dev/null; then
                            emit_event "$feature_id" "gate_pass" "$stage_id" "AI-review gate passed (structural fallback)"
                            set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                            send_message "$feature_id" "$agent_type" "Commander" "$MSG_RESPONSE" \
                                "${stage_name} complete" "${output_dir}/output.json"
                            send_message "$feature_id" "Commander" "GateCheck" "$MSG_GATE" \
                                "${stage_id} ai-review gate: PASSED (fallback)"
                            echo -e "  ${GREEN}✓ Gate PASSED (structural fallback)${NC}"
                            return 0
                        fi
                    fi
                elif [[ -f "$output_json" ]]; then
                    # No ai-review-checker.sh available, pass if output exists
                    emit_event "$feature_id" "gate_pass" "$stage_id" "AI-review gate passed (output valid)"
                    set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                    send_message "$feature_id" "$agent_type" "Commander" "$MSG_RESPONSE" \
                        "${stage_name} complete" "${output_dir}/output.json"
                    send_message "$feature_id" "Commander" "GateCheck" "$MSG_GATE" \
                        "${stage_id} ai-review gate: PASSED"
                    echo -e "  ${GREEN}✓ Gate PASSED (AI-review)${NC}"
                    return 0
                fi
                emit_event "$feature_id" "gate_fail" "$stage_id" "AI-review gate failed"
                prev_error_output="AI-review gate rejected the output. Review checker did not pass quality threshold."
                prev_exit_code="gate_fail"
                ((retry_count++))
                continue
                ;;

            human-required)
                # Skeleton mode: auto-approve human gates
                if [[ "${PIPELINE_SKELETON_MODE:-false}" == "true" ]]; then
                    echo -e "  ${YELLOW}[SKELETON] Auto-approving human gate for ${stage_id}${NC}"
                    emit_event "$feature_id" "gate_pass" "$stage_id" "Human gate auto-approved (skeleton mode)"
                    set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                    echo -e "  ${GREEN}✓ Gate PASSED (human-required, skeleton auto-approved)${NC}"
                    return 0
                fi
                # Create approval request file
                local approval_file="${output_dir}/APPROVAL_REQUIRED"
                local notification
                notification=$(DAG_PATH="$DAG_FILE" STG="$stage_name" python3 -c "
import json, os
stage = json.load(open(os.environ['DAG_PATH']))['stages'][os.environ['STG']]
print(stage.get('gate', {}).get('notification', 'Human approval required'))
" 2>/dev/null)

                cat > "$approval_file" <<APPROVAL
============================================
HUMAN APPROVAL REQUIRED
============================================
Feature:  ${feature_id}
Stage:    ${stage_id} - ${stage_name}
Time:     $(date -u +"%Y-%m-%dT%H:%M:%SZ")

${notification}

To approve:  rm ${approval_file} && touch ${output_dir}/APPROVED
To reject:   rm ${approval_file} && touch ${output_dir}/REJECTED
============================================
APPROVAL

                emit_event "$feature_id" "human_wait" "$stage_id" "Waiting for human approval"
                set_stage_state "$feature_id" "$stage_id" "human_waiting" "$retry_count"
                send_notification "$feature_id" "human_wait" "Stage ${stage_id} requires human approval. Review: ${output_dir}/"

                echo -e "  ${BOLD}${YELLOW}⏸ Human approval required.${NC}"
                echo -e "  ${YELLOW}  Review output at: ${output_dir}/${NC}"
                echo -e "  ${YELLOW}  To approve: rm ${approval_file} && touch ${output_dir}/APPROVED${NC}"
                echo -e "  ${YELLOW}  To reject:  rm ${approval_file} && touch ${output_dir}/REJECTED${NC}"

                # Poll for approval (check every 10 seconds, timeout after 24 hours)
                local wait_count=0
                local max_wait=8640  # 8640 * 10s = 24 hours
                while [[ $wait_count -lt $max_wait ]]; do
                    if [[ -f "${output_dir}/APPROVED" ]]; then
                        rm -f "${output_dir}/APPROVED" "$approval_file"
                        emit_event "$feature_id" "gate_pass" "$stage_id" "Human approved"
                        set_stage_state "$feature_id" "$stage_id" "passed" "$retry_count"
                        echo -e "  ${GREEN}✓ Approved!${NC}"
                        return 0
                    elif [[ -f "${output_dir}/REJECTED" ]]; then
                        rm -f "${output_dir}/REJECTED" "$approval_file"
                        emit_event "$feature_id" "gate_fail" "$stage_id" "Human rejected"
                        set_stage_state "$feature_id" "$stage_id" "failed" "$retry_count"
                        echo -e "  ${RED}✗ Rejected${NC}"
                        ((retry_count++))
                        continue 2
                    fi
                    sleep 10
                    ((wait_count++))
                done

                echo -e "  ${RED}Approval timeout (24 hours)${NC}"
                emit_event "$feature_id" "dead_letter" "$stage_id" "Approval timeout"
                set_stage_state "$feature_id" "$stage_id" "dead_letter" "$retry_count"

                # Capture timeout for evolve learning
                local evolve_dir="${PIPELINE_ROOT}/${feature_id}/evolve/failures"
                mkdir -p "$evolve_dir"
                cat > "${evolve_dir}/${stage_id}-$(date +%s).json" <<EVOLVE_TIMEOUT
{
  "stage_id": "${stage_id}",
  "stage_name": "${stage_name}",
  "feature_id": "${feature_id}",
  "failure_type": "human_approval_timeout",
  "timeout_seconds": $((max_wait * 10)),
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EVOLVE_TIMEOUT
                emit_event "$feature_id" "evolve_capture" "$stage_id" "Approval timeout captured for evolve learning"

                return 1
                ;;
        esac
    done

    # Max retries exceeded → dead letter
    emit_event "$feature_id" "dead_letter" "$stage_id" "Max retries (${max_retry}) exceeded"
    set_stage_state "$feature_id" "$stage_id" "dead_letter" "$retry_count"
    echo -e "  ${RED}[DEAD LETTER] Stage ${stage_id} failed after ${max_retry} retries${NC}"

    send_notification "$feature_id" "dead_letter" "Stage ${stage_id} (${stage_name}) failed after ${max_retry} retries. Manual intervention required."

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

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) dry_run=true; shift ;;
            --resume) auto_resume=true; shift ;;
            --start-from) start_from="$2"; shift 2 ;;
            --stages) specific_stages="$2"; shift 2 ;;
            --cost-limit) COST_LIMIT="$2"; shift 2 ;;
            --tech-stack) tech_stack="$2"; shift 2 ;;
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

    # Validate DAG
    if ! validate_dag; then
        echo -e "${RED}DAG validation failed. Aborting.${NC}"
        exit 1
    fi

    # Auto-resume: find last passed stage and continue from there
    if $auto_resume; then
        local resume_point
        resume_point=$(get_resume_point "$feature_id")
        if [[ -n "$resume_point" ]]; then
            start_from="$resume_point"
            echo -e "${CYAN}Auto-resume: continuing from ${resume_point}${NC}"
            emit_event "$feature_id" "pipeline_resume" "PIPE" "Resuming from ${resume_point}"
            set_pipeline_state "$feature_id" "running" "Resumed from ${resume_point}"
        else
            echo -e "${GREEN}All stages already passed. Nothing to resume.${NC}"
            exit 0
        fi
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
    else:
        s = item['stage']
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

    emit_event "$feature_id" "pipeline_start" "PIPE" "Starting pipeline for: ${feature_description}"

    # Initialize state — skip if resuming (preserve existing passed stages)
    if [[ "$auto_resume" == "true" || -n "$start_from" ]]; then
        echo -e "${CYAN}Preserving existing state.json (resume mode)${NC}"
    else
        # Fresh start or force restart — initialize clean state
        FEAT_ID="$feature_id" FEAT_DESC="$feature_description" \
        STATE_FILE="$state_file" \
        COST_LIM="$COST_LIMIT" MAX_R="$MAX_RETRIES" python3 << 'PYEOF'
import json, os
state = {
    'feature_id': os.environ['FEAT_ID'],
    'feature_description': os.environ['FEAT_DESC'],
    'stages': {},
    'cost': {'total_tokens': 0, 'estimated_usd': 0.0},
    'config': {
        'cost_limit_usd': float(os.environ['COST_LIM']),
        'max_retries': int(os.environ['MAX_R'])
    }
}
with open(os.environ['STATE_FILE'], 'w') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
PYEOF
    fi

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
        set_stage_state "$feature_id" "S1" "passed" 0
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
        PLAN_FILE="$plan_file" OUT_DIR="$s2_dir" python3 << 'PYEOF'
import json, os, datetime

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

with open(os.path.join(out_dir, 'output.json'), 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f'Imported plan from {plan_file}')
PYEOF
        set_stage_state "$feature_id" "S2" "passed" 0
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

    while IFS= read -r exec_item <&3; do
        local exec_mode="${exec_item%%:*}"
        local exec_target="${exec_item#*:}"

        if [[ "$exec_mode" == "parallel" ]]; then
            # Parallel execution group
            local parallel_stages="${exec_target//|/,}"

            # Skip logic for parallel groups (--start-from)
            if [[ -n "$skip_until" ]]; then
                local found_start=false
                IFS=',' read -ra par_arr <<< "$parallel_stages"
                for ps in "${par_arr[@]}"; do
                    local ps_id
                    ps_id=$(dag_get "$ps" "id")
                    if [[ "$ps_id" == "$skip_until" || "$ps" == "$skip_until" ]]; then
                        found_start=true
                        break
                    fi
                done
                if $found_start; then
                    skip_until=""
                else
                    echo -e "  ${YELLOW}Skipping parallel group ${parallel_stages} (resuming from ${start_from})${NC}"
                    continue
                fi
            fi

            # Check if ALL stages in this parallel group are skipped via --skip-stage
            if [[ -n "$skip_stages" ]]; then
                local all_skipped=true
                local remaining_stages=""
                IFS=',' read -ra par_arr <<< "$parallel_stages"
                for ps in "${par_arr[@]}"; do
                    local ps_id
                    ps_id=$(dag_get "$ps" "id")
                    if echo "$skip_stages" | tr ',' '\n' | grep -qw "$ps_id" || \
                       echo "$skip_stages" | tr ',' '\n' | grep -qw "$ps"; then
                        # This stage is skipped
                        set_stage_state "$feature_id" "$ps_id" "passed" 0
                        emit_event "$feature_id" "stage_skip" "$ps_id" "Skipped via --skip-stage flag"
                    else
                        all_skipped=false
                        if [[ -n "$remaining_stages" ]]; then
                            remaining_stages="${remaining_stages},${ps}"
                        else
                            remaining_stages="$ps"
                        fi
                    fi
                done

                if $all_skipped; then
                    echo -e "  ${YELLOW}Skipping entire parallel group [${parallel_stages}] (all stages in --skip-stage)${NC}"
                    emit_event "$feature_id" "parallel_skip" "PAR" "Entire parallel group skipped: ${parallel_stages}"
                    continue
                fi

                # If only some stages are skipped, run the remaining ones
                if [[ "$remaining_stages" != "$parallel_stages" ]]; then
                    parallel_stages="$remaining_stages"
                    echo -e "  ${YELLOW}Partial parallel group: running only [${parallel_stages}]${NC}"
                fi
            fi

            echo -e "\n${BOLD}${MAGENTA}▶ Executing parallel group: ${parallel_stages}${NC}"
            if ! /opt/homebrew/bin/bash "$PARALLEL_SCRIPT" "$feature_id" "$feature_description" "$parallel_stages"; then
                pipeline_success=false
                echo -e "${RED}Parallel group failed: ${parallel_stages}${NC}"
                emit_event "$feature_id" "pipeline_fail" "PIPE" "Pipeline halted: parallel group ${parallel_stages} failed"
                render_dashboard "$feature_id"
                break
            fi
            render_dashboard "$feature_id"
        else
            # Sequential execution (existing logic)
            local stage="$exec_target"
            local stage_id
            stage_id=$(dag_get "$stage" "id")

            # Skip stages if --start-from specified
            if [[ -n "$skip_until" ]]; then
                if [[ "$stage_id" == "$skip_until" || "$stage" == "$skip_until" ]]; then
                    skip_until=""
                else
                    echo -e "  ${YELLOW}Skipping ${stage_id} ${stage} (resuming from ${start_from})${NC}"
                    continue
                fi
            fi

            # Skip stages not in --stages list
            if [[ -n "$specific_stages" ]]; then
                if ! echo "$specific_stages" | tr ',' '\n' | grep -qw "$stage"; then
                    continue
                fi
            fi

            # Skip stages in --skip-stage list
            if [[ -n "$skip_stages" ]]; then
                if echo "$skip_stages" | tr ',' '\n' | grep -qw "$stage_id" || \
                   echo "$skip_stages" | tr ',' '\n' | grep -qw "$stage"; then
                    echo -e "  ${YELLOW}Skipping ${stage_id} ${stage} (--skip-stage)${NC}"
                    set_stage_state "$feature_id" "$stage_id" "passed" 0
                    emit_event "$feature_id" "stage_skip" "$stage_id" "Skipped via --skip-stage flag"
                    continue
                fi
            fi

            if ! execute_stage "$stage" "$feature_id" "$feature_description"; then
                pipeline_success=false
                local dead_state
                dead_state=$(get_stage_state "$feature_id" "$stage_id")
                render_dashboard "$feature_id"
                if [[ "$dead_state" == "dead_letter" ]]; then
                    echo -e "${RED}Pipeline halted at ${stage_id} (dead letter)${NC}"
                    break
                fi
            else
                render_dashboard "$feature_id"
            fi

            # Pause after stage if --pause flag set
            if $pause_after; then
                emit_event "$feature_id" "pipeline_pause" "PIPE" "Paused after ${stage_id}"
                set_pipeline_state "$feature_id" "paused" "Paused after ${stage_id}"
                echo -e "${YELLOW}Pipeline paused after ${stage_id}. Resume with: --resume${NC}"
                exit 0
            fi
        fi
    done 3<<< "$exec_items"

    # Pipeline summary
    if $pipeline_success; then
        emit_event "$feature_id" "pipeline_end" "PIPE" "Pipeline completed successfully"
        send_notification "$feature_id" "pipeline_end" "Pipeline COMPLETE for ${feature_id}"
    else
        emit_event "$feature_id" "pipeline_end" "PIPE" "Pipeline completed with failures"
        send_notification "$feature_id" "pipeline_end" "Pipeline FAILED for ${feature_id}"
    fi

    # Final dashboard
    echo ""
    render_dashboard "$feature_id"

    if $pipeline_success; then
        echo -e "\n${GREEN}${BOLD}✅ Pipeline COMPLETE for ${feature_id}${NC}"
    else
        echo -e "\n${RED}${BOLD}❌ Pipeline FAILED for ${feature_id}${NC}"
    fi

    echo -e "  Logs:   ${PIPELINE_ROOT}/${feature_id}/events.jsonl"
    echo -e "  State:  ${PIPELINE_ROOT}/${feature_id}/state.json"

    $pipeline_success
}

main "$@"
