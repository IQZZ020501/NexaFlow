# 运行可靠性与资源准入

系统通过以下机制实现持久运行：活动 Run 恢复、创建幂等、文件稳定身份、资源等待与组合准入、独立于摘要的精确引用。继续复用 PostgreSQL Run 四表、统一 ToolInvocation 账本、Celery 与 OpenSandbox，不增加常驻服务。

## Run 恢复与创建

- Console 和公开聊天读取历史后，继续观察原来的 queued/running/awaiting_approval Run。恢复观察不创建新 Run，也不执行新的工具调用。
- 流层遇到过期 Worker 租约，发送 `recovering` 快照并继续观察；只有数据库已保存的成功、失败或取消状态才结束流。Beat 和既有租约机制负责恢复执行。
- 审批 HTTP 响应可能晚于同一 Run 的完成事件。Console/公开聊天的快照合并拒绝把已保存终态降回运行中，避免最终回答被迟到的审批响应覆盖；持续审批流回归覆盖此竞态。
- 持久过程携带事件 `sequence`、Worker `stream_epoch` 和已包含的 Redis `live_sequence`，快照与公开进度投影保留这些位置（公开 epoch 仍做哈希）。前端按过程版本合并，只追加水位之后的推理/参数增量；工具开始执行后输入固定，重连快照保留已显示的较新过程。NDJSON 每处理一条事件即提交恢复游标，读流异常不会退回旧位置。
- OpenAI 兼容与专用 DeepSeek 的 Chat Completions 历史保留供应商返回的 `reasoning_content`，包含工具结果后的下一轮请求；未返回该字段的消息不补造字段，Responses API 沿用其原生序列化。两轮回归覆盖真实 Agent 循环和流式/非流式 SDK 请求，使用模拟供应商。
- 创建、Console/公开聊天重新生成支持可选 `request_id`，长度 1–64，限 ASCII 字母、数字、`_`、`-`。同一 workspace、application、access_source、consumer 内，同键同内容返回原 Run；同键不同 goal/conversation/file IDs/approval mode 返回 `409`。不同重新生成来源也会产生冲突。
- Agent 行锁串行化请求查询和写入，数据库唯一约束兜底。重放先于一次性上传解析、配额和派发；已完成 Run 也能重放。
- 前端为一次提交生成一个键，响应不明的网络错误或 5xx 只自动重试一次，重用原始请求体。取消和确定的 4xx 不重试。缺省不传键的旧客户端仍按原契约创建。

## 工具租约、审批与结果

- 普通调用和 MCP 长任务均核对 invocation 与所属 Run 的 Worker 身份。Run 状态接受共享的 `running` / `running_v2` 集合；普通调用在 adapter 等待期间续租，失去任一归属或收到 Run 租约丢失信号时通知并取消 adapter。结果写回再次核对归属；只有租约过期而未被接管时，已返回的成功结果仍可保存。
- Agent API 使用 `ask_risky` 解释审批偏好，包括读取旧 Run 快照时。创建预检和执行前检查继续要求 Tool 策略为 `auto`、effect 为 `pure` 或 `external_read`，且允许 API 访问；需要交互审批的工具在创建时拒绝。Console 和公开聊天仍按用户选择审批。
- bash 按最终 UTF-8 JSON 大小裁剪 stdout/stderr 预览，使整体结果保持在 32 KiB 内，并保留退出码和制品引用。超出预览的结果在 2 MiB 内保存到 `tool_invocations.full_result`，通过同 Run、执行用户和访问来源隔离的 `read_tool_result` 分页读取；沙箱原有的 30 KiB 日志采集上限保持不变。
- 生图账本记录 `not_started`、`dispatched`、`completed`。请求前在短事务中检查归属并提交派发标记，制品写入在同一归属锁下提交；取消事务与这些边界按 RunState → invocation 顺序锁定。取消发生在模型配置读取期间时，不再派发供应商请求；已派发的请求仍可能收费，取消后返回的图片不会跨过归属检查落库。缺少派发标记的旧记录继续保守判定 `uncertain`。

`tests.tools.tools` 包含 `tests.tools.lifecycle` 的真实账本时序回归，覆盖续租、Run/invocation 接管、取消发生在生图派发前后、结果重放以及 bash 日志分页与身份隔离。带实际 Run 的 HTTP 长任务首次提交、恢复和 API 只读审批检查由 `tests.tools.remote_tasks` 覆盖。

## 文件身份与授权

沙箱丢失后的重建与 Worker 重连是不同事件。新 guest 发布与
`environment` / `agent.workspace_reset` 过程事件在同一数据库事务中提交；
即使重建发生在导入文件阶段，后续 bash 只报告普通重连，刷新页面仍能看到环境重建提示。
会话产物和已保存的工作文件按各自授权范围恢复，依赖锁按现有规则重放；
没有保存的文件、后台服务、浏览器和进程内存不在恢复保证内。

