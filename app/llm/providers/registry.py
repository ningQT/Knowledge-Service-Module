"""Extensible model provider registry.

This module keeps provider metadata and model construction in one place so KSM can
add or remove vendors without scattering provider-specific imports across the
write, search, and answer pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.config import Settings
from app.security.url_validation import validate_llm_base_url


CHAT_CAPABILITY = "chat"
STRUCTURED_OUTPUT_CAPABILITY = "structured_output"
EMBEDDING_CAPABILITY = "embedding"
TTS_CAPABILITY = "tts"
VISION_CAPABILITY = "vision"
AUDIO_INPUT_CAPABILITY = "audio_input"


class LLMNotConfiguredError(RuntimeError):
    """Raised when a chat model is requested before the LLM is configured."""


class UnsupportedProviderCapabilityError(RuntimeError):
    """Raised when a provider or capability is not available."""


@dataclass(frozen=True)
class ModelProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str = ""

    @classmethod
    def from_settings(cls, settings: Settings) -> "ModelProviderConfig":
        return cls(
            provider=(settings.llm_provider or "").strip(),
            model=(settings.llm_model or "").strip(),
            api_key=(settings.llm_api_key or "").strip(),
            base_url=(settings.llm_base_url or "").strip().rstrip("/"),
        )


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    display_name: str
    docs_url: str
    default_base_url: str | None
    model_examples: tuple[str, ...]
    required_fields: tuple[str, ...]
    capabilities: tuple[str, ...]
    chat_builder: Callable[[ModelProviderConfig, "ProviderDescriptor"], Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "docs_url": self.docs_url,
            "default_base_url": self.default_base_url,
            "model_examples": list(self.model_examples),
            "required_fields": list(self.required_fields),
            "capabilities": list(self.capabilities),
        }


def _provider_id(settings: Settings) -> str:
    provider = (settings.llm_provider or "").strip()
    if provider:
        return provider
    if settings.llm_api_key and settings.llm_model:
        return "openai"
    return ""


def _base_url(config: ModelProviderConfig, descriptor: ProviderDescriptor) -> str | None:
    return config.base_url or descriptor.default_base_url


def _build_openai_chat_model(config: ModelProviderConfig, descriptor: ProviderDescriptor) -> Any:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        api_key=config.api_key or None,
        base_url=_base_url(config, descriptor),
    )
    return OpenAIChatModel(config.model, provider=provider)


def _build_alibaba_chat_model(config: ModelProviderConfig, descriptor: ProviderDescriptor) -> Any:
    return _build_openai_chat_model(config, descriptor)


def _build_anthropic_chat_model(config: ModelProviderConfig, _descriptor: ProviderDescriptor) -> Any:
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(config.model, provider=AnthropicProvider(api_key=config.api_key or None))


def _build_google_chat_model(config: ModelProviderConfig, _descriptor: ProviderDescriptor) -> Any:
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    return GoogleModel(config.model, provider=GoogleProvider(api_key=config.api_key or None))


def _build_openrouter_chat_model(config: ModelProviderConfig, _descriptor: ProviderDescriptor) -> Any:
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    return OpenRouterModel(config.model, provider=OpenRouterProvider(api_key=config.api_key or None))


class ModelProvider:
    """Single provider entry with current and future model factories."""

    def __init__(self, descriptor: ProviderDescriptor):
        self.descriptor = descriptor

    def build_chat_model(self, config: ModelProviderConfig) -> Any:
        return self.descriptor.chat_builder(config, self.descriptor)

    def build_embedding_model(self, _config: ModelProviderConfig) -> Any:
        raise UnsupportedProviderCapabilityError("Embedding models are not implemented yet")

    def build_tts_model(self, _config: ModelProviderConfig) -> Any:
        raise UnsupportedProviderCapabilityError("TTS models are not implemented yet")

    def build_multimodal_model(self, _config: ModelProviderConfig) -> Any:
        raise UnsupportedProviderCapabilityError("Multimodal models are not implemented yet")


class ProviderRegistry:
    """Registry for all model providers supported by the management console."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for descriptor in _default_descriptors():
            self.register(ModelProvider(descriptor))

    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.descriptor.id] = provider

    def list_providers(self) -> list[ProviderDescriptor]:
        return [provider.descriptor for provider in self._providers.values()]

    def get_provider(self, provider_id: str) -> ModelProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise UnsupportedProviderCapabilityError(f"Unsupported LLM provider: {provider_id}") from exc

    def missing_fields(self, settings: Settings) -> list[str]:
        provider_id = _provider_id(settings)
        if not provider_id:
            return ["provider", "model", "api_key"]

        provider = self.get_provider(provider_id)
        config = ModelProviderConfig.from_settings(settings)
        missing: list[str] = []
        for field in provider.descriptor.required_fields:
            if field == "provider" and not provider_id:
                missing.append(field)
            elif field == "model" and not config.model:
                missing.append(field)
            elif field == "api_key" and not config.api_key:
                missing.append(field)
            elif field == "base_url" and not _base_url(config, provider.descriptor):
                missing.append(field)
        return missing

    def is_configured(self, settings: Settings) -> bool:
        try:
            return not self.missing_fields(settings)
        except UnsupportedProviderCapabilityError:
            return False

    def build_chat_model(self, settings: Settings) -> Any:
        missing = self.missing_fields(settings)
        if missing:
            raise LLMNotConfiguredError(f"LLM configuration is incomplete: {', '.join(missing)}")

        provider_id = _provider_id(settings)
        provider = self.get_provider(provider_id)
        config = ModelProviderConfig.from_settings(settings)
        if config.base_url:
            validate_llm_base_url(
                config.base_url,
                require_https=getattr(settings, "require_https_llm_base_url", False),
                ssrf_protection=getattr(settings, "llm_ssrf_protection", None),
            )
        if not config.provider:
            config = ModelProviderConfig(
                provider=provider_id,
                model=config.model,
                api_key=config.api_key,
                base_url=config.base_url,
            )
        return provider.build_chat_model(config)


