# MVP 任务规划计划书

这个文件是 NexaFlow MVP 的任务总表。后续按单条任务循环推进：实现一条，验证后端，验证前端，通过后再进入下一条。

## 基本假设

- 使用当前仓库结构：后端在 `apps/`，前端在 `web/`。
- 所有核心资源表从第一天开始带 `workspace_id`，代码和 API 使用 `workspace` 命名，不再混用 `tenant`。
- 权限先用 RBAC + 资源级授权，不先做复杂策略引擎。
- 知识库向量能力使用 ChromaDB 持久化索引，PostgreSQL 保留文档、切片、任务、权限和审计等权威数据。
- 工具先接入 Streamable HTTP MCP Server；stdio、OAuth 和内置代码执行先不做。
- 工作流第一版只做固定节点类型，不做拖拽画布。
- Agent MVP 先保证查得准、答得有来源、权限不出错，不先做复杂多 Agent、自主长期规划、过度自动化。
- Open API 先用租户级 API Key 和 OpenAPI 文档，不先做 OAuth、SDK、应用市场。

## 状态约定

| 状态 | 含义 |
| --- | --- |
| `待实现` | 还没开始。 |
| `实现中` | 当前正在做。 |
| `后端已验证` | 后端检查通过，前端还没验证。 |
| `前端已验证` | 前端检查通过，仍可能需要联调验证。 |
| `通过` | 后端和前端都验证通过。 |
| `阻塞` | 需要决策或外部依赖，暂时不能继续。 |

## 执行循环

1. 选择优先级最高的 `待实现` 任务。
2. 只实现这一条任务，不顺手扩展别的功能。
3. 跑最小后端检查，证明后端行为正确。
4. 跑最小前端检查，证明前端行为正确。
5. 后端和前端都通过后，把任务标记为 `通过`。
6. 新想法先放进想法池；只有影响 MVP 闭环时再提升为正式任务。

## Agent MVP 能力边界

| 能力 | MVP 做到什么 | 对应任务 |
| --- | --- | --- |
| 目标理解 | 识别用户任务、约束、优先级，缺信息时先澄清 | MVP-035 |
| 上下文感知 | 读取当前租户、用户、权限和必要产品上下文 | MVP-004、MVP-036 |
| 任务规划 | 把复杂请求拆成可执行步骤，区分自动执行和需要确认的步骤 | MVP-035 |
| 知识库检索 | 判断是否需要知识库，按权限检索，基于证据回答并给来源 | MVP-025、MVP-026、MVP-033 |
| 工具调用 | 调用 Agent 已绑定的 MCP 工具，做参数校验、超时和结果截断 | MVP-041、MVP-043 |
| 执行能力 | 执行低风险动作；高风险动作先生成确认请求 | MVP-037 |
| 反馈与解释 | 返回做了什么、没做什么、为什么，以及可检查结果 | MVP-038 |
| 边界与安全 | 租户隔离、资源权限、敏感信息保护、提示注入基础防护 | MVP-003、MVP-004、MVP-041 |
| 记忆与个性化 | MVP 只使用当前会话上下文，不保存长期记忆 | LATER-009 |
| 协作能力 | 需要用户补充信息或确认时暂停，不假装完成 | MVP-035、MVP-037 |
| 评估与可观测 | 记录 Agent 调用、工具调用、成功/失败状态，支持问题回放 | MVP-034、MVP-042、MVP-060 |

## Agent MVP 执行链路

```text
用户问题
→ 理解意图
→ 读取用户、租户、权限和产品上下文
→ 判断是否需要知识库
→ 查询改写
→ 权限过滤
→ 知识库检索
→ 筛选命中片段
→ 基于证据生成答案
→ 必要时调用已授权工具
→ 高风险动作前请求确认
→ 给出结果、来源和下一步
→ 记录日志
```

## Open API MVP 范围

- 对外提供 OpenAPI schema/API 文档，覆盖 MVP 需要开放的核心接口。
- 外部调用必须使用租户绑定的 API Key，并走同一套 `tenant_id` 和资源权限过滤。
- Open API logger 记录 `request_id`、`tenant_id`、`api_key_id`、method、path、status、耗时和错误。
- logger 不记录明文 API Key，不默认记录敏感 request/response body。

