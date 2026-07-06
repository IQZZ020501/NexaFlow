CATALOG = {
    "provider": "model_siliconflow_provider",
    "name": "SILICONFLOW",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_siliconflow_provider/icon.svg",
    "default_api_base": "https://api.siliconflow.cn/v1",
    "model_types": [
        "LLM",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "deepseek-ai/DeepSeek-R1-Distill-Llama-8B",
                "desc": "DeepSeek R1 Distill on SiliconFlow",
                "model_type": "LLM"
            },
            {
                "name": "Qwen/Qwen2.5-7B-Instruct",
                "desc": "Qwen2.5 on SiliconFlow",
                "model_type": "LLM"
            },
            {
                "name": "THUDM/glm-4-9b-chat",
                "desc": "GLM 4 on SiliconFlow",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "BAAI/bge-m3",
                "desc": "BGE-M3 embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "netease-youdao/bce-embedding-base_v1",
                "desc": "BCE embedding model",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "BAAI/bge-reranker-v2-m3",
                "desc": "BGE reranker model",
                "model_type": "RERANKER"
            },
            {
                "name": "netease-youdao/bce-reranker-base_v1",
                "desc": "BCE reranker model",
                "model_type": "RERANKER"
            }
        ]
    }
}
