# 统一 Tool 系统测试计划

> 状态：待执行。本文件只定义测试范围、步骤与验收标准，不代表任何用例已经执行或通过。

## 1. 测试目标

验证统一 Tool 系统达到可交付状态，重点确认：

1. Python、MCP、builtin Tool 使用同一目录、身份、版本、权限、策略和调用账本。
2. 普通成员可以创建自己的 Python Tool 与公网 MCP Source；默认私有，只能通过 `view` / `use` 授权共享。
3. Tool 能被 Agent、Workflow Tool 节点和 Workflow Agent 节点复用，且版本不会静默漂移。
4. public、API、Workflow、嵌套 Agent 的访问源限制正确，撤权、禁用和策略漂移均 fail closed。
5. 重试、崩溃、取消、超时和重复投递不会造成不可控的外部副作用重放。
6. 工具中心、Agent 配置和 Workflow 三页签节点面板在桌面端与移动端可用，并满足基础无障碍要求。
7. 存量 MCP、Agent、Workflow 和运行记录可以安全迁移，升级与允许的回滚不会破坏历史审计。

## 2. 范围与非范围

### 2.1 本轮范围

- Tool catalog：builtin、Python、MCP。
- Tool owner、workspace/global admin、`view`、`use`、无权限五类访问。
- Tool draft、测试、发布、版本、策略、启停、归档、授权和审计。
- MCP Streamable HTTP、SSE、stdio，以及公网/私网网络策略。
- 统一 Tool Runtime、`tool_invocations`、审批、幂等、租约和不确定结果。
- Agent ToolRef、不可变发布版本、console/public/API Run。
- Workflow Tool 节点、LLM Tool 选择、legacy MCP/Code 兼容。
- Workflow -> published Agent durable child Run、恢复、取消和预算聚合。
- `/app/tools`、Agent 工具选择器、Workflow 添加节点三页签。
- PostgreSQL 数据迁移、Celery worker/Beat、sandbox 和部署拓扑。

### 2.2 本轮非范围

- Skill 的创建和执行；只验证“Skill 暂未开放”的入口状态。
- Agent -> Agent、Agent -> Workflow、Workflow -> Workflow 递归调用。
- Python Tool 的网络、secret、pip、持久文件或自定义依赖。
- Workflow 内的 `each_call` 人工审批；本版应展示但禁止选择，并说明原因。
- 真实生产 MCP、真实第三方写操作和生产数据。

## 3. 优先级与停止规则

| 级别 | 定义 | 处理规则 |
| --- | --- | --- |
| P0 | 跨租户、越权、数据损坏、重复外部写、迁移失败、服务无法启动 | 发现即停止发布，修复后重跑相关域和全量回归 |
| P1 | 核心创建/授权/发布/调用失败，撤权或禁用不生效，父子 Run 无法恢复 | 发布前必须全部关闭 |
| P2 | 非核心错误态、兼容展示、响应式或无障碍缺陷 | 需评估并记录；影响主要流程时升级为 P1 |
| P3 | 文案、轻微视觉或非阻塞体验问题 | 可进入后续修复，但必须留有记录 |

出现以下任一情况应立即停止当前测试批次：

- 测试连接到非明确命名的临时数据库。
- 测试 MCP 指向真实外部写系统。
- sandbox 获得网络、宿主文件或未授权环境变量。
- 同一幂等键产生两次外部写。
- 发现跨 workspace 数据可见或可执行。

## 4. 测试环境

### 4.1 建议拓扑

- PostgreSQL 17 临时数据库，名称包含测试批次号；禁止使用开发共享库或生产库。
- Redis、Celery worker、Celery Beat。
- Qdrant；涉及知识库的 Agent 场景使用独立 collection 前缀。
- sandbox 容器：`network_mode: none`、read-only、cap drop、非 root，socket 只挂给 worker。
- Backend API 与 Frontend 开发/预发布构建。
- 两个 MCP fixture：
  - 公网语义的 Streamable HTTP/SSE fixture，包含只读、外部写、错误和慢响应 Tool。
  - 受信部署场景的 stdio fixture，不访问真实文件或网络。
- 浏览器：Chromium 最新稳定版；桌面 1440×900，移动端 390×844。

### 4.2 测试账号

