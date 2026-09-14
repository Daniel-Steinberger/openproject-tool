from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from op.notify.llm import LlmClient, LlmError, LlmUnavailableError

BASE = 'http://llm.example.com:8000/v1'
SCHEMA = {
    'type': 'object',
    'properties': {'classification': {'type': 'string'}},
    'required': ['classification'],
    'additionalProperties': False,
}


def _chat_response(content: str) -> dict:
    return {
        'id': 'chatcmpl-1',
        'object': 'chat.completion',
        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content},
                     'finish_reason': 'stop'}],
    }


@pytest.fixture
def client() -> LlmClient:
    return LlmClient(base_url=BASE, model='test-model', timeout=5.0, parallel=2)


class TestCompleteJson:
    async def test_sends_expected_request(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=_chat_response('{"classification": "churn"}'))
        )
        async with client:
            result = await client.complete_json(system='SYS', user='USR', schema=SCHEMA)
        assert result == {'classification': 'churn'}

        body = json.loads(route.calls.last.request.content)
        assert body['model'] == 'test-model'
        assert body['temperature'] == 0.2
        assert body['messages'] == [
            {'role': 'system', 'content': 'SYS'},
            {'role': 'user', 'content': 'USR'},
        ]
        assert body['response_format']['type'] == 'json_schema'
        assert body['response_format']['json_schema']['schema'] == SCHEMA

    async def test_falls_back_to_json_object_when_schema_rejected(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        responses = [
            httpx.Response(400, json={'error': {'message': 'response_format not supported'}}),
            httpx.Response(200, json=_chat_response('{"classification": "relevant"}')),
        ]
        route = respx_mock.post(f'{BASE}/chat/completions').mock(side_effect=responses)
        async with client:
            result = await client.complete_json(system='SYS', user='USR', schema=SCHEMA)
        assert result == {'classification': 'relevant'}
        assert json.loads(route.calls[1].request.content)['response_format'] == {
            'type': 'json_object'
        }

    async def test_parses_json_wrapped_in_a_code_fence(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(
                200,
                json=_chat_response('Hier das Ergebnis:\n```json\n{"classification": "churn"}\n```'),
            )
        )
        async with client:
            assert await client.complete_json(system='S', user='U', schema=SCHEMA) == {
                'classification': 'churn'
            }

    async def test_unparsable_answer_raises(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=_chat_response('kein JSON weit und breit'))
        )
        async with client:
            with pytest.raises(LlmError):
                await client.complete_json(system='S', user='U', schema=SCHEMA)

    async def test_server_error_is_retried_once_then_raises(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(500, text='boom')
        )
        async with client:
            with pytest.raises(LlmError):
                await client.complete_json(system='S', user='U', schema=SCHEMA)
        assert route.call_count == 2

    async def test_transport_error_names_the_host(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post(f'{BASE}/chat/completions').mock(
            side_effect=httpx.ConnectError('connection refused')
        )
        async with client:
            with pytest.raises(LlmUnavailableError) as excinfo:
                await client.complete_json(system='S', user='U', schema=SCHEMA)
        assert 'llm.example.com' in str(excinfo.value)


class TestCompleteText:
    async def test_returns_plain_content(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=_chat_response('## Bericht\n\nAlles ruhig.'))
        )
        async with client:
            assert await client.complete_text(system='S', user='U') == '## Bericht\n\nAlles ruhig.'


class TestAuthAndModels:
    async def test_no_authorization_header_without_key(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=_chat_response('{"classification": "churn"}'))
        )
        async with client:
            await client.complete_json(system='S', user='U', schema=SCHEMA)
        assert 'authorization' not in route.calls.last.request.headers

    async def test_bearer_header_with_key(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=_chat_response('{"classification": "churn"}'))
        )
        async with LlmClient(base_url=BASE, model='m', api_key='secret') as client:
            await client.complete_json(system='S', user='U', schema=SCHEMA)
        assert route.calls.last.request.headers['authorization'] == 'Bearer secret'

    async def test_available_models(self, client: LlmClient, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f'{BASE}/models').mock(
            return_value=httpx.Response(200, json={'data': [{'id': 'test-model'}, {'id': 'other'}]})
        )
        async with client:
            assert await client.available_models() == ['test-model', 'other']

    async def test_available_models_unreachable(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE}/models').mock(side_effect=httpx.ConnectError('nope'))
        async with client:
            with pytest.raises(LlmUnavailableError):
                await client.available_models()


class TestParallelism:
    async def test_never_exceeds_configured_parallelism(
        self, respx_mock: respx.MockRouter
    ) -> None:
        in_flight = 0
        peak = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return httpx.Response(200, json=_chat_response('{"classification": "churn"}'))

        respx_mock.post(f'{BASE}/chat/completions').mock(side_effect=handler)
        async with LlmClient(base_url=BASE, model='m', parallel=2) as client:
            await asyncio.gather(*(
                client.complete_json(system='S', user=f'U{i}', schema=SCHEMA) for i in range(6)
            ))
        assert peak <= 2


class TestReasoningModels:
    async def test_thinking_not_disabled_by_default(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=_chat_response('{"classification": "churn"}'))
        )
        async with client:
            await client.complete_json(system='S', user='U', schema=SCHEMA)
        assert 'chat_template_kwargs' not in json.loads(route.calls.last.request.content)

    async def test_disable_thinking_is_sent(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=_chat_response('{"classification": "churn"}'))
        )
        async with LlmClient(base_url=BASE, model='m', disable_thinking=True) as client:
            await client.complete_json(system='S', user='U', schema=SCHEMA)
        body = json.loads(route.calls.last.request.content)
        assert body['chat_template_kwargs'] == {'enable_thinking': False}

    async def test_budget_exhausted_by_reasoning_is_explained(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        """A reasoning model can burn the whole budget before writing an answer."""
        payload = {
            'choices': [{
                'index': 0,
                'finish_reason': 'length',
                'message': {'role': 'assistant', 'content': '',
                            'reasoning_content': 'denkt und denkt und denkt'},
            }],
        }
        respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=payload)
        )
        async with client:
            with pytest.raises(LlmError) as excinfo:
                await client.complete_json(system='S', user='U', schema=SCHEMA)
        message = str(excinfo.value).lower()
        assert 'max_tokens' in message
        assert 'disable_thinking' in message

    async def test_truncated_answer_without_reasoning_is_reported_as_such(
        self, client: LlmClient, respx_mock: respx.MockRouter
    ) -> None:
        payload = {
            'choices': [{
                'index': 0,
                'finish_reason': 'length',
                'message': {'role': 'assistant', 'content': '{"classification": "chu'},
            }],
        }
        respx_mock.post(f'{BASE}/chat/completions').mock(
            return_value=httpx.Response(200, json=payload)
        )
        async with client:
            with pytest.raises(LlmError) as excinfo:
                await client.complete_json(system='S', user='U', schema=SCHEMA)
        assert 'max_tokens' in str(excinfo.value).lower()
