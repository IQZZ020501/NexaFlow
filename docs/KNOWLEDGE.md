# KNOWLEDGE 模块（backend/app 知识域：domain/knowledge + application/knowledge + tasks/knowledge + api/v1/knowledge + entities/schemas/knowledge + tests/knowledge）

## 职责

知识库业务领域：知识库/文档/分块/任务的状态机编排（解析 → 规范化全文 → 分块 → embedding → 向量入库），支持普通文档与显式 QA 表导入、平铺分段与按 Markdown 章节生成 Parent + Child 的智能分段；仅 Child 进入文本与向量检索索引。检索统一经过向量、PostgreSQL `pg_search` BM25、显式文档引用一跳扩展、可选重排和可选 Evidence Graph，多跳图谱结果始终回指证据。模块同时负责任务租约与失败重试、文档生命周期、知识库删除后的持久化外部存储清理。Celery 任务入口在 `backend/app/tasks/knowledge/jobs.py`。

## 权限语义

- 知识库列表按用户隔离：只列出自己创建的与被 `ResourcePermission` 授权的知识库（响应 `permission` 字段为 view/edit/none），工作空间管理员与系统管理员不例外；跨租户或未授权访问一律按未找到/禁止处理。
- 知识库归档后只读：写操作（上传/解析/索引/重建/改名/授权管理/删除）返回 403，仅创建者可恢复。
- owner（`created_by_user_id`）可通过 `PUT /knowledge-bases/{id}/owner` 转移给活动工作区成员；转移后原 owner 不再隐式享有 edit。

## 分层关系

```text
api/v1/knowledge（routes/lifecycle/retrieval/evaluation/graph 路由）
  → application/knowledge（用例编排：documents、retrieval、evaluation/runner、graph/{service,build,query,maintenance}）
    → domain/knowledge（bases、documents、evaluation、storage、tasks、graph 领域规则；service.py 门面）
      → ports（llm/parsing/vector_store 等稳定契约入口）
      → adapters（rag 检索与向量、parsing 管线与 QA 导入、llm 运行时与 provider）
      → infra/db/repositories/knowledge + sql/knowledge（PostgreSQL 权威读写）
    → tasks/knowledge/jobs.py（Celery 包装、恢复与重试；app.knowledge.* / app.uploads.*）
```

仓储层把 ORM 行经 `to_entity` 映射回 `entities/knowledge` 的 dataclass 实体后供领域层消费。

## 文档导入流程

- 附件上传 `POST /knowledge-bases/{kb_id}/attachments` 只持久化文件（对象存储 adapter 见 `backend/app/infra/storage/object_storage.py`），返回 attachment。
- 文档创建 `POST /documents` 接收 `attachment_ids`、`staged` 和显式 `import_mode`（`document`/`qa`）；事务内消费附件并生成 staged 文档。解析/向量化一律走 Celery 任务（`POST /parse`、`POST /index`）。
- QA 模式只接受 UTF-8 CSV 或 XLSX，表头支持 `question/问题`、`answer/答案` 和可选 `source/来源`。每行生成一个 `kind=qa` Child，答案作为返回正文，`question + answer` 作为检索文本；最多 5000 行，问题/答案分别限制为 2000/20000 字符，普通分段参数在该模式下忽略。
- 图片资产：DOCX 解析时抽取内嵌图片落对象存储，chunk 正文保留原子占位符并用 `images[]` 结构化返回；前端经鉴权接口拉取 blob 渲染，不暴露对象路径。图片不参与向量化。
- 附件生命周期：available → consumed（创建文档）→ deleted（删除文档/知识库时对象一并清理）。

### 四种持久表示与权威性

- 原始文件是用户上传的事实来源，保存在共享对象存储；数据库只保存文档元数据、状态和清理意图。
- 规范化全文工件是解析器生成的 UTF-8 Markdown/text 快照，按内容 hash 写入对象存储，并由 `document.meta.normalized_artifact_key` 和 `normalized_content_hash` 指向。它是分块、引用解析和 Graph 增量版本判断的输入，不替代原始文件。
- Parent/Child 是可重建的结构化分段：Parent 保存章节上下文，Child 保存可检索正文、半开区间 offset 和索引状态。只有 Child 进入 Qdrant/`pg_search`；数据库中的文档、Parent、Child 状态和权限仍是检索事实来源。
- Evidence Graph 保存实体、别名、提及、claim、evidence、review、schema 和 revision。PostgreSQL 是关系、状态、版本和证据引用的唯一权威；Profile Markdown 是由当前发布 revision 投影出的持久知识页，Qdrant profile collection 只是可删除、可重建的派生向量索引。

