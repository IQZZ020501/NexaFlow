CATALOG = {
    "provider": "model_local_provider",
    "name": "本地模型",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_local_provider/icon.svg",
    "default_api_base": "",
    "api_key_required": False,
    "model_types": [
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "EMBEDDING": [
            {
                "name": "Qwen/Qwen3-Embedding-8B",
                "desc": "Local Qwen3 embedding",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "Qwen/Qwen3-Reranker-4B",
                "desc": "Local Qwen3 reranker",
                "model_type": "RERANKER"
            }
        ]
    }
}
