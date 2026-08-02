CATALOG = {
    "provider": "model_kimi_provider",
    "name": "Kimi",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_kimi_provider/icon.svg",
    "default_api_base": "https://api.moonshot.cn/v1",
    "model_types": [
        "LLM"
    ],
    "models": {
        "LLM": [
            {
                "name": "moonshot-v1-8k",
                "desc": "Moonshot 8K",
                "model_type": "LLM"
            },
            {
                "name": "moonshot-v1-32k",
                "desc": "Moonshot 32K",
                "model_type": "LLM"
            },
            {
                "name": "moonshot-v1-128k",
                "desc": "Moonshot 128K",
                "model_type": "LLM"
            }
        ]
    }
}
