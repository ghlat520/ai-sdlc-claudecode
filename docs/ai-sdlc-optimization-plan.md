# ai-sdlc-claudecode 优化方案

> Layer 4 编排层架构分析与优化路径
> 基于 ai-media-platform Phase 2 真实运行复盘（2026-03-19）

---

## 核心结论

**ai-sdlc-claudecode 的核心矛盾是"Python 侧设计精良但 Bash 侧承担过重"。1026 行 pipeline-executor.sh 内嵌 ~15 个 Python 片段，形成了双语言割裂。优化路径不是推倒重写，而是渐进式迁移：Bash 做调度壳，Python 做决策核。**

---

## 现状代码审计

### 文件架构

```
ai-sdlc-claudecode/
├── pipeline-executor.sh      # 1026行 — 主编排器（过重）
├── orchestrate-parallel.sh   # 538行 — 并行执行器（含worktree隔离）
├── ai-review-checker.sh      # 520行 — AI审查门
├── lib/
│   ├── events.sh             # 347行 — 事件/状态/成本/通知
│   └── protocol.sh           # 316行 — Agent间通信协议
├── src/ai_sdlc_claudecode/
│   ├── engine.py             # 474行 — 错误学习引擎（精良）
│   ├── summarizer.py         # 294行 — 智能上下文裁剪（精良）
│   ├── memory.py             # 195行 — 共享内存（原子写入，精良）
│   ├── runner.py             # 164行 — Python包装器（未充分利用）
│   ├── state.py              # 状态管理
│   ├── config.py             # 配置管理
│   └── cli.py                # CLI入口
├── pipeline-dag.json         # 707行 — 13阶段DAG定义
├── schemas/                  # 13个输出Schema
└── tests/                    # 测试文件
```

### 健康度评估

| 组件 | 行数 | 质量 | 问题 |
|------|------|------|------|
| pipeline-executor.sh | 1026 | C | 过大、双语言混合、eval注入风险、难以测试 |
| orchestrate-parallel.sh | 538 | B | 功能完整但worktree在非git项目中脆弱 |
| ai-review-checker.sh | 520 | B | 已修复模型预检，但regex提取JSON脆弱 |
| lib/events.sh | 347 | B | 功能完整，但python3调用过多（每次事件一次fork） |
| lib/protocol.sh | 316 | A | 设计清晰，MetaGPT通信协议 |
| engine.py | 474 | A | 不可变数据、确定性分类、自我进化 |
| summarizer.py | 294 | A | 策略表驱动、可扩展 |
| memory.py | 195 | A | fcntl锁、原子写入、TTL过期 |
| runner.py | 164 | B- | 存在但几乎未使用（Bash直接跑pipeline） |

---

## 10 个问题 × 5W1H 分析

### 问题 1：Bash-Python 双语言割裂

| 维度 | 分析 |
|------|------|
| **What** | pipeline-executor.sh 内嵌 ~15 个 `python3 -c "..."` 和 `python3 << 'PYEOF'` 代码块 |
| **Why** | 历史原因——先写 Bash 壳，再逐步加 Python 能力。两边各自生长 |
| **Who** | pipeline-executor.sh (DAG解析、状态更新、成本计算、Prompt构建全用内联Python) |
| **When** | 每次stage执行时：DAG解析1次 + Prompt构建1次 + 成本更新1次 + 状态更新2-3次 = ~5次python3 fork/stage |
| **Where** | `pipeline-executor.sh:41-71`(DAG解析), `224-317`(Prompt构建), `423`(token估算) |
| **How改** | **渐进迁移**：Python 暴露 CLI 子命令，Bash 调用 `ai-sdlc build-prompt S3` 替代内联Python |

**优化动作：**
```
Phase 1: cli.py 暴露子命令
  ai-sdlc build-prompt <stage> <feature_id> <desc>
  ai-sdlc update-state <feature_id> <stage_id> <status>
  ai-sdlc update-cost <feature_id> <tokens> <model>
  ai-sdlc check-cost <feature_id>

Phase 2: pipeline-executor.sh 调用子命令替代内联Python

Phase 3: runner.py 升级为主编排器，Bash降为启动入口
```

**投入**: 中 | **回报**: 高（可测试性、可维护性大幅提升）

---

### 问题 2：Token 计数不准确

