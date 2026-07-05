CATALOG = {
    "provider": "model_anthropic_provider",
    "name": "Anthropic",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_anthropic_provider/icon.svg",
    "default_api_base": "https://api.anthropic.com/v1",
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
