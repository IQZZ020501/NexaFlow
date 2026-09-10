CATALOG = {
    "provider": "model_volcanic_engine_provider",
    "name": "火山引擎",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_volcanic_engine_provider/icon.svg",
    "default_api_base": "https://ark.cn-beijing.volces.com/api/v3",
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "doubao-seed-2.0-pro",
                "desc": "Doubao Seed 2.0 Pro",
                "model_type": "LLM"
            },
            {
                "name": "doubao-seed-2.0-lite",
                "desc": "Doubao Seed 2.0 Lite",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "doubao-seed-2.0-pro",
                "desc": "Doubao Seed 2.0 Pro vision",
                "model_type": "VISION"
            },
            {
                "name": "doubao-seed-2.0-lite",
                "desc": "Doubao Seed 2.0 Lite vision",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "doubao-embedding-text-240515",
                "desc": "Doubao text embedding",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
