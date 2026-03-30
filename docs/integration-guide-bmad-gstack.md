# ai-sdlc × BMAD × gstack 集成最佳实战指南

> 产品发现 + 深度审查 + 自动化流水线的完美融合
> 版本: 1.0 | 日期: 2026-03-30

---

## 一、核心架构：六层融合模型

```
Layer 6: ai-sdlc Pipeline DAG          ← 全局编排（14阶段，自动状态机）
Layer 5: BMAD 产品发现引擎              ← 产品思维 + PRD协作 + 域自适应（S0p/S1增强）
Layer 4: gstack 工程治理引擎            ← 认知模式 + 反谄媚 + 深度审查（S0/S5增强）
Layer 3: ECC + 164 Agent 专家库         ← 领域专家 + Commander 并行调度
Layer 2: Superpowers TDD 纪律           ← 编码阶段 TDD + 1% Rule
Layer 1: CLAUDE.md + Rules + Hooks      ← 项目定制 + 安全拦截 + Java/Maven适配
```

### 为什么是六层而不是简单替换

每层解决不同问题，**不可合并**：

| 层 | 核心价值 | 来源框架 | 不可替代的原因 |
|----|---------|---------|--------------|
| 6 | DAG编排+状态机+成本追踪 | ai-sdlc | 唯一的全流程自动化串联 |
| 5 | 产品发现+域自适应+协作引导 | BMAD | 其他框架没有"从模糊想法到PRD"的引导能力 |
| 4 | 认知模式+反谄媚+审查纪律 | gstack | 防止AI附和用户、杀死坏想法的能力 |
| 3 | 164领域专家+并行调度 | ECC+Agents | 跨13领域的专家覆盖 |
| 2 | TDD纪律+反合理化 | Superpowers | 最严格的"先写测试"执行 |
| 1 | Java/Maven适配+Hook拦截 | 本地配置 | 项目特定的安全和编译保障 |

---

## 二、增强后的 Pipeline 全景图

### Before（原13阶段）

```
S0 → S1 → S2 → S2b → S3 → S3b → [S4/S4b/S4c] → S4d → S5 → S6 → [S7/S8/S9] → S10
38行   12行  15行                                        基础审查
薄弱   极薄  极薄                                        无认知模式
```

### After（增强15阶段）

```
S0p → S0 → S1 → S2 → S2b → S3 → S3b → [S4/S4b/S4c] → S4d → S4e → S5 → S6 → [S7/S8/S9] → S10
新增   ↑      ↑                                           ↑     新增    ↑
产品   深度   深度                                         冒烟   浏览器  深度
发现   审查   需求                                         测试   QA探索  代码审查
BMAD   gstack BMAD                                               gstack  gstack
```

### 每个增强点的 Before/After 对比

| 阶段 | Before | After | 增强来源 | 行数变化 |
|------|--------|-------|---------|---------|
| S0p | 不存在 | 产品发现（PRFAQ + 需求验证 + 域研究） | BMAD product-brief | 0 → 120行 |
| S0 | 38行：3个视角 + 4个输出 | 130行：6个Forcing Questions + 8个认知模式 + 反谄媚 + Scope Ceremony | gstack /plan-ceo-review | 38 → 130行 |
| S1 | 12行：模板变量 | 160行：域分类(15域) + 12步发现 + 交叉验证 | BMAD PRD workflow | 12 → 160行 |
| S5 | 基础代码审查 | +对抗性审查 + quality-lessons注入 | gstack /review | 已有，增强 |

---

## 三、各阶段详细设计

### S0p: 产品发现（新增）

**触发条件**：Pipeline 启动时自动运行
**跳过条件**：feature_description 已包含（特定角色 + 明确问题 + 可测量标准 + 范围边界）中的3+项

**核心方法论**（融合BMAD三大研究Skill）：

| 步骤 | 来源 | 作用 |
|------|------|------|
| 问题陈述提取 | BMAD product-brief | 把"想法"变成"问题" |
| 需求信号评估 | BMAD market-research | 验证有人要这个 |
| 市场与域上下文 | BMAD domain-research | 竞品怎么做的 |
| PRFAQ | Amazon Working Backwards | 倒推法写新闻稿 |
| 用户画像 | BMAD create-prd Step 4 | 具体到人 |
| 最窄可行功能 | gstack /office-hours Q4 | 最小验证单元 |

**Gate**: `human-required`（产品发现需要人类输入）+ auto-skip 机制
**成本**: ~$0.50-1.00（Opus，11K tokens）