| 维度 | 分析 |
|------|------|
| **What** | `est_tokens=$(( (${#prompt} + ${#claude_output}) / 4 ))` — 字符数/4 估算token |
| **Why** | `claude --print` 不返回 usage 信息，只返回纯文本 |
| **Who** | pipeline-executor.sh:423, 影响 events.sh:update_cost |
| **When** | 每个stage完成后。ai-media-platform 报告 106,720 tokens / $1.17，但实际可能偏差 30%+ |
| **Where** | 成本追踪链：executor→update_cost→state.json |
| **How改** | 用 `claude --print --output-format json` 或解析 stderr 中的 usage 信息（如果CLI支持）；否则改用分段计费：input_tokens = prompt_chars/3.5, output_tokens = output_chars/4.5（更精确的中英文混合比例） |

**优化动作：**
1. 检查 `claude --print --verbose` 是否输出 token usage
2. 若不支持，优化估算公式：区分中文（~2 chars/token）和英文（~4 chars/token）
3. 将估算逻辑收到 Python 侧（config.py 中的 PRICING 表已经有）

**投入**: 低 | **回报**: 中（成本报告更可信）

---

### 问题 3：JSON 输出提取脆弱

| 维度 | 分析 |
|------|------|
| **What** | 从 claude 输出中用 regex 提取 JSON：`` r'\`\`\`json\n(.*?)\n\`\`\`' `` |
| **Why** | claude --print 返回自由文本，可能包含解释性文字+JSON混合 |
| **Who** | pipeline-executor.sh:463-494, orchestrate-parallel.sh:399-423 |
| **When** | 每个stage完成后。Phase 2 中依赖此逻辑提取所有 output.json |
| **Where** | 两处重复的 regex 提取逻辑（DRY违反） |
| **How改** | (1) Prompt 中强制 `"ONLY output raw JSON, no markdown"` (2) 提取逻辑抽到 Python 工具函数 (3) 多级 fallback：先 json.loads 整体 → 再 regex → 再 LLM 修复 |

**优化动作：**
1. 创建 `src/ai_sdlc_claudecode/extract.py` — 统一 JSON 提取逻辑
2. 增加 json-repair 策略（去除 BOM、修复尾逗号、补全括号）
3. 两处 Bash 调用统一为 `ai-sdlc extract-json <raw_file> <output_file>`

**投入**: 低 | **回报**: 高（减少 stage 失败率）

---

### 问题 4：ErrorEngine 默认未启用

| 维度 | 分析 |
|------|------|
| **What** | ErrorEngine 仅在 `EVOLVE_ERRORS_DIR` 环境变量设置时启用 |
| **Why** | 设计为 opt-in，避免非 evolve 模式下的额外 I/O |
| **Who** | pipeline-executor.sh:33-35, 385-451（evolve 相关逻辑全在 if 块内） |
| **When** | Phase 2 运行中 S3 超时 3 次，但 ErrorEngine 未捕获这些失败（因为没设 env） |
| **Where** | 错误分类(classify)和修复模式(extract_pattern)完全可用，但被 if 门控住了 |
| **How改** | **默认启用 ErrorEngine**，错误目录用 `${PIPELINE_ROOT}/${feature_id}/evolve/`（已在上次修复中部分实现——dead_letter 写 evolve/failures/，但 ErrorEngine.capture_realtime 仍需 env var） |

**优化动作：**
1. 移除 `EVOLVE_MODE` 门控，改为始终初始化 ErrorEngine
2. ErrorEngine 目录默认为 `${PIPELINE_ROOT}/${feature_id}/evolve/`
3. 每次 stage 失败时自动调用 `capture_realtime`，下次重试自动注入 augment

**投入**: 低 | **回报**: 高（失败自愈从 opt-in 变为默认行为）

---

### 问题 5：StageSummarizer 集成不完整

| 维度 | 分析 |
|------|------|
| **What** | summarizer.py 有完善的策略表（S2→S10每个stage需要哪些upstream字段），但 build_prompt 中有 `try/except` fallback |
| **Why** | `sys.path.insert` 动态导入可能失败（路径不对、Python 版本、import 错误） |
| **Who** | pipeline-executor.sh:252-289（build_prompt 函数） |
| **When** | Phase 2 中可能走了 fallback 路径（50000 char 截断），导致下游 stage 收到过多或过少上下文 |
| **Where** | summarizer.py 的 CONTEXT_STRATEGY 表设计良好，但与 Bash 侧的集成不够稳固 |
| **How改** | (1) 改为 CLI 子命令调用 (2) 添加 summarizer 健康检查 (3) fallback 时记录事件（当前静默失败） |

**优化动作：**
1. `ai-sdlc build-context <target_stage> <upstream_dir>` — CLI 子命令
2. fallback 时 emit_event 记录（不再静默 pass）
3. 每个 stage 完成后自动生成 `{stage_id}-summary.json`（summarizer.summarize_output 已有此能力，但未被调用）