| 代号 | 身份 | 用途 |
| --- | --- | --- |
| GA | global admin | 全局治理与跨 workspace 防泄露验证 |
| WA | workspace admin | workspace 内治理、授权、Source 管理 |
| A | 普通成员、Tool owner | 创建 Python Tool 与 MCP Source |
| B | 普通成员、`view` | 只读详情、禁止使用和绑定 |
| C | 普通成员、`use` | 使用与绑定、禁止治理 |
| D | 普通成员、无授权 | 404 防泄露验证 |
| E | 另一 workspace 成员 | 跨租户验证 |
| API | Agent API credential | API access source 验证 |
| Public | 匿名用户 | public access source 验证 |

### 4.3 基础测试数据

- builtin：`current_time`。
- Python P1：输入 `{text: string}`，输出 `{length: integer}`，发布 v1。
- Python P2：P1 修改实现后发布 v2，用于版本固定验证。
- Python Invalid：包含 schema、代码、输出、超时和超限错误的草稿。
- MCP R：`read_value`，声明并确认 `external_read + auto`。
- MCP W：`write_value`，`external_write + each_call`。
- MCP U：无可靠 annotations，保持 `unknown + each_call`。
- MCP Drift：同名 Tool 在 refresh 后 definition hash 变化。
- Agent A1：绑定 builtin、Python P1、MCP R。
- Agent A2：绑定 MCP W，用于 console 审批验证。
- Workflow W1：包含 Tool 节点、LLM 节点、Agent 节点。
- Legacy Workflow：包含旧 `mcp`、`code` 和 `mcp_servers` 配置。

## 5. 权限与访问源预期矩阵

### 5.1 Tool 权限

| 身份 | 列表/详情 | 使用/绑定 | 编辑/发布/启停 | 授权 |
| --- | --- | --- | --- | --- |
| owner | 是 | 是 | 是 | 是 |
| workspace/global admin | 是 | 是 | 是 | 是 |
| `use` | 是 | 是 | 否 | 否 |
| `view` | 是 | 否 | 否 | 否 |
| 无权限 | 否，返回 404 | 否 | 否 | 否 |
| 其他 workspace | 否，返回 404 | 否 | 否 | 否 |

### 5.2 运行访问源

| 来源 | 允许条件 | 禁止条件 |
| --- | --- | --- |
| console Agent | live 授权有效；`auto` 自动执行；`each_call` 经当前用户审批 | disabled、archived、unavailable、hash/policy drift |
| public Agent | `approval=auto` 且 effect 为 `pure` / `external_read` | `each_call`、`external_write`、`unknown` |
| Agent API | 同 public | 同 public |
| Workflow Tool | `workflow_callable=true`、`approval=auto`、live use 有效 | `each_call` 或不可调用 |
| Workflow nested Agent | 子 Agent 全部 Tool 为 `auto + pure/external_read`，且 live 授权有效 | 写、未知、审批、递归、depth > 1 |
| Python test | owner/admin 对草稿或当前 Tool 发起，异步 sandbox 执行 | 浏览器/API 线程直接执行代码 |

## 6. 详细测试用例

### 6.1 安装、迁移与回滚

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| MIG-001 | P0 | 空 PostgreSQL 从 base 升级到 head | 所有 Tool、版本、策略、调用、Agent publication、Workflow child 表和约束创建成功 |
| MIG-002 | P0 | 导入含 MCP Server、leaf、policy、Agent binding 的存量 fixture 后升级 | 每个 Server 物化一个 Source；每个 leaf 有稳定 Tool/Version；binding 精确指向版本 |
| MIG-003 | P0 | 存量 MCP Tool 为 disabled 后升级 | Tool 与 policy 保持禁用，不能因 drift 变成可审批 |
| MIG-004 | P1 | 存量 discovery 中 Tool 已消失 | 历史 Tool 保留为 unavailable，不静默删除 binding 或历史调用 |
| MIG-005 | P1 | 历史 MCP Server 已不存在 | 生成 archived tombstone Source/Tool，不伪造连接信息，不创建授权 |
| MIG-006 | P0 | 存量 Agent 已发布且 draft 已变化 | publication v1 使用历史发布快照，未发布 draft 不对外生效 |
| MIG-007 | P0 | 存量非终态 Agent Run 升级 | Run 获得一致的不可变快照；无法安全重建时迁移明确中止 |
| MIG-008 | P0 | 存量 active Run / 旧 worker 未排空时升级 | 部署闸门拒绝继续，不能混跑两代 ledger |
| MIG-009 | P1 | 迁移前 binder 无 grant 且无撤权证据 | 仅为历史精确 binding 回填必要 use；不扩大到其他 Tool |
| MIG-010 | P0 | binder 已显式降为 view 或已 revoke | 不自动恢复 use，运行时 fail closed |
| MIG-011 | P1 | upgrade -> downgrade -> upgrade，期间无新 canonical 写入 | 允许回滚的数据完整、ID 确定性一致 |
| MIG-012 | P0 | upgrade 后存在新 publication、非终态 canonical Run 或 ledger 状态变化再 downgrade | downgrade 中止，不删除可能导致副作用重放的账本 |
| MIG-013 | P1 | 删除 MCP Server 后检查历史 Version/Policy/Binding/Invocation | Source/Tool tombstone；历史链保留且 FK 完整 |
| MIG-014 | P0 | workspace 永久删除 | 先 tombstone/清理相关资源，再删除 workspace；无孤儿和 FK 失败 |
| MIG-015 | P1 | `alembic current`、`heads`、`check` | 只有一个预期 head；无本变更引入的 schema drift |

