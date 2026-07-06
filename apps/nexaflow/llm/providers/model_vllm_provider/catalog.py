CATALOG = {
    "provider": "model_vllm_provider",
    "name": "vLLM",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_vllm_provider/icon.svg",
    "default_api_base": "http://localhost:8000/v1",
    "model_types": [
        "LLM",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "facebook/opt-125m",
                "desc": "Example vLLM model",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "BAAI/bge-m3",
                "desc": "Example embedding model",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "BAAI/bge-reranker-v2-m3",
                "desc": "Example reranker model",
                "model_type": "RERANKER"
            }
        ]
    }
}
