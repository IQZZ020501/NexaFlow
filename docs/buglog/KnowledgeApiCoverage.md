# KnowledgeApiCoverage 子任务 BUG 记录

> 测试套件: `backend/tests/knowledge_api_coverage.py`
> 覆盖模块: knowledge / knowledge_lifecycle / knowledge_retrieval 端点,
> `app.application.knowledge`, `app.capabilities.rag.retrieval`,
> `app.capabilities.rag.vector_store`, `app.capabilities.embedding.pipeline`

## 发现的 BUG / 观察

### medium: 知识库重命名冲突返回 500 而非 409

- 编号: BUG-knowledge-001
- 严重度: medium
- 模块: `backend/app/shareddomain/knowledge/kb.py::update_knowledge_base`
- 现象: `PATCH /api/v1/workspaces/{ws}/knowledge-bases/{id}` 将 `name` 改为
  工作区内已存在的名称时返回 500（`sqlalchemy.exc.IntegrityError` 冒泡到
  端点层），而非 409。原因: `save_knowledge_base()`（内部 flush）在
  `try/except IntegrityError`（只包住 `db.commit()`）之外执行，唯一约束
  冲突在 flush 时抛出，未被捕获。
- 预期: 与创建路径一致返回 `409 Conflict`（"Knowledge base name already
  exists."）。
- 复现: 创建两个知识库 A、B；以 B 的 owner 身份 `PATCH B {name: A.name}`，
  观察 500 + `sqlite3.IntegrityError: UNIQUE constraint failed:
  knowledge.workspace_id, knowledge.name`。
- 来源: `tests.knowledge_api_coverage.py`（测试中按实际行为移除该断言，
  仅记录）

### test-infra: 套件共享知识库存储目录导致并行运行互相删除文件

- 编号: BUG-testinfra-002
- 严重度: test-infra (high)
- 模块: `backend/tests/support.py`（`KNOWLEDGE_STORAGE_DIR` 固定为
  `/tmp/app-test-knowledge-storage`）
- 现象: 所有套件共用一个存储根目录；每个 `test_client()` 块启动时
  `shutil.rmtree` 整个目录。多个套件并行执行时，后启动的套件会删掉其他
  套件已上传的文档文件，解析任务随机报 `KnowledgePipelineError: Document
  file is missing.`，测试偶发失败（同一套件先后失败点不一致）。
- 预期: 每个测试进程使用独立的存储目录（如按 PID 区分）。
- 复现: 并行运行两个及以上包含知识库上传/解析流程的套件，观察随机的
  "Document file is missing." 失败。
- 来源: `tests.knowledge_api_coverage.py`（本套件通过
  `KNOWLEDGE_STORAGE_DIR=<pid 后缀目录>` + `dataclasses.replace` 覆盖
  `support.settings()` 规避；建议统一修复 support.py）

### 观察: 重复文档名不存在冲突分支

- 编号: BUG-knowledge-002 (observation)
- 严重度: low (无行为缺陷)
- 模块: `backend/app/shareddomain/knowledge/documents.py`
  (`create_knowledge_documents_from_attachments`)
- 现象: 同一知识库内可以创建多个 `filename` 相同的文档（文档文件名无唯一
  约束），代码中不存在"重复文档名冲突"分支。任务清单中期望的 409 冲突
  分支在该模块中不可达。
- 预期: 无（产品未设计该约束）；测试按"允许同名"处理。
- 来源: `tests.knowledge_api_coverage.py`
