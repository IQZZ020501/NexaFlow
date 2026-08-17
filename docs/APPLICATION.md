# APPLICATION 模块（backend/app/application）

## 职责

应用服务层：HTTP 层与领域层之间的编排与业务规则。负责跨模块流程（登录签发、运行编排）、规则校验（最后一名管理员、角色约束）与审计记录（`record_audit_log`）。

## 分层关系

```text
api/endpoints → application（编排/规则/审计）→ shareddomain + capabilities
```

## 文件清单

- `backend/app/application/identity.py` — 身份与应用服务：登录认证、access/refresh token 签发、改密、用户 CRUD 及审计记录
- `backend/app/application/workspace.py` — 工作区应用服务：创建/更新/删除、成员增删改、最后一名管理员等规则校验
- `backend/app/application/agents.py` — Agent 用例门面：重导出 Agent CRUD、Run 与工具用例，保持 API 层入口稳定
- `backend/app/application/agent_runs.py` — Agent Run 编排：登录态与公开/API Key 提交、按来源主体查询、工具审批及 PostgreSQL/Redis 可重放事件订阅；外部响应经过独立白名单收敛
- `backend/app/application/agent_access.py` — Agent 外部访问用例：发布资料、HttpOnly 访客会话、Agent 级 API Key 创建/轮换/撤销、跨来源日志/用户/监控聚合、公开/API 流安全投影与 Redis 成本限流
- `backend/app/application/agent_executor.py` — Durable Executor：短事务装载、租约心跳/接管、节点 checkpoint、工具账本与 Redis 实时 delta 发布
- `backend/app/application/agent_tools.py` — 把 Agent 固定 `ToolRef` 解析为 ToolSnapshot，并构造模型可调用工具
- `backend/app/application/agent_tool_runtime.py` — Agent 调用统一 Tool Runtime 的幂等身份、审批状态和结果映射
- `backend/app/application/agent_child_runs.py` — Workflow Agent 节点的固定发布版本、durable child Run、恢复与取消编排
- `backend/app/application/agent_memory.py` — Agent 对话记忆：按会话恢复角色消息，并在模型上下文预算内压缩旧轮次、持久化摘要
- `backend/app/application/tools.py` — 统一 Tool 用例门面，向 API 暴露目录、Source、Python 生命周期、授权与策略操作
- `backend/app/application/tool_management.py` — Tool/Source 查询，Python 草稿/测试/发布/启停/归档，MCP Source 生命周期及 `view/use` 授权
- `backend/app/application/tool_runtime.py` — canonical ToolInvocation 的预检、入队、租约执行、终态与 uncertain 处理
- `backend/app/application/tool_adapters.py` — builtin/Python/MCP 的唯一 provider 分流边界；业务调用方不直接判断工具类型
- `backend/app/application/workflows.py` — Workflow 用例门面：定义、版本、运行、外部访问与上传能力的稳定入口
- `backend/app/application/workflow_runs.py` — 草稿/发布运行创建、资源快照、Tool/Agent 预检、事件订阅与表单恢复
- `backend/app/application/workflow_executor.py` — 确定性图执行、租约/checkpoint、节点审计、durable child Run 与终态编排
- `backend/app/application/workflow_tool_runtime.py` — Workflow 直接 Tool 节点与 LLM Tool 循环共用的 canonical ToolInvocation 适配
- `backend/app/application/workflow_access.py` — 已发布 Workflow 的公开/API Key 资料、会话、Run 与安全流投影
