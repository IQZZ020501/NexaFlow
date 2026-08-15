# InfraUnitCoverage — BUG 记录

> 由 `tests/infra_unit_coverage.py`（LLM/MCP 基础设施与团队服务覆盖率套件）产生。
> 只记录、不修改产品代码。格式见 docs/BUG_LOG.md 顶部。

## 发现的 BUG 汇总

### medium: 模型凭据解密失败时 Fernet InvalidToken 逃逸，未归一化为 ModelProviderError

- 编号: BUG-infraunit-001
- 严重度: medium
- 状态: **已修复（2026-08-15）**
- 模块:
  - `backend/app/capabilities/llm/runtime.py:624-625`（`_registered_model_credentials`）
  - `backend/app/capabilities/llm/registry.py:150-153`（`stored_model_credentials`）
  - `backend/app/capabilities/llm/credentials.py:33-47`（`decrypt_credential_secrets`）
- 现象: `decrypt_secret`（Fernet）对任何损坏/篡改/密钥不匹配的密文都抛出
  `cryptography.fernet.InvalidToken`，而 `InvalidToken` 的 MRO 是
  `(InvalidToken, Exception, BaseException, object)` —— **不是** `ValueError`
  子类。`_registered_model_credentials` 的
  `except (ValueError, json.JSONDecodeError) as exc: raise ModelProviderError("Stored model credentials are invalid.")`
  因此永远捕不到 Fernet 解密失败；`stored_model_credentials` 甚至没有任何 try/except。
  后果：数据库中 `api_key_ciphertext` 一旦损坏（或被错误密钥加密），
  `build_registered_chat_model` / `build_registered_embeddings` / `build_registered_reranker`
  以及模型更新流程会直接抛出裸 `InvalidToken`（HTTP 500 / 任务失败），而不是预期的
  `ModelProviderError("Stored model credentials are invalid.")`（HTTP 400/业务错误）。
- 预期: 所有解密失败（含 `InvalidToken`）都应被捕获并归一化为
  `ModelProviderError`。修复建议：在 `decrypt_credential_secrets` 内把
  `InvalidToken` 包装为 `ValueError`，或在调用处把 `cryptography.fernet.InvalidToken`
  加入捕获元组。
- 复现:
  ```python
  from app.capabilities.llm.runtime import _registered_model_credentials
  from app.capabilities.llm.models import RegisteredModel
  from tests.support import settings
  model = RegisteredModel(workspace_id="w", name="m", provider="p",
      provider_type="deepseek", api_base="", model_type="LLM", model_name="m",
      api_key_ciphertext="garbage-not-a-token", status="active",
      created_by_user_id="u")
  _registered_model_credentials(model, settings(), "LLM")
  # -> 抛出 cryptography.fernet.InvalidToken（应为 ModelProviderError）
  ```
- 来源: tests.infra_unit_coverage（`test_registered_model_credentials` 记录实际行为；合法可达的 ValueError 分支用 `SECRET_BUNDLE_PREFIX + 非法 JSON` 密文覆盖）
- 修复: 共享凭据解密边界将 `InvalidToken` 归一化为 `ValueError`；模型更新接口映射为
  HTTP 400，Agent/Workflow 构建路径继续映射为 `ModelProviderError`。
