from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

from .errors import ConfigError


@dataclass(slots=True)
class TelegramConfig:
    bot_token: str = ""
    allowed_user_ids: set[int] = field(default_factory=set)


@dataclass(slots=True)
class LLMConfig:
    default_model: str = "gpt-4o-mini"
    timeout: int = 60
    retry: int = 3
    api_base: str | None = None
    api_key: str | None = None


@dataclass(slots=True)
class OperatorConfig:
    exec_timeout: int = 30
    max_consecutive_failures: int = 3
    large_output_threshold: int = 1000


@dataclass(slots=True)
class AgentsConfig:
    sleep_check_hour: int = 3
    default_sleep_after_days: int = 7


@dataclass(slots=True)
class AppConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    operator: OperatorConfig = field(default_factory=OperatorConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    log_level: str = "INFO"


def _parse_allowed_user_ids(value: Any) -> set[int]:
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ConfigError("telegram.allowed_user_ids must be a list of integers")

    ids: set[int] = set()
    for user_id in value:
        if not isinstance(user_id, int):
            raise ConfigError("telegram.allowed_user_ids must be a list of integers")
        ids.add(user_id)
    return ids


def _optional_non_empty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def load_config(path: str | Path = "config.toml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc

    telegram_raw = raw.get("telegram", {})
    llm_raw = raw.get("llm", {})
    operator_raw = raw.get("operator", {})
    agents_raw = raw.get("agents", {})
    logging_raw = raw.get("logging", {})

    if not isinstance(telegram_raw, dict):
        raise ConfigError("[telegram] must be a table")
    if not isinstance(llm_raw, dict):
        raise ConfigError("[llm] must be a table")
    if not isinstance(operator_raw, dict):
        raise ConfigError("[operator] must be a table")
    if not isinstance(agents_raw, dict):
        raise ConfigError("[agents] must be a table")
    if not isinstance(logging_raw, dict):
        raise ConfigError("[logging] must be a table")

    telegram = TelegramConfig(
        bot_token=str(telegram_raw.get("bot_token", "")),
        allowed_user_ids=_parse_allowed_user_ids(
            telegram_raw.get("allowed_user_ids", []),
        ),
    )
    llm = LLMConfig(
        default_model=str(llm_raw.get("default_model", "gpt-4o-mini")),
        timeout=int(llm_raw.get("timeout", 60)),
        retry=int(llm_raw.get("retry", 3)),
        api_base=_optional_non_empty_str(llm_raw.get("api_base")),
        api_key=_optional_non_empty_str(llm_raw.get("api_key")),
    )
    operator = OperatorConfig(
        exec_timeout=int(operator_raw.get("exec_timeout", 30)),
        max_consecutive_failures=int(
            operator_raw.get("max_consecutive_failures", 3),
        ),
        large_output_threshold=int(operator_raw.get("large_output_threshold", 1000)),
    )
    agents = AgentsConfig(
        sleep_check_hour=int(agents_raw.get("sleep_check_hour", 3)),
        default_sleep_after_days=int(agents_raw.get("default_sleep_after_days", 7)),
    )
    log_level = str(logging_raw.get("level", "INFO")).upper()

    return AppConfig(
        telegram=telegram,
        llm=llm,
        operator=operator,
        agents=agents,
        log_level=log_level,
    )
