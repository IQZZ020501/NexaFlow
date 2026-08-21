# KNOWLEDGE 模块（backend/app/shareddomain/knowledge + knowledge_graph + tasks）

## 职责

知识库业务领域：知识库/文档/分块/任务的状态机编排（解析 → 规范化全文 → 分块 → embedding → 向量入库），支持普通文档与显式 QA 表导入、平铺分段与按 Markdown 章节生成 Parent + Child 的智能分段；仅 Child 进入文本与向量检索索引。检索统一经过向量、PostgreSQL `pg_search` BM25、显式文档引用一跳扩展、可选重排和可选 Evidence Graph，多跳图谱结果始终回指证据。模块同时负责任务租约与失败重试、文档生命周期、知识库删除后的持久化外部存储清理，以及旧版段落式批量导入兼容。Celery 任务入口在 `tasks/`。

## 权限语义

- 同工作区成员可见全部知识库列表（响应 `permission` 字段为 view/edit/none），访问与写入仍按 view/edit 资源授权判定。
- 知识库归档后只读：写操作（上传/解析/索引/重建/改名/授权管理/删除）返回 403，仅工作区管理员或 owner 可恢复。
- owner（`created_by_user_id`）可通过 `PUT /knowledge-bases/{id}/owner` 转移给活动工作区成员；转移后原 owner 不再隐式享有 edit。

## 分层关系

```text
api/knowledge*.py → application（用例组合）
                  → shareddomain/knowledge（业务规则与任务编排）
                  → ports + infrastructure/repositories
                  → capabilities/{embedding,rag,llm}
                  → tasks/knowledge.py（Celery 包装、恢复与重试）
```

## 文档导入流程

- 附件上传 `POST /knowledge-bases/{kb_id}/attachments` 只持久化文件（`infrastructure/object_storage.py` 对象存储 adapter），返回 attachment。
- 文档创建 `POST /documents` 接收 `attachment_ids`、`staged` 和显式 `import_mode`（`document`/`qa`）；事务内消费附件并生成 staged 文档。解析/向量化一律走 Celery 任务（`POST /parse`、`POST /index`）。
- QA 模式只接受 UTF-8 CSV 或 XLSX，表头支持 `question/问题`、`answer/答案` 和可选 `source/来源`。每行生成一个 `kind=qa` Child，答案作为返回正文，`question + answer` 作为检索文本；最多 5000 行，问题/答案分别限制为 2000/20000 字符，普通分段参数在该模式下忽略。
- 图片资产：DOCX 解析时抽取内嵌图片落对象存储，chunk 正文保留原子占位符并用 `images[]` 结构化返回；前端经鉴权接口拉取 blob 渲染，不暴露对象路径。图片不参与向量化。
- 附件生命周期：available → consumed（创建文档）→ deleted（删除文档/知识库时对象一并清理）。

### 四种持久表示与权威性

- 原始文件是用户上传的事实来源，保存在共享对象存储；数据库只保存文档元数据、状态和清理意图。
- 规范化全文工件是解析器生成的 UTF-8 Markdown/text 快照，按内容 hash 写入对象存储，并由 `document.meta.normalized_artifact_key` 和 `normalized_content_hash` 指向。它是分块、引用解析和 Graph 增量版本判断的输入，不替代原始文件。
- Parent/Child 是可重建的结构化分段：Parent 保存章节上下文，Child 保存可检索正文、半开区间 offset 和索引状态。只有 Child 进入 Qdrant/`pg_search`；数据库中的文档、Parent、Child 状态和权限仍是检索事实来源。
- Evidence Graph 保存实体、别名、提及、claim、evidence、review、schema 和 revision。PostgreSQL 是关系、状态、版本和证据引用的唯一权威；Profile Markdown 是由当前发布 revision 投影出的持久知识页，Qdrant profile collection 只是可删除、可重建的派生向量索引。

## 检索、引用图与评测

