# ai-sdlc Pipeline 正确使用指南（费曼讲解版）

> 用最简单的话讲清楚，让你五分钟内完全理解。

---

## 一句话定义

**ai-sdlc pipeline = 一条自动化流水线，把"一句话需求"变成"可部署的代码"，中间经过 13 个质检关卡。**

就像工厂流水线：原料(需求) → 设计 → 加工(编码) → 质检(测试) → 包装(部署) → 出厂(发布)。

---

## 费曼五分钟：三个核心概念

### 概念 1：Pipeline 是什么？

想象你开了一家蛋糕店。你不会让一个人从买面粉到送货全干，而是：

```
面包师傅(S1需求) → 设计师(S2架构) → 裱花师(S3编码) → 质检员(S4测试) → 快递员(S6部署)
```

ai-sdlc 就是这条流水线。每个工位是一个 AI Agent（专家角色），每个工位之间有质检门（Gate）。

**你只需要做一件事：告诉流水线"我要一个什么蛋糕"。**

### 概念 2：你（人类）在哪里介入？

```
                    你在这里 ↓
                        │
    "我要一个儿童英语学习平台"
                        │
                        ▼
              ┌─ pipeline-executor.sh ─┐
              │                        │
              │  S1:  产品经理写 PRD    │  ← AI 自动 (ai-review gate)
              │  S2:  架构师画蓝图      │  ← AI 自动 (ai-review gate)
              │  S3:  后端程序员写代码   │  ← AI 自动 (ai-review gate)
              │  S3b: 前端程序员写UI    │  ← AI 自动 (S3/S3b 并行)
              │  S4:  单元测试          │  ← AI 自动 ┐
              │  S4b: 集成测试          │  ← AI 自动 ├ S4/S4b/S4c 并行
              │  S4c: E2E 测试          │  ← AI 自动 ┘
              │  S5:  代码审查+安全扫描  │  ← AI 自动
              │  S6:  部署准备          │  ← 你审批 ⬅ human-required gate
              │  S7:  监控告警设计       │  ← AI 自动 ┐
              │  S8:  文档生成          │  ← AI 自动 ├ S7/S8/S9 并行
              │  S9:  性能测试          │  ← AI 自动 ┘
              │  S10: 发布上线          │  ← 你审批 ⬅ human-required gate
              └────────────────────────┘
                        │
                        ▼
              完成！产出在 docs/pipeline/{feature_id}/ 里
```

**关键：只有 S6(部署) 和 S10(发布) 需要你手动审批，其余全自动。**

### 概念 3：Plan 和 Brainstorm 在哪里？

**ai-sdlc 的 "plan" = S1 + S2 阶段（需求 + 架构），不是 Claude Code 的 Plan Mode。**

| 你说的 | 实际对应 | 怎么触发 |
|--------|---------|---------|
| "帮我规划一下" | S1 Requirements + S2 Architecture | `--stages S1,S2` |
| "帮我头脑风暴" | ai-sdlc 没有独立的 brainstorm | 用 S1 的 PRD 生成代替，或外部工具产出后 `--spec-file` 导入 |
| Claude Code `/plan` | Claude Code 内置 Plan Mode（只读模式） | 按 Tab 切换 |
| CLAUDE.md 的 PLAN 模式 | 执行协议 v4 的 planner agent | 输入包含"规划/计划/plan" |

**三者是完全不同的东西！**

---

## 正确使用姿势（操作手册）

### 姿势 1：只想规划，不想写代码

```bash
cd /Applications/soft/CodeSpace/ai-sdlc-claudecode

# 只跑 S1(PRD) + S2(架构)，不写代码
bash pipeline-executor.sh kids-english \
  "面向6-12岁儿童的沉浸式英语学习Web平台，含间隔重复和游戏化机制" \
  --stages S1,S2

# 产出在这里：
# docs/pipeline/kids-english/S1-requirements/   ← PRD
# docs/pipeline/kids-english/S2-architecture/   ← 架构设计
```

### 姿势 2：先规划，确认后再继续

```bash
# 第一步：只跑规划
bash pipeline-executor.sh kids-english "..." --stages S1,S2

# 你看完 PRD 和架构，觉得 OK

# 第二步：从 S3 继续（自动读取 S1/S2 的输出）
bash pipeline-executor.sh kids-english "..." --start-from S3
```

### 姿势 3：试跑看看（不真执行）

```bash
# dry-run：只展示执行计划，不调用任何 AI
bash pipeline-executor.sh kids-english "..." --dry-run
```

### 姿势 4：用 mock 模式省钱测试

```bash
# mock-review：AI Review 用假分数，不调用 Claude API 做 gate 检查
bash pipeline-executor.sh kids-english "..." --mock-review
```

### 姿势 5：外部文档直接喂入

```bash
# 你已经有 PRD 了，跳过 S1
bash pipeline-executor.sh kids-english "..." --spec-file my-prd.json

# 你已经有架构设计了，跳过 S2
bash pipeline-executor.sh kids-english "..." --plan-file my-arch.json

# 两个都有，直接从编码开始
bash pipeline-executor.sh kids-english "..." \
  --spec-file my-prd.json --plan-file my-arch.json --start-from S3
```

### 姿势 6：跑到一半暂停 / 恢复

```bash
# 跑完当前阶段后暂停
bash pipeline-executor.sh kids-english "..." --pause

# 从上次通过的阶段恢复（读取 state.json）
bash pipeline-executor.sh kids-english "..." --resume
```

