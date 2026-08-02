CATALOG = {
    "provider": "model_ollama_provider",
    "name": "Ollama",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_ollama_provider/icon.svg",
    "default_api_base": "http://localhost:11434/v1",
    "model_types": [
        "LLM",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "deepseek-r1:7b",
                "desc": "Local Ollama model",
                "model_type": "LLM"
            },
            {
                "name": "llama3:8b",
                "desc": "Local Ollama model",
                "model_type": "LLM"
            },
            {
                "name": "qwen2.5:7b-instruct",
                "desc": "Local Ollama model",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "nomic-embed-text",
                "desc": "Local Ollama embedding model",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "linux6200/bge-reranker-v2-m3",
                "desc": "Local Ollama reranker model",
                "model_type": "RERANKER"
            }
        ]
    }
}
