CATALOG = {
    "provider": "model_siliconflow_provider",
    "name": "SILICONFLOW",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_siliconflow_provider/icon.svg",
    "default_api_base": "https://api.siliconflow.cn/v1",
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "deepseek-ai/DeepSeek-V4-Flash",
                "desc": "DeepSeek V4 Flash on SiliconFlow",
                "model_type": "LLM"
            },
            {
                "name": "Pro/deepseek-ai/DeepSeek-V4",
                "desc": "DeepSeek V4 on SiliconFlow",
                "model_type": "LLM"
            },
            {
                "name": "Pro/zai-org/GLM-5.2",
                "desc": "GLM 5.2 on SiliconFlow",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "deepseek-ai/DeepSeek-V4-Flash",
                "desc": "DeepSeek V4 Flash vision on SiliconFlow",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "Qwen/Qwen3-Embedding-8B",
                "desc": "Qwen3 8B embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "Qwen/Qwen3-Embedding-4B",
                "desc": "Qwen3 4B embedding model",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "Qwen/Qwen3-Reranker-8B",
                "desc": "Qwen3 8B reranker model",
                "model_type": "RERANKER"
            },
            {
                "name": "Qwen/Qwen3-Reranker-4B",
                "desc": "Qwen3 4B reranker model",
                "model_type": "RERANKER"
            }
        ]
    }
}
