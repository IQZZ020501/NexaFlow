# FrontendUploadChatFinal — BUG/发现记录（第二轮）

## 已修复：BUG-frontend-002（parsing 文档路由恢复继续轮询）

- 状态: **已修复（2026-08-15）**
- 回归用例 `resumes polling for parsing documents restored from the route` 验证恢复中的
  文档继续查询原任务，任务成功后加载分段，且不会重复提交 parse。

## low: 若干防御性分支在 UI 上不可达（覆盖率死代码）

- 模块: `frontend/components/knowledge/knowledge-upload-flow.tsx`
- 这些分支在“只跑本组件测试文件”口径下依然无法覆盖，原因均为
  happy-dom 中 `disabled` 按钮不派发 click（已用最小用例验证），
  且守卫条件与按钮 `disabled` 条件/渲染条件严格一致：

| 行号 | 守卫 | 不可达原因 |
|---|---|---|
| 722-723 | `handleRemoveDocument`：`isNavigationLocked \|\| staged!==true \|\| status∉UNINDEXED` | staged 非 true 或 status 不在 UNINDEXED 时不渲染移除按钮；`isNavigationLocked` 时按钮 `disabled` |
| 770 | `handleNext`：`!files.length` | 无文件时“下一步”按钮 `disabled` |
| 782 | `uploadPendingFiles`：`!files.length` | 队列非空时才调用 `prepareUpload`，闭包捕获的 files 恒非空 |
| 858 | `handleGeneratePreview`：`!uploadedDocuments.length \|\| isSegmentInvalid` | 与按钮 `disabled` 条件（超集）一致 |
| 871 | `handleStartImport`：`!canStartIndex` | 与按钮 `disabled` 条件一致 |
| 614-617 | upload `.catch`（与 BUG-frontend-003 相同） | `uploadPendingFiles` 从不 reject（全 allSettled + 内部兜底） |
| 460 | 轮询循环 `documentIndex < 0` | `pendingDocumentIds` 恒来自 `documents`，`findIndex` 必命中 |

- 预期: 如追求 100% 可删除这些纯防御分支（`handleNext` 空文件守卫、三个 handler
  守卫）或改为可触发形式；当前视为有意保留的防御代码。

## low: generatePreviewForDocuments 外层 catch 只能靠回调抛错触发

- 模块: `frontend/components/knowledge/knowledge-upload-flow.tsx`（557-558 行）
- API 层所有错误都被 `Promise.allSettled`/内层 try-catch 消化，外层
  `catch (error) { reportError(error) }` 实际只捕获 `onNotify` 等回调抛出的异常。
- 本轮用“success 通知抛错”用例覆盖该分支（`surfaces unexpected errors during
  preview generation`），验证外层 catch 会把错误转报为 error 通知。

## 其他

- `lib/api/run-stream.ts` 147 行为 while 循环闭合大括号，bun lcov 归因到
  “循环条件退出”路径，该路径实际不存在（循环恒通过 return/throw 退出），
  为覆盖率归因假象，非可执行缺陷。
- 上述历史 WIP 失败已过期；2026-08-15 本轮四个相关测试文件共 202 项通过。
