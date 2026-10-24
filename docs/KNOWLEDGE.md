# KNOWLEDGE 模块（backend/app 知识域：domain/knowledge + application/knowledge + tasks/knowledge + api/v1/knowledge + entities/schemas/knowledge + tests/knowledge）

## 职责

知识库业务领域：知识库/文档/分块/任务的状态机编排（解析 → 规范化全文 → 分块 → embedding → 向量入库），支持普通文档与显式 QA 表导入、平铺分段与按 Markdown 章节生成 Parent + Child 的智能分段；Child 进入向量与文本检索索引。检索统一经过向量、PostgreSQL `pg_search` BM25和可选重排。模块同时负责任务租约与失败重试、文档生命周期、知识库删除后的持久化外部存储清理。Celery 任务入口在 `backend/app/tasks/knowledge/jobs.py`。

## 权限语义

- 知识库列表按用户隔离：只列出自己创建的与被 `ResourcePermission` 授权的知识库（响应 `permission` 字段为 view/edit/none），工作空间管理员与系统管理员不例外；跨租户或未授权访问一律按未找到/禁止处理。
- 知识库归档后只读：写操作（上传/解析/索引/重建/改名/授权管理/删除）返回 403，仅创建者可恢复。
- owner（`created_by_user_id`）可通过 `PUT /knowledge-bases/{id}/owner` 转移给活动工作区成员；转移后原 owner 不再隐式享有 edit。

## 分层关系

```text
api/v1/knowledge（routes/lifecycle/retrieval/evaluation 路由）
  → application/knowledge（用例编排：documents、retrieval、evaluation/runner）
    → domain/knowledge（bases、documents、evaluation、storage、tasks 领域规则；service.py 门面）
      → ports（llm/vector_store/execution/mcp 等稳定契约入口；解析与 QA 导入不是 port）
      → adapters（rag/vector_store 向量存储、llm 运行时与 provider）
      → infra/db/repositories/knowledge + sql/knowledge（PostgreSQL 权威读写）
    → tasks/knowledge/jobs.py（Celery 包装、恢复与重试；app.knowledge.run_task / app.storage.cleanup / app.maintenance.run）
```

仓储层把 ORM 行经 `to_entity` 映射回 `entities/knowledge` 的 dataclass 实体后供领域层消费。

## 文档导入流程

- 附件上传 `POST /knowledge-bases/{kb_id}/attachments` 只接受 DOCX、MD、MARKDOWN、PDF、TXT、PPTX、XLSX、XLS、HTML、CSV、JSON、XML、ZIP，并先在服务端按扩展名拒绝其他格式，再将原文件持久化到对象存储（adapter 见 `backend/app/infra/storage/object_storage.py`）并返回 attachment。
- 文档创建 `POST /documents` 接收 `attachment_ids`、`staged` 和显式 `import_mode`（`document`/`qa`）；事务内消费附件并生成 staged 文档。解析/向量化一律走 Celery 任务（`POST /parse`、`POST /index`）。
- 普通文档解析在前后端统一默认使用智能分段：`hierarchical`、1200 字符、150 字符重叠、按空行分隔，并依次执行 `trim_lines` 与 `remove_empty_lines`；高级模式仍可显式提交 `flat` 和自定义参数。省略解析请求体与提交空对象的语义一致。
- QA 模式只接受 UTF-8 CSV 或 XLSX，表头支持 `question/问题`、`answer/答案` 和可选 `source/来源`。每行生成一个 `kind=qa` Child，答案作为返回正文，`question + answer` 作为检索文本；最多 5000 行，问题/答案分别限制为 2000/20000 字符，普通分段参数在该模式下忽略。
- 图片资产：DOCX 解析时抽取内嵌图片落对象存储（`KnowledgeAsset`/`KnowledgeChunkAsset` 记录），chunk 正文保留原子占位符并用 `images[]` 结构化返回；前端经鉴权接口拉取 blob 渲染，不暴露对象路径。图片不参与向量化。
- 附件生命周期：available → consumed（创建文档）→ deleted（删除文档/知识库时对象一并清理）。

### 持久表示

- 原始文件是用户上传的事实来源，保存在共享对象存储；数据库只保存文档元数据、状态和清理意图。
- 规范化全文工件是解析器为每种受支持格式（包括 QA CSV/XLSX）生成的 UTF-8 Markdown 快照，按内容 hash 以 `.md` 写入对象存储，并由 `document.meta.normalized_artifact_key`、`normalized_content_hash`、`normalized_content_type=text/markdown` 和 `normalized_text_version` 指向。它是分块和文档详情 Markdown 展示的输入，不替代原始文件；详情通过受知识库权限保护的 `GET /documents/{document_id}/content` 读取。
- Parent/Child 是可重建的结构化分段：Parent 保存章节上下文，Child 保存可检索正文、半开区间 offset 和索引状态。只有 Child 进入 Qdrant/`pg_search`；数据库中的文档、Parent、Child 状态和权限仍是检索事实来源。