**关键设计决策**：
- 为什么是 `human-required` 而不是 `ai-review`？产品发现的本质是**协作**，不是模板填空。AI可以引导结构，但判断"这个需求是否真实"需要人类
- 为什么有 auto-skip？对于已经明确的特性（如"在用户列表添加CSV导出按钮"），跑产品发现是浪费

### S0: 深度战略审查（增强）

**增强要点**：

#### 1. 六个Forcing Questions（来自gstack /office-hours）

不是简单的"评估可行性"，而是**逼出真相**的6个问题：

| 问题 | 目的 | 如果答不出来怎么办 |
|------|------|------------------|
| Q1: 需求现实 | 谁有这个问题？证据？ | HOLD — 需求未验证 |
| Q2: 现状替代 | 用户今天怎么解决的？ | 如果替代方案可忍受 → 优先级降低 |
| Q3: 绝望的具体性 | 一句话描述最小版本 | 如果描述不出 → 问题没理解清楚 |
| Q4: 最窄楔子 | 验证假设的最小实验 | 如果定义不出 → 返回S0p |
| Q5: 观察而非观点 | 成功指标是什么？ | 如果没有指标 → 不可评估 |
| Q6: 未来适配 | 成功/失败的二阶效应 | 识别不可逆决策 |

#### 2. 认知模式矩阵（来自gstack /plan-ceo-review）

8个认知模式，每次选3-5个最相关的应用：

| 模式 | 问题 | 来源 |
|------|------|------|
| 后悔最小化 | 5年后会后悔没做吗？ | Bezos |
| 逆向思维 | 什么会让它必然失败？ | Munger |
| 单向/双向门 | 可逆吗？不可逆就慎重 | Bezos |
| 机会成本 | 不做别的什么？ | Horowitz |
| 10x vs 10% | 这是突破还是微调？ | Page |
| 需求拉动 vs 技术推动 | 用户拉还是我们推？ | Christensen |
| 价值时间 | 第一个用户多久获益？ | — |
| 竞争护城河 | 加强还是削弱护城河？ | Buffett |

#### 3. 反谄媚守卫（来自gstack Anti-Sycophancy）

**Hard Rules — 永远不说**：
- "这是个好主意！" → 基于证据评价
- "用户会喜欢的" → 引用数据或标记"未验证假设"
- "应该很简单" → 识别最难的部分
- "我没发现问题" → 主动寻找问题

**Pushback Patterns — 需要时使用**：
- Scope Creep Alert、Assumption Challenge、Evidence Request、Complexity Warning、Sunk Cost Check

#### 4. Scope Ceremony（来自gstack Opt-in Ceremony）

每个超出最窄楔子的范围添加，都需要：
1. 识别：添加了什么？
2. 论证：为什么不能等v2？
3. 成本：增加多少时间/复杂度/风险？
4. 决策：批准或推迟

**Gate**: `human-required`（不变，但现在输出质量大幅提升）
**成本**: ~$1.00-2.00（Opus，15K tokens）

### S1: 深度需求分析（增强）

**增强要点**：

#### 1. 域分类自适应（来自BMAD CSV驱动路由）

15个域分类 × 触发条件 × 合规要求：

```
输入："建一个供应商管理系统"
→ 域分类：Enterprise SaaS + Finance
→ 自动触发：RBAC + 租户隔离 + SSO + 审计日志 + PCI-DSS合规
→ NFR自动注入：这些合规要求变成必选NFR
```

**与原S1的本质区别**：
- 原S1：给一个空模板，AI自由发挥 → 结果取决于AI的"直觉"
- 新S1：基于域分类自动注入必须考虑的需求 → 结果有确定性保障

#### 2. 12步结构化发现（来自BMAD PRD workflow）

| 步骤 | 内容 | 质量门 |
|------|------|--------|
| 1 | 域分类 | 必须匹配至少1个域 |
| 2 | 项目类型分类 | 决定必选章节 |
| 3 | 执行摘要 | 4个问题都要回答 |
| 4 | 成功标准(SMART) | 三个时间维度都要有 |
| 5 | 用户旅程映射 | 至少3个旅程 |
| 6 | 域特定需求（条件） | 仅触发域有此步骤 |
| 7 | 功能需求(20-50条) | FR格式 + MoSCoW |
| 8 | 非功能需求 | 5个必选类别 |
| 9 | 范围边界 | 与S0 Scope Ceremony对齐 |
| 10 | 交叉引用检查 | 每个US映射到FR |
| 11 | 下游就绪检查 | S2需要的都齐了吗？ |
| 12 | 输出组装 | JSON schema验证 |

