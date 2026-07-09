"""Tests for EmbeddingService and cosine_similarity."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.llm.embedding import EmbeddingService, _parse_embedding_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Mapping from Settings field names to their env-var aliases
_FIELD_TO_ALIAS: dict[str, str] = {
    "embedding_provider": "KSM_EMBEDDING_PROVIDER",
    "embedding_base_url": "KSM_EMBEDDING_BASE_URL",
    "embedding_api_key": "KSM_EMBEDDING_API_KEY",
    "embedding_model": "KSM_EMBEDDING_MODEL",
    "embedding_dimension": "KSM_EMBEDDING_DIMENSION",
    "embedding_batch_size": "KSM_EMBEDDING_BATCH_SIZE",
    "llm_base_url": "KSM_LLM_BASE_URL",
    "llm_api_key": "KSM_LLM_API_KEY",
}


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance with sensible defaults for tests.

    Uses environment variables because pydantic-settings fields have aliases
    and constructor kwargs with field names are ignored when aliases are set.
    All values must be strings (env vars are strings).
    """
    import os

    defaults: dict[str, str] = {
        "KSM_EMBEDDING_PROVIDER": "openai",
        "KSM_EMBEDDING_BASE_URL": "https://api.example.com/v1",
        "KSM_EMBEDDING_API_KEY": "sk-test-key",
        "KSM_EMBEDDING_MODEL": "text-embedding-3-small",
        "KSM_EMBEDDING_DIMENSION": "1536",
        "KSM_EMBEDDING_BATCH_SIZE": "32",
    }
    # Translate field names to env-var aliases and convert to strings
    for k, v in overrides.items():
        alias = _FIELD_TO_ALIAS.get(k, k)
        defaults[alias] = str(v)
    with patch.dict(os.environ, defaults, clear=False):
        return Settings()


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def _embedding_payload(texts: list[str], dim: int = 4) -> dict:
    """Build a fake OpenAI-compatible embedding response."""
    return {
        "data": [
            {"embedding": [float(i) for i in range(dim)], "index": idx}
            for idx, _ in enumerate(texts)
        ],
        "model": "test-model",
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }


