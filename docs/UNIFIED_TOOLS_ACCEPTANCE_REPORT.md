# Unified Tool 系统验收报告

> 验收入口：[`docs/UNIFIED_TOOLS_TEST_PLAN.md`](./UNIFIED_TOOLS_TEST_PLAN.md)  
> 测试批次：`uat-2617`  
> 最终结论：**FAIL（未通过验收，不可交付）**

## 1. 基线

- 分支：`feat/unified-tools`
- 起始 Commit：`76c2920401ea8eae864a7f2a973d41cb79da1e66`
- 结束 Commit：`d92c145805a7b68a90f1dd4ebff2ef2e9978c5d2`
- 结束 HEAD 相对 `main`：领先 28 个提交
- 测试期间基线变化：
  - 新增提交 `d92c145 feat(coverage): refactor coverage script to use parallel execution with logging`
  - 相对起始 SHA，该提交只修改 `backend/scripts/coverage.sh`，应用源码未变化
  - 该提交将测试开始时未提交的 coverage runner 改动纳入 HEAD；覆盖率结果对应当前 runner
- 起始工作树：
  - `M backend/scripts/coverage.sh`
  - `?? docs/PLUGIN_SYSTEM.md`
  - `?? docs/superpowers/plans/2026-08-16-unified-tool-system.md`
- 测试完成时工作树：仅保留上述两个测试前已有的未跟踪规划文档
- 环境：
  - uv 0.11.3
  - Python 3.11.15
  - Bun 1.3.14
  - Docker 29.4.0
  - 临时 PostgreSQL 17.11，`pg_search` 0.25.2 与 pgvector 可用
- 执行时间：2026-08-17 14:22～17:03（UTC+8，含清理）

## 2. 验收结论

验收未通过，存在以下阻塞：

1. `AUTH-006` 未满足 P0 契约：跨 workspace 访问返回 403，而计划要求统一返回 404。
2. 后端覆盖率为 94%，低于 97% 门禁。
3. 前端全量测试存在 14 个失败与 5 个错误。
4. 前端 lint 和生产构建失败。
5. 前端覆盖率为 86.1%，低于 99% 门禁。
6. 完整桌面/移动浏览器验收按用户要求移交用户自行执行，因此相关 P1 项为 `NOT RUN`，不能计为通过。

因此不满足以下交付条件：

- REQ-001～016 全部 PASS
- 所有 P0/P1 全部 PASS
- 所有自动化门禁全部 PASS
- 浏览器验收完成

## 3. 需求追踪

| 需求 ID | 结果 | 证据摘要 | 缺陷或说明 |
| --- | --- | --- | --- |
| REQ-001 | PASS | 分支、起止 SHA、工作树与基点均已记录；测试期间新增提交仅影响 coverage runner | — |
| REQ-002 | **FAIL** | owner/admin/view/use/none 权限矩阵已执行；跨 workspace 未返回 Tool 数据 | AUTH-006 要求 404，实际为通用 403 |
| REQ-003 | PASS | builtin/Python/MCP 统一通过 ToolSnapshot、adapter 与 `tool_invocations`；观察到 `agent`、`workflow`、`test` 三种 origin | — |
| REQ-004 | PASS | PY-001～015：schema/code 限制、sandbox、测试、发布、版本、禁用、归档均已执行 | — |
| REQ-005 | PASS | MCP-001～017：成员/管理员、HTTP/SSE/stdio、网络策略、policy、脱敏、tombstone 已执行 | — |
| REQ-006 | PASS | AGT-001～018：ToolRef、发布快照、public/API 预检、审批与活动 Run 删除保护已执行 | — |
| REQ-007 | PASS | Workflow Tool、LLM Tool、Inline Python 均进入 canonical runtime | — |
| REQ-008 | **FAIL** | 已验证 WF-011～013 和一次 durable child Run 成功路径 | WF-014～020 的去重、恢复、限制、预算和取消竞态证据不完整 |
| REQ-009 | **NOT RUN** | 已观察工具中心、添加菜单、Python 对话框、Agent 配置卡、Workflow 三页签与三语 | 键盘、焦点、只读、完整错误态、200% zoom、完整移动端验收由用户自验 |
| REQ-010 | PASS | MIG-001～015 在真实 PostgreSQL 17 上完成空库、存量、回滚、闸门与确定性测试 | `alembic check` 存在非本变更新增的 legacy drift |
| REQ-011 | **FAIL** | 已验证 sandbox self-check、Compose 隔离及 worker/Beat 基本启停 | OPS-003～011 尚未形成完整逐项证据 |
| REQ-012 | PASS | public/API 绑定 write/unknown/each_call Tool 时，Run 在模型调用前被拒绝；LLM 调用计数未增加 | — |
| REQ-013 | **FAIL** | 已验证部分幂等、审批、uncertain 与 lease/recover 路径 | RUN-006～016/020、AGT-014～016、WF-014～020 尚未完整闭环 |
| REQ-014 | PASS | Skill 显示“后续开放”且 disabled，不存在可点击死链 | — |
| REQ-015 | **FAIL** | 后端 94%；前端测试/lint/build 失败；前端覆盖率 86.1% | 自动化门禁未达标 |
| REQ-016 | PASS | CLEAN-001～010 已执行；测试资源全部清理 | 测试期间新增外部提交已记录 |

