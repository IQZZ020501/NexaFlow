# 测试与 BUG 记录

> 由全项目覆盖率测试任务（分支 `test/coverage-95`，2026-08-15）产生。
> 测试过程中发现的 BUG 只记录、不修改，后续统一修复。每个子任务的详细记录在
> `docs/buglog/<agent>.md`，本文件为主汇总。

## 记录格式

```md
- 编号: BUG-<area>-NNN
- 严重度: critical / high / medium / low / test-infra
- 模块: <文件或端点>
- 现象: <实际行为>
- 预期: <期望行为>
- 复现: <最小复现步骤或证据>
- 来源: <测试套件>
```

## 严重度分布

- medium: 5（KB 重命名 500、模型凭据解密 500、公开对话加载卡死、API 非 JSON 错误体、重复批准幂等）
- low: 12（死代码/不可达分支 6、前端交互/显示 4、弃用常量 2）
- test-infra: 7（并发存储目录冲突、coverage 追踪伪影 ×4、--source 崩溃、MarkItDown 偶发）

## 产品 BUG（medium）

### medium: 知识库重命名冲突返回 500 而非 409

- 编号: BUG-knowledge-001（KnowledgeDomainCoverage 独立复现为 BUG-kdc-001）
- 严重度: medium
- 模块: `backend/app/shareddomain/knowledge/kb.py::update_knowledge_base`
- 现象: `PATCH .../knowledge-bases/{id}` 将 name 改为工作区内已存在的名称时返回
  500（`sqlalchemy.exc.IntegrityError` 冒泡），而非创建路径的 409。
  `save_knowledge_base()` 内部 flush 在 `try/except IntegrityError`（只包住
  `db.commit()`）之外执行，唯一约束冲突在 flush 时抛出。
- 预期: 与创建路径一致返回 `409 Conflict`（"Knowledge base name already exists."）。
- 复现: 创建知识库 A、B；以 B 的 owner 身份 `PATCH B {name: A.name}`。
- 来源: tests.knowledge_api_coverage / tests.knowledge_domain_coverage

### medium: 模型凭据解密失败时 Fernet InvalidToken 逃逸为 500

- 编号: BUG-infraunit-001
- 严重度: medium
- 模块: `app/capabilities/llm/runtime.py:624-625`、`registry.py:150-153`、
  `credentials.py:33-47`
- 现象: 损坏/密钥不匹配的密文触发 `cryptography.fernet.InvalidToken`
  （MRO 不含 ValueError），`except (ValueError, JSONDecodeError)` 捕不到；
  `stored_model_credentials` 无任何捕获 → 裸 `InvalidToken`（HTTP 500），
  而非预期的 `ModelProviderError("Stored model credentials are invalid.")`（400）。
- 预期: 所有解密失败归一化为 `ModelProviderError`（在 `decrypt_credential_secrets`
  内包装或把 `InvalidToken` 加入捕获元组）。
- 复现: `_registered_model_credentials(RegisteredModel(..., api_key_ciphertext="garbage-not-a-token", ...), settings(), "LLM")`
- 来源: tests.infra_unit_coverage

### medium: 公开对话点击当前已激活会话后加载指示器永久卡住

- 编号: BUG-frontend-001
- 严重度: medium
- 模块: `frontend/components/agents/public-agent-chat.tsx`（`selectConversation`）
- 现象: 点击"当前已激活"的会话时 `setIsRunsLoading(true)` 但
  `setActiveConversationId` 传入相同值 → effect 依赖不变不重跑 →
  `isRunsLoading` 永不复位，消息区永久 spinner。
- 预期: 点击当前会话不应进入加载态（或 effect 兜底复位）。
- 复现: 渲染含历史会话的 `PublicAgentChat`，点击带 `aria-current="page"` 的同一会话。
- 来源: tests/public-agent-chat.test.tsx

### medium: request() 对非 JSON 错误响应体抛 JSON.parse 异常吞掉错误消息

- 编号: BUG-frontend-001（FrontendSystemTools）
- 严重度: medium
- 模块: `frontend/lib/api-client.ts::request`
- 现象: 后端返回非 JSON 错误体（如 `500 text/plain`）时 `JSON.parse` 抛
  `SyntaxError` 而非 `ApiError`，`getErrorMessage` 拿不到后端消息。
- 预期: 非 JSON 错误体走 `errorMessage(payload, statusText)` 兜底并抛 `ApiError`
  （与 `requestBlob` 一致）。
- 复现: `new Response("boom text", { status: 500 })` 时 `listTeams` 抛 SyntaxError。
- 来源: tests/system-tools.test.tsx

### medium: 终态 run 上重复工具批准静默返回而非 409

