# AgentRuntimeCoverage — BUG 记录

> 由 `tests/agent_runtime_coverage.py`（Agent 执行内核覆盖率套件：
> agent_executor / agent_runs / agent_memory / agent_tools / runtime 图 /
> live stream）产生。只记录、不修改产品代码。格式见 docs/BUG_LOG.md 顶部。

## 发现的 BUG 汇总

### test-infra: coverage.py 的 --source 列表超过 4 个模块时 numpy 导入崩溃

- 编号: BUG-testinfra-002
- 严重度: test-infra (low)
- 模块: `coverage 7.15.4` + `numpy`（经 `qdrant_client` 在 `app.main` 导入链中引入）
- 现象: 按任务给定方式运行
  `uv run coverage run --source=<5 个及以上模块> --data-file=.coverage.AgentRuntimeCoverage -m tests.agent_runtime_coverage`
  时，进程在导入阶段崩溃：
  `ImportError: cannot load module more than once per process`
  （`numpy._core._multiarray_umath`，触发链 `app.api.deps -> workspace ->
  knowledge -> vector_store -> qdrant_client -> numpy`）。`--source` 为
  1–4 个模块时稳定通过（5 个模块两个变体各复测 5 次均失败，非偶发）。
  `--timid` 无法规避。
- 预期: `--source` 模块数量不应影响被测程序能否导入。
- 复现:
  ```
  cd backend
  uv run coverage run --source=app.application.agent_executor,app.application.agent_runs,app.application.agent_memory,app.application.agent_tools,app.shareddomain.agents.runtime.graph --data-file=.coverage.AgentRuntimeCoverage -m tests.agent_runtime_coverage
  ```
- 规避（已用于本套件验证）: 不带 `--source` 运行 coverage（默认测量全部已导入
  模块），再用 `coverage report --include="<模块列表>"` 过滤报表。测量范围等价，
  数据文件独立（.coverage.AgentRuntimeCoverage），不运行 coverage combine。
- 来源: tests.agent_runtime_coverage

### low: agent_memory 压缩源选择存在不可达分支

- 编号: BUG-runtime-001
- 严重度: low
- 模块: `backend/app/application/agent_memory.py:266`
- 现象: `prepare_conversation_memory` 的源运行选择循环中，
  `if not source_runs: source_runs = old_runs[:1]` 永不可达：循环体的首个
  候选运行必然被选中（`if source_runs and _approx_tokens(...) > source_budget`
  在 `source_runs` 为空时短路为 False），因此只要 `old_runs` 非空，
  `source_runs` 就不会为空；而 `old_runs` 为空的情况已在更早的
  `if not old_runs:` 分支返回。
- 预期: 删除该防御分支，或修正选择逻辑（例如跳过空消息对时保证至少选中一个
  有内容的运行）。
- 复现: 单元构造任意 `old_runs` 非空场景，`source_runs` 恒非空。
- 来源: tests.agent_runtime_coverage（assert_memory_db_paths）

### low: agent_executor record_event 存在不可达分支

- 编号: BUG-runtime-002
- 严重度: low
- 模块: `backend/app/application/agent_executor.py:743-744`
- 现象: `_execute_claimed_agent_run` 内 `record_event` 的
  `if event_type != "process": return` 分支不可达：`run_agent` 回调只会发布
  `{"type": "process", ...}`、`answer_delta`、`reasoning_delta` 三类事件，
  前两个分支已全部处理，不存在其他事件类型到达该语句。
- 预期: 删除该防御分支，或在回调层面对事件类型做白名单校验并记录未知类型。
- 复现: 任何一次完整 run_agent 执行。
- 来源: tests.agent_runtime_coverage（assert_durable_execution_paths）

### low: usage 归一化丢弃非整数 token 计数

- 编号: BUG-runtime-003
- 严重度: low
- 模块: `backend/app/shareddomain/agents/runtime/usage.py:27-36`（`_number`）
- 现象: `_number` 对非整数 float（如 `3.5`）返回 `None`，`usage_from_message`
  与 `merge_usage` 会静默把这类值当作 0 / 直接丢弃。若某供应商上报小数 token
  计数（如推理模型按分数计费），账本会少记。
- 预期: 对非整数数值四舍五入或向上取整后计入，而不是丢弃。
- 复现: `usage_from_message(SimpleNamespace(usage_metadata={"total_tokens": 3.5}, response_metadata={}))`
  -> `total_tokens == 0`（应为 4 或 3.5 取整）。
- 来源: tests.agent_runtime_coverage（assert_usage_normalization）

### low: resolve_agent_run_tool_approval 对已终态 run 的重复批准静默返回

- 编号: BUG-runtime-004
- 严重度: low
- 模块: `backend/app/application/agent_runs.py:286-291`
- 现象: 当调用已 `approved` 且 `approved_by_user_id == actor.id` 时，重复
  approve 直接 `refresh_agent_run` 返回，即使该 run 已处于 `succeeded`/
  `failed` 终态（工具调用完成/失败后，同一用户在终态 run 上重复批准不会得到
  409，而是静默返回当前 run）。同类调用在终态 call 上会被拒绝（292-296），
  行为不一致。
- 预期: 终态 run 上的重复批准应同样返回 409，或至少在响应中体现幂等语义差异。
- 复现: 先 approve 使 run 重新排队并执行完成（succeeded），再以同一用户再次
  approve 同一 call —— 返回 200 与 run 实体而非 409。
- 来源: tests.agent_runtime_coverage（assert_approval_paths）
