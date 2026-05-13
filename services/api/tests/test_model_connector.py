from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobops_api.model_connector import (
    GeminiModelProvider,
    MockModelProvider,
    ModelConfigurationError,
    ModelConnectorConfig,
    ModelMessage,
    ModelProviderError,
    ModelRequest,
    ModelRoutingConfig,
    create_model_connector,
    read_model_connector_config_from_settings,
    route_model_request,
    select_model_for_task,
)
from jobops_api.settings import Settings


def test_model_routing_selects_default_and_cheap_models() -> None:
    routing = ModelRoutingConfig(default_model="default-model", cheap_model="cheap-model")

    assert select_model_for_task("profile_extract", routing) == "default-model"
    assert select_model_for_task("intake_followup", routing) == "default-model"
    assert select_model_for_task("role_fit", routing) == "default-model"
    assert select_model_for_task("judge_or_second_pass", routing) == "default-model"
    assert select_model_for_task("bulk_triage", routing) == "cheap-model"
    assert select_model_for_task("eval_harness", routing) == "cheap-model"


def test_route_model_request_preserves_explicit_model() -> None:
    request = make_request(task="bulk_triage", model="explicit-model")
    routing = ModelRoutingConfig(default_model="default-model", cheap_model="cheap-model")

    assert route_model_request(request, routing).model == "explicit-model"


def test_mock_provider_returns_deterministic_task_output() -> None:
    provider = MockModelProvider(
        responses_by_task={
            "profile_extract": lambda request: json.dumps({"task": request.task, "model": request.model}),
        }
    )
    response = provider.generate(make_request(task="profile_extract", model="mock-default"))

    assert response.provider == "mock"
    assert response.model == "mock-default"
    assert json.loads(response.text) == {
        "task": "profile_extract",
        "model": "mock-default",
    }


def test_gemini_provider_missing_key_fails_configuration() -> None:
    with pytest.raises(ModelConfigurationError, match="GEMINI_API_KEY"):
        GeminiModelProvider(None)


def test_provider_factory_selects_mock_and_routes_model() -> None:
    connector = create_model_connector(
        ModelConnectorConfig(
            provider="mock",
            routing=ModelRoutingConfig(default_model="default-model", cheap_model="cheap-model"),
        ),
        mock_responses_by_task={"bulk_triage": "bulk"},
    )

    response = connector.generate(make_request(task="bulk_triage"))

    assert response.text == "bulk"
    assert response.model == "cheap-model"


def test_provider_factory_selects_gemini_when_configured() -> None:
    connector = create_model_connector(
        ModelConnectorConfig(
            gemini_api_key="test-key",
            provider="gemini",
            routing=ModelRoutingConfig(default_model="default-model", cheap_model="cheap-model"),
        )
    )

    assert isinstance(connector.provider, GeminiModelProvider)


def test_read_model_connector_config_from_settings() -> None:
    config = read_model_connector_config_from_settings(
        Settings(
            app_env="test",
            cheap_model="cheap",
            database_url=None,
            default_model="default",
            default_candidate_profile_slug="rebekah-love",
            gemini_api_key="key",
            model_provider="mock",
            profile_intake_save_artifacts=False,
            profile_intake_save_raw_text=False,
            repo_root=Path("."),
        )
    )

    assert config.provider == "mock"
    assert config.gemini_api_key == "key"
    assert config.routing.default_model == "default"
    assert config.routing.cheap_model == "cheap"


def test_gemini_invalid_json_response_is_wrapped_safely(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeHttpResponse("not json"),
    )

    with pytest.raises(ModelProviderError, match="not valid JSON"):
        GeminiModelProvider("test-key").generate(make_request(task="profile_extract", model="gemini-test"))


def test_gemini_unexpected_response_shape_is_wrapped_safely(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeHttpResponse("{}"),
    )

    with pytest.raises(ModelProviderError, match="did not include candidates"):
        GeminiModelProvider("test-key").generate(make_request(task="profile_extract", model="gemini-test"))


class FakeHttpResponse:
    def __init__(self, body: str) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body.encode("utf-8")


def make_request(*, task, model: str | None = None) -> ModelRequest:
    return ModelRequest(
        max_output_tokens=4000,
        messages=[
            ModelMessage(role="system", content="Return JSON."),
            ModelMessage(role="user", content="{}"),
        ],
        model=model,
        response_mime_type="application/json",
        task=task,
        temperature=0,
    )
