# FRONTEND 模块（frontend/）

## 架构

Next.js 16 App Router 客户端渲染 SPA（多数页面 `'use client'`）：`src/app/` 路由薄壳委托给 `src/components/` 巨型页面组件；`src/contexts/` 提供语言/主题/会话/消息中心全局状态；`src/lib/api/` 按域划分的 API 客户端统一走 `src/lib/api-client.ts` 的 fetch 封装（dev 下 `/api` 由 Next rewrite 代理到 FastAPI）；`src/i18n/` 以中文文案为键的三语词典；系统管理（dashboard 路由组）与平台工作区（platform 路由组）共享 SessionGate/TopBar，Workflow 画布路由组（`(platform)/workflow`）只用 SessionGate 并全屏渲染。技术栈：React 19 + Tailwind v4 + shadcn/ui（radix-nova）、`@xyflow/react`（Workflow 画布）、`recharts`（数据大屏）、`shiki`/`beautiful-mermaid`（Markdown/Mermaid 渲染）、Bun 脚本。

## 文件清单

### 根目录配置

- `frontend/package.json` — 项目清单与 bun 脚本（dev/build/start/lint/test/format/typecheck）；覆盖率由 `frontend/scripts/coverage.sh` 单独驱动（`bun test --isolate --coverage`）
- `frontend/tsconfig.json` — 严格模式 TS 配置，`@/*` 路径别名
- `frontend/next.config.ts` — Next.js 配置：`/api`、完整 Swagger `/docs`/`/openapi.json` 与 `/health` 代理到 FastAPI（`NEXAFLOW_API_PROXY`），standalone 输出
- `frontend/postcss.config.mjs` — Tailwind v4 PostCSS 插件配置
- `frontend/eslint.config.js` — ESLint flat config（TS + React Hooks + `@next/next` recommended/core-web-vitals）
- `frontend/components.json` — shadcn 注册表配置
- `frontend/bunfig.toml` — bun 测试 preload（`tests/setup.ts`）
- `frontend/scripts/coverage.sh` — 串行 `--isolate` 覆盖运行器（99% 总行覆盖率门槛，`--detail` 逐文件模式）
- `frontend/.prettierrc`、`frontend/.prettierignore` — Prettier 配置
- `frontend/public/` — 静态资源（`NexaFlow-logo.png`、`feishu.svg`、`skill-icons/`、`model-providers/`）
- `frontend/next-env.d.ts` — Next.js 自动生成的类型引用（勿手改）
- `frontend/src/app/globals.css` — 全局 Tailwind v4 主题 CSS 变量、暗色模式与各外观轴令牌块（`[data-palette]`、`[data-font]`、`[data-radius]`、`[data-density]`、`[data-layout]`、`[data-content-width]`、`[data-sidebar]`）与 `pb-safe`/`pt-safe`/`h-safe-bottom` 安全区工具类
- `frontend/src/types/css.d.ts` — CSS 模块类型声明

### 主题与外观

八条互相独立、各自持久化的外观轴（localStorage 键即 `theme`/`palette`/`font`/`radius`/`density`/`sidebar`/`layout`/`content-width`）：明暗模式 `system|light|dark`、配色方案（10 个调色板）、字体、圆角、密度、侧边栏、布局与内容宽度。由 `src/app/layout.tsx` 的内联 `themeScript` 在首次绘制前写入 `<html>` 的 class 与 `data-*` 属性，配合同文件 `criticalThemeStyles` 在样式表加载前先铺底色；UI 入口在 `src/components/app/theme-settings-dialog.tsx`，状态与同步逻辑在 `src/contexts/theme-provider.tsx`，轴定义与校验在 `src/lib/theme-options.ts`。

浏览器 chrome 颜色有个明确约束：**不要在 `viewport` 元数据上声明 `themeColor`** —— 元数据看不到当前调色板，且 React 会在 hydration 后重新应用而覆盖调色板感知值；浏览器地址栏颜色改由 `themeScript` 注入 `<meta name="theme-color">`，并由 `ThemeProvider` 的 `syncThemeColorMeta()` 在每次外观变更后保持同步。`viewportFit: "cover"` 是 `pb-safe` 等安全区工具类生效的前提。调色板色板展示通过在被展示元素上嵌套 `data-palette` 属性读取该调色板自身令牌，因此新增调色板无需额外色板样式。

