# ADAPTERS 适配层（backend/app/ports 与 backend/app/adapters）

## 职责

统一承载与业务领域正交的外部技术能力（模型调用、向量检索、文档解析、MCP 客户端、工具执行、企业身份），并将其拆为两层：

- `backend/app/ports/` — **稳定能力契约**：结构化协议（`Protocol`）、共享值类型与**委托函数（delegate functions）**。业务层（`application/`、`domain/`）只依赖本包，不直接 import `app.adapters`；
- `backend/app/adapters/` — **具体实现**：厂商 SDK、Qdrant、解析器、MCP 客户端、沙箱工具等第三方集成全部收拢于此；
- 各端口暴露的工厂（`build_*`）是唯一组合点：替换实现只改动对应适配模块与本包，业务层代码不受影响。

`ports/__init__.py` 汇总导出各端口。

## app/ports/（能力契约）

- `llm.py` — LLM 供应商端口：`ChatProvider` / `EmbeddingProvider` / `RerankProvider` 结构化协议；工厂 `build_chat_model` / `build_embeddings` / `build_reranker` 依据注册模型配置构造实例；`extract_image_text` 供视觉模型抽取图片文字；同时再导出运行时数据类型与统一异常（`ModelCompletion`、`ModelToolCall`、`ModelProviderError` 及状态码/超时子类）、`RegisteredModel` 与 `VISION_MODEL_REQUIRED_MESSAGE`。业务代码经此构造模型，不触碰具体厂商实现。
- `model_registry.py` — 模型注册数据访问端口：`ModelRegistry` Protocol（列表/按 ID/按名称查、删除等），同名的委托函数直接转发到仓储实现（见 `app/infra/db/repositories/models/registry.py`），`build_model_registry()` 为组合点。
- `vector_store.py` — 向量库端口：`VectorStore` Protocol 描述完整契约（健康检查、collection 创建/删除、向量 upsert/查询/删除、图谱画像向量的 upsert/查询与 collection 删除），`build_vector_store()` 为单一组合点（当前后端为 Qdrant，实现为 `QdrantVectorStore`）；值类型 `VectorChunk` / `VectorHit` / `GraphProfileVector` / `GraphProfileVectorHit` 一并由此再导出。
- `parsing.py` — 文档解析与分块端口：`DocumentParser` Protocol 与 `build_document_parser()` 组合点；解析/清洗/分块的纯函数（`extract_document`、`clean_text`、`normalize_text`、`split_text`、`build_flat_chunks`、`build_hierarchical_chunks`、`chunk_token_count` 等）及分块常量（`CHUNK_SIZE`、`CHUNK_OVERLAP`、`EMBED_BATCH_SIZE`、各版本号）从实现层再导出；问答对解析（`QaRow`、`extract_qa_rows`）也在此暴露。
- `mcp.py` — MCP 客户端端口：`McpClient` Protocol（`discover_mcp_tools` / `call_mcp_tool`），委托函数 `discover_mcp_tools` / `call_mcp_tool` / `normalize_mcp_url`，`build_mcp_client()` 返回多传输客户端实现；连接、发现与错误类型（`McpConnection`、`McpDiscovery`、`McpClientError` 等）一并再导出。
- `tool_runtime.py` — 统一工具执行的 provider-neutral 契约：`ToolAdapter` Protocol（`kind` + `invoke`）、`ToolInvocationContext`、`ToolRuntimeResult`、`ToolAdapterBusy`；基于 `app/entities/tools` 的 `ToolKind` / `ToolSnapshot` / `ToolRef`。
- `enterprise_identity.py` — 企业身份端口：再导出实现层契约面（`build_authorization_url`、`resolve_external_principal`、`ExternalPrincipal`、`EnterpriseProviderError`）。

端口中的 Protocol 主要作为静态类型契约，运行时的实际出口是上述委托函数/工厂。

## app/adapters/（具体实现）

### llm/（模型运行时与厂商目录）

