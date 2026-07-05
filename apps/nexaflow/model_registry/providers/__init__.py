from importlib import import_module

PROVIDER_MODULES = [
    "aliyun_bai_lian_model_provider",
    "model_anthropic_provider",
    "model_aws_bedrock_provider",
    "model_azure_provider",
    "model_deepseek_provider",
    "model_openai_provider",
    "model_zhipu_provider",
    "model_kimi_provider",
    "model_siliconflow_provider",
    "model_docker_ai_provider",
    "model_gemini_provider",
    "model_local_provider",
    "model_vllm_provider",
    "model_ollama_provider",
    "model_regolo_provider",
    "model_tencent_cloud_provider",
    "model_tencent_provider",
    "model_volcanic_engine_provider",
    "model_wenxin_provider",
    "model_xf_provider",
    "model_xinference_provider",
    "model_custom_provider",
]

PROVIDER_CATALOG = [
    import_module(f"{__name__}.{provider}.catalog").CATALOG
    for provider in PROVIDER_MODULES
]

__all__ = ["PROVIDER_CATALOG"]
