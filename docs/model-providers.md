# 模型供应商接入

更新时间：2026-09-10。

NexaFlow 当前提供 22 个供应商目录项，但不会为每家供应商安装一套重复的客户端。运行时保留两类稳定契约：有成熟原生客户端的供应商使用其官方 Python SDK；明确提供 OpenAI 兼容接口的供应商复用官方 `openai` Python SDK。这样既使用厂商支持的协议，又避免把只用于控制台、训练或部署的 SDK 引入在线推理进程。

供应商接口返回的 `integration` 字段记录实际适配器、运行时 SDK、厂商专用 SDK（如果存在）、协议、模型目录类型、官方文档和核验日期。模型目录类型含义如下：

- `static_recommendations`：仓库维护一组经官方文档核对的当前推荐模型；仍可手动输入其他有效模型 ID。
- `account_or_region`：可用模型取决于账号、区域或服务开通情况，静态列表只提供当前代表项。
- `deployment_defined`：注册时填写的是用户自己的部署名，而不是平台全局模型 ID。
- `runtime_discovered`：模型由本地或远端运行时加载，静态列表只是当前示例。
- `user_defined`：完全由用户提供兼容端点和模型名。

## 接入矩阵

| 供应商 | NexaFlow 实际调用 | 厂商专用 Python SDK | 模型目录 | 官方资料 |
| --- | --- | --- | --- | --- |
| OpenAI | `langchain-openai` + `openai`，Chat Completions / Embeddings | `openai` | 静态推荐 | [SDK](https://developers.openai.com/api/docs/libraries) / [模型](https://developers.openai.com/api/docs/models) |
| Anthropic | `langchain-anthropic` + `anthropic`，Messages API | `anthropic` | 静态推荐 | [SDK](https://platform.claude.com/docs/en/api/client-sdks) / [模型](https://platform.claude.com/docs/en/models/overview) |
| Amazon Bedrock | `langchain-aws` + `boto3`，Bedrock Converse / Embeddings / Rerank | `boto3` | 账号或区域相关 | [Python](https://docs.aws.amazon.com/bedrock/latest/userguide/getting-started-api-ex-python.html) / [模型卡](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html) |
| Azure OpenAI | `langchain-openai` + `openai`，Azure endpoint + deployment | `openai` | 部署名 | [接入](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/switching-endpoints) / [模型](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure?pivots=azure-openai) |
| Gemini | `langchain-google-genai` + `google-genai` | `google-genai` | 静态推荐 | [SDK](https://ai.google.dev/gemini-api/docs/libraries) / [模型](https://ai.google.dev/gemini-api/docs/models) |
| Ollama | `langchain-ollama` + `ollama` | `ollama` | 运行时动态 | [API](https://docs.ollama.com/api/introduction) / [模型库](https://ollama.com/library) |
| DeepSeek | `langchain-deepseek`，底层使用 OpenAI 兼容协议 | 无需专用 SDK | 静态推荐 | [API 与模型](https://api-docs.deepseek.com/quick_start/pricing/) |
| 阿里云百炼 | `openai`，DashScope OpenAI 兼容端点 | `dashscope`（本项目推理未使用） | 静态推荐 | [调用](https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api) / [模型](https://help.aliyun.com/zh/model-studio/models) |
| Kimi | `openai`，OpenAI Chat Completions 兼容端点 | 无需专用 SDK | 静态推荐 | [调用](https://platform.kimi.com/docs/api/chat) / [模型](https://platform.kimi.com/docs/guide/models-overview) |
| 智谱 AI | `openai`，OpenAI Chat Completions 兼容端点 | `zhipuai`（本项目推理未使用） | 静态推荐 | [兼容接口](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction) / [模型](https://docs.bigmodel.cn/cn/guide/models/text/glm-5) |
| SiliconFlow | `openai`，Chat Completions / Embeddings；Rerank 使用兼容 HTTP | 无需专用 SDK | 静态推荐 | [Chat API](https://docs.siliconflow.cn/docs/api/chat-completions-post) / [模型](https://cloud.siliconflow.cn/models) |
| 腾讯云 TokenHub | `openai`，Base URL 为 `https://tokenhub.tencentmaas.com/v1` | 无需专用 SDK | 静态推荐 | [调用](https://cloud.tencent.com/document/product/1823/130079) / [模型](https://cloud.tencent.com/document/product/1823/130051) |
| 腾讯混元 | `openai`，混元 OpenAI 兼容端点 | `tencentcloud-sdk-python-hunyuan`（本项目推理未使用） | 静态推荐 | [调用](https://cloud.tencent.com/document/product/1729/111007) / [模型](https://cloud.tencent.com/document/product/1729/104753) |
| 火山方舟 | `openai`，可填写 Model ID 或账号中的 Endpoint ID | `volcengine-python-sdk`（本项目推理未使用） | 账号或区域相关 | [兼容接口](https://www.volcengine.com/docs/82379/1330626) / [模型](https://www.volcengine.com/docs/82379/1330310) |
| 百度千帆 | `openai`，千帆 OpenAI 兼容端点 | `qianfan`（本项目推理未使用） | 静态推荐 | [兼容接口](https://ai.baidu.com/ai-doc/WENXINWORKSHOP/1m9ra0mle) / [模型](https://cloud.baidu.com/doc/qianfan/s/wmh4sv6ya) |
| 讯飞星火 | `openai`，官方 OpenAI 兼容 Chat Completions 端点 | 官方提供示例与平台 SDK，无必需推理包 | 静态推荐 | [HTTP / OpenAI SDK](https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html) |
| Regolo | `openai`，OpenAI Chat Completions 兼容端点 | `regolo`（可选，本项目推理未使用） | 运行时动态 | [接入](https://docs.regolo.ai/getting-started/first-api-call/) / [模型目录](https://docs.regolo.ai/models/catalog/) |
| Docker Model Runner | `openai`，本机 OpenAI 兼容端点 | 无需专用 SDK | 运行时动态 | [API](https://docs.docker.com/ai/model-runner/api-reference/) / [模型](https://hub.docker.com/u/ai) |
| vLLM | `openai`，vLLM OpenAI-compatible server | `vllm` 是服务端运行时，不是必需客户端 | 运行时动态 | [OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/) |
| Xorbits Inference | `openai`，Xinference OpenAI 兼容端点 | `xinference-client`（本项目推理未使用） | 运行时动态 | [客户端与 API](https://inference.readthedocs.io/en/latest/user_guide/client_api.html) |
| 本地模型 | `openai`，用户提供兼容端点 | 取决于本地服务 | 运行时动态 | [OpenAI 请求格式](https://platform.openai.com/docs/api-reference/chat) |
| 自定义 OpenAI 兼容 | `openai`，用户提供端点、密钥和模型名 | 取决于供应商 | 用户定义 | [OpenAI 请求格式](https://platform.openai.com/docs/api-reference/chat) |

## 请求路径

- LLM 与 Vision：原生供应商分别走 Anthropic Messages、Bedrock Converse、Google GenAI 或 Ollama；其他供应商走 `{api_base}/chat/completions`。
- Embedding：原生供应商走各自 SDK，其余兼容供应商走 `{api_base}/embeddings`。
- Reranker：Bedrock 使用官方 Rerank 客户端；OpenAI 兼容供应商走 `{api_base}/rerank`。
- 注册模型时可以覆盖目录中的默认 API URL，并可直接输入静态列表之外的有效模型 ID。AWS 可用模型受区域与账号授权影响，Azure 和火山方舟还可能要求使用自己的部署名或 Endpoint ID。

仓库只直接声明运行时确实导入的 SDK：`openai`、`anthropic`、`boto3` / `botocore`、`google-genai` 和 `ollama`。矩阵中其他厂商 SDK 只在需要其非兼容能力时才应引入，不能仅为“每家一个包”增加在线依赖。
