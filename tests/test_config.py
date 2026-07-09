"""Tests for KSM configuration settings."""

import os
from unittest.mock import patch

import pytest

from app.config import Settings


class TestEmbeddingConfig:
    """Test embedding configuration fields in Settings."""

    def test_embedding_defaults(self):
        """Test that embedding fields have correct default values."""
        settings = Settings()
        assert settings.embedding_provider == "openai"
        assert settings.embedding_base_url == ""
        assert settings.embedding_api_key == ""
        assert settings.embedding_model == "text-embedding-3-small"
        assert settings.embedding_dimension == 1536
        assert settings.embedding_batch_size == 32

    def test_embedding_from_env(self):
        """Test that embedding fields can be loaded from environment variables."""
        env_vars = {
            "KSM_EMBEDDING_PROVIDER": "anthropic",
            "KSM_EMBEDDING_BASE_URL": "https://api.anthropic.com/v1",
            "KSM_EMBEDDING_API_KEY": "sk-ant-test-key",
            "KSM_EMBEDDING_MODEL": "claude-3-haiku",
            "KSM_EMBEDDING_DIMENSION": "1024",
            "KSM_EMBEDDING_BATCH_SIZE": "64",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.embedding_provider == "anthropic"
            assert settings.embedding_base_url == "https://api.anthropic.com/v1"
            assert settings.embedding_api_key == "sk-ant-test-key"
            assert settings.embedding_model == "claude-3-haiku"
            assert settings.embedding_dimension == 1024
            assert settings.embedding_batch_size == 64


class TestDedupConfig:
    """Test deduplication threshold configuration fields."""

    def test_dedup_defaults(self):
        """Test that dedup threshold fields have correct default values."""
        settings = Settings()
        assert settings.dedup_source_threshold == 0.92
        assert settings.dedup_card_threshold == 0.88
        assert settings.dedup_merge_threshold == 0.90

    def test_dedup_from_env(self):
        """Test that dedup threshold fields can be loaded from environment variables."""
        env_vars = {
            "KSM_DEDUP_SOURCE_THRESHOLD": "0.95",
            "KSM_DEDUP_CARD_THRESHOLD": "0.85",
            "KSM_DEDUP_MERGE_THRESHOLD": "0.91",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.dedup_source_threshold == 0.95
            assert settings.dedup_card_threshold == 0.85
            assert settings.dedup_merge_threshold == 0.91


class TestEmbeddingFallback:
    """Test fallback behavior for embedding_base_url and embedding_api_key."""

    def test_embedding_base_url_fallback_to_llm(self):
        """Test that embedding_base_url falls back to llm_base_url when empty."""
        env_vars = {
            "KSM_LLM_BASE_URL": "https://api.openai.com/v1",
            "KSM_EMBEDDING_BASE_URL": "",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.effective_embedding_base_url == "https://api.openai.com/v1"

    def test_embedding_base_url_no_fallback(self):
        """Test that embedding_base_url is used when explicitly set."""
        env_vars = {
            "KSM_LLM_BASE_URL": "https://api.openai.com/v1",
            "KSM_EMBEDDING_BASE_URL": "https://api.custom-embedding.com/v1",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.effective_embedding_base_url == "https://api.custom-embedding.com/v1"

    def test_embedding_api_key_fallback_to_llm(self):
        """Test that embedding_api_key falls back to llm_api_key when empty."""
        env_vars = {
            "KSM_LLM_API_KEY": "sk-llm-test-key",
            "KSM_EMBEDDING_API_KEY": "",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.effective_embedding_api_key == "sk-llm-test-key"

    def test_embedding_api_key_no_fallback(self):
        """Test that embedding_api_key is used when explicitly set."""
        env_vars = {
            "KSM_LLM_API_KEY": "sk-llm-test-key",
            "KSM_EMBEDDING_API_KEY": "sk-embedding-test-key",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.effective_embedding_api_key == "sk-embedding-test-key"

    def test_fallback_with_all_empty(self):
        """Test fallback behavior when both embedding and LLM values are empty."""
        env_vars = {
            "KSM_LLM_BASE_URL": "",
            "KSM_LLM_API_KEY": "",
            "KSM_EMBEDDING_BASE_URL": "",
            "KSM_EMBEDDING_API_KEY": "",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            # Should return empty strings when both are empty
            assert settings.effective_embedding_base_url == ""
            assert settings.effective_embedding_api_key == ""
