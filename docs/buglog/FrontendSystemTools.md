# FrontendSystemTools 发现的 BUG

## low: request() 对非 JSON 错误响应体抛 JSON.parse 异常

- 编号: BUG-frontend-001
- 严重度: low
- 模块: `frontend/lib/api-client.ts::request`（`errorMessage` 前置的 `JSON.parse(text)`）
- 现象: 后端返回非 JSON 错误体（如 `500 text/plain "boom text"`）时，`request()`
  在 `const payload = text ? JSON.parse(text) : null` 处抛出
  `SyntaxError: JSON Parse error: Unexpected identifier "boom"`，而非 `ApiError`，
  导致上层 `getErrorMessage` 拿到的是解析错误而不是后端消息（错误文本被吞掉）。
- 预期: 非 JSON 错误体应走 `errorMessage(payload, statusText)` 的兜底分支，
  将响应文本作为 fallback 消息并抛出 `ApiError`（与 `requestBlob` 一致）。
- 复现: `frontend/tests/system-tools.test.tsx` 中
  `request surfaces API error details` 用例
  （`new Response("boom text", { status: 500 })` 时 `listTeams` 抛出的是
  `JSON.parse` 的 `SyntaxError` 而非 `ApiError`）。
- 来源: `frontend/tests/system-tools.test.tsx`（系统 API 客户端覆盖套件）
