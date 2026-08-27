from types import SimpleNamespace
from typing import Any

from app.providers.deepseek_provider import (
    DeepSeekProvider,
    DeepSeekSettings,
)


def test_settings_disable_thinking_by_default(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "DEEPSEEK_API_KEY",
        "test-key",
    )
    monkeypatch.setenv(
        "DEEPSEEK_MODEL",
        "deepseek-v4-flash",
    )
    monkeypatch.delenv(
        "DEEPSEEK_THINKING_ENABLED",
        raising=False,
    )
    monkeypatch.delenv(
        "DEEPSEEK_MAX_TOKENS",
        raising=False,
    )

    settings = DeepSeekSettings.from_env()

    assert settings.thinking_enabled is False
    assert settings.max_tokens == 2400


def test_settings_can_enable_thinking(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "DEEPSEEK_API_KEY",
        "test-key",
    )
    monkeypatch.setenv(
        "DEEPSEEK_MODEL",
        "deepseek-v4-flash",
    )
    monkeypatch.setenv(
        "DEEPSEEK_THINKING_ENABLED",
        "true",
    )

    settings = DeepSeekSettings.from_env()

    assert settings.thinking_enabled is True


def test_request_sends_thinking_disabled() -> None:
    captured: dict[str, Any] = {}

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)

            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            content=(
                                '{"incident_id":'
                                '"inc-test"}'
                            )
                        ),
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                ),
                model="deepseek-v4-flash",
            )

    provider = object.__new__(
        DeepSeekProvider
    )
    provider.settings = DeepSeekSettings(
        api_key="test-key",
        model="deepseek-v4-flash",
        thinking_enabled=False,
    )
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FakeCompletions()
        )
    )

    output = provider.generate(
        [
            {
                "role": "user",
                "content": "output json",
            }
        ]
    )

    assert captured["extra_body"] == {
        "thinking": {
            "type": "disabled",
        }
    }
    assert captured["max_tokens"] == 2400
    assert output.total_tokens == 120
