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
- `backend/app/application/agent_runs.py` — Agent Run 编排：提交/查询、工具审批与 PostgreSQL/Redis 可重放事件订阅
- `backend/app/application/agent_executor.py` — Durable Executor：短事务装载、租约心跳/接管、节点 checkpoint、工具账本与 Redis 实时 delta 发布
- `backend/app/application/agent_memory.py` — Agent 对话记忆：按会话恢复角色消息，并在模型上下文预算内压缩旧轮次、持久化摘要
