CATALOG = {
    "provider": "model_tencent_provider",
    "name": "腾讯混元",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_tencent_provider/icon.svg",
    "default_api_base": "https://api.hunyuan.cloud.tencent.com/v1",
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "hunyuan-a13b",
                "desc": "Hunyuan A13B",
                "model_type": "LLM"
            },
            {
                "name": "hunyuan-translation",
                "desc": "Hunyuan Translation",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "hunyuan-vision-1.5-instruct",
                "desc": "Hunyuan Vision 1.5 Instruct",
                "model_type": "VISION"
            },
            {
                "name": "hunyuan-t1-vision-20250916",
                "desc": "Hunyuan T1 Vision",
                "model_type": "VISION"
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