## MVP 任务总表

| ID | 模块 | 功能 | 后端验证 | 前端验证 | 状态 |
| --- | --- | --- | --- | --- | --- |
| MVP-001 | 多租户 | `workspace` 模型和工作空间隔离约定 | migration/model 检查；工作空间 CRUD API；工作空间隔离测试或自检 | 工作空间列表/详情 UI，或 API client smoke check | 通过 |
| MVP-002 | 多租户 | `user`、全局管理员、工作空间成员角色 | 默认管理员初始化；登录/强制改密；工作空间管理员分配 API；权限查询检查 | 登录/改密/用户和角色管理 UI smoke check | 通过 |
| MVP-003 | 多租户 | `resource_permission` | 资源授权/撤销 API；跨租户拒绝访问检查 | 权限编辑 UI，或受保护操作 smoke check | 通过 |
| MVP-004 | 多租户 | 请求工作空间上下文和鉴权守卫 | 受保护接口必须带工作空间上下文；未授权请求被拒绝 | 前端发送工作空间上下文，并能处理未授权状态 | 通过 |
| MVP-010 | 模型管理 | 单层 `model` 注册表 | 模型 CRUD API、租户隔离、字段校验 | 单层模型列表/创建/编辑/删除 UI | 通过 |
| MVP-011 | 模型管理 | 模型凭据和保存前测试 | API Key 加密/脱敏；API URL/model 连通性测试 | 添加/编辑模型时填写 API URL、API Key 并保存前测试 | 通过 |
| MVP-012 | 模型管理 | 统一 `ModelProvider` 适配层 | 通过适配层完成一次 chat completion，使用测试或 stub 验证 | Agent/model 选择器能加载已配置模型 | 通过 |
| MVP-013 | 模型管理 | 模型参数扩展 | 当前不保存上下文、价格、能力字段；需要计费或能力路由时再设计 | 当前 UI 不显示这些字段 | 暂缓 |
| MVP-020 | 知识库 | `knowledge_base` CRUD | CRUD API；租户隔离检查 | 知识库列表/创建/编辑 UI | 通过 |
| MVP-021 | 知识库 | 文档上传和存储元数据 | 上传 API 保存文件元数据和租户归属 | 上传 UI 显示成功/失败和文档状态 | 通过 |
| MVP-022 | 知识库 | 文本解析 | parser 能从 MVP 支持格式中抽取文本 | 文档详情显示解析状态和错误 | 通过 |
| MVP-023 | 知识库 | chunk 切片 | 切片任务生成稳定的 `document_chunk` 记录 | 文档详情显示 chunk 数量和状态 | 通过 |
| MVP-024 | 知识库 | embedding 生成 | embedding 任务为 chunk 写入向量 | 文档状态能显示 embedded/failed | 通过 |
| MVP-025 | 知识库 | 向量检索和权限过滤 | query 返回按 `tenant_id`、知识库、资源权限过滤后的 top chunks | 检索测试 UI 或 Agent 预览能显示命中片段 | 通过 |
| MVP-027 | 知识库 | 文档生命周期和索引维护 | 文档删除清理持久化文件、数据库记录和向量；支持单文档重建 | 文档操作和任务状态可见 | 通过 |
| MVP-026 | 知识库 | 命中片段引用和无证据结果 | 检索结果包含来源文档和 chunk 引用；无命中时返回“知识库无答案”状态 | Chat 答案能显示引用片段，并区分无来源答案 | 待实现 |
| MVP-029 | Agent | 自动规划和受限执行内核 | 单次提问自动生成内部计划并执行；有界工具循环；截断调用不执行；运行归属与权限检查 | 调试区一次提问直接展示结果、来源和可折叠执行详情 | 通过 |
| MVP-030 | Agent | `agent` CRUD 和模型绑定 | Agent CRUD API；名称和模型必填，系统指令使用安全默认值 | Agent 列表和左侧配置 UI | 通过 |
| MVP-031 | Agent | Agent 绑定知识库 | 绑定/解绑 API；租户范围查询检查 | Agent 编辑页能绑定/解绑知识库 | 通过 |
| MVP-032 | Agent | 对话 session 和 message 存储 | session/message API 持久化上下文 | Chat UI 能创建 session 并渲染消息 | 待实现 |
| MVP-033 | Agent | RAG 问答闭环 | Agent 判断是否检索知识库，改写查询，检索 chunk，再把证据发给模型适配层 | 调试 UI 显示答案和引用 | 通过 |
| MVP-034 | Agent | Agent 调用日志 | 每次调用记录模型、prompt、耗时、状态和错误 | Chat/session 详情能看到调用状态或日志入口 | 待实现 |
| MVP-035 | Agent | 目标理解和任务规划 | Agent 返回意图、缺失信息、执行步骤、风险等级；信息不足时不执行 | Chat UI 能展示澄清问题或执行计划 | 待实现 |
| MVP-036 | Agent | 产品上下文读取 | Agent 调用前能读取当前用户、租户、权限和必要业务上下文 | Chat UI 能在当前租户/资源范围内发起 Agent 请求 | 待实现 |
| MVP-037 | Agent | 高风险动作确认 | 高风险工具或事务返回待确认状态，确认前不执行 | Chat UI 能展示确认卡片，并在确认后继续执行 | 待实现 |
| MVP-038 | Agent | 结果反馈协议 | 响应包含已完成、未完成、原因、来源、下一步字段 | Chat UI 能稳定渲染结果、引用、失败原因和下一步 | 待实现 |
| MVP-040 | 工具 | HTTP `tool` 和参数 schema | Tool CRUD API；schema 校验拒绝非法参数 | Tool 表单能编辑 URL、method、headers、schema | 待实现 |
| MVP-041 | 工具 | 工具鉴权、超时和安全限制 | 执行工具时检查租户权限并强制超时 | Tool 测试 UI 能清楚显示超时/鉴权错误 | 待实现 |
| MVP-042 | 工具 | `tool_call_log` | 每次工具调用记录请求摘要、响应状态、耗时和错误 | Tool 详情显示最近调用日志 | 待实现 |
| MVP-043 | 工具 | Agent 绑定并调用 MCP 工具 | 管理员登记 Streamable HTTP MCP Server；Agent 只能调用已绑定工具 | 调试 UI 显示工具调用结果摘要 | 通过 |
| MVP-050 | 工作流 | `workflow`、`workflow_node`、`workflow_edge` CRUD | CRUD API 校验固定节点类型和边关系 | 工作流列表/详情编辑页，不做画布 | 待实现 |
| MVP-051 | 工作流 | 固定节点执行 | 开始、LLM、知识库检索、HTTP 工具、条件判断、结束节点能按序执行 | 工作流运行按钮能发起执行 | 待实现 |
| MVP-052 | 工作流 | `workflow_run` 日志 | run 记录节点状态、输入、输出、耗时和错误 | run 详情显示节点执行时间线 | 待实现 |
| MVP-055 | Open API | Open API Key 和租户鉴权 | API Key 归属租户；缺失、无效、跨租户调用被拒绝 | 开发者设置页能创建、禁用、复制一次性 API Key | 待实现 |
| MVP-056 | Open API | OpenAPI schema/API 文档 | schema 覆盖已开放接口，并声明鉴权、租户上下文、错误格式 | 开发者页面能查看 API 文档入口 | 待实现 |
| MVP-057 | Open API | Open API logger | 每次外部调用写入 request_id、tenant_id、api_key_id、method、path、status、耗时、错误；不记录明文密钥 | 开发者页面能查看最近 API 调用日志 | 待实现 |
| MVP-060 | 运维 | `audit_log` | 敏感新增/修改/删除动作写入审计记录 | 管理端/审计页或最小日志查看入口 | 通过 |
| MVP-061 | 运维 | 用量额度基础 | 模型和工具调用按租户产出用量计数 | 租户/管理 UI 能查看当前用量 | 待实现 |

