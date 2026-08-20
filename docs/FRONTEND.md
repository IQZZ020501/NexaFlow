# FRONTEND 模块（frontend/）

## 架构

Next.js 16 App Router 客户端渲染 SPA（多数页面 `'use client'`）：`src/app/` 路由薄壳委托给 `src/components/` 巨型页面组件；`src/contexts/` 提供语言/主题/会话全局状态；`src/lib/api/` 按域划分的 API 客户端统一走 `src/lib/api-client.ts` 的 fetch 封装（dev 下 `/api` 由 Next rewrite 代理到 FastAPI）；`src/i18n/` 以中文文案为键的三语词典；系统管理（dashboard 路由组）与平台工作区（platform 路由组）共享 SessionGate/TopBar。技术栈：React 19 + Tailwind v4 + shadcn/ui（radix-nova），Bun 脚本。

## 文件清单

### 根目录配置

- `frontend/package.json` — 项目清单与 bun 脚本（dev/build/start/lint/test/typecheck）
- `frontend/tsconfig.json` — 严格模式 TS 配置，`@/*` 路径别名
- `frontend/next.config.ts` — Next.js 配置：`/api`、完整 Swagger `/docs`/`/openapi.json` 与 `/health` 代理到 FastAPI（`NEXAFLOW_API_PROXY`），standalone 输出
- `frontend/postcss.config.mjs` — Tailwind v4 PostCSS 插件配置
- `frontend/eslint.config.js` — ESLint flat config（TS + React Hooks 规则）
- `frontend/components.json` — shadcn 注册表配置
- `frontend/next-env.d.ts` — Next.js 自动生成的类型引用（勿手改）
- `frontend/src/app/globals.css` — 全局 Tailwind v4 主题 CSS 变量与暗色模式
- `frontend/src/types/css.d.ts` — CSS 模块类型声明

### app/ 路由组

- `frontend/src/app/layout.tsx` — 根布局：元信息 + AppProviders 包裹
- `frontend/src/app/page.tsx` — 首页重定向到 `/app/apps`
- `frontend/src/app/not-found.tsx` — 站点级三语 404 页面，不回显后端资源细节
- `frontend/src/app/(platform)/app/layout.tsx` — 平台区布局：SessionGate + TopBar
- `frontend/src/app/(platform)/app/page.tsx` — 重定向到 `/app/apps`
- `frontend/src/app/(platform)/app/knowledge/page.tsx` — 知识库列表页
- `frontend/src/app/(platform)/app/knowledge/[id]/page.tsx` — 知识库详情页
- `frontend/src/app/(platform)/app/knowledge/[id]/upload/page.tsx` — 上传向导「选择文件」步骤
- `frontend/src/app/(platform)/app/knowledge/[id]/upload/segment/page.tsx` — 上传向导「分段预览」步骤（server 解析路由状态）
- `frontend/src/app/(platform)/app/knowledge/[id]/documents/[docId]/page.tsx` — 文档详情页
- `frontend/src/app/(platform)/app/tools/page.tsx` — 统一工具中心：builtin/Python/MCP 目录、来源与授权管理
- `frontend/src/app/(platform)/app/apps/page.tsx` — Agent 应用列表页
- `frontend/src/app/(platform)/app/apps/[id]/page.tsx` — Agent 详情页
- `frontend/src/app/(platform)/workflow/[id]/page.tsx` — Workflow 画布；查看授权用户进入只读模式
- `frontend/src/app/(public)/chat/[id]/page.tsx` — 已发布 Agent 的匿名公开对话页
- `frontend/src/app/(public)/agent-api/[id]/docs/page.tsx` — API Key 解锁的单 Agent API 文档页
- `frontend/src/app/(platform)/app/models/page.tsx` — 模型管理页
- `frontend/src/app/(auth)/login/page.tsx` — 登录页（登录回调与已登录跳转）
- `frontend/src/app/(dashboard)/system/layout.tsx` — 系统管理布局
- `frontend/src/app/(dashboard)/system/page.tsx` — 重定向到 `/system/workspaces`
- `frontend/src/app/(dashboard)/system/[tab]/page.tsx` — 系统管理 Tab 页（workspaces/teams/users/audit）

### components/（按功能分组）

