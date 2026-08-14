# AgentServicesCoverage 发现

## test-infra: coverage 的 portal 线程在首个 await 后丢失跟踪，HTTP 路径行无法统计

- 编号: BUG-testinfra-003
- 严重度: test-infra (low)
- 模块: `backend/tests/agent_services_coverage.py`（以及所有基于 TestClient 的套件）
- 现象: 在 `coverage run` 下，TestClient（anyio portal 线程）执行的 HTTP 处理路径只被
  跟踪到每个协程的第一个 await 之前的语句；之后的所有行（如
  `app/api/v1/endpoints/agents.py` 的 124, 251, 271-272, 287-288, 308, 321, 337-338,
  475-478, 490, 518-528, 541）即使被真实执行并返回正确状态码，仍被报告为“缺失”。
  主线程中 `asyncio.run(...)` 的直接调用则被完整跟踪（services/permissions/repository/
  tasks 全部达 100%）。已用最小复现（`tests.probe_cov4`、`min_login6.py`）确认：
  `GET /workspaces/{id}/agents/ghost-agent` 返回 404，但 `services.py` 的 195-197
  仍显示未覆盖；端点第一语句（如 250/270/286/320/336）被覆盖、第二语句（251/271/308/321）
  不覆盖。
- 预期: HTTP 请求线程与主线程应被同等跟踪，端点行可统计。
- 复现: `uv run coverage run --source=app --data-file=/tmp/x -m tests.agent_services_coverage`
  后 `coverage report` 查看 `endpoints/agents.py`。
- 来源: 覆盖率提升任务（2026-08-15）

## test-infra: --source 指定 app.tasks.* 单个模块会使 TestClient 登录请求 500

- 编号: BUG-testinfra-004
- 严重度: test-infra (high，影响指定模块列表的自检命令)
- 模块: `backend/app/tasks/agents.py`、`backend/app/tasks/knowledge.py` 与 coverage 配置
- 现象: `uv run coverage run --source=app.tasks.agents ...`（或任何
  `app.tasks.<module>` 形式的模块级 source）时，TestClient 的任意 HTTP 请求
  （最小复现中连 `/api/v1/auth/login` 都）以
  `RuntimeError: No response returned.` / `anyio.EndOfStream` /
  `asyncio.exceptions.InvalidStateError` 失败；`--source=app`、`--source=app.tasks`
  （包形式）均正常。仓库自带的 `tests/workflows.py` 同样触发，属既有环境问题。
- 预期: 模块名 source 与包名 source 行为一致，测试可运行。
- 复现: `uv run coverage run --source=app.tasks.agents --data-file=/tmp/x \
  -m tests.agent_services_coverage`（或 `-m tests.workflows`）。
- 来源: 覆盖率提升任务（2026-08-15）