## 4. 自动化门禁

| Gate | 命令或场景 | 退出码 | 结果 |
| --- | --- | --- | --- |
| GATE-001 | `uv run python -m compileall -q app alembic tests` | 0 | PASS |
| GATE-002 | 21 个后端套件 | 全部 0 | PASS |
| GATE-003 | `backend/scripts/coverage.sh` | 0 | **FAIL：94% < 97%** |
| GATE-004 | PostgreSQL 17 Alembic 空库/存量/回滚/重升 | 0 | PASS |
| GATE-005 | sandbox self-check / sandbox coverage | 0 / 0 | PASS，覆盖率 100% |
| GATE-006 | `bun test --parallel` | 1 | **FAIL：702 pass / 14 fail / 5 errors** |
| GATE-007 | typecheck / lint / build | 0 / 1 / 1 | **FAIL** |
| GATE-008 | 前端 coverage | 1 | **FAIL：86.1% < 99%** |
| GATE-009 | 完整浏览器桌面/移动验收 | — | **NOT RUN：用户自验** |

### 4.1 后端定向套件

以下套件均退出码 0：

- `tests.unit`
- `tests.tools`
- `tests.mcp_transports`
- `tests.agents`
- `tests.workflows`
- `tests.agent_access`
- `tests.agent_services_coverage`
- `tests.agent_runtime_coverage`
- `tests.workflow_node_coverage`
- `tests.workflow_run_coverage`
- `tests.workspace_admin_coverage`
- `tests.infra_unit_coverage`
- `tests.test_main`
- `tests.identity`
- `tests.logger`
- `tests.llm`
- `tests.knowledge`
- `tests.workspaces`
- `tests.teams`
- `tests.knowledge_domain_coverage`
- `tests.knowledge_api_coverage`

### 4.2 后端覆盖率

后端合并覆盖率：

```text
TOTAL  16062 statements  1016 missed  94%
```

主要低覆盖文件：

| 文件 | 覆盖率 |
| --- | ---: |
| `app/shareddomain/tools/python_tools.py` | 70% |
| `app/shareddomain/tools/runtime.py` | 83% |
| `app/shareddomain/tools/services.py` | 88% |
| `app/shareddomain/tools/catalog.py` | 91% |
| `app/shareddomain/workflows/resources.py` | 83% |

### 4.3 前端失败

`bun test --parallel`：

```text
702 pass
14 fail
5 errors
716 tests / 45 files
```

失败集中在：

- `frontend/tests/workflow-node-layout.test.ts`：7 个源码级布局/结构断言
- `frontend/tests/tool-picker.test.tsx`：ToolPicker 可用/view-only 过滤场景
- `frontend/tests/tools-page.test.tsx`：零 Tool 的 MCP Source 管理场景
- `frontend/tests/agents-page.test.tsx`：5 个 Workflow 详情分支超时

Lint 与 build 的共同阻塞：

```text
frontend/components/agents/agents-page.tsx:692
react-hooks/set-state-in-effect
void loadToolCatalog()
```

前端覆盖率：

```text
22056 / 25614 lines = 86.1%
```

## 5. PostgreSQL 迁移验收

MIG-001～015 均已执行并通过。

### 5.1 空库与单 head

- 空 PostgreSQL 17 从 base 升级到 `202608170003` 成功
- 创建 47 张 public 表
- `alembic heads`：仅 `202608170003 (head)`
- `alembic current`：`202608170003 (head)`