ORM 模型集中在 `backend/app/domain/knowledge/models.py`，Alembic `env.py` 从 `app.domain.*` 导入模型装载全部表。

## 检索与评测

- 所有 API、Agent 和 Workflow 调用同一应用层检索器（`application/knowledge/retrieval/service.py`）；`query/inspect` 额外返回候选数量、重排状态和各阶段耗时，不记录原始查询文本。
- 关键词通道使用 `pg_search` 的 ParadeDB 索引和 `pdb.score()` BM25 排序，`search_text` 以 Jieba 分词；查询采用词项析取以提高自然语言问题召回，再与向量候选通过 RRF 融合。（如需回滚到引入 `pg_search` 之前的旧关键词实现，须同时恢复上一版应用和 Alembic 版本，使原生 `ts_rank_cd` 查询与 GIN 索引匹配。）
- API、Agent 工具和 Workflow Knowledge 节点只使用文本检索参数；返回命中、引用和检索 trace，不再包含图谱模式、实体、路径、修订或图评测指标。旧请求中多余的图参数被忽略，历史运行快照保持原样。
- 检索评测复用生产检索链路，保留 Hit@K、Recall@K、MRR、NDCG 与延迟指标。

### 生命周期与升级

- 文档删除或停用更新文档状态；对象存储和向量删除意图持久化，失败由 Beat 重试。
- 知识任务保留 parse/index/rebuild_index/evaluate。排队任务停止后进入 `cancelled`；运行任务先进入 `cancelling`，worker 在租约/批次边界收口。只有终态任务可删除，受支持类型的 `failed/cancelled` 任务可在重试次数范围内重新提交。
- 迁移 `202610250001` 删除图谱表、文档引用表、图设置/评测列、图任务以及结构化图导入文档与文件，并删除专属 Qdrant Profile collections。普通文档、向量 collection 与答案引用保留。
- 该迁移需要访问 Qdrant 与共享 `KNOWLEDGE_STORAGE_DIR`；Compose 的 migrate 服务挂载知识存储并等待 Qdrant 健康。外部清理失败会中止升级，重试为幂等操作。迁移删除数据，不提供降级恢复；历史迁移文件保留以维持升级链。

## 文件清单

### 领域层 `backend/app/domain/knowledge/`

- `models.py` — 知识库/附件/文档/图片资产（`knowledge_assets`）/资源/Parent 分块/分块/分块资产（`knowledge_chunk_assets`）/任务/评测用例、评测期望与结果/存储清理共 12 张 ORM 表
- `service.py` — 领域门面：重导出 bases（知识库 CRUD + 模型解析）、documents（文档/附件）、permissions 等按关切拆分的子服务
- `entities` 对应实体在 `backend/app/entities/knowledge/models.py`（dataclass + 文档/任务/分块状态常量）
- `bases/service.py` — 知识库 CRUD、注册模型解析与默认模型、模型连通性测试、owner 转移、删除返回持久清理 id
- `bases/permissions.py` — view/edit 资源授权、归档只读校验、授权读写与审计
- `documents/service.py` — 文档与附件服务：上传落盘（对象存储）、附件消费建文档、清理文件名、响应组装
- `documents/parsing.py` — 解析管线：mammoth/MarkItDown/pypdf 抽取（PDF 只读文本层，不做 OCR）、归档与内嵌图片资产约束、规范化全文工件、平铺与层级分块（`SEGMENTATION_VERSION`）
- `documents/qa_import.py` — 有界 CSV/XLSX QA 行解析与校验（openpyxl；`MAX_QA_ROWS`/问题与答案长度上限）
- `documents/lifecycle.py` — 文档删除/停用生命周期：状态更新与级联清理编排
- `retrieval.py` — 纯检索算法：RRF 融合、Parent 上下文与 evidence 窗口裁剪、重排结果应用（由 `application/knowledge/retrieval/service.py` 调用）
- `tasks/orchestration.py` — 解析/索引/重建/评测状态机编排：入队与冲突检测、embedding 模型解析、stop/retry/删除
- `tasks/runner.py` — 知识任务执行体：租约维护与心跳、parse/index 执行、失败/取消收口、孤儿任务恢复
- `evaluation/service.py` — 评测用例与运行的业务规则：创建/删除、入队、权限、与重建类任务互斥
- `evaluation/metrics.py` — 纯检索指标计算（单用例与聚合，含百分位延迟）
- `evaluation/__init__.py` — 门面，重导出 `service`
- `storage/cleanup.py` — 删除前创建持久化清理记录；删除后幂等清理对象存储、向量 collection，失败按退避重试
- `__init__.py` — 空包文件

