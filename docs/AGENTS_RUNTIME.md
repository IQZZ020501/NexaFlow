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
