"""Pure unit tests for the models feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.models.unit
"""
import tests.support  # noqa: F401  (sets required env before app imports)

"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

from types import SimpleNamespace

from fastapi import HTTPException

from app.application.models.registry import (
    is_masked_secret,
    normalize_model_type,
    normalize_provider_credentials,
    normalize_url_credential,
    validate_status,
)


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError("expected HTTPException")

def payload_with(**fields):
    return SimpleNamespace(model_dump=lambda: fields)

def test_model_type_normalization() -> None:
    assert normalize_model_type("llm") == "LLM"
    assert normalize_model_type("vision") == "VISION"
    assert normalize_model_type("image") == "IMAGE"
    assert normalize_model_type(" embeddings ") == "EMBEDDING"
    assert normalize_model_type("rerank") == "RERANKER"
    expect_http_error(lambda: normalize_model_type("audio"), 422)


def test_image_model_registration_skips_paid_connection_tests() -> None:
    from app.application.models.registry import run_model_test

    assert run_model_test("openai_compatible", {}, "gpt-image-1", "IMAGE") == {}

def test_status_validation() -> None:
    assert validate_status("active") == "active"
    expect_http_error(lambda: validate_status("paused"), 422)

def test_url_credential_validation() -> None:
    assert (
        normalize_url_credential("https://api.example.com/", "api_base")
        == "https://api.example.com"
    )
    expect_http_error(
        lambda: normalize_url_credential("file:///tmp/x", "api_base"),
        422,
    )

def test_masked_secret_detection() -> None:
    assert is_masked_secret("****abcd", "abcd")
    assert not is_masked_secret("real-secret", "abcd")

def test_provider_credentials_aws_pairing_rule() -> None:
    entry = {
        "credential_fields": [
            {"field": "aws_access_key_id", "input_type": "PasswordInput", "required": False},
            {"field": "aws_secret_access_key", "input_type": "PasswordInput", "required": False},
            {"field": "aws_session_token", "input_type": "PasswordInput", "required": False},
        ]
    }
    expect_http_error(
        lambda: normalize_provider_credentials(
            entry,
            {"aws_access_key_id": "AKIA123"},
        ),
        422,
    )
    expect_http_error(
        lambda: normalize_provider_credentials(
            entry,
            {"aws_session_token": "token"},
        ),
        422,
    )
    _config, secrets, _hints, changed = normalize_provider_credentials(
        entry,
        {"aws_access_key_id": "AKIA123", "aws_secret_access_key": "secret"},
    )
    assert changed == {"aws_access_key_id", "aws_secret_access_key"}
    assert secrets["aws_access_key_id"] == "AKIA123"

def test_run_knowledge_model_test_uses_injected_providers() -> None:
    from app.domain.knowledge.service import run_knowledge_model_test
    from app.schemas.knowledge import KnowledgeModelTestRequest

    embedding_model = SimpleNamespace(id="emb-1")
    reranker_model = SimpleNamespace(id="rerank-1")
    calls = {"embed": 0, "rerank": 0}

    class FakeEmbeddings:
        def embed_query(self, text: str) -> list[float]:
            assert text == "query"
            calls["embed"] += 1
            return [1.0, 2.0, 3.0]

    class FakeReranker:
        def rerank(self, query: str, documents: list[str]) -> list[dict]:
            assert query == "query"
            assert documents == ["doc"]
            calls["rerank"] += 1
            return [{"index": 0, "relevance_score": 0.9}]

    from app.domain.knowledge.bases import service as knowledge_kb

    original_embeddings = knowledge_kb.build_embeddings
    original_reranker = knowledge_kb.build_reranker
    knowledge_kb.build_embeddings = lambda _settings, _model: FakeEmbeddings()
    knowledge_kb.build_reranker = lambda _settings, _model: FakeReranker()
    try:
        response = run_knowledge_model_test(
            embedding_model,
            reranker_model,
            KnowledgeModelTestRequest(query="query", documents=["doc"]),
            settings=object(),
        )
        assert response.embedding_dimensions == 3
        assert response.reranker_results == 1
        assert calls == {"embed": 1, "rerank": 1}

        # without a reranker the rerank port is never touched
        no_rerank = run_knowledge_model_test(
            embedding_model,
            None,
            KnowledgeModelTestRequest(query="query", documents=["doc"]),
            settings=object(),
        )
        assert no_rerank.reranker_model_id is None
        assert calls["rerank"] == 1
    finally:
        knowledge_kb.build_embeddings = original_embeddings
        knowledge_kb.build_reranker = original_reranker


def main() -> None:
    test_model_type_normalization()
    test_status_validation()
    test_url_credential_validation()
    test_masked_secret_detection()
    test_provider_credentials_aws_pairing_rule()
    test_run_knowledge_model_test_uses_injected_providers()
    print("MODELS_UNIT_OK")


if __name__ == "__main__":
    main()
