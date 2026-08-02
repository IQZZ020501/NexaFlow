CATALOG = {
    "provider": "model_regolo_provider",
    "name": "Regolo",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_regolo_provider/icon.svg",
    "default_api_base": "https://api.regolo.ai/v1",
    "model_types": [
        "LLM",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "Phi-4",
                "desc": "Regolo Phi-4",
                "model_type": "LLM"
            },
            {
                "name": "DeepSeek-R1-Distill-Qwen-32B",
                "desc": "Regolo DeepSeek R1 Distill",
                "model_type": "LLM"
            },
            {
                "name": "Llama-3.3-70B-Instruct",
                "desc": "Regolo Llama 3.3",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "gte-Qwen2",
                "desc": "Regolo embedding model",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
