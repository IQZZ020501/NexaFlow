CATALOG = {
    "provider": "model_xinference_provider",
    "name": "Xorbits Inference",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_xinference_provider/icon.svg",
    "default_api_base": "http://localhost:9997/v1",
    "api_key_required": False,
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "qwen3.8-27b",
                "desc": "Xinference Qwen 3.8",
                "model_type": "LLM"
            },
            {
                "name": "deepseek-v4-flash",
                "desc": "Xinference DeepSeek V4 Flash",
                "model_type": "LLM"
            },
            {
                "name": "qwen3.5-9b",
                "desc": "Xinference Qwen 3.5",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "qwen3.8-27b",
                "desc": "Xinference Qwen 3.8 vision",
                "model_type": "VISION"
            },
            {
                "name": "qwen3.5-9b",
                "desc": "Xinference Qwen 3.5 vision",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "qwen3-embedding-8b",
                "desc": "Xinference Qwen3 embedding",
                "model_type": "EMBEDDING"
            },
            {
                "name": "bge-m3",
                "desc": "Xinference BGE M3",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "qwen3-reranker-4b",
                "desc": "Xinference Qwen3 reranker",
                "model_type": "RERANKER"
            }
        ]
    }
}