ORM 模型集中在 `backend/app/domain/knowledge/models.py`（并在文件尾部导入 `domain/knowledge/graph/models.py` 完成 Graph 表元数据注册），Alembic `env.py` 从 `app.domain.*` 导入这些模型装载全部表。

## 检索、引用图与评测

- 所有 API、Agent 和 Workflow 调用同一应用层检索器（`application/knowledge/retrieval/service.py`）；`query/inspect` 额外返回候选数量、重排状态和各阶段耗时，不记录原始查询文本。
- 关键词通道使用 `pg_search` 的 ParadeDB 索引和 `pdb.score()` BM25 排序，`search_text` 以 Jieba 分词；查询采用词项析取以提高自然语言问题召回，再与向量和引用候选通过 RRF 融合。（如需回滚到引入 `pg_search` 之前的旧关键词实现，须同时恢复上一版应用和 Alembic 版本，使原生 `ts_rank_cd` 查询与 GIN 索引匹配。）
- 文档引用图使用 PostgreSQL `knowledge_document_references` 邻接表，不使用图数据库。Markdown/纯文本中的相对链接在解析时确定性解析（规则在 `domain/knowledge/documents/references.py`）；仅扩展同工作区、同知识库、已启用且已索引的目标文档，固定一跳，单文档最多 100 条边、单次最多 8 个目标文档。
- Evidence Graph 领域规则与纯遍历逻辑在 `domain/knowledge/graph/`（schema/extraction/resolution/revisions/traversal 等子模块）；用例层在 `application/knowledge/graph/`：`build.py` 负责抽取、身份消歧、引用 claim、组件/Profile 与 revision 发布，`query.py` 负责实体链接、路径/邻域计划和结果裁剪，`maintenance.py` 负责源变更对账、孤儿 revision 恢复与 Profile 修复，`service.py` 提供 Graph 管理/查询用例门面。复杂路径查询使用 `infra/db/sql/knowledge/graph/*.sql` 的有界 PostgreSQL `WITH RECURSIVE` CTE，并在同一 workspace/knowledge base 范围内设置 2 秒 statement timeout。
- Graph schema 是知识库级版本化抽取约束；revision 依次经历 `building`、`published`、`failed`、`retired`，发布时以数据库事务原子切换活动版本。Entity 为 `active/merged/retired`，claim 为 `candidate/active/rejected/superseded`，evidence 为 `active/deleted/inaccessible`，review 为 `open/approved/rejected/resolved`。候选、人工 merge/split 和拒绝结果都进入下一 revision，不直接改写历史快照。
- Graph 默认使用内置 schema，不要求用户先编辑 JSON。知识库从关闭切换为启用时会持久化一次全量 `graph_rebuild`；之后每个文档索引成功都会自动合并 `graph_sync`，因此上传流程不需要手工触发抽取。自定义 schema 和手动全量重建只用于高级约束、模型切换或故障恢复。
- `graph_sync` 只处理文档增量和停用/删除 tombstone，`graph_rebuild` 从当前文档全量重建；两者都通过持久化 `KnowledgeTask`、租约、心跳和冲突检测运行。抽取在 `domain/knowledge/graph/extraction.py` 以确定性规则（显式二元谓词 + 实体词典/别名）逐 Child 进行，结构化导入按源批次处理；每完成一个 Child/批次就以 worker 所有权条件原子写入 `processed_items/total_items`，任务页轮询刷新即显示 `1/175`、`2/175` 等增量进度，停止请求也不会被旧 worker 的进度写回覆盖。断点续跑要求 checkpoint 与源批次对齐且 schema、父 revision、文档版本未变化，否则拒绝并退回全量重试。构建失败或停止后 revision 保持终态，只能由用户显式重试（`all` 或 `unfinished`）；Beat 只恢复孤儿 `building` revision 并按批次修复 `profile_repair_pending`/删除 pending Profile。
- 构建失败会保留上一个 `published` revision 和现有文本 RAG 结果，失败原因只在管理员可见的截断字段中保存；Profile 向量写入失败会留下 `profile_repair_pending/profile_delete_pending`，由 Beat 重试。revision changes、状态、统计和发布审计在同一数据库事务中提交，失败回滚不会留下半个活动图。

