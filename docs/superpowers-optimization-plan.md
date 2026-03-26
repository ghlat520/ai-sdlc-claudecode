# Superpowers 执行机制优化方案

> ai-sdlc Layer 3 稳定输出质量保障体系分析与优化路径
> 日期：2026-03-19

---

## 核心结论

**Superpowers 的三大执行机制当前处于"能用但脆弱"状态，需要从"被动检查"升级为"主动闭环"——让 Hooks 能自愈、Agent Prompts 能进化、Commander 能度量。**

一句话行动指南：**先建度量（P0），再拆结构（P1），最后上智能（P2/P3）。没有数据的优化都是猜。**

---

## 四层架构中的定位

```
┌─────────────────────────────────────────────────────────┐
│ Layer 4: 编排层 — ai-sdlc-claudecode（指挥官+参谋部）     │
├─────────────────────────────────────────────────────────┤
│ Layer 3: 方法论层 — Superpowers/ECC（教练）  ← 本文焦点   │
├─────────────────────────────────────────────────────────┤
│ Layer 2: 执行层 — Claude Code（士兵）                     │
├─────────────────────────────────────────────────────────┤
│ Layer 1: IDE层 — Roo Code（IDE助手，可选）                │
└─────────────────────────────────────────────────────────┘
```

**Layer 3 的职责**：定义 Agent "怎么做到稳定"。CLAUDE.md 定义"做什么"（规则可迁移），但执行机制（Hooks + Agent Prompts + Commander Orchestration）不可替代。

---

## 7 大现有规范机制

| # | 机制 | 核心文件 | 作用 | CLAUDE.md 可替代？ |
|---|------|---------|------|-------------------|
| 1 | 熵增控制 | architecture-guardian.md | 新增文件 ≤2, 新增代码 ≤修改×3, 不新增抽象层 | 能（静态规则） |
| 2 | 执行前检查清单 | CLAUDE.md CODE 模式 | 搜索→理解→评估→确认最小范围 | 能（已在其中） |
| 3 | TDD 强制流程 | tdd-guide agent | RED→GREEN→REFACTOR→80%+ coverage | 部分（规则可以，专业模板不可） |
| 4 | 代码审查自动触发 | code-reviewer agent | 写完代码后自动多维度检查 | 部分（触发规则可以，检查模板不可） |
| 5 | Workaround 警报 | CLAUDE.md | 检测 --force/catch忽略/重试等危险行为 | 能（已在其中） |
| 6 | PostToolUse Hooks | hooks.json | prettier/tsc/console.log/quality-gate 自动执行 | 不能（事件驱动，CLAUDE.md 无法触发） |
| 7 | Commander 三层架构 | commander.md | 战略方案→施工图纸→Agent自主宪章 | 不能（41KB 调度逻辑+160角色表） |

**结论**：约 40% 是静态规则（可迁移到 CLAUDE.md），60% 是执行机制（不可替代，需要优化）。

---

## 三大执行机制 5W1H 分析

### 一、Hooks：从"报警器"到"自动修复器"

| 维度 | 现状 | 问题 | 目标 |
|------|------|------|------|
| **What** | 6 个 PostToolUse hooks（prettier/tsc/console.log/quality-gate 等） | 只报警不修复，Agent 收到警告后可能忽略或重复犯错 | Hooks 检测到问题后自动修复或阻断 |
| **Why** | 设计初衷是"轻量提醒"，避免阻断开发流 | 提醒≠执行。Agent 无记忆，下次同样犯错 | 减少同类问题重复出现率 |
| **Who** | hooks.json 定义，shell 脚本执行 | 无人维护 hook 有效性，不知道哪些 hook 真正在工作 | 需要 hook 健康度监控 |
| **When** | PostToolUse 触发（编辑后） | PreToolUse hooks 太少（仅 5 个），大量问题在执行后才发现 | 关键操作前拦截（左移） |
| **Where** | `~/.claude/hooks/hooks.json` | 所有项目共用一套 hooks，无法按项目定制 | 支持项目级 hooks overlay |
| **How** | exit code 0=pass, 2=block | PostToolUse 的 exit code 不影响执行流，即使 hook 失败 Agent 也继续 | PostToolUse 失败时 Agent 必须回退修复 |

**优化动作：**

