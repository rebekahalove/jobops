from __future__ import annotations

from dataclasses import dataclass

from ..settings import Settings
from .routing import ModelRoutingConfig


@dataclass(frozen=True)
class ModelConnectorConfig:
    provider: str
    routing: ModelRoutingConfig
    gemini_api_key: str | None = None
    request_timeout_seconds: float = 60


def read_model_connector_config_from_settings(settings: Settings) -> ModelConnectorConfig:
    return ModelConnectorConfig(
        gemini_api_key=settings.gemini_api_key,
        provider=settings.model_provider,
        routing=ModelRoutingConfig(
            cheap_model=settings.cheap_model,
            default_model=settings.default_model,
        ),
        request_timeout_seconds=settings.llm_request_timeout_seconds,
    )
