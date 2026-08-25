# NexaFlow Frontend

NexaFlow 的 Web 前端，基于 Next.js 16 App Router、React 19、TypeScript、Bun、shadcn/ui 和 Tailwind CSS。

## 本地开发

```bash
bun install --frozen-lockfile
bun run dev
```

开发服务器默认监听 <http://localhost:3000>，并将 `/api`、`/health`、`/docs` 和 `/openapi.json` 转发到 `http://127.0.0.1:8000`。如需使用其他后端地址，设置 `NEXAFLOW_API_PROXY`。

## 常用检查

```bash
bun run typecheck
bun run lint
bun test --parallel
bun run build
```

## 目录约定

- `src/app/`：App Router 页面，包含认证、平台、管理后台和已发布应用访问页。
- `src/components/`：共享组件与功能组件。
- `src/contexts/`：全局上下文和 Provider。
- `src/i18n/`：简体中文、繁体中文和英文词典。
- `src/lib/api/`：按功能拆分的 API 客户端。
- `tests/`：Bun 与 happy-dom 测试。

所有用户可见文案必须通过 `@/i18n` 的 `t()` 获取，并同步更新三种语言。已发布 Agent 的访问页面要求用户登录且属于 Agent 所在工作空间；独立系统接入使用 Agent API Key。