### 5.2 存量 backfill

存量 fixture 包含：

- active/disabled MCP Server
- read-only / approval-required / disabled policy
- Agent MCP binding
- published Agent snapshot
- terminal Agent/Workflow Run
- missing MCP Server 引用
- revoke audit 证据

升级后验证：

- 每个 MCP Server 对应独立 ToolSource
- leaf Tool/Version/Policy 均被物化
- disabled Server/Tool/Policy 状态保持
- missing Server 形成 archived tombstone，不伪造连接信息
- publication v1 保持历史发布指令，不读取当前 draft
- fallback grant 只在有必要且无 revoke 证据时创建
- binding 精确指向 ToolVersion

### 5.3 升降级闸门

验证通过：

- 非终态 Agent Run 阻止升级 unified Tool execution
- 非终态 Workflow Run 阻止启用 child Run
- 非终态 canonical Run 阻止 downgrade
- child Run lineage 存在时阻止 downgrade
- canonical ToolInvocation 新写入后阻止 downgrade
- 无 canonical 新写入时 `upgrade → downgrade → upgrade` 成功
- 两次升级产生的 Source/Tool/Version/Policy/Binding/Publication/Grant 共 36 项 ID/版本记录完全一致

### 5.4 Schema drift 说明

`alembic check` 发现的 drift 仅涉及：

- `agent_api_credentials`
- `knowledge*`
- `model`
- `system_logs`
- `team_memberships`

未涉及本轮新增的 `tool_*`、publication 或 child Run 表，因此记录为存量 drift，不判定为本变更引入。

## 6. 实时后端验收

测试使用独立临时 PostgreSQL、Redis、Qdrant、sandbox、Celery worker/Beat、MCP fixture 与 LLM fixture；未连接生产资源，未对真实外部系统执行写操作。

### 6.1 权限与防泄露

已验证：

- owner/admin/view/use/none 权限矩阵
- view 用户不可调用或治理
- use 用户可绑定但不可治理
- self/owner 冗余授权返回 422
- 非成员/其他 workspace 用户授权返回 404
- 成员移除后 grant 删除，重新加入不恢复
- owner 用户被 Tool/Agent 引用时删除返回 409
- 未授权 Tool ID 的详情、permission、test 等入口返回 404

失败：

- 其他 workspace 用户访问已知 workspace 路径时，在 workspace context 层返回 403，而计划要求 404。
- 根因位于 `backend/app/application/workspace.py` 的非成员 workspace 访问分支。
- 未观察到 Tool 名称、kind、owner、版本或执行结果泄露。

### 6.2 Python Tool

已验证：

- 创建私有 draft
- object root / closed schema / 无 `$ref` / 无组合关键字
- 深度、属性数、数组、字符串与代码大小限制
- 参数错误返回 422
- sandbox 异步执行成功
- 未设置 result、subprocess、网络、文件写入、无限循环均被阻断或失败
- 宿主无测试文件副作用
- 发布 v1/v2；v1 与 v2 记录并存且内容不变
- disabled 时 dispatch 前失败
- archived 后 publish/enable 返回 409
- view 用户不获得 draft code

### 6.3 MCP

已验证：

- 普通成员可创建公网语义 HTTP/SSE Source
- 普通成员 stdio、loopback 与私网地址被拒绝
- 管理员 stdio Source 创建与 discovery 成功
- token 仅返回 hint，不返回明文或密文
- leaf Tool/Version/Policy 独立物化
- 重复 refresh 保持 ID 与 function name
- definition 变化创建新版本；相同 definition 不重复创建版本
- policy read-only attestation、CAS、非 owner 拒绝
- Source disable/enable 同步 leaf 状态
- delete 形成 Source/Tool tombstone；历史 Version/Policy 保留
- HTTP 实际 fixture 提供 read/write/unknown/error/slow/injection/big tools

### 6.4 Agent / Runtime

已验证：

- Agent 保存 canonical ToolRef
- console auto/pure Agent Run 成功
- public/API Agent 含 write/each_call Tool 时，在模型调用前返回 409
- 拒绝前 LLM 调用计数不增加
- console `each_call` Run 进入 `awaiting_approval`
- approve 后恢复并成功
- reject 后模型接收 Tool 错误并完成
- active Run 存在时删除 Agent 返回 409
- publication profile 从未发布 404 变为发布后 200
- canonical ledger 观察到 `succeeded`、`failed`、`rejected`、`uncertain`、`awaiting_approval`