### Graph API、Agent/Workflow 契约

- 管理页和 API 提供 `/graph/settings`、`/graph/schema`、`/graph/status`、`/graph/rebuild`、`/graph/entities`、`/graph/overview`、`/graph/path`、`/graph/neighborhood`、`/graph/import`、`/graph/reviews` 和 review resolve（路由在 `api/v1/knowledge/graph.py`）；所有路由先验证 workspace、知识库状态和 view/edit 权限。
- 知识查询与 inspect 请求接受 `graph_mode=off|auto|path|neighborhood`、`source_entity`、`target_entity`、`max_hops` 和 `relation_filters`。Trace 返回 graph intent、revision、候选/路径/访问节点数、hop、truncated/limit_reason 及阶段耗时；Graph 关闭时这些字段为 0/null，且不访问 Graph repository 或 Qdrant profile collection。
- Agent/Workflow 复用同一检索用例。内部工具可读取有界的 graph path、claim/evidence ID 和 revision snapshot；公开 Agent 只返回最终安全文本与既有公开 citation，不返回 profile、内部实体/claim/revision ID 或完整 evidence quote。Workflow Knowledge 节点保留 `graph_revision_id`、有界 `graph_paths` 和每个命中 Child 的 `graph_claim_ids/graph_hops`，历史运行快照不随当前 Graph 更新而改变。

### 生命周期、权限、日志与回滚

- 文档停用或删除先写 tombstone/revision change；当 evidence 不再被任何活动文档支持时才退休 claim。对象存储、普通向量和 profile 向量的删除意图均持久化（`domain/knowledge/storage/cleanup.py`），删除失败由 Beat 按退避重试，不能用未持久化的 post-commit 清理替代。
- 知识任务支持 `POST /tasks/{task_id}/stop`、`DELETE /tasks/{task_id}` 和 `POST /tasks/bulk-delete`。排队任务停止后直接进入 `cancelled`；运行任务先进入 `cancelling`，worker 在租约/批次边界收口为 `cancelled`。`queued/running/cancelling` 仍参与冲突检测且不能删除，只有终态任务可以单条或原子批量删除；`failed/cancelled` 可在重试次数范围内重新提交。Graph 重试请求可选择 `all` 或 `unfinished`：前者新建 revision 并从 0 开始，后者复用失败 revision，只跳过已原子提交的 Child；Schema、父 revision、文档版本或分片总数变化时拒绝断点续跑并要求全部重试。
- Graph API 遵循知识库 view/edit 权限和 workspace 隔离；跨 workspace 的实体、review、path ID 不可读取。Graph 日志只记录 workspace/knowledge base/task/revision、阶段、计数、耗时、限制和安全错误分类，不记录 query、实体属性、canonical name、alias、profile、quote、prompt、源文件、凭据或完整异常 request body。
- 回滚只需关闭 Graph setting（`enabled=false`），不要删除表、revision 或执行生产 downgrade；`graph_mode=off` 会继续走现有 vector + `pg_search` BM25 + reference + rerank 三路检索。确认文本 RAG 稳定后可重新启用并 rebuild，PostgreSQL Graph 权威数据和历史 revision 保留，Qdrant profile collection 可从发布 revision 重建。
- 命中测试可将当前问题和选定期望文档保存为检索评测用例；评测任务复用生产检索链路（`application/knowledge/evaluation/runner.py`），指标计算（Hit@K、Recall@K、MRR、nDCG@K、P50/P95 延迟）在 `domain/knowledge/evaluation/metrics.py`，纯函数无副作用。评测与其他知识任务共用冲突检测与租约机制；失败用例可在同一任务上重试，已成功结果不会被重复执行或旧 worker 错误覆盖。已结束的评测运行可从历史中删除，结果随运行清理。

## 文件清单

### 领域层 `backend/app/domain/knowledge/`

