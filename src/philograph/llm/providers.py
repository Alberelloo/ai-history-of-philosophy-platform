"""Провайдеры моделей за общим интерфейсом."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    messages: tuple[Message, ...]
    max_output_tokens: int
    temperature: float
    timeout_seconds: float
    json_mode: bool = False


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage


@dataclass(frozen=True)
class StreamChunk:
    text: str = ""
    usage: Usage | None = None  # приходит с последним фрагментом


class TransientProviderError(Exception):
    """Временная ошибка: перегрузка, таймаут, обрыв. Можно повторить."""


class PermanentProviderError(Exception):
    """Постоянная ошибка: неверный ключ, неверный запрос. Повторять бессмысленно."""


class Provider(Protocol):
    def generate(self, request: ProviderRequest) -> Completion: ...

    def stream(self, request: ProviderRequest) -> Iterator[StreamChunk]: ...

    def embed(
        self, model: str, texts: list[str], timeout_seconds: float
    ) -> tuple[list[list[float]], Usage]: ...


# --- тестовый провайдер -------------------------------------------------------------


@dataclass
class FakeProvider:
    """Отвечает по сценарию: заранее заданные ответы и ошибки по очереди.

    Элемент сценария — строка ответа, исключение или список фрагментов для потока
    (исключение в списке означает обрыв на этом месте).
    """

    script: deque[Any] = field(default_factory=deque)
    default: str = "ok"
    calls: list[ProviderRequest] = field(default_factory=list)
    embed_calls: list[list[str]] = field(default_factory=list)
    dimension: int = 8

    def push(self, *items: Any) -> None:
        self.script.extend(items)

    def _next(self) -> Any:
        return self.script.popleft() if self.script else self.default

    @staticmethod
    def _usage(request: ProviderRequest, text: str) -> Usage:
        prompt = sum(len(m.content) for m in request.messages)
        return Usage(
            input_tokens=max(1, prompt // 4),
            cached_input_tokens=0,
            output_tokens=max(1, len(text) // 4),
        )

    def generate(self, request: ProviderRequest) -> Completion:
        self.calls.append(request)
        item = self._next()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, list):
            item = "".join(str(p) for p in item if not isinstance(p, Exception))
        return Completion(item, self._usage(request, item))

    def stream(self, request: ProviderRequest) -> Iterator[StreamChunk]:
        self.calls.append(request)
        item = self._next()
        if isinstance(item, Exception):
            raise item
        parts = item if isinstance(item, list) else [item]
        produced = ""
        for part in parts:
            if isinstance(part, Exception):
                raise part
            produced += part
            yield StreamChunk(text=part)
        yield StreamChunk(usage=self._usage(request, produced))

    def embed(
        self, model: str, texts: list[str], timeout_seconds: float
    ) -> tuple[list[list[float]], Usage]:
        self.embed_calls.append(list(texts))
        item = (
            self.script.popleft() if self.script and isinstance(self.script[0], Exception) else None
        )
        if item is not None:
            raise item
        vectors = []
        for text in texts:
            seed = sum(ord(c) for c in text)
            vectors.append([((seed * (i + 1)) % 97) / 97 for i in range(self.dimension)])
        tokens = sum(max(1, len(t) // 4) for t in texts)
        return vectors, Usage(tokens, 0, 0)


# --- провайдер с HTTP-интерфейсом, совместимым с OpenAI (DeepSeek) ------------------


class OpenAICompatibleProvider:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    @staticmethod
    def _body(request: ProviderRequest, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    @staticmethod
    def _usage(data: dict[str, Any]) -> Usage:
        usage = data.get("usage") or {}
        cached = usage.get("prompt_cache_hit_tokens")
        if cached is None:
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        return Usage(usage.get("prompt_tokens", 0), cached or 0, usage.get("completion_tokens", 0))

    @staticmethod
    def _raise_for(response: httpx.Response) -> None:
        if response.status_code in (408, 409, 429) or response.status_code >= 500:
            raise TransientProviderError(f"провайдер ответил {response.status_code}")
        if response.status_code >= 400:
            raise PermanentProviderError(f"провайдер ответил {response.status_code}")

    def generate(self, request: ProviderRequest) -> Completion:
        try:
            response = self._http.post(
                "/chat/completions",
                json=self._body(request, False),
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise TransientProviderError("таймаут") from exc
        except httpx.TransportError as exc:
            raise TransientProviderError(f"нет связи: {type(exc).__name__}") from exc
        self._raise_for(response)
        data = response.json()
        return Completion(data["choices"][0]["message"]["content"] or "", self._usage(data))

    def stream(self, request: ProviderRequest) -> Iterator[StreamChunk]:
        try:
            with self._http.stream(
                "POST",
                "/chat/completions",
                json=self._body(request, True),
                timeout=request.timeout_seconds,
            ) as response:
                self._raise_for(response)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    data = json.loads(payload)
                    if data.get("usage"):
                        yield StreamChunk(usage=self._usage(data))
                    for choice in data.get("choices", []):
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield StreamChunk(text=delta)
        except httpx.TimeoutException as exc:
            raise TransientProviderError("таймаут") from exc
        except httpx.TransportError as exc:
            raise TransientProviderError(f"обрыв: {type(exc).__name__}") from exc

    def embed(
        self, model: str, texts: list[str], timeout_seconds: float
    ) -> tuple[list[list[float]], Usage]:
        try:
            response = self._http.post(
                "/embeddings", json={"model": model, "input": texts}, timeout=timeout_seconds
            )
        except httpx.TimeoutException as exc:
            raise TransientProviderError("таймаут") from exc
        self._raise_for(response)
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"])]
        tokens = (data.get("usage") or {}).get("prompt_tokens", 0)
        return vectors, Usage(tokens, 0, 0)