- 所有 API、Agent 和 Workflow 调用同一应用层检索器；`query/inspect` 额外返回候选数量、重排状态和各阶段耗时，不记录原始查询文本。
- 关键词通道使用 `pg_search` 的 ParadeDB 索引和 `pdb.score()` BM25 排序，`search_text` 以 Jieba 分词；查询采用词项析取以提高自然语言问题召回，再与向量和引用候选通过 RRF 融合。回滚时必须同时恢复上一版应用和 Alembic 版本，使原生 PostgreSQL `ts_rank_cd` 查询与 GIN 索引匹配。
- 文档引用图使用 PostgreSQL `knowledge_document_references` 邻接表，不使用图数据库。Markdown/纯文本中的相对链接在解析时确定性解析；仅扩展同工作区、同知识库、已启用且已索引的目标文档，固定一跳，单文档最多 100 条边、单次最多 8 个目标文档。
- Evidence Graph 由 `backend/app/shareddomain/knowledge_graph/` 保存领域规则和纯遍历逻辑：`application/knowledge_graph_build.py` 负责抽取、身份消歧、引用 claim、组件/Profile 和 revision 发布；`knowledge_graph_query.py` 负责实体链接、路径/邻域计划和结果裁剪；`knowledge_graph_maintenance.py` 负责源变更对账、孤儿 revision 恢复与 Profile 清理。复杂路径查询使用 `infrastructure/sql/knowledge_graph/*.sql` 的有界 PostgreSQL `WITH RECURSIVE` CTE，并在同一 workspace/knowledge base 范围内设置 2 秒 statement timeout。
- Graph schema 是知识库级版本化抽取约束；revision 依次经历 `building`、`published`、`failed`、`retired`，发布时以数据库事务原子切换活动版本。Entity 为 `active/merged/retired`，claim 为 `candidate/active/rejected/superseded`，evidence 为 `active/deleted/inaccessible`，review 为 `open/approved/rejected/resolved`。候选、人工 merge/split 和拒绝结果都进入下一 revision，不直接改写历史快照。
- Graph 默认使用内置 schema，不要求用户先编辑 JSON。知识库从关闭切换为启用时会持久化一次全量 `graph_rebuild`；之后每个文档索引成功都会自动合并 `graph_sync`，因此上传流程不需要手工触发抽取。自定义 schema 和手动全量重建只用于高级约束、模型切换或故障恢复。
- `graph_sync` 只处理文档增量和停用/删除 tombstone，`graph_rebuild` 从当前文档全量重建；两者都通过持久化 `KnowledgeTask`、租约、心跳、冲突检测和有限重试运行。Graph LLM 调用有单任务与工作空间月度 token 预算，实际/估算用量写入 revision。Celery Beat 的 `reconcile_graphs` 会重新派发过期任务、恢复孤儿 revision，并按批次清理 profile repair；不得改成提交后的 best-effort 调用。
- 构建失败会保留上一个 `published` revision 和现有文本 RAG 结果，失败原因只在管理员可见的截断字段中保存；Profile 向量写入失败会留下 `profile_repair_pending/profile_delete_pending`，由 Beat 重试。revision changes、状态、统计和发布审计在同一数据库事务中提交，失败回滚不会留下半个活动图。

### Graph API、Agent/Workflow 契约

- 管理页和 API 提供 `/graph/settings`、`/graph/schema`、`/graph/status`、`/graph/rebuild`、`/graph/entities`、`/graph/path`、`/graph/neighborhood`、`/graph/import`、`/graph/reviews` 和 review resolve；所有路由先验证 workspace、知识库状态和 view/edit 权限。
- 知识查询与 inspect 请求接受 `graph_mode=off|auto|path|neighborhood`、`source_entity`、`target_entity`、`max_hops` 和 `relation_filters`。Trace 返回 graph intent、revision、候选/路径/访问节点数、hop、truncated/limit_reason 及阶段耗时；Graph 关闭时这些字段为 0/null，且不访问 Graph repository 或 Qdrant profile collection。
- Agent/Workflow 复用同一检索用例。内部工具可读取有界的 graph path、claim/evidence ID 和 revision snapshot；公开 Agent 只返回最终安全文本与既有公开 citation，不返回 profile、内部实体/claim/revision ID 或完整 evidence quote。Workflow Knowledge 节点保留 `graph_revision_id`、有界 `graph_paths` 和每个命中 Child 的 `graph_claim_ids/graph_hops`，历史运行快照不随当前 Graph 更新而改变。

### 生命周期、权限、日志与回滚

