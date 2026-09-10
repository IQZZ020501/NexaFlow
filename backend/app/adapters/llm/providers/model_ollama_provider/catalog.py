CATALOG = {
    "provider": "model_ollama_provider",
    "name": "Ollama",
    "provider_type": "ollama",
    "icon": "/model-providers/model_ollama_provider/icon.svg",
    "default_api_base": "http://localhost:11434",
    "credential_fields": [
        {
            "field": "api_base",
            "label": "API URL",
            "input_type": "TextInput",
            "required": True,
            "default_value": "http://localhost:11434",
        },
    ],
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gemma4:12b",
                "desc": "Local Ollama model",
                "model_type": "LLM"
            },
            {
                "name": "qwen3.8:27b",
                "desc": "Local Ollama model",
                "model_type": "LLM"
            },
            {
                "name": "qwen3.5:9b",
                "desc": "Local Ollama model",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "gemma4:12b",
                "desc": "Local Ollama vision model",
                "model_type": "VISION"
            },
            {
                "name": "qwen3.8:27b",
                "desc": "Local Ollama vision model",
                "model_type": "VISION"
            },
            {
                "name": "qwen3.5:9b",
                "desc": "Local Ollama vision model",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "qwen3-embedding:8b",
                "desc": "Local Ollama Qwen3 embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "embeddinggemma",
                "desc": "Local Ollama EmbeddingGemma model",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
