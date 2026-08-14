# WorkflowNodeCoverage 子任务发现

套件: `backend/tests/workflow_node_coverage.py`（运行命令
`uv run python -m tests.workflow_node_coverage`，exit 0）。

## 记录

### test-infra: coverage.py 7.15.4 + Python 3.11 对含未执行 raise 的协程丢失行级追踪

- 编号: BUG-testinfra-002
- 严重度: test-infra (medium)
- 模块: 覆盖率测量（`uv run coverage run --source=... -m tests.<suite>`）
- 现象: 协程函数体内只要存在一个**未执行**的 `raise` 语句，coverage 在协程首次
  `await` 之后便不再记录后续行。最小复现（`coverage run -m t5`）:
  ```python
  async def main():
      paused = await helper(1, 2)
      if paused:
          current = await helper()
          if current is None:
              raise RuntimeError("x")   # 未执行，但仅其存在即触发
          await asyncio.sleep(0)
      await asyncio.sleep(0)
  ```
  报告缺失 `if paused:` 块及之后的所有行；去掉该 `raise` 后 100% 覆盖。
  同样地，`except` 块内单语句 for 循环体等行也会漏记。
- 预期: 执行过的行应被记录。
- 复现: 本套件对 `app/application/workflow_executor.py` 的 17 行、`workflow_uploads.py`
  的 3 行做了 spy 验证（`claim_agent_run`/`pause_agent_run_for_input`/
  `finalize_agent_run`/`set_first_run_deadline` 全部返回 True 且事件已落库、
  断言成立），代码确实执行，但 coverage 仍报缺失：
  - workflow_executor.py: 471-476, 485, 561, 572-576, 582, 599, 619, 625
  - workflow_uploads.py: 269, 277, 507
  这些行同时出现在任务给定的"基线缺失行"列表中，说明基线测量受同一缺陷影响；
  无法通过测试手段修正（不改产品代码），建议合并时按已执行处理或改用
  `--branch`/C 扩展追踪器复核。
- 来源: WorkflowNodeCoverage 套件

### test-infra: 文档抽取（MarkItDown）在 coverage 下偶发失败

- 编号: BUG-testinfra-003
- 严重度: test-infra (low)
- 模块: `app/capabilities/embedding/pipeline.py::extract_document`（.txt 走
  MARKITDOWN.convert_local）
- 现象: 全套件在 coverage 下首次运行，公开运行携带 `file_ids` 的
  document-extract 图时返回 422 "Workflow document content could not be
  extracted."；单独复现脚本与重跑全套件均成功（同环境下直接调用
  `extract_document("notes.txt", "text/plain", path)` 返回正常文本）。
- 预期: 稳定成功。
- 复现: `uv run coverage run --source=<目标模块> -m tests.workflow_node_coverage`
  偶发（覆盖率运行 2 次中 1 次）。
- 来源: WorkflowNodeCoverage 套件
