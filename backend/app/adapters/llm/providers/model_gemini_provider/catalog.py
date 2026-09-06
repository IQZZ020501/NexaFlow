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
        "EMBEDDING"
    ],
    "models": {
        "LLM": [
            {
                "name": "gemini-1.5-flash",
                "desc": "Gemini 1.5 Flash",
                "model_type": "LLM"
            },
            {
                "name": "gemini-1.5-pro",
                "desc": "Gemini 1.5 Pro",
                "model_type": "LLM"
            },
            {
                "name": "gemini-1.0-pro",
                "desc": "Gemini 1.0 Pro",
                "model_type": "LLM"
            }
        ],
        "EMBEDDING": [
            {
                "name": "models/text-embedding-004",
                "desc": "Gemini embedding model",
                "model_type": "EMBEDDING"
            },
            {
                "name": "models/embedding-001",
                "desc": "Gemini embedding model",
                "model_type": "EMBEDDING"
            }
        ]
    }
}
