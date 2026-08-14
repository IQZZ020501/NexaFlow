# FrontendKnowledgePages — BUG 记录

> 来源: `frontend/tests/knowledge-page.test.tsx` + `frontend/tests/knowledge-page-dialogs.test.tsx`
> （DOM 级知识库管理页测试，2026-08-15）

## 发现的 BUG 汇总

### low: 文档分页页脚在页容量覆盖全部条目后消失，无法改回分页大小

- 编号: BUG-kbp-001
- 严重度: low
- 模块: `frontend/components/knowledge/knowledge-base-page.tsx`
  （`filteredDocuments.length > documentPageSize` 条件渲染分页区）
- 现象: 当文档总数 ≤ 当前每页条数时，整个分页页脚（含"每页 N 条"下拉、
  "上一页/下一页"）都不渲染。例如 12 个文档时把每页改为 20，页脚立即消失，
  之后没有任何 UI 入口能把每页条数改回 10/20/50。
- 预期: 页脚或至少"每页 N 条"选择器应保留，允许用户随时调整分页大小。
- 复现: 进入知识库详情文档页（12 个文档），点"每页 10 条"→ 选"每页 20 条"，
  页脚整体消失。
- 来源: `knowledge-page.test.tsx > paginates documents and changes the page size`

### low: 文档行"向量化中 {done}/{total}"进度文本依赖任务列表已加载

- 编号: BUG-kbp-002
- 严重度: low
- 模块: `frontend/components/knowledge/knowledge-base-page.tsx`
  （`documentStatusText` + 任务加载时机）
- 现象: 文档状态为 `indexing` 时，首次进入"文档"页签显示的是普通"向量化中"
  状态标签；只有切到"任务"页签加载过任务列表、或 3 秒轮询触发后，才显示
  "向量化中 2/5"这类进度。轮询间隔使进度展示最多延迟 3 秒。
- 预期: 进入含处理中文档的页面时应尽快（例如随文档列表一起）加载相关任务，
  立即展示进度。
- 复现: 上传并索引一个文档后立即进入知识库"文档"页签，观察状态列文本。
- 来源: `knowledge-page.test.tsx > shows progress from tasks for indexing documents`

## 测试环境备注（非产品缺陷）

- Radix `DropdownMenuItem` 内容含嵌套 span 时 `getByText` 会命中多个节点；
  `DropdownMenuTrigger` 的 accessible name 会被 `FieldLabel htmlFor` 关联覆盖，
  查询需用标签名或 role。
- bun `expect(...).toBeNull()` 对 happy-dom DOM 元素断言失败时，diff 打印会
  无限递归导致进程 SIGTRAP 崩溃；应断言 `.disabled` 等属性而非元素本身。
- `withFetch` 的 `afterEach` 会还原 `globalThis.fetch`，单次安装只对第一个测试
  生效；需在每个测试后重新安装 stub。
