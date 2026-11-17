# NexaFlow 文档索引

本目录保留当前系统的使用、架构、模块和运维说明。安装入口见仓库根 [README](../README.md)。

## 安装与开发

| 文档 | 内容 |
| --- | --- |
| [部署说明](DEPLOYMENT.md) | 单机 Compose 安装、配置、升级、存储与本地开发 |
| [后端 README](../backend/README.md) | FastAPI 开发入口、Worker 角色、迁移和检查命令 |
| [前端 README](../frontend/README.md) | Next.js 开发、API 代理与检查命令 |
| [OpenSandbox 部署](../deploy/opensandbox/README.md) | 执行镜像、网络边界、可选 Kata 主机和执行平面检查 |

## 整体架构与技术层

项目采用[分层模块化单体](MODULAR_MONOLITH.md)：后端按技术层组织，每层内部按业务模块分包；前端独立使用 Next.js App Router。API、前端、后台 Worker 和 Agent Worker 在默认部署的同一个应用容器内运行，依赖 PostgreSQL、Redis、Qdrant 和 OpenSandbox。

| 文档 | 内容 |
| --- | --- |
| [模块化单体](MODULAR_MONOLITH.md) | 模块职责、公开接口、依赖方向与架构检查 |
| [HTTP API 与契约](API.md) | 认证、工作空间上下文、路由与 Pydantic Schema |
| [应用服务](APPLICATION.md) | 用例编排、跨模块协作与代码入口 |
| [能力端口与适配器](ADAPTERS.md) | LLM、MCP、向量库、执行平面和企业身份的契约与实现 |
| [基础设施](INFRA.md) | 配置、数据库、仓储、队列、安全、存储和 Alembic |
| [前端](FRONTEND.md) | 路由、功能组件、主题、三语词典、API 客户端与测试 |

## 功能与运行机制

| 文档 | 内容 |
| --- | --- |
| [Agent 运行时](AGENTS_RUNTIME.md) | 模型/工具循环、能力目录、持久 Run、事件与上下文 |
| [工作流](WORKFLOWS.md) | 图校验、节点、固定版本、审批与暂停恢复 |
| [知识库](KNOWLEDGE.md) | 文档解析、索引、BM25/向量检索与检索评测 |
| [身份与工作空间](IDENTITY_WORKSPACE.md) | 用户、租户、团队、资源权限与工具目录 |
| [Skills](SKILLS.md) | 版本化包、渐进加载、脚本、依赖安装与内置指南 |
| [对话文件](PROJECT_FILES.md) | 文件夹/ZIP 导入、对话工作文件、版本与交付 |
| [运行可靠性](RUN_RELIABILITY.md) | 请求幂等、文件身份、资源等待、准入与精确引用 |
| [执行主机](EXECUTION_HOSTS.md) | 可选多主机配置、固定放置、容量与故障边界 |
| [可信扩展](EXTENSIONS.md) | 扩展 API、生命周期与部署时组合 |
| [MCP OAuth](MCP_OAUTH.md) | 外部账号连接、授权状态与令牌生命周期 |
| [MCP 远端任务](MCP_TASKS.md) | 持久任务、轮询、取消与副作用状态 |
| [模型供应商](model-providers.md) | 仓库内供应商目录、协议与适配路径 |
| [企业身份](ENTERPRISE_IDENTITY.md) | 飞书、钉钉、企业微信登录配置 |
| [Agent 评测用法](AGENT_EVALUATION.md) | 确定性回归、在线评测命令、数据集与结果判定 |
