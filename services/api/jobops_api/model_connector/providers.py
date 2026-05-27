from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol

from .config import ModelConnectorConfig
from .errors import ModelConfigurationError, ModelProviderError
from .models import ModelMessage, ModelRequest, ModelResponse, ModelTask
from .routing import route_model_request


MockResponder = str | Callable[[ModelRequest], str]


class ModelProvider(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse:
        ...


class ModelConnector:
    def __init__(self, provider: ModelProvider, config: ModelConnectorConfig) -> None:
        self.provider = provider
        self.config = config

    def route_request(self, request: ModelRequest) -> ModelRequest:
        return route_model_request(request, self.config.routing)

    def generate(self, request: ModelRequest) -> ModelResponse:
        return self.provider.generate(self.route_request(request))


class MockModelProvider:
    def __init__(
        self,
        *,
        default_response: str = "{}",
        responses_by_task: dict[ModelTask, MockResponder] | None = None,
    ) -> None:
        self.default_response = default_response
        self.responses_by_task = responses_by_task or {}

    def generate(self, request: ModelRequest) -> ModelResponse:
        responder = self.responses_by_task.get(request.task, self.default_response)
        text = responder(request) if callable(responder) else responder
        return ModelResponse(
            finish_reason="stop",
            model=request.model or "mock",
            provider="mock",
            text=text,
            metadata={"searchGroundingEnabled": request.search_grounding},
        )


class GeminiModelProvider:
    endpoint_base = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None, *, timeout_seconds: float = 60) -> None:
        if not api_key:
            raise ModelConfigurationError("GEMINI_API_KEY is required when JOBOPS_LLM_PROVIDER=gemini.")
        if timeout_seconds <= 0:
            raise ModelConfigurationError("JOBOPS_LLM_TIMEOUT_SECONDS must be greater than 0.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not request.model:
            raise ModelConfigurationError("ModelRequest.model is required before provider generation.")

        encoded_model = urllib.parse.quote(request.model, safe="")
        url = f"{self.endpoint_base}/{encoded_model}:generateContent"
        payload = build_gemini_payload(request)
        body = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ModelProviderError(f"Gemini request failed with HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ModelProviderError(f"Gemini request failed: {error.reason}") from error
        except TimeoutError as error:
            raise ModelProviderError("Gemini request timed out.") from error

        data = parse_gemini_response_json(response_body)
        candidate = first_gemini_candidate(data)
        parts = gemini_candidate_parts(candidate)
        text = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str)).strip()
        if not text:
            raise ModelProviderError("Gemini response did not include text content.")

        return ModelResponse(
            finish_reason=candidate.get("finishReason") if isinstance(candidate.get("finishReason"), str) else None,
            metadata=gemini_response_metadata(candidate, data),
            model=request.model,
            provider="gemini",
            text=text,
        )


def create_model_connector(
    config: ModelConnectorConfig,
    *,
    mock_responses_by_task: dict[ModelTask, MockResponder] | None = None,
) -> ModelConnector:
    provider_name = config.provider.strip().lower()
    if provider_name == "mock":
        return ModelConnector(
            MockModelProvider(responses_by_task=mock_responses_by_task),
            config,
        )
    if provider_name == "gemini":
        return ModelConnector(
            GeminiModelProvider(config.gemini_api_key, timeout_seconds=config.request_timeout_seconds),
            config,
        )
    raise ModelConfigurationError(f"Unsupported JOBOPS_LLM_PROVIDER: {config.provider}")


def build_gemini_payload(request: ModelRequest) -> dict[str, object]:
    system_text = "\n\n".join(message.content for message in request.messages if message.role == "system").strip()
    conversation = [message for message in request.messages if message.role != "system"]
    contents = [
        {
            "role": gemini_role(message),
            "parts": [{"text": message.content}],
        }
        for message in conversation
    ]
    generation_config: dict[str, object] = {
        "temperature": request.temperature,
        "maxOutputTokens": request.max_output_tokens,
    }
    if request.response_mime_type and not request.search_grounding:
        generation_config["responseMimeType"] = request.response_mime_type
    if request.thinking_budget is not None and not request.search_grounding:
        generation_config["thinkingConfig"] = {"thinkingBudget": request.thinking_budget}

    payload: dict[str, object] = {
        "contents": contents,
        "generationConfig": generation_config,
    }
    if request.search_grounding:
        payload["tools"] = [{"google_search": {}}]
    if system_text:
        payload["systemInstruction"] = {
            "parts": [{"text": system_text}],
        }

    return payload


def gemini_role(message: ModelMessage) -> str:
    return "model" if message.role == "assistant" else "user"


def parse_gemini_response_json(response_body: str) -> dict[str, object]:
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise ModelProviderError("Gemini response was not valid JSON.") from error

    if not isinstance(data, dict):
        raise ModelProviderError("Gemini response was not a JSON object.")

    return data


def first_gemini_candidate(data: dict[str, object]) -> dict[str, object]:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ModelProviderError("Gemini response did not include candidates.")

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ModelProviderError("Gemini response candidate was not a JSON object.")

    return candidate


def gemini_candidate_parts(candidate: dict[str, object]) -> list[dict[str, object]]:
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ModelProviderError("Gemini response candidate did not include content.")

    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ModelProviderError("Gemini response content did not include parts.")

    return [part for part in parts if isinstance(part, dict)]


def gemini_response_metadata(candidate: dict[str, object], data: dict[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    grounding_metadata = candidate.get("groundingMetadata")
    if isinstance(grounding_metadata, dict):
        metadata["groundingMetadata"] = grounding_metadata
        web_search_queries = grounding_metadata.get("webSearchQueries")
        if isinstance(web_search_queries, list):
            metadata["webSearchQueries"] = [query for query in web_search_queries if isinstance(query, str)]

    usage_metadata = data.get("usageMetadata")
    if isinstance(usage_metadata, dict):
        metadata["usageMetadata"] = usage_metadata

    return metadata
