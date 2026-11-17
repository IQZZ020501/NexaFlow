# NexaFlow Backend

FastAPI 后端，使用 Python >=3.11、SQLAlchemy `AsyncSession`、PostgreSQL、Celery、Redis 和 Qdrant。整体采用[分层模块化单体](../docs/MODULAR_MONOLITH.md)，代码入口见[文档索引](../docs/INDEX.md)。

## 本地开发

完整开发环境从仓库根启动：

```bash
make dev
```

该入口准备依赖、私有根 `.env`、基础设施和数据库迁移，再统一托管 API、Worker 和前端。只调试后端时，在 `backend/` 运行：

```bash
make dev
```

后端入口使用仓库根 `.env`，不创建第二份环境文件。部署使用根 `docker-compose.yml` 显式配置，见[部署说明](../docs/DEPLOYMENT.md)。

## 后台任务

在 `backend/` 启动本地混合 Worker：

```bash
make worker
```

`scripts/worker.py` 要求 `OPENSANDBOX_API_KEY`，并支持以下角色：

| 角色 | 队列与调度 |
| --- | --- |
| `all`（默认） | 消费 `celery`、`agents-legacy`、`agents-v2`，内嵌 Beat，用于本地开发 |
| `background` | 只消费 `celery`，内嵌唯一 Beat |
| `agents` | 消费两个 Agent 队列，使用线程池，不启动 Beat |

按角色启动示例：`uv run python scripts/worker.py --role agents`。部署的 `app` 容器分别运行 `background` 和 `agents` 两个进程；包含 Beat 的进程只能有一个，不能横向扩容整个 `app` 容器。

API 和 Worker 必须共用 PostgreSQL、Redis、`KNOWLEDGE_STORAGE_DIR` 和 `QDRANT_URL`。bash、Skill 脚本和 stdio MCP 通过独立 OpenSandbox 执行；业务进程没有宿主执行回退。配置与检查见 [OpenSandbox README](../deploy/opensandbox/README.md)。

## 数据库迁移

在 `backend/` 运行：

```bash
uv run python -m alembic heads
uv run python -m alembic history
make migrate
```

历史迁移是新安装和已有数据库升级的一部分，应与代码一起保留。生产由 Compose 的一次性 `migrate` 服务执行升级，应用等待其成功后启动。

## 常用检查

以下命令均在 `backend/` 运行：

```bash
uv run python -m compileall -q app tests main.py
uv run python scripts/dependency_matrix.py --check
uv run python -m tests.smoke.test_main
uv run python -m tests.infra.architecture
```

按改动运行 `uv run python -m tests.<feature>.<suite>`；套件清单见 `scripts/coverage.py`，CI 范围见 [ci.yml](../.github/workflows/ci.yml)。完整覆盖率使用 `make coverage`，当前后端门槛为 97%。真实模型评测的参数与数据集见 [Agent 评测用法](../docs/AGENT_EVALUATION.md)。
