# KNOWLEDGE 模块（backend/app/shareddomain/knowledge + tasks）

## 职责

知识库业务领域：知识库/文档/分块/任务的状态机编排（解析 → 分块 → embedding → 向量入库），支持保持原行为的平铺分段与按 Markdown 章节生成 Parent + Child 的智能分段；仅 Child 进入检索索引。模块同时负责任务租约与失败重试、文档生命周期、知识库删除后的持久化外部存储清理，以及旧版段落式批量导入兼容。Celery 任务入口在 `tasks/`。

## 权限语义

- 同工作区成员可见全部知识库列表（响应 `permission` 字段为 view/edit/none），访问与写入仍按 view/edit 资源授权判定。
- 知识库归档后只读：写操作（上传/解析/索引/重建/改名/授权管理/删除）返回 403，仅工作区管理员或 owner 可恢复。
- owner（`created_by_user_id`）可通过 `PUT /knowledge-bases/{id}/owner` 转移给活动工作区成员；转移后原 owner 不再隐式享有 edit。

## 分层关系

```text
10:api/knowledge*.py → shareddomain/knowledge/services（CRUD/权限/上传落盘）
11:
12:## 文档导入流程（解耦形态）
13:
14:- 附件上传 `POST /documents/../attachments` 只持久化文件（`infrastructure/object_storage.py` 本地对象存储 adapter，对象 key 形如 `workspace/kb/attachments/<id>/<name>`），返回 attachment。
15:- 文档创建 `POST /documents` 接收 `attachment_ids` JSON，事务内消费附件并生成 staged 文档；解析/向量化一律走 Celery 任务（`POST /parse`、`POST /index`），请求内不再同步解析。
16:- 图片资产：DOCX 解析时经 Mammoth callback 抽取内嵌图片落对象存储，chunk 正文保留原子占位符（私有区字符）并用 `images[]` 结构化返回；前端经鉴权接口拉取 blob 渲染，不暴露对象路径。图片不参与向量化。
17:- 附件生命周期：available → consumed（创建文档）→ deleted（删除文档/知识库时对象一并清理）。
                 → orchestration（任务状态机编排）
                 → task_runner（执行体：租约锁/解析/向量化）
                 → tasks/knowledge.py（Celery 任务包装、删除清理与失败重试）
                 → capabilities/{embedding,rag,llm}（解析管道/Qdrant/embedding 模型）
```

## 文件清单

- `backend/app/shareddomain/knowledge/models.py` — 知识库/文档/Parent/Child 分块/任务/外部存储清理 ORM 模型及租户范围约束
- `backend/app/shareddomain/knowledge/services.py` — 知识库与文档服务层：CRUD、权限校验（view/edit 资源级）、上传落盘、模型绑定校验
- `backend/app/shareddomain/knowledge/cleanup.py` — 删除前创建持久清理记录，删除后幂等清理 Qdrant 与对象存储；失败按退避时间重试
- `backend/app/shareddomain/knowledge/orchestration.py` — 文档解析/索引/任务状态机编排：状态流转、冲突任务检测、embedding/rerank 模型解析
- `backend/app/shareddomain/knowledge/task_runner.py` — 知识任务执行体：租赁锁、解析/向量化/入库执行与失败标记
- `backend/app/shareddomain/knowledge/legacy.py` — 旧版段落式批量导入文档的兼容服务
- `backend/app/shareddomain/knowledge/lifecycle.py` — 知识文档删除生命周期：清理分块、向量与磁盘文件
- `backend/app/tasks/knowledge.py` — Celery 任务定义：知识任务执行、外部存储清理及 Beat 周期恢复，失败自动重试

## 相关测试

- `backend/tests/knowledge.py` — 知识库端到端测试：CRUD/上传解析/平铺与层级分块/Child 索引/混合检索/任务恢复/租户约束/权限/审计
