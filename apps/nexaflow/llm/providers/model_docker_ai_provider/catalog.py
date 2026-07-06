CATALOG = {
    "provider": "model_docker_ai_provider",
    "name": "Docker AI",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_docker_ai_provider/icon.svg",
    "default_api_base": "http://localhost:12434/engines/v1",
    "model_types": [
        "LLM",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "ai/qwen3-vl:8B",
                "desc": "Docker AI Qwen3 VL",
                "model_type": "LLM"
            },
            {
                "name": "gpt-3.5-turbo",
                "desc": "Docker AI compatible chat model",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "ai/qwen3-embedding-vllm",
                "desc": "Docker AI embedding model",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "ai/qwen3-reranker:0.6B",
                "desc": "Docker AI reranker model",
                "model_type": "RERANKER"
            }
        ]
    }
}
