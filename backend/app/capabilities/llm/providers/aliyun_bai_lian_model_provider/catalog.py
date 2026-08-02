CATALOG = {
    "provider": "aliyun_bai_lian_model_provider",
    "name": "阿里云百炼",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/aliyun_bai_lian_model_provider/icon.svg",
    "default_api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model_types": [
        "LLM",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "qwen-plus",
                "desc": "Qwen Plus",
                "model_type": "LLM"
            },
            {
                "name": "qwen-turbo",
                "desc": "Qwen Turbo",
                "model_type": "LLM"
            },
            {
                "name": "qwen-max",
                "desc": "Qwen Max",
                "model_type": "LLM"
            },
            {
                "name": "qwen3-32b",
                "desc": "Qwen3 32B",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "text-embedding-v4",
                "desc": "Qwen embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "text-embedding-v1",
                "desc": "Aliyun text embedding",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "gte-rerank-v2",
                "desc": "GTE reranker",
                "model_type": "RERANKER"
            }
        ]
    }
}