- `models.py` — 知识库/附件/文档/资源/分块/文档引用/任务/评测用例与结果/存储清理 ORM 模型（文件尾导入 graph 子包 ORM 完成全表注册）
- `service.py` — 领域门面：重导出 bases（知识库 CRUD + 模型解析）、documents（文档/附件）、permissions 等按关切拆分的子服务
- `entities` 对应实体在 `backend/app/entities/knowledge/models.py`（dataclass + 文档/任务/分块状态常量）与 `backend/app/entities/knowledge/graph.py`（Graph 实体 dataclass 与 schema/revision/entity/claim/evidence/review 状态常量）
- `bases/service.py` — 知识库 CRUD、注册模型解析与默认模型、模型连通性测试、owner 转移、删除返回持久清理 id
- `bases/permissions.py` — view/edit 资源授权、归档只读校验、授权读写与审计
- `documents/service.py` — 文档与附件服务：上传落盘（对象存储）、附件消费建文档、清理文件名、响应组装
- `documents/lifecycle.py` — 文档删除/停用生命周期：tombstone、级联清理编排与 graph_sync 触发
- `documents/references.py` — 文档引用规则：Markdown/纯文本链接标签提取、别名/锚点归一化、一跳解析、引用重建与解绑
- `tasks/orchestration.py` — 解析/索引/重建/评测/图任务状态机编排：入队与冲突检测、embedding 模型解析、stop/retry/删除、图重试模式（`all`/`unfinished`）与断点续跑校验
- `tasks/runner.py` — 知识任务执行体：租约维护与心跳、parse/index 执行、失败/取消收口、孤儿任务恢复
- `evaluation/service.py` — 评测用例与运行的业务规则：创建/删除、入队、权限、与重建类任务互斥及 Graph 期望指标
- `evaluation/metrics.py` — 纯检索指标计算（单用例与聚合，含百分位延迟）
- `evaluation/__init__.py` — 门面，重导出 `service`
- `storage/cleanup.py` — 删除前创建持久化清理记录；删除后幂等清理对象存储、普通向量 collection 与 Graph profile collection，失败按退避重试
- `graph/` — Graph 领域规则与纯遍历逻辑：
  - `schema.py` — `GraphSchemaDefinition`（entity type/relation/property 约束）、名称归一化与 hash、内置默认 schema
  - `extraction.py` — 确定性规则抽取器（显式二元谓词 + 实体词典/别名匹配）、抽取批量校验与有界约束
  - `resolution.py` — 身份消歧：claim 指纹、external_key/人工别名/规范化名匹配、初始 claim 状态判定
  - `revisions.py` — revision 创建、变更 staging/应用（upsert/retire/delete 按 record kind）、原子 `publish_revision`
  - `services.py` — Graph schema 领域服务（create/activate）+ 重导出 extraction/resolution/revisions 规则
  - `models.py` — Graph 表 ORM
  - `traversal.py` — 有界 path/neighborhood 遍历：节点/claim/evidence 视图组装与结果裁剪
- `__init__.py` — 空包文件

### 应用层 `backend/app/application/knowledge/`

- `documents/service.py` — 面向 API 的知识用例组合：附件上传（图片文档校验）、文档/附件响应、删除/启停后的图任务触发、资产文件解析与鉴权读取、任务分发 `dispatch_knowledge_task`
- `retrieval/service.py` — 统一详细检索用例（API/Agent/Workflow 共用）：向量 + 关键词 + 引用一跳 + Graph 候选 + RRF 融合 + 可选重排；`retrieve_knowledge_base` 额外返回诊断 trace
- `evaluation/runner.py` — 评测任务执行：复用生产检索链路、按所有权持久化进度、幂等结果写入与汇总响应
- `graph/service.py` — Graph 管理/查询用例门面：settings/schema/status/rebuild/entities/overview/path/neighborhood/import/reviews/resolve
- `graph/build.py` — `graph_sync`/`graph_rebuild` 执行体：分块抽取与消歧 staging、references/连通分量、Profile 生成与向量 upsert、原子发布、失败标记与统计
- `graph/query.py` — Graph 查询计划：实体链接（规范化名精确/Profile 向量候选）、path/neighborhood 规划与执行、结果裁剪与阶段耗时
- `graph/maintenance.py` — Beat 对账：源版本 diff、due graph 任务入队、孤儿 building revision 恢复、pending Profile 修复/删除

### API 与契约层

- `backend/app/api/v1/knowledge/` — 知识域路由：
  - `routes.py` — 知识库/文档/附件/任务 CRUD、`parse`/`index`/`rebuild`、模型测试、owner 转移、授权管理
  - `lifecycle.py` — 文档下载、文档资产 blob 读取、文档删除与启停
  - `retrieval.py` — `POST /{kb_id}/query` 与 `POST /{kb_id}/query/inspect`
  - `evaluation.py` — `/evaluations` 用例/运行/结果路由
  - `graph.py` — `/graph` 子路由（settings/schema/status/rebuild/entities/overview/path/neighborhood/import/reviews/resolve）
