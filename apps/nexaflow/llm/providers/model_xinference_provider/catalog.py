CATALOG = {
    "provider": "model_xinference_provider",
    "name": "Xorbits Inference",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_xinference_provider/icon.svg",
    "default_api_base": "http://localhost:9997/v1",
    "model_types": [
        "LLM",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "qwen2.5-7b-instruct",
                "desc": "Xinference Qwen2.5",
                "model_type": "LLM"
            },
            {
                "name": "deepseek-chat",
                "desc": "Xinference DeepSeek",
                "model_type": "LLM"
            },
            {
                "name": "phi3",
                "desc": "Xinference Phi3",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "bge-m3",
                "desc": "Xinference BGE M3",
                "model_type": "EMBEDDING"
            },
            {
                "name": "bce-embedding-base_v1",
                "desc": "Xinference BCE embedding",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "bce-reranker-base_v1",
                "desc": "Xinference BCE reranker",
                "model_type": "RERANKER"
            }
        ]
    }
}
