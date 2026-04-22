from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from ..errors import LLMUnavailable
from ..logs import (
    clip_text,
    get_logger,
    summarize_messages,
    summarize_tool_calls,
    summarize_tools,
    to_log_json,
)

logger = get_logger("llm.client")


@dataclass(slots=True)
class LLMResponse:
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None


class LLMClient:
    def __init__(
        self,
        default_model: str,
        timeout: int = 60,
        retry: int = 3,
        api_base: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.default_model = default_model
        self.timeout = timeout
        self.retry = retry
        self.api_base = api_base
        self.api_key = api_key

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        target_model = model or self.default_model
        tools_list = tools or []
        logger.debug(
            "llm.chat start model=%s timeout=%s retry=%s api_base=%s has_api_key=%s tools=%s messages=%s",
            target_model,
            self.timeout,
            self.retry,
            self.api_base or "",
            bool(self.api_key),
            summarize_tools(tools_list),
            to_log_json(summarize_messages(messages)),
        )

        try:
            result = await self._chat_with_retry(target_model, messages, tools_list)
            logger.debug(
                "llm.chat done model=%s content=%s tool_calls=%s",
                target_model,
                clip_text(result.content or "", max_chars=220),
                to_log_json(summarize_tool_calls(result.tool_calls)),
            )
            return result
        except LLMUnavailable:
            logger.exception("llm.chat unavailable model=%s", target_model)
            raise
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception("llm.chat unexpected_error model=%s", target_model)
            raise LLMUnavailable(str(exc)) from exc

    async def _chat_with_retry(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        try:
            from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential
        except ImportError:
            return await self._chat_with_manual_retry(model, messages, tools)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.retry),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            reraise=True,
        ):
            with attempt:
                logger.debug(
                    "llm.retry attempt=%s model=%s",
                    attempt.retry_state.attempt_number,
                    model,
                )
                raw_response = await self._run_completion(
                    model=model,
                    messages=messages,
                    tools=tools,
                )
                return self._normalize_response(raw_response)

        raise LLMUnavailable("LLM retry exhausted")

    async def _chat_with_manual_retry(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        last_error: Exception | None = None
        for attempt in range(1, self.retry + 1):
            try:
                logger.debug("llm.manual_retry attempt=%s model=%s", attempt, model)
                raw_response = await self._run_completion(
                    model=model,
                    messages=messages,
                    tools=tools,
                )
                return self._normalize_response(raw_response)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm.manual_retry failed attempt=%s/%s model=%s error=%s",
                    attempt,
                    self.retry,
                    model,
                    exc,
                )
                if attempt == self.retry:
                    break
                await asyncio.sleep(min(2 ** (attempt - 1), 8))

        logger.error(
            "llm.manual_retry exhausted model=%s attempts=%s last_error=%s",
            model,
            self.retry,
            last_error,
        )
        raise LLMUnavailable(str(last_error) if last_error else "LLM retry exhausted")

    async def _run_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        try:
            from litellm import acompletion
        except ImportError as exc:
            raise LLMUnavailable("litellm is not installed") from exc

        kwargs = self._build_completion_kwargs(model=model, messages=messages, tools=tools)
        logger.debug("llm.request payload=%s", to_log_json(kwargs, max_chars=12000))
        raw = await acompletion(**kwargs)
        logger.debug("llm.response raw=%s", to_log_json(raw, max_chars=12000))
        return raw

    def _build_completion_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "timeout": self.timeout,
        }
        if tools:
            kwargs["tools"] = tools
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return kwargs

    def _normalize_response(self, raw_response: Any) -> LLMResponse:
        message = self._extract_message(raw_response)
        content = self._get_field(message, "content")
        tool_calls_raw = self._get_field(message, "tool_calls") or []
        logger.debug(
            "llm.parse message content=%s raw_tool_calls=%s",
            clip_text(str(content) if content is not None else "", max_chars=220),
            to_log_json(tool_calls_raw),
        )
        tool_calls = [self._normalize_tool_call(item) for item in tool_calls_raw]
        logger.debug(
            "llm.parse normalized_tool_calls=%s",
            to_log_json(summarize_tool_calls(tool_calls)),
        )
        return LLMResponse(content=content, tool_calls=tool_calls, raw=raw_response)

    def _extract_message(self, raw_response: Any) -> Any:
        choices = self._get_field(raw_response, "choices")
        if not choices:
            return {}

        first_choice = choices[0]
        message = self._get_field(first_choice, "message")
        return message or {}

    def _normalize_tool_call(self, raw_call: Any) -> dict[str, Any]:
        call_id = self._get_field(raw_call, "id") or ""
        function = self._get_field(raw_call, "function") or {}
        name = self._get_field(raw_call, "name") or self._get_field(function, "name") or ""
        arguments = self._get_field(raw_call, "arguments")
        if arguments is None:
            arguments = self._get_field(function, "arguments")

        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        elif arguments is None:
            arguments = "{}"
        else:
            arguments = str(arguments)

        normalized = {
            "id": str(call_id),
            "type": "function",
            "function": {
                "name": str(name),
                "arguments": arguments,
            },
            "name": str(name),
            "arguments": arguments,
            "source": "native",
            "metadata": {},
        }
        logger.debug("llm.parse normalize_tool_call value=%s", to_log_json(normalized))
        return normalized

    def _get_field(self, obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)