def _default_capabilities(*extra: str) -> tuple[str, ...]:
    return (CHAT_CAPABILITY, STRUCTURED_OUTPUT_CAPABILITY, *extra)


def _default_descriptors() -> tuple[ProviderDescriptor, ...]:
    compatible_required = ("provider", "api_key", "model", "base_url")
    return (
        ProviderDescriptor(
            id="openai",
            display_name="OpenAI",
            docs_url="https://platform.openai.com/docs",
            default_base_url="https://api.openai.com/v1",
            model_examples=("gpt-4o", "gpt-4o-mini", "gpt-4.1"),
            required_fields=("provider", "api_key", "model"),
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_openai_chat_model,
        ),
        ProviderDescriptor(
            id="anthropic",
            display_name="Anthropic Claude",
            docs_url="https://docs.anthropic.com/",
            default_base_url=None,
            model_examples=("claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"),
            required_fields=("provider", "api_key", "model"),
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_anthropic_chat_model,
        ),
        ProviderDescriptor(
            id="gemini",
            display_name="Google Gemini",
            docs_url="https://ai.google.dev/gemini-api/docs",
            default_base_url=None,
            model_examples=("gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"),
            required_fields=("provider", "api_key", "model"),
            capabilities=_default_capabilities(VISION_CAPABILITY, AUDIO_INPUT_CAPABILITY),
            chat_builder=_build_google_chat_model,
        ),
        ProviderDescriptor(
            id="dashscope",
            display_name="阿里百炼 DashScope",
            docs_url="https://help.aliyun.com/zh/model-studio/",
            default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_examples=("qwen-plus", "qwen-turbo", "qwen-max"),
            required_fields=("provider", "api_key", "model"),
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_alibaba_chat_model,
        ),
        ProviderDescriptor(
            id="zhipu",
            display_name="智谱 GLM",
            docs_url="https://docs.bigmodel.cn/",
            default_base_url="https://open.bigmodel.cn/api/paas/v4",
            model_examples=("glm-4-plus", "glm-4-air", "glm-4-flash"),
            required_fields=("provider", "api_key", "model"),
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_openai_chat_model,
        ),
        ProviderDescriptor(
            id="siliconflow",
            display_name="硅基流动 SiliconFlow",
            docs_url="https://docs.siliconflow.com/",
            default_base_url="https://api.siliconflow.cn/v1",
            model_examples=("Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"),
            required_fields=("provider", "api_key", "model"),
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_openai_chat_model,
        ),
        ProviderDescriptor(
            id="xiaomi",
            display_name="小米 MiMo",
            docs_url="https://docs.litellm.ai/docs/providers/xiaomi_mimo",
            default_base_url=None,
            model_examples=("mimo-chat", "mimo-vl"),
            required_fields=compatible_required,
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_openai_chat_model,
        ),
        ProviderDescriptor(
            id="openrouter",
            display_name="OpenRouter",
            docs_url="https://openrouter.ai/docs",
            default_base_url=None,
            model_examples=("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"),
            required_fields=("provider", "api_key", "model"),
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_openrouter_chat_model,
        ),
        ProviderDescriptor(
            id="openai_compatible",
            display_name="OpenAI-compatible",
            docs_url="https://platform.openai.com/docs/api-reference/chat",
            default_base_url=None,
            model_examples=("your-model-name",),
            required_fields=compatible_required,
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_openai_chat_model,
        ),
        ProviderDescriptor(
            id="litellm_proxy",
            display_name="LiteLLM Proxy",
            docs_url="https://docs.litellm.ai/docs/proxy/quick_start",
            default_base_url=None,
            model_examples=("gpt-4o-mini", "claude-3-5-sonnet-latest"),
            required_fields=compatible_required,
            capabilities=_default_capabilities(VISION_CAPABILITY),
            chat_builder=_build_openai_chat_model,
        ),
    )


_REGISTRY = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    return _REGISTRY