## 暂缓清单

| ID | 功能 | 什么时候再做 |
| --- | --- | --- |
| LATER-001 | 工作流拖拽画布 | 固定节点工作流已经有实际使用价值，并且用户需要可视化编辑。 |
| LATER-002 | 插件市场 | HTTP 工具不够用，且第三方扩展需求明确。 |
| LATER-003 | 独立向量数据库 | `pgvector` 被实际压测证明成为瓶颈。 |
| LATER-004 | 内置搜索/数据库/代码执行工具 | HTTP 工具闭环稳定，并且每个内置工具都有清晰权限模型。 |
| LATER-005 | 复杂沙箱 | 代码执行或不可信工具执行进入范围。 |
| LATER-006 | 模型微调 | prompt、RAG、模型配置已经无法满足效果要求。 |
| LATER-007 | 计费 | 用量统计可信，价格规则稳定。 |
| LATER-008 | 监控看板 | 日志和审计数据已经存在，并且需要运营视图。 |
| LATER-009 | 长期记忆和个性化管理 | 用户需要跨会话偏好，并且有查看、修改、删除记忆的产品入口。 |
| LATER-010 | 复杂多 Agent | 单 Agent + 工具调用已经不够表达团队流程。 |
| LATER-011 | 混合检索、重排、冲突/过期提示 | 基础向量检索和引用已经跑通，并且检索质量成为主要问题。 |
| LATER-012 | Open API OAuth/SDK/应用市场 | API Key 模式不够用，且第三方集成需求稳定。 |
| LATER-013 | 普通用户自注册 | 第一阶段只允许默认全局管理员创建工作空间和管理员；需要开放外部注册入口时再做。 |
| LATER-014 | Refresh token 和会话管理 | access token 登录链路稳定，并且需要更长登录态、踢下线或多设备管理。 |
| LATER-015 | 邀请流程 | 工作空间管理员需要邀请已有用户或外部邮箱加入工作空间/团队。 |
| LATER-016 | 复杂 RBAC 权限矩阵 | `admin/member` 无法覆盖真实操作权限，需要细粒度角色和权限配置。 |
| LATER-017 | 团队成员管理 | 团队被实际用于权限、协作或资源归属，需要管理团队成员关系。 |

