CATALOG = {
    "provider": "model_vllm_provider",
    "name": "vLLM",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_vllm_provider/icon.svg",
    "default_api_base": "http://localhost:8000/v1",
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
                "name": "Qwen/Qwen3.8-27B",
                "desc": "Example current vLLM chat model",
                "model_type": "LLM"
            },
            {
                "name": "deepseek-ai/DeepSeek-V4-Flash",
                "desc": "Example current vLLM reasoning model",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "Qwen/Qwen3.8-27B",
                "desc": "Example current vLLM vision model",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "Qwen/Qwen3-Embedding-8B",
                "desc": "Example current vLLM embedding model",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "Qwen/Qwen3-Reranker-4B",
                "desc": "Example current vLLM reranker model",
                "model_type": "RERANKER"
            }
        ]
    }
}
