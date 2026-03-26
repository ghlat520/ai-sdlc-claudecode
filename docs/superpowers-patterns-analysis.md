# Superpowers 设计模式分析 — 提炼可借鉴的规范

> 基于 obra/superpowers v5.0.4 源码分析，2026-03-20
> 目标：提炼 Superpowers 的 Agent/Skill 规范设计模式，指导 ai-sdlc-claudecode 优化

---

## 核心发现

**Superpowers 不是 Agent 军团，而是 Skill 工作流。**

| 维度 | Superpowers (obra) | 我们当前 (ECC + ai-sdlc) |
|------|-------------------|------------------------|
| 架构哲学 | **12 个 Skill + 1 个 Agent** | 182 个 Agent + 少量 Skill |
| 调度方式 | Skill 自动激活（context-triggered） | Commander 关键词匹配 |
| Agent 定位 | 仅 code-reviewer 是 Agent | 所有角色都是 Agent |
| 质量保障 | 两阶段审查（spec compliance → code quality） | 单阶段 AI Review |
| 工作流 | 严格线性：brainstorm → plan → worktree → implement → finish | DAG 编排 13 阶段 |
| Prompt 管理 | Skill 文件自带触发条件（description = "Use when..."） | Agent 文件无激活条件 |
| 测试理念 | **Skill 本身也用 TDD 测试** | 无 Skill/Prompt 测试机制 |

---

## 10 大可借鉴设计模式

### 模式 1：Skill 自动激活（Context-Triggered Skills）

**Superpowers 做法：**
```yaml
---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
---
```
- `description` 字段定义 **何时触发**，不是描述功能
- Agent 遇到匹配场景时自动加载对应 Skill
- 关键洞察：**description = "Use when..." 不是 "This skill does..."**

**我们可以借鉴：**
- ai-sdlc 每个 Stage 的 prompt 增加触发条件前缀
- 明确每个 Stage 的 **输入信号** 和 **退出条件**

---

### 模式 2：两阶段审查（Spec Compliance + Code Quality）

**Superpowers 做法：**
```
实现完成
  → Spec Reviewer（对照需求逐行验证，不信任 Agent 报告）
  → Code Quality Reviewer（代码质量，仅在 Spec 通过后）
```
- Spec Reviewer 核心原则：**"Do NOT trust the report"**
- 分两个独立 Subagent，分别用不同 prompt 模板
- 顺序不可颠倒：先验"做对了"，再验"做好了"

**我们可以借鉴：**
- ai-sdlc 的 AI Review Gate 拆为两步：
  1. **Schema Gate**：产出是否符合该阶段的 Schema 定义？（等价于 Spec Compliance）
  2. **Quality Gate**：产出质量如何？（等价于 Code Quality）
- 当前 ai-review-checker.sh 只做了一步混合审查

---

### 模式 3：Subagent 隔离 + 精确上下文注入

**Superpowers 做法：**
```
Controller（主 Agent）
  │
  ├─ 提取任务全文 + 上下文（一次性读取 plan）
  │
  └─ Dispatch Subagent：
     - 完整任务文本（不让 Subagent 自己读文件）
     - 场景上下文（该任务在整体中的位置）
     - 明确的输出格式（DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT）
     - 明确的升级路径（Subagent 可以说"我做不了"）
```

**关键洞察：**
- **不让 Subagent 读 plan 文件** — Controller 提取并喂入精确内容
- **Subagent 有权说"做不到"** — 4 种状态码，Controller 可以换更强模型重试
- **Fresh context per task** — 每个任务一个新 Subagent，避免上下文污染

**我们可以借鉴：**
- ai-sdlc 的 StageSummarizer 已在做上下文精简，但可以更激进
- 增加 Stage 执行的 **状态码协议**（不只是 exit code 0/1）
- 支持 Stage 失败后 **升级模型重试**（当前只是相同配置重试）

---

### 模式 4：反合理化防护（Anti-Rationalization Tables）

**Superpowers 做法：**
```markdown
| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "TDD is dogmatic" | TDD IS pragmatic. |
```
- 每个 Skill 都有 **Red Flags** 列表
- **"Violating the letter of the rules is violating the spirit of the rules."**
- 明确列出所有可能的借口和正确做法

**我们可以借鉴：**
- ai-sdlc 的 Stage prompts 加入 Anti-Rationalization 表
- 特别是 S3 代码生成阶段，防止 Agent "偷懒"生成 Mock 数据
- 防止 Agent 在超时压力下降低质量

---

### 模式 5：Hard Gate 机制

**Superpowers 做法：**
```markdown
<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project,
or take any implementation action until you have presented a design and
the user has approved it.
</HARD-GATE>
```
- 用 XML 标签标记不可跳过的门控
- 不是建议，是 **硬性阻断**