## 单条任务记录模板

开始任务时复制这一块。

## MVP-001/MVP-002/MVP-004：身份与组织地基

- 状态：通过
- 范围：
  - `tenant` 概念改为 `workspace`，代码和 API 使用工作空间命名。
  - 后端按 DRF-like app layout 组织：`identity/`、`workspaces/`、`teams/` 各自维护本模块的 API、模型、schema 和服务。
  - 系统默认全局管理员：初始化用户名、邮箱、姓名和默认密码从 `apps/.env`/环境变量读取；首次登录后必须修改密码。
  - 默认工作空间和默认团队初始化；`admin` 是全局管理员，并作为默认工作空间 `admin`。
  - 工作空间之间数据隔离；工作空间上下文使用路径参数 `/workspaces/{workspace_id}/...`。
  - 全局管理员是平台超管，可以创建和管理工作空间生命周期；不默认穿透工作空间成员、团队、知识库、应用和工具权限。
  - 新工作空间默认不创建团队；工作空间管理员可自行创建团队。
- 明确不做：
  - 普通用户自注册，记录为 `LATER-013`。
  - refresh token 和会话管理，记录为 `LATER-014`。
  - 邀请流程，记录为 `LATER-015`。
  - 复杂 RBAC 权限矩阵，记录为 `LATER-016`。
  - 团队成员管理，记录为 `LATER-017`。
