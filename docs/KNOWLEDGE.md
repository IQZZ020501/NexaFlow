# KNOWLEDGE 模块（backend/app/shareddomain/knowledge + tasks）

## 职责

知识库业务领域：知识库/文档/分块/任务的状态机编排（解析 → 分块 → embedding → 向量入库），任务租约与失败重试，文档生命周期（删除清理分块/向量/磁盘文件），旧版段落式批量导入兼容。Celery 任务入口在 `tasks/`。

## 分层关系

```text
api/knowledge*.py → shareddomain/knowledge/services（CRUD/权限/上传落盘）
                 → orchestration（任务状态机编排）
                 → task_runner（执行体：租约锁/解析/向量化）
                 → tasks/knowledge.py（Celery 任务包装，失败重试）
                 → capabilities/{embedding,rag,llm}（解析管道/Qdrant/embedding 模型）
```

## 文件清单

- `backend/app/shareddomain/knowledge/models.py` — 知识库/文档/分块/任务 ORM 模型
- `backend/app/shareddomain/knowledge/services.py` — 知识库与文档服务层：CRUD、权限校验（view/edit 资源级）、上传落盘、模型绑定校验
- `backend/app/shareddomain/knowledge/orchestration.py` — 文档解析/索引/任务状态机编排：状态流转、冲突任务检测、embedding/rerank 模型解析
- `backend/app/shareddomain/knowledge/task_runner.py` — 知识任务执行体：租赁锁、解析/向量化/入库执行与失败标记
- `backend/app/shareddomain/knowledge/legacy.py` — 旧版段落式批量导入文档的兼容服务
- `backend/app/shareddomain/knowledge/lifecycle.py` — 知识文档删除生命周期：清理分块、向量与磁盘文件
- `backend/app/tasks/knowledge.py` — Celery 任务定义：`run_knowledge_task_job` 包装知识任务执行体，失败自动重试

## 相关测试

- `backend/tests/knowledge.py` — 知识库端到端测试：CRUD/上传解析/分块索引/混合检索/任务恢复/权限/审计