**knowledge/**（知识库功能）
- `frontend/src/components/knowledge/knowledge-base-page.tsx` — 知识库列表/详情/上传向导主组件（CRUD/权限/任务）
- `frontend/src/components/knowledge/knowledge-upload-flow.tsx` — 上传流程（选文件→上传→分段预览）
- `frontend/src/components/knowledge/knowledge-base-dialogs.tsx` — 新建/编辑/权限分配对话框
- `frontend/src/components/knowledge/document-detail-page.tsx` — 文档详情：分段、任务、重新解析/向量化
- `frontend/src/components/knowledge/chunk-preview-list.tsx` — 分段预览列表（智能模式按 Parent 分组，高级模式平铺，高亮同 Parent 相邻重叠文本）
- `frontend/src/components/knowledge/markdown-content.tsx` — react-markdown + GFM 渲染
- `frontend/src/components/knowledge/status-badges.tsx` — 状态/权限徽章
- `frontend/src/components/knowledge/status-labels.ts` — 状态中文标签与状态点样式映射

**agents/**（Agent 功能）
- `frontend/src/components/agents/agents-page.tsx` — Agent CRUD、持久 Run 提交、PostgreSQL/Redis 双游标重连、实时答案与审批状态合并
- `frontend/src/components/agents/agent-detail-workspace.tsx` — 运行工作台：过程事件、待审批/不确定工具调用处理
- `frontend/src/components/agents/agent-config-fields.tsx` — 配置表单字段（模型、显式知识检索策略、知识库与统一 Tool picker）
- `frontend/src/components/agents/agent-management-panels.tsx` — Agent 概览、API 凭据、对话日志、监控统计与对话用户面板
- `frontend/src/components/agents/public-agent-chat.tsx` — 匿名公开对话历史、提问、脱敏执行摘要与答案流；最终回答沿用调试页的 Markdown 展示，执行链展示模型思考过程但不暴露工具名称/参数或检索原文
- `frontend/src/components/agents/agent-api-documentation.tsx` — 校验 Agent API Key 后仅展示当前 Agent 的 API 调用文档

**llm/**（模型功能）
- `frontend/src/components/llm/llm-page.tsx` — 模型管理页：注册模型 CRUD、凭据、目录浏览

**tools/**（工具功能）
- `frontend/src/components/tools/tools-page.tsx` — 生产工具中心：mine/shared/builtin 分组、跨页加载、详情、来源状态、策略与授权入口
- `frontend/src/components/tools/python-tool-dialog.tsx` — Python Tool 草稿、schema、沙箱测试、发布与版本状态
- `frontend/src/components/tools/mcp-source-dialog.tsx` — MCP Source 创建：普通成员公网 HTTP/SSE，管理员额外支持 stdio/私网
- `frontend/src/components/tools/tool-permissions-dialog.tsx` — 同工作空间成员搜索及 `view/use/none` 授权管理
- `frontend/src/components/tools/tool-picker.tsx` — Agent 共用 Tool picker：搜索、键盘选择、固定 Tool/Version 引用与失效状态
- `frontend/src/components/tools/mcp-tools-page.tsx` — 旧 MCP 专页兼容组件；生产 `/app/tools` 不再使用，仅保留既有回归覆盖

**system/**（系统管理功能）
- `frontend/src/components/system/system-shell.tsx` — 系统管理壳：数据加载、CRUD 编排、Tab 切换
- `frontend/src/components/system/system-page-view.tsx` — 四 Tab 面板 + 对话框装配
- `frontend/src/components/system/system-utils.ts` — 格式化工具（角色/审计详情）
- `frontend/src/components/system/panels/global-users-panel.tsx` — 全局用户列表面板
- `frontend/src/components/system/panels/workspace-users-panel.tsx` — 工作空间成员面板
- `frontend/src/components/system/panels/workspaces-panel.tsx` — 工作空间列表面板
- `frontend/src/components/system/panels/teams-panel.tsx` — 团队列表面板
- `frontend/src/components/system/panels/audit-panel.tsx` — 审计日志面板
- `frontend/src/components/system/dialogs/scope-dialogs.tsx` — 工作空间/团队对话框
- `frontend/src/components/system/dialogs/user-dialogs.tsx` — 用户对话框

**auth/**（认证功能）
- `frontend/src/components/auth/login-screen.tsx` — 登录表单（含初始密码强制修改）
- `frontend/src/components/auth/change-password-dialog.tsx` — 修改密码对话框

**app/**（平台壳）
- `frontend/src/components/app/top-bar.tsx` — 顶栏：导航、工作空间/语言/主题切换、用户菜单
- `frontend/src/components/app/session-gate.tsx` — 会话门禁：未登录跳转、强制改密
- `frontend/src/components/app/top-progress.tsx` — 路由切换进度条
- `frontend/src/components/app/operation-notification.tsx` — 成功/错误通知条
- `frontend/src/components/app/filter-dropdown.tsx` — 通用下拉筛选

**ui/**（shadcn 基础组件）
- `frontend/src/components/ui/button.tsx`、`input.tsx`、`label.tsx`、`card.tsx`、`dialog.tsx`、`dropdown-menu.tsx`、`field.tsx`、`icon-button.tsx`、`avatar.tsx`、`badge.tsx`、`spec.tsx`（键值展示小部件）

**pages/**
- `frontend/src/components/pages/placeholder-page.tsx` — 功能占位页

### contexts/（全局状态）

- `frontend/src/contexts/app-providers.tsx` — 组合 Language/Theme/Session Provider
- `frontend/src/contexts/session-context.tsx` — 全局会话：token/me/工作空间/通知/强制改密/刷新
- `frontend/src/contexts/language-provider.tsx` — 三语切换与 `t()` 翻译
- `frontend/src/contexts/theme-provider.tsx` — 主题（light/dark/system）

### i18n/（三语词典，键即中文文案）

- `frontend/src/i18n/index.ts` — 词典注册表、`translate()` 插值、语言选项与存储键
- `frontend/src/i18n/zh-hans.ts` — 简体中文词典
- `frontend/src/i18n/zh-hant.ts` — 繁体中文词典
- `frontend/src/i18n/en.ts` — 英文词典

### lib/

- `frontend/src/lib/api-client.ts` — fetch 封装：JSON/FormData、Bearer token、ApiError 归一化
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
- `frontend/src/lib/theme-options.ts` — 主题选项定义

**lib/api/**（按域划分的 API 客户端）
- `frontend/src/lib/api/auth.ts` — 认证 API：登录/登出/me/刷新/改密
- `frontend/src/lib/api/knowledge.ts` — 知识库 API：知识库/文档/任务/chunk/检索
- `frontend/src/lib/api/agents.ts` — Agent API：CRUD、发布、API 凭据、日志/统计/用户、Run 提交/游标订阅/自动重连、工具审批
- `frontend/src/lib/api/public-agents.ts` — 公开 Agent 资料、访客会话、历史和脱敏 Run 流
- `frontend/src/lib/api/run-stream.ts` — 登录态与公开 Run 共用的 NDJSON 双游标重连器
- `frontend/src/lib/api/llm.ts` — 模型 API：目录、注册模型 CRUD、凭据
- `frontend/src/lib/api/mcp.ts` — MCP Server API：三种传输契约、CRUD、刷新、工具列表与执行策略
- `frontend/src/lib/api/tools.ts` — 统一 Tool/Source API：目录、Python 生命周期、固定版本、策略、授权与测试 Invocation
- `frontend/src/lib/api/workflows.ts` — Workflow 草稿、发布版本、Tool/Agent 资源快照、运行与节点审计
- `frontend/src/lib/api/public-workflows.ts` — 已发布 Workflow 的公开/API 会话与运行流
- `frontend/src/lib/api/system.ts` — 系统管理 API：工作空间/团队/用户/审计

### tests/（bun 测试）

- `frontend/tests/knowledge-upload-route.test.ts` — 上传路由状态序列化/回环测试
- `frontend/tests/agent-draft.test.ts` — Agent 表单脏检查与运行合并逻辑
- `frontend/tests/agent-public.test.ts` — 公开 Agent 请求、流取消/重连、脱敏过程与推理增量合并
- `frontend/tests/api-client.test.ts` — request 封装（header/错误 detail）
- `frontend/tests/chunk-overlap.test.ts` — 分段重叠检测边界
- `frontend/tests/dialog-dropdown-interaction.test.ts` — dropdown 事件判定
- `frontend/tests/feature-page-catalog.test.ts` — pages 目录完整性
- `frontend/tests/i18n.test.ts` — 词典一致性/翻译插值
- `frontend/tests/mcp-registration.test.ts` — MCP 三种传输创建载荷与隐藏字段隔离
- `frontend/tests/tools-page.test.tsx` — 统一工具中心、来源、状态、策略与错误恢复
- `frontend/tests/tool-picker.test.tsx` — Tool picker 搜索、键盘、焦点与固定版本行为
- `frontend/tests/tool-permissions-dialog.test.tsx` — 成员搜索、授权切换、撤销与失败重试
- `frontend/tests/workflow-node-card.test.tsx` — Workflow Tool/Agent 节点、只读与失效绑定状态

## 关键约定

- 用户可见文案一律走 `t()`（`@/i18n`），新文案须同时加三语词典（类型校验强制同步）。
- API 调用统一走 `lib/api/*`，不直接散落 fetch。
- 新资源详情页复用 `[id]` 深路由模式（刷新/前进后退可恢复）。
