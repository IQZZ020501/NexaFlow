CATALOG = {
    "provider": "model_gemini_provider",
    "name": "Gemini",
    "provider_type": "google_genai",
    "icon": "/model-providers/model_gemini_provider/icon.svg",
    "default_api_base": "",
    "credential_fields": [
        {
            "field": "api_base",
            "label": "API URL",
            "input_type": "TextInput",
            "required": False,
            "default_value": "",
        },
        {
            "field": "api_version",
            "label": "API Version",
            "input_type": "TextInput",
            "required": False,
            "default_value": "",
        },
        {
            "field": "api_key",
            "label": "API Key",
            "input_type": "PasswordInput",
            "required": True,
            "default_value": "",
        },
    ],
    "model_types": [
        "LLM",
        "VISION",
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gemini-3.7-flash",
                "desc": "Gemini 3.7 Flash",
                "model_type": "LLM"
            },
            {
                "name": "gemini-3.6-flash",
                "desc": "Gemini 3.6 Flash",
                "model_type": "LLM"
            },
            {
                "name": "gemini-3.5-flash-lite",
                "desc": "Gemini 3.5 Flash Lite",
                "model_type": "LLM"
            }
        ],
        "VISION": [
            {
                "name": "gemini-3.7-flash",
                "desc": "Gemini 3.7 Flash vision",
                "model_type": "VISION"
            },
            {
                "name": "gemini-3.6-flash",
                "desc": "Gemini 3.6 Flash vision",
                "model_type": "VISION"
            },
            {
                "name": "gemini-3.5-flash-lite",
                "desc": "Gemini 3.5 Flash Lite vision",
                "model_type": "VISION"
            }
        ],
        "EMBEDDING": [
            {
                "name": "models/gemini-embedding-001",
                "desc": "Gemini Embedding",
                "model_type": "EMBEDDING"
            },
            {
                "name": "models/gemini-embedding-2-preview",
                "desc": "Gemini Embedding 2 preview",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