**我们可以借鉴：**
- ai-sdlc 的 Gate 定义中增加 `<HARD-GATE>` 标记
- 防止 auto gate 被绕过
- 在 prompt 中明确哪些检查是 **硬门控** vs **软建议**

---

### 模式 6：模型路由（Model Selection by Task Complexity）

**Superpowers 做法：**
```
机械实现任务（1-2 files, clear spec） → 廉价模型（haiku）
集成和判断任务（multi-file, integration） → 标准模型（sonnet）
架构/设计/审查任务 → 最强模型（opus）
```

**我们可以借鉴：**
- ai-sdlc pipeline-dag.json 已有 `preferred_model` 字段
- 但当前所有 Stage 用相同模型
- 可以根据 Stage 特性自动选择模型：
  - S1 需求分析 → opus（需要深度理解）
  - S3 代码生成 → sonnet（标准实现）
  - S4 测试生成 → haiku（机械任务）
  - S5 代码审查 → opus（需要判断力）

---

### 模式 7：Prompt 模板分离（Separate Prompt Templates）

**Superpowers 做法：**
```
skills/subagent-driven-development/
  ├── SKILL.md                        # 主流程定义
  ├── implementer-prompt.md           # 实现者 prompt 模板
  ├── spec-reviewer-prompt.md         # Spec 审查者模板
  └── code-quality-reviewer-prompt.md # 质量审查者模板
```
- 角色定义和 prompt 模板 **物理分离**
- 每个模板可以独立版本化和测试
- Controller 根据场景选择模板

**我们可以借鉴：**
- ai-sdlc 的 Stage prompts 从 pipeline-dag.json 中抽出
- 建立 `prompts/` 目录，每个 Stage 一个 .md 文件
- 这正是我们优化方案中的 **P0 #9：Prompt 外部化**
- Superpowers 验证了这个方向是对的

---

### 模式 8：验证即证据（Verification Before Completion）

**Superpowers 做法：**
```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE

Before claiming:
1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command
3. READ: Full output, check exit code
4. VERIFY: Does output confirm the claim?
5. ONLY THEN: Make the claim
```
- **"Claiming work is complete without verification is dishonesty, not efficiency."**
- 不接受"应该可以"、"看起来正确"

**我们可以借鉴：**
- ai-sdlc 的 Gate 检查增加 **证据要求**
- auto gate 必须有命令输出作为证据
- ai-review gate 必须有具体评分和问题列表
- 不接受 "structural fallback" 作为长期方案

---

### 模式 9：Skill 用 TDD 测试（Test Skills with Subagents）

**Superpowers 做法：**
```
RED:   不加载 Skill，让 Agent 执行任务 → 观察偏差行为
GREEN: 加载 Skill，让 Agent 执行同一任务 → 验证行为改善
REFACTOR: Agent 找到新借口 → 补充反合理化条目 → 重测
```
- **Skill 本身也是代码，需要测试**
- 用 Subagent 做 A/B 测试：有 Skill vs 无 Skill

**我们可以借鉴：**
- ai-sdlc 的 Stage prompt 修改后应做 A/B 验证
- 建立 prompt 效果对比机制（正是 Superpowers 优化方案 P0 的评分回写）
- 跑同一个需求两次，对比不同 prompt 版本的产出质量

---

### 模式 10：SessionStart 注入（Skill System Bootstrap）

**Superpowers 做法：**
```bash
# hooks/session-start
# 每次会话开始时注入 using-superpowers skill
session_context="<EXTREMELY_IMPORTANT>
You have superpowers.
Below is the full content of your 'superpowers:using-superpowers' skill...
</EXTREMELY_IMPORTANT>"
```
- 通过 SessionStart hook 注入核心指令
- 用 `<EXTREMELY_IMPORTANT>` 标签强调
- 只注入入口 skill，其他 skill 按需加载

**我们可以借鉴：**
- ai-sdlc 可以在 Stage 开始时注入 "Stage 执行规范" skill
- 用 Hook 机制确保每个 Stage 都遵循基本规范
- 不需要注入全部规范，只注入"如何找到和使用规范"

---

## 架构对比：Superpowers vs ai-sdlc

