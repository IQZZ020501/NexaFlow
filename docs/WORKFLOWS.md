# 工作流

工作流与 Agent 共用应用目录、工作空间权限、模型、知识库、统一工具账本和持久 Run，节点调度由独立的确定性图引擎负责。画布定义是 React Flow JSON，不需要另写一套执行 DSL。

## 编辑、发布与资源绑定

画布支持草稿保存、校验、调试、节点状态和输入输出审计；草稿使用版本号检测并发修改。发布生成不可变版本，可将历史发布版本恢复为新草稿。Run 保存图与资源快照，后续编辑不会替换正在执行的定义。

知识库和模型必须在当前工作空间内可用；Tool 固定 `tool_id` / `version_id`，Agent 节点固定已发布的 Agent 版本，Skill 固定 `skill_id` / `version_id`。发布、排队与执行时会重新检查当前授权、停用状态及版本哈希；冻结快照不绕过撤权。

## 图与调度规则

- 图最多 200 个节点、500 条边，节点和边 ID 各自唯一。
- 恰好一个 Start 和一个 End；Start 无入边，End 无出边。所有节点从 Start 可达且都能到达 End，禁止环和自连。
- Condition 的每个分支、Classifier 的每个类别及默认分支必须各有一条出边。
- 节点配置由对应 Pydantic Schema 校验，节点引用必须指向拓扑上游。

边有 `unknown`、`taken`、`skipped` 三种状态。所有入边已确定且至少一条被选中的节点可以执行；所有入边都被跳过的节点继续向下游传播跳过。普通节点成功后选择全部出边，条件和分类节点只选择命中的分支。

同一就绪波次可并行执行，状态合并和持久化按画布节点顺序处理。节点失败会终止运行；同波次已经启动的节点仍会完成并记录结果。引擎不提供图内循环、隐式失败重试或失败分支。

## 节点

| 类型 | 行为 |
| --- | --- |
| Start / End | 提供问题与全局上下文；汇总最终输出 |
| LLM | 模型生成，支持提示词、对话历史、MCP 工具与工作空间 Skill |
| Classifier | 按预设类别选择分支，未命中时走默认分支 |
| Knowledge | 使用生产知识检索链路召回内容 |
| Reranker | 对候选内容重排 |
| Form | 持久暂停并等待输入，提交后恢复 |
| Document Extract | 读取经授权上传的文件内容 |
| Condition | 按配置规则选择分支 |
| Reply | 渲染自定义 Jinja2 回复，或引用一个上游字段 |
| Variable | 解析并输出配置值 |
| Tool | 调用允许用于工作流的固定版本工具 |
| Agent | 创建固定发布版本的持久子 Run，等待其结果 |

契约还保留 `template` 和 `mcp` 类型用于已有定义。独立 Python Tool 和 Python Code 节点已移除；文件处理可通过获授权的 MCP、工作空间 Skill 或 Agent 节点完成。内置文档指南加载器只供 Agent 使用，不能直接绑定为工作流 Tool 节点。

LLM 节点只可加载自己选择的 Skill，不能使用其他节点的 Skill。服务端根据授权的 Skill 构造能力工具，客户端提交的 `capability_tools` 不作为授权依据。具体包格式和脚本限制见 [Skills](SKILLS.md)。

## 引用与回复

配置值支持 `{{node_id.field}}`。当整个值就是一个引用时，保留原始 JSON 类型；嵌入其他文字时转换为文本。全局值包括 `time`、`history_context`、`chat_id`、`start_time`，也可使用 `{{global.time}}` 形式。

自定义 Reply 使用沙箱化的 Jinja2 和严格未定义变量检查，变量缺失会使节点失败。引用式 Reply 只读取所选上游字段并转为文本。Form 有自己的模板和提交校验，表单输入不能获得额外工具权限。

## 持久执行与交互

运行复用 `agent_runs`、`agent_run_states`、`agent_run_snapshots`、`agent_run_events`，工作流版本、运行详情和节点审计保存在独立工作流表。所有工具调用写入唯一的 `tool_invocations` 账本。

节点转换时，在同一个租约检查事务内保存节点记录、引擎 checkpoint、运行详情和事件。Worker 重试从 checkpoint 恢复；首次认领建立的整体 deadline 不会重置。流式观察断开不取消 Run。

Form 等待、Agent 子运行和工具审批分别保存为可恢复状态。LLM 工具循环会先保存模型决策再执行工具，审批恢复沿用原决策和调用身份。多个节点同时请求审批时，全部决定后才恢复。API Key 消费者不能执行需要交互审批的工具；依赖安装器也不会向 API 模型开放。

调用者必须保有当前工作空间和应用访问权。公开应用的资料可匿名读取，提交和观察 Run 仍需登录成员身份；系统集成使用应用级 API Key。工具的副作用不确定状态不会被自动当作安全重试。

## 代码入口与检查

| 路径 | 职责 |
| --- | --- |
| `backend/app/schemas/workflows/contracts.py` | 图、节点配置、运行和交互契约 |
| `backend/app/domain/workflows/runtime/engine.py` | 图校验、边状态、调度与 checkpoint |
| `backend/app/domain/workflows/definitions/` | 定义、版本和 Skill 绑定规则 |
| `backend/app/application/workflows/definitions/service.py` | 草稿、发布和版本用例 |
| `backend/app/application/workflows/runs/` | 提交、租约执行、暂停恢复和终态 |
| `backend/app/application/workflows/nodes/` | 节点执行与能力组合 |
| `backend/app/application/workflows/tools/runtime.py` | 统一工具账本适配 |
| `backend/app/api/v1/workflows/` | 工作空间、公开和 API Key 接口 |
| `frontend/src/components/workflows/` | 画布、配置、运行面板与公开对话 |

从 `backend/` 按影响范围运行：

```bash
uv run python -m tests.workflows.unit
uv run python -m tests.workflows.workflows
uv run python -m tests.workflows.capabilities
uv run python -m tests.workflows.workflow_node_coverage
uv run python -m tests.workflows.workflow_run_coverage
```

工具权限、执行隔离和资源等待的共用机制见 [Agent 运行时](AGENTS_RUNTIME.md)、[运行可靠性](RUN_RELIABILITY.md) 和 [OpenSandbox 部署](../deploy/opensandbox/README.md)。