### 6.2 Tool 目录与授权

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| AUTH-001 | P1 | A 创建 Tool 后 A/B/C/D/E 分别打开列表 | 初始只有 A、admin 和 builtin 可见；其他成员看不到私有 Tool |
| AUTH-002 | P1 | A 授予 B `view` | B 可见列表与脱敏详情，不能看到 Python code/secret，也不能绑定或调用 |
| AUTH-003 | P1 | A 将 B 升级为 `use` | B 可绑定和调用已发布版本，仍不能编辑、发布、启停或授权 |
| AUTH-004 | P1 | A 撤销 B 授权 | 新列表不可见；现存 binding 保留但下次执行 fail closed |
| AUTH-005 | P0 | D 猜测 Tool ID 请求详情、版本、策略、权限、测试结果 | 全部返回 404，不泄露名称、kind、owner 或状态 |
| AUTH-006 | P0 | E 使用另一 workspace 路径访问同 ID | 返回 404；不得出现跨租户 FK 或查询结果 |
| AUTH-007 | P1 | WA/GA 管理 A 的 Tool | 可以治理；审计记录 actor 与动作，不能改写 created_by owner |
| AUTH-008 | P1 | A 给自己或 Tool owner 显式授权 | 返回 422，不创建冗余 grant |
| AUTH-009 | P1 | A 给非 active member、其他 workspace 用户授权 | 返回 404，不泄露用户存在性 |
| AUTH-010 | P1 | B(`view`) 尝试授权、编辑、发布、disable | 返回 403；资源保持不变 |
| AUTH-011 | P1 | C(`use`) 尝试治理 | 返回 403；允许使用但不能管理 |
| AUTH-012 | P1 | 移除 workspace member | 该成员所有 Tool grant 级联删除，审计可追踪 |
| AUTH-013 | P1 | 成员被删除后重新加入 | 不自动恢复此前被撤销的 grant |
| AUTH-014 | P1 | Tool 被当前/历史 Agent publication 或 Run 引用时删除 owner 用户 | 返回 409，保留审计身份或先明确解除引用 |
| AUTH-015 | P2 | 列表 mine/shared/builtin、搜索和分页 | 不重不漏；稳定排序；下一页不会丢失授权 Tool |

### 6.3 Python Tool 生命周期

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| PY-001 | P1 | 普通成员 A 创建 Python Tool | 创建私有 draft；function_name 在 workspace 唯一且稳定 |
| PY-002 | P1 | 提交非 object 根、开放 additionalProperties、远程 `$ref`、组合关键字 | 返回 422，draft 不被错误发布 |
| PY-003 | P1 | schema 超过深度、属性、数组、字符串或字节限制 | 返回 422，错误可理解 |
| PY-004 | P1 | code 超 8 KiB 或非 UTF-8 | 返回 422 |
| PY-005 | P1 | 合法代码读取 `inputs` 并赋值 object `result` | 异步测试成功，data 匹配 output schema |
| PY-006 | P1 | arguments 不匹配动态 input schema | 创建测试请求返回 422，不产生 500 |
| PY-007 | P1 | 未赋值 result、result 非 JSON、primitive、schema 不匹配 | invocation failed，错误码稳定，不发布错误结果 |
| PY-008 | P0 | 代码尝试 network、socket、env secret、workspace file、fork/exec | sandbox 阻断；宿主无副作用 |
| PY-009 | P1 | 无限循环、内存、进程、文件、stdout/stderr、输出超限 | 在各自限额内终止；日志截断；模型和下游不接收 stdout/stderr |
| PY-010 | P1 | sandbox busy | 有界退避后执行或明确失败；不忙等、不无限重试 |
| PY-011 | P1 | 发布 draft 为 v1 | 创建不可变 ToolVersion，current pointer 指向 v1，默认 pure/auto |
| PY-012 | P1 | 修改 draft 发布 v2 | v1 内容不变；current 指向 v2；旧 binding 不静默升级 |
| PY-013 | P1 | disable/enable | disable 后所有未执行调用 fail closed；enable 只恢复有效版本 |
| PY-014 | P1 | archive 后调用 publish/enable | 返回 409，archived 为终态，不可复活原 ID |
| PY-015 | P1 | B/C 查看 Python Tool 详情 | view/use 用户看不到 draft code；owner/admin 可见管理数据 |