- 编号: BUG-runtime-004
- 严重度: medium
- 模块: `backend/app/application/agent_runs.py:286-291`
- 现象: run 已进入终态后，同一用户重复 approve 同一工具调用返回 200 与 run 实体
  （静默），而终态 call 的同类重复会被 409 拒绝——行为不一致。
- 预期: 终态 run 上的重复批准返回 409，或明确幂等语义。
- 复现: approve → run 执行完成（succeeded）→ 同一用户再次 approve 同一 call。
- 来源: tests.agent_runtime_coverage

## 产品 BUG（low）

### low: usage 归一化丢弃非整数 token 计数

- 编号: BUG-runtime-003
- 模块: `backend/app/shareddomain/agents/runtime/usage.py:27-36`（`_number`）
- 现象: 非整数 float（如 3.5）返回 None → 被当作 0/丢弃；小数 token 上报会少记。
- 预期: 四舍五入/向上取整后计入。
- 来源: tests.agent_runtime_coverage

### low: 文档分页页脚在页容量覆盖全部条目后消失

- 编号: BUG-kbp-001
- 模块: `frontend/components/knowledge/knowledge-base-page.tsx`
- 现象: 文档总数 ≤ 每页条数时分页页脚（含"每页 N 条"下拉）整体消失，无法改回。
- 预期: 至少保留"每页 N 条"选择器。
- 来源: tests/knowledge-page.test.tsx

### low: 分段中文档路由恢复后不轮询，界面停在无限 spinner

- 编号: BUG-frontend-002
- 模块: `frontend/components/knowledge/knowledge-upload-flow.tsx`
- 现象: URL 恢复分段预览时 `parse_queued`/`parsing` 状态文档不触发轮询，
  `isPreviewRunning` 为 true，预览区一直 spinner，"生成分段预览"按钮被禁用。
- 预期: 恢复 parsing 文档时应继续轮询任务或至少不阻塞按钮。
- 来源: tests/knowledge-upload.test.tsx

### low: 向量化进度文本依赖任务列表加载时机，首屏最多延迟 3 秒

- 编号: BUG-kbp-002
- 模块: `frontend/components/knowledge/knowledge-base-page.tsx`
- 现象: indexing 文档首次进入"文档"页签只显示普通"向量化中"；切"任务"页签或 3 秒
  轮询后才显示 "2/5" 进度。
- 预期: 尽快随文档列表加载任务并展示进度。
- 来源: tests/knowledge-page.test.tsx

### low: 弃用常量 HTTP_422_UNPROCESSABLE_ENTITY

- 编号: BUG-low-001 / BUG-low-003
- 模块: `backend/app/application/workspace.py:326`、
  `backend/app/shareddomain/workflows/services.py:135`
- 现象: `StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is
  deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.`
- 预期: 使用非弃用常量。
- 来源: tests.workspaces / tests.workflow_run_coverage

### low: 测试 JWT 密钥不足 32 字节触发 InsecureKeyLengthWarning

- 编号: BUG-low-002
- 模块: `backend/tests/support.py`（`JWT_SECRET_KEY` 31 字节）
- 现象: 所有后端套件输出 `InsecureKeyLengthWarning` 噪音。
- 预期: 测试密钥 ≥32 字节。
- 来源: 全部后端套件

### low: 死代码/不可达分支（建议清理）

- BUG-agentaccess-001: `agent_access.py:721-722` 凭证 workspace 不匹配分支不可达
  （凭证创建固定用 agent.workspace_id，且无跨空间迁移功能）。
- BUG-agentaccess-002: `agent_access.py:1112-1113` 监控日期过滤 continue 恒假。
- BUG-runtime-001: `agent_memory.py:266` 压缩源选择回退分支不可达。
- BUG-runtime-002: `agent_executor.py:743-744` record_event 非 process 事件分支不可达。
- BUG-kdc-002(部分): `task_runner.py:483` "Unsupported knowledge task type" 被
  DB CHECK `ck_knowledge_tasks_task_type` 挡住，不可达。
- BUG-low-004: `workflow_runs.py:250-254` console 上传 id 防御分支无 API 触发路径。
- BUG-frontend-003: `knowledge-upload-flow.tsx` segment 恢复 `.catch` 为死代码
  （uploadPendingFiles 用 allSettled + 内部 reportError，从不 reject）。

## test-infra 记录

### high: 套件共享知识库存储目录，并行运行互相删除文件

- 编号: BUG-testinfra-002（KnowledgeApiCoverage）
- 模块: `backend/tests/support.py`（`KNOWLEDGE_STORAGE_DIR` 固定
  `/tmp/app-test-knowledge-storage`，每个 `test_client()` rmtree 整个目录）