- 后端验证：
  - [x] 命令/检查：`apps/.venv/bin/python -m compileall apps/nexaflow apps/tests apps/main.py`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m tests.smoke_identity_workspace`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `env DATABASE_URL=sqlite+pysqlite:////private/tmp/nexaflow_migration_check_20260704.db JWT_SECRET_KEY=test-secret-for-nexaflow-migration-check .venv/bin/alembic upgrade head`
  - [x] 结果：通过
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run typecheck`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run lint`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run build`
  - [x] 结果：通过
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
- 备注：MVP-003 `resource_permission` 仍保持单独待实现。

## MVP-060：审计日志

- 状态：通过
- 范围：
  - 敏感新增、修改、删除动作写入 `audit_logs`。
  - 审计记录带 `workspace_id`，支持全局审计列表和工作空间内审计列表。
  - 前端系统管理页提供审计日志入口。
- 明确不做：
  - 监控看板，记录为 `LATER-008`。
- 后端验证：
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.identity.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.workspaces.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.teams.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `DATABASE_URL=sqlite+pysqlite:////private/tmp/nexaflow_migration_check_20260705_retry_$$.db JWT_SECRET_KEY=test-secret-for-nexaflow-migration-check .venv/bin/alembic upgrade head`
  - [x] 结果：通过
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run typecheck`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run lint`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run build`
  - [x] 结果：通过
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
- 备注：已覆盖工作空间、团队、用户相关审计动作；Open API logger 仍属于 MVP-057。

## MVP-003/MVP-020：资源授权与知识库 CRUD

- 状态：通过
- 范围：
  - 新增 `resource_permissions`，按 `workspace_id`、资源类型、资源 ID、用户和权限记录资源授权。
  - 第一版资源类型只接入 `knowledge_base`；权限只支持 `view` 和 `edit`。
  - 新增 `knowledge_bases` CRUD，知识库归属工作空间，并记录创建者。
  - 工作空间管理员和知识库创建者可授权/撤销同工作空间用户。
  - 普通成员可创建知识库；被授权用户可查看或编辑对应知识库。
  - 跨工作空间用户不能被授权，跨工作空间请求被拒绝。
  - 前端知识库页接入列表、创建、编辑、归档/恢复、删除和用户授权。
- 明确不做：
  - 团队授权、继承权限、复杂 RBAC 权限矩阵。
  - 文档上传、文本解析、chunk、embedding、向量检索，继续留在 MVP-021 到 MVP-026。
- 后端验证：
  - [x] 命令/检查：`apps/.venv/bin/python -m compileall apps/nexaflow apps/main.py`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge_bases.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.workspaces.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.teams.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.identity.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `DATABASE_URL=sqlite+pysqlite:////private/tmp/nexaflow_migration_check_mvp003_$$.db JWT_SECRET_KEY=test-secret-for-nexaflow-migration-check .venv/bin/alembic upgrade head`
  - [x] 结果：通过
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run typecheck`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run lint`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run build`
  - [x] 结果：通过
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
- 备注：为了让知识库创建者能选择授权对象，工作空间成员列表读取放宽为工作空间成员可读；成员新增、更新、删除仍要求工作空间管理员。

## MVP-010：单层模型注册表

- 状态：通过
- 范围：
  - 新增单层 `model` 注册表，按工作空间管理模型记录；只记录供应商、模型类型、基础模型、API URL、状态和访问凭据。
  - 后端模型管理模块使用 `apps/nexaflow/llm/`；历史 `model_registry_models` 表通过 Alembic 迁移重命名为 `model`。
  - 供应商按参考项目方式作为静态 provider catalog 暴露；不再把供应商作为可持久化资源单独管理。
  - 模型凭据使用 `credential` 结构提交，当前支持 OpenAI-compatible 的 `api_base` 和 `api_key`。
  - API Key 加密保存；响应只返回脱敏 `credential.api_key`、`api_key_hint`，不返回明文或密文。
  - 新增/编辑模型时，OpenAI-compatible 的大语言、向量、重排模型会先发起一次测试调用；测试通过后才保存。
  - 工作空间成员可读取模型注册表；工作空间管理员可新增、更新、删除模型。
  - 前端模型页为单层模型列表和单个添加/编辑模型弹窗；弹窗一次填写供应商、模型类型、基础模型、API URL 和 API Key。
- 明确不做：
  - Agent runner、自主工具调用和确认流，继续留在 MVP-033 到 MVP-038。
- 后端验证：
  - [x] 命令/检查：`apps/.venv/bin/python -m compileall apps/nexaflow apps/main.py`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.llm.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.identity.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.workspaces.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.teams.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `DATABASE_URL=sqlite+pysqlite:////tmp/nexaflow_migration_check_model_single_$$.db JWT_SECRET_KEY=test-secret-for-nexaflow-migration-check MODEL_SECRET_KEY=test-model-secret-for-nexaflow-migration-check .venv/bin/alembic upgrade head`
  - [x] 结果：通过
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run typecheck`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run lint`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run build`
  - [x] 结果：通过
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
- 备注：上下文、价格、能力字段不进入当前模型注册表；供应商 catalog 仍为只读静态配置，不做供应商 CRUD；MVP-011 的密钥遮蔽、必填配置和保存前测试已并入这一轮完成。

## MVP-012：统一 ModelProvider 适配层

- 状态：通过
- 范围：
  - 新增 `apps/nexaflow/llm/runtime.py`，从已注册 `model` 记录解密凭据并构造 OpenAI-compatible 运行时 provider。
  - provider 暴露 `chat`、`embed`、`rerank` 三个最小调用入口。
  - 模型新增/编辑时的保存前测试复用同一个运行时 provider，避免探活逻辑和正式调用逻辑分叉。
- 明确不做：
  - 不新增模型参数扩展字段；MVP-013 继续暂缓。
  - 不做 Agent runner、RAG 编排、工具调用或前端变更。
- 后端验证：
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.llm.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m compileall nexaflow main.py`
  - [x] 结果：通过
