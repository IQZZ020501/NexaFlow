CATALOG = {
    "provider": "model_openai_provider",
    "name": "OpenAI",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_openai_provider/icon.svg",
    "default_api_base": "https://api.openai.com/v1",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gpt-4o",
                "desc": "OpenAI GPT-4o",
                "model_type": "LLM"
            },
            {
                "name": "gpt-4o-mini",
                "desc": "OpenAI GPT-4o mini",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "text-embedding-3-small",
                "desc": "OpenAI embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "text-embedding-3-large",
                "desc": "OpenAI large embedding model",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
