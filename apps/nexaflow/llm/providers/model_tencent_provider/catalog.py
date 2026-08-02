CATALOG = {
    "provider": "model_tencent_provider",
    "name": "腾讯混元",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_tencent_provider/icon.svg",
    "default_api_base": "https://api.hunyuan.cloud.tencent.com/v1",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "hunyuan-pro",
                "desc": "Hunyuan Pro",
                "model_type": "LLM"
            },
            {
                "name": "hunyuan-standard",
                "desc": "Hunyuan Standard",
                "model_type": "LLM"
            },
            {
                "name": "hunyuan-lite",
                "desc": "Hunyuan Lite",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "hunyuan-embedding",
                "desc": "Hunyuan embedding model",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