### 6.4 MCP Source 与 discovery

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| MCP-001 | P1 | 普通成员创建公网 Streamable HTTP Source | 创建成功并物化 leaf Tools，默认私有 |
| MCP-002 | P1 | 普通成员创建公网 SSE Source | 同上，transport 正确 |
| MCP-003 | P0 | 普通成员创建 stdio、loopback、私网或 file-like endpoint | 拒绝；即使全局允许私网，成员入口仍 fail closed |
| MCP-004 | P1 | WA 创建受信 stdio Source | 在受信部署策略下成功；响应不回显完整 env/command secret |
| MCP-005 | P0 | token、stdio env、working directory 的列表/详情/错误响应 | 均脱敏，不出现在 audit、异常或前端状态中 |
| MCP-006 | P1 | 首次 discovery | 每个 leaf 有独立 Tool/Version/Policy；function_name 唯一 |
| MCP-007 | P1 | Source 重命名与重复 refresh | Tool ID/function_name 不变；definition 未变不新建版本 |
| MCP-008 | P1 | definition hash 改变后 refresh | 生成 v2；旧 version/binding 保留但不可静默执行 |
| MCP-009 | P1 | discovery 中 leaf 消失后 refresh | Tool 标为 unavailable；历史记录保留 |
| MCP-010 | P1 | discovery 整体失败/超时 | 原 catalog 不被半更新；Source 记录可诊断状态 |
| MCP-011 | P1 | function_name 8 位 digest 碰撞 | 稳定扩展 digest，runtime 使用 catalog 名称而非重新计算 |
| MCP-012 | P1 | owner 将当前 hash 标为 auto read-only | policy revision 增加，effect external_read；仅当前 hash 生效 |
| MCP-013 | P1 | 非 owner/use/view 修改 policy | 返回 403 |
| MCP-014 | P1 | 远端 readOnlyHint 缺失但 owner作出只读确认 | 按产品规则保存人工确认；refresh drift 后自动失效 |
| MCP-015 | P1 | Source disable/enable | leaf live availability 同步；disable 优先于历史 snapshot |
| MCP-016 | P1 | Source delete | tombstone 后历史版本/策略/调用保留；同名 Source 可重新创建 |
| MCP-017 | P0 | MCP 返回 prompt injection、超大 payload、非 JSON、错误/超时 | 统一 envelope、大小限制和 untrusted-data 规则生效 |