- 前端验证：
  - [ ] 检查：无前端变更，未运行前端检查。
  - [ ] 结果：未执行
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
  - 日期：2026-07-06

## MVP-021：文档上传和存储元数据

- 状态：通过
- 范围：
  - 新增 `knowledge_documents` 表，保存工作空间、知识库、文件名、content type、文件大小、存储路径、上传状态和创建者。
  - 新增 `KNOWLEDGE_STORAGE_DIR`，文档文件按工作空间和知识库目录存储。
  - 新增知识库文档列表和上传 API；查看权限可列出文档，编辑权限才可上传。
  - 前端知识库文档 tab 接入上传按钮、文档列表、文件名搜索和上传状态显示。
- 明确不做：
  - 文本解析、chunk、embedding、向量检索和引用展示，继续留在 MVP-022 到 MVP-026。
  - 文档删除、标签管理、向量化按钮和生成问题按钮；文档删除后提升为 MVP-027，向量化后提升为 MVP-024。
- 后端验证：
  - [x] 命令/检查：`apps/.venv/bin/python -m compileall apps/nexaflow apps/main.py`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge.test`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `DATABASE_URL=sqlite+pysqlite:////tmp/nexaflow_migration_check_mvp021_$$.db JWT_SECRET_KEY=test-secret-for-nexaflow-migration-check MODEL_SECRET_KEY=test-model-secret-for-nexaflow-migration-check .venv/bin/alembic upgrade head`
  - [x] 结果：通过
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run typecheck`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run lint`
  - [x] 结果：通过
  - [x] 命令/检查：在 `web/` 下运行 `bun run build`
  - [x] 结果：通过
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
  - 日期：2026-07-06

## MVP-022：文本解析

- 状态：通过
- 范围：
  - 使用禁用插件的 MarkItDown 解析 TXT、Markdown、PDF、DOCX；上传文件先持久化，再由 Celery 任务异步解析。
  - 解析任务维护 `parse_queued`、`parsing`、`parsed`、`parse_failed` 状态和错误信息；队列不可用时保留文档并收敛为 `parse_failed`。
  - 上传向导进入分段步骤后自动触发预览，并轮询未完成任务。
- 明确不做：
  - 复杂版式编辑、OCR 和用户自定义解析器。
- 后端验证：
  - [x] 命令/检查：`apps/.venv/bin/python -m compileall apps/nexaflow apps/main.py`
  - [x] 结果：通过
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge.test`
  - [x] 结果：通过，包含不支持格式的解析失败与重试、队列不可用降级场景。
  - [x] 命令/检查：Celery 任务注册断言 `nexaflow.knowledge.run_task`
  - [x] 结果：通过
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run test`、`bun run typecheck`、`bun run lint`、`bun run build`
  - [x] 结果：全部通过（build 仅保留既有 chunk 大小提示）。
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
  - 日期：2026-08-02

## MVP-023：chunk 切片

- 状态：通过
- 范围：
  - 解析文本按分隔符、字符上限和重叠字符切片，写入稳定的 `document_chunk` 记录。
  - 预览页显示每个分段的字符数和 token 数；后续分段复用前一分段结尾时高亮重复前缀。
  - 兼容保留 `document/split` 和 `document/batch_create` 协议，供现有上传向导提交预览结果。
