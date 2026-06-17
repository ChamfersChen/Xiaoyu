from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xiaoyu.horizon.ai.client import XiaoyuAIClient
from xiaoyu.horizon.ai.tokens import get_usage_snapshot, reset_usage


@pytest.fixture(autouse=True)
def _reset_usage():
    reset_usage()
    yield


class _MockMessage:
    def __init__(self, content: str):
        self.content = content


class _MockChoice:
    def __init__(self, content: str):
        self.message = _MockMessage(content)


class _MockUsage:
    def __init__(self, prompt_tokens: int = 0, completion_tokens: int = 0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _MockResponse:
    def __init__(self, content: str = "", usage: _MockUsage | None = None):
        self.choices = [_MockChoice(content)]
        self.usage = usage


def _make_openai_mock(
    model_name: str = "gpt-4o-mini",
    model_params: dict | None = None,
    create_return: _MockResponse | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.model_name = model_name
    mock.model_params = model_params or {}
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=create_return or _MockResponse())
    mock.client = mock_client
    return mock


class TestComplete:
    """Tests for XiaoyuAIClient.complete()."""

    @pytest.mark.parametrize("content", ["Hello!", "", "   "])
    async def test_return_content(self, monkeypatch, content: str) -> None:
        response = _MockResponse(content=content)
        mock = _make_openai_mock(create_return=response)
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        result = await client.complete("sys", "user")

        assert result == content

    async def test_passes_messages(self, monkeypatch) -> None:
        mock = _make_openai_mock()
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        await client.complete("You are helpful", "Say hello")

        create = mock.client.chat.completions.create
        create.assert_awaited_once()
        assert create.await_args.kwargs["model"] == "gpt-4o-mini"
        assert create.await_args.kwargs["messages"] == [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Say hello"},
        ]

    async def test_temperature_override(self, monkeypatch) -> None:
        mock = _make_openai_mock(model_params={"temperature": 0.7})
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        await client.complete("sys", "user", temperature=0.2)

        params = mock.client.chat.completions.create.await_args.kwargs
        assert params["temperature"] == 0.2

    async def test_max_tokens_override(self, monkeypatch) -> None:
        mock = _make_openai_mock(model_params={"max_tokens": 1024})
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        await client.complete("sys", "user", max_tokens=512)

        params = mock.client.chat.completions.create.await_args.kwargs
        assert params["max_tokens"] == 512

    async def test_uses_default_model_params_when_no_override(self, monkeypatch) -> None:
        mock = _make_openai_mock(model_params={"temperature": 0.5, "max_tokens": 2048})
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        await client.complete("sys", "user")

        params = mock.client.chat.completions.create.await_args.kwargs
        assert params["temperature"] == 0.5
        assert params["max_tokens"] == 2048

    async def test_json_mode_injects_response_format(self, monkeypatch) -> None:
        mock = _make_openai_mock()
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini", json_mode=True)
        await client.complete("sys", "user")

        params = mock.client.chat.completions.create.await_args.kwargs
        assert params["response_format"] == {"type": "json_object"}

    async def test_json_mode_false_does_not_inject_response_format(self, monkeypatch) -> None:
        mock = _make_openai_mock()
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini", json_mode=False)
        await client.complete("sys", "user")

        params = mock.client.chat.completions.create.await_args.kwargs
        assert "response_format" not in params

    async def test_records_usage(self, monkeypatch) -> None:
        usage = _MockUsage(prompt_tokens=25, completion_tokens=100)
        response = _MockResponse(content="result", usage=usage)
        mock = _make_openai_mock(create_return=response)
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        await client.complete("sys", "user")

        snapshot = get_usage_snapshot()
        assert snapshot.total_input_tokens == 25
        assert snapshot.total_output_tokens == 100
        assert "openai:gpt-4o-mini" in snapshot.per_provider

    async def test_handles_missing_usage_gracefully(self, monkeypatch) -> None:
        response = _MockResponse(content="result", usage=None)
        mock = _make_openai_mock(create_return=response)
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        result = await client.complete("sys", "user")

        assert result == "result"
        snapshot = get_usage_snapshot()
        assert snapshot.total_tokens == 0

    async def test_passes_model_param_copy_not_reference(self, monkeypatch) -> None:
        """Verify complete() copies model_params so caller can't mutate the original."""
        original = {"temperature": 0.5, "max_tokens": 1024}
        mock = _make_openai_mock(model_params=original)
        monkeypatch.setattr("xiaoyu.models.chat.select_model", lambda spec: mock)

        client = XiaoyuAIClient("openai:gpt-4o-mini")
        await client.complete("sys", "user", temperature=0.9)

        assert original["temperature"] == 0.5  # original unchanged
        assert original["max_tokens"] == 1024
