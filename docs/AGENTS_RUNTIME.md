# AGENTS_RUNTIME 模块（backend/app/shareddomain/agents + application/agents）

## 职责

Agent 业务领域与运行时：Agent CRUD、知识库/工具绑定与权限校验；基于 LangGraph 的多轮工具调用执行（计划 → 检索/工具调用 → 结果 → 终止条件），事件流式输出，会话记忆注入。

## 分层关系

```text
api/agents.py → application/agents.py（公开用例门面）
             → application/agent_runs.py（提交运行、审批、可重放事件订阅）
             → application/agent_executor.py（租约执行、checkpoint、工具账本）
             → shareddomain/agents/services（CRUD/绑定/权限）
             → shareddomain/agents/runtime（LangGraph 状态图执行）
             → capabilities/{llm,rag,mcp}（模型/检索/MCP 工具）
application/agent_memory.py（历史成功运行 → 上下文记忆）
```

## 文件清单

### shareddomain/agents/

- `backend/app/shareddomain/agents/models.py` — Agent/绑定/Run、事件游标与工具调用账本 ORM 模型
- `backend/app/shareddomain/agents/services.py` — Agent 服务层：CRUD、权限校验、知识库/工具绑定、编排运行参数

### shareddomain/agents/runtime/（LangGraph 执行内核）

- `backend/app/shareddomain/agents/runtime/graph.py` — LangGraph 智能体状态图：多轮工具调用循环、证据去重与终止条件
- `backend/app/shareddomain/agents/runtime/executor.py` — LangGraph 执行入口与可序列化节点 checkpoint
- `backend/app/shareddomain/agents/runtime/tools.py` — 工具适配层：MCP 工具包装为带 schema 校验的 StructuredTool
- `backend/app/shareddomain/agents/runtime/callbacks.py` — 智能体事件总线：事件订阅、敏感字段脱敏、LLM 流式回调
- `backend/app/shareddomain/agents/runtime/state.py` — 智能体运行状态 TypedDict 定义（消息、轮次、待执行工具调用等）

### application/

- `backend/app/application/agents.py` — Agent 用例门面：重导出 CRUD、Run 与工具用例，保持调用方入口稳定
- `backend/app/application/agent_runs.py` — Run 编排：提交/读取、审批与 PostgreSQL/Redis 事件订阅
- `backend/app/application/agent_executor.py` — Celery worker 执行：Run 租约/心跳/接管、checkpoint、工具幂等账本与终态
- `backend/app/application/agent_memory.py` — Agent 对话记忆：从历史成功运行记录格式化上下文注入（限量/限字符）

## 相关测试

- `backend/tests/agents.py` — Agent 端到端测试：检索策略、租约接管、断线、MCP 审批/只读策略/不确定结果、运行器预算与安全边界
- `docs/AGENT_TOOL_ORCHESTRATION_RESEARCH.md` — Dify 经典 Agent 与 Agent v2 的工具层、knowledge layer、迭代收束和持久执行边界对照

## 运行策略与生产边界

- 知识策略显式分为 `required`（默认，用用户原始问题在首个模型节点前检索）和 `agentic`（模型生成查询并决定何时调用）；策略与绑定会快照到 Run，运行中修改 Agent 不改变已提交 Run。
- 每次工具调用与整次在线运行都有硬超时；达到最后一轮时不再向模型暴露工具。连续两轮没有新知识证据后停止继续检索，保留 MCP 外部能力供模型决定是否需要。
- HTTP 只提交/观察 Run；Celery worker 用数据库租约执行，节点 checkpoint、过程事件游标和工具账本均持久化。答案与推理 delta 不写 PostgreSQL，而是进入按 Run 隔离、限长并带 15 分钟 TTL 的 Redis Stream；API 把 Redis 增量与数据库事件合并为同一 NDJSON。客户端分别用 `after` 和 `live_after` 恢复持久与实时游标，终态数据库快照负责最终校正；Redis 不可用时自动降级为过程事件加完整终态答案。断开 NDJSON 不会取消 Run。
- 新发现的 MCP 工具默认逐次审批；只有管理员按当前定义哈希显式设置为 `read_only` 才会自动运行，远端 `readOnlyHint` 等注解不会单独改变审批策略。管理员可按当前定义哈希设置为只读、审批或禁用，工具定义变化后已有策略回落到逐次审批。副作用调用携带稳定幂等键；传输超时、worker 在外部调用后崩溃或结果未落账时标记 `uncertain`，禁止自动重试，只能人工确认后“不重试并继续”。远端 MCP 若不兑现幂等键，系统提供的是保守恢复而非跨系统 exactly-once。