# ---------------------------------------------------------------------------
# cosine_similarity tests
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    """Pure-Python cosine similarity."""

    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert math.isclose(EmbeddingService.cosine_similarity(v, v), 1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert math.isclose(EmbeddingService.cosine_similarity(a, b), 0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert math.isclose(EmbeddingService.cosine_similarity(a, b), -1.0)

    def test_known_value(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        expected = (1 * 4 + 2 * 5 + 3 * 6) / (
            math.sqrt(1 + 4 + 9) * math.sqrt(16 + 25 + 36)
        )
        assert math.isclose(EmbeddingService.cosine_similarity(a, b), expected)

    def test_empty_vectors(self):
        assert EmbeddingService.cosine_similarity([], []) == 0.0

    def test_mismatched_lengths(self):
        assert EmbeddingService.cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector(self):
        assert EmbeddingService.cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_single_element(self):
        assert math.isclose(EmbeddingService.cosine_similarity([5.0], [5.0]), 1.0)

    def test_large_vectors(self):
        a = [1.0] * 1536
        b = [1.0] * 1536
        assert math.isclose(EmbeddingService.cosine_similarity(a, b), 1.0)


# ---------------------------------------------------------------------------
# embed_text tests
# ---------------------------------------------------------------------------


class TestEmbedText:
    """Single-text embedding via API."""

    def test_success(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)
        payload = _embedding_payload(["hello world"])
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(payload)
            result = svc.embed_text("hello world")
        assert len(result) == 4
        assert result == [0.0, 1.0, 2.0, 3.0]

    def test_empty_text_returns_empty(self):
        svc = EmbeddingService(_make_settings())
        assert svc.embed_text("") == []
        assert svc.embed_text("   ") == []

    def test_api_error_returns_empty(self):
        svc = EmbeddingService(_make_settings())
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.side_effect = httpx.HTTPStatusError(
                "error",
                request=MagicMock(),
                response=_mock_response({}, status_code=500),
            )
            result = svc.embed_text("hello")
        assert result == []

    def test_network_error_returns_empty(self):
        svc = EmbeddingService(_make_settings())
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.side_effect = httpx.ConnectError("connection refused")
            result = svc.embed_text("hello")
        assert result == []

    def test_no_base_url_returns_empty(self):
        import os

        env_vars = {
            "KSM_EMBEDDING_BASE_URL": "",
            "KSM_LLM_BASE_URL": "",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            settings = Settings()
        svc = EmbeddingService(settings)
        result = svc.embed_text("hello")
        assert result == []

    def test_request_headers_and_body(self):
        import os

        env_vars = {
            "KSM_EMBEDDING_BASE_URL": "https://api.example.com/v1",
            "KSM_EMBEDDING_API_KEY": "sk-my-key",
            "KSM_EMBEDDING_MODEL": "my-model",
            "KSM_EMBEDDING_DIMENSION": "256",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            settings = Settings()
        svc = EmbeddingService(settings)

        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(
                _embedding_payload(["test"], dim=256)
            )
            svc.embed_text("test")

            call_args = client_instance.post.call_args
            url = call_args[0][0]
            assert url == "https://api.example.com/v1/embeddings"

            headers = call_args[1].get("headers", {})
            assert headers["Authorization"] == "Bearer sk-my-key"

            body = call_args[1].get("json", {})
            assert body["input"] == "test"
            assert body["model"] == "my-model"
            assert body["dimensions"] == 256

    def test_unexpected_response_returns_empty(self):
        svc = EmbeddingService(_make_settings())
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response({"unexpected": "shape"})
            result = svc.embed_text("hello")
        assert result == []


# ---------------------------------------------------------------------------
# embed_batch tests
# ---------------------------------------------------------------------------


class TestEmbedBatch:
    """Batch embedding with chunking."""

    def test_empty_input(self):
        svc = EmbeddingService(_make_settings())
        assert svc.embed_batch([]) == []

    def test_single_text(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)
        payload = _embedding_payload(["hello"])
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(payload)
            result = svc.embed_batch(["hello"])
        assert len(result) == 1
        assert result[0] == [0.0, 1.0, 2.0, 3.0]

    def test_multiple_texts(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)
        texts = ["hello", "world", "foo"]
        payload = _embedding_payload(texts)
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(payload)
            result = svc.embed_batch(texts)
        assert len(result) == 3

    def test_chunking_respects_batch_size(self):
        settings = _make_settings(embedding_batch_size=2)
        svc = EmbeddingService(settings)
        texts = ["a", "b", "c", "d", "e"]

        # Track all input lists sent to the API
        sent_inputs: list[list[str]] = []

        def side_effect(*args, **kwargs):
            body = kwargs.get("json", {})
            inp = body.get("input", [])
            if isinstance(inp, str):
                inp = [inp]
            sent_inputs.append(inp)
            return _mock_response(_embedding_payload(inp))

        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.side_effect = side_effect
            result = svc.embed_batch(texts)

        assert len(result) == 5
        # 5 texts / batch_size 2 => 3 API calls: ["a","b"], ["c","d"], ["e"]
        assert len(sent_inputs) == 3
        assert sent_inputs[0] == ["a", "b"]
        assert sent_inputs[1] == ["c", "d"]
        assert sent_inputs[2] == ["e"]

    def test_empty_strings_produce_empty_embeddings(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(
                _embedding_payload(["placeholder"])
            )
            result = svc.embed_batch(["", "  ", ""])
        assert result == [[], [], []]

    def test_api_error_produces_empty_entries(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.side_effect = httpx.ConnectError("no connection")
            result = svc.embed_batch(["a", "b", "c"])
        assert result == [[], [], []]

    def test_batch_mixed_valid_and_empty(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)
        texts = ["valid", "", "also valid"]
        payload = _embedding_payload(["valid", "also valid"])
        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(payload)
            result = svc.embed_batch(texts)
        assert len(result) == 3
        assert result[1] == []  # empty string -> empty list
        assert len(result[0]) == 4  # valid embedding
        assert len(result[2]) == 4  # valid embedding


# ---------------------------------------------------------------------------
# _parse_embedding_response tests
# ---------------------------------------------------------------------------


class TestParseEmbeddingResponse:
    """Unit tests for the response parser."""

    def test_sorted_by_index(self):
        data = {
            "data": [
                {"embedding": [3.0], "index": 2},
                {"embedding": [1.0], "index": 0},
                {"embedding": [2.0], "index": 1},
            ]
        }
        result = _parse_embedding_response(data, 3)
        assert result == [[1.0], [2.0], [3.0]]

    def test_empty_data(self):
        assert _parse_embedding_response({"data": []}, 1) == []

    def test_missing_data_key(self):
        assert _parse_embedding_response({}, 1) == []

    def test_count_mismatch(self):
        data = {"data": [{"embedding": [1.0], "index": 0}]}
        assert _parse_embedding_response(data, 2) == []

    def test_malformed_entry(self):
        data = {"data": [{"no_embedding_field": True, "index": 0}]}
        assert _parse_embedding_response(data, 1) == []


# ---------------------------------------------------------------------------
# Integration-style tests (verify request format)
# ---------------------------------------------------------------------------


class TestRequestFormat:
    """Verify the outgoing HTTP request is shaped correctly."""

    def test_batch_input_is_list(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)

        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(
                _embedding_payload(["a", "b"])
            )
            svc.embed_batch(["a", "b"])

            body = client_instance.post.call_args[1].get("json", {})
            assert isinstance(body["input"], list)
            assert body["input"] == ["a", "b"]

    def test_single_text_input_is_string(self):
        settings = _make_settings()
        svc = EmbeddingService(settings)

        with patch("app.llm.embedding.httpx.Client") as mock_client_cls:
            client_instance = mock_client_cls.return_value.__enter__.return_value
            client_instance.post.return_value = _mock_response(
                _embedding_payload(["only one"])
            )
            svc.embed_text("only one")

            body = client_instance.post.call_args[1].get("json", {})
            assert isinstance(body["input"], str)
