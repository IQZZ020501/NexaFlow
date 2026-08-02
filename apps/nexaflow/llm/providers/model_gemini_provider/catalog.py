CATALOG = {
    "provider": "model_gemini_provider",
    "name": "Gemini",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_gemini_provider/icon.svg",
    "default_api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gemini-1.5-flash",
                "desc": "Gemini 1.5 Flash",
                "model_type": "LLM"
            },
            {
                "name": "gemini-1.5-pro",
                "desc": "Gemini 1.5 Pro",
                "model_type": "LLM"
            },
            {
                "name": "gemini-1.0-pro",
                "desc": "Gemini 1.0 Pro",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "models/text-embedding-004",
                "desc": "Gemini embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "models/embedding-001",
                "desc": "Gemini embedding model",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