### 6.5 统一 Runtime 与 ToolInvocation

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| RUN-001 | P0 | workspace/tool/version/snapshot 任一不匹配 | dispatch 前拒绝，不调用 provider |
| RUN-002 | P0 | binder 离开 workspace、被禁用或 use 被撤销 | dispatch 前拒绝 |
| RUN-003 | P1 | Tool/Source disabled、archived、unavailable | dispatch 前拒绝 |
| RUN-004 | P1 | version hash、policy version/hash/revision 漂移 | dispatch 前拒绝，要求重新绑定/发布 |
| RUN-005 | P1 | 输入和输出 schema/大小边界 | 输入在 dispatch 前校验；输出在落账前校验 |
| RUN-006 | P0 | 同一 idempotency key 并发提交 | 只创建/执行一个 invocation，其余复用同一结果 |
| RUN-007 | P1 | queued invocation 重复 Celery delivery | 只有一个 worker claim，attempt/lease 正确 |
| RUN-008 | P1 | worker 在 provider dispatch 前崩溃 | lease 到期后可安全重试 |
| RUN-009 | P0 | external_write/unknown 在 dispatch 后崩溃 | 终态 uncertain，不自动重放 |
| RUN-010 | P1 | pure/external_read 在 dispatch 后崩溃 | 按策略安全重试或失败，不标记外部写不确定性 |
| RUN-011 | P1 | 成功 invocation 后 live revoke，再读同一幂等结果 | 已确认成功结果可重放；不产生第二次 provider 调用 |
| RUN-012 | P1 | pending/approved/running-resume 后 live revoke | claim 前重新检查并拒绝 |
| RUN-013 | P1 | each_call approval、reject、错误 call id、跨 turn call id | 只能审批当前 Run 的精确 invocation；不能错批 |
| RUN-014 | P1 | 长时间等待审批后批准 | 执行 deadline 重新计算；不会立即因旧 deadline 超时 |
| RUN-015 | P1 | Beat 恢复 queued/running/expired invocation | 只恢复符合状态和 lease 的记录，幂等 |
| RUN-016 | P1 | 达到 max_attempts | safe 调用 failed；unsafe running 调用 uncertain |
| RUN-017 | P1 | provider result/error envelope | `ok/data/summary/error/outcome/usage` 字段稳定且有大小上限 |
| RUN-018 | P1 | Agent、Workflow、test 调用同一 Tool | 全部进入 `tool_invocations`，adapter 才区分 provider |
| RUN-019 | P1 | 日志与 API response | 不包含 token、代码、stdio env 或未截断 stdout/stderr |
| RUN-020 | P0 | 取消 Run 与 provider finalize 并发 | 终态单一；unsafe 已派发为 uncertain；迟到 finalize 不能覆盖取消结果 |

### 6.6 Agent 集成

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| AGT-001 | P1 | Agent 工具卡选择 builtin/Python/MCP | 统一保存 `ToolRef[]`，知识库保持独立 |
| AGT-002 | P1 | view-only Tool | picker 不可选；已撤权 binding 保留告警并可移除 |
| AGT-003 | P1 | use Tool 保存 binding | 保存 `bound_by_user_id`；未变化 binding 不因 admin 普通保存而换 binder |
| AGT-004 | P1 | Tool 发布 v2 | Agent draft/已发布版本仍固定 v1，只有显式升级后改变 |
| AGT-005 | P1 | Agent 发布 v1/v2 | publication append-only，current pointer 变化，v1 不可修改 |
| AGT-006 | P1 | public/API 创建 Run | 必须固定 current publication id、配置 hash、ToolSnapshot |
| AGT-007 | P1 | republish 后检查旧 Run | 旧 Run 继续使用旧 publication，不漂移到 v2 |
| AGT-008 | P0 | public/API publication 与 unpublish/republish 并发 | 建 Run 时锁定并验证 current pointer，不创建过期 publication Run |
| AGT-009 | P1 | public/API Agent 含 auto read Tool | 可运行 |
| AGT-010 | P0 | public/API Agent 含 each_call/write/unknown Tool | 整次 Run 在模型调用前拒绝，不能静默过滤危险 Tool |
| AGT-011 | P1 | console Agent 含 each_call Tool | 进入 awaiting approval，批准后继续，拒绝后明确终止/返回工具错误 |
| AGT-012 | P1 | knowledge Tool + canonical Tool 混用 | knowledge 历史与 ToolInvocation 均可在 tool-calls API 查看 |
| AGT-013 | P1 | Tool grant revoke/disable/policy drift | 新调用 fail closed；已成功 ledger 仍可重放 |
| AGT-014 | P1 | Agent Run 重复投递、lease 到期、max attempts | 不重复已确认 Tool；unsafe 未知结果保留 uncertain |
| AGT-015 | P1 | 取消 root Agent Run | active child、节点和 invocation 一并收口；重复取消返回 409 |
| AGT-016 | P0 | 删除有 active Run/unsafe invocation 的 Agent | 返回 409，不级联丢失审计 |
| AGT-017 | P1 | legacy `mcp_tools` request | 仅在兼容边界转换为 ToolRef；新响应不再以 tuple 为身份 |
| AGT-018 | P1 | public/profile/API docs | 从 immutable publication 读取，不读取未发布 draft |

