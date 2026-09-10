CATALOG = {
    "provider": "model_regolo_provider",
    "name": "Regolo",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_regolo_provider/icon.svg",
    "default_api_base": "https://api.regolo.ai/v1",
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
                "desc": "Regolo Qwen 3.8 27B",
                "model_type": "LLM"
            },
            {
                "name": "qwen3.5-122b",
                "desc": "Regolo Qwen 3.5 122B",
                "model_type": "LLM"
            },
            {
                "name": "mistral-small-4-119b",
                "desc": "Regolo Mistral Small 4",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "gemma4-31b",
                "desc": "Regolo Gemma 4 vision",
                "model_type": "VISION"
            },
            {
                "name": "qwen3.8-27b",
                "desc": "Regolo Qwen 3.8 vision",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "Qwen3-Embedding-8B",
                "desc": "Regolo Qwen3 embedding",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "Qwen3-Reranker-4B",
                "desc": "Regolo Qwen3 reranker",
                "model_type": "RERANKER"
            }
        ]
    }
}