### 6.5 Workflow

已验证：

- direct Tool 节点运行成功
- Inline Python Code 节点经 sandbox 运行成功
- LLM Tool 节点经 canonical runtime 运行成功
- WorkflowVersion 固定旧 ToolVersion，不静默升级
- Tool 发布 v2 后，新 Run 创建返回 409，按版本漂移 fail closed
- disabled Tool 在 Run 创建预检时返回 409，不到 provider dispatch
- Agent 节点固定 publication version
- durable child Run 成功，父 Workflow 恢复并成功
- child Run 记录 `depth=1`、`root_run_id=parent_run_id`、`parent_node_id`
- Agent ID / publication version 不匹配时保存被拒绝

### 6.6 运行时、安全与运维证据矩阵

| 用例 ID | 自动化位置 | 实时证据（断言摘要） | 结果 | 缺陷或说明 |
| --- | --- | --- | --- | --- |
| RUN-006 | `tests/tools.py` `assert_tool_runtime_is_durable` 2286-2289、2438-2454 | 同 idempotency key 返回同一 invocation；并发双 worker 只有一个 claim，provider 恰好调用 1 次 | PASS | 并发方收到 `ToolInvocationBusy`，不返回存储结果（结果复用仅顺序路径） |
| RUN-007 | `tests/tools.py` 3086-3099、3101-3125、2469-2503 | 单次 Celery delivery 恰一个 worker claim；busy 按 30s countdown 重试；attempt/lease 记账正确 | PASS | — |
| RUN-008 | `tests/tools.py` `assert_tool_runtime_is_durable`（本批次新增 crashed-pure 块） | pure 工具 dispatch 前崩溃（lease 过期、attempts < max）→ lease 到期后安全重试，provider 再次调用 | PASS | 本批次新增回归 |
| RUN-009 | `tests/tools.py` 2551-2590；`tests/agent_runtime_coverage.py` 1966-1988 | external_write dispatch 后崩溃 → 终态 `uncertain`，不自动重放（provider 调用数不变） | PASS | — |
| RUN-010 | `tests/agent_runtime_coverage.py` 1989-1991；`tests/tools.py` 2376-2391 | read_only 传输失败 → error 且 `outcome_uncertain=False`；pure 非法输出 → 确定性失败 | PASS | 未显式断言 pure 崩溃后重试成功（由 RUN-008 覆盖） |
| RUN-011 | `tests/tools.py` 2322-2336；`tests/agent_runtime_coverage.py` 3786-3793、3947-3973 | 成功后 live revoke → 重读重放已确认结果，provider 不再调用 | PASS | — |
| RUN-012 | `tests/tools.py` 2338-2361；`tests/agent_runtime_coverage.py` 3840-3853、3236-3255 | 禁用/策略变更在 claim 前重新检查并拒绝；approval race 只 requeue 不重复执行 | PASS | 未单独构造 running-resume 中 revoke 变体，断言覆盖 disable 与 approved-race 两形态 |
| RUN-013 | `tests/agent_runtime_coverage.py` 2413-2527 | each_call 精确 approve/reject；错误 call id 404；终态/uncertain/rejected 409 | PASS | — |
| RUN-014 | `tests/agent_runtime_coverage.py` 3020-3070 | 长时间等待审批后批准 → deadline 前移重算，不因旧 deadline 立即超时 | PASS | — |
| RUN-015 | `tests/tools.py` 3127-3139、3171-3178、2562-2590 | Beat 对每个 recoverable id 恰派发一次；`app.tools.recover` 已注册进 beat schedule；崩溃且 lease 过期记录可恢复 | PASS | — |
| RUN-016 | `tests/tools.py` 2469-2503、2551-2590 | max_attempts 到达：safe 调用 failed、unsafe running 调用 uncertain，attempts==max 持久化 | PASS | — |
| RUN-020 | `tests/agents.py` `test_cancelling_root_run_cancels_active_children`（本批次新增 late-finalize 块） | cancel 后 running 写调用 → `uncertain`/`agent_run_cancelled`；迟到 worker finalize 不覆盖终态、provider 调用数 0 | PASS | 本批次新增回归 |
| AGT-014 | `tests/agents.py` 1790-1902、1905-2068、3891-3935 | lease 接管、attempts 上限收口、unsafe 未知结果 uncertain、重试 409 且无重复派发（provider 计数不变） | PASS | — |
| AGT-015 | `tests/agents.py` 4213-4344 | cancel root → child、queued/running invocation 一并收口；重复 cancel 409 | PASS | 节点执行行关闭未单独断言，child/ledger 收口已断言 |
| AGT-016 | `tests/agents.py` 4119-4204 | 有 active Run/unsafe invocation 的 Agent 删除返回 409；settle 后 204；audit 保留 create/delete | PASS | — |
| WF-014 | `tests/workflows.py` `test_workflow_agent_node_runs_one_durable_pinned_child`（本批次新增 dedupe 断言） | child `depth=1`、`root_run_id=parent_run_id`、`parent_node_id`；重复投递 `ensure_workflow_agent_child` 返回同一 child，child 总数保持 1 | PASS | 本批次补齐 `(parent,node)` 唯一与重复投递断言 |
| WF-015 | `tests/workflows.py` 同上（reconciler 断言）；2377-2560 | child 成功后父 requeue 一次并最终成功；child failed 时父被幂等 requeue（rowcount 守卫） | PASS | 本批次补齐 child 失败 → 父 requeue 断言 |
| WF-016 | `tests/workflows.py`（本批次新增 reconciler 块） | Beat reconciler 修复 awaiting 父；重复扫描返回空、不重复执行节点 | PASS | 本批次新增回归 |
| WF-017 | `tests/workflows.py`（本批次新增 dedupe 断言） | child 创建提交后恢复路径复用已持久化 child，不新建第二个 | PASS | 本批次新增回归 |
| WF-018 | `tests/workflows.py`（本批次新增嵌套/上限断言） | depth>1/Agent→Agent 嵌套拒绝；每父最多 4 child，第 5 个拒绝 | PASS | 本批次新增回归 |
| WF-019 | `tests/workflows.py`（本批次新增 runtime_limits 断言） | child 继承 root deadline、`max_turns=4`、`max_tool_calls=6`、`max_model_tokens>=1`；child model_usage 合并回父 run | PASS | 本批次新增回归 |
| WF-020 | `tests/workflows.py`（本批次新增 not-re-woken 断言）；`tests/agents.py` 4213-4344 | cancel 后的父不再被终态 child 唤醒；unsafe 调用 uncertain | PASS | 本批次新增回归 |
| SEC-005 | `tests/unit.py` `test_mcp_private_network_policy` 5077-5099；`app/capabilities/mcp/client.py` 153-240；`tests/mcp_transports.py` 84-96；`tests/tools.py` 331-387 | loopback/私网拒绝、`MCP_ALLOW_PRIVATE_NETWORKS=true`+deployment 放行；每次连接 DNS 解析并 pin 目标地址，`follow_redirects=False`；schema/defaults 迁移断言 | PASS | redirect 到私网路径靠 `follow_redirects=False` + pin transport 阻断 |
| SEC-006 | `tests/agent_runtime_coverage.py` `assert_durable_execution_paths`（本批次新增注入块） | 恶意 MCP 输出只以 ToolMessage/untrusted data 进入；两轮 system policy 字节一致且不含注入或 goal；provider 只被合法调用 1 次；ledger 中注入内容仅在 result 数据位，arguments/error 不含 goal | PASS | 本批次新增确定性断言 |
| SEC-010 | `tests/tools.py` `test_tool_boundaries_reject_unsafe_payloads`（本批次新增） | `__proto__`/`constructor`/非字符串 key/超深参数被 closed schema 拒绝；NaN/Infinity 被 `allow_nan=False` 拒绝；schema 深度、引用、unsupported keyword、宽 additionalProperties 被拒绝 | PASS | 本批次新增回归 |
| SEC-011 | `tests/agent_runtime_coverage.py` 2451-2463、2565-2605、3030-3091（本批次新增 ambiguity 块）；`tests/agents.py` `test_agent_run_approval_is_actor_scoped`（本批次新增） | 错误 call id 404；approval run-scoped；跨 turn 同 call id → 409 ambiguous；跨用户 approve → 404（run 隐藏）；历史 invocation id 不能劫持当前审批 | PASS | 本批次补齐跨用户与跨 turn 断言 |
| OPS-003 | `tests/tools.py` 2429-2503、3101-3125 | 单槽 `ToolInvocationBusy`、busy requeue 30s、attempts 耗尽 failed | PASS | busy/等待指标未断言，以结构化日志与计数代替 |
| OPS-004 | `tests/tools.py` 3067-3167、3171-3179；`tests/workflows.py` 2377-2560、1445-1474 | 恢复任务派发、Beat 注册、lease/claim 恢复、child reconciler、worker cancellation 传播 | PASS | 无真实 broker 重启，用 patched claim/lease 证明 |
| OPS-005 | `tests/unit.py` 762+；`tests/agents.py` 1826-1837、2023-2034；`tests/agent_services_coverage.py` 1176-1219、1754-1823 | worker generation fence 阻断旧 worker claim canonical Run | PASS | — |
| OPS-006 | `deploy/docker-compose*.yml` + `sandbox/self_check.py`；Task 9 的 `docker compose config --quiet` 与 sandbox self-check | sandbox `network_mode:none`/`read_only`/`cap_drop:ALL`/`pids_limit`；socket 仅 worker | PASS | 以 Task 9 门禁命令为证据 |
| OPS-007 | `docs/AGENTS.md`、`sandbox/`、Task 9 门禁 | host-only worker 无 sandbox socket，不伪装支持 Python Tool/Workflow 执行 | PASS | 以部署文档与沙箱自检为证据 |
| OPS-008 | `deploy/docker-compose*.yml` + `make worker-compose`；Task 9 门禁 | 独立 Compose 启停无孤儿容器/网络/卷 | PASS | 以 Task 9 门禁命令为证据 |
| OPS-009 | `tests/tools.py` 110-146（ToolInvocation 列契约）；Agent Run events/audit | 记录 trace/run/invocation/tool version、attempt、duration、outcome；不含敏感值 | PASS | 日志内容断言有限，以列契约与事件结构为准 |
| OPS-010 | `tests/tools.py` 1555-1568；`tests/agents.py` 4203-4204 | grant/revoke 可经 audit 查询到 actor 与目标；create/delete 保留 | PASS | publish/policy/enable/archive 经 API 执行但未逐项走 audit 查询 |
| OPS-011 | `tests/workflows.py` 1531-1557；`tests/mcp_transports.py` 179-231；第 10 节 CLEAN-001～010 | 上传对象删除、stdio 超时进程被 reap、无残留 lease/容器/卷/网络 | PASS | — |



