# CAPABILITIES 模块（backend/app/capabilities）

## 职责

技术能力层：与业务领域正交的模型/检索/工具/解析能力。`llm/` 为模型注册核心（服务 + 运行时 + 供应商静态目录）；`rag/` 为向量检索；`mcp/` 为 MCP 客户端；`embedding/` 为文档解析管道。

## 文件清单

### llm/（模型注册与运行时）

- `backend/app/capabilities/llm/registry.py` — 模型注册中心服务层：模型 CRUD、凭据加解密与校验、连接测试、状态管理、审计记录
- `backend/app/capabilities/llm/registry_repository.py` — RegisteredModel 数据访问层（列表/按 ID/按名称查、删除）
- `backend/app/capabilities/llm/runtime.py` — 模型运行时：按注册配置构建各厂商 LLM/Embedding/Reranker 客户端、调用与连接测试，统一异常映射
- `backend/app/capabilities/llm/credentials.py` — 模型凭据加密打包/解密解析及旧格式（api_base）向新配置的兼容转换
- `backend/app/capabilities/llm/models.py` — RegisteredModel ORM 模型（model 表，含 provider/model_type/status 约束）
- `backend/app/capabilities/llm/providers/*/catalog.py` — 22 个模型厂商静态目录（aliyun_bai_lian、anthropic、aws_bedrock、azure、custom、deepseek、docker_ai、gemini、kimi、local、ollama、openai、regolo、siliconflow、tencent、tencent_cloud、vllm、volcanic_engine、wenxin、xf、xinference、zhipu）：名称、图标、默认 API 地址、模型列表
- `backend/app/capabilities/llm/providers/__init__.py` — 汇总全部 provider 目录的 CATALOG 为 `PROVIDER_CATALOG`

### rag/（向量检索）

- `backend/app/capabilities/rag/vector_store.py` — Qdrant 向量库封装：collection 管理（并发创建竞态处理）、向量 upsert/查询/删除、结构化日志（`source=external` 分类）
- `backend/app/capabilities/rag/retrieval.py` — 知识库检索：Child 向量召回 + 关键词命中 RRF、可选 Child 重排、Parent 去重与预算内上下文扩展；平铺文档保持原聚合行为

### mcp/（MCP 客户端）

- `backend/app/capabilities/mcp/client.py` — MCP 客户端：URL 规范化与内网地址防护、工具发现/调用、结果截断与超时

### embedding/（文档解析管道）

- `backend/app/capabilities/embedding/pipeline.py` — 文档解析管道：MarkItDown 文本抽取、清洗、平铺分块、Markdown 章节 Parent/Child 分块、精确字符偏移与 token 统计
