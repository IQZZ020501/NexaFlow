CATALOG = {
    "provider": "model_azure_provider",
    "name": "Azure OpenAI",
    "provider_type": "azure_openai",
    "icon": "/model-providers/model_azure_provider/icon.svg",
    "default_api_base": "",
    "credential_fields": [
        {
            "field": "azure_endpoint",
            "label": "API URL",
            "input_type": "TextInput",
            "required": True,
            "default_value": "",
        },
        {
            "field": "api_version",
            "label": "API Version",
            "input_type": "TextInput",
            "required": True,
            "default_value": "2024-10-21",
        },
        {
            "field": "api_key",
            "label": "API Key",
            "input_type": "PasswordInput",
            "required": True,
            "default_value": "",
        },
    ],
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
