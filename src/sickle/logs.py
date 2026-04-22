from __future__ import annotations

import json
import logging
import os
from typing import Any

_REDACTED = "***XXX***"
_SENSITIVE_KEYWORDS = ("api_key", "token", "secret", "password", "authorization")


class _SickleOnlyDebugFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("sickle."):
            return True
        return record.levelno >= logging.WARNING


def configure_logging(level: str | None = None) -> None:
    effective_level = (level or os.getenv("SICKLE_LOG_LEVEL") or "INFO").upper()
    numeric_level = getattr(logging, effective_level, logging.INFO)

    logging.basicConfig(
        level=logging.NOTSET,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(_SickleOnlyDebugFilter())
    logging.getLogger("sickle").setLevel(numeric_level)


def get_logger(module: str) -> logging.Logger:
    return logging.getLogger(f"sickle.{module}")


def to_log_json(payload: Any, *, max_chars: int = 6000) -> str:
    redacted = redact_payload(payload)
    try:
        text = json.dumps(redacted, ensure_ascii=False, default=_json_fallback)
    except Exception:
        text = str(redacted)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...(truncated {len(text) - max_chars} chars)"


def summarize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        content = message.get("content")
        content_text = _content_to_text(content)
        item: dict[str, Any] = {
            "index": index,
            "role": message.get("role", ""),
            "content_preview": clip_text(content_text, max_chars=180),
            "content_length": len(content_text),
        }
        tool_calls = message.get("tool_calls") or []
        if isinstance(tool_calls, list) and tool_calls:
            item["tool_calls"] = summarize_tool_calls(tool_calls)
        summary.append(item)
    return summary


def summarize_tools(tools: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str):
                names.append(name)
                continue
        if isinstance(tool, dict) and isinstance(tool.get("name"), str):
            names.append(str(tool["name"]))
        else:
            names.append("<unknown>")
    return names


def summarize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function") if isinstance(call, dict) else None
        name = ""
        arguments: Any = None
        if isinstance(function, dict):
            name = str(function.get("name") or "")
            arguments = function.get("arguments")
        if not name:
            name = str(call.get("name") or "") if isinstance(call, dict) else ""
        if arguments is None and isinstance(call, dict):
            arguments = call.get("arguments")
        arguments_text = _content_to_text(arguments)
        result.append(
            {
                "id": str(call.get("id") or "") if isinstance(call, dict) else "",
                "name": name,
                "arguments_preview": clip_text(arguments_text, max_chars=180),
                "arguments_length": len(arguments_text),
            }
        )
    return result


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key).lower()
            if any(sensitive in key_text for sensitive in _SENSITIVE_KEYWORDS):
                redacted[str(key)] = _REDACTED
            else:
                redacted[str(key)] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return [redact_payload(item) for item in payload]
    return payload


def clip_text(text: str, *, max_chars: int = 180) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...(truncated)"


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list, tuple)):
        return to_log_json(content, max_chars=1200)
    return str(content)


def _json_fallback(value: Any) -> str:
    return str(value)
