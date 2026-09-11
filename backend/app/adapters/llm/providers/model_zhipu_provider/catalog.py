CATALOG = {
    "provider": "model_zhipu_provider",
    "name": "智谱 AI",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_zhipu_provider/icon.svg",
    "default_api_base": "https://open.bigmodel.cn/api/paas/v4",
    "model_types": [
        "LLM",
        "VISION"
    ],
    "models": {
        "LLM": [
            {
                "name": "glm-5.3",
                "desc": "GLM 5.3",
                "model_type": "LLM"
            },
            {
                "name": "glm-5.3-flash",
                "desc": "GLM 5.3 Flash",
                "model_type": "LLM"
            },
            {
                "name": "glm-5.2",
                "desc": "GLM 5.2",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "glm-5.3-flash",
                "desc": "GLM 5.3 Flash vision",
                "model_type": "VISION"
            }
        ]
    }
}