每次导出保留独立 `artifact_id`、`relative_path`、SHA-256 `content_hash` 和同会话同路径的 `previous_artifact_id`。旧数据允许缺少新增元数据。版本身份不依赖可过期的下载地址；两个目录的同名文件分别展示，旧消息继续指向原版本。

| 调用方 | 稳定读取入口 | 每次读取的授权 |
| --- | --- | --- |
| Console / 公开聊天登录用户 | `GET /api/v1/artifacts/{artifact_id}/content` | 原会话调用者、当前成员/应用访问权；公开入口还要求当前发布和访问资格 |
| Agent API | `GET /api/v1/agent-api/{agent_id}/runs/{run_id}/artifacts/{artifact_id}/content` | 当前有效 API 凭据、应用及 Run 所属调用方；允许该根 Run 的子运行文件 |

关联 Run 的字节按原会话/应用生命周期保留，稳定入口不再受 `expires_at` 限制。已有签名 bearer URL、图片 UUID URL 和独立临时文件继续使用 24 小时有效期。图片的旧消息内联预览仍受 bearer 过期影响。

下载继续是 attachment、`nosniff`、`private, no-store`，HTML 加限制性 CSP。前端用当前会话在宿主读取文件字节，再传给不透明 sandbox iframe；不向 viewer 发送登录令牌，不授予 `allow-same-origin`。

## 资源等待与调度

ToolInvocation 的 `resource_wait` 保存 schema version、首次入队、等待截止时间、原因、所需资源和下次尝试时间。等待上限为首次 Busy 后 300 秒，且始终受原 Run deadline 约束。每次重排队不延长这两个截止时间。

确认命令尚未派发的 Busy 会回退本次 claim 的 attempts，立即交回 Worker；超过等待上限后返回明确的资源等待超时。再次获准时恢复冻结的单次执行窗口，并受整体 Run deadline 限制。已经可能派发的动作保留 uncertain 语义，不能以资源等待为名重做。

新 Agent 和 Workflow Run 冻结 `application_snapshot.sandbox_requirements`：普通任务预留一份；绑定 stdio MCP 的任务预留代码和 MCP 两份，最多一个同时存活的 stdio 宿主。第一次真正需要 guest 时才原子准入，实际环境仍按需创建，纯模型和远程 HTTP 调用不申请 guest。缺少该字段的旧快照按其已有能力推导保守组合需求，不扩展授权。

准入同时检查主机、workspace、外部 consumer 数量，以及可选 CPU/内存预算。未消费的承诺也计入额度。规格由冻结能力集推导，仍是待真实负载校准的保守配置。预热默认关闭；启用时同时扣除空闲池数量和最重规格预算。

Redis 原子队列采用工作空间轮转、同一空间按到达顺序，跳过已受 workspace/consumer 配额限制的空间。每个宿主最多 1000 个等待，单空间最多 100 个，记录最多等待 300 秒。不提供精确排队位置或 ETA。容量释放发出合并后的 Celery 唤醒，提前重试原 Run/调用；持久记录与原子准入继续决定能否执行，heartbeat 和 Beat 补偿丢失的通知。不允许小任务绕过暂时放不下的大任务，等待上限负责约束这种阻塞。

## 持有者、创建与回收

- Run 租约和命令 holder 只负责执行所有权，不能用它们的短过期时间释放 guest 容量。
- `execution_sessions` 保存组合预留和 `creation_pending`。受限主机准入在短 PostgreSQL advisory transaction lock 内恢复 Redis 账本、原子预留并持久化创建意图；不在锁内请求 OpenSandbox。
- 已提交的会话及临时创建预留能在 Redis 状态丢失后重建存活 guest 和未消费的组合预算。无持久会话的短期独立执行也保留数据库创建预留，直到确认销毁或 native TTL。
- 创建未返回 guest ID 时，SDK 包装后的错误也不能证明没有环境存活：保留意图和容量，禁止第二次创建，等待对账或 native TTL。同一 Run 的后续执行立即返回明确的未执行失败，让 Agent 继续使用其他工具；不再将这个无法恢复的会话当作资源繁忙、逐次排队等待 300 秒。后台清理将该记录标为 closing 时也遵守此规则，实际容量不足或仍在进行的并发创建继续按原等待策略处理。已知 guest 的销毁成功或明确 404 后才释放占用。
- 同一组合的成员绑定会话 ID，旧会话清理不能释放新持有者。最后一个持久会话关闭后才撤销组合承诺。取消等待会话撤销队列记录，执行中取消沿用停止命令、关闭 guest 的既有流程。
- 预留保留到 Run deadline + 60 秒的 guest native TTL；异常时可能保守多占容量，但不能因为短租约到期漏算存活环境。