Sandbox 验证结果：

- Docker self-check：PASS
- 覆盖率：100%（284/284）
- `network_mode: none`
- `read_only: true`
- `cap_drop: ALL`
- `no-new-privileges:true`
- `pids_limit: 64`
- sandbox socket 仅挂载到 worker
- API 不挂载 sandbox socket
- worker 启动命令包含 `--beat` 与 `celery,agents-legacy,agents-v2` queues

OPS-008 使用独立 Compose project、临时数据目录与无宿主端口映射启动：

- PostgreSQL、Redis、Qdrant、sandbox、worker 均 healthy/ready
- worker 正常启动并包含 Beat
- `down --volumes` 后无孤儿容器、网络或卷
- 未访问或修改既有 `deploy/data`

## 8. 浏览器验收状态

已观察并留证：

- `/app/tools` 统一工具中心
- 我的工具 / 内置工具分组
- Python/MCP 添加入口
- Skill disabled
- Python 对话框基础字段
- Agent 设置中的知识库卡与工具卡
- Workflow 添加节点浮层的三页签及 `tablist` 语义
- 工具页签中的 Inline Python 和 disabled Tool 原因
- 简中、繁中、英文切换

未完成，结果必须记为 `NOT RUN`：

- 完整 loading/error/retry/empty 状态
- 超过单页的真实 UI 分页
- ToolPicker 完整键盘方向键、焦点返回
- 撤权/不可用 binding 的完整交互
- 只读 Workflow
- 完整 390×844 Dialog 与 Workflow 三页签
- 高对比与 200% zoom
- 401/403/404 页面级交互
- 保存刷新后的 UI 状态完整性

