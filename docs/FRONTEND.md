# FRONTEND 模块（frontend/）

## 架构

Next.js 15 App Router 客户端渲染 SPA（多数页面 `'use client'`）：`app/` 路由薄壳委托给 `components/` 巨型页面组件；`contexts/` 提供语言/主题/会话全局状态；`lib/api/` 按域划分的 API 客户端统一走 `lib/api-client.ts` 的 fetch 封装（dev 下 `/api` 由 Next rewrite 代理到 FastAPI）；`i18n/` 以中文文案为键的三语词典；系统管理（dashboard 路由组）与平台工作区（platform 路由组）共享 SessionGate/TopBar。技术栈：React 19 + Tailwind v4 + shadcn/ui（radix-nova），Bun 脚本。

## 文件清单

### 根目录配置

- `frontend/package.json` — 项目清单与 bun 脚本（dev/build/start/lint/test/typecheck）
- `frontend/tsconfig.json` — 严格模式 TS 配置，`@/*` 路径别名
- `frontend/next.config.ts` — Next.js 配置：`/api`、完整 Swagger `/docs`/`/openapi.json` 与 `/health` 代理到 FastAPI（`NEXAFLOW_API_PROXY`），standalone 输出
- `frontend/postcss.config.mjs` — Tailwind v4 PostCSS 插件配置
- `frontend/eslint.config.js` — ESLint flat config（TS + React Hooks 规则）
- `frontend/components.json` — shadcn 注册表配置
- `frontend/next-env.d.ts` — Next.js 自动生成的类型引用（勿手改）
- `frontend/app/globals.css` — 全局 Tailwind v4 主题 CSS 变量与暗色模式
- `frontend/types/css.d.ts` — CSS 模块类型声明

### app/ 路由组

- `frontend/app/layout.tsx` — 根布局：元信息 + AppProviders 包裹
- `frontend/app/page.tsx` — 首页重定向到 `/app/apps`
- `frontend/app/(platform)/app/layout.tsx` — 平台区布局：SessionGate + TopBar
- `frontend/app/(platform)/app/page.tsx` — 重定向到 `/app/apps`
- `frontend/app/(platform)/app/knowledge/page.tsx` — 知识库列表页
- `frontend/app/(platform)/app/knowledge/[id]/page.tsx` — 知识库详情页
- `frontend/app/(platform)/app/knowledge/[id]/upload/page.tsx` — 上传向导「选择文件」步骤
- `frontend/app/(platform)/app/knowledge/[id]/upload/segment/page.tsx` — 上传向导「分段预览」步骤（server 解析路由状态）
- `frontend/app/(platform)/app/knowledge/[id]/documents/[docId]/page.tsx` — 文档详情页
- `frontend/app/(platform)/app/tools/page.tsx` — MCP 工具管理页
- `frontend/app/(platform)/app/apps/page.tsx` — Agent 应用列表页
- `frontend/app/(platform)/app/apps/[id]/page.tsx` — Agent 详情页
- `frontend/app/(public)/chat/[id]/page.tsx` — 已发布 Agent 的匿名公开对话页
- `frontend/app/(public)/agent-api/[id]/docs/page.tsx` — API Key 解锁的单 Agent API 文档页
- `frontend/app/(platform)/app/models/page.tsx` — 模型管理页
- `frontend/app/(auth)/login/page.tsx` — 登录页（登录回调与已登录跳转）
- `frontend/app/(dashboard)/system/layout.tsx` — 系统管理布局
- `frontend/app/(dashboard)/system/page.tsx` — 重定向到 `/system/workspaces`
- `frontend/app/(dashboard)/system/[tab]/page.tsx` — 系统管理 Tab 页（workspaces/teams/users/audit）

### components/（按功能分组）

