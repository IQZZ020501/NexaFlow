# ADAPTERS 适配层（backend/app/ports 与 backend/app/adapters）

## 职责

统一承载与业务领域正交的外部技术能力（模型调用、向量检索、MCP 客户端、执行平台、企业身份、公告实时投递），并将其拆为两层（文档解析/分块、检索评分与统一工具运行时已迁入各自功能域，见文末）：

- `backend/app/ports/` — **稳定能力契约**：结构化协议（`Protocol`）、共享值类型与**委托函数（delegate functions）**。业务层（`application/`、`domain/`）只依赖本包；当前唯一例外是 `app/application/models/registry.py`、`service.py` 直接 import `app.adapters.llm.credentials`/`providers`（凭据加解密与 `PROVIDER_CATALOG`）；
- `backend/app/adapters/` — **具体实现**：厂商 SDK、Qdrant、MCP 客户端、执行平台、企业身份等第三方集成全部收拢于此；
- 各端口暴露的工厂（`build_*`）是唯一组合点：替换实现只改动对应适配模块与本包，业务层代码不受影响。

`ports/__init__.py` 仅承载包说明（无 `__all__` 汇总导出）。

## app/ports/（能力契约）

- `llm.py` — LLM 供应商端口：`ChatProvider` / `EmbeddingProvider` / `RerankProvider` 结构化协议；工厂 `build_chat_model` / `build_embeddings` / `build_reranker` 依据注册模型配置构造实例；`generate_image` 与 `extract_image_text` 供图片生成与视觉模型抽取图片文字；同时再导出运行时数据类型与统一异常（`ModelCompletion`、`ModelToolCall`、`ModelProviderError` 及状态码/超时子类）、`SUPPORTED_PROVIDER_TYPES`、`MODEL_REQUEST_PARAMS_META_KEY`、`DEFAULT_MODEL_REQUEST_PARAMS`、`test_model_connection` 与 `VISION_MODEL_REQUIRED_MESSAGE`（`RegisteredModel` 仅为类型标注导入，不在导出列表）。业务代码经此构造模型，不触碰具体厂商实现。
- `vector_store.py` — 向量库端口：`VectorStore` Protocol 描述完整契约（健康检查、collection 删除、向量 upsert/查询/删除、图谱画像向量的 upsert/查询与 collection 删除；collection 创建在首次 upsert 时隐式完成），`build_vector_store()` 为组合点，另有同名委托函数（`check_vector_store_health`、`upsert_vectors`、`query_vectors`、`delete_vectors` 与图谱画像系列）；值类型 `VectorChunk` / `VectorHit` / `GraphProfileVector` / `GraphProfileVectorHit` 一并由此再导出。
- `mcp.py` — MCP 客户端端口：`McpClient` Protocol（`discover_mcp_tools` / `call_mcp_tool`），委托函数 `discover_mcp_tools` / `call_mcp_tool` / `normalize_mcp_url`，`build_mcp_client()` 返回多传输客户端实现；连接、发现与错误类型（`McpConnection`、`McpDiscovery`、`McpCallResult`、`McpTransport`、`McpClientError`、`MAX_MCP_TOOL_PAGES` 等）一并再导出。
- `execution.py` — 私有执行能力端口：`ExecutionError`、`ExecutionScope`、`execution_scope` ContextVar、`ExecutionPlatform` Protocol（`execute` / `close_session`）、`build_execution_platform()` 与 `close_execution_session()`；stdio MCP 与 Skill 依赖安装在 OpenSandbox 内执行所依赖的接缝。
- `enterprise_identity.py` — 企业身份端口：`EnterpriseIdentityProvider` Protocol，并再导出实现层契约面（`build_authorization_url`、`resolve_external_principal`、`ExternalPrincipal`、`EnterpriseProviderError`）。
- `announcements.py` — 公告实时投递端口：`AnnouncementLiveStreamPublisher` / `AnnouncementLiveStreamReader`、`AnnouncementStreamEntry` 与 `build_announcement_live_stream_publisher()` / `build_announcement_live_stream_reader()`。
- `errors.py` — `ExternalServiceError`：各端口异常类型的公共基类，供基础设施日志按 `source=external` 归类。

端口中的 Protocol 主要作为静态类型契约，运行时的实际出口是上述委托函数/工厂。

## app/adapters/（具体实现）

### llm/（模型运行时与厂商目录）

- `credentials.py` — 模型凭据加密打包/解密解析（`credential-v1` 密文格式，基于 `app/infra/security/secrets`），并兼容旧格式：`api_base` 按厂商转换为新配置（azure_endpoint、anthropic/ollama 的 api_base 归一等）。
- `runtime.py` — 模型运行时：按 `provider_type` 与解密后的凭据构造各厂商 Chat/Embedding/Reranker 客户端（langchain 系封装 + OpenAI-compatible 自定义实现），统一异常映射为 `ModelProviderError` 族（状态码、超时）；`build_registered_chat_model` / `build_registered_embeddings` / `build_registered_reranker` / `build_registered_vision_model` 依据 `RegisteredModel` + `Settings` 构建；含视觉模型消息构造（`vision_message`、`extract_registered_image_text`）与 `test_model_connection` 连接测试。
- `image.py` — `IMAGE` 类型模型的图片生成：`generate_registered_image`（OpenAI-compatible，PNG 签名校验与体积上限，gpt-image/dall-e 请求整形）。
- `providers/<vendor>_model_provider/catalog.py` — 22 家厂商静态目录（`model_openai_provider`、`model_anthropic_provider`、`model_gemini_provider`、`model_deepseek_provider`、`model_ollama_provider`、`model_azure_provider`、`model_aws_bedrock_provider`、`aliyun_bai_lian_model_provider`、`model_siliconflow_provider`、`model_zhipu_provider`、`model_kimi_provider`、`model_tencent_provider`、`model_tencent_cloud_provider`、`model_volcanic_engine_provider`、`model_wenxin_provider`、`model_xf_provider`、`model_vllm_provider`、`model_local_provider`、`model_regolo_provider`、`model_xinference_provider`、`model_custom_provider`、`model_docker_ai_provider` 等），每份 `CATALOG`：provider 标识、展示名、图标、默认 API 地址、支持的 `model_types` 与模型清单。
- `providers/integrations.py` — 各厂商集成元数据（`adapter`、`runtime_sdk`、`api_protocol`、`model_catalog`、`docs_url` 与 `CATALOG_VERIFIED_AT`），由 `providers/__init__.py` 合并进 `PROVIDER_CATALOG`。

