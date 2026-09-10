# Agent 生产评测门禁

Agent 评测分成两层：CI 中的确定性运行时回归，和部署/发布前对真实 Agent 的在线评测。前者阻止执行内核、工具安全和 grounding 预算逻辑回退；后者验证当前模型、知识、提示词和工具组合的实际质量。

## CI 门禁

从 `backend/` 运行：

```bash
uv run python -m tests.agents.evaluation
```

该套件不访问数据库、网络或第三方模型，覆盖直接回答、工具选择与成功执行、grounding、必需用例门禁、未上报 token 拒绝以及 grounding 调用纳入 token 总预算。它已接入 GitHub Actions 和后端覆盖率套件。

## 在线发布门禁

复制并按具体 Agent 修改 [examples/agent-evaluation.json](examples/agent-evaluation.json)。生产数据集建议至少覆盖 20–50 个稳定用例，并包含以下类别：

- 关键业务答案和拒答边界；
- `required` / `agentic` 知识检索与证据不足场景；
- 每个允许工具、禁止工具和参数校验场景；
- 提示注入、越权访问、敏感信息和高成本输入；
- 历史上出现过的线上缺陷。

使用具有目标工作区和 Agent 访问权限的短期登录令牌运行：

```bash
export NEXAFLOW_EVAL_TOKEN='replace-with-short-lived-token'
uv run python -m scripts.agent_eval \
  --base-url https://nexaflow.example.com \
  --workspace-id WORKSPACE_ID \
  --agent-id AGENT_ID \
  --dataset ../docs/examples/agent-evaluation.json \
  --output /tmp/nexaflow-agent-evaluation.json
```

令牌只能通过 `NEXAFLOW_EVAL_TOKEN` 提供，不会写入报告。`base-url`、工作区和 Agent 也可分别通过 `NEXAFLOW_EVAL_BASE_URL`、`NEXAFLOW_EVAL_WORKSPACE_ID`、`NEXAFLOW_EVAL_AGENT_ID` 提供。

退出码：`0` 表示门禁通过，`1` 表示质量门禁未通过，`2` 表示数据集、认证或 API 执行错误。报告只包含用例 ID、分类、样本序号、Agent Run ID 和失败规则，不保存问题、回答、证据正文或访问令牌。

## 数据集契约

每个用例支持：

- `samples`：同一问题重复执行次数，用于发现模型波动；
- `required`：默认为 `true`，任一必需样本失败都会阻断发布，即使总通过率达到阈值；
- `expect.status`：预期 Run 终态；
- `grounding_statuses`：允许的 `grounded`、`insufficient`、`unavailable` 或 `skipped`；
- `answer_contains` / `answer_not_contains`：稳定、短小的答案断言；
- `required_tool_names` / `forbidden_tool_names`：成功调用和绝对禁止观察到的工具；
- `min_sources`：API 返回的最少证据源数量；
- `max_total_tokens` / `max_model_calls` / `max_duration_ms`：成本与延迟上限。

设置 `max_total_tokens` 时，只要任一模型调用没有报告 usage，该样本就以 `usage:unreported` 失败，门禁不会猜测 token。在线运行遇到人工审批或输入等待会立即结束采样，并以当前 Run 状态参与断言；自动发布门禁使用的 Agent 应只绑定可自动执行的只读工具。

## 发布流程建议

1. PR 必须先通过确定性 CI 门禁。
2. 在与生产相同的模型、知识版本、工具策略和环境变量下运行在线数据集。
3. 保存不含内容的 JSON 报告作为发布证据；失败时根据用例 ID 定位服务端 Run 和审计事件。
4. 模型凭据、请求参数或知识权限在 Run 创建后发生漂移时，运行会失败关闭，应重新创建评测 Run，而不是继续使用失真的旧上下文。
