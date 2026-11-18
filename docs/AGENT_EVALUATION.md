# Agent 评测用法

Agent 评测分成两层：CI 中的确定性运行时回归，和部署/发布前对真实 Agent 的在线评测。前者阻止执行内核、工具安全和通用能力循环回退；后者验证当前模型、知识、提示词和工具组合的实际质量。

## CI 门禁

从 `backend/` 运行：

```bash
uv run python -m tests.agents.evaluation
uv run python -m tests.agents.evaluation_files
uv run python -m tests.agents.harness
```

前两个套件不访问数据库、网络或第三方模型，覆盖直接回答、可选工具选择与成功执行、无 manifest 的即时流式回答、知识/MCP/Skill 工具的统一预算、必需用例门禁及未上报 token 拒绝。harness 套件另外使用隔离数据库和本地模拟模型，覆盖大目录中的指南可见性、Schema 上限、逐轮预算反馈、恢复计数，以及不同访问来源的隔离。它们已接入 GitHub Actions 和后端覆盖率套件。

Word 批量检查、合并单元格地址、缓存失效和真实文件重开回归从仓库根目录运行 `uv run --project sandbox python -m sandbox.tests`；执行镜像还须以 UID 65532 运行其 `self_check.py`。这些检查只验证确定行为，不替代真实模型评测。

## 在线发布门禁

为目标 Agent 编写本地 JSON 数据集。下面的最小示例可保存为 `/tmp/nexaflow-agent-evaluation-cases.json`，用于检查直接回答与断言链路：

```json
{
  "gate": {"minimum_pass_rate": 1.0},
  "cases": [
    {
      "id": "direct-answer",
      "goal": "计算 12 加 8，只输出结果数字。",
      "expect": {"answer_contains": ["20"]}
    }
  ]
}
```

该例只说明格式。实际数据集应覆盖具体业务，并加入以下类别：

- 关键业务答案和拒答边界；
- 可选知识检索、没有检索和检索无结果场景；
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
  --dataset /tmp/nexaflow-agent-evaluation-cases.json \
  --output /tmp/nexaflow-agent-evaluation.json
```

令牌只能通过 `NEXAFLOW_EVAL_TOKEN` 提供，不会写入报告。`base-url`、工作区和 Agent 也可分别通过 `NEXAFLOW_EVAL_BASE_URL`、`NEXAFLOW_EVAL_WORKSPACE_ID`、`NEXAFLOW_EVAL_AGENT_ID` 提供。

退出码：`0` 表示门禁通过，`1` 表示质量门禁未通过，`2` 表示数据集、认证或 API 执行错误。报告 schema v2 保存用例标识、逐轮 Run、失败规则、耗时、实际用量、模型/工具/Skill 版本指纹及文件 ID/hash/检查状态，不保存问题、回答、文件正文或访问令牌。没有上报的用量保持缺失。

## 数据集契约

每个用例的 `id`、`goal` 必填，`category` 默认 `general`，`expect.status` 默认 `succeeded`。以下答案、工具、来源、成本和文件断言均放在 `expect` 对象内：

- `id` / `goal` / `category`：用例标识、发送给 Agent 的目标与分类；
- `samples`：同一问题重复执行次数，用于发现模型波动；
- `required`：默认为 `true`，任一必需样本失败都会阻断发布，即使总通过率达到阈值；
- `expect.status`：预期 Run 终态；
- `answer_contains` / `answer_not_contains`：稳定、短小的答案断言；
- `required_tool_names` / `forbidden_tool_names`：成功调用和绝对禁止观察到的工具；
- `min_sources`：API 返回的最少证据源数量；
- `max_total_tokens` / `max_model_calls` / `max_duration_ms`：成本与延迟上限。
- `expect.files`：最多 8 个实际交付文件，每项使用 `path` 指定完整相对路径；支持 `text_contains`、`text_not_contains`、`cells`（例如 `{"Data!B2": 12}`）、`min_pages`（PDF）、`min_slides`（PPTX）。表格断言比较存储值或公式文本，不计算公式；需要金额数值时明确要求 Agent 写入数值。
- 文件断言默认 `require_inspection=true`，要求当前执行镜像完成文件检查；旧镜像或旧文件缺少记录时不能算通过。`changed=true` 要求相对该用例前一版本的实际字节发生变化，并结合内容断言判断修改是否正确。
- `follow_ups`：最多 7 轮 `{goal, expect}`，与第一轮共用一个会话，每轮创建独立且幂等的 Run，样本总超时不重置。所有轮次参与门禁，结束后重新下载旧文件验证其不可变性。不同用例/样本使用新会话，避免相互污染。
- 数据集顶层 `gate.minimum_pass_rate`：总通过率阈值，默认 `1.0`（取值范围 `0 < x <= 1`）。

设置 `max_total_tokens` 时，只要任一模型调用没有报告 usage，该样本就以 `usage:unreported` 失败，门禁不会猜测 token。在线运行遇到人工审批或输入等待会立即结束采样，并以当前 Run 状态参与断言。文件交付 Agent 需要已授权的 bash、MCP 或 Skill 脚本能力，并使用隔离的评测会话及已批准的工具策略；外部副作用不属于这些样本。

文件身份来自成功工具事件，评测器通过当前用户授权下载，校验响应中的产物/Run 身份，再读取实际字节。文本提取限制为 200000 字符，文件为 5 MiB、Office 解压总量为 64 MiB；超限或不可解析以规则失败报告。PDF/Office 可解析不代表排版合格；排版敏感的任务仍需渲染后人工或专用视觉验收。

评估文件任务的调用效率时，固定模型请求参数、原始材料、工具目录和执行预算，分别重复首轮生成与后续修改。记录实际工具调用、bash 调用、模型调用、供应商上报用量、首次有效文件时间和总耗时；按调用身份去重，不能把同一调用的开始/结束事件算成两次执行。较少调用必须同时满足交付验收：使用所给模板、标签和相邻物理单元格对应正确、已知必填项完整、分节字数限制满足，并确认追问后的新旧文件各自可读、旧版本字节不变。Word 表单需读取实际 DOCX XML/物理单元格追加业务断言，当前 `expect.files.cells` 仅用于电子表格。检查不通过的样本应保留失败结论，不能凭 Run 成功或文件存在计为通过。报告和材料副本放在仓库之外；历史线上运行与新版本的比较应标明不是同期 A/B 实验。

## 使用结果

1. PR 必须先通过确定性 CI 门禁。
2. 在与生产相同的模型、知识版本、工具策略和环境变量下运行在线数据集。
3. 报告输出到指定的本地路径；失败时根据用例 ID 定位服务端 Run 和审计事件。报告属于运行产物，不是说明文档。
4. 模型凭据、请求参数或知识权限在 Run 创建后发生漂移时，运行会失败关闭，应重新创建评测 Run，而不是继续使用失真的旧上下文。
