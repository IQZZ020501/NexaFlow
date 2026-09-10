CATALOG = {
    "provider": "model_wenxin_provider",
    "name": "千帆大模型",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_wenxin_provider/icon.svg",
    "default_api_base": "https://qianfan.baidubce.com/v2",
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "ernie-5.1",
                "desc": "ERNIE 5.1",
                "model_type": "LLM"
            },
            {
                "name": "ernie-5.0",
                "desc": "ERNIE 5.0",
                "model_type": "LLM"
            },
            {
                "name": "ernie-4.5-turbo-128k",
                "desc": "ERNIE 4.5 Turbo 128K",
                "model_type": "LLM"
            },
            {
                "name": "deepseek-v4-pro",
                "desc": "DeepSeek V4 Pro on Qianfan",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "ernie-5.1",
                "desc": "ERNIE 5.1 multimodal",
                "model_type": "VISION"
            },
            {
                "name": "ernie-5.0",
                "desc": "ERNIE 5.0 multimodal",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "bge-large-zh",
                "desc": "Qianfan BGE embedding",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
