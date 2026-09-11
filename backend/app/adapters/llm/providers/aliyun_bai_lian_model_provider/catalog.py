CATALOG = {
    "provider": "aliyun_bai_lian_model_provider",
    "name": "阿里云百炼",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/aliyun_bai_lian_model_provider/icon.svg",
    "default_api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "qwen3.8-max",
                "desc": "Qwen 3.8 Max",
                "model_type": "LLM"
            },
            {
                "name": "qwen3.7-plus",
                "desc": "Qwen 3.7 Plus",
                "model_type": "LLM"
            },
            {
                "name": "qwen3.8-flash",
                "desc": "Qwen 3.8 Flash",
                "model_type": "LLM"
            },
        ],
        "VISION": [
            {
                "name": "qwen3.8-max",
                "desc": "Qwen 3.8 Max multimodal",
                "model_type": "VISION"
            },
            {
                "name": "qwen3.7-plus",
                "desc": "Qwen 3.7 Plus multimodal",
                "model_type": "VISION"
            },
            {
                "name": "qwen3.5-omni-plus",
                "desc": "Qwen 3.5 Omni Plus",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "qwen3.7-text-embedding",
                "desc": "Qwen 3.7 text embedding",
                "model_type": "EMBEDDING"
            },
            {
                "name": "text-embedding-v4",
                "desc": "Qwen text embedding v4",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "qwen3-rerank",
                "desc": "Qwen 3 reranker",
                "model_type": "RERANKER"
            }
        ]
    }
}
