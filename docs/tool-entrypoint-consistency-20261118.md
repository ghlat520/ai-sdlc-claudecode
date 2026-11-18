# 固定坏候选的正式入口一致性验证

日期：2026-11-18，Asia/Singapore。目标是验证、修复和迭代 ai-sdlc-claudecode；本轮验证固定 R1 坏候选在执行、状态查询、列表和交付报告之间的结果一致性。

## 结论与范围

两个执行入口均正确返回 1，并持久化 `failed`。每次执行后的七个查询／报告入口均正常退出 0，内容一致显示项目验收失败、原 R1 阻断项、声明范围和同一候选摘要。本轮没有发现该范围内新的误报成功通道，因此没有为这些入口修改运行源码。

查询退出 0 表示读取或报告生成成功。候选是否通过须读取其输出中的 Execution / Project acceptance，或 JSON 的 pipeline_state / project_acceptance.status。

当前矩阵的工具基线为 ce23aab 加当时工作区已有的 runner 中断修复。精确运行源码由回执中的 34 文件 SHA-256 清单固定，矩阵前后清单一致。不能将旧的 383 项全量结果提升为当前工作区全部变更的新全量证明。

## 事实与验证合同

- 原样本为 `.artifacts/pilots/20261118-ai-market-t1-t9/candidate`，245 文件，摘要 `92cb967c15a7e731651e441d544d53ebfac8c2e6a0a763de135e253bd8a47b4c`。
- 复制原样本并只增加一个结果适配器，得到 246 文件候选，摘要 `d7bd25bab468988e90753c28c3ac69a99342d1ed9920955424687e3e8fcf5bfd`。适配器也纳入候选哈希；原 245 文件及原始断言均未修改。
- 正式 Bash 执行器、Python CLI、PipelineRunner、supervisor、候选验收和七种消费者均实际运行。Python CLI 使用原始模块入口，无运行时 monkeypatch 或替换执行器。
- 只把模型命令替换为隔离 PATH 中的固定本地协议响应。该响应明确声明等待真实 post-command 验收；没有模型推理，没有额外云端派工。实际 R1 检查仍运行原 pytest、临时 HTTP/Caddy、SQLite 和文件存储路径。
- 验收阈值：坏候选的两入口原生退出码和持久化 executor_exit 都为 1；状态为 failed，R1 仍 open；各消费者的候选、范围、状态、阻断项一致；读操作不得改写执行状态。合法协议对照须保持退出 0、complete / passed。
- 比较约束：上一轮已修复 CLI 返回链；本轮尚缺的是跨正式入口、同一候选的当前证据。直接验证这条路径能补足证据，无需修改业务、增加执行引擎或调用云模型。
- 推翻条件：任一坏候选执行入口退出 0、状态／报告显示通过、R1 丢失、候选摘要漂移，或合法对照被误阻断，均使本结论不成立。工具源码或候选改变后，需重做受影响验证。

## 实测矩阵

| 正式入口 | Bash 执行后 | Python CLI 执行后 | 判定 |
|---|---|---|---|
| pipeline-executor.sh / Python CLI run | 退出 1 | 退出 1 | 坏候选被拒绝 |
| Python CLI status | 退出 0，failed / failed | 同左 | 一致 |
| Python CLI report 及生成文件 | 退出 0，failed / failed | 同左 | 一致 |
| pipeline-status.sh | 退出 0，failed / failed | 同左 | 一致 |
| pipeline-monitor.sh | 退出 0，failed / failed | 同左 | 一致 |
| pipeline-list.sh | 退出 0，failed / failed | 同左 | 一致 |
| pipeline-list.sh --verbose | 退出 0，failed / failed | 同左 | 一致 |
| pipeline-list.sh --json | 退出 0，failed / failed | 同左 | 一致 |

两次终态记录有不同的 run_id / attempt_id，候选摘要相同：

- Bash：run `70ca56733aa64a089be66f49d942ab26`，attempt `80e9e720d6934567a0c4537bb3f46436`。
- Python CLI：run `c8ce9f5cea73411bb346fc0436e36589`，attempt `f6d8f12fa9bb433fbe41181e64229277`。

R1 原始两个用例均保持失败：`test_upload_commit_ack_loss_preserves_committed_file`、`test_storage_collision_then_entropy_failure_preserves_existing_asset`。由于当前 CLI 的重复尝试，矩阵实际产生四份两用例 JUnit，共八次用例执行；独立业务反例仍只有两项，不能按八项计覆盖。运行工具和依赖绑定检查通过。

