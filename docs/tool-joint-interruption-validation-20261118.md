# Python CLI → Runner → Bash 联合中断验收

日期：2026-11-18，Asia/Singapore。验收基线：`ce23aab`。
交付对象是 ai-sdlc-claudecode 工具。本轮继续使用本地工具，不增加云端模型派工。

**收口：基线 `ce23aab` 联合验收不通过；最小修复后的固定候选通过联合 2/2、
每种信号七入口 7/7，以及完整框架 385/385。完整 AI 管理目标仍未通过。**

## 基线判定与根因

**`ce23aab` 联合验收不通过：SIGINT 通过，SIGTERM 失败，1/2。**
这份失败结果保留，不会因后续修复而把旧版本改判为通过。

| 原始信号只发送给 CLI PID | CLI 实际退出码 | 最终执行记录 | 基线判定 |
| --- | --- | --- | --- |
| SIGINT | 130 | 130 | 通过 |
| SIGTERM | 143 | 130 | 失败 |

SIGTERM 时，CLI 已返回 143，Bash 阶段的失败原因也为 `Executor exited with code 143`，
最终 `executor_exit` 却成为 130。与“CLI 映射错误”“Bash 未能落盘”比较，
源码及运行值共同指向 Runner 的 `except BaseException` 分支：清理后固定记录 130，
覆盖了已正确记录的结果。原直接 Bash 的分项通过证据不能外推为联合路径通过。

干净基线用例耗时 5.00 秒；权威回执为
`.artifacts/quality-joint-interruption-20261118/ce23-actual-red.xml`。
初次夹具误把首轮未完成时不存在的 phase 条目当作必有字段，其错误记录独立保留；
它没有被当作工具缺陷证据。实际约束是 checkpoint 不得声称阶段 complete。

## 最小修复与验收方法

只修改 Runner 的异常结果记录：CLI 抛出带整数非零退出码的 `SystemExit` 时保留该码；
其他中断继续沿用既有 130。run／invocation 校验、进程组清理、超时处理和异常传播均复用原实现。
不修改 CLI、Bash、状态模型、产品断言或生产超时配置。

新增回归使用既有 executor 夹具，实际路径为：公开 CLI 参数解析与 `run` →
真实 `PipelineRunner.run` → 真实 `pipeline-executor.sh` → 真实本地模型调度进程。
等待模型替身确实进入阻塞状态后，信号只发给 CLI PID；Runner 必须负责终止其另一个进程组中的 Bash。

测试设置的替换边界为模型可执行程序、临时执行器／状态目录、安装连通性 preflight 和单轮上限。
执行器包装脚本仅追加临时 `--project-dir` 并 exec 原 Bash。Runner、信号处理、状态写入及报告不做结果 mock。

## 验证结果

| 修复后检查 | 实测 |
| --- | --- |
| SIGINT | CLI／执行记录均 130；流水线与活动阶段 failed，owner 释放 |
| SIGTERM | CLI／执行记录均 143；流水线与活动阶段 failed，owner 释放 |
| 自动清理 | 两种信号下 Bash 与模型替身均已消失；断言在测试 finally 的兜底清理之前执行 |
| 七个报告入口 | 每种信号各 7/7；执行 failed、产品 not_evaluated；读取前后状态字节一致 |
| 原生显式 `--resume` | 两种场景均退出 0；原 S8／S9 scope 保留，新 run／attempt，旧失败进入 history |
| 联合定向回归 | 2/2；8.95 秒 |
| 完整框架回归 | 385/385；0 失败、0 错误、0 跳过；退出 0；566.776 秒 |
| 源码／资源收尾 | 76 个绑定运行及测试文件无漂移；自有进程 0；额外云端派工 0 |

执行记录中的最终码是监督调用的公共结果。Runner 沿用 SIGTERM 清理子进程组；
因此 CLI 接收 SIGINT 时，子 Bash 的清理原因可以是 143，监督结果应保持 CLI 的 130。
验收比较各层的既定含义，不把清理信号伪称为原始输入信号。

七入口包括 CLI status、Shell status、monitor、普通／verbose／JSON 列表和 Markdown report，
均在原中断状态尚未恢复时实际读取。中断状态原始字节、观察值和读端回执已归档于
`.artifacts/quality-joint-interruption-20261118/fixed-SIGINT/` 与 `fixed-SIGTERM/`。
完整回归中的实际现场另归档为 `full-SIGINT/`、`full-SIGTERM/`；旧失败 attempt
在各自恢复后的 history 中均恰好出现一次。385 个用例是原 383 项加 2 个联合用例，未删除或替换原用例。
权威汇总为同目录 `joint-validation-result.json`，完整 JUnit 为 `full.xml`，
进程清理读回为 `cleanup-readback.json`。另一会话在收集后创建的未跟踪测试不纳入本次候选与提交。

## 边界、推翻与后续约束

事实是本地联合路径的信号、退出、失败落盘、清理和显式原生恢复可被实际验证。
推断是已控制 Runner 固定 130 导致的退出结果覆写，有限范围置信度高。
CLI 首轮尚未返回时 iteration 为 0、phase 条目尚未生成；checkpoint 保存且不声明完成。
本轮不据此宣称 CLI 跨进程自动恢复已实现，恢复证明限于原生显式 `--resume`。

模型替身证明工具控制流；真实模型和代理链、SIGKILL／断电、长期无人值守、
独立业务复核与返工率改善仍未验证。AI Market 产品原有失败及完整 AM-ISO-01 的未通过结论保留。

若同版本、同一已测路径再次出现 CLI 与监督记录不一致、存活子进程、running 残留、
旧 writer 覆盖新 run、恢复丢失证据、读端不一致或必要失败被错误接受，推翻对应通过判断。
完整回归未通过或运行源文件摘要漂移时不能交付。回滚只撤回本次 Runner／测试提交，保留基线和失败回执。

经验沉淀在本项目文档：独立入口各自通过，仍需验证组合边界；中断退出应沿调用链传递实际公共结果。
沿用已读 Codex 本地 Matt 路线；共享目录同名正文差异未同步。复核由协调者本地完成，没有派工独立审查代理。
