CATALOG = {
    "provider": "model_wenxin_provider",
    "name": "千帆大模型",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_wenxin_provider/icon.svg",
    "default_api_base": "https://qianfan.baidubce.com/v2",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "ERNIE-Bot-4",
                "desc": "ERNIE Bot 4",
                "model_type": "LLM"
            },
            {
                "name": "ernie-4.5-turbo-32k",
                "desc": "ERNIE 4.5 Turbo",
                "model_type": "LLM"
            },
            {
                "name": "ernie-speed-8k",
                "desc": "ERNIE Speed",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "Embedding-V1",
                "desc": "Qianfan embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "bge-large-zh",
                "desc": "Qianfan BGE embedding",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