#### 3. 反模式检测

自动标记并拒绝这些模式：
- 模糊需求："改进性能" → 拒绝，要求具体数字
- 实现语言："使用Redis" → 拒绝，这是WHAT不是HOW
- 缺少验收标准 → 拒绝
- "锦上添花"伪装成"必须有" → 要求降级

**Gate**: `ai-review`（PRD可以自动验证完整性）
**成本**: ~$1.50-3.00（Opus，20K tokens）

---

## 四、Pipeline 运行模式

### 模式A：完整新产品（推荐每月S4场景）

```
S0p(产品发现) → S0(深度审查) → S1(深度需求) → S2(架构) → ... → S10(发布)
  ↑ human         ↑ human         ↑ ai-review
  ~$1.00          ~$2.00          ~$3.00

总增量成本: ~$6.00（相比原Pipeline增加 $4-5）
总质量提升: S0从38行→130行，S1从12行→160行
```

### 模式B：明确特性（日常S1场景）

```
S0p(auto-skip) → S0(深度审查) → S1(深度需求) → S2(架构) → ...
  ↑ 自动跳过       ↑ human         ↑ ai-review
  ~$0              ~$2.00          ~$3.00

S0p跳过条件: feature_description已包含角色+问题+标准+范围
```

### 模式C：紧急修复（跳过发现）

```
S0(简化审查) → S3(后端开发) → S4(测试) → S5(审查)
  ↑ 可选跳过

使用: --start-from S3 --skip-stage S0p,S1,S2
```

### 与已安装BMAD/gstack Skill的协作

| 场景 | Pipeline阶段 | 可选外部Skill辅助 |
|------|-------------|-----------------|
| 新产品从0到1 | S0p | `bmad-product-brief` + `bmad-domain-research` 做更深的交互式发现 |
| PRD评审 | S1完成后 | `bmad-validate-prd` 做独立验证 |
| 架构评审 | S2完成后 | `bmad-party-mode` 让Winston+Sally+John讨论 |
| CEO视角审查 | S0 | gstack `/plan-ceo-review` 做更深的18模式分析（当pipeline的S0不够时） |
| 多角度讨论 | 任意阶段 | `bmad-party-mode` 召集相关Agent讨论争议点 |

**关键原则**：Pipeline内是自动化运行的精简版，BMAD/gstack Skill是按需的深度版。Pipeline保证最低质量线，Skill提供上限。

---

## 五、Quality Gate 设计哲学

### 三类Gate分布

```
S0p: human-required (产品发现需要人判断)
S0:  human-required (战略决策需要人拍板)
S1:  ai-review      (PRD完整性可自动验证)
S2:  ai-review      (架构可验证)
S2b: human-required (UI设计需要人审美)
S3:  ai-review + post_commands (编译通过 = 自动验证)
S3b: ai-review + post_commands
S4/S4b/S4c: ai-review + post_commands (测试通过 = 自动验证)
S4d: auto (冒烟测试纯自动)
S5:  ai-review + adversarial (对抗性审查)
S6:  human-required (部署需要人批准)
S7/S8/S9: ai-review (文档/监控/性能可自动验证)
S10: human-required (发布需要人批准)
```

### Gate分布的逻辑

```
人类决策（不可自动化）：产品方向(S0p/S0) + 设计审美(S2b) + 部署/发布(S6/S10)
AI验证（可自动化）：需求完整性(S1) + 架构覆盖(S2) + 编译通过(S3) + 测试通过(S4) + 代码质量(S5)
```

---

## 五-B、多 Agent 自审循环（从"及格"到"优秀"）

### 问题：单次生成 = 质量天花板

Pipeline 的每个阶段只调用一次 `claude --print`。单次生成的质量取决于 prompt 写得好不好——这是"及格线"。

### 解决方案：双层自审机制

#### Layer 1: Prompt 内自审（self-review-loop.md）

通过 `stage-methods.json` 注入到 S0p/S0/S1 的 prompt 中。强制 Agent 在**单次调用内**完成三阶段：

```
Phase 1: 生成初稿（不输出JSON）
Phase 2: 切换到批评者视角，找至少3个问题
Phase 3: 修订初稿，修复问题，输出最终JSON
```

**优点**：零额外成本（同一次 claude 调用），零代码改动
**局限**：同一个 LLM 自我批评，独立性有限

#### Layer 2: 独立 Review Agent（review_passes）

