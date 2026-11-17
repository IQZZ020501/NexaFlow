# 私有项目文件

项目属于一个 workspace 和一个创建者。只有当前仍可访问该 workspace 的创建者可以管理或读取项目，workspace/global admin 没有额外文件权限。用于直接 Console Agent Run，公开聊天、API 消费者和 Workflow child Run 不继承私有项目。

应用列表和新 Agent 对话提供“项目文件”入口。新对话可选择项目，已有对话保留原绑定，切换项目需要新建对话。`/app/projects` 与 `/app/projects/[id]` 支持创建、重命名、上传、文件重命名、删除和历史下载；存在活动 Run 时拒绝删除整个项目。

| 内容 | guest 路径 | 持久化 |
| --- | --- | --- |
| 源资料 | `/project/sources/<相对路径>` | Run 冻结版本，root 所有、只读；模型不能重命名其父目录 |
| 工作文件、脚本 | `/workspace/project/<相对路径>` | 每次 bash 后按 Run 的版本游标与项目当前版本做原子 CAS 保存 |
| 交付文件 | `/workspace/outputs/<相对路径>` | 原有不可变 artifact、检查记录与授权下载 |

项目最多 64 个有效文件、64 MiB；单文件 1 字节至 5 MiB；历史最多 256 MiB、路径索引最多 256 项。工作树不保存 `.git`、`.venv`、`venv`、`node_modules`、`__pycache__`、`.cache`、`.nexaflow`，也不保存进程。受控 Skill 安装继续要求每次调用批准，当前 Run 保存精确安装计划和环境 hash，同 Run 的 guest 重建仍通过原有锁重放；新 Run 不会静默取得旧安装授权。

`agent_projects` 保存所有权与修订；`project_file_versions` 只追加字节、SHA-256、前版本、路径和删除标记；`project_run_states` 保存独立于模型 checkpoint 的文件游标与本 Run 的依赖锁。作者 id 为不透明历史值，无 users 外键；workspace 删除级联清理。Run 删除只清理其游标，项目文件中的 Run/invocation 身份不阻止历史保留。

上传、删除和重命名提交 `expected_version_id`，新路径为空。过时版本返回 409，精确重试不添加版本；重命名在一次事务中写旧路径删除标记与新路径版本。模型摘要不能改写项目身份，精确引用持续保留项目 id 和三个根路径。

每个 Run 冻结初始文件，工作游标随后前移。导入每个路径一次，不覆盖 guest 内编辑。每次 bash 返回有界的完整工作树清单，后端只读取 hash 已改变的文件，因此保存失败后下次命令仍可捕获改动。guest 重建从游标恢复并跳过删除标记。

保存前重新检查账号、workspace 和项目所有权，并锁定有效的 Run Worker 租约与项目。任一文件冲突会拒绝本批全部变更。冲突字节保留为本 Run 的 `.bin` 恢复 artifact，原路径与删除意图在 `project_conflicts` 返回；这些字节不宣称通过 Office/PDF 检查。`project_saved: false` 及原因直接返回模型。失租 Worker 不得写入项目或新 Worker 的游标。

API 前缀为 `/api/v1/workspaces/{workspace_id}/projects`：集合 GET/POST；项目 GET/PATCH/DELETE；文件 GET/POST/DELETE `/files`；重命名 POST `/files/rename`；历史 GET `/versions?path=...`；当前用户授权下载 GET `/versions/{version_id}/content`。迁移为 `202611160003`。

## 检查入口

从 `backend/` 运行 `uv run python -m tests.projects.api` 和 `uv run python -m tests.projects.runtime`；前端项目交互覆盖在 `frontend/tests/projects.test.tsx`。真实执行平面检查由 `tests.projects.opensandbox_smoke.check(settings)` 提供，只能使用隔离的控制面、数据库和 Redis；覆盖源文件写保护、guest 重建、跨 Run 恢复、重命名/删除与不可变交付文件。普通 Docker 检查不能证明 Kata 隔离。
