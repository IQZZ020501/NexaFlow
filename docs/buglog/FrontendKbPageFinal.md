# FrontendKbPageFinal — BUG 记录

> 来源: `frontend/tests/knowledge-page.test.tsx`、`frontend/tests/knowledge-page-dialogs.test.tsx`、
> `frontend/tests/knowledge-page-edge.test.tsx`（知识库页残余分支补测，2026-08-15）

## 发现的 BUG 汇总

### low: 文档分页页脚在页容量覆盖全部条目后消失，无法改回分页大小（与 BUG-kbp-001 相同，本轮以现状断言固化）

- 编号: BUG-kbp-001（已在 `docs/buglog/FrontendKnowledgePages.md` 记录）
- 模块: `frontend/components/knowledge/knowledge-base-page.tsx`
  （`filteredDocuments.length > documentPageSize` 条件渲染分页区）
- 现状断言: `knowledge-page.test.tsx > paginates documents and changes the page size`
  在 12 个文档切换"每页 20 条"后断言页脚（含"每页 20 条"触发器）消失——
  这是已知 bug 的现状固化，未修产品代码。

### low: 文档行"向量化中 {done}/{total}"进度文本依赖任务列表已加载（同 BUG-kbp-002）

- 编号: BUG-kbp-002（已在 `docs/buglog/FrontendKnowledgePages.md` 记录）
- 本轮补充: 新增 `polls for document status while documents are processing` 用例，
  验证 `hasProcessingDocuments` 时 3 秒轮询以 silent 模式刷新文档/任务列表，
  行为符合现状（轮询间隔内进度文本延迟属已知表现）。

## 本轮测试环境发现（非产品缺陷）

- bun 的 lcov 在全量/多文件并行下对组件行数（LF）统计不稳定：单独运行测试文件时
  只登记实际执行到的行（如 chunk-preview-list LF=198），多文件并行合并后登记全量
  行集（LF=231，含注释/类型注解/空行/JSX 收尾等不可执行行的 0 命中记录），导致
  同一组用例在两种口径下百分比不同。因此组件覆盖率一律以"只运行自己的测试文件"
  为准（chunk-preview-list 99.5% vs 合并口径 84.0%）。
- `createLeadingTextRange` 的 walker 穷尽分支（`setEnd(currentNode, currentNode.length)`）
  在多节点 markdown 输出（如 `**ab**cdefgh-xyz` 拆成 `<strong>ab</strong>cdefgh-xyz`
  两个文本节点）下可稳定命中；bun 单文件 lcov 可能把循环体内行归一到 `while` 行。
- 行内 checkbox 的"已选中再点"天然发 `checked=false`（删除分支），
  `checked=true` 且已包含的 no-op 分支只能通过直接派发 change 事件覆盖。
- `ModelIcon`（@lobehub/icons）会给 `DropdownMenuItem` 贡献额外 accessible name，
  用 `getByRole(..., { name })` 精确匹配会失败，需按文本 + `closest('[role="menuitem"]')`
  定位。

## 剩余已知未覆盖分支（不可达/防御性，不影响 ≥95%）

- `knowledge-base-page.tsx`：无工作空间守卫（`loadMoreKnowledgeBases`、
  `handleCreate/Update/ToggleStatus/Delete/TestModels/…` 的 `!selectedWorkspaceId` 分支）、
  `handleDelete` 删除当前打开知识库时的 `closeKnowledgeBase()`（当前 UI 无入口）、
  `handleGrantPermission` 空 userId 守卫（本轮已用表单直提覆盖）。
- `knowledge-base-dialogs.tsx`：各 `setForm/setEditForm/setPermissionForm` 回调中
  `current ? … : current` 的 falsy 分支（弹窗打开时表单必非空）。
- `chunk-preview-list.tsx`：`createLeadingTextRange` 的 `!firstNode` 空文本守卫
  （图片型分段已覆盖）、`while` 循环后不可达的 `return null`。
