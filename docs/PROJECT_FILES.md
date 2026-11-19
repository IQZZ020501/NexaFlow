# 对话文件

控制台和公开 Agent 对话都支持直接上传文件、文件夹或 ZIP。上传后直接提问，无须创建项目或选择绑定；旧版后台独立文件项目页面和管理 API 已移除。浏览器文件夹选择和目录拖入保留相对路径，单独选择的 ZIP 在导入时展开并保留内部路径；文件夹和 ZIP 内嵌的 ZIP 作为原始文件保留。普通文档仍提供有界文本摘录，原始文件同时进入对话文件树，Agent 可按需读取、修改和运行脚本。

## 公开 Agent 个人项目

登录用户可以在已发布 Agent 的聊天侧栏创建项目，将多段对话归入同一项目，并上传共享资料。项目右侧的「…」菜单提供编辑、归档／恢复和解散操作；编辑弹窗仅管理项目名称和资料。项目限定于当前 workspace、Agent 和用户，仅所有者可见；工作流公开聊天暂不提供项目。项目有稳定入口 `/chat/{agent_id}/projects/{project_id}`，可直接打开或刷新，具体对话通过 `conversation_id` 查询参数定位。

共享文件版本及既有项目说明在每个 Run 创建时冻结，后续修改从下一次发送起生效。共享资料恢复到只读的 `/project/sources/{project_id}/`，可以复制到当前对话的 `/workspace/project/` 再编辑；各段对话的历史、可编辑文件和生成文件仍独立。既有项目说明及 API 契约保留，不会提升 Agent 权限或授予新工具；界面已移除项目说明和「从当前对话保存」入口。资料预览仍使用右侧分栏，复用已有文件配额、路径检查和隔离预览机制。

已有对话可移入、移出项目，运行中的对话需先完成。归档项目保留全部内容，恢复后可继续发送和修改资料；解散项目会把对话移回普通历史记录，并保留历史回答、生成文件和 Run 引用的不可变资料版本。删除单段对话不会删除项目共享资料。

`202611190002` 迁移增加 `chat_projects` 和 `chat_conversations`，元数据与资料文件树分别保存；应用删除时统一清理，资料历史随 workspace 删除。公开项目 API 位于 `/api/v1/public/agents/{agent_id}/projects`，对话归属通过 `/conversations/{conversation_id}/project` 修改，均要求登录及对应已发布应用的访问权限。

## 保存与隔离

文件树按 workspace、Agent、访问来源、当前使用者和 conversation 隔离。公开对话的文件属于聊天用户，模型、工具和 Skill 仍按发布者的执行授权运行，两种身份分别校验。API 消费者与 Workflow child Run 不自动继承交互对话文件。

每个直接交互 Run 自动冻结文件版本，并在执行前恢复到 `/workspace/project/`。后续命令不会覆盖同一 guest 中的编辑；guest 重建会从 Run 文件游标恢复。每次 bash 后保存完整工作树中的变更、重命名和删除，后续消息及重新打开同一对话可继续使用。运行依赖和进程不随文件持久化，新的 Run 不继承依赖安装审批。

交付文件仍写入 `/workspace/outputs/`，复用已有的不可变 artifact、文件检查、预览和下载；Agent 可复制单个工作文件或生成 ZIP 进行交付。聊天附件属于输入，导入文件不会自动成为经过检查的输出。

## 边界

普通单独附件保留原有总计 100 MiB 的上传与文本摘录能力；超过 5 MiB 的单独文档或图片仅提供有界文本摘录，界面会标注，原件不进入可编辑文件树。文件夹和 ZIP 的展开内容按下列文件空间配额校验。

每段对话最多保存 64 个有效文件、合计 64 MiB，单个展开后的文件不超过 5 MiB，保留空文件；历史最多 256 MiB，路径索引最多 256 项。ZIP 最多检查 4096 个条目，拒绝无效路径、重复路径、文件/目录冲突、链接、特殊文件、加密条目以及超限或损坏的内容。解压不会执行代码或授予能力。

依赖目录、缓存和 Git 元数据不导入或保存：`.git`、`.venv`、`venv`、`node_modules`、`__pycache__`、`.cache`、`.nexaflow`；导入同时跳过 `__MACOSX` 和 `.DS_Store`。文件夹上传只发送用户选中的文件，不读取本地其他目录。

保存前重新校验用户、workspace、文件所有权与 Run Worker 租约。批次使用版本比较及原子保存，失租 Worker 不得写入；冲突不会覆盖现有版本，恢复字节保留为本 Run 的 artifact，并明确返回保存失败。

## 数据兼容与清理

内部继续复用 `agent_projects`、`project_file_versions` 和 `project_run_states` 保存不可变字节、SHA-256、删除标记与 Run 文件游标，由 `202611170007` 迁移放宽上传记录、清理队列和持久文件中必须非空的约束，保留文件夹中的空 `__init__.py` 等文件。文件树身份由服务端从对话确定，客户端不提交项目 id。

已有对话绑定的旧项目在下一次消息时复制为该对话的独立工作树，保留原有字节；历史快照与旧独立项目数据不被重写或删除。删除对话或应用时，在同一事务内清理其自动创建的文件树和版本；旧独立项目数据仍随 workspace 删除级联清理。

## 检查入口

从 `backend/` 运行 `uv run python -m tests.projects.api`、`uv run python -m tests.projects.migration`、`uv run python -m tests.projects.runtime` 和 `uv run python -m tests.projects.chat`，覆盖 ZIP 导入、路径及配额、真实上传/Run 持久化、公开用户隔离、项目生命周期、不可变共享资料、跨 Run 恢复、旧字节保留、失租拒写和删除清理。新约束需应用迁移，执行镜像需包含当前 `sandbox/command.py`；标准 `make dev` 会根据输入变化构建镜像并执行迁移。前端入口与目录路径覆盖在 `frontend/tests/agent-file-picker.test.tsx`、`frontend/tests/public-chat-projects.test.tsx` 及 Agent 对话套件。执行 guest 的文件恢复和工作树导出由 `sandbox/command_tests.py` 覆盖；这些测试不代表 Kata 隔离验收。