### rag/（向量检索）

- `vector_store.py` — Qdrant 向量库封装：collection 管理（并发创建竞态处理）、向量 upsert/查询/删除、图谱画像 collection（`graph_profile_collection_name` 与 upsert/query/delete/deletion）、结构化日志（`source=external` 分类）。

### mcp/

- `client.py` — 统一 MCP 客户端（`MultiTransportMcpClient`）：Streamable HTTP、legacy SSE、加密 stdio 配置；HTTP DNS/重定向/代理防护，stdio 经 execution port 在 OpenSandbox 内执行；完整保留 content/structuredContent/_meta，超过上界明确失败而非截断为无效 JSON。

### execution/

- `opensandbox.py` — execution port 的私有实现：受信镜像/控制面、资源/TTL、有效网络策略核对、只读 staging、固定非 root 命令、有界结果读取、取消与 destroy；不依赖业务 domain/schema/application，无宿主回退。

### identity/

- `enterprise.py` — 企业身份 OAuth 实现：飞书/钉钉/企业微信授权 URL 构造与授权码换取外部主体（`ExternalPrincipal`），错误统一为 `EnterpriseProviderError`。

### announcements/

- `live_stream.py` — Redis 公告实时流：`RedisAnnouncementLiveStreamPublisher` / `RedisAnnouncementLiveStreamReader`（键前缀 `nexaflow:announcement-live:*`），满足 `app/ports/announcements.py` 契约。

## 已迁出适配层的能力

- 文档解析/分块与问答导入 → `app/domain/knowledge/documents/`：`parsing.py`（`extract_document`、`clean_text`、`normalize_text`、`split_text`、`build_flat_chunks`、`build_hierarchical_chunks`、`chunk_token_count`、`CHUNK_SIZE`/`CHUNK_OVERLAP`/`EMBED_BATCH_SIZE` 与版本常量，含归档加固与 DOCX 内嵌图片资产）、`qa_import.py`（`QaRow`、`extract_qa_rows`、`validate_qa_rows`，仅支持 CSV/XLSX，行数 5000、问题 2000 字符、答案 20000 字符上限）。端口层没有 `DocumentParser`/`build_document_parser`。
- 检索实现 → 评分与证据窗口在 `app/domain/knowledge/retrieval.py`（`RankedHit`、`reciprocal_rank_fusion`、`parent_evidence`、`bounded_text_chunks`、`rerank_child_hits`、`apply_rerank_results`），编排在 `app/application/knowledge/retrieval/service.py`（`retrieve_knowledge_base`）；`adapters/rag/retrieval.py` 已删除。
- 统一工具执行契约 → `app/application/tools/runtime/contracts.py`（`ToolAdapter`、`ToolInvocationContext`、`ToolRuntimeResult`、`ToolAdapterBusy`），基于 `app/entities/tools` 的 `ToolKind`/`ToolSnapshot`/`ToolRef`；实现与工厂在 `app/application/tools/runtime/adapters/`（`builtin.py`/`python_tool.py`/`mcp.py`/`image_generation.py`，`build_tool_adapter(snapshot, settings, server)`）；代码执行走 `app/infra/sandbox`，MCP 工具经 `app/ports/mcp.py` 委托调用，内置工具含产物直读/预检等逻辑。端口层没有 `tool_runtime.py`。
- 模型注册数据访问 → 仓储 `app/infra/db/repositories/models/registry.py`，业务/应用层直接 import（没有 `app/ports/model_registry.py`）。

## 模型注册相关文件的归属

- `RegisteredModel` ORM（model 表，含 provider/model_type/status 约束）→ `backend/app/domain/models/registered.py`
- 凭据规范化与校验（provider/status/model_type 校验与归一、凭据字段规范化与 `apply_model_credentials`、连接测试辅助、`PROVIDER_CATALOG` 查询）→ `backend/app/application/models/registry.py`；模型管理用例编排（审计记录、DTO 组装等）→ `backend/app/application/models/service.py`
- 数据访问仓储（列表/按 ID/按名称查、删除）→ `backend/app/infra/db/repositories/models/registry.py`
- 检索评测指标（hit@k、recall@k、RR、NDCG 及延迟分位聚合）→ `backend/app/domain/knowledge/evaluation/metrics.py`

## 依赖方向

业务层（`application/`、`domain/`）依赖 `app/ports`（契约），`app/adapters`（实现）依赖并实现这些契约；`application/models/` 直接依赖 `app.adapters.llm` 的凭据与目录模块，是上述已知例外。实现层可组合 `app/infra` 提供的基础设施（db 会话、secrets、settings、sandbox、observability）与 `app/entities`、`app/domain` 中的值对象/ORM；`app/ports` 自身不依赖任何具体适配实现，保证能力可替换。