## 回归与证据

新增 `tests/test_entrypoint_consistency.py`，复用现有本地模型协议夹具，以坏候选和合法对照分别经过原 Bash、原 Python CLI 及七个消费者。它以独立的预期状态、范围、候选和阻断项断言消费者结果，保留真实进程退出码与 run / attempt 绑定；合法成功允许复用仍有效的既有验收证据，未把缓存证据伪装成新测试执行。

初次探针曾因测试模块导入路径、误认为列表 JSON 有顶层 run_id、误认为 CLI 只迭代一次而失败。这些探针保留在 artifact 中；它们不是入口误报成功的复现。最终使用既有 JSON 的 project_acceptance.run_id，与实际证据记录对应。

主要证据目录：`.artifacts/entrypoint-consistency-20261118/`。

- `verified/real-r1-receipt.json`：真实 R1 矩阵、所有原生命令退出码、34 文件工具清单、父候选／新候选清单及哈希。
- `verified/bash/`、`verified/python-cli/`：逐入口执行和七个消费者日志、状态快照、交付报告、运行回执。
- `verified/business-evidence/*/r1.xml`：两项原始反例的实际 JUnit，含重复运行，未覆盖旧红灯。
- `protocol-v4.xml`：两种协议候选的初次通过记录；最终新增断言由 `focused.xml` 承接。
- `focused.xml`、`focused.log`、`focused-exit.json`：本轮相关模块回归，完成计数以该 JUnit 和原生退出回执为准。
- `local-http.xml`、`quality-http.xml` 及各自退出回执：沙箱阻止 localhost bind 后，原路径复核的 10 项和 2 项检查，均通过、原生退出 0。

相关模块包含本轮新增测试、runner、EvolveState 和 pipeline-contract，共 158 个独立用例。初次回归为 151 通过、7 失败，原生退出 1，291.86 秒；7 项失败的实际日志均为 localhost HTTP 夹具 `PermissionError: [Errno 1] Operation not permitted`。随后在允许本机回环的环境复核受影响的 12 项检查，全部通过、两次命令均退出 0，其中完整覆盖原 7 项失败。按用例身份对齐后未解决项为 0；没有把重复执行数累加成新增覆盖，也不称其为单次全绿运行。新增两个坏候选／合法对照场景均通过。完整合并关系见 `validation-receipt.json`。

## 新发现与停止线

发现另一个已确认、尚未修复的工具配置问题：公开 CLI `--max-failures 1` 显示停滞阈值 1，但 `EvolveState.check_stall(window=3)` 使用固定默认值，调用方没有传入用户配置。真实 CLI 留下四次迭代、三次无改善后停止的记录。它增加重复执行，没有改变本轮终态为失败的结论。原记录位于第一轮 `python-cli/execution.log` 和 `pipeline/r1-fixed/ai-sdlc-state.json`。本轮记录此问题，不把迭代限制也纳入修复范围。

下一限制由“是否会错误报告成功”转为“显式停滞预算是否可靠约束重复执行”。最小后续工作是独立复现并修复 `--max-failures` 到停滞检查的配置传递，保留合法进展和停止对照。

业务 R1/R2/R4 修复、完整产品验收、真实模型自治、发布和推送均未发生。其他会话已有的 runner、pipeline-contract、中断文档和 tickets 变更不归本轮所有。

## 方法与复盘

Skill 路由：ask-matt → Codex 本地 tdd；codex-workflow-loop 用于本地预检和证据收尾。code-review 的 Standards / Spec 两轴由当前会话自检，按用户限制未启动审查代理，不能称为独立模型复核。比较基点为任务开始的 ce23aab；规格来源为用户本轮固定坏候选和入口一致性要求。

tdd 在 Codex、共享、Claude 三处的文件内容并不相同；本轮按本地优先使用已读取的 Codex 版本，副本差异未同步，不宣称跨根内容一致。未改 Skill、Hook、AGENTS 或全局记忆。

可复用结论：验收失败与查询命令成功退出可以同时成立，必须把进程返回值和业务状态分别核对；合法缓存应保留原证据归属。沉淀目标为本项目测试和本文件，不新增全局规则或记忆。