### app/ 路由组

- `frontend/src/app/layout.tsx` — 根布局：元信息 + AppProviders 包裹
- `frontend/src/app/page.tsx` — 首页重定向到 `/app/apps`
- `frontend/src/app/not-found.tsx` — 站点级三语 404 页面，不回显后端资源细节
- `frontend/src/app/(platform)/app/layout.tsx` — 平台区布局：SessionGate + TopBar
- `frontend/src/app/(platform)/app/page.tsx` — 重定向到 `/app/apps`
- `frontend/src/app/(platform)/app/messages/page.tsx` — 消息中心收件箱
- `frontend/src/app/(platform)/app/knowledge/page.tsx` — 知识库列表页
- `frontend/src/app/(platform)/app/knowledge/[id]/page.tsx` — 知识库详情页
- `frontend/src/app/(platform)/app/knowledge/[id]/[tab]/page.tsx` — 知识库详情 Tab 规范路由（非法值/documents 重定向回文档路由）
- `frontend/src/app/(platform)/app/knowledge/[id]/upload/page.tsx` — 上传向导「选择文件」步骤
- `frontend/src/app/(platform)/app/knowledge/[id]/upload/layout.tsx` — 上传向导共享状态 Provider
- `frontend/src/app/(platform)/app/knowledge/[id]/upload/segment/page.tsx` — 上传向导「分段预览」步骤（server 解析路由状态）
- `frontend/src/app/(platform)/app/knowledge/[id]/documents/[docId]/page.tsx` — 文档详情页
- `frontend/src/app/(platform)/app/tools/page.tsx` — 统一工具中心：builtin/Python/MCP 目录、来源与授权管理
- `frontend/src/app/(platform)/app/apps/page.tsx` — Agent 应用列表页
- `frontend/src/app/(platform)/app/apps/[id]/page.tsx` — Agent 详情页（兼容旧 `?view=` 查询参数）
- `frontend/src/app/(platform)/app/apps/[id]/[view]/page.tsx` — Agent/Workflow 详情规范路由（`overview` 重定向到规范路径）
- `frontend/src/app/(platform)/workflow/[id]/page.tsx` — Workflow 画布（页面本身忽略路由参数，交由 `AgentsPage` 以 settings 视图渲染）；查看授权用户进入只读模式
- `frontend/src/app/(platform)/workflow/layout.tsx` — 全屏工作区壳：仅 SessionGate，无 TopBar
- `frontend/src/app/(public)/chat/[id]/page.tsx` — 已发布 Agent/Workflow 的公开对话入口（由 `components/apps/public-application-chat.tsx` 分派）
- `frontend/src/app/(public)/agent-api/[id]/docs/page.tsx` — API Key 解锁的单 Agent API 文档页
- `frontend/src/app/(public)/workflow-api/[id]/docs/page.tsx` — API Key 解锁的单 Workflow API 文档页
- `frontend/src/app/(platform)/app/models/page.tsx` — 模型管理页
- `frontend/src/app/(auth)/login/page.tsx` — 登录页（登录回调与已登录跳转）
- `frontend/src/app/(auth)/auth/complete/page.tsx` — 企业扫码登录回调
- `frontend/src/app/(auth)/forgot-password/page.tsx` — 忘记密码申请页
- `frontend/src/app/(auth)/reset-password/[token]/page.tsx` — 重置密码确认页
- `frontend/src/app/(dashboard)/system/layout.tsx` — 系统管理布局
- `frontend/src/app/(dashboard)/system/page.tsx` — 重定向到 `/system/workspaces`
- `frontend/src/app/(dashboard)/system/[tab]/page.tsx` — 系统管理基础 Tab 页（workspaces/teams/users/audit/permissions；非法值重定向到 workspaces）
- `frontend/src/app/(dashboard)/system/announcements/page.tsx` — 公告管理
- `frontend/src/app/(dashboard)/system/analytics/page.tsx` — 工作区数据大屏
- `frontend/src/app/(dashboard)/system/email/page.tsx` — 全局 SMTP 邮件设置
- `frontend/src/app/(dashboard)/system/identity/page.tsx` — 企业登录（SSO）配置
- `frontend/src/app/(dashboard)/system/operations/page.tsx` — 系统运行、健康状态和脱敏运行日志
- `frontend/src/app/(dashboard)/system/governance/page.tsx` — 工作空间资源盘点、配额策略和成员邀请
- `frontend/src/app/(dashboard)/system/security/page.tsx` — 当前用户/系统管理员的会话设备撤销
- `frontend/src/app/(public)/invite/[token]/page.tsx` — 工作空间邀请接受页：指定成员链接一次性领取，通用链接 7 天内可重复注册

