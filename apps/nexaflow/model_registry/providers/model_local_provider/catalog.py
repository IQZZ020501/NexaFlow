CATALOG = {
    "provider": "model_local_provider",
    "name": "本地模型",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_local_provider/icon.svg",
    "default_api_base": "",
    "model_types": [
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "EMBEDDING": [
            {
                "name": "shibing624/text2vec-base-chinese",
                "desc": "Local text2vec embedding",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "BAAI/bge-reranker-v2-m3",
                "desc": "Local BGE reranker",
                "model_type": "RERANKER"
            }
        ]
    }
}
