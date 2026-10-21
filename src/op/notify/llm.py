"""Minimal async client for an OpenAI-compatible chat endpoint.

Deliberately no SDK: the three calls we need (`/chat/completions` twice, `/models`
once) are less code than the dependency would be, and `httpx` is already a
dependency of this project. `op` and `op perms` never construct this client.
"""

from __future__ import annotations

import asyncio
import json
import re
import typing as T

import httpx

_JSON_FENCE_RE = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', flags=re.DOTALL)
_JSON_OBJECT_RE = re.compile(r'\{.*\}', flags=re.DOTALL)
_ERROR_BODY_CHARS = 500


class LlmError(Exception):
    """The model could be reached but did not deliver a usable answer."""


class LlmUnavailableError(LlmError):
    """The endpoint could not be reached at all (DNS, refused, timeout)."""


class LlmClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 180.0,
        parallel: int = 4,
        disable_thinking: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip('/')
        self._model = model
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._parallel = max(1, parallel)
        self._disable_thinking = disable_thinking
        self._http: httpx.AsyncClient | None = None
        self._slots: asyncio.Semaphore | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    async def __aenter__(self) -> LlmClient:
        headers = {'Content-Type': 'application/json'}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'
        self._http = httpx.AsyncClient(
            base_url=self._base_url, headers=headers, timeout=self._timeout
        )
        self._slots = asyncio.Semaphore(self._parallel)
        return self

    async def __aexit__(self, *_: T.Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._slots = None

    async def available_models(self) -> list[str]:
        """Model ids the server offers — used to fail early with a useful message."""
        data = await self._get('/models')
        entries = data.get('data') or []
        return [e.get('id', '') for e in entries if isinstance(e, dict)]

    async def complete_text(self, *, system: str, user: str) -> str:
        payload = self._payload(system, user)
        data = await self._post_chat(payload)
        return _content(data)

    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, T.Any], schema_name: str = 'answer'
    ) -> dict[str, T.Any]:
        """Ask for a JSON answer, with a fallback for servers without schema support.

        Not every OpenAI-compatible server implements `json_schema`; those answer
        400. Rather than requiring the user to configure which dialect their
        server speaks, we try the strict form and fall back to `json_object`.
        """
        payload = self._payload(system, user)
        payload['response_format'] = {
            'type': 'json_schema',
            'json_schema': {'name': schema_name, 'schema': schema, 'strict': True},
        }
        try:
            data = await self._post_chat(payload)
        except _SchemaUnsupported:
            payload['response_format'] = {'type': 'json_object'}
            data = await self._post_chat(payload)
        return _parse_json(_content(data))

    # --- internals --------------------------------------------------------

    def _payload(self, system: str, user: str) -> dict[str, T.Any]:
        payload: dict[str, T.Any] = {
            'model': self._model,
            'temperature': self._temperature,
            'max_tokens': self._max_tokens,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
        }
        if self._disable_thinking:
            # Understood by llama.cpp and vLLM; ignored by servers without a
            # thinking mode, so it is safe to send unconditionally when asked for.
            payload['chat_template_kwargs'] = {'enable_thinking': False}
        return payload

    async def _post_chat(self, payload: dict[str, T.Any]) -> dict[str, T.Any]:
        # One retry: local inference servers drop the occasional request while a
        # model is still warming up, and a rerun is cheaper than a failed group.
        last_error: LlmError | None = None
        for attempt in range(2):
            async with self._acquire():
                response = await self._send('POST', '/chat/completions', json=payload)
            if response.status_code == 400 and _mentions_response_format(response):
                raise _SchemaUnsupported()
            if response.status_code < 400:
                return response.json()
            last_error = LlmError(
                f'{self._base_url}/chat/completions returned {response.status_code}: '
                f'{response.text[:_ERROR_BODY_CHARS]}'
            )
            if response.status_code < 500 or attempt == 1:
                break
        raise last_error or LlmError('chat completion failed')

    async def _get(self, path: str) -> dict[str, T.Any]:
        response = await self._send('GET', path)
        if response.status_code >= 400:
            raise LlmError(
                f'{self._base_url}{path} returned {response.status_code}: '
                f'{response.text[:_ERROR_BODY_CHARS]}'
            )
        return response.json()

    async def _send(self, method: str, path: str, **kwargs: T.Any) -> httpx.Response:
        if self._http is None:
            raise LlmError('LLM client not opened — use `async with LlmClient(...)`')
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise LlmUnavailableError(
                f'Timeout ({self._timeout:g}s) bei {method} {self._base_url}{path}: {exc}'
            ) from exc
        except httpx.TransportError as exc:
            raise LlmUnavailableError(
                f'LLM nicht erreichbar — {method} {self._base_url}{path}: {exc}'
            ) from exc

    def _acquire(self) -> T.AsyncContextManager[T.Any]:
        if self._slots is None:
            raise LlmError('LLM client not opened — use `async with LlmClient(...)`')
        return self._slots


class _SchemaUnsupported(Exception):
    """Server rejected `response_format: json_schema` — internal control flow only."""


def _mentions_response_format(response: httpx.Response) -> bool:
    return 'response_format' in response.text or 'json_schema' in response.text


def _content(data: dict[str, T.Any]) -> str:
    try:
        choice = data['choices'][0]
        content = choice['message']['content'] or ''
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError(f'unexpected chat completion payload: {str(data)[:200]}') from exc

    if choice.get('finish_reason') == 'length':
        raise LlmError(_length_hint(choice))
    return content


def _length_hint(choice: dict[str, T.Any]) -> str:
    """Explain a truncated answer in terms of the two knobs that fix it."""
    thought = (choice.get('message') or {}).get('reasoning_content')
    if thought and not (choice.get('message') or {}).get('content'):
        return (
            'the model used the whole token budget for reasoning and never wrote an '
            'answer — raise max_tokens or set disable_thinking = true in [llm]'
        )
    return (
        'the answer was cut off before it was complete — raise max_tokens in [llm] '
        '(or set disable_thinking = true if the model reasons at length)'
    )


def _parse_json(content: str) -> dict[str, T.Any]:
    """Extract the JSON object from an answer that may carry prose around it."""
    for candidate in _json_candidates(content):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LlmError(f'no JSON object in model answer: {content[:200]!r}')


def _json_candidates(content: str) -> list[str]:
    stripped = content.strip()
    candidates = [stripped]
    fence = _JSON_FENCE_RE.search(content)
    if fence:
        candidates.append(fence.group(1))
    loose = _JSON_OBJECT_RE.search(content)
    if loose:
        candidates.append(loose.group(0))
    return candidates
