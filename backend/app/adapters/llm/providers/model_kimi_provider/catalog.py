CATALOG = {
    "provider": "model_kimi_provider",
    "name": "Kimi",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_kimi_provider/icon.svg",
    "default_api_base": "https://api.moonshot.cn/v1",
    "model_types": [
        "LLM",
        "VISION"
    ],
    "models": {
        "LLM": [
            {
                "name": "kimi-k3",
                "desc": "Kimi K3",
                "model_type": "LLM"
            },
            {
                "name": "kimi-k2.7-code",
                "desc": "Kimi K2.7 Code",
                "model_type": "LLM"
            },
            {
                "name": "kimi-k2.6",
                "desc": "Kimi K2.6",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "kimi-k3",
                "desc": "Kimi K3 vision",
                "model_type": "VISION"
            },
            {
                "name": "kimi-k2.7-code",
                "desc": "Kimi K2.7 Code vision",
                "model_type": "VISION"
            },
            {
                "name": "kimi-k2.6",
                "desc": "Kimi K2.6 vision",
                "model_type": "VISION"
            }
        ]
    }
}
