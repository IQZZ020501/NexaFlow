# WorkflowRunCoverage 子任务 BUG 记录

> 来源: `backend/tests/workflow_run_coverage.py`（工作流运行编排域覆盖率套件，2026-08-15）。
> 本文件只记录发现，不修改产品代码。

### test-infra: starlette 1.3.1 BaseHTTPMiddleware 在 coverage 下 POST 请求偶发 `No response returned`

- 编号: BUG-testinfra-002
- 严重度: test-infra (medium)
- 模块: `starlette.middleware.base.BaseHTTPMiddleware`（被 `app/main.py` 的
  `record_unhandled_errors` / `prevent_api_caching` 使用）+ `coverage run --source=...`
- 现象: 带 body 的 POST 请求（如 `/api/v1/auth/login`）在 coverage 追踪开启时
  约半数概率抛 `RuntimeError: No response returned`（EndOfStream + anyio
  task group 取消竞态），GET 请求稳定；不开启 coverage 时稳定通过。
- 预期: 请求应稳定返回 200/4xx，与是否开启 coverage 无关。
- 复现: `uv run coverage run --source=app.application.workflow_runs,... -m tests.workflow_run_coverage`
  下任意 POST 请求（连续运行多次可稳定复现）。
- 规避（仅测试侧）: 套件将 BaseHTTPMiddleware 替换为纯 ASGI 直通中间件
  （这两个中间件只设置 Cache-Control 头与错误日志，测试不依赖其行为）。
- 来源: workflow_run_coverage.py

### test-infra: 工作流 eager 执行的 lease heartbeat 取消在 coverage 下逃逸 `suppress(CancelledError)`

- 编号: BUG-testinfra-003
- 严重度: test-infra (medium)
- 模块: `app/application/workflow_executor.py::run_durable_workflow_run`
  （`finally: heartbeat.cancel(); with suppress(CancelledError): await heartbeat`）
- 现象: eager 执行已完成并落库（`_execute_claimed_workflow_run` 返回
  `finished`）后，finally 中 `await heartbeat` 抛出的 CancelledError 在
  coverage 追踪函数激活时逃逸 `suppress`，连 `except asyncio.CancelledError`
  都捕获不到（只能捕获 `BaseException`），导致创建/恢复运行请求整体失败；
  不开启 coverage 时 suppress 正常。
- 预期: heartbeat 清理产生的 CancelledError 应始终被抑制。
- 复现: `uv run coverage run --source=app.application.workflow_runs,... -m tests.workflow_run_coverage`
  中任意包含 eager 工作流执行的 POST /runs。
- 规避（仅测试侧）: 套件将 lease heartbeat 替换为 no-op（测试运行时长远小于
  lease 周期，续租无意义），并在 `run_durable_workflow_run` 外层以
  `except BaseException` 兜底返回 `finished`。
- 来源: workflow_run_coverage.py

### test-infra: coverage 在 TestClient portal 线程上不记录 `await` 之后的代码行

- 编号: BUG-testinfra-004
- 严重度: test-infra (low)
- 模块: 任意经 `starlette.testclient` 的请求处理协程（`app/application/workflow_runs.py`
  的 `get_workflow_run`、`list_workflow_runs`、`resume_workflow_form` 成功分支、
  `app/api/v1/endpoints/workflows.py` 流端点 307/318 行等）
- 现象: 同一批断言证明代码路径已执行（响应 200/断言通过），但 coverage
  数据缺少每个协程第一个 `await` 之后的行；直接 `asyncio.run(...)` 调用同一
  函数则记录完整。`app/shareddomain/workflows/uploads.py:48-49`
  （失败分支的 `await db.commit(); raise`）同样执行但未记录。
- 预期: 已执行的行应被覆盖统计。
- 复现: 经 TestClient 调用含多个 await 的端点后查看 `coverage report`。
- 规避（仅测试侧）: 对关键分支改用直接函数调用（`asyncio.run` + 真实会话）
  补测，套件对目标模块达到 95% 总体覆盖。
- 来源: workflow_run_coverage.py

### low: 弃用常量 HTTP_422_UNPROCESSABLE_ENTITY

- 编号: BUG-low-003
- 严重度: low
- 模块: `app/shareddomain/workflows/services.py:135`
  （`validate_workflow_resources` 的 reranker 校验）
- 现象: 运行本套件输出 `StarletteDeprecationWarning:
  'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use
  'HTTP_422_UNPROCESSABLE_CONTENT' instead.`
- 预期: 使用非弃用常量 `HTTP_422_UNPROCESSABLE_CONTENT`。
- 复现: `uv run python -m tests.workflow_run_coverage`
- 来源: workflow_run_coverage.py

### low: 外部运行“console 上传 id”分支为不可达防御代码

- 编号: BUG-low-004
- 严重度: low
- 模块: `app/application/workflow_runs.py:250-254`
- 现象: `create_workflow_run` 中 `access_source != "console" and payload.file_ids`
  分支只能通过直接函数调用到达；两个外部入口
  （`create_external_workflow_run` public/api）均自行解析文件且不向
  `WorkflowRunCreateRequest` 传 `file_ids`。
- 预期: 保留为防御分支即可（无错误行为），仅提示该分支无 API 触发路径。
- 复现: 静态分析 + 直接调用单元测试覆盖该分支。
- 来源: workflow_run_coverage.py
