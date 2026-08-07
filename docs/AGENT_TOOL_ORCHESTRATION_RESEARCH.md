# Dify Agent 工具编排研究

> 调研时间：2026-08-07。只使用 Dify 官方文档和官方 GitHub 源码。源码固定在
> [`42d6589ce28923e0045d56e13b48b1452f5a7db8`](https://github.com/langgenius/dify/tree/42d6589ce28923e0045d56e13b48b1452f5a7db8)，避免后续主分支变化使结论失真。

## 结论

1. Dify 有两条清晰可见的知识编排路径：经典 Agent 把普通工具和 Dataset Retriever 一起暴露给模型；当前 Agent v2 则把 dataset retrieval 排除在普通工具层之外，改为独立 knowledge layer，并按 `user_query`（进入运行时立即检索）或 `generated_query`（模型调用统一知识搜索工具）选择路径。业务要求“必须先查知识库”时应选 eager/显式检索路径，而不是只靠提示词。
2. Dify 把工具执行收口到统一的 `ToolEngine`：参数归一化、回调、响应转换、文件处理、错误映射和耗时元数据不散落在 Agent 循环中；插件调用同时携带租户、用户、会话、应用、消息、凭据类型和工具参数。
3. Dify 的 Function Calling 与 ReAct runner 都设置迭代上限，并在最后一轮移除工具，让模型只能收束为最终回答；这比达到上限后直接中断更完整。
4. 持久执行需要与模型决策循环分层。Dify 的异步 Workflow/HITL 路径使用 Celery、持久暂停状态和序列化图状态恢复；核心 Agent 循环本身不是完整的任务接管、租约和副作用幂等系统。Dify 新 Agent runtime 的官方运维文档也明确说明，同进程 `asyncio` 调度没有队列恢复，进程崩溃可能遗留 `running` 状态。

## 1. 模型如何选择工具

Dify 官方文档把 Agent 定义为由 LLM 自主、迭代地决定“何时使用哪个工具”；Function Calling 会把工具定义放入模型的 `tools` 参数，ReAct 则使用 `Thought -> Action -> Observation` 循环。文档同时明确指出，工具描述会直接影响模型的选择，因此工具名、适用范围和参数 schema 都属于路由输入，而不是装饰信息。[Dify Agent 官方文档](https://docs.dify.ai/en/cloud/use-dify/nodes/agent)

经典源码路径中，`BaseAgentRunner` 先从租户和应用配置解析普通工具的 LLM 描述与 JSON schema，再把配置的普通工具和 Dataset Retriever 追加到同一个 `prompt_messages_tools` 列表；Function Calling runner 随后把该列表传给模型。该路径没有知识库优先于其他工具的确定性分支，所以同时暴露知识库和 MCP 时，最终选择取决于模型、描述、上下文和当前 observation。[普通工具与 Dataset Retriever 的同一工具列表](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/agent/base_agent_runner.py#L141-L217) [工具列表传入模型](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/agent/fc_agent_runner.py#L114-L178)

## 2. Dataset Retriever 与 Knowledge Retrieval

### 经典 Dataset Retriever：Agent 可选工具

Agent 配置了知识库时，Dify 会按已选 `dataset_ids` 构建 Dataset Retriever；该实现要求 retrieval config，并明确将 Agent 检索限制为 `SINGLE` 模式。工具向模型暴露一个必填 `query` 字符串，执行结果作为工具 observation 返回。因此它仍处在模型决策循环内，模型可以不调用、重复调用或改写查询。[Dataset Retriever 构建与 SINGLE 模式](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/tools/utils/dataset_retriever_tool.py#L29-L90) [查询参数与调用](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/tools/utils/dataset_retriever_tool.py#L92-L136)

### Agent v2：独立 knowledge layer

当前 Agent v2 的工具构建器明确拒绝把 `dataset-retrieval` 放进普通 Agent 工具层；plugin、builtin、API、workflow 和 MCP 工具走 tool layers，知识库走单独的 knowledge path。运行请求也分别携带 `tools/core_tools` 与 `knowledge` 配置，后者保留知识集名称、描述、dataset refs、query policy、retrieval 和 metadata filtering。[Agent v2 工具层边界](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/workflow/nodes/agent_v2/dify_tools_builder.py#L151-L226) [拒绝 dataset-retrieval 进入工具层](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/workflow/nodes/agent_v2/dify_tools_builder.py#L351-L372) [独立构建 knowledge 配置](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/workflow/nodes/agent_v2/runtime_request_builder.py#L219-L269) [知识集配置映射](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/workflow/nodes/agent_v2/runtime_request_builder.py#L757-L792)

knowledge layer 内部再按查询策略分流：`generated_query` 知识集暴露一个固定的 `knowledge_base_search(set_name, query)` 工具，由模型选知识集和查询；`user_query` 知识集则在 layer 进入/恢复时立即检索，把结果作为额外 user prompt 注入，并把结果及配置指纹保存为可序列化 runtime state，避免相同配置恢复时重复检索。[两种查询策略](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/dify-agent/src/dify_agent/layers/knowledge/layer.py#L1-L8) [generated_query 工具](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/dify-agent/src/dify_agent/layers/knowledge/layer.py#L97-L165) [user_query eager 检索与快照状态](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/dify-agent/src/dify_agent/layers/knowledge/layer.py#L167-L286)

### Knowledge Retrieval：确定性工作流节点

Knowledge Retrieval 节点从工作流变量读取 query，使用节点预先选择的 dataset IDs、检索模式、Top K、阈值、rerank 和元数据过滤配置执行检索，并输出结构化 `result`。这是显式工作流边：流程到达该节点就会检索，不依赖 Agent 在多个工具中选择。[Knowledge Retrieval 官方文档](https://docs.dify.ai/en/cloud/use-dify/nodes/knowledge-retrieval) [节点读取 query 并执行检索](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/workflow/nodes/knowledge_retrieval/knowledge_retrieval_node.py#L99-L224) [多知识库检索参数](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/workflow/nodes/knowledge_retrieval/knowledge_retrieval_node.py#L226-L294)

因此，三种产品语义应分开：

- “复杂任务中由模型按需选择知识集并改写查询”使用 `generated_query` 知识工具。
- “进入 Agent 前必须用指定查询取证”使用 `user_query` eager knowledge layer。
- “回答前必须以指定知识库为依据”使用确定性 Knowledge Retrieval 路径，再把结果交给 LLM 或 Agent。

## 3. ToolEngine 与插件边界

`ToolEngine.agent_invoke` 统一处理字符串参数归一化、工具开始/结束/失败回调、文件响应转换、面向模型的文本 observation，以及凭据、工具不存在、参数校验和执行异常。内部 `_invoke` 记录工具配置、错误和耗时元数据。这使 Agent runner 只负责循环和状态推进，不直接复制每种工具的协议细节。[ToolEngine Agent 调用入口](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/tools/tool_engine.py#L43-L157) [统一执行元数据](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/tools/tool_engine.py#L205-L238)

插件调用通过租户作用域的 daemon 路径发送 `user_id`、`conversation_id`、`app_id`、`message_id`，并携带 provider、tool、credentials、credential type 和 tool parameters。Dify Agent 的插件层文档进一步规定：API 侧先解析用户选中的工具、凭据和隐藏/manual 参数，只把允许模型填写的 schema 暴露给模型。[插件调用身份与凭据](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/plugin/impl/tool.py#L85-L127) [插件工具层职责](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/dify-agent/docs/dify-agent/user-manual/plugin-tool-layer/index.md#L12-L49) [API 侧预解析约束](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/dify-agent/docs/dify-agent/user-manual/plugin-tool-layer/index.md#L118-L130)

## 4. 迭代上限与最后一轮

Function Calling runner 将最大执行步数设为 `min(configured_max, 99) + 1`。达到最后一步时清空工具列表，再调用一次模型；若模型仍返回工具调用则抛出最大迭代错误。ReAct runner 也在最后一步移除可选工具，并拒绝非 `Final Answer` 动作。[Function Calling 最后一轮无工具](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/agent/fc_agent_runner.py#L119-L178) [Function Calling 上限错误](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/agent/fc_agent_runner.py#L299-L331) [ReAct 最后一轮与终止检查](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/agent/cot_agent_runner.py#L104-L191)

这实现了两个不同的预算：最多 N 轮工具行动，再保留一次只生成最终答案的收束机会。官方文档也把 Max Iterations 定义为防止无限循环和失控成本的安全上限。[Dify Agent 执行控制](https://docs.dify.ai/en/cloud/use-dify/nodes/agent#execution-controls)

## 5. 生产持久执行边界

Dify 核心 Function Calling runner 在每次等待模型前提交并关闭数据库 session，工具调用后也提交 session；它会持久化 thought 并发布事件，但循环仍在当前 runner 内连续执行。这些代码提供事务边界、审计记录和流式观察，不等同于崩溃后从某个工具调用断点自动接管。[模型等待前释放事务](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/agent/fc_agent_runner.py#L145-L178) [工具调用与 observation 持久化](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/core/agent/fc_agent_runner.py#L305-L394)

Dify 的异步 Workflow 路径另有 Celery 任务和持久恢复机制：任务先更新 trigger log，再执行 workflow；暂停恢复任务从 `WorkflowPause` 读取序列化的 `GraphRuntimeState`，重建 repository 后调用 `generator.resume`。`WorkflowPause` 表保存恢复所需的状态对象引用，并以 workflow run 唯一约束保证一对一的活动暂停记录。[异步 Workflow Celery 执行](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/tasks/async_workflow_tasks.py#L53-L200) [序列化图状态恢复](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/tasks/async_workflow_tasks.py#L203-L302) [WorkflowPause 持久模型](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/api/models/workflow.py#L2087-L2152)

边界必须明确：Dify 新 Agent runtime 的官方运维文档写明，`POST /runs` 虽会持久化 run record，但执行仍是同进程 `asyncio` task，没有 Redis job stream、pending reclaim 或自动重试；硬崩溃可能让 run 永久停在 `running`，Redis 只提供跨实例的状态/事件可见性，不提供负载均衡或任务恢复。[Dify Agent 调度与故障边界](https://github.com/langgenius/dify/blob/42d6589ce28923e0045d56e13b48b1452f5a7db8/dify-agent/docs/dify-agent/guide/index.md#L257-L285)

## 对 NexaFlow 的直接约束

- 保留模型自主选工具时，只暴露当前身份和工作空间允许的 effective allowlist；MCP 描述必须具体，隐藏参数和凭据不能进入模型 schema。
- 知识库应有独立于 MCP 的 query policy：`required/eager` 进入 Agent 前检索，`agentic/generated` 才暴露模型可调用的知识工具；不要把“KB first”只写成提示词后宣称为确定性保证。
- Agent 循环应保留工具调用上限、整次运行 deadline、单工具 timeout、无新增证据停止条件和最后一轮无工具收束。
- 当前在线请求路径可承载知识检索和审核过的只读 MCP。带副作用的 MCP 在开放前仍需独立 Durable Executor：持久 run/tool-call ledger、队列 worker、租约与超时接管、`run_id + tool_call_id` 幂等、审批/恢复，以及断线后的事件重放。Dify 的源码说明这些能力属于 workflow/执行基础设施边界，不能由提示词或一次 HTTP/SSE 循环替代。
