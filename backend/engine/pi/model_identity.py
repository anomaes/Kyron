from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


def normalize_pi_models(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        provider = item.get("provider")
        model = item.get("model")
        if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
            continue
        response_models = item.get("response_models", [])
        normalized.append(
            {
                "provider": provider,
                "model": model,
                "response_models": list(
                    dict.fromkeys(
                        response
                        for response in response_models
                        if isinstance(response, str) and response
                    )
                )
                if isinstance(response_models, list)
                else [],
            }
        )
    return merge_pi_models([], normalized)


def merge_pi_models(
    target: list[dict[str, Any]], models: object
) -> list[dict[str, Any]]:
    existing = normalize_pi_models_shallow(target)
    target.clear()
    target.extend(existing)
    by_identity = {(item["provider"], item["model"]): item for item in target}
    for item in normalize_pi_models_shallow(models):
        key = (item["provider"], item["model"])
        current = by_identity.get(key)
        if current is None:
            current = {**item, "response_models": list(item["response_models"])}
            target.append(current)
            by_identity[key] = current
            continue
        current["response_models"] = list(
            dict.fromkeys([*current["response_models"], *item["response_models"]])
        )
    return target


def aggregate_pi_models_events(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for event in events:
        messages: list[object] = []
        if "message" in event:
            messages.append(event.get("message"))
        event_messages = event.get("messages")
        if isinstance(event_messages, list):
            messages.extend(event_messages)
        for message in messages:
            if not isinstance(message, Mapping) or message.get("role") != "assistant":
                continue
            provider = message.get("provider")
            model = message.get("model")
            if (
                not isinstance(provider, str)
                or not provider
                or not isinstance(model, str)
                or not model
            ):
                continue
            response_model = message.get("responseModel", message.get("response_model"))
            merge_pi_models(
                models,
                [
                    {
                        "provider": provider,
                        "model": model,
                        "response_models": [response_model]
                        if isinstance(response_model, str) and response_model
                        else [],
                    }
                ],
            )
    return models


def aggregate_pi_models_content(content: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            events.append(event)
    return aggregate_pi_models_events(events)


def normalize_pi_models_shallow(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        provider = item.get("provider")
        model = item.get("model")
        if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
            continue
        raw_responses = item.get("response_models", [])
        responses = (
            [response for response in raw_responses if isinstance(response, str) and response]
            if isinstance(raw_responses, list)
            else []
        )
        normalized.append(
            {"provider": provider, "model": model, "response_models": responses}
        )
    return normalized
