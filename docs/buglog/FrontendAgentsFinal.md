# FrontendAgentsFinal — BUG 记录

> 来源: `frontend/tests/agents-page.test.tsx`、`frontend/tests/agent-detail-workspace.test.tsx`、
> `frontend/tests/agent-config-fields.test.tsx`、`frontend/tests/agents-edge.test.tsx`
> （Agent 页域残余缺口补测，2026-08-15）

## 发现的 BUG 汇总

本轮未发现产品缺陷：新增 38 个用例（流合并纯函数、错误态、竞态、键盘路径、
graph.ts/workflows.ts 纯函数）全部按现状断言通过，未修改任何产品代码。

## 观察项（防御性死代码，非缺陷，不影响覆盖率目标）

### low: agents-page.tsx 的 handlePublishAgent 工作流分支不可达

- 位置: `frontend/components/agents/agents-page.tsx`
  - `handlePublishAgent` 守卫 `isDirty || isPublishing`（961-962）
  - `updateAgent` 成功后的工作流发布/取消发布 notify（982-983）
- 原因: `AgentsPage` 渲染 `WorkflowDetailWorkspace` 时未传 `onPublish`（工作流
  发布由画布内部自行处理），因此 Agent 分支的发布按钮在 `isDirty/isPublishing`
  时被禁用、非 admin 不渲染，工作流分支没有任何入口触发该函数——三个分支均为
  防御性死代码，UI 无法到达。

### low: loadRunToolCalls 入口守卫与 loadMoreAgents 无 token 守卫不可达

- 位置: `frontend/components/agents/agents-page.tsx`
  - `loadRunToolCalls` 的 `!token || !selectedWorkspaceId || 会话不匹配` 守卫
    （447-448）：所有调用点传入的 `conversationId` 均为调用时刻 `ref` 的即时值，
    且守卫之间无 await，不存在 ref 先变的时序。
  - `loadMoreAgents` 的 `!token || !selectedWorkspaceId` 守卫（561）：无工作空间时
    列表为空态，不渲染 infinite-scroll 哨兵，回调不会触发。
- 均为无 UI 入口的防御分支。

### low: management-panels 监控图表 Tooltip formatter 无法在 happy-dom 触发

- 位置: `frontend/components/agents/agent-management-panels.tsx`（1010-1012）
- recharts 在 happy-dom 0×0 容器下不渲染 `.recharts-wrapper`，Tooltip 的
  `formatter` 只在悬浮时调用，无法构造事件到达，保持未覆盖。

## 本轮测试环境发现（非产品缺陷）

- bun 的 lcov 在多文件 `--parallel` 合并下对 `agent-management-panels.tsx` 的
  登记行数（LF）不稳定：单独运行 `agent-detail-workspace.test.tsx` 时 LF=968
  （LH=966，99.8%）；四文件并行合并后 LF=1023（含 JSX 收尾行、类型注解、空行等
  无可执行语句的 0 命中记录，LH 仍为 966 → 94.4%）。与
  `docs/buglog/FrontendKbPageFinal.md` 记录的同一现象一致，组件覆盖率一律以
  "只运行自己的测试文件"为准（本域该口径 99.8%）。
- `navigator.clipboard` 需在用例内 try/finally 恢复；helpers 导出的 `screen`
  在本文件部分用例中绑定过时 document，改用 `view.container.querySelector`
  （`agent-detail-workspace.test.tsx` 复制用例）。
- 流式观察接口对 5xx 响应按指数退避无限重连（`lib/api/run-stream.ts`），测试
  观察失败分支需用 4xx 触发一次性抛出，避免超时。

## 剩余已知未覆盖分支（不可达/防御性，不影响 ≥95%）

- `agents-page.tsx`: `handlePublishAgent` 工作流 notify 与 `isDirty/isPublishing`
  守卫、`loadRunToolCalls` 会话竞态入口守卫、`loadMoreAgents` 无 token 守卫、
  工作流发布（无 onPublish 通道）。
- `agent-management-panels.tsx`: 监控图表 Tooltip formatter、window scroll 处理
  中 `previewScrollHost !== 容器` 分支（happy-dom 无 scrollingElement）、
  ResizeObserver 内容跟随回调；其余为 bun 并行合并口径下的 JSX 收尾/类型/空行
  伪行（单文件口径 99.8%）。
- `agent-detail-workspace.tsx`: `ReasoningContent` 布局副作用中的空行/收尾伪行
  （单文件口径 98.2%）。
