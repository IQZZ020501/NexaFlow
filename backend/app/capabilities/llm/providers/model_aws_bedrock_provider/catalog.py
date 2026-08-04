CATALOG = {
    "provider": "model_aws_bedrock_provider",
    "name": "Amazon Bedrock",
    "provider_type": "bedrock",
    "icon": "/model-providers/model_aws_bedrock_provider/icon.svg",
    "default_api_base": "",
    "credential_fields": [
        {
            "field": "region_name",
            "label": "AWS Region",
            "input_type": "TextInput",
            "required": True,
            "default_value": "us-east-1",
        },
        {
            "field": "endpoint_url",
            "label": "Endpoint URL",
            "input_type": "TextInput",
            "required": False,
            "default_value": "",
        },
        {
            "field": "aws_access_key_id",
            "label": "AWS Access Key ID",
            "input_type": "PasswordInput",
            "required": False,
            "default_value": "",
        },
        {
            "field": "aws_secret_access_key",
            "label": "AWS Secret Access Key",
            "input_type": "PasswordInput",
            "required": False,
            "default_value": "",
        },
        {
            "field": "aws_session_token",
            "label": "AWS Session Token",
            "input_type": "PasswordInput",
            "required": False,
            "default_value": "",
        },
    ],
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
