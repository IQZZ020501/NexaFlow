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
        "LLM",
        "VISION"
    ],
    "models": {
        "LLM": [
            {
                "name": "claude-fable-5-1",
                "desc": "Claude Fable 5.1",
                "model_type": "LLM"
            },
            {
                "name": "claude-opus-5",
                "desc": "Claude Opus 5",
                "model_type": "LLM"
            },
            {
                "name": "claude-sonnet-5",
                "desc": "Claude Sonnet 5",
                "model_type": "LLM"
            },
            {
                "name": "claude-haiku-4-5-20251001",
                "desc": "Claude Haiku 4.5",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "claude-fable-5-1",
                "desc": "Claude Fable 5.1 vision",
                "model_type": "VISION"
            },
            {
                "name": "claude-opus-5",
                "desc": "Claude Opus 5 vision",
                "model_type": "VISION"
            },
            {
                "name": "claude-sonnet-5",
                "desc": "Claude Sonnet 5 vision",
                "model_type": "VISION"
            }
        ]
    }
}
