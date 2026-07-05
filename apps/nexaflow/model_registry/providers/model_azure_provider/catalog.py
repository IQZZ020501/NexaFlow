CATALOG = {
    "provider": "model_azure_provider",
    "name": "Azure OpenAI",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_azure_provider/icon.svg",
    "default_api_base": "",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gpt-4o",
                "desc": "Azure OpenAI GPT-4o deployment",
                "model_type": "LLM"
            },
            {
                "name": "gpt-4o-mini",
                "desc": "Azure OpenAI GPT-4o mini deployment",
                "model_type": "LLM"
            },
            {
                "name": "gpt-4",
                "desc": "Azure OpenAI GPT-4 deployment",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "text-embedding-3-large",
                "desc": "Azure OpenAI embedding",
                "model_type": "EMBEDDING"
            },
            {
                "name": "text-embedding-3-small",
                "desc": "Azure OpenAI embedding",
                "model_type": "EMBEDDING"
            },
            {
                "name": "text-embedding-ada-002",
                "desc": "Azure OpenAI embedding",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
