CATALOG = {
    "provider": "model_volcanic_engine_provider",
    "name": "火山引擎",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_volcanic_engine_provider/icon.svg",
    "default_api_base": "https://ark.cn-beijing.volces.com/api/v3",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "ep-xxxxxxxxxx-yyyy",
                "desc": "Volcengine Ark endpoint",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "ep-xxxxxxxxxx-yyyy",
                "desc": "Volcengine Ark embedding endpoint",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
