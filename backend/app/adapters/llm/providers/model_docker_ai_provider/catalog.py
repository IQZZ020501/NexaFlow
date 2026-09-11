CATALOG = {
    "provider": "model_docker_ai_provider",
    "name": "Docker AI",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_docker_ai_provider/icon.svg",
    "default_api_base": "http://localhost:12434/engines/v1",
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
                "name": "ai/qwen3-vl:8B",
                "desc": "Docker AI Qwen3 VL",
                "model_type": "LLM"
            },
            {
                "name": "ai/qwen3.5:9B",
                "desc": "Docker AI Qwen 3.5",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "ai/qwen3-vl:8B",
                "desc": "Docker AI Qwen3 VL",
                "model_type": "VISION"
            },
            {
                "name": "ai/qwen3.5:9B",
                "desc": "Docker AI Qwen 3.5 vision",
                "model_type": "VISION"
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
