# 运行可靠性与资源准入

本轮落实《NexaFlow 架构改进与沙箱调度设计》的 P1：活动 Run 恢复、创建幂等、文件稳定身份、资源等待与组合准入、独立于摘要的精确引用。继续复用 PostgreSQL Run 四表、统一 ToolInvocation 账本、Celery 与 OpenSandbox，不增加常驻服务。

## Run 恢复与创建

- Console 和公开聊天读取历史后，继续观察原来的 queued/running/awaiting_approval Run。恢复观察不创建新 Run，也不执行新的工具调用。
- 流层遇到过期 Worker 租约，发送 `recovering` 快照并继续观察；只有数据库已保存的成功、失败或取消状态才结束流。Beat 和既有租约机制负责恢复执行。
- 审批 HTTP 响应可能晚于同一 Run 的完成事件。Console/公开聊天的快照合并拒绝把已保存终态降回运行中，避免最终回答被迟到的审批响应覆盖；持续审批流回归覆盖此竞态。
- 创建、Console/公开聊天重新生成支持可选 `request_id`，长度 1–64，限 ASCII 字母、数字、`_`、`-`。同一 workspace、application、access_source、consumer 内，同键同内容返回原 Run；同键不同 goal/conversation/file IDs/approval mode 返回 `409`。不同重新生成来源也会产生冲突。
- Agent 行锁串行化请求查询和写入，数据库唯一约束兜底。重放先于一次性上传解析、配额和派发；已完成 Run 也能重放。
- 前端为一次提交生成一个键，响应不明的网络错误或 5xx 只自动重试一次，重用原始请求体。取消和确定的 4xx 不重试。缺省不传键的旧客户端仍按原契约创建。

## 文件身份与授权

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
- 创建未返回 guest ID 时，SDK 包装后的错误也不能证明没有环境存活：保留意图和容量，禁止第二次创建，等待对账或 native TTL。已知 guest 的销毁成功或明确 404 后才释放占用。
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

迁移 `202611160001` 增加请求身份/唯一约束、资源等待、artifact 哈希/前版本，以及会话预留/创建意图。生产仍通过现有 `migrate` 服务升级；不要让新代码先于迁移运行。回滚前需停止相关运行并保存新增元数据，再降级代码/迁移；直接 downgrade 会移除新增元数据。

常规回归包括 `tests.agents.reliability`、`tests.agents.harness`、`tests.agents.agent_runtime_coverage`、`tests.artifacts.conversations`、`tests.tools.tools`、`tests.execution.unit`、`tests.execution.sessions`。Redis 原子准入可使用明确隔离的测试库运行：

```bash
cd backend
NEXAFLOW_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m tests.execution.reservations
```

该测试使用随机主机命名空间，并只清理自己的键。不得把地址指向业务 Redis。迁移升级/降级和数据库并发需要独立 PostgreSQL 17（含项目固定 pg_search）验证。

2026-11-16 本地验证结果：24 组后端回归通过，前端 286 项测试、TypeScript、ESLint、生产构建通过，Python Ruff、编译和架构检查通过。隔离 PostgreSQL 17 完整迁移链升级及本次迁移降级/升级往返通过；8 个同键并发事务只创建一个 Run；两个双环境 Run 只准入一个，Redis 账本丢失后能从数据库重建并继续拒绝超额准入。业务数据库未迁移。

后续扩展回归时已更新 LLM 测试桩的 `generation_info`，该基础设施套件通过；未修改生产 LLM 行为。

后续普通 Docker 的真实 OpenSandbox 文件恢复、两控制面放置及控制面暂停恢复检查通过，见 [EXECUTION_HOSTS.md](EXECUTION_HOSTS.md)。项目文件、OAuth/远端任务和可信扩展的交付状态见 [ARCHITECTURE_DELIVERY.md](ARCHITECTURE_DELIVERY.md)。DeepSeek 真实模型基线首轮 4/5 的失败记录保留；表格产品规则与无缓存公式反馈修复后，以原中性 Agent 指令完整重跑 5/5，见 [修复回归](evaluations/2026-11-17-spreadsheet-values/README.md)。生产负载、物理多主机与 Kata 校准仍需分别验收；自主子代理依用户要求暂不实施。

2026-11-17 收尾补齐 Workflow 与旧快照的组合需求、释放即时唤醒及临时创建的数据库预留账本。`tests.execution.wakeup` 验证原调用身份、等待期限和执行次数不变；`tests.execution.admissions` 验证不明创建经 Redis 丢失仍占容量；`tests.execution.load` 在真实 Redis 饱和队列下完成 5 空间 60 请求、首轮轮转与空间内 FIFO。PostgreSQL 并发放置和完整空库迁移到 `202611160006` 通过。这些验证不代替生产环境的创建耗时、峰值资源和 P50/P95 负载测量。