- `credentials.py` — 模型凭据加密打包/解密解析（`credential-v1` 密文格式，基于 `app/infra/security/secrets`），并兼容旧格式：`api_base` 按厂商转换为新配置（azure_endpoint、anthropic/ollama 的 api_base 归一等）。
- `runtime.py` — 模型运行时：按 `provider_type` 与解密后的凭据构造各厂商 Chat/Embedding/Reranker 客户端（langchain 系封装 + OpenAI-compatible 自定义实现），统一异常映射为 `ModelProviderError` 族（状态码、超时）；`build_registered_chat_model` / `build_registered_embeddings` / `build_registered_reranker` 依据 `RegisteredModel` + `Settings` 构建；含视觉模型消息构造与图片文字抽取、`test_model_connection` 连接测试。
- `providers/<vendor>_model_provider/catalog.py` — 22 家厂商静态目录（`model_openai_provider`、`model_anthropic_provider`、`model_gemini_provider`、`model_deepseek_provider`、`model_ollama_provider`、`model_azure_provider`、`model_aws_bedrock_provider`、`aliyun_bai_lian_model_provider`、`model_siliconflow_provider`、`model_zhipu_provider`、`model_kimi_provider`、`model_tencent_provider`、`model_tencent_cloud_provider`、`model_volcanic_engine_provider`、`model_wenxin_provider`、`model_xf_provider`、`model_vllm_provider`、`model_local_provider`、`model_regolo_provider`、`model_xinference_provider`、`model_custom_provider`、`model_docker_ai_provider` 等），每份 `CATALOG`：provider 标识、展示名、图标、默认 API 地址、支持的 `model_types` 与模型清单。
- `providers/__init__.py` — 汇总全部 provider 目录的 `CATALOG` 为 `PROVIDER_CATALOG`。

### rag/（向量检索）

- `vector_store.py` — Qdrant 向量库封装：collection 管理（并发创建竞态处理）、向量 upsert/查询/删除、结构化日志（`source=external` 分类）。
- `retrieval.py` — 知识库检索：Child 向量召回 + 关键词命中 RRF、可选 Child 重排、Parent 去重与预算内上下文扩展；平铺文档保持原聚合行为。

### parsing/（文档解析管道，承接原 embedding 管道）

- `pipeline.py` — 文档解析与分块管道：MarkItDown 抽取 DOCX、Markdown、纯文本、PPTX、XLSX、XLS、HTML、CSV、JSON、XML、IPYNB、EPUB 和 ZIP，常见 UTF-8 源码/配置文件直接读取，pypdf 只抽取 PDF 已有文本层且不做 OCR；PNG、JPG、JPEG、WEBP 通过工作区启用的视觉模型提取文字，未配置时拒绝图片上传；随后执行清洗、平铺分块、Markdown 章节 Parent/Child 分块、精确字符偏移与 token 统计。
- `qa_import.py` — 问答对导入解析（CSV/XLSX/ZIP）：`QaRow` 数据类与 `extract_qa_rows` / `validate_qa_rows`，支持中英文表头别名（question/answer/source），含行数、长度等上限校验。

### mcp/

- `client.py` — 统一 MCP 客户端（`MultiTransportMcpClient`）：Streamable HTTP、legacy SSE、加密持久化的 stdio 配置连接；HTTP URL/重定向/代理环境防护、stdio 运行时校验、工具发现/调用、结果截断与超时。

### identity/

- `enterprise.py` — 企业身份 OAuth 实现：飞书/钉钉授权 URL 构造与授权码换取外部主体（`ExternalPrincipal`），错误统一为 `EnterpriseProviderError`。

### tools/（统一工具运行时）

- `runtime.py` — 统一工具运行时适配（自原 application/tool_adapters.py 迁入，系历史归属说明）：`BuiltinToolAdapter` / `PythonToolAdapter` / `McpToolAdapter` 三类实现满足 `tool_runtime` 端口契约，`build_tool_adapter(snapshot, settings, server)` 按工具 `kind` 分发；代码执行走沙箱（`app/infra/sandbox`），MCP 工具经 `app/ports/mcp.py` 委托调用，内置工具含产物直读/预检等逻辑。

## 模型注册相关文件的归属（非 adapter 迁出）

模型注册能力在拆分后并不全部留在适配层，业务侧归位如下：

- `RegisteredModel` ORM（model 表，含 provider/model_type/status 约束）→ `backend/app/domain/models/registered.py`
- 凭据规范化与校验（provider/status/model_type 校验与归一、凭据字段规范化与 `apply_model_credentials`、连接测试辅助、`PROVIDER_CATALOG` 查询）→ `backend/app/application/models/registry.py`；模型管理用例编排（审计记录、DTO 组装等）→ `backend/app/application/models/service.py`
- 数据访问仓储（列表/按 ID/按名称查、删除）→ `backend/app/infra/db/repositories/models/registry.py`，经 `app/ports/model_registry.py` 被业务层调用
- 检索评测指标（hit@k、recall@k、RR、NDCG 及延迟分位聚合）→ `backend/app/domain/knowledge/evaluation/metrics.py`

## 依赖方向

业务层（`application/`、`domain/`）→ `app/ports`（契约）→ `app/adapters`（实现）。实现层可组合 `app/infra` 提供的基础设施（db 会话、secrets、settings、sandbox、observability）与 `app/domain`、`app/entities` 中的值对象/ORM；`app/ports` 自身不依赖任何具体适配实现，保证能力可替换。