```
Superpowers 架构：
┌──────────────────────────────────────────────┐
│  SessionStart Hook → 注入 using-superpowers   │
├──────────────────────────────────────────────┤
│  brainstorming (Skill)                        │
│    └→ writing-plans (Skill)                   │
│         └→ subagent-driven-development (Skill)│
│              ├→ implementer (Subagent)         │
│              ├→ spec-reviewer (Subagent)       │
│              └→ code-quality-reviewer (Subagent)│
│         └→ finishing-branch (Skill)            │
├──────────────────────────────────────────────┤
│  TDD (Skill) — 贯穿所有实现环节               │
│  verification (Skill) — 贯穿所有完成声明       │
│  code-reviewer (Agent) — 唯一真正的 Agent      │
└──────────────────────────────────────────────┘

ai-sdlc 架构：
┌──────────────────────────────────────────────┐
│  pipeline-executor.sh → DAG 调度              │
├──────────────────────────────────────────────┤
│  S1 需求 → S2 架构 → S3 后端 → S3b 前端       │
│  → S4 测试 → S5 审查 → S6 部署                │
├──────────────────────────────────────────────┤
│  每个 Stage：                                 │
│    claude --print "prompt" → 产出文件          │
│    → auto/ai-review/human Gate → 下一阶段     │
├──────────────────────────────────────────────┤
│  ErrorEngine (Python) — 错误分类和修复提示      │
│  StageSummarizer (Python) — 上下文精简         │
│  SharedMemory (Python) — 并行协调              │
└──────────────────────────────────────────────┘
```

---

## 关键差异和优化建议

### 1. Skill vs Agent 的本质区别

| Superpowers 理解 | 我们应该学的 |
|-----------------|------------|
| Skill = 可复用的方法论文档 | Stage prompt = 应该像 Skill 一样管理 |
| Agent = 有独立上下文的执行单元 | Stage 执行 = Agent invocation |
| Skill 自动激活，Agent 被 dispatch | Stage 由 DAG 触发，prompt 应自动选择 |

**行动**：ai-sdlc 的 Stage prompt 应借鉴 Skill 格式——frontmatter (name/description/trigger) + 结构化内容 + Anti-Rationalization + Red Flags

### 2. 两阶段审查 → ai-sdlc Gate 升级

当前 ai-sdlc 的 ai-review gate 是"一锅煮"，应拆为：
```
Stage 完成
  → Schema Compliance Check（产出格式是否正确？字段是否完整？）
  → Quality Review（内容质量如何？逻辑是否合理？）
```

### 3. 状态码协议

Superpowers 的 4 状态码（DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT）比 ai-sdlc 的 exit code 0/1 丰富得多。

建议 ai-sdlc 的 Stage 输出增加结构化状态：
```json
{
  "status": "DONE_WITH_CONCERNS",
  "output_file": "S3-backend/output.json",
  "concerns": ["前端 API 未对接", "测试覆盖率低于 80%"],
  "model_used": "sonnet",
  "tokens": 12345
}
```

### 4. Prompt 外部化 + 版本化

Superpowers 验证了 prompt 外部化的可行性。每个 Skill 是独立的 .md 文件，可以：
- 独立版本控制（git diff 可见）
- A/B 测试（同 Skill 不同版本）
- 按项目覆盖（项目级 > 全局级）

ai-sdlc 应将 pipeline-dag.json 中的 prompt 模板迁移到 `prompts/` 目录。

### 5. 模型路由优化

当前 ai-sdlc 所有 Stage 用同一模型。借鉴 Superpowers 的任务复杂度→模型匹配：

| Stage | 任务特性 | 推荐模型 |
|-------|---------|---------|
| S1 需求分析 | 深度理解、创意 | opus |
| S2 架构设计 | 系统思维、判断 | opus |
| S3 代码实现 | 标准编码 | sonnet |
| S3b 前端 | 标准编码 | sonnet |
| S4 测试 | 机械任务 | haiku → sonnet fallback |
| S5 审查 | 判断力、经验 | opus |
| S6 部署 | 模板化 | sonnet |

---

## 实施优先级（与现有优化方案合并）

| 优先级 | 借鉴项 | 对应现有方案 | 新增/已有 |
|--------|--------|------------|----------|
| **P0** | Prompt 外部化 + Skill 格式 | ai-sdlc P0 #9 | 加强 |
| **P0** | 两阶段 Gate（Schema + Quality） | ai-sdlc P1 #7 | 升级为 P0 |
| **P1** | 状态码协议（4 种状态） | 新增 | 新增 |
| **P1** | Anti-Rationalization 表 | 新增 | 新增 |
| **P1** | 模型路由 | 新增 | 新增 |
| **P2** | Prompt A/B 测试 | Superpowers P0 评分回写 | 已有 |
| **P2** | Hard Gate 标记 | 新增 | 新增 |
| **P3** | SessionStart 规范注入 | 新增 | 新增 |

---

## 一句话总结

**Superpowers 教会我们：少即是多。12 个精心设计的 Skill 比 182 个 Agent 更有效。
ai-sdlc 的优化方向不是增加更多 Agent，而是把每个 Stage 的 prompt 做成像 Superpowers Skill 一样精雕细琢——有触发条件、有反合理化防护、有两阶段审查、有证据要求。**
