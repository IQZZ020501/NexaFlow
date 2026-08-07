# AGENTS_RUNTIME 模块（backend/app/shareddomain/agents + application/agents）

## 职责

Agent 业务领域与运行时：Agent CRUD、知识库/工具绑定与权限校验；基于 LangGraph 的多轮工具调用执行（计划 → 检索/工具调用 → 结果 → 终止条件），事件流式输出，会话记忆注入。

## 分层关系

```text
api/agents.py → application/agents.py（运行编排：构建检索/工具、组装消息、流式）
             → shareddomain/agents/services（CRUD/绑定/权限）
             → shareddomain/agents/runtime（LangGraph 状态图执行）
             → capabilities/{llm,rag,mcp}（模型/检索/MCP 工具）
application/agent_memory.py（历史成功运行 → 上下文记忆）
```

## 文件清单

### shareddomain/agents/

- `backend/app/shareddomain/agents/models.py` — Agent/知识库绑定/MCP 工具绑定/运行记录 ORM 模型
- `backend/app/shareddomain/agents/services.py` — Agent 服务层：CRUD、权限校验、知识库/工具绑定、编排运行参数

### shareddomain/agents/runtime/（LangGraph 执行内核）

- `backend/app/shareddomain/agents/runtime/graph.py` — LangGraph 智能体状态图：多轮工具调用循环、证据去重与终止条件
- `backend/app/shareddomain/agents/runtime/executor.py` — 智能体执行入口 `run_agent`：构建初始状态并驱动状态图，返回结果与事件流
- `backend/app/shareddomain/agents/runtime/tools.py` — 工具适配层：MCP 工具包装为带 schema 校验的 StructuredTool
- `backend/app/shareddomain/agents/runtime/callbacks.py` — 智能体事件总线：事件订阅、敏感字段脱敏、LLM 流式回调
- `backend/app/shareddomain/agents/runtime/state.py` — 智能体运行状态 TypedDict 定义（消息、轮次、待执行工具调用等）

### application/

- `backend/app/application/agents.py` — Agent 运行编排层：构建知识库检索/MCP 工具、组装执行消息、准备/执行/流式运行 Agent
- `backend/app/application/agent_memory.py` — Agent 对话记忆：从历史成功运行记录格式化上下文注入（限量/限字符）

## 相关测试

- `backend/tests/agents.py` — Agent 端到端测试：运行器工具调用/截断与非法参数防护、流式事件、并行与预算策略、MCP 工具发现与 URL 校验、会话记忆裁剪
- `docs/AGENT_TOOL_ORCHESTRATION_RESEARCH.md` — Dify 经典 Agent 与 Agent v2 的工具层、knowledge layer、迭代收束和持久执行边界对照

## 运行策略与生产边界

- 当前自动 Agent 仍由模型在 allowlist 工具中选择；系统消息明确要求工作区问题优先 `search_knowledge`，MCP 只用于当前/外部数据或用户明确要求的外部动作。知识库名称/描述会以有界元数据提供给模型。这是路由引导，不是确定性保证；严格 KB-first 需要后续显式 `required/eager` query policy 或工作流检索路径。
- 每次工具调用与整次在线运行都有硬超时；达到最后一轮时不再向模型暴露工具。连续两轮没有新知识证据后停止继续检索，保留 MCP 外部能力供模型决定是否需要。
- 当前 HTTP/SSE 路径没有持久 checkpoint、工具调用幂等账本、租约 worker 或审批恢复；因此在线生产范围应限制为知识检索和部署层审核过的只读 MCP，带副作用的 MCP 仍需 Durable Executor（队列、幂等键、审批和断线恢复）完成后再开放。