- 文档停用或删除先写 tombstone/revision change；当 evidence 不再被任何活动文档支持时才退休 claim。对象存储、普通向量和 profile 向量的删除意图均持久化，删除失败由 Beat 按退避重试，不能用未持久化的 post-commit 清理替代。
- Graph API 遵循知识库 view/edit 权限和 workspace 隔离；跨 workspace 的实体、review、path ID 不可读取。Graph 日志只记录 workspace/knowledge base/task/revision、阶段、计数、耗时、限制和安全错误分类，不记录 query、实体属性、canonical name、alias、profile、quote、prompt、源文件、凭据或完整异常 request body。
- 回滚只需关闭 Graph setting（`enabled=false`），不要删除表、revision 或执行生产 downgrade；`graph_mode=off` 会继续走现有 vector + `pg_search` BM25 + reference + rerank 三路检索。确认文本 RAG 稳定后可重新启用并 rebuild，PostgreSQL Graph 权威数据和历史 revision 保留，Qdrant profile collection 可从发布 revision 重建。
- 命中测试可将当前问题和选定期望文档保存为检索评测用例；评测任务复用生产检索链路，计算 Hit@K、Recall@K、MRR、nDCG@K 和 P50/P95 延迟。评测与解析、索引、重建互斥；失败用例可在同一任务上重试，已成功结果不会被重复执行或旧 worker 错误覆盖。已结束的评测运行可从历史中删除，结果随任务级联清理。

## 文件清单

- `backend/app/shareddomain/knowledge/models.py` — 知识库/文档/Parent/Child 分块/任务/外部存储清理 ORM 模型及租户范围约束
- `backend/app/shareddomain/knowledge/services.py` — 知识库与文档服务层：CRUD、权限校验（view/edit 资源级）、上传落盘、模型绑定校验
- `backend/app/shareddomain/knowledge/cleanup.py` — 删除前创建持久清理记录，删除后幂等清理 Qdrant 与对象存储；失败按退避时间重试
- `backend/app/shareddomain/knowledge/orchestration.py` — 文档解析/索引/任务状态机编排：状态流转、冲突任务检测、embedding/rerank 模型解析
- `backend/app/shareddomain/knowledge/task_runner.py` — 知识任务执行体：租赁锁、解析/向量化/入库执行与失败标记
- `backend/app/shareddomain/knowledge_graph/` — Graph 状态、schema/revision、身份解析、遍历和发布规则
- `backend/app/application/knowledge_graph_build.py` — 增量/全量构建、抽取、Profile、用量和原子发布
- `backend/app/application/knowledge_graph_query.py` — Graph 查询计划、实体链接、路径/邻域与安全 trace
- `backend/app/application/knowledge_graph_maintenance.py` — Beat 对账、失败恢复和 profile cleanup
- `backend/app/infrastructure/repositories/knowledge_graph.py` 与 `backend/app/infrastructure/sql/knowledge_graph/` — PostgreSQL 权威读写和有界 CTE 查询
- `backend/app/shareddomain/knowledge/evaluation.py` — 评测用例、运行创建、权限与并发业务规则
- `backend/app/application/knowledge_evaluation.py` — 生产检索评测执行、幂等结果持久化与指标汇总
- `backend/app/capabilities/embedding/qa_import.py` — 有界 CSV/XLSX QA 行解析与校验
- `backend/app/capabilities/rag/evaluation.py` — 无副作用的检索指标计算
- `backend/app/shareddomain/knowledge/legacy.py` — 旧版段落式批量导入文档的兼容服务
- `backend/app/shareddomain/knowledge/lifecycle.py` — 知识文档删除生命周期：清理分块、向量与磁盘文件
- `backend/app/tasks/knowledge.py` — Celery 任务定义：知识任务执行、外部存储清理及 Beat 周期恢复，失败自动重试

## 相关测试

- `backend/tests/knowledge.py` — 知识库端到端测试：CRUD/普通与 QA 导入/平铺与层级分块/引用图/混合检索/评测重试与恢复/任务租约/租户约束/权限/审计
- `backend/tests/knowledge_graph.py` — Graph 固定数据、revision 原子发布、身份消歧、证据生命周期、路径限制、租约恢复、Agent/Workflow 输出和 Graph off 回滚回归