1. **将关键 PostToolUse 升级为 PreToolUse**（左移拦截）—— tsc 检查应在写入前而非写入后
2. **增加自修复 hook** —— console.log 检测后自动删除，而非只警告
3. **添加 hook 健康度追踪** —— 统计每个 hook 的触发次数、拦截次数、误报率

---

### 二、Agent Prompts：从"静态模板"到"可进化模板"

| 维度 | 现状 | 问题 | 目标 |
|------|------|------|------|
| **What** | 16 个 agent，每个有固定 prompt 模板（.md 文件） | 模板写死后不再更新，无法从运行结果中学习 | Prompt 模板根据历史成功/失败自动调整 |
| **Why** | Agent 质量 = prompt 质量。prompt 是核心资产 | ai-media-platform 运行中 S3 超时 3 次才过——prompt 未针对大项目优化 | 不同项目规模/类型使用不同 prompt 变体 |
| **Who** | 用户手动维护 agent/*.md | 维护成本高，16 个 agent × N 个场景 = 组合爆炸 | 自动化 prompt 版本管理 |
| **When** | Agent 创建时一次性写入 | 永不更新，即使跑了 100 次 pipeline 也不改进 | 每次 pipeline 运行后评估 prompt 有效性 |
| **Where** | `~/.claude/agents/*.md` | 全局共用，无项目级覆盖机制 | 支持项目级 agent prompt overlay |
| **How** | 纯文本模板，`{{变量}}` 替换 | 无版本控制、无 A/B 测试、无效果度量 | prompt 版本化 + 效果打分 + 自动优选 |

**优化动作：**

1. **Prompt 版本化** —— 每个 agent prompt 带版本号，修改有 diff 记录
2. **效果评分回写** —— pipeline 每阶段完成后，将 AI Review 分数关联到使用的 prompt 版本
3. **条件变体** —— 根据项目规模（LOC）、技术栈、历史超时率选择不同 prompt 变体

---

### 三、Commander：从"分发器"到"带度量的调度中枢"

| 维度 | 现状 | 问题 | 目标 |
|------|------|------|------|
| **What** | 160 角色速查表 + 4 种调度模式（单/串/并/会诊） | 调度决策靠规则匹配，无历史数据支撑 | 数据驱动的智能调度 |
| **Why** | Commander 是 Agent 军团的大脑 | 不知道哪个 Agent 在哪类任务上表现好/差 | 建立 Agent 能力画像 |
| **Who** | Commander 选 Agent，用户无感知 | 选错 Agent 时用户无法干预（除非手动指定） | 透明化选择理由，允许用户覆盖 |
| **When** | 任务开始时一次性选择 | 不支持运行中切换——如 code-reviewer 发现架构问题，无法自动升级到 architect | 支持动态升级/降级 |
| **Where** | `~/.claude/agents/commander.md`（41KB 单文件） | 文件过大，维护困难，角色表与调度逻辑耦合 | 拆分：角色注册表 + 调度引擎 + 度量面板 |
| **How** | 关键词匹配 + 人工规则 | 无法处理边界场景（如"优化数据库查询"——DBA? Backend? Performance?） | 多信号加权：关键词 + 历史成功率 + 任务复杂度 |

**优化动作：**

1. **拆分 commander.md** —— 角色注册表（roles.json）+ 调度规则（routing.md）+ 度量（metrics.jsonl）
2. **Agent 能力画像** —— 记录每个 Agent 在不同任务类型上的成功率、平均耗时、token 消耗
3. **调度透明化** —— Commander 选择 Agent 时输出理由：`[选择: code-reviewer | 原因: 代码变更+S5阶段 | 置信度: 92%]`

---

## 金字塔分析结构

```
                    ┌─────────────────────────────────┐
                    │          核心结论                 │
                    │  从"被动检查"→"主动闭环"           │
                    │  Hooks自愈 + Prompts进化           │
                    │  + Commander度量                   │
                    └──────────────┬──────────────────┘
                                  │
           ┌──────────────────────┼──────────────────────┐
           │                      │                      │
    ┌──────▼──────┐       ┌──────▼──────┐       ┌──────▼──────┐
    │   Hooks     │       │   Agent     │       │  Commander  │
    │  报警→自愈   │       │  Prompts    │       │  分发→调度   │
    │             │       │  静态→进化   │       │             │
    └──────┬──────┘       └──────┬──────┘       └──────┬──────┘
           │                     │                      │
    ┌──────▼──────┐       ┌──────▼──────┐       ┌──────▼──────┐
    │  事实依据    │       │  事实依据    │       │  事实依据    │
    │             │       │             │       │             │
    │ • PostTool  │       │ • S3超时3次  │       │ • 41KB单文件 │
    │   只报警     │       │   prompt未   │       │ • 关键词匹配 │
    │ • PreTool   │       │   适配大项目  │       │   无历史数据 │
    │   仅5个      │       │ • 16agent无  │       │ • 无Agent    │
    │ • 无修复能力 │       │   版本管理   │       │   能力画像   │
    │ • 无健康度   │       │ • 无A/B测试  │       │ • 不支持     │
    │   监控       │       │ • 无效果度量 │       │   动态切换   │
    └─────────────┘       └─────────────┘       └─────────────┘
```

---

## 优先级排序

| 优先级 | 优化项 | 投入 | 回报 | 理由 |
|--------|--------|------|------|------|
| **P0** | Agent Prompt 效果评分回写 | 低（pipeline 已有 AI Review 分数，只需关联） | 高（知道哪个 prompt 有效） | 数据是一切优化的前提 |
| **P1** | Commander 拆分（roles.json + routing.md） | 中（重构 41KB 文件） | 高（可维护性大幅提升） | 当前单文件已不可维护 |
| **P1** | Hook 自修复升级 | 低（改 shell 脚本） | 中（减少重复问题） | 投入小见效快 |
| **P2** | Prompt 条件变体 | 中（需设计变体选择逻辑） | 高（适配不同项目规模） | 依赖 P0 的数据 |
| **P2** | Agent 能力画像 | 中（需 metrics.jsonl 基础设施） | 高（智能调度基础） | 依赖 P0 的数据 |
| **P3** | PreToolUse 左移拦截 | 中（需评估对开发流影响） | 中（减少写后修） | 需要小心误拦截 |

---

## 实施路线图

```
Phase 1 (本周)          Phase 2 (下周)           Phase 3 (第3周)
─────────────          ─────────────           ──────────────
P0: 评分回写            P1: Commander拆分        P2: Prompt条件变体
  pipeline完成后          roles.json              按项目规模选变体
  写入 prompt_version     routing.md              A/B 测试框架
  + ai_review_score       metrics.jsonl
  到 events.jsonl
                        P1: Hook自修复           P2: Agent能力画像
                          console.log自动删        成功率/耗时/token
                          tsc左移到PreTool          可视化面板

                                                P3: PreToolUse扩充
                                                  评估误拦截率
                                                  渐进式上线
```

---

## 验证方式

| 优化项 | 验证方法 | 成功指标 |
|--------|---------|---------|
| 评分回写 | 跑 2 次 pipeline，检查 events.jsonl 中是否包含 prompt_version 字段 | 100% 阶段有评分关联 |
| Commander 拆分 | `wc -l` 检查拆分后文件，各 < 500 行；dry-run 验证调度结果不变 | 功能等价 + 文件可维护 |
| Hook 自修复 | 故意写入 console.log，检查 hook 是否自动删除 | 自动修复率 > 90% |
| Prompt 变体 | 同一需求用不同变体跑 pipeline，对比 AI Review 分数 | 变体 B 分数 > 变体 A |
| Agent 能力画像 | 跑 3+ 次 pipeline 后检查 metrics.jsonl 数据完整性 | 每个 Agent 有 ≥ 3 条记录 |

---

## 关键文件

| 文件 | 用途 |
|------|------|
| `~/.claude/hooks/hooks.json` | Hook 配置，修复自修复逻辑 |
| `~/.claude/agents/commander.md` | 待拆分为 roles.json + routing.md + metrics.jsonl |
| `~/.claude/agents/*.md` | 16 个 Agent prompt 模板，待版本化 |
| `ai-sdlc-claudecode/pipeline-executor.sh` | P0 评分回写的写入点 |
| `ai-sdlc-claudecode/ai-review-checker.sh` | AI Review 分数来源 |
| `ai-sdlc-claudecode/lib/events.sh` | events.jsonl 事件写入 |