**投入**: 中 | **回报**: 高（上下文质量直接影响所有下游 stage 输出质量）

---

### 问题 6：并行执行中无重试机制

| 维度 | 分析 |
|------|------|
| **What** | orchestrate-parallel.sh 中 agent 失败后直接标记 failed，无重试 |
| **Why** | 顺序执行有 `while retry_count <= max_retry` 循环，但并行执行器没有 |
| **Who** | orchestrate-parallel.sh:346-374 |
| **When** | 并行组（如 S3+S3b, S4+S4b+S4c）中任一 agent 失败则整组失败 |
| **Where** | Phase 2 中 S3/S3b 是并行组，S3 超时 3 次——但这些重试发生在顺序执行路径（说明实际跑的是顺序模式） |
| **How改** | 并行执行器增加 per-stage 重试：失败的 stage 单独重试，不影响已成功的 stage |

**优化动作：**
1. 并行 agent 失败后，进入串行重试（不再重新启动整组）
2. 已成功的 stage 保持 passed 状态
3. 重试次数读取 DAG 的 max_retries 配置

**投入**: 中 | **回报**: 高（并行组的容错性从 0 提升到与顺序一致）

---

### 问题 7：Gate 检查缺少真实编译验证

| 维度 | 分析 |
|------|------|
| **What** | S3/S3b 的 gate 是 ai-review（语义检查），但不验证代码是否真正能编译 |
| **Why** | `claude --print` 生成的是 JSON 格式的"代码描述"，不是直接写入文件系统的源码 |
| **Who** | pipeline-dag.json S3 gate: `"commands": ["compile_passes", "no_new_warnings"]` — 这些是检查名称，不是实际命令 |
| **When** | Phase 2 中 S5 审查发现了 3 HIGH 问题（含安全漏洞），说明 S3 gate 未真正验证代码质量 |
| **Where** | auto gate 的 `eval "$cmd"` 逻辑存在，但 DAG 中 S3 gate type 是 `ai-review`，不是 `auto` |
| **How改** | (1) S3/S3b 增加 post-stage hook：将生成的代码写入实际文件 → 运行编译命令 (2) 或改 gate 为 `auto` + `ai-review` 组合 |

**优化动作：**
1. 支持混合 gate：`"type": "auto+ai-review"` — 先 auto 编译验证，再 AI 语义审查
2. S3 gate commands 改为实际可执行命令（根据 tech_stack_commands 配置）
3. 编译失败自动触发 ErrorEngine，注入修复 prompt 重试

**投入**: 中 | **回报**: 高（在 S3 就拦截编译错误，而非等到 S5 审查才发现）

---

### 问题 8：events.sh 每次事件 fork python3

| 维度 | 分析 |
|------|------|
| **What** | emit_event 调用 `python3 -c "..."` 生成 JSON；set_stage_state 调用 `python3 -c "..."` 更新 state.json |
| **Why** | Bash 原生 JSON 处理能力弱，依赖 Python |
| **Who** | lib/events.sh — 每个 stage 至少触发 5-8 次 emit_event + 2-3 次 set_stage_state |
| **When** | 13 个 stage × ~8 次 python3 fork = ~104 次进程创建。开销约 0.5s/次 = 总计 ~52s 浪费 |
| **Where** | events.sh:32-44(emit_event), 103-123(set_stage_state), 137-168(update_cost) |
| **How改** | (1) 轻量事件用 Bash 原生字符串拼接（不含特殊字符时） (2) 重度操作批量化（Python daemon 或 CLI 子命令） |

**优化动作：**
1. 简单事件用 printf 直接生成 JSON（避免 fork）：
   ```bash
   printf '{"timestamp":"%s","event_type":"%s","stage_id":"%s"}\n' "$(date -u ...)" "$type" "$id"
   ```
2. state.json 更新改用 `ai-sdlc update-state` CLI 子命令（单次 Python 启动处理批量更新）
3. 保留 Python 调用仅用于需要复杂转义的场景

**投入**: 低 | **回报**: 中（pipeline 总耗时减少 ~1 分钟）

---

### 问题 9：Prompt 模板硬编码在 DAG 中