- 明确不做：
  - 基于语义模型的自适应切片和人工逐字编辑。
- 后端验证：
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge.test`
  - [x] 结果：通过，包含切片、预览和稳定 chunk 记录检查。
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run test`、`bun run typecheck`、`bun run lint`、`bun run build`
  - [x] 结果：全部通过，包含分段编号和重叠高亮测试。
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
  - 日期：2026-08-02

## MVP-024：embedding 生成

- 状态：通过
- 范围：
  - Celery embedding 任务按批次调用已配置的 embedding provider，把向量写入 ChromaDB，并以 PostgreSQL chunk 状态作为权威状态。
  - 支持单文档向量化、批量重建和失败重试；前端显示排队、处理中、已向量化和失败状态。
  - 文档状态使用 `indexed`/`index_failed` 表示规格中的 embedded/failed 等价状态。
- 明确不做：
  - 多向量库路由、向量模型自动切换和在线迁移。
- 后端验证：
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge.test` 和 `.venv/bin/python -m nexaflow.llm.test`
  - [x] 结果：全部通过，包含 provider 调用、失败重试、Chroma 持久化和 Celery 任务进度。
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run test`、`bun run typecheck`、`bun run lint`、`bun run build`
  - [x] 结果：全部通过。
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
  - 日期：2026-08-02

## MVP-025：向量检索和权限过滤

- 状态：通过
- 范围：
  - query 先校验工作空间、知识库和资源级 `view`/`edit` 权限，再从 Chroma over-fetch 并返回过滤后的 top chunks 和来源文档。
  - 检索测试面板显示命中片段、文档来源和距离；无命中返回空结果。
- 明确不做：
  - Chat/Agent 的引用编排和无证据回答协议，继续留在 MVP-026 及后续 Agent 任务。
- 后端验证：
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge.test`
  - [x] 结果：通过，包含跨工作空间拒绝、资源授权和 stale vector 过滤检查。
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run test`、`bun run typecheck`、`bun run lint`、`bun run build`
  - [x] 结果：全部通过。
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
  - 日期：2026-08-02

## MVP-027：文档生命周期和索引维护

- 状态：通过
- 范围：
  - 编辑用户可删除文档；删除同时清理文件、数据库记录和 Chroma 向量，并写入审计日志。
  - 支持单文档索引、知识库批量重建和失败任务重试。
- 明确不做：
  - 标签体系、回收站和版本恢复。
- 后端验证：
  - [x] 命令/检查：在 `apps/` 下运行 `.venv/bin/python -m nexaflow.knowledge.test`
  - [x] 结果：通过，包含并发冲突、删除清理和重建任务检查。
- 前端验证：
  - [x] 命令/检查：在 `web/` 下运行 `bun run test`、`bun run typecheck`、`bun run lint`、`bun run build`
  - [x] 结果：全部通过。
- 联调/手动验证：
  - [ ] 检查：未单独做浏览器手动联调。
  - [ ] 结果：未执行
- 通过决策：
  - [x] 通过
  - [ ] 阻塞
  - 日期：2026-08-02

```markdown
## TASK-ID：任务标题

- 状态：
- 范围：
- 明确不做：
- 后端验证：
  - [ ] 命令/检查：
  - [ ] 结果：
- 前端验证：
  - [ ] 命令/检查：
  - [ ] 结果：
- 联调/手动验证：
  - [ ] 检查：
  - [ ] 结果：
- 通过决策：
  - [ ] 通过
  - [ ] 阻塞
- 备注：
```

## 想法池模板

新想法先放这里。只有它影响 MVP 闭环时，再提升为正式 MVP 任务。

| ID | 想法 | 为什么重要 | 影响模块 | 是否阻塞 MVP | 状态 |
| --- | --- | --- | --- | --- | --- |
| IDEA-001 | 为工作空间和知识库详情增加独立前端路由 | 已实现 `/knowledge/:id` 深路由，刷新和浏览器前进后退可恢复知识库详情；后续只需在新增资源详情时复用该模式。 | 前端路由、知识库、工作空间 | 否 | 通过 |
