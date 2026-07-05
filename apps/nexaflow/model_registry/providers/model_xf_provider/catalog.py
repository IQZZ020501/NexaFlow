CATALOG = {
    "provider": "model_xf_provider",
    "name": "讯飞星火",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_xf_provider/icon.svg",
    "default_api_base": "https://spark-api-open.xf-yun.com/v1",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "generalv3.5",
                "desc": "Spark general v3.5",
                "model_type": "LLM"
            },
            {
                "name": "generalv3",
                "desc": "Spark general v3",
                "model_type": "LLM"
            },
            {
                "name": "generalv2",
                "desc": "Spark general v2",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "embedding",
                "desc": "Spark embedding model",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