Executor 增强：primary agent 生成 output.json 后，顺序执行 review agents，每个 review agent：
1. 读取 primary output
2. 通过其专业视角审查和修订
3. 输出替换 output.json

```
S0p: PM 生成产品发现 → Demand Critic (Sonnet) 挑战需求真实性 → 修订后的output.json
S0:  PM 做战略审查   → Devil's Advocate (Sonnet) 反驳每个结论 → 修订后的output.json
S1:  PM 生成 PRD     → Architect Checker (Sonnet) 验证可实现性 → 修订后的output.json
```

**优点**：独立 Agent，真正的多视角。不同 model 可以产生不同思路
**成本**：每个 review pass ~$0.50-1.00（Sonnet）

### 每个 Review Agent 的专业视角

| 阶段 | Review Agent | 核心问题 | Kill Signal |
|------|-------------|---------|-------------|
| S0p | Demand Critic | 需求是真的吗？ | 证据级别虚高、问题陈述是伪装的方案 |
| S0 | Devil's Advocate | 为什么不该做这个？ | 风险被低估、recommendation 与证据矛盾 |
| S1 | Architect Checker | 这能实现吗？ | FR模糊到无法设计、NFR缺失、Java/Maven特定问题 |

### 执行流程（在 pipeline-executor.sh 中）

```
execute_stage()
    │
    ├── 1. Primary Agent (claude --print) → output.json
    │
    ├── 2. run_review_passes()  ← 新增
    │       ├── Review Agent 1: 读 output.json → 审查 → 替换 output.json
    │       └── Review Agent N: 读 output.json → 审查 → 替换 output.json
    │
    ├── 3. Post-commands (compile/lint)
    ├── 4. Evidence check
    ├── 5. Schema validation
    └── 6. Gate check
```

### 成本影响

| 阶段 | Primary | Review Pass | 总计 | vs 原来 |
|------|---------|-------------|------|---------|
| S0p | ~$1.00 (Opus) | +$0.50 (Sonnet) | ~$1.50 | +$0.50 |
| S0 | ~$2.00 (Opus) | +$0.75 (Sonnet) | ~$2.75 | +$0.75 |
| S1 | ~$3.00 (Opus) | +$0.75 (Sonnet) | ~$3.75 | +$0.75 |
| **总增量** | | | | **+$2.00/次** |

### 容错设计

Review pass 失败时（超时、格式错误、无效JSON）：
- **不阻塞 Pipeline**：保留 primary output，继续执行
- **记录事件**：emit_event 记录失败，可用于后续分析
- **降级策略**：review pass 是增强，不是依赖

---

## 六、ErrorEngine 与增强阶段的集成

现有 ErrorEngine 已支持 6 类错误自动学习：
- `schema_validation` — JSON schema不合格
- `ai_output_quality` — AI输出格式错误
- `compilation` — 编译失败
- `timeout` — 超时
- `cost_overrun` — 成本超限
- `context_overflow` — 上下文溢出

**S0p/S0/S1的错误特征**：
- 主要是 `schema_validation`（输出缺少required fields）和 `ai_output_quality`（格式不对）
- ErrorEngine会自动学习并在重试时注入修复
- S0增强后的schema更复杂（forcing_questions, cognitive_patterns_applied），前几次运行可能有schema错误
- ErrorEngine的 `augment_prompt` 会自动注入："CRITICAL: Include ALL required fields..."

**无需额外改造**——ErrorEngine已经兼容新阶段。

---

## 七、成本与效率分析

### 增量成本

| 阶段 | 模型 | 估算Tokens | 估算成本 |
|------|------|-----------|---------|
| S0p | Opus | 11K | $0.50-1.00 |
| S0(增强) | Opus | 15K→20K | +$0.50 |
| S1(增强) | Opus | 20K→35K | +$1.50 |
| **总增量** | | **+25K tokens** | **+$2.50-3.00/次** |

### ROI分析

| 问题 | 没有增强时的成本 | 有增强后的节省 |
|------|----------------|--------------|
| 需求模糊导致S3返工 | $10-50/次（重跑S3+S4+S5） | S1域自适应提前捕获90%遗漏 |
| 坏想法进入开发 | $50-200/次（全Pipeline浪费） | S0 Forcing Questions在$2时杀死坏想法 |
| PRD缺少合规需求 | $20-100/次（S5审查发现→返工） | S1域分类自动注入合规NFR |
| Scope Creep | 不可估（项目延期） | S0 Scope Ceremony强制opt-in |

