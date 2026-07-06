CATALOG = {
    "provider": "model_aws_bedrock_provider",
    "name": "Amazon Bedrock",
    "provider_type": "openai_compatible",
    "icon": "/model-providers/model_aws_bedrock_provider/icon.svg",
    "default_api_base": "",
    "model_types": [
        "LLM",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "anthropic.claude-3-5-sonnet-20240620-v1:0",
                "desc": "Claude 3.5 Sonnet on Bedrock",
                "model_type": "LLM"
            },
            {
                "name": "amazon.titan-text-express-v1",
                "desc": "Amazon Titan Text Express",
                "model_type": "LLM"
            },
            {
                "name": "meta.llama3-70b-instruct-v1:0",
                "desc": "Meta Llama 3 70B",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "amazon.titan-embed-text-v1",
                "desc": "Amazon Titan Embed Text",
                "model_type": "EMBEDDING"
            }
        ],
        "RERANKER": [
            {
                "name": "cohere.rerank-v3-5:0",
                "desc": "Cohere Rerank on Bedrock",
                "model_type": "RERANKER"
            }
        ]
    }
}