### 应用层 `backend/app/application/knowledge/`

- `documents/service.py` — 面向 API 的知识用例组合：附件上传（图片文档校验）、文档/附件响应、文档删除/启停、资产文件解析与鉴权读取、任务分发 `dispatch_knowledge_task`
- `retrieval/service.py` — 统一详细检索用例（API/Agent/Workflow 共用）：向量 + 关键词 + RRF 融合 + 可选重排；`retrieve_knowledge_base` 额外返回诊断 trace
- `evaluation/runner.py` — 评测任务执行：复用生产检索链路、按所有权持久化进度、幂等结果写入与汇总响应

### API 与契约层

- `backend/app/api/v1/knowledge/` — 知识域路由：
  - `routes.py` — 知识库/文档/附件/任务 CRUD、`parse`/`index`/`rebuild`、模型测试、owner 转移、授权管理
  - `lifecycle.py` — 文档下载、文档资产 blob 读取、文档删除与启停
  - `retrieval.py` — `POST /{kb_id}/query` 与 `POST /{kb_id}/query/inspect`
  - `evaluation.py` — `/evaluations` 用例/运行/结果路由，含 `GET /results/latest` 最近指标汇总
- `backend/app/schemas/knowledge/contracts.py` — 知识库/文档/分块/任务/检索/评测请求响应契约

### 数据访问与 SQL 资产

- `backend/app/infra/db/repositories/knowledge/` — 按关切拆分的仓储包：`repository.py`（重导出门面，并加载关键词 SQL）、`bases.py`（知识库与授权行读写）、`documents.py`（文档/分块/Parent/图片资产与 `query_keyword_chunk_ids` BM25 查询）、`tasks.py`（任务、租约与恢复候选）、`storage.py`（清理记录）、`evaluation.py`（评测用例/期望/结果与运行）
- `backend/app/infra/db/sql/knowledge/query_keyword_chunk_ids.sql` — `pg_search` BM25 关键词候选查询

### 契约与实现

- `backend/app/ports/{llm,vector_store}.py`（另有 `execution`/`mcp`/`errors`/`announcements`/`enterprise_identity`）— 稳定契约入口（模型与重排、向量存储）；实现集中在 `backend/app/adapters/`
  - `backend/app/domain/knowledge/documents/parsing.py` — 解析管线（抽取/规范化全文/分块）
  - `backend/app/domain/knowledge/documents/qa_import.py` — 有界 CSV/XLSX QA 行解析与校验
  - `backend/app/domain/knowledge/retrieval.py` — RRF 融合、Parent 上下文/evidence 窗口裁剪、重排应用
  - `backend/app/adapters/rag/vector_store.py` — Qdrant 向量读写
- `backend/app/infra/storage/object_storage.py` — 对象存储 port 与本地实现（知识附件/规范化全文工件落盘）

### Celery 任务

- `backend/app/tasks/knowledge/jobs.py` — `app.knowledge.run_task` 执行 parse/index/rebuild_index/evaluate。
- `backend/app/tasks/storage/jobs.py` — `app.storage.cleanup` 按 `knowledge` / `upload` 类型执行持久化外部存储清理。
- `backend/app/tasks/maintenance/jobs.py` — `app.maintenance.run` 按 cadence 恢复孤儿任务并重新派发到期的存储清理。
- Celery app 由 `backend/app/infra/queue/celery.py`（`celery_app`）提供，worker 以 `celery -A app.infra.queue.celery:celery_app` 启动。

## 相关测试（`backend/tests/knowledge/`）

按 `python -m tests.<feature>.<file>` 运行：

- `tests.knowledge.knowledge`（`knowledge.py`）— 知识库端到端：CRUD/普通与 QA 导入/平铺与层级分块/混合检索/评测重试与恢复/任务租约/租户约束/权限/审计
- `tests.knowledge.unit`（`unit.py`）— 领域单元测试（编排/runner/指标等纯逻辑）
- `tests.knowledge.graph_removal`（`graph_removal.py`）— 移除图接口、参数和 ORM 表，升级清理专属文件/索引且保留普通文档
- `tests.knowledge.knowledge_domain_coverage`（`knowledge_domain_coverage.py`）— 领域规则/状态机覆盖
- `tests.knowledge.knowledge_api_coverage`（`knowledge_api_coverage.py`）— API 路由/契约/权限覆盖
