#!/usr/bin/env bash
# =============================================================================
# pipeline-monitor.sh — Rich terminal status panel (standalone)
#
# Same rendering as the inline dashboard in pipeline-executor.sh,
# but can be run independently for monitoring.
#
# Usage:
#   bash pipeline-monitor.sh <feature_id>              # One-shot
#   bash pipeline-monitor.sh <feature_id> --watch      # Auto-refresh 5s
#   bash pipeline-monitor.sh <feature_id> --watch 2    # Refresh 2s
#   bash pipeline-monitor.sh <feature_id> --events     # Event log
#   bash pipeline-monitor.sh <feature_id> --events 20  # Last 20 events
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FEATURE_ID="${1:-}"
MODE="${2:---status}"
INTERVAL="${3:-5}"

PIPELINE_ROOT="${PIPELINE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)/docs/pipeline}"
DAG_FILE="${SCRIPT_DIR}/pipeline-dag.json"

if [[ -z "$FEATURE_ID" ]]; then
    echo "Usage: $0 <feature_id> [--watch [interval] | --events [count]]"
    echo ""
    echo "Available pipeline runs:"
    for state_file in "${PIPELINE_ROOT}"/*/state.json; do
        [[ -f "$state_file" ]] || continue
        fid=$(basename "$(dirname "$state_file")")
        echo "  - ${fid}"
    done
    exit 1
fi

STATE_FILE="${PIPELINE_ROOT}/${FEATURE_ID}/state.json"
EVENTS_FILE="${PIPELINE_ROOT}/${FEATURE_ID}/events.jsonl"

if [[ ! -f "$STATE_FILE" ]]; then
    echo "Error: No pipeline state found at ${STATE_FILE}"
    exit 1
fi

render_panel() {
    FEATURE_ID="$FEATURE_ID" \
    PIPELINE_ROOT="$PIPELINE_ROOT" \
    DAG_FILE="$DAG_FILE" \
    STATE_FILE="$STATE_FILE" \
    EVENTS_FILE="$EVENTS_FILE" \
    python3 << 'DASHEOF'
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

effective_done = len(passed_ids) + len(skipped_ids)
pct = int(effective_done / total * 100) if total > 0 else 0
bar_len = 30
filled = int(bar_len * effective_done / total) if total > 0 else 0
bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

skip_desc = ""
if skipped_ids:
    skip_desc = f" ({'+'.join(skipped_ids)} 跳过)"

# ── Event index ──
skip_reasons = {}
retry_reasons = {}
fix_keywords = []

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

# ── Display width ──
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

ICONS = {
    "passed": "\u2705", "running": "\U0001f535", "gate_checking": "\U0001f50d",
    "failed": "\u274c", "dead_letter": "\U0001f480", "retrying": "\U0001f501",
    "human_waiting": "\u23f8\ufe0f", "skipped": "\u23ed\ufe0f", "pending": "\u23f3",
}

# ═══════════════ RENDER ═══════════════

print(f"\u2554{'═' * (W + 2)}\u2557")
print(bx(f"AI-SDLC Pipeline: {feature_id:<24s} {elapsed_str:>8s}"))
print(sep())
print(bx(""))
print(bx(f"进度: [{bar}] {pct:3d}%{skip_desc}"))
print(bx(""))

for sm in stages_meta:
    sid = sm["id"]
    sdata = stages_state.get(sid, {})
    st = sdata.get("status", "pending")
    ic = ICONS.get(st, "?")
    retry = sdata.get("retry_count", 0)

    if st == "running":
        detail = f"Claude CLI ({sm['model']}) 执行中..."
    elif st == "skipped":
        reason = skip_reasons.get(sid, "")
        detail = f"skipped ({reason[:30]})" if reason else "skipped (从后续恢复)"
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

    pm = ""
    if sm["name"] in par_groups:
        g = par_groups[sm["name"]]
        if sm["name"] == g[0]: pm = "┌ "
        elif sm["name"] == g[-1]: pm = "└ "
        else: pm = "│ "

    print(bx(f"{pm}{sid:<4s} {sm['cn']:<8s}  {ic}  {detail}"))

print(bx(""))

usd = cost.get("estimated_usd", 0.0)
tokens = cost.get("total_tokens", 0)
print(bx(f"运行时间: {elapsed_str}  |  估计总成本: ~${usd:.2f}"))

if fix_keywords:
    fix_summary = f"修复汇总: {len(fix_keywords)} 个 ({', '.join(fix_keywords[:3])})"
    if len(fix_summary) > W - 2:
        fix_summary = fix_summary[:W - 5] + "..."
    print(bx(fix_summary))

for sm in stages_meta:
    sid = sm["id"]
    if stages_state.get(sid, {}).get("status") in ("running", "gate_checking"):
        print(bx(f"{sid} Agent: {sm['agent']} ({sm['model']}, timeout {sm['timeout']}s)"))
        for dep in sm["deps"]:
            dep_stage = dag["stages"].get(dep, {})
            dep_id = dep_stage.get("id", dep)
            dep_out = f"{pipeline_root}/{feature_id}/{dep_id}-{dep}/output.json"
            if os.path.exists(dep_out):
                sz = os.path.getsize(dep_out) / 1024
                dep_cn = CN.get(dep, dep)
                action = "正在生成" + CN.get(sm["name"], sm["name"])
                print(bx(f"输入: {dep_id}-{dep}/output.json ({sz:.0f}KB) → {action}"))

print(f"\u255a{'═' * (W + 2)}\u255d")

# Pipeline completion summary
end_ev = next((e for e in reversed(events) if e.get("event_type") in ("pipeline_end", "pipeline_fail")), None)
if end_ev:
    is_ok = "success" in end_ev.get("message", "")
    emoji = "\u2705" if is_ok else "\u274c"
    label = "COMPLETE" if is_ok else "FAILED"
    print(f"\n{emoji} Pipeline {label}")
    print(f"   Passed: {len(passed_ids)}/{total} | Failed: {len(failed_ids)} | Cost: ${usd:.2f} | Tokens: {tokens:,}")
DASHEOF
}

show_events() {
    local limit="${1:-50}"
    EVENTS_FILE="$EVENTS_FILE" LIMIT="$limit" python3 << 'PYEOF'
import json, os
events_file = os.environ["EVENTS_FILE"]
limit = int(os.environ.get("LIMIT", "50"))
if not os.path.exists(events_file):
    print(f"No events found: {events_file}")
    exit(1)
with open(events_file) as f:
    lines = f.readlines()
print(f"Event Log ({len(lines)} total, showing last {limit}):\n")
colors = {
    "pipeline_start": "\033[1;36m", "pipeline_end": "\033[1;32m",
    "pipeline_fail": "\033[1;31m",
    "stage_start": "\033[0;36m", "stage_pass": "\033[0;32m",
    "stage_fail": "\033[0;31m",
    "gate_pass": "\033[0;32m", "gate_fail": "\033[0;33m",
    "retry": "\033[0;33m", "dead_letter": "\033[0;31m",
    "cost_update": "\033[0;35m", "human_wait": "\033[1;33m",
    "parallel_start": "\033[0;35m", "parallel_end": "\033[0;35m",
}
reset = "\033[0m"
for line in lines[-limit:]:
    line = line.strip()
    if not line: continue
    try: ev = json.loads(line)
    except: continue
    ts = ev.get("timestamp", "")[:19].replace("T", " ")
    etype = ev.get("event_type", "unknown")
    sid = ev.get("stage_id", "-")
    msg = ev.get("message", "")
    color = colors.get(etype, "")
    print(f"  {color}[{ts}] {sid:4s} {etype:16s} {msg}{reset}")
PYEOF
}

# --- Main ---
case "$MODE" in
    --watch)
        while true; do
            clear 2>/dev/null || true
            render_panel
            echo -e "\n  \033[2mRefreshing every ${INTERVAL}s... (Ctrl+C to stop)\033[0m"
            sleep "$INTERVAL"
        done
        ;;
    --events)
        show_events "${3:-50}"
        ;;
    *)
        render_panel
        ;;
esac
