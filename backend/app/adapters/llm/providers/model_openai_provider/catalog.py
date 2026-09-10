CATALOG = {
    "provider": "model_openai_provider",
    "name": "OpenAI",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_openai_provider/icon.svg",
    "default_api_base": "https://api.openai.com/v1",
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gpt-6-astra",
                "desc": "OpenAI GPT-6 Astra",
                "model_type": "LLM"
            },
            {
                "name": "gpt-5.6-sol",
                "desc": "OpenAI GPT-5.6 Sol",
                "model_type": "LLM"
            },
            {
                "name": "gpt-5.6-terra",
                "desc": "OpenAI GPT-5.6 Terra",
                "model_type": "LLM"
            },
            {
                "name": "gpt-5.6-luna",
                "desc": "OpenAI GPT-5.6 Luna",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "gpt-6-astra",
                "desc": "OpenAI GPT-6 Astra vision",
                "model_type": "VISION"
            },
            {
                "name": "gpt-5.6-sol",
                "desc": "OpenAI GPT-5.6 Sol vision",
                "model_type": "VISION"
            },
            {
                "name": "gpt-5.6-terra",
                "desc": "OpenAI GPT-5.6 Terra vision",
                "model_type": "VISION"
            },
            {
                "name": "gpt-5.6-luna",
                "desc": "OpenAI GPT-5.6 Luna vision",
                "model_type": "VISION"
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
