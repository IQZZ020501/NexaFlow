CATALOG = {
    "provider": "model_deepseek_provider",
    "name": "DeepSeek",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_deepseek_provider/icon.svg",
    "default_api_base": "https://api.deepseek.com",
    "model_types": [
        "LLM"
    ],
    "models": {
        "LLM": [
            {
                "name": "deepseek-chat",
                "desc": "DeepSeek chat model",
                "model_type": "LLM"
            },
            {
                "name": "deepseek-reasoner",
                "desc": "DeepSeek reasoning model",
                "model_type": "LLM"
            }
        ]
    }
}
