CATALOG = {
    "provider": "model_deepseek_provider",
    "name": "DeepSeek",
    "provider_type": "deepseek",
    "icon": "/model-providers/model_deepseek_provider/icon.svg",
    "default_api_base": "https://api.deepseek.com",
    "model_types": [
        "LLM",
        "VISION"
    ],
    "models": {
        "LLM": [
            {
                "name": "deepseek-flash",
                "desc": "DeepSeek V4.1 Flash",
                "model_type": "LLM"
            },
            {
                "name": "deepseek-v4-pro",
                "desc": "DeepSeek V4 Pro",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "deepseek-flash",
                "desc": "DeepSeek V4.1 Flash vision",
                "model_type": "VISION"
            },
            {
                "name": "deepseek-v4-pro",
                "desc": "DeepSeek V4 Pro vision",
                "model_type": "VISION"
            }
        ]
    }
}