### 6.7 Workflow Tool 与 Agent 节点

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| WF-001 | P1 | 添加节点打开浮层 | 只显示“基础节点 / 工具 / Agent”三个页签 |
| WF-002 | P1 | 基础节点检查 | 不含 Python Code；原基础节点功能不丢失 |
| WF-003 | P1 | 工具页检查 | builtin、Python、MCP、Inline Python 平铺展示，不按种类拆组 |
| WF-004 | P1 | Tool 为 view-only/unavailable/each_call/not callable | 保留展示并禁用，显示准确原因 |
| WF-005 | P1 | 选择可用 Tool | 创建 `tool` 节点并固定 ToolRef，schema-driven arguments 可编辑 |
| WF-006 | P1 | LLM 节点选择 Tool | 只保存 canonical ToolRef，不保存 MCP server tuple |
| WF-007 | P1 | legacy mcp/code/LLM mcp_servers 打开与保存 | 可读取；保存后规范成 canonical Tool，不破坏语义 |
| WF-008 | P1 | Inline Python Code | 通过 builtin inline-python adapter 与 sandbox 执行，不直接走第二条沙箱路径 |
| WF-009 | P1 | Workflow publish/run 后 Tool 发布 v2 | WorkflowVersion 与 Run 继续固定旧 ToolVersion |
| WF-010 | P1 | Workflow Tool 在运行前撤权/disable/drift | Run 在 dispatch 前失败，节点给出通用安全错误 |
| WF-011 | P1 | Agent 页选择 published Agent | 节点同时保存 `agent_id + agent_version_id` |
| WF-012 | P0 | agent_id 与 version 所属 Agent 不一致 | 保存/发布拒绝 |
| WF-013 | P1 | Agent republish v2 后运行已发布 Workflow | child 仍固定 v1 |
| WF-014 | P1 | 创建 child | parent/node 原子进入 awaiting_child；`(parent,node)` 唯一，重复投递只建一个 child |
| WF-015 | P1 | child 成功/失败/取消 | 父被幂等 requeue；节点输出/错误正确映射 |
| WF-016 | P1 | child 已终态但父未入队 | Beat reconciler 修复；重复扫描不重复执行节点 |
| WF-017 | P1 | child 创建提交后派发前崩溃 | 恢复任务派发已有 child，不新建第二个 |
| WF-018 | P0 | depth > 1、Agent->Agent、并行 Agent 节点、超过 4 child | 发布或运行前拒绝 |
| WF-019 | P1 | child 预算 | 继承 root deadline；最多 4 turns/6 tool calls；token 合并回父节点/root |
| WF-020 | P0 | parent cancel/deadline 与 child 完成并发 | parent 不被重新唤醒；child/ledger 正确收口；unsafe 调用 uncertain |

### 6.8 前端、响应式与无障碍

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| UI-001 | P1 | `/app/tools` 首屏 | 直接显示统一工具列表，不再是“新建 MCP”单一页面 |
| UI-002 | P1 | “添加工具”菜单 | Python、MCP 可选；Skill 显示未开放且不可选 |
| UI-003 | P1 | 普通成员打开创建菜单 | 可以创建 Python 和公网 MCP；stdio/private 说明需 admin |
| UI-004 | P1 | loading/error/retry/empty | 页面内状态完整；错误后可重试，不白屏 |
| UI-005 | P1 | Tool 列表分页超过单页 | 所有页可到达，不只加载前 50/200 项 |
| UI-006 | P1 | detail 请求部分失败 | 明确显示失败并允许重试，不能静默遗漏可见 Tool |
| UI-007 | P1 | Python dialog | draft/schema/code/test/publish 状态清楚；不在浏览器执行代码 |
| UI-008 | P1 | permission dialog | 成员搜索、view/use 切换、撤权、loading/error 完整 |
| UI-009 | P1 | Agent 设置 | 保留知识库卡；只有一个统一“工具”卡与共享 picker |
| UI-010 | P1 | picker 搜索/键盘 | 名称、描述、来源可搜索；方向键/Tab/Enter/Escape 可操作，关闭后焦点返回触发器 |
| UI-011 | P1 | 已撤权/不可用 binding | 保留显示，不自动替换版本，提供移除/升级提示 |
| UI-012 | P1 | Workflow 浮层 tab | 正确 role=tablist/tab、aria-selected；键盘切换可用 |
| UI-013 | P1 | 只读 Workflow | 不显示添加节点入口；现有节点仍可查看 |
| UI-014 | P2 | 390×844 工具中心与各 Dialog | 不横向溢出；Dialog 使用可滚动高度；按钮可点击 |
| UI-015 | P2 | Workflow 三 tab 移动端 | tab 可横向滚动，节点列表不截断，画布不跳动 |
| UI-016 | P1 | 三语言切换 | zh-Hans、zh-Hant、en 无缺 key、硬编码中文或布局破坏 |
| UI-017 | P2 | 图标和禁用原因 | 装饰图标 aria-hidden；禁用项有可读原因，不只依赖颜色 |
| UI-018 | P2 | 高对比/200% zoom | 主要流程可用，文本和控件不重叠 |
| UI-019 | P1 | 401/403/404 | 401 交 SessionGate；403/404 不泄露资源信息 |
| UI-020 | P1 | 保存后刷新页面 | ToolRef、Agent version、参数和节点位置完整保持 |