以上未完成项目按用户要求移交用户自行验证。

## 9. 缺陷清单

### 9.1 AUTH-006：跨 workspace 返回 403 而非 404

- 级别：P0（按验收计划标注）
- 预期：404
- 实际：403 `Workspace access denied.`
- 数据泄露：未观察到 Tool 数据泄露
- 影响：不符合 API-003 的统一防泄露状态码契约

### 9.2 后端覆盖率不足

- 实际：94%
- 门槛：97%
- 影响：REQ-015 / GATE-003 FAIL

### 9.3 前端自动化失败

- `bun test --parallel`：14 fail / 5 errors
- lint：1 error
- build：同 lint error 失败
- 覆盖率：86.1%
- 影响：REQ-015 / GATE-006～008 FAIL

### 9.4 审计注记

以下为非门禁或待评估项：

- MCP refresh 的 reconcile `ValueError` 未统一映射，罕见分支可能返回 500
- `SEC-006` 已补齐确定性断言（见 6.6 矩阵）：恶意响应只进入 ToolMessage/untrusted data、system policy 两轮字节一致、provider 调用计数 1、ledger 仅 result 数据位携带注入内容；断言位于 `tests/agent_runtime_coverage.py` `assert_durable_execution_paths` 注入块。
- MCP prompt injection 防护主要依赖“untrusted data”系统指令，而非结构化隔离
- ToolPicker 无方向键 roving navigation
- 工具中心使用 200/页循环拉全量，无 UI 分页
- 无全局 `error.tsx` / `not-found.tsx`
- sandbox 无 import 层拦截，依赖容器与进程边界阻断副作用

