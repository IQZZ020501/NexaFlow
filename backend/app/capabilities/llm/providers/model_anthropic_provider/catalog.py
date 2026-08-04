CATALOG = {
    "provider": "model_anthropic_provider",
    "name": "Anthropic",
    "provider_type": "anthropic",
    "icon": "/model-providers/model_anthropic_provider/icon.svg",
    "default_api_base": "https://api.anthropic.com",
    "credential_fields": [
        {
            "field": "api_base",
            "label": "API URL",
            "input_type": "TextInput",
            "required": False,
            "default_value": "https://api.anthropic.com",
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
        "LLM"
    ],
    "models": {
        "LLM": [
            {
                "name": "claude-3-5-sonnet-20241022",
                "desc": "Claude 3.5 Sonnet",
                "model_type": "LLM"
            },
            {
                "name": "claude-3-5-haiku-20241022",
                "desc": "Claude 3.5 Haiku",
                "model_type": "LLM"
            },
            {
                "name": "claude-3-opus-20240229",
                "desc": "Claude 3 Opus",
                "model_type": "LLM"
            }
        ]
    }
}
