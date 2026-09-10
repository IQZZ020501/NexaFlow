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
        "VISION",
        "EMBEDDING",
        "RERANKER"
    ],
    "models": {
        "LLM": [
            {
                "name": "amazon.nova-2-lite-v1:0",
                "desc": "Amazon Nova 2 Lite",
                "model_type": "LLM"
            },
            {
                "name": "amazon.nova-premier-v1:0",
                "desc": "Amazon Nova Premier",
                "model_type": "LLM"
            },
            {
                "name": "amazon.nova-pro-v1:0",
                "desc": "Amazon Nova Pro",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "amazon.nova-2-lite-v1:0",
                "desc": "Amazon Nova 2 Lite vision",
                "model_type": "VISION"
            },
            {
                "name": "amazon.nova-premier-v1:0",
                "desc": "Amazon Nova Premier vision",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "amazon.titan-embed-text-v2:0",
                "desc": "Amazon Titan Text Embeddings V2",
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