## 精确引用与原始历史

checkpoint 的 `harness.exact_references`（schema version 1）独立保存文件各版本身份/路径/哈希、外置结果身份/来源调用、输入源 ID 与已加载 Skill ID；固定 Skill 版本继续由能力 checkpoint 保存。自然语言摘要不能改写这个索引。

每轮向模型投影最近的完整引用，JSON 限 4000 字符，不截断 ID 或路径。压缩后重新注入同一权威投影；完整索引留在 checkpoint。内置 `read_conversation_history` 可分页读取：

- 不传 `run_id`：列出成功历史 Run 和最新文件身份，每页最多 20 项。
- 传 `run_id`：按 Unicode 字符 offset/limit 读取 goal、result、attachment_context、inputs 或 references，每页最多 12000 字符。
- `field=tool_result`：额外传 `result_id`，复用原有完整工具结果读取与大小限制。

历史读取要求 workspace、application、access_source、consumer、execution_user、conversation 六项身份一致，历史来源必须已成功；本 Run 可读取自身已保存状态。原始文本与结构化引用均作为不可信数据进入模型，不赋予工具或访问权限。

## 升级与验证

迁移 `202611180002` 增加按工作空间时区划分的月度模型用量和逐请求预留。
注册 LLM 的每次异步供应商调用（含工具绑定、压缩、Workflow 和子 Run）在发出前
原子检查 `used_tokens + reserved_tokens`；结算只使用这次供应商报告的用量，
不重复累加父子 Run 的汇总。无月度限制仍记录用量，但不改变原来的输出参数。
启用月限额时，预留输入序列化 UTF-8 字节数加 4096 framing 余量，以及请求的输出上限
（未指定时 4096）；向供应商传递相应输出限制。该准入估算可能高估普通文本输入，
也不是供应商计费的数学硬上限：特殊输入或供应商计数超出估算时仍记录实际用量，
后续请求被阻止。Embedding、reranker、VISION 和生图不在本次 LLM 月度账本内，
不能把它当成覆盖所有外部 API 的金额预算。

超时、取消、Worker 中断或没有 usage 的响应保留预留，避免把可能已计费的请求当成零。
运维应先在供应商侧核实实际 token，再从 `backend/` 只读查看并显式结算：

```sh
uv run python -m scripts.reconcile_model_usage --reservation-id RESERVATION_ID
uv run python -m scripts.reconcile_model_usage --reservation-id RESERVATION_ID --actual-tokens VERIFIED_TOKENS --apply
```

新账本从升级开始记录，不从历史 Run 汇总反推计费。部署时先完成迁移；
若在月中启用，需在运维侧考虑升级前的供应商用量。回退前停止模型调用、备份账本，
再降级代码并保留账本；非空账本的 migration downgrade 会拒绝执行，
避免丢失已用量和不确定预留。
回归入口为 `tests.governance.tokens`，显式提供隔离
`NEXAFLOW_TEST_DATABASE_URL` 时验证 PostgreSQL 并发，否则使用 SQLite。

迁移 `202611160001` 增加请求身份/唯一约束、资源等待、artifact 哈希/前版本，以及会话预留/创建意图。生产仍通过现有 `migrate` 服务升级；不要让新代码先于迁移运行。回滚前需停止相关运行并保存新增元数据，再降级代码/迁移；直接 downgrade 会移除新增元数据。

常规回归包括 `tests.agents.reliability`、`tests.agents.harness`、`tests.agents.agent_runtime_coverage`、`tests.artifacts.conversations`、`tests.tools.tools`、`tests.execution.unit`、`tests.execution.sessions`。Redis 原子准入可使用明确隔离的测试库运行：

```bash
cd backend
NEXAFLOW_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m tests.execution.reservations
```

该测试使用随机主机命名空间，并只清理自己的键。不得把地址指向业务 Redis。迁移升级/降级和数据库并发需要独立 PostgreSQL 17（含项目固定 pg_search）验证。

准入与恢复的其他检查入口：`tests.execution.wakeup`、`tests.execution.admissions`、`tests.execution.load`。它们分别覆盖释放后的唤醒、创建结果不明时的容量保留，以及工作空间轮转/FIFO。测试通过不代表完成生产创建耗时、峰值资源和 P50/P95 负载校准。

可选多主机与故障边界见 [执行主机](EXECUTION_HOSTS.md)，对话文件、MCP 外部授权和持久任务分别见 [对话文件](PROJECT_FILES.md)、[MCP OAuth](MCP_OAUTH.md)、[MCP 远端任务](MCP_TASKS.md)。
