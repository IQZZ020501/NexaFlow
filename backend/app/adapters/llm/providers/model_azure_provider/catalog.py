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
        "VISION",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gpt-6-astra",
                "desc": "Azure OpenAI GPT-6 Astra deployment",
                "model_type": "LLM"
            },
            {
                "name": "gpt-5.6-sol",
                "desc": "Azure OpenAI GPT-5.6 Sol deployment",
                "model_type": "LLM"
            },
            {
                "name": "gpt-5.6-terra",
                "desc": "Azure OpenAI GPT-5.6 Terra deployment",
                "model_type": "LLM"
            },
            {
                "name": "gpt-5.6-luna",
                "desc": "Azure OpenAI GPT-5.6 Luna deployment",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "gpt-6-astra",
                "desc": "Azure OpenAI GPT-6 Astra vision deployment",
                "model_type": "VISION"
            },
            {
                "name": "gpt-5.6-sol",
                "desc": "Azure OpenAI GPT-5.6 Sol vision deployment",
                "model_type": "VISION"
            },
            {
                "name": "gpt-5.6-terra",
                "desc": "Azure OpenAI GPT-5.6 Terra vision deployment",
                "model_type": "VISION"
            },
            {
                "name": "gpt-5.6-luna",
                "desc": "Azure OpenAI GPT-5.6 Luna vision deployment",
                "model_type": "VISION"
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
