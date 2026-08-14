# FrontendKnowledgeUpload 发现的 BUG

## low: 分段中（parse_queued/parsing）文档路由恢复后不轮询，界面停在无限 spinner

- 编号: BUG-frontend-002
- 严重度: low
- 模块: `frontend/components/knowledge/knowledge-upload-flow.tsx`
  （`step === "segment"` 路由恢复 effect + `UNPARSED_STATUS`/`PARSING_STATUSES`）
- 现象: 从 URL 恢复分段预览时，如果文档状态为 `parse_queued` 或 `parsing`
  （例如上次会话生成中途离开页面，服务端任务仍在跑），路由 effect 只对
  `status === "uploaded"` 的文档触发 `generatePreviewForDocuments`：
  ```
  if (nextDocuments.some((document) => document.status === UNPARSED_STATUS)) {
    await generatePreviewForDocuments(nextDocuments, routeState.parseSettings)
  }
  ```
  `PARSING_STATUSES = { parse_queued, parsing }` 的文档不会触发生成、也不会启动
  轮询，而 `hasPendingParsing` 使 `isPreviewRunning` 为 true，导致“生成分段预览”
  按钮被禁用。用户只能手动点“刷新”等任务结束后再“重新生成预览”，否则预览区
  一直显示 spinner。
- 预期: 恢复 `parse_queued`/`parsing` 文档时应像 `uploaded` 一样继续轮询任务
  状态并在完成后加载分段，或至少不阻塞“生成分段预览”按钮。
- 复现: 服务端返回文档状态 `parsing`（`frontend/tests/knowledge-upload.test.tsx`
  中 `skips generation when routed settings are invalid` 场景验证了
  非 `uploaded` 状态不触发生成的代码路径；`polls until a queued parse task
  succeeds` 验证了 `uploaded` 状态会轮询）。
- 来源: `frontend/tests/knowledge-upload.test.tsx`（知识库导入/分段预览覆盖套件）

## low: segment 恢复时上传 Promise 的 .catch 是不可达死代码

- 编号: BUG-frontend-003
- 严重度: low（test-infra）
- 模块: `frontend/components/knowledge/knowledge-upload-flow.tsx`
  （`step === "segment"` 空 documentIds 分支 `void upload.then(...).catch(...)`）
- 现象: `uploadPendingFiles` 内部对全部上传失败/建文档失败都做了兜底：
  `Promise.allSettled` + 内部 `reportError` 后 `return []`，从不 reject。
  因此路由 effect 里的 `.catch((error) => { reportError(error); onBackToFiles() })`
  永远不会执行（覆盖率报告显示 614-617 行无法覆盖），错误实际只通过
  `onBackToFiles` + `reportError`（在 uploadPendingFiles 内部）双路径上报，
  `.catch` 中的 `onBackToFiles` 是冗余逻辑。
- 预期: 要么让上传函数在失败时 reject 以便统一由 `.catch` 处理，要么删除死代码，
  避免错误上报路径分叉（当前“全部上传失败”时 notify 在 uploadPendingFiles 内
  触发，而 `.catch` 的路径永远不触发，行为不一致）。
- 复现: 让所有附件上传返回 500，观察 `onNotify` 仅由 `uploadPendingFiles`
  内部触发一次（`frontend/tests/knowledge-upload.test.tsx` 中
  `reports the failure when every upload fails`）。
- 来源: `frontend/tests/knowledge-upload.test.tsx`（知识库导入/分段预览覆盖套件）