### 姿势 7：跳过不需要的阶段

```bash
# 纯后端项目，跳过前端和 E2E
bash pipeline-executor.sh kids-english "..." --skip-stage S3b,S4c
```

---

## 完整 CLI 参数速查

| 参数 | 说明 | 示例 |
|------|------|------|
| `--dry-run` | 只展示执行计划，不调用 AI | `--dry-run` |
| `--stages S1,S2` | 只跑指定阶段 | `--stages S1,S2` |
| `--start-from S3` | 从指定阶段开始（跳过之前的） | `--start-from S3` |
| `--resume` | 自动从上次通过的阶段恢复 | `--resume` |
| `--pause` | 当前阶段完成后暂停 | `--pause` |
| `--mock-review` | Gate 检查用假分数（省钱） | `--mock-review` |
| `--spec-file <F>` | 外部 PRD 文件作为 S1 输出 | `--spec-file prd.json` |
| `--plan-file <F>` | 外部架构文件作为 S2 输出 | `--plan-file arch.json` |
| `--skip-stage S3b,S4c` | 跳过指定阶段 | `--skip-stage S3b` |
| `--cost-limit <N>` | 覆盖成本上限（默认 $500） | `--cost-limit 100` |
| `--tech-stack <S>` | 覆盖技术栈 | `--tech-stack python` |
| `--force-restart` | 强制重新开始（覆盖 state.json） | `--force-restart` |

---

## 13 阶段全景图

```
S1 需求分析 ──→ S2 架构设计 ──┬──→ S3  后端开发 ──┬──→ S4  单元测试  ──┐
           (sequential)       │                   │     S4b 集成测试   ├──→ S5 代码审查
                              └──→ S3b 前端开发 ──┘     S4c E2E测试   ┘     │
                                   (parallel)          (parallel)           │
                                                                            ▼
                              ┌── S7 监控设计 ──┐                    S6 部署准备
                              ├── S8 文档生成  ──┼──→ S10 发布上线     (human gate)
                              └── S9 性能测试 ──┘   (human gate)
                                  (parallel)
```

**Gate 类型**：
- `ai-review`：AI 自动评分，达标即通过
- `human-required`：必须人工审批（S6、S10）

**失败处理**：每个阶段最多重试 3 次 → 重试用尽进入 dead-letter → 等待人工介入

---

## 常见误解对照表

| 误解 | 真相 |
|------|------|
| "ai-sdlc 有 brainstorm 功能" | 没有独立的 brainstorm，S1 阶段的 PRD 生成最接近；或用外部工具后 `--spec-file` 导入 |
| "Claude Code Plan Mode = ai-sdlc 的 plan" | 完全不同。前者是 Claude Code 内置只读模式，后者是 pipeline 的 S1+S2 |
| "pipeline 会直接改我的代码" | 不会。产出全在 `docs/pipeline/{feature_id}/` 目录下，不碰你的 src/ |
| "跑一次要很贵" | `--mock-review` + `--stages S1` 只跑一个阶段，成本很低 |
| "需要单独激活 plan skill" | 不需要。S1/S2 就是 plan，直接 `--stages S1,S2` 即可 |
| "S3 和 S3b 是串行的" | 不是。后端(S3)和前端(S3b)并行执行 |
| "测试只跑一种" | S4/S4b/S4c 三种测试并行跑：单元/集成/E2E |
| "state.json 没了就要重来" | `--force-restart` 可以重新开始；也可以 `--start-from` 指定阶段 |

---

## 验证你理解了

如果你能回答以下 3 个问题，说明你完全理解了：

1. **我想让 AI 帮我分析需求、设计架构，但不写代码，该怎么做？**
   → `bash pipeline-executor.sh <id> "<desc>" --stages S1,S2`

2. **pipeline 跑完 S1 后我不满意 PRD，怎么办？**
   → 修改描述重新跑 S1（加 `--force-restart`），或用 `--spec-file` 喂你自己写的 PRD

3. **Claude Code 的 Plan Mode 和 ai-sdlc 的 S1/S2 有什么区别？**
   → Plan Mode 是当前会话的只读规划模式；S1/S2 是 pipeline 用 headless Claude 自动生成 PRD+架构文档，产出持久化到 `docs/pipeline/` 目录

---

## 成本参考

| 场景 | 阶段 | 预估 Token | 大约成本 |
|------|------|-----------|---------|
| 只规划 | S1+S2 | ~70K | ~$1-2 |
| 全流程（mock gate） | S1-S10 | ~600K | ~$5-10 |
| 全流程（real gate） | S1-S10 | ~700K | ~$8-15 |

成本硬限制默认 $500（可用 `--cost-limit` 覆盖）。

---

## 技术栈支持

pipeline-dag.json 预配置了 4 种技术栈的编译/测试/覆盖率/lint 命令：

| 技术栈 | 编译 | 测试 | 切换方式 |
|--------|------|------|---------|
| `node-typescript`（默认） | `npm run build` | `npm test` | 默认 |
| `java-maven` | `mvn clean compile test-compile -q` | `mvn clean test` | `--tech-stack java-maven` |
| `python` | `python -m py_compile` | `pytest` | `--tech-stack python` |
| `golang` | `go build ./...` | `go test ./...` | `--tech-stack golang` |