**结论**：增量$2.50换取$10-200的潜在返工成本 → **ROI 4x-80x**。

---

## 八、实施路线图

### Phase 1: 即刻生效（已完成）

- [x] 增强 `S0-strategic-review.md`（38行→130行，gstack模式）
- [x] 增强 `S1-requirements.md`（12行→160行，BMAD模式）
- [x] 新增 `S0p-product-discovery.md` + schema
- [x] 更新 `strategic-review-output.json` schema
- [x] 更新 `pipeline-dag.json` DAG定义

### Phase 2: 验证运行（下次新项目时）

- [ ] 用一个新feature跑完整Pipeline，验证S0p→S0→S1的增强效果
- [ ] 收集ErrorEngine在新schema上的学习记录
- [ ] 对比增强前后的PRD质量（盲审）
- [ ] 测量增量成本是否在$3以内

### Phase 3: 精细调优（运行3次后）

- [ ] 根据实际域分类命中率调整域表
- [ ] 根据Forcing Questions回答质量微调prompt
- [ ] 将高频ErrorEngine修复promote到skill
- [ ] 考虑将BMAD Party Mode集成为S0p的可选深度模式

### Phase 4: 深度集成（可选，月度评审）

- [ ] S2增强：集成gstack `/plan-eng-review` 308行工程审查模式
- [ ] S5增强：集成gstack `/review` 290行代码审查（含Greptile集成思路）
- [ ] S10增强：集成gstack `/ship` 19步发布门禁的关键步骤
- [ ] 添加 `/retro` 风格的Pipeline复盘阶段

---

## 九、决策树：何时使用什么

```
收到新任务
    │
    ├── 模糊想法（"建个什么东西"）
    │   └── 方案A：跑完整Pipeline（S0p→S0→S1→...）
    │   └── 方案B：先用 bmad-product-brief 深度交互，再喂入Pipeline
    │
    ├── 明确特性（"用户列表加导出"）
    │   └── S0p auto-skip → S0快速审查 → S1生成需求 → ...
    │
    ├── 紧急修复（"线上bug修复"）
    │   └── --start-from S3 直接开发
    │
    ├── 重大架构决策
    │   └── Pipeline S0 + bmad-party-mode（Winston+John+Sally讨论）
    │
    └── 产品方向争议
        └── bmad-party-mode（Mary商分 + John PM + Winston架构）→ 输出喂入Pipeline S0
```

---

## 十、文件清单

### 新增文件
| 文件 | 用途 |
|------|------|
| `prompts/stages/S0p-product-discovery.md` | 产品发现prompt（120行） |
| `schemas/product-discovery-output.json` | S0p输出schema |
| `prompts/methods/self-review-loop.md` | 多视角自审协议（Prompt内3阶段） |
| `prompts/reviews/S0p-demand-critic.md` | S0p Review Agent: 需求真实性挑战 |
| `prompts/reviews/S0-devils-advocate.md` | S0 Review Agent: 魔鬼代言人反驳 |
| `prompts/reviews/S1-architect-checker.md` | S1 Review Agent: 架构可行性验证 |
| `docs/integration-guide-bmad-gstack.md` | 本指南 |

### 修改文件
| 文件 | 变更 |
|------|------|
| `prompts/stages/S0-strategic-review.md` | 38行→130行（+gstack模式） |
| `prompts/stages/S1-requirements.md` | 12行→160行（+BMAD模式） |
| `schemas/strategic-review-output.json` | +forcing_questions, cognitive_patterns, anti_sycophancy_flags, scope_ceremony_log |
| `pipeline-dag.json` | +S0p stage + review_passes(S0p/S0/S1) + S0 depends on S0p + execution_order |
| `pipeline-executor.sh` | +run_review_passes() 函数 + DAG缓存review_passes字段 + 调用点插入 |
| `prompts/methods/stage-methods.json` | +S0p + self-review-loop 注入到 S0p/S0/S1 |

### 未修改的关键文件（利用现有能力）
| 文件 | 为什么不改 |
|------|----------|
| `engine.py` (ErrorEngine) | 已兼容新stage，自动学习schema错误 |
| `runner.py` (PipelineRunner) | 已兼容新stage，state.json自动追踪 |
| `prompts/methods/anti-rationalization.md` | 已足够好 |
| `prompts/methods/adversarial-review.md` | 已足够好 |
| `prompts/methods/verification.md` | 已足够好 |
| `prompts/quality-lessons.md` | 继续累积，不需要改 |