| 维度 | 分析 |
|------|------|
| **What** | 每个 stage 的 prompt_template 写死在 pipeline-dag.json 中（单行字符串，无法换行/格式化） |
| **Why** | 初始设计将 DAG 定义和 prompt 放在一起，方便管理 |
| **Who** | pipeline-dag.json 的每个 stage.agents[0].prompt_template |
| **When** | 想优化某个 stage 的 prompt 时必须编辑 707 行的 JSON 文件 |
| **Where** | 如 S3 的 prompt 是一行 300+ 字符的字符串，不可读 |
| **How改** | prompt 模板独立为 `prompts/{stage_id}.md` 文件，DAG 中只引用路径 |

**优化动作：**
1. 创建 `prompts/` 目录，每个 stage 一个 `.md` 文件
2. DAG 中 `prompt_template` 改为 `prompt_file: "prompts/S3-backend.md"`
3. build_prompt 函数加载外部文件
4. prompt 文件支持 Jinja2 风格变量：`{{ feature_description }}`, `{{ S1_output }}`

**投入**: 低 | **回报**: 高（prompt 可独立版本化、A/B测试、按项目覆盖）

---

### 问题 10：缺少 Pipeline 运行报告

| 维度 | 分析 |
|------|------|
| **What** | Pipeline 完成后只打印简要 tokens/cost，无结构化报告 |
| **Why** | events.jsonl 和 state.json 有完整数据，但没有消费端 |
| **Who** | pipeline-executor.sh:994-1022（仅打印 cost 和文件路径） |
| **When** | Phase 2 的复盘需要手动读 events.jsonl 分析——应该自动生成 |
| **Where** | 缺少 `pipeline-report.sh` 或 `ai-sdlc report` 命令 |
| **How改** | Pipeline 完成后自动生成 `report.md`：耗时、成本、每阶段状态、AI Review 分数、问题列表 |

**优化动作：**
1. 创建 `src/ai_sdlc_claudecode/report.py` — 从 state.json + events.jsonl 生成报告
2. 报告格式：Markdown（可在 GitHub 渲染）
3. 包含：甘特图（文本版）、成本分解、质量分数趋势、失败模式统计
4. Pipeline 结束时自动生成 `${PIPELINE_ROOT}/${feature_id}/report.md`

**投入**: 中 | **回报**: 高（自动化复盘，减少人工分析时间）

---

## 金字塔结构

```
                      ┌───────────────────────────────┐
                      │         核心结论               │
                      │  Bash做调度壳,Python做决策核    │
                      │  渐进迁移,不推倒重写            │
                      └───────────────┬───────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
   ┌──────▼──────┐            ┌──────▼──────┐            ┌──────▼──────┐
   │  架构治理    │            │  质量提升    │            │  可观测性    │
   │  (问题1,8,9) │            │  (问题3,4,5  │            │  (问题2,10)  │
   │              │            │   6,7)       │            │              │
   └──────┬──────┘            └──────┬──────┘            └──────┬──────┘
          │                          │                          │
   ┌──────▼──────┐            ┌──────▼──────┐            ┌──────▼──────┐
   │ • 1026行Bash │            │ • JSON提取   │            │ • Token不准  │
   │   内嵌15段Py │            │   regex脆弱  │            │   chars/4    │
   │ • 104次fork  │            │ • ErrorEngine│            │ • 无运行报告 │
   │ • Prompt硬编 │            │   默认关闭   │            │ • 无甘特图   │
   │   码在JSON中 │            │ • Summarizer │            │ • 复盘靠人工 │
   │              │            │   静默fallback│            │              │
   │              │            │ • 并行无重试  │            │              │
   │              │            │ • Gate不编译  │            │              │
   └─────────────┘            └─────────────┘            └─────────────┘
```

---

## 优先级排序

| 优先级 | # | 优化项 | 投入 | 回报 | 依赖 |
|--------|---|--------|------|------|------|
| **P0** | 4 | ErrorEngine 默认启用 | 低 | 高 | 无 |
| **P0** | 3 | JSON 提取统一 + json-repair | 低 | 高 | 无 |
| **P0** | 9 | Prompt 模板外部化 | 低 | 高 | 无 |
| **P1** | 1 | CLI 子命令（Bash→Python桥） | 中 | 高 | 无 |
| **P1** | 5 | StageSummarizer 完整集成 | 中 | 高 | #1 |
| **P1** | 7 | 混合 Gate（auto+ai-review） | 中 | 高 | 无 |
| **P2** | 6 | 并行执行器重试机制 | 中 | 高 | 无 |
| **P2** | 10 | Pipeline 运行报告自动生成 | 中 | 高 | 无 |
| **P2** | 2 | Token 计数优化 | 低 | 中 | #1 |
| **P3** | 8 | events.sh fork 优化 | 低 | 中 | #1 |

