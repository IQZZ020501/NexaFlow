CATALOG = {
    "provider": "model_tencent_cloud_provider",
    "name": "腾讯云",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_tencent_cloud_provider/icon.svg",
    "default_api_base": "https://tokenhub.tencentmaas.com/v1",
    "model_types": [
        "LLM",
        "VISION"
    ],
    "models": {
        "LLM": [
            {
                "name": "deepseek/deepseek-flash",
                "desc": "Tencent TokenHub DeepSeek Flash",
                "model_type": "LLM"
            },
            {
                "name": "deepseek/deepseek-v4-pro",
                "desc": "Tencent TokenHub DeepSeek V4 Pro",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "deepseek/deepseek-v4-flash-vision-exp",
                "desc": "Tencent TokenHub DeepSeek V4 Flash Vision",
                "model_type": "VISION"
            }
        ]
    }
}
