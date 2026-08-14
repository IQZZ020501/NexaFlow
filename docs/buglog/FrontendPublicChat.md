# FrontendPublicChat — BUG 记录

## medium: 选择当前已激活对话后加载指示器卡死

- 编号: BUG-frontend-001
- 严重度: medium
- 模块: `frontend/components/agents/public-agent-chat.tsx`（`selectConversation` 与 runs 加载 effect）
- 现象: 在侧栏或移动端历史对话框里点击"当前已激活"的会话时，`setIsRunsLoading(true)`
  后 `setActiveConversationId(conversationId)` 传入相同值，React 状态不变、依赖数组
  `[activeConversationId, ...]` 未变化，runs 加载 effect 不会重新执行，`isRunsLoading`
  永远不会被置回 `false`，消息区永久停留在"正在加载"旋转指示器。
- 预期: 点击当前会话不应进入加载态；即使进入也应在一次加载后恢复内容（可跳过
  `setIsRunsLoading(true)` 当 `conversationId === activeConversationId`，或让 effect
  在主动刷新时兜底复位）。
- 复现: 渲染 `PublicAgentChat`（含历史会话 conv-1），点击侧栏中带 `aria-current="page"`
  的同一会话按钮；消息区从内容变为永久旋转指示器。测试证据：
  `frontend/tests/public-agent-chat.test.tsx` 中若在移动端对话框点击当前会话
  （conv-1），"来自对话的记录"随即消失且不再出现（为通过测试只能改为点击另一会话）。
- 来源: 测试套件 `frontend/tests/public-agent-chat.test.tsx`（2026-08-15）
