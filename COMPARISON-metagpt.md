# MetaGPT vs Claude Code Pipeline: 通信协议对比

## MetaGPT 的通信模型

```python
# MetaGPT: Python async/await + 内存消息队列
async def run():
    await mike.analyze(requirement)     # Mike 分析需求
    await mike.dispatch_to_team()       # Mike 分配任务
    await alex.execute()                # Alex 自动执行
    return output

# MetaGPT 消息协议
Mike → Alice: "创建 PRD"
Alice → Mike: "PRD 完成，路径: /path/prd.md"
Mike → Bob: "设计架构，参考 PRD: /path/prd.md"
Bob → Mike: "架构完成，路径: /path/arch.md"
Mike → Alex: "开发代码，参考: PRD + 架构"
Alex → Mike: "代码完成，路径: /path/code"
```

## 我们的通信模型

```bash
# Claude Pipeline: Bash DAG executor + 文件消息日志 + Schema 验证
./pipeline-executor.sh health-check "Add /health endpoint"

# 等效消息协议 (communication.jsonl)
Commander → Product Manager: "Execute requirements: Add /health endpoint"
Product Manager → Commander: "requirements complete" [artifact: S1-requirements/output.json]
Commander → Software Architect: "Routing output from requirements: use as input" [artifact: S1-requirements/output.json]
Commander → Software Architect: "Execute architecture: Add /health endpoint"
Software Architect → Commander: "architecture complete" [artifact: S2-architecture/output.json]
Commander → GateCheck: "S2 ai-review gate: PASSED"
Commander → Senior Developer: "Execute backend: Add /health endpoint"
Senior Developer → Commander: "backend complete" [artifact: S3-backend/output.json]
Commander → GateCheck: "S3 auto gate: PASSED"
```

## 逐项对比

| 维度 | MetaGPT | Claude Pipeline | 评估 |
|------|---------|-----------------|------|
| **通信方式** | 内存消息队列 (ActionOutput) | 文件消息日志 (communication.jsonl) | ≈ 等效，我们可审计 |
| **消息类型** | ActionOutput(content, instruct_content) | request/response/handoff/error/gate/parallel | ✅ 我们更细粒度 |
| **Artifact 传递** | 文件路径引用 | 文件路径引用 + JSON Schema 验证 | ✅ 我们有合约验证 |
| **中央调度** | Mike (ProductManager) 角色 | Commander (pipeline-executor.sh) | ≈ 等效 |
| **执行模型** | Python asyncio 协程 | Bash 进程 + background PID | ≈ 等效 |
| **并行执行** | asyncio.gather() | git worktree + 后台进程 + merge gate | ✅ 我们有隔离 |
| **状态管理** | 内存 (SharedEnvironment) | 文件 (state.json per feature) | ✅ 我们可持久化 |
| **错误处理** | try/except + retry | 重试预算 + 死信 + 状态机 | ✅ 我们更健壮 |
| **成本控制** | 无 | Token 追踪 + USD 累计 + 硬上限 | ✅ 我们独有 |
| **可观测性** | 日志输出 | JSONL 事件 + 状态面板 + 通信日志 | ✅ 我们更完整 |
| **门控机制** | 无（或手动检查） | auto/ai-review/human-required 三级 | ✅ 我们独有 |
| **Schema 验证** | Pydantic model (Python) | JSON Schema (语言无关) | ≈ 等效 |
| **启动复杂度** | `pip install metagpt` + Python | `bash pipeline-executor.sh` | ✅ 我们零依赖 |
| **Agent 选择** | 固定 5 角色 | 160+ Agent 类型可选 | ✅ 我们更灵活 |

## MetaGPT 的优势（我们学习的）

| MetaGPT 优势 | 我们的应对 |
|-------------|-----------|
| **真正的 async/await** — 语言级并发 | git worktree 进程级并行（更重但更隔离） |
| **类型安全** — Pydantic 强类型 | JSON Schema 验证（跨语言但不如 Pydantic 严格） |
| **内存通信** — 零 I/O 延迟 | 文件通信（有 I/O 但可审计、可恢复） |
| **统一运行时** — 单进程 Python | 多进程 Bash（更复杂但更健壮） |

## 我们的优势（MetaGPT 没有的）

1. **成本守卫**：Pipeline 启动前估算成本，运行时追踪，超限自动停止
2. **门控分级**：auto（编译通过？）/ ai-review（架构覆盖 PRD？）/ human-required（部署审批）
3. **死信机制**：Agent 失败 3 次后不无限重试，写入死信等人工介入
4. **通信日志**：MetaGPT 的消息在内存中，进程退出即丢失；我们的 communication.jsonl 永久保留
5. **状态恢复**：`--start-from S3` 从中间阶段恢复，MetaGPT 只能从头开始
6. **并行隔离**：git worktree 确保并行 Agent 不互相干扰，MetaGPT 的 asyncio.gather 共享内存可能冲突
7. **Agent 生态**：160+ 专家角色 vs MetaGPT 固定 5 角色

## 结论

**MetaGPT 的核心创新是"结构化通信协议"——我们已完整实现。**

MetaGPT 用 Python 内存消息队列，我们用文件消息日志；语义相同，我们多了持久化和审计。

MetaGPT 缺少的（成本控制、门控、死信、状态恢复、并行隔离），我们都有。

**本质差异**：MetaGPT 是一个 Python 框架（需要 Python 运行时），我们是 Bash 脚本 + Claude CLI（零额外依赖）。对于已经使用 Claude Code 的团队，我们的方案是更自然的选择。
