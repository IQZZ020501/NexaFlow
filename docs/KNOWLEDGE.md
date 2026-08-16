# KNOWLEDGE 模块（backend/app/shareddomain/knowledge + tasks）

## 职责

知识库业务领域：知识库/文档/分块/任务的状态机编排（解析 → 分块 → embedding → 向量入库），支持普通文档与显式 QA 表导入、平铺分段与按 Markdown 章节生成 Parent + Child 的智能分段；仅 Child 进入检索索引。检索统一经过向量、PostgreSQL `pg_search` BM25、显式文档引用一跳扩展和可选重排，并提供同链路离线评测。模块同时负责任务租约与失败重试、文档生命周期、知识库删除后的持久化外部存储清理，以及旧版段落式批量导入兼容。Celery 任务入口在 `tasks/`。

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

## 检索、引用图与评测

- 所有 API、Agent 和 Workflow 调用同一应用层检索器；`query/inspect` 额外返回候选数量、重排状态和各阶段耗时，不记录原始查询文本。
- 关键词通道使用 `pg_search` 的 ParadeDB 索引和 `pdb.score()` BM25 排序，`search_text` 以 Jieba 分词；查询采用词项析取以提高自然语言问题召回，再与向量和引用候选通过 RRF 融合。回滚时必须同时恢复上一版应用和 Alembic 版本，使原生 PostgreSQL `ts_rank_cd` 查询与 GIN 索引匹配。
- 文档引用图使用 PostgreSQL `knowledge_document_references` 邻接表，不使用图数据库。Markdown/纯文本中的相对链接在解析时确定性解析；仅扩展同工作区、同知识库、已启用且已索引的目标文档，固定一跳，单文档最多 100 条边、单次最多 8 个目标文档。
- 本切片不引入 Neo4j、LLM 实体/关系抽取、递归多跳遍历或跨知识库引用；仅当评测证明显式引用不足时再评估这些能力。
- 检索评测用例保存问题、期望文档与答案要点；评测任务复用生产检索链路，计算 Hit@K、Recall@K、MRR、nDCG@K 和 P50/P95 延迟。评测与解析、索引、重建互斥；失败用例可在同一任务上重试，已成功结果不会被重复执行或旧 worker 错误覆盖。

## 文件清单

- `backend/app/shareddomain/knowledge/models.py` — 知识库/文档/Parent/Child 分块/任务/外部存储清理 ORM 模型及租户范围约束
- `backend/app/shareddomain/knowledge/services.py` — 知识库与文档服务层：CRUD、权限校验（view/edit 资源级）、上传落盘、模型绑定校验
- `backend/app/shareddomain/knowledge/cleanup.py` — 删除前创建持久清理记录，删除后幂等清理 Qdrant 与对象存储；失败按退避时间重试
- `backend/app/shareddomain/knowledge/orchestration.py` — 文档解析/索引/任务状态机编排：状态流转、冲突任务检测、embedding/rerank 模型解析
- `backend/app/shareddomain/knowledge/task_runner.py` — 知识任务执行体：租赁锁、解析/向量化/入库执行与失败标记
- `backend/app/shareddomain/knowledge/evaluation.py` — 评测用例、运行创建、权限与并发业务规则
- `backend/app/application/knowledge_evaluation.py` — 生产检索评测执行、幂等结果持久化与指标汇总
- `backend/app/capabilities/embedding/qa_import.py` — 有界 CSV/XLSX QA 行解析与校验
- `backend/app/capabilities/rag/evaluation.py` — 无副作用的检索指标计算
- `backend/app/shareddomain/knowledge/legacy.py` — 旧版段落式批量导入文档的兼容服务
- `backend/app/shareddomain/knowledge/lifecycle.py` — 知识文档删除生命周期：清理分块、向量与磁盘文件
- `backend/app/tasks/knowledge.py` — Celery 任务定义：知识任务执行、外部存储清理及 Beat 周期恢复，失败自动重试

## 相关测试

- `backend/tests/knowledge.py` — 知识库端到端测试：CRUD/普通与 QA 导入/平铺与层级分块/引用图/混合检索/评测重试与恢复/任务租约/租户约束/权限/审计