### 6.9 安全专项

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| SEC-001 | P0 | 枚举 Tool/Source/version/invocation ID | 未授权统一 404，无时间/字段侧信道 |
| SEC-002 | P0 | 修改 workspace_id、tool_id、version_id 组合 | tenant composite FK 与应用校验同时阻断 |
| SEC-003 | P0 | 伪造 bound_by_user_id/execution_user_id/access_source | 服务端忽略客户端伪造值，使用可信上下文 |
| SEC-004 | P0 | public/API 尝试审批写 Tool | canonical 路径不可进入公开审批接口 |
| SEC-005 | P0 | MCP DNS rebinding、redirect 到私网、IPv4/IPv6 loopback | 每次连接/redirect 均执行网络策略，普通成员入口拒绝 |
| SEC-006 | P0 | MCP 响应中的 prompt injection | 作为不可信 Tool data，不改变系统策略或泄露上下文 |
| SEC-007 | P0 | Python import socket/subprocess/ctypes、读取 `/proc`/env | sandbox 与解释器限制阻断 |
| SEC-008 | P0 | sandbox socket 从 API 容器访问 | API 无挂载；只有 worker 可访问 |
| SEC-009 | P1 | secret/token 出现在 validation、trace、audit、SSE、前端错误 | 全部脱敏 |
| SEC-010 | P0 | 参数原型污染键、超深 JSON、NaN/Infinity、非字符串 key | schema/JSON 边界拒绝 |
| SEC-011 | P1 | 审批 invocation_id 重放或跨用户使用 | 只允许当前 actor、Run、turn、call 精确匹配 |
| SEC-012 | P0 | 用户删除、成员移除、角色降级 | publication/run/invocation binder 引用被保留或删除被 409 阻断 |
| SEC-013 | P1 | admin 普通保存别人的 Agent | 不接管原 Tool binding binder |
| SEC-014 | P0 | live disabled 与历史 snapshot 冲突 | live kill switch 永远优先 |
| SEC-015 | P1 | policy revision 并发更新 | expected revision/CAS 保证只成功一次，另一请求冲突 |

### 6.10 性能、可观测性与部署

| ID | 级别 | 场景与步骤 | 预期结果 |
| --- | --- | --- | --- |
| OPS-001 | P1 | 1k Tool、多人授权下列表分页 | 查询在数据库层过滤，响应时间与内存无异常增长 |
| OPS-002 | P1 | 同时刷新多个 MCP Source | function_name/version 无冲突，失败互不污染 |
| OPS-003 | P1 | sandbox 单槽下批量 Python 测试 | 有界排队/退避；busy、等待、失败有指标或结构化日志 |
| OPS-004 | P1 | Celery worker/Beat 重启 | queued test、Tool invocation、Agent/Workflow Run 可恢复 |
| OPS-005 | P1 | API 与 worker 使用不同版本 | 部署代际闸门阻断旧 worker claim canonical Run |
| OPS-006 | P1 | Compose 配置检查 | sandbox 无网络、只读、cap drop；socket 仅 worker；依赖健康检查正确 |
| OPS-007 | P1 | host worker 执行 Python Tool | 文档明确不支持或明确失败，不伪装成功 |
| OPS-008 | P1 | Compose worker + sandbox 开发命令 | 能启动必要服务，退出/重启无孤儿容器 |
| OPS-009 | P1 | invocation/Run 日志 | 含 trace/run/invocation/tool version、attempt、duration、outcome；不含敏感值 |
| OPS-010 | P1 | audit 查询 | 创建、发布、授权、撤权、policy、启停、归档均可追踪 actor 与目标 |
| OPS-011 | P2 | 运行取消/失败后的临时资源 | 无残留 lease、测试数据库、MCP fixture、sandbox 子进程或临时容器 |