**knowledge/**（知识库功能）
- `frontend/components/knowledge/knowledge-base-page.tsx` — 知识库列表/详情/上传向导主组件（CRUD/权限/任务）
- `frontend/components/knowledge/knowledge-upload-flow.tsx` — 上传流程（选文件→上传→分段预览）
- `frontend/components/knowledge/knowledge-base-dialogs.tsx` — 新建/编辑/权限分配对话框
- `frontend/components/knowledge/document-detail-page.tsx` — 文档详情：分段、任务、重新解析/向量化
- `frontend/components/knowledge/chunk-preview-list.tsx` — 分段预览列表（智能模式按 Parent 分组，高级模式平铺，高亮同 Parent 相邻重叠文本）
- `frontend/components/knowledge/markdown-content.tsx` — react-markdown + GFM 渲染
- `frontend/components/knowledge/status-badges.tsx` — 状态/权限徽章
- `frontend/components/knowledge/status-labels.ts` — 状态中文标签与状态点样式映射

**agents/**（Agent 功能）
- `frontend/components/agents/agents-page.tsx` — Agent CRUD、持久 Run 提交、PostgreSQL/Redis 双游标重连、实时答案与审批状态合并
- `frontend/components/agents/agent-detail-workspace.tsx` — 运行工作台：过程事件、待审批/不确定工具调用处理
- `frontend/components/agents/agent-config-fields.tsx` — 配置表单字段（模型、显式知识检索策略、知识库/MCP）
- `frontend/components/agents/agent-management-panels.tsx` — Agent 概览、API 凭据、对话日志、监控统计与对话用户面板
- `frontend/components/agents/public-agent-chat.tsx` — 匿名公开对话历史、提问、脱敏执行摘要与答案流；最终回答沿用调试页的 Markdown 展示，执行链展示模型思考过程但不暴露工具名称/参数或检索原文
- `frontend/components/agents/agent-api-documentation.tsx` — 校验 Agent API Key 后仅展示当前 Agent 的 API 调用文档

**llm/**（模型功能）
- `frontend/components/llm/llm-page.tsx` — 模型管理页：注册模型 CRUD、凭据、目录浏览

**tools/**（工具功能）
- `frontend/components/tools/mcp-tools-page.tsx` — MCP Server 管理：Streamable HTTP/SSE URL 配置、stdio 命令/参数/工作目录/环境变量填写与管理员工具执行策略审核

**system/**（系统管理功能）
- `frontend/components/system/system-shell.tsx` — 系统管理壳：数据加载、CRUD 编排、Tab 切换
- `frontend/components/system/system-page-view.tsx` — 四 Tab 面板 + 对话框装配
- `frontend/components/system/system-utils.ts` — 格式化工具（角色/审计详情）
- `frontend/components/system/panels/global-users-panel.tsx` — 全局用户列表面板
- `frontend/components/system/panels/workspace-users-panel.tsx` — 工作空间成员面板
- `frontend/components/system/panels/workspaces-panel.tsx` — 工作空间列表面板
- `frontend/components/system/panels/teams-panel.tsx` — 团队列表面板
- `frontend/components/system/panels/audit-panel.tsx` — 审计日志面板
- `frontend/components/system/dialogs/scope-dialogs.tsx` — 工作空间/团队对话框
- `frontend/components/system/dialogs/user-dialogs.tsx` — 用户对话框

**auth/**（认证功能）
- `frontend/components/auth/login-screen.tsx` — 登录表单（含初始密码强制修改）
- `frontend/components/auth/change-password-dialog.tsx` — 修改密码对话框

**app/**（平台壳）
- `frontend/components/app/top-bar.tsx` — 顶栏：导航、工作空间/语言/主题切换、用户菜单
- `frontend/components/app/session-gate.tsx` — 会话门禁：未登录跳转、强制改密
- `frontend/components/app/top-progress.tsx` — 路由切换进度条
- `frontend/components/app/operation-notification.tsx` — 成功/错误通知条
- `frontend/components/app/filter-dropdown.tsx` — 通用下拉筛选

**ui/**（shadcn 基础组件）
- `frontend/components/ui/button.tsx`、`input.tsx`、`label.tsx`、`card.tsx`、`dialog.tsx`、`dropdown-menu.tsx`、`field.tsx`、`icon-button.tsx`、`avatar.tsx`、`badge.tsx`、`spec.tsx`（键值展示小部件）

**pages/**
- `frontend/components/pages/placeholder-page.tsx` — 功能占位页

### contexts/（全局状态）

- `frontend/contexts/app-providers.tsx` — 组合 Language/Theme/Session Provider
- `frontend/contexts/session-context.tsx` — 全局会话：token/me/工作空间/通知/强制改密/刷新
- `frontend/contexts/language-provider.tsx` — 三语切换与 `t()` 翻译
- `frontend/contexts/theme-provider.tsx` — 主题（light/dark/system）

### i18n/（三语词典，键即中文文案）

- `frontend/i18n/index.ts` — 词典注册表、`translate()` 插值、语言选项与存储键
- `frontend/i18n/zh-hans.ts` — 简体中文词典
- `frontend/i18n/zh-hant.ts` — 繁体中文词典
- `frontend/i18n/en.ts` — 英文词典

### lib/

- `frontend/lib/api-client.ts` — fetch 封装：JSON/FormData、Bearer token、ApiError 归一化
- `frontend/lib/knowledge-upload-route.ts` — 上传路由状态 URL 序列化/校验
- `frontend/lib/pages.ts` — 四大功能页布局元数据目录
- `frontend/lib/storage.ts` — localStorage 键常量
- `frontend/lib/utils.ts` — `cn()` class 合并
- `frontend/lib/dom.ts` — dropdown 事件来源判定
- `frontend/lib/errors.ts` — 统一错误文案
- `frontend/lib/notifications.ts` — AppNotification 类型
- `frontend/lib/password.ts` — 新密码校验
- `frontend/lib/chunk-overlap.ts` — 分段重叠文本检测
- `frontend/lib/constants.ts` — 默认密码、状态/审计标签键映射
- `frontend/lib/display.ts` — 展示格式化工具
- `frontend/lib/theme-options.ts` — 主题选项定义

**lib/api/**（按域划分的 API 客户端）
- `frontend/lib/api/auth.ts` — 认证 API：登录/登出/me/刷新/改密
- `frontend/lib/api/knowledge.ts` — 知识库 API：知识库/文档/任务/chunk/检索
- `frontend/lib/api/agents.ts` — Agent API：CRUD、发布、API 凭据、日志/统计/用户、Run 提交/游标订阅/自动重连、工具审批
- `frontend/lib/api/public-agents.ts` — 公开 Agent 资料、访客会话、历史和脱敏 Run 流
- `frontend/lib/api/run-stream.ts` — 登录态与公开 Run 共用的 NDJSON 双游标重连器
- `frontend/lib/api/llm.ts` — 模型 API：目录、注册模型 CRUD、凭据
- `frontend/lib/api/mcp.ts` — MCP Server API：三种传输契约、CRUD、刷新、工具列表与执行策略
- `frontend/lib/api/system.ts` — 系统管理 API：工作空间/团队/用户/审计

### tests/（bun 测试）

- `frontend/tests/knowledge-upload-route.test.ts` — 上传路由状态序列化/回环测试
- `frontend/tests/agent-draft.test.ts` — Agent 表单脏检查与运行合并逻辑
- `frontend/tests/api-client.test.ts` — request 封装（header/错误 detail）
- `frontend/tests/chunk-overlap.test.ts` — 分段重叠检测边界
- `frontend/tests/dialog-dropdown-interaction.test.ts` — dropdown 事件判定
- `frontend/tests/feature-page-catalog.test.ts` — pages 目录完整性
- `frontend/tests/i18n.test.ts` — 词典一致性/翻译插值
- `frontend/tests/mcp-registration.test.ts` — MCP 三种传输创建载荷与隐藏字段隔离

## 关键约定

- 用户可见文案一律走 `t()`（`@/i18n`），新文案须同时加三语词典（类型校验强制同步）。
- API 调用统一走 `lib/api/*`，不直接散落 fetch。
- 新资源详情页复用 `[id]` 深路由模式（刷新/前进后退可恢复）。