### components/（按功能分组）

**knowledge/**（知识库功能）
- `frontend/src/components/knowledge/knowledge-base-page.tsx` — 知识库列表/详情/上传向导主组件（CRUD/权限/任务）
- `frontend/src/components/knowledge/knowledge-upload-flow.tsx` — 上传流程（选文件→上传→分段预览）
- `frontend/src/components/knowledge/knowledge-upload-files.ts`、`knowledge-upload-state.tsx` — 上传文件处理与向导共享状态
- `frontend/src/components/knowledge/knowledge-base-dialogs.tsx` — 新建/编辑/权限分配对话框
- `frontend/src/components/knowledge/document-detail-page.tsx` — 文档详情：分段、任务、重新解析/向量化
- `frontend/src/components/knowledge/chunk-preview-list.tsx` — 分段预览列表（智能模式按 Parent 分组，高级模式平铺，高亮同 Parent 相邻重叠文本）
- `frontend/src/components/knowledge/knowledge-hit-test.tsx` — 命中测试与评测用例入口
- `frontend/src/components/knowledge/knowledge-evaluation.tsx` — 检索评测用例/运行/指标
- `frontend/src/components/knowledge/knowledge-graph.tsx`、`knowledge-graph-canvas.tsx` — 证据图谱视图与画布
- `frontend/src/components/knowledge/markdown-content.tsx` — react-markdown + GFM 渲染；`markdown-code-block.tsx` 代码高亮
- `frontend/src/components/knowledge/document-file-icon.tsx` — 文档类型图标
- `frontend/src/components/knowledge/status-badges.tsx` — 状态/权限徽章
- `frontend/src/components/knowledge/status-labels.ts` — 状态中文标签与状态点样式映射

**agents/**（Agent 功能）
- `frontend/src/components/agents/agents-page.tsx` — Agent CRUD、持久 Run 提交、PostgreSQL/Redis 双游标重连、实时答案与审批状态合并
- `frontend/src/components/agents/agent-detail-workspace.tsx` — 运行工作台：过程事件、待审批/不确定工具调用处理
- `frontend/src/components/agents/agent-config-fields.tsx` — 配置表单字段（模型、知识库与统一 Tool picker）；`interaction-config-fields.tsx` 交互配置
- `frontend/src/components/agents/agent-management-panels.tsx` — Agent 概览、API 凭据、对话日志、监控统计与对话用户面板
- `frontend/src/components/agents/agent-permissions-dialog.tsx` — Agent `view/edit` 授权管理
- `frontend/src/components/agents/agent-approval-mode-menu.tsx` — 运行级审批模式（always_ask/ask_risky/full_access）
- `frontend/src/components/agents/agent-attachment-list.tsx`、`tool-input-preview.tsx`、`message-timestamp.tsx` — 附件、工具入参与时间戳展示
- `frontend/src/components/agents/agent-source-references.tsx` — 知识来源引用卡片
- `frontend/src/components/agents/public-agent-chat.tsx` — 公开对话历史、提问、脱敏执行摘要与答案流；最终回答沿用调试页的 Markdown 展示，执行链展示模型思考过程但不暴露工具名称/参数或检索原文
- `frontend/src/components/agents/agent-api-documentation.tsx`、`agent-api-reference.tsx` — 校验 Agent API Key 后仅展示当前 Agent 的 API 调用文档（正文渲染在 reference 组件）

**llm/**（模型功能）
- `frontend/src/components/llm/llm-page.tsx` — 模型管理页：注册模型 CRUD、凭据、目录浏览

**tools/**（工具功能）
- `frontend/src/components/tools/tools-page.tsx` — 生产工具中心：Skills/MCP/Python 目录页签（内置工具、内置 Skills、工作区 Skills、MCP Server 分组）、跨页加载、详情、来源状态、策略与授权入口
- `frontend/src/components/tools/python-tool-dialog.tsx` — Python Tool 草稿、schema、沙箱测试、发布与版本状态
- `frontend/src/components/tools/mcp-source-dialog.tsx`、`mcp-form.ts` — MCP Source 创建：普通成员公网 HTTP/SSE，管理员额外支持 stdio/私网
- `frontend/src/components/tools/skill-dialog.tsx` — Agent Skill 导入检查、版本与发布
- `frontend/src/components/tools/builtin-tool-icon.tsx` — 内置工具/Skill 图标映射
- `frontend/src/components/tools/tool-permissions-dialog.tsx` — 同工作空间成员搜索及 `view/use/none` 授权管理
- `frontend/src/components/tools/tool-picker.tsx` — Agent 共用 Tool picker：搜索、键盘选择、固定 Tool/Version 引用与失效状态
- `frontend/src/components/tools/mcp-tools-page.tsx` — 旧 MCP 专页兼容组件；生产 `/app/tools` 不再使用，仅保留既有回归覆盖

**workflows/**（Workflow 画布与公开对话）
- `frontend/src/components/workflows/workflow-canvas.tsx`、`workflow-node.tsx`、`workflow-edge.tsx`、`workflow-node-palette.tsx` — React Flow 画布、节点/连线与节点面板
- `frontend/src/components/workflows/workflow-detail-workspace.tsx` — Workflow 编辑工作台；`workflow-runtime-form.tsx` 运行表单
- `frontend/src/components/workflows/workflow-api-documentation.tsx` — API Key 解锁的单 Workflow API 文档
- `frontend/src/components/workflows/public-workflow-chat.tsx` — 已发布 Workflow 的公开对话

**messages/**（消息与公告）
- `frontend/src/components/messages/message-center.tsx` — 消息中心收件箱与实时流订阅
- `frontend/src/components/messages/announcement-admin-page.tsx` — 公告管理页；`announcement-expiration-field.tsx` 过期时间字段

**resource-folders/**（跨资源文件夹）
- `frontend/src/components/resource-folders/resource-folder-tree.tsx`、`resource-folder-layout.tsx`、`resource-folder-panel.tsx` — 文件夹树与面板
- `frontend/src/components/resource-folders/resource-folder-picker-dialog.tsx`、`resource-bulk-move-bar.tsx` — 归入文件夹与批量移动
- `frontend/src/components/resource-folders/use-resource-folders.ts` — 知识库/应用/模型/工具共用的文件夹状态 hook

**apps/**（公开应用对话分派）
- `frontend/src/components/apps/public-application-chat.tsx` — `/chat/[id]` 的分派器：按应用类型渲染公开 Agent 或 Workflow 对话

**system/**（系统管理功能）
- `frontend/src/components/system/system-shell.tsx` — 系统管理壳：数据加载、CRUD 编排、Tab 切换
- `frontend/src/components/system/system-page-view.tsx` — 五 Tab 面板（workspaces/teams/users/audit/permissions）+ 对话框装配
- `frontend/src/components/system/system-utils.ts` — 格式化工具（角色/审计详情）
- `frontend/src/components/system/panels/global-users-panel.tsx` — 全局用户列表面板
- `frontend/src/components/system/panels/workspace-users-panel.tsx` — 工作空间成员面板
- `frontend/src/components/system/panels/workspaces-panel.tsx` — 工作空间列表面板
- `frontend/src/components/system/panels/teams-panel.tsx` — 团队列表面板
- `frontend/src/components/system/panels/audit-panel.tsx` — 审计日志面板
- `frontend/src/components/system/resource-permissions-page.tsx` — 资源权限总览（permissions Tab）
- `frontend/src/components/system/workspace-analytics-page.tsx`（+ `-overview/-inventory/-insights/-metrics/-date-range-picker`）— 工作区数据大屏
- `frontend/src/components/system/enterprise-identity-page.tsx`、`smtp-settings-page.tsx` — 企业登录与 SMTP 设置页
- `frontend/src/components/system/system-governance-page.tsx` — 系统运行、工作空间治理和会话安全面板（按 `section` 复用 email/identity 页）
- `frontend/src/components/system/dialogs/scope-dialogs.tsx` — 工作空间/团队对话框
- `frontend/src/components/system/dialogs/user-dialogs.tsx` — 用户对话框
- `frontend/src/components/system/dialogs/team-members-dialog.tsx`、`workspace-members-dialog.tsx` — 成员管理对话框
- `frontend/src/components/system/pagination-footer.tsx` — 列表分页页脚

**auth/**（认证功能）
- `frontend/src/components/auth/login-page-content.tsx` — 登录页内容装配（`(auth)/login/page.tsx` 实际渲染入口）
- `frontend/src/components/auth/login-screen.tsx` — 登录表单（含初始密码强制修改）
- `frontend/src/components/auth/enterprise-login-complete.tsx` — 企业扫码登录回调处理
- `frontend/src/components/auth/forgot-password-page.tsx`、`reset-password-page.tsx`、`invitation-page.tsx` — 找回/重置密码与邀请接受页
- `frontend/src/components/auth/change-password-dialog.tsx` — 修改密码对话框

**app/**（平台壳）
- `frontend/src/components/app/top-bar.tsx` — 顶栏：桌面导航、工作空间/语言/主题切换、用户菜单；`sm` 以下只保留标识、工作空间、消息与用户菜单
- `frontend/src/components/app/mobile-tab-bar.tsx` — 手机底部标签栏（`sm` 以下由 `useMediaQuery(PHONE_NAV_QUERY)` 挂载）：应用/知识库/模型/工具/数据大屏
- `frontend/src/components/app/session-gate.tsx` — 会话门禁：未登录跳转、强制改密
- `frontend/src/components/app/top-progress.tsx` — 路由切换进度条
- `frontend/src/components/app/operation-notification.tsx` — 成功/错误通知条
- `frontend/src/components/app/filter-dropdown.tsx` — 通用下拉筛选
- `frontend/src/components/app/theme-settings-dialog.tsx` — 主题与八条外观轴的设置界面
- `frontend/src/components/app/run-action-bar.tsx`、`confirm-dialog.tsx` — Run 操作条与通用确认对话框

**ui/**（shadcn 基础组件）
- `frontend/src/components/ui/button.tsx`、`input.tsx`、`label.tsx`、`card.tsx`、`card-more-menu.tsx`、`dialog.tsx`、`dropdown-menu.tsx`、`field.tsx`、`icon-button.tsx`、`avatar.tsx`、`badge.tsx`、`tooltip.tsx`、`resource-card.tsx`、`spec.tsx`（键值展示小部件）

**pages/**
- `frontend/src/components/pages/placeholder-page.tsx` — 功能占位页（当前无调用方，仅保留导出）

### contexts/（全局状态）

- `frontend/src/contexts/app-providers.tsx` — 组合 Language/Theme/Session/MessageCenter Provider
- `frontend/src/contexts/session-context.tsx` — 全局会话：token/me/工作空间/通知/强制改密/刷新
- `frontend/src/contexts/language-provider.tsx` — 三语切换与 `t()` 翻译
- `frontend/src/contexts/theme-provider.tsx` — 八条外观轴（明暗/调色板/字体/圆角/密度/侧边栏/布局/内容宽度）偏好，各自持久化于 localStorage、作用于 `<html>` 并同步浏览器 chrome 颜色
- `frontend/src/contexts/message-center-context.tsx` — 消息中心：未读计数、SSE 订阅与已读状态

### i18n/（三语词典，键即中文文案）

- `frontend/src/i18n/index.ts` — 词典注册表、`translate()` 插值、语言选项与存储键
- `frontend/src/i18n/zh-hans.ts` — 简体中文词典
- `frontend/src/i18n/zh-hant.ts` — 繁体中文词典
- `frontend/src/i18n/en.ts` — 英文词典

### lib/

- `frontend/src/lib/api-client.ts` — fetch 封装：`apiUrl`/`listQuery`、`request`/`requestPage`（`X-Total-Count` 分页信封）/`requestBlob`、JSON/FormData、Bearer token、`ApiError` 归一化与 `NEXT_PUBLIC_API_BASE_URL` 基址覆盖
- `frontend/src/lib/agent-views.ts`、`knowledge-views.ts` — 详情深路由契约（`AGENT_DETAIL_VIEWS`、`appViewPath`、`parseAgentDetailView` 等）
- `frontend/src/lib/knowledge-upload-route.ts` — 上传路由状态 URL 序列化/校验
- `frontend/src/lib/pages.ts` — 四大功能页布局元数据目录
- `frontend/src/lib/storage.ts` — localStorage 键常量
- `frontend/src/lib/utils.ts` — `cn()` class 合并
- `frontend/src/lib/dom.ts` — dropdown 事件来源判定
- `frontend/src/lib/errors.ts` — 统一错误文案
- `frontend/src/lib/notifications.ts` — AppNotification 类型
- `frontend/src/lib/password.ts` — 新密码校验
- `frontend/src/lib/chunk-overlap.ts` — 分段重叠文本检测
- `frontend/src/lib/constants.ts` — 默认密码、状态/审计标签键映射
- `frontend/src/lib/display.ts` — 展示格式化工具
- `frontend/src/lib/theme-options.ts` — 外观轴选项与判别函数：调色板（10 个）、字体、圆角、密度、侧边栏、布局、内容宽度 + `isTheme*` 校验
- `frontend/src/lib/tool-display.ts`、`tool-visibility.ts`、`builtin-skill-docs.ts` — 工具展示名/可见性与内置 Skill 文档
- `frontend/src/lib/interaction-config.ts`、`agent-session-handoff.ts`、`conversation-export.ts`、`run-versions.ts` — 交互配置、会话交接、对话导出与运行版本
- `frontend/src/lib/visual-viewport.ts`、`auth-path.ts`、`browser-tts.ts`、`clipboard.ts`、`use-infinite-scroll.ts` — 视口、认证跳转、语音、剪贴板与无限滚动工具
- `frontend/src/lib/use-media-query.ts` — `useMediaQuery()` 与 `PHONE_LIST_QUERY`（`< md`）/`PHONE_NAV_QUERY`（`< sm`）：按断点选择手机或桌面版式
- `frontend/src/lib/workflows/` — `graph.ts`（Workflow 图模型）、`canvas.ts`（画布几何）

**lib/api/**（按域划分的 API 客户端）
- `frontend/src/lib/api/auth.ts` — 认证 API：登录/登出/me/刷新/改密/找回密码/会话
- `frontend/src/lib/api/knowledge.ts` — 知识库 API：知识库/文档/任务/chunk/检索/图谱/评测
- `frontend/src/lib/api/agents.ts` — Agent API：CRUD、发布、API 凭据、日志/统计/用户、Run 提交/游标订阅/自动重连、工具审批
- `frontend/src/lib/api/public-agents.ts` — 公开 Agent 资料、公开会话、历史和脱敏 Run 流
- `frontend/src/lib/api/run-stream.ts` — 登录态与公开 Run 共用的 NDJSON 双游标重连器
- `frontend/src/lib/api/llm.ts` — 模型 API：目录、注册模型 CRUD、凭据
- `frontend/src/lib/api/mcp.ts` — MCP Server API：三种传输契约、CRUD、刷新、工具列表与执行策略
- `frontend/src/lib/api/tools.ts` — 统一 Tool/Source API：目录、Python 生命周期、固定版本、策略、授权与测试 Invocation
- `frontend/src/lib/api/workflows.ts` — Workflow 草稿、发布版本、Tool/Agent 资源快照、运行与节点审计
- `frontend/src/lib/api/public-workflows.ts` — 已发布 Workflow 的公开/API 会话与运行流
- `frontend/src/lib/api/system.ts` — 系统管理 API：工作空间/团队/用户/审计/运行健康/治理/邀请/会话
- `frontend/src/lib/api/announcements.ts`、`messages.ts` — 公告管理与消息中心（含 `observeMessageStream`）
- `frontend/src/lib/api/analytics.ts` — 工作区运营分析
- `frontend/src/lib/api/agent-skills.ts` — Agent Skill 草稿/导入/发布/版本与授权
- `frontend/src/lib/api/enterprise-identity.ts` — 企业身份连接与公开扫码登录
- `frontend/src/lib/api/resource-folders.ts` — 资源文件夹树/创建/移动

### tests/（bun 测试）

`frontend/tests/` 有 100+ 个测试文件，按命名区分形态：`*.test.ts` 为纯逻辑测试，`*.test.tsx` 为 happy-dom + Testing Library 的 DOM 测试。`bunfig.toml` 的 `[test] preload` 加载 `tests/setup.ts`（注册 happy-dom 全局并把 `asyncUtilTimeout` 提到 5000ms，因为并行 worker 抢占 CPU），DOM 测试复用 `tests/helpers/dom.tsx` 的 `mockUseSession`/`mockNextNavigation`/`renderPage`/`withFetch` 等助手。日常运行 `bun test --parallel`；覆盖率用 `frontend/scripts/coverage.sh`（刻意 `--isolate` 串行，因 bun 并行 worker 会虚增 lcov 行数分母，低于 99% 失败；`--detail` 逐文件查看缺口）。代表性用例：

- `frontend/tests/knowledge-upload-route.test.ts` — 上传路由状态序列化/回环测试
- `frontend/tests/agent-public.test.ts` — 公开 Agent 请求、流取消/重连、脱敏过程与推理增量合并
- `frontend/tests/api-client.test.ts` — request 封装（header/错误 detail）
- `frontend/tests/i18n.test.ts` — 词典一致性/翻译插值
- `frontend/tests/tools-page.test.tsx` — 统一工具中心、来源、状态、策略与错误恢复
- `frontend/tests/tool-picker.test.tsx` — Tool picker 搜索、键盘、焦点与固定版本行为
- `frontend/tests/workflow-node-card.test.tsx` — Workflow Tool/Agent 节点、只读与失效绑定状态
- `frontend/tests/mobile-layout.test.tsx` — `useMediaQuery` 断点跟随，以及列表在手机卡片/桌面表格间的切换

## 关键约定

- 用户可见文案一律走 `t()`（`@/i18n`），新文案须同时加三语词典（类型校验强制同步）。
- API 调用统一走 `lib/api/*`，不直接散落 fetch。
- 新资源详情页复用深路由模式（Agent 用 `[id]/[view]`、知识库用 `[id]/[tab]`，刷新/前进后退可恢复），路径由 `lib/agent-views.ts` 与 `lib/knowledge-views.ts` 的 `appViewPath`/`parse*` 函数集中定义。
- 移动端断点：`< sm`(640px) 用底部标签栏导航，`< md`(768px) 宽表改用卡片列表。两套版式文案相同，因此同一屏只渲染其中一套：组件用 `useMediaQuery(PHONE_LIST_QUERY)` 条件渲染，不要用 `hidden` 属性配合响应式工具类隐藏其中一套（Tailwind preflight 的 `[hidden]` 带 `!important`，会把手机版式也一起隐藏）。
- 手机版式必须保证：整页无横向滚动（`documentElement.scrollWidth === clientWidth`）、可点元素不小于约 40px、固定底栏留出安全区（`pb-safe`，页面级固定操作条用 `bottom-[calc(4.5rem+env(safe-area-inset-bottom))]` 避开底部标签栏）。