## 10. 清理结果

CLEAN-001～010 已完成：

| 清理项 | 结果 | 证据摘要 |
| --- | --- | --- |
| CLEAN-001 临时 PostgreSQL | PASS | `uat-2617-pg` 与数据卷已删除 |
| CLEAN-002 fixture/sandbox/worker | PASS | `uat-2617-*` 5 个容器已删除；测试进程已停止 |
| CLEAN-003 Redis | PASS | 临时 Redis 容器与数据已删除 |
| CLEAN-004 Qdrant/文件/socket | PASS | 临时 Qdrant、sandbox socket 与测试文件已删除 |
| CLEAN-005 非终态 Run/Invocation | PASS | 临时 DB 随容器删除，无状态残留 |
| CLEAN-006 端口/进程/孤儿 | PASS | 测试端口全部释放；无 uat 容器、卷、网络 |
| CLEAN-007 Docker 前后对比 | PASS | 本批次 5 容器 + 3 卷从有到无 |
| CLEAN-008 Git 状态 | PASS（有基线变化） | 测试期间 `d92c145` 仅提交测试前已有 runner 改动；测试未编辑应用源码 |
| CLEAN-009 既有资源 | PASS（后续状态变化已记录） | 既有容器、卷、网络未删除或重建 |
| CLEAN-010 脱敏 | PASS | 证据目录已删除含合成凭据的 runner/fixture/解析配置，并复扫无密码、token、JWT |

清理检查点完成后，最终复核发现预存 `nexaflow-*` 五个容器已变为 Exited，同时旧 `postgres`/`redis` 容器被启动。`nexaflow-*` 容器创建时间、卷和网络均未改变，说明未被本批次删除或重建。由于这是清理后发生的外部环境变化，本次未自动恢复或切换容器。

## 11. 签署

- 所有 REQ-001～016 是否 PASS：**否**
- 所有 P0/P1 是否 PASS：**否**
- 覆盖率门槛是否满足：**否**
- 完整浏览器验收是否完成：**否**
- 临时资源是否全部清理：**是**
- 是否可交付：**否**

## 12. 复验入口

修复后至少重跑：

1. AUTH-006、API-003、SEC-001/002 的 404 防泄露回归。
2. `backend/scripts/coverage.sh`，总覆盖率必须达到 97% 以上。
3. `bun test --parallel`，全部测试必须通过。
4. `bun run typecheck`、`bun run lint`、`bun run build`。
5. `frontend/scripts/coverage.sh`，总覆盖率必须达到 99% 以上。
6. 用户完成 GATE-009/UI-001～020 的剩余桌面、移动、键盘、焦点、缩放和错误态验收。
7. 修复影响到 Tool Runtime、迁移、sandbox 或 Compose 时，重跑对应域以及 MIG/GATE-004、GATE-005、OPS-006/008。
8. 再次执行 CLEAN-001～010，并保存新的前后对比证据。
