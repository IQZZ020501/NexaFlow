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
        "EMBEDDING"
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
        ]
    }
}