## 7. 建议执行顺序

1. 环境与安全闸门：确认临时数据库、fixture、sandbox、网络隔离。
2. MIG 全部用例；迁移失败时不继续业务测试。
3. AUTH、PY、MCP；先证明目录、权限和 provider 生命周期正确。
4. RUN；先证明统一账本和幂等，再测 Agent/Workflow。
5. AGT、WF；随后执行 UI 桌面与移动端验收。
6. SEC 与故障注入；最后执行 OPS、覆盖率和构建门禁。
7. 清理所有临时数据库、容器、fixture 进程、Redis key、Qdrant collection 和测试文件。

## 8. 建议自动化命令清单

以下命令仅供测试人员执行，本计划不记录执行结果：

```bash
# Backend 定向与全量
cd backend
uv run python -m compileall app alembic tests
uv run python -m tests.unit
uv run python -m tests.tools
uv run python -m tests.mcp_transports
uv run python -m tests.agents
uv run python -m tests.agent_services_coverage
uv run python -m tests.agent_runtime_coverage
uv run python -m tests.workflows
uv run python -m tests.workflow_node_coverage
uv run python -m tests.workflow_run_coverage
uv run python -m tests.workspace_admin_coverage
uv run python -m tests.infra_unit_coverage
make coverage

# Sandbox
cd ../sandbox
python -m sandbox.tests
./run_coverage.sh

# Frontend
cd ../frontend
bun test --parallel
bun run typecheck
bun run lint
bun run build
./scripts/coverage.sh

# Compose 静态与 sandbox 自检
cd ..
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml config --quiet
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml \
  run --rm --no-deps --entrypoint python sandbox -m sandbox.self_check
```

迁移测试必须显式传入临时 PostgreSQL URL，并在执行前后分别记录：

- `alembic current`
- `alembic heads`
- upgrade 前后关键行数、ID、hash、permission、binding、ledger 状态
- downgrade 被允许或被安全拒绝的原因
- 临时数据库删除确认

## 9. 通过标准

发布候选必须同时满足：

- 所有 P0、P1 用例通过；没有未评估的 P2。
- owner/view/use/none/admin 与跨 workspace 矩阵全部符合预期。
- public/API/Workflow/nested Agent 不可获得写或待审批 Tool。
- 撤权、禁用、definition/policy drift 在 provider dispatch 前生效。
- 重复投递、崩溃恢复、取消和 deadline race 不产生重复外部写。
- 空库和存量 fixture 升级通过；不安全 downgrade 被明确阻断。
- Backend 覆盖率达到仓库门槛 97%+；Frontend 达到 99%+；不得用排除真实业务代码的方式补数字。
- Frontend test、typecheck、lint、build 通过；桌面和 390px 移动端主要流程通过。
- sandbox 隔离和 Compose 拓扑通过检查。
- 无 secret、跨租户数据、孤儿容器、临时数据库或测试进程残留。

## 10. 缺陷与证据模板

每个失败用例至少记录：

- 用例 ID、构建 commit、环境和账号角色。
- 前置数据的 Tool/Version/Policy/AgentVersion/Run ID；敏感字段必须脱敏。
- 最小复现步骤、预期、实际、HTTP 状态和稳定错误码。
- 截图或录屏、相关 trace/run/invocation ID、必要的截断日志。
- 是否涉及外部副作用；若结果未知，立即标记 `outcome=uncertain`，不得重试写操作。
- 严重级别、影响范围、临时规避、修复 commit 和回归用例。

## 11. 清理清单

- 删除本批次临时 PostgreSQL 数据库并再次查询确认不存在。
- 停止并移除测试 MCP fixture、sandbox/worker 临时容器和子进程。
- 删除测试 Redis key、Celery 队列消息和租约。
- 删除测试 Qdrant collections、上传文件和 sandbox socket 临时目录。
- 确认没有 invocation/Run 仍处于测试产生的 `running`、`awaiting_approval` 或 `awaiting_child`。
- 保存脱敏测试报告；不得保存 token、代码 secret、stdio env 或用户密码。
