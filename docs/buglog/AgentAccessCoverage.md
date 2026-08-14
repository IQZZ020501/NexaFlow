# AgentAccessCoverage — BUG 记录

> 由 `tests/agent_access.py`（公开 Agent / API 凭证访问域覆盖率套件）产生。
> 只记录、不修改产品代码。格式见 docs/BUG_LOG.md 顶部。

## 发现的 BUG 汇总

### low: authenticate_agent_api_credential 工作空间不匹配分支不可达

- 编号: BUG-agentaccess-001
- 严重度: low
- 模块: `backend/app/application/agent_access.py:721-722`（`authenticate_agent_api_credential`）
- 现象: `if credential.workspace_id != context.agent.workspace_id: raise HTTPException(401)` 分支无法通过任何输入触发。API 凭证创建时固定使用 `agent.workspace_id`（`_new_agent_api_credential`），而 `get_published_application_context` 返回的 `context.agent` 就是同一 agent，两个 workspace_id 恒等；系统也没有迁移 agent 工作空间的功能。
- 预期: 死代码（防御性分支），无法被测试覆盖。
- 复现: 无法构造 `credential.workspace_id != context.agent.workspace_id` 的合法持久化数据。
- 来源: tests.agent_access

### low: get_agent_monitoring 日期过滤分支不可达

- 编号: BUG-agentaccess-002
- 严重度: low
- 模块: `backend/app/application/agent_access.py:1112-1113`（`get_agent_monitoring`）
- 现象: `if day not in daily_values: continue` 条件恒为假。`list_agent_monitoring_rows` 以 `created_at >= since`（since = 窗口首日 00:00）过滤，返回行的 `created_at.date()` 必然落在 `daily_values` 键范围（`first_day..today`）内。
- 预期: 死代码（防御性分支），无法被测试覆盖。
- 复现: 无法构造 `created_at >= since` 但日期不在窗口内的行（除非 UTC 时钟在查询窗口内跨天且不一致）。
- 来源: tests.agent_access

### test-infra: coverage C tracer 在 await eager agent run 执行后丢失调用方后续行事件

- 编号: BUG-testinfra-002
- 严重度: test-infra (low)
- 模块: coverage.py 7.15.4（C 扩展 tracer）+ TestClient 工作线程 / `enqueue_prepared_agent_run` eager 执行
- 现象: `coverage run` 下（a）TestClient 工作线程中执行的部分行不被记录（例如 agent_access 端点的 `return await ...` 行）；（b）在主线程直接调用 `create_external_agent_run` / `resolve_external_agent_tool_approval` 时，await 完整 eager run 执行（`enqueue_prepared_agent_run` → `run_durable_agent_run`）返回后的调用方行（如 agent_access.py:803-804、860）不被记录；将 enqueue 替换为 no-op 后同一语句可被正常记录。`--timid`（纯 Python tracer）下 TestClient 报 `RuntimeError: This portal is not running`。
- 预期: 所有实际执行过的行都应被记录。
- 复现: `uv run coverage run --source=app.application.agent_access --data-file=.coverage.AgentAccessCoverage -m tests.agent_access`（agent_access.py:802 被记录而 803-804 缺失）。
- 来源: tests.agent_access（套件已用 no-op enqueue 规避，HTTP 端到端路径仍走真实 eager 执行）