- `backend/app/schemas/knowledge/contracts.py` — 知识库/文档/分块/任务/检索/评测请求响应契约
- `backend/app/schemas/knowledge/graph.py` — Graph 契约（settings/schema/status/entity/claim/review/查询结果与 import 记录）

### 数据访问与 SQL 资产

- `backend/app/infra/db/repositories/knowledge/repository.py` — 知识库/附件/文档/分块/任务/清理记录的 PostgreSQL 读写（ORM↔entity 映射、锁与租约续期、冲突检测）及关键词 chunk id 查询
- `backend/app/infra/db/repositories/knowledge/references.py` — `knowledge_document_references` 邻接表读写与别名解析查询
- `backend/app/infra/db/repositories/knowledge/evaluation.py` — 评测用例/期望/结果与运行读写
- `backend/app/infra/db/repositories/knowledge/graph.py` — Graph schema/revision/entity/alias/mention/claim/evidence/review 权威读写、工作空间模型用量统计、有界遍历行查询（加载下方 CTE 并设置 2 秒 statement timeout）
- `backend/app/infra/db/sql/knowledge/query_keyword_chunk_ids.sql` — `pg_search` BM25 关键词候选查询
- `backend/app/infra/db/sql/knowledge/graph/shortest_path.sql`、`neighborhood.sql`、`query_entity_candidates.sql` — 有界 `WITH RECURSIVE` CTE（路径/邻域/实体候选）

### 契约与实现

- `backend/app/ports/{llm,parsing,vector_store}.py` — 稳定契约入口（模型与重排、解析管线与 QA 导入、向量存储）；实现集中在 `backend/app/adapters/`
  - `backend/app/adapters/parsing/pipeline.py` — 解析管线（分块/规范化全文）
  - `backend/app/adapters/parsing/qa_import.py` — 有界 CSV/XLSX QA 行解析与校验
  - `backend/app/adapters/rag/retrieval.py` — RRF 融合、Parent 上下文/evidence 窗口裁剪、重排应用
  - `backend/app/adapters/rag/vector_store.py` — Qdrant 向量读写（含 Graph profile collection）
- `backend/app/infra/storage/object_storage.py` — 对象存储 port 与本地实现（知识附件/规范化全文工件落盘）

### Celery 任务

- `backend/app/tasks/knowledge/jobs.py` — Celery 任务定义与入队 helper（共用 `backend/app/tasks/runtime.py` 的 worker 配置与异步运行辅助）：
  - `app.knowledge.run_task` — 知识任务执行（parse/index/rebuild/evaluate/graph_sync/graph_rebuild 分发）
  - `app.knowledge.recover` — 恢复孤儿知识任务并重新入队
  - `app.knowledge.reconcile_graphs` — Graph 源变更对账与 due 任务入队（Beat）
  - `app.knowledge.cleanup_storage` / `app.knowledge.recover_storage_cleanups` — 知识库外部存储清理及恢复
  - `app.uploads.cleanup_storage` / `app.uploads.recover_storage_cleanups` — 上传对象存储清理及恢复
  - celery app 由 `backend/app/infra/queue/celery.py`（`celery_app`）提供，worker 以 `celery -A app.infra.queue.celery:celery_app` 启动

## 相关测试（`backend/tests/knowledge/`）

按 `python -m tests.<feature>.<file>` 运行：

- `tests.knowledge.knowledge`（`knowledge.py`）— 知识库端到端：CRUD/普通与 QA 导入/平铺与层级分块/引用图/混合检索/评测重试与恢复/任务租约/租户约束/权限/审计
- `tests.knowledge.unit`（`unit.py`）— 领域单元测试（编排/runner/指标/引用规则等纯逻辑）
- `tests.knowledge.knowledge_graph`（`knowledge_graph.py`）— Graph 固定数据、revision 原子发布、身份消歧、证据生命周期、路径限制、租约恢复、Agent/Workflow 输出和 Graph off 回滚回归
- `tests.knowledge.knowledge_graph_edge_coverage`（`knowledge_graph_edge_coverage.py`）— Graph API、自动首次构建、协调补偿和错误边界覆盖
- `tests.knowledge.knowledge_domain_coverage`（`knowledge_domain_coverage.py`）— 领域规则/状态机覆盖
- `tests.knowledge.knowledge_api_coverage`（`knowledge_api_coverage.py`）— API 路由/契约/权限覆盖
