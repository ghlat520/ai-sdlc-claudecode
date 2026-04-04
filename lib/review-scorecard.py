#!/usr/bin/env python3
"""
review-scorecard.py — 人工审核量化决策框架生成器

为每个 human-required gate 自动：
1. 从前置阶段拉取量化指标
2. 对比阈值计算得分
3. 生成加权决策评分卡
4. 输出决策建议 + 思考引导

用法：
  python3 review-scorecard.py <pipeline_root> <feature_id> <stage_id>
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime


def load_json(path):
    """安全加载 JSON 文件"""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def score_metric(actual, threshold, direction="gte"):
    """
    量化评分：actual vs threshold
    direction: gte=越大越好, lte=越小越好, eq=精确匹配
    返回 0-100 分
    """
    if actual is None or threshold is None:
        return None
    try:
        actual = float(actual)
        threshold = float(threshold)
    except (TypeError, ValueError):
        return None

    if direction == "gte":
        return min(100, int(actual / threshold * 100)) if threshold > 0 else 100
    elif direction == "lte":
        return min(100, int(threshold / actual * 100)) if actual > 0 else 100
    elif direction == "eq":
        return 100 if actual == threshold else max(0, 100 - abs(actual - threshold) * 10)
    return None


def traffic_light(score):
    """评分转红绿灯"""
    if score is None:
        return "⬜ N/A"
    if score >= 80:
        return f"🟢 {score}"
    elif score >= 60:
        return f"🟡 {score}"
    else:
        return f"🔴 {score}"


# ═══════════════════════════════════════════════════════
# 各阶段的量化指标定义
# ═══════════════════════════════════════════════════════

def scorecard_S0p(base):
    """S0p 产品发现 — 决策框架"""
    prd = load_json(f"{base}/S0p-product-discovery/output.json")
    metrics = []

    if prd:
        # 检查关键字段完整性
        fields = ["problem_statement", "target_users", "demand_evidence",
                   "scope", "success_metrics", "competitive_analysis"]
        present = sum(1 for f in fields if prd.get(f) or prd.get("product_discovery", {}).get(f))
        metrics.append({
            "name": "字段完整度",
            "actual": f"{present}/{len(fields)}",
            "threshold": f"{len(fields)}/{len(fields)}",
            "score": score_metric(present, len(fields)),
            "weight": 25,
        })

        # 需求证据强度
        evidence = prd.get("demand_evidence", prd.get("product_discovery", {}).get("demand_evidence", {}))
        if isinstance(evidence, dict):
            evidence_types = len(evidence)
        elif isinstance(evidence, list):
            evidence_types = len(evidence)
        else:
            evidence_types = 1 if evidence else 0
        metrics.append({
            "name": "需求证据数量",
            "actual": evidence_types,
            "threshold": 3,
            "score": score_metric(evidence_types, 3),
            "weight": 30,
        })

        # 范围是否明确
        scope = prd.get("scope", prd.get("product_discovery", {}).get("scope", {}))
        has_in = bool(scope.get("in_scope") or scope.get("included") if isinstance(scope, dict) else scope)
        has_out = bool(scope.get("out_of_scope") or scope.get("excluded") if isinstance(scope, dict) else False)
        scope_score = (50 if has_in else 0) + (50 if has_out else 0)
        metrics.append({
            "name": "范围边界清晰度",
            "actual": f"IN={'✓' if has_in else '✗'} OUT={'✓' if has_out else '✗'}",
            "threshold": "IN=✓ OUT=✓",
            "score": scope_score,
            "weight": 25,
        })
    else:
        metrics.append({"name": "产品发现报告", "actual": "未找到", "threshold": "必须存在", "score": 0, "weight": 100})

    thinking_prompts = [
        "这个痛点你在一线听到过几次？AI 生成的证据和你的直觉一致吗？",
        "如果只用一句话描述这个产品解决什么问题，你能说出来吗？说不出来=范围不清晰。",
        "做这个的机会成本是什么？你团队接下来 2 周不做什么？",
        "最坏情况：做完没人用，你能承受这个损失吗？",
    ]
    return metrics, thinking_prompts


def scorecard_S0(base):
    """S0 战略评审 — 决策框架"""
    review = load_json(f"{base}/S0-strategic-review/output.json")
    metrics = []

    if review:
        sr = review.get("strategic_review", review)

        # ROI 评估
        roi = sr.get("roi_estimate", sr.get("roi", {}))
        if isinstance(roi, dict):
            roi_val = roi.get("value", roi.get("estimated_roi"))
        else:
            roi_val = roi
        metrics.append({
            "name": "ROI 估算",
            "actual": roi_val or "未评估",
            "threshold": "> 2x",
            "score": score_metric(roi_val, 2) if isinstance(roi_val, (int, float)) else None,
            "weight": 25,
        })

        # 风险矩阵
        risks = sr.get("risks", sr.get("risk_matrix", []))
        high_risks = sum(1 for r in risks if isinstance(r, dict) and r.get("impact") == "high") if isinstance(risks, list) else 0
        total_risks = len(risks) if isinstance(risks, list) else 0
        mitigated = sum(1 for r in risks if isinstance(r, dict) and r.get("mitigation")) if isinstance(risks, list) else 0
        metrics.append({
            "name": "高影响风险数",
            "actual": high_risks,
            "threshold": "≤ 2",
            "score": score_metric(2, high_risks, "gte") if high_risks > 0 else 100,
            "weight": 25,
        })
        metrics.append({
            "name": "风险缓解覆盖率",
            "actual": f"{mitigated}/{total_risks}",
            "threshold": "100%",
            "score": score_metric(mitigated, total_risks) if total_risks > 0 else 100,
            "weight": 20,
        })

        # GO/NO-GO 评分
        go_score = sr.get("go_score", sr.get("design_score", sr.get("overall_score")))
        metrics.append({
            "name": "AI GO/NO-GO 评分",
            "actual": go_score or "未评估",
            "threshold": "≥ 70",
            "score": score_metric(go_score, 70) if isinstance(go_score, (int, float)) else None,
            "weight": 30,
        })
    else:
        metrics.append({"name": "战略评审报告", "actual": "未找到", "threshold": "必须存在", "score": 0, "weight": 100})

    thinking_prompts = [
        "AI 估算的 ROI 基于什么假设？用户量/转化率/客单价 哪个最脆弱？",
        "高影响风险的缓解方案是否实际可执行？还是纸上谈兵？",
        "如果竞品下个月发布类似功能，你的差异化在哪？",
        "你愿意在这个方向上 all-in 3 个月吗？不愿意说明信心不足。",
    ]
    return metrics, thinking_prompts


def scorecard_S2b(base):
    """S2b UI 设计 — 决策框架"""
    design = load_json(f"{base}/S2b-ui-design/output.json")
    prd = load_json(f"{base}/S1-requirements/output.json")
    metrics = []

    if design:
        ds = design.get("ui_design", design)

        # 页面完整性 vs PRD 用户故事
        pages = ds.get("pages", ds.get("page_inventory", []))
        page_count = len(pages) if isinstance(pages, list) else 0
        metrics.append({
            "name": "页面数量",
            "actual": page_count,
            "threshold": "≥ 5 (MVP)",
            "score": score_metric(page_count, 5),
            "weight": 25,
        })

        # 组件复用率
        components = ds.get("components", ds.get("component_plan", []))
        custom = sum(1 for c in components if isinstance(c, dict) and c.get("custom", False)) if isinstance(components, list) else 0
        total_comp = len(components) if isinstance(components, list) else 0
        reuse_rate = ((total_comp - custom) / total_comp * 100) if total_comp > 0 else 0
        metrics.append({
            "name": "组件复用率",
            "actual": f"{reuse_rate:.0f}%",
            "threshold": "≥ 70%",
            "score": score_metric(reuse_rate, 70),
            "weight": 25,
        })

        # 导航层级
        nav = ds.get("navigation", ds.get("navigation_structure", {}))
        max_depth = nav.get("max_depth", 3) if isinstance(nav, dict) else 3
        metrics.append({
            "name": "导航最大层级",
            "actual": max_depth,
            "threshold": "≤ 3",
            "score": score_metric(3, max_depth, "gte"),
            "weight": 25,
        })

        # 移动端适配
        has_mobile = any(
            "mobile" in str(p).lower() or "移动" in str(p)
            for p in (pages if isinstance(pages, list) else [])
        )
        metrics.append({
            "name": "移动端适配",
            "actual": "✓" if has_mobile else "✗",
            "threshold": "✓",
            "score": 100 if has_mobile else 0,
            "weight": 25,
        })
    else:
        metrics.append({"name": "UI 设计报告", "actual": "未找到", "threshold": "必须存在", "score": 0, "weight": 100})

    thinking_prompts = [
        "你的目标用户最常用手机还是电脑？这决定了移动端优先级。",
        "页面数量是否最小化？每多一个页面 = 多一份开发和维护成本。",
        "你能在 10 秒内画出主流程的页面跳转吗？画不出来=导航不直觉。",
        "有没有用户操作需要 >5 次点击？每次点击流失 20% 用户。",
    ]
    return metrics, thinking_prompts


def scorecard_S6(base):
    """S6 部署 — 决策框架"""
    deploy = load_json(f"{base}/S6-deployment/deployment.json")
    s5_output = load_json(f"{base}/S5-review/output.json")
    s4_output = load_json(f"{base}/S4-testing/output.json")
    s4b_output = load_json(f"{base}/S4b-integration-testing/output.json") or \
                 load_json(f"{base}/S4b-integration-testing/integration-testing.json")
    s9_output = load_json(f"{base}/S9-performance/output.json")
    metrics = []

    # 1. 测试通过率
    test_pass_rate = None
    if s4b_output:
        testing = s4b_output.get("testing", s4b_output)
        total = testing.get("total_tests", 0)
        passed = testing.get("passed", 0)
        if total > 0:
            test_pass_rate = passed / total * 100
    metrics.append({
        "name": "集成测试通过率",
        "actual": f"{test_pass_rate:.1f}%" if test_pass_rate is not None else "N/A",
        "threshold": "100%",
        "score": score_metric(test_pass_rate, 100) if test_pass_rate else None,
        "weight": 25,
    })

    # 2. S5 Critical issues
    critical_count = 0
    unfixed_critical = 0
    if s5_output:
        issues = s5_output.get("issues", s5_output.get("findings", []))
        for i in issues:
            if isinstance(i, dict) and i.get("severity") in ("critical", "CRITICAL"):
                critical_count += 1
                if i.get("status") != "fixed":
                    unfixed_critical += 1
    metrics.append({
        "name": "未修复 Critical 问题",
        "actual": unfixed_critical,
        "threshold": "0",
        "score": 100 if unfixed_critical == 0 else max(0, 100 - unfixed_critical * 30),
        "weight": 30,
    })

    # 3. 性能达标率
    perf_pass_rate = None
    if s9_output:
        benchmarks = s9_output.get("benchmarks", [])
        if isinstance(benchmarks, list) and benchmarks:
            passed = sum(1 for b in benchmarks if isinstance(b, dict) and b.get("passed"))
            perf_pass_rate = passed / len(benchmarks) * 100
    metrics.append({
        "name": "性能基准达标率",
        "actual": f"{perf_pass_rate:.0f}%" if perf_pass_rate else "N/A",
        "threshold": "100%",
        "score": score_metric(perf_pass_rate, 100) if perf_pass_rate else None,
        "weight": 20,
    })

    # 4. 回滚方案完整性
    rollback_score = 0
    if deploy:
        rollback = deploy.get("deployment", {}).get("rollback_plan", deploy.get("rollback_plan", {}))
        if isinstance(rollback, dict):
            has_steps = bool(rollback.get("steps"))
            has_time = bool(rollback.get("estimated_time"))
            reversible = rollback.get("data_migration_reversible", False)
            rollback_score = (40 if has_steps else 0) + (30 if has_time else 0) + (30 if reversible else 0)
    metrics.append({
        "name": "回滚方案完整度",
        "actual": f"{rollback_score}%",
        "threshold": "100%",
        "score": rollback_score,
        "weight": 15,
    })

    # 5. 环境变量配置
    env_total = 0
    env_sensitive = 0
    if deploy:
        env_changes = deploy.get("deployment", {}).get("environment_changes", [])
        env_total = len(env_changes)
        env_sensitive = sum(1 for e in env_changes if isinstance(e, dict) and e.get("sensitive"))
    metrics.append({
        "name": "敏感环境变量数",
        "actual": f"{env_sensitive} 项需配置",
        "threshold": "全部已配置",
        "score": None,  # 需人工确认
        "weight": 10,
    })

    thinking_prompts = [
        f"当前有 {unfixed_critical} 个未修复 Critical — 0 才能部署。每个 Critical 都是生产事故的种子。",
        "现在是低峰期吗？部署后有人值班观察 30 分钟吗？",
        f"回滚方案估计 {deploy.get('deployment', {}).get('rollback_plan', {}).get('estimated_time', '?')} — 你实际演练过吗？没演练过的回滚 = 不存在。",
        f"有 {env_sensitive} 个敏感变量要配 — 你确认生产环境已经配好了？配错一个 = 全站故障。",
    ]
    return metrics, thinking_prompts


def scorecard_S10(base):
    """S10 发布 — 决策框架"""
    s4b_output = load_json(f"{base}/S4b-integration-testing/output.json") or \
                 load_json(f"{base}/S4b-integration-testing/integration-testing.json")
    s5_output = load_json(f"{base}/S5-review/output.json")
    s7_output = load_json(f"{base}/S7-monitoring/output.json")
    s8_output = load_json(f"{base}/S8-documentation/output.json")
    s9_output = load_json(f"{base}/S9-performance/output.json")
    state = load_json(f"{base}/state.json")
    metrics = []

    # 1. 全链路通过率
    if state:
        stages = state.get("stages", {})
        total = len(stages)
        passed = sum(1 for s in stages.values() if s.get("status") == "passed")
        metrics.append({
            "name": "Pipeline 阶段通过率",
            "actual": f"{passed}/{total} ({passed/total*100:.0f}%)",
            "threshold": "100%",
            "score": score_metric(passed, total),
            "weight": 20,
        })
        # 总重试次数
        total_retries = sum(s.get("retry_count", 0) for s in stages.values())
        metrics.append({
            "name": "总重试次数",
            "actual": total_retries,
            "threshold": "≤ 5",
            "score": max(0, 100 - total_retries * 10),
            "weight": 10,
        })

    # 2. 测试覆盖
    if s4b_output:
        testing = s4b_output.get("testing", s4b_output)
        total_tests = testing.get("total_tests", 0)
        passed_tests = testing.get("passed", 0)
        failed_tests = testing.get("failed", 0)
        metrics.append({
            "name": "测试通过",
            "actual": f"{passed_tests} 通过 / {failed_tests} 失败 / {total_tests} 总计",
            "threshold": "0 失败",
            "score": 100 if failed_tests == 0 else max(0, 100 - failed_tests * 20),
            "weight": 20,
        })

    # 3. 性能
    if s9_output:
        benchmarks = s9_output.get("benchmarks", [])
        if isinstance(benchmarks, list):
            perf_passed = sum(1 for b in benchmarks if isinstance(b, dict) and b.get("passed"))
            metrics.append({
                "name": "性能基准达标",
                "actual": f"{perf_passed}/{len(benchmarks)}",
                "threshold": "100%",
                "score": score_metric(perf_passed, len(benchmarks)),
                "weight": 15,
            })
        # 压测
        load = s9_output.get("load_test", {})
        if load:
            error_rate = load.get("error_rate", 0)
            p99 = load.get("p99_ms", 0)
            metrics.append({
                "name": "压测错误率",
                "actual": f"{error_rate}%",
                "threshold": "< 1%",
                "score": score_metric(1, error_rate, "gte") if error_rate > 0 else 100,
                "weight": 10,
            })
            metrics.append({
                "name": "压测 P99 延迟",
                "actual": f"{p99}ms",
                "threshold": "< 500ms",
                "score": score_metric(500, p99, "gte") if p99 > 0 else 100,
                "weight": 5,
            })

        # 优化建议
        recommendations = s9_output.get("recommendations", [])
        critical_recs = sum(1 for r in recommendations if isinstance(r, dict) and r.get("impact") == "critical")
        high_recs = sum(1 for r in recommendations if isinstance(r, dict) and r.get("impact") == "high")
        metrics.append({
            "name": "Critical/High 优化建议",
            "actual": f"{critical_recs} critical + {high_recs} high",
            "threshold": "0 critical",
            "score": max(0, 100 - critical_recs * 30 - high_recs * 10),
            "weight": 10,
        })

    # 4. 监控
    if s7_output:
        alerts = s7_output.get("alerts", s7_output.get("monitoring_alerts",
                 s7_output.get("monitoring", {}).get("alerts", [])))
        alert_count = len(alerts) if isinstance(alerts, list) else 0
        metrics.append({
            "name": "监控告警规则数",
            "actual": alert_count,
            "threshold": "≥ 10",
            "score": score_metric(alert_count, 10),
            "weight": 5,
        })

    # 5. 文档
    if s8_output:
        docs = s8_output.get("documentation", s8_output.get("docs", {}))
        doc_sections = len(docs) if isinstance(docs, (dict, list)) else 0
        metrics.append({
            "name": "文档模块数",
            "actual": doc_sections,
            "threshold": "≥ 3 (API/架构/运维)",
            "score": score_metric(doc_sections, 3),
            "weight": 5,
        })

    # 6. 成本
    if state:
        cost = state.get("cost", {}).get("estimated_usd", 0)
        limit = state.get("config", {}).get("cost_limit_usd", 500)
        metrics.append({
            "name": "Pipeline 成本",
            "actual": f"${cost:.2f}",
            "threshold": f"< ${limit:.0f}",
            "score": score_metric(limit, cost, "gte") if cost > 0 else 100,
            "weight": 0,  # 信息性指标，不参与评分
        })

    thinking_prompts = [
        "[D1 发布时机] 现在发还是等？业务日历上有冲突吗？团队有人值班观察吗？",
        "[D2 技术债] S9 的 Critical 建议（Redis 未缓存/序列号并发/CSV 内存）— 你能接受 MVP 带着这些上线吗？最坏情况是什么？",
        "[D3 Release Notes] 如果用户遇到了已知限制，他们会觉得被欺骗还是被尊重？诚实 > 完美。",
        "[验证] 以上所有编译/测试/冒烟/安全扫描已由 S3-S9 自动完成，你不需要手动验证任何一项。如果评分卡全绿，你的唯一工作是做决策。",
    ]
    return metrics, thinking_prompts


# ═══════════════════════════════════════════════════════
# 决策评分卡渲染
# ═══════════════════════════════════════════════════════

SCORECARD_FN = {
    "S0p": scorecard_S0p,
    "S0": scorecard_S0,
    "S2b": scorecard_S2b,
    "S6": scorecard_S6,
    "S10": scorecard_S10,
}


def render_scorecard(stage_id, base, dag_path):
    """生成完整的量化审核报告"""
    # 加载 DAG 获取 review_guide
    dag = load_json(dag_path)
    stage_name = None
    gate = {}
    if dag:
        for name, stage in dag.get("stages", {}).items():
            if stage.get("id") == stage_id:
                stage_name = name
                gate = stage.get("gate", {})
                break

    guide = gate.get("review_guide", {})
    fn = SCORECARD_FN.get(stage_id)
    if not fn:
        return f"No scorecard defined for {stage_id}"

    metrics, thinking_prompts = fn(base)

    # 计算加权总分
    weighted_sum = 0
    weight_total = 0
    for m in metrics:
        if m["score"] is not None and m["weight"] > 0:
            weighted_sum += m["score"] * m["weight"]
            weight_total += m["weight"]
    overall = int(weighted_sum / weight_total) if weight_total > 0 else 0

    # 决策建议
    if overall >= 80:
        recommendation = "✅ RECOMMEND APPROVE — 量化指标全面达标"
        confidence = "高"
    elif overall >= 60:
        recommendation = "🟡 CONDITIONAL — 有可改进项，评估是否阻塞"
        confidence = "中"
    else:
        recommendation = "🔴 RECOMMEND HOLD — 多项指标未达标，建议修复后再审"
        confidence = "低"

    # 渲染
    lines = []
    lines.append(f"{'=' * 60}")
    lines.append(f"  {stage_id} 量化决策评分卡")
    lines.append(f"  生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"{'=' * 60}")
    lines.append("")

    # WHY
    if guide.get("why"):
        lines.append(f"为什么需要你: {guide['why']}")
        lines.append("")

    # 量化指标表
    lines.append(f"{'─' * 60}")
    lines.append(f"  {'指标':<20s} {'实际值':<18s} {'阈值':<12s} {'得分':>6s} {'权重':>4s}")
    lines.append(f"{'─' * 60}")
    for m in metrics:
        tl = traffic_light(m["score"])
        actual_str = str(m["actual"])[:16]
        threshold_str = str(m["threshold"])[:10]
        weight_str = f"{m['weight']}%" if m["weight"] > 0 else "info"
        lines.append(f"  {m['name']:<20s} {actual_str:<18s} {threshold_str:<12s} {tl:>6s} {weight_str:>4s}")
    lines.append(f"{'─' * 60}")
    lines.append(f"  加权总分: {traffic_light(overall)}  / 100")
    lines.append(f"  决策建议: {recommendation}")
    lines.append(f"  决策信心: {confidence}")
    lines.append("")

    # STAR
    star = guide.get("star", {})
    if star:
        lines.append(f"{'─' * 60}")
        lines.append("  决策上下文 (STAR)")
        lines.append(f"{'─' * 60}")
        lines.append(f"  Situation: {star.get('situation', '')}")
        lines.append(f"  Task:      {star.get('task', '')}")
        lines.append(f"  Action:    {star.get('action', '')}")
        lines.append(f"  Result:    {star.get('result', '')}")
        lines.append("")

    # 思考引导
    lines.append(f"{'─' * 60}")
    lines.append("  决策质量提升 — 你必须回答的问题")
    lines.append(f"{'─' * 60}")
    for i, q in enumerate(thinking_prompts, 1):
        lines.append(f"  {i}. {q}")
    lines.append("")

    # 批准/拒绝信号
    if guide.get("approve_signal"):
        lines.append(f"  ✅ 批准条件: {guide['approve_signal']}")
    if guide.get("reject_signal"):
        lines.append(f"  ❌ 拒绝条件: {guide['reject_signal']}")
    lines.append("")

    # 决策记录
    lines.append(f"{'─' * 60}")
    lines.append("  你的决策记录（建议填写后保存）")
    lines.append(f"{'─' * 60}")
    lines.append("  决策: [ ] APPROVE  [ ] HOLD  [ ] REJECT")
    lines.append("  理由: ")
    lines.append("  风险接受: ")
    lines.append("  下一步行动: ")
    lines.append(f"{'=' * 60}")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <pipeline_root> <feature_id> <stage_id>")
        sys.exit(1)

    pipeline_root = sys.argv[1]
    feature_id = sys.argv[2]
    stage_id = sys.argv[3]
    dag_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline-dag.json")

    base = os.path.join(pipeline_root, feature_id)
    print(render_scorecard(stage_id, base, dag_path))
