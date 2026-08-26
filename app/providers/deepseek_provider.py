import json
import os
from dataclasses import dataclass, field
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class DeepSeekError(RuntimeError):
    pass


class RetryableDeepSeekError(DeepSeekError):
    pass


class TerminalDeepSeekError(DeepSeekError):
    pass


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str = field(repr=False)
    model: str
    base_url: str = "https://api.deepseek.com"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    max_tokens: int = 1800

    @classmethod
    def from_env(cls) -> "DeepSeekSettings":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        model = os.getenv("DEEPSEEK_MODEL", "").strip()
        if not api_key:
            raise TerminalDeepSeekError("DEEPSEEK_API_KEY is not set")
        if not model:
            raise TerminalDeepSeekError("DEEPSEEK_MODEL is not set")
        return cls(
            api_key=api_key,
            model=model,
            base_url=os.getenv(
                "DEEPSEEK_BASE_URL",
                "https://api.deepseek.com",
            ).rstrip("/"),
            timeout_seconds=float(
                os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30")
            ),
            max_retries=min(
                max(int(os.getenv("DEEPSEEK_MAX_RETRIES", "2")), 0),
                3,
            ),
            max_tokens=min(
                max(int(os.getenv("DEEPSEEK_MAX_TOKENS", "1800")), 500),
                4000,
            ),
        )


@dataclass(frozen=True)
class ProviderOutput:
    payload: dict[str, Any]
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class DeepSeekProvider:
    def __init__(self, settings: DeepSeekSettings | None = None) -> None:
        self.settings = settings or DeepSeekSettings.from_env()
        self.client = OpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            timeout=self.settings.timeout_seconds,
            max_retries=0,
        )

    def _request(self, messages: list[dict[str, str]]) -> ProviderOutput:
        try:
            response = self.client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=self.settings.max_tokens,
                stream=False,
            )
        except (APIConnectionError, APITimeoutError) as error:
            raise RetryableDeepSeekError(type(error).__name__) from error
        except APIStatusError as error:
            if error.status_code in {429, 500, 502, 503, 504}:
                raise RetryableDeepSeekError(
                    f"DeepSeek HTTP {error.status_code}"
                ) from error
            raise TerminalDeepSeekError(
                f"DeepSeek HTTP {error.status_code}"
            ) from error

        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise TerminalDeepSeekError(
                f"unexpected finish_reason={choice.finish_reason}"
            )
        content = choice.message.content
        if not content or not content.strip():
            raise TerminalDeepSeekError("DeepSeek returned empty content")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise TerminalDeepSeekError("DeepSeek returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise TerminalDeepSeekError("DeepSeek JSON root must be object")

        usage = response.usage
        return ProviderOutput(
            payload=payload,
            model=response.model or self.settings.model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )

    def generate(self, messages: list[dict[str, str]]) -> ProviderOutput:
        retrying = Retrying(
            stop=stop_after_attempt(self.settings.max_retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception_type(RetryableDeepSeekError),
            reraise=True,
        )
        return retrying(self._request, messages)
