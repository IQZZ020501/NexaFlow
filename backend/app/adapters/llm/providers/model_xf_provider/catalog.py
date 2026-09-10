CATALOG = {
    "provider": "model_xf_provider",
    "name": "讯飞星火",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_xf_provider/icon.svg",
    "default_api_base": "https://spark-api-open.xf-yun.com/v1",
    "model_types": [
        "LLM"
    ],
    "models": {
        "LLM": [
            {
                "name": "4.0Ultra",
                "desc": "Spark 4.0 Ultra with X1.5 fast thinking",
                "model_type": "LLM"
            },
            {
                "name": "pro-128k",
                "desc": "Spark Pro 128K",
                "model_type": "LLM"
            },
            {
                "name": "lite",
                "desc": "Spark Lite",
                "model_type": "LLM"
            }
        ]
    }
}