---

## 实施路线图

```
Week 1 (P0 - 快速胜利)             Week 2 (P1 - 架构桥接)
──────────────────────            ──────────────────────
#4 ErrorEngine默认启用              #1 cli.py子命令暴露
   移除EVOLVE_MODE门控                build-prompt
   自动capture_realtime               update-state
                                      update-cost
#3 JSON提取统一                       extract-json
   创建extract.py
   json-repair策略               #5 StageSummarizer集成
   替换两处重复regex                  summary.json自动生成
                                     fallback时记录事件
#9 Prompt模板外部化
   创建prompts/目录               #7 混合Gate
   DAG引用prompt_file                auto+ai-review组合
   支持Jinja2变量                    tech_stack_commands真实执行


Week 3 (P2 - 完善)                Week 4 (P3 - 打磨)
──────────────────────            ──────────────────────
#6 并行重试机制                    #8 events.sh fork优化
   单stage重试,不重启组               printf原生JSON
   max_retries复用                    批量state更新

#10 Pipeline运行报告              全面回归测试
    report.py                     ai-media-platform重跑验证
    自动生成report.md
    甘特图+成本分解

#2 Token计数优化
   中英文混合比例
   claude CLI usage解析
```

---

## 验证方式

| # | 优化项 | 验证方法 | 成功指标 |
|---|--------|---------|---------|
| 1 | CLI子命令 | `ai-sdlc build-prompt S3 test "desc"` 输出合法 prompt | 输出与Bash内联Python一致 |
| 2 | Token计数 | 对比估算值与 claude CLI 实际 usage | 误差 < 20% |
| 3 | JSON提取 | 构造 10 种 claude 输出格式（纯JSON、markdown包裹、混合文本） | 提取成功率 > 95% |
| 4 | ErrorEngine | 跑 `--mock-review` pipeline，故意注入超时 | evolve/records/ 有记录、下次retry有augment |
| 5 | Summarizer | 对比 fallback 路径和 strategy 路径的上下文大小 | strategy 路径字符数 < fallback 的 50% |
| 6 | 并行重试 | `--dry-run` 模拟并行组中单stage失败 | 仅失败stage重试，成功stage保持 |
| 7 | 混合Gate | S3 输出代码 → auto gate 运行编译 → ai-review | 编译错误在 S3 就被拦截 |
| 8 | Fork优化 | `time` 对比优化前后 pipeline 总耗时 | 减少 > 30s |
| 9 | Prompt外部化 | 修改 `prompts/S3-backend.md` 后 build_prompt 输出变化 | 模板热更新生效 |
| 10 | 运行报告 | pipeline 完成后检查 `report.md` 存在且包含所有章节 | 6 个章节齐全 |

---

## 关键文件索引

| 文件 | 修改内容 |
|------|---------|
| `pipeline-executor.sh` | #1 内联Python→CLI调用, #4 ErrorEngine默认启用, #7 混合Gate |
| `orchestrate-parallel.sh` | #6 并行重试机制 |
| `src/ai_sdlc_claudecode/cli.py` | #1 新增子命令 |
| `src/ai_sdlc_claudecode/extract.py` | #3 新建，JSON提取+修复 |
| `src/ai_sdlc_claudecode/report.py` | #10 新建，运行报告生成 |
| `src/ai_sdlc_claudecode/summarizer.py` | #5 summary.json自动生成 |
| `lib/events.sh` | #8 printf原生JSON替代python3 fork |
| `pipeline-dag.json` | #9 prompt_template→prompt_file, #7 gate type扩展 |
| `prompts/*.md` | #9 新建，独立prompt模板文件 |

---

## 与 Superpowers 优化方案的关系

```
ai-sdlc (Layer 4)                    Superpowers (Layer 3)
─────────────────                    ─────────────────────
#9 Prompt外部化                  ←→  Agent Prompt进化（P0评分回写）
   prompts/*.md 版本化                prompt版本+效果评分可共享数据

#7 混合Gate                      ←→  Hook自修复（P1）
   auto+ai-review                     PostToolUse→PreToolUse左移
                                      同一个"质量左移"理念

#10 运行报告                     ←→  Commander度量（P1拆分）
   report.md自动生成                  Agent能力画像可从report提取
```

两个优化方案互补：
- **ai-sdlc 提供数据**（运行报告、AI Review 分数、错误记录）
- **Superpowers 消费数据**（Prompt 进化、Agent 能力画像、智能调度）

**先做 ai-sdlc P0（数据源），再做 Superpowers P0（数据消费），形成闭环。**