- 现象: 并行套件随机报 `KnowledgePipelineError: Document file is missing.`。
- 处置: **已修复**——`support.py` 尊重预置的 `KNOWLEDGE_STORAGE_DIR`，
  `scripts/coverage.sh` 按套件隔离存储目录。
- 来源: tests.knowledge_api_coverage

### medium: coverage.py 在 TestClient portal 线程上不记录 await 之后的 raise/后续行

- 编号: BUG-testinfra-002/003/004（AgentAccess、WorkflowNode、AgentServices、WorkflowRun 各自复现）
- 模块: coverage 7.15.4 + starlette TestClient（anyio portal 线程）
- 现象: 协程体内第一个 await 之后的 `raise`（及其后某些行）在 HTTP 路径下不产生
  行事件；主线程 `asyncio.run` 直接调用同一函数则完整记录。最小复现：404 返回
  但 `raise HTTPException` 行仍报缺失；`--timid` 同样丢失。影响约 200+ 行
  （如 `workspace.py`、`identity.py` 中大量 `raise HTTPException`），这些行已由
  套件断言证实执行（响应码匹配）。
- 预期: 已执行行应被统计。
- 处置: 各套件已用主线程直接调用补测可覆盖部分；剩余为纯伪影，合并时按已执行
  评估（后端总体 97%，含伪影后真实值更高）。
- 来源: 多个后端覆盖率套件

### low: coverage --source 模块列表 ≥5 个时 numpy 导入崩溃

- 编号: BUG-testinfra-002（AgentRuntimeCoverage）
- 现象: `--source=<5+ 模块>` 时 `ImportError: cannot load module more than once
  per process`（numpy，经 qdrant_client 导入链）；1-4 个模块稳定。
- 处置: 不带 --source 运行 + `report --include` 过滤（套件自检用）。
- 来源: tests.agent_runtime_coverage

### low: coverage --source=app.tasks.<模块> 使 TestClient 请求全部 500

- 编号: BUG-testinfra-004（AgentServicesCoverage）
- 现象: 模块级 `app.tasks.*` source 时任意 HTTP 请求
  `RuntimeError: No response returned` / `anyio.EndOfStream`；`app.tasks` 包形式正常。
- 来源: tests.agent_services_coverage

### low: starlette BaseHTTPMiddleware 在 coverage 下 POST 偶发 `No response returned`

- 编号: BUG-testinfra-002（WorkflowRunCoverage）
- 现象: coverage 开启时带 body 的 POST 约半数抛 `RuntimeError: No response
  returned`（GET 稳定）；不开启 coverage 稳定。
- 处置（仅测试侧）: 套件将 BaseHTTPMiddleware 替换为纯 ASGI 直通。
- 来源: tests.workflow_run_coverage

### low: eager 执行 heartbeat 的 CancelledError 在 coverage 下逃逸 suppress

- 编号: BUG-testinfra-003（WorkflowRunCoverage）
- 处置（仅测试侧）: 套件将 lease heartbeat 替换为 no-op + `except BaseException` 兜底。
- 来源: tests.workflow_run_coverage

### low: MarkItDown 文档抽取在 coverage 下偶发失败（不可复现）

- 编号: BUG-testinfra-003（WorkflowNodeCoverage）
- 现象: coverage 下首次运行 document-extract 图返回 422 "could not be
  extracted"；单独复现与重跑均成功。
- 来源: tests.workflow_node_coverage

## 其他观察（非缺陷）

- BUG-knowledge-002: 同一知识库允许同名文档（无唯一约束、无冲突分支），产品未设计
  该约束，测试按允许处理。
- BUG-kdc-002(观察): `task_runner.py:426-427` naive vs aware datetime 比较在
  sqlite 下对 running 任务抛 TypeError；Postgres（timestamptz）返回 aware，生产不受影响。
- mcp_transports 套件在 11 路并行负载下偶发 "MCP test server did not start"
  （CPU 争抢超时），单独运行稳定——见 `BUG-testinfra-001` 早期记录。
- 前端测量口径：bun 的 lcov 在 `--parallel`（多 worker 合并）下对组件可执行行数
  （LF）统计不稳定（同一文件单文件运行 LF=2161、全量合并 LF=2476，含不可执行行
  的 0 命中记录），并集口径会低估覆盖率。权威口径为
  `bun test --isolate --coverage`（串行 + 每文件独立全局对象，单进程一致 LF）：
  前端总行覆盖率 98.31%，与各组件单文件测量（95-100%）一致。
  `frontend/scripts/coverage.sh` 已采用该口径。
- RTL `waitFor` 默认 1s 超时在并行 worker 共享 CPU 下造成偶发失败；
  `tests/setup.ts` 已将 `asyncUtilTimeout` 提到 5000ms（测试基建，非产品缺陷）。
