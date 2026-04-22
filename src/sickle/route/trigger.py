from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CommandSpec:
    name: str
    aliases: tuple[str, ...] = ()
    min_args: int = 0
    max_args: int = -1


@dataclass(slots=True)
class CommandMatch:
    name: str
    args: list[str]
    raw_args: str
    matched_spec: CommandSpec


@dataclass(slots=True)
class MessageMatch:
    entry_agent: str
    body: str
    had_explicit_target: bool
    matched_trigger: str | None = None


@dataclass(slots=True)
class TriggerMatch:
    kind: str
    raw_text: str
    message: MessageMatch | None = None
    command: CommandMatch | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_COMMAND_SPECS: dict[str, CommandSpec] = {
    "cancel": CommandSpec(name="cancel", aliases=("c",), min_args=0, max_args=0),
    "clear": CommandSpec(name="clear", aliases=(), min_args=0, max_args=1),
    "agents": CommandSpec(name="agents", aliases=(), min_args=0, max_args=0),
    "reload": CommandSpec(name="reload", aliases=(), min_args=0, max_args=0),
    "mode": CommandSpec(name="mode", aliases=(), min_args=0, max_args=1),
    "help": CommandSpec(name="help", aliases=(), min_args=0, max_args=0),
}


def parse_trigger(
    raw_text: str,
    available_agents: set[str],
    command_specs: dict[str, CommandSpec] | None = None,
    target_aliases: dict[str, str] | None = None,
) -> TriggerMatch:
    text = raw_text.strip()
    if not text:
        return TriggerMatch(kind="empty", raw_text=raw_text)

    specs = command_specs or DEFAULT_COMMAND_SPECS
    command_match = _try_parse_command(text, specs)
    if command_match is not None:
        return TriggerMatch(kind="command", raw_text=raw_text, command=command_match)

    first_token, _, remainder = text.partition(" ")
    if first_token.startswith("@") and len(first_token) > 1:
        target_name = first_token[1:].lower()
        target_agent = _resolve_target_agent(
            target_name=target_name,
            available_agents=available_agents,
            target_aliases=target_aliases or {},
        )
        if target_agent is not None:
            body = remainder.strip()
            return TriggerMatch(
                kind="message",
                raw_text=raw_text,
                message=MessageMatch(
                    entry_agent=target_agent,
                    body=body,
                    had_explicit_target=True,
                    matched_trigger=first_token,
                ),
            )

    return TriggerMatch(
        kind="message",
        raw_text=raw_text,
        message=MessageMatch(
            entry_agent="orchestrator",
            body=text,
            had_explicit_target=False,
            matched_trigger=None,
        ),
    )


def _try_parse_command(text: str, specs: dict[str, CommandSpec]) -> CommandMatch | None:
    if not text.startswith("/"):
        return None

    token, _, raw_args = text[1:].partition(" ")
    command_name = token.strip().lower()
    if not command_name:
        return None

    spec = _find_command_spec(command_name, specs)
    if spec is None:
        return None

    args = raw_args.split() if raw_args else []
    if len(args) < spec.min_args:
        return None
    if spec.max_args >= 0 and len(args) > spec.max_args:
        return None

    return CommandMatch(
        name=spec.name,
        args=args,
        raw_args=raw_args,
        matched_spec=spec,
    )


def _find_command_spec(
    command_name: str,
    specs: dict[str, CommandSpec],
) -> CommandSpec | None:
    direct = specs.get(command_name)
    if direct is not None:
        return direct

    for spec in specs.values():
        if command_name in spec.aliases:
            return spec
    return None


def _resolve_target_agent(
    target_name: str,
    available_agents: set[str],
    target_aliases: dict[str, str],
) -> str | None:
    mapped = target_aliases.get(target_name, target_name)
    if mapped in available_agents:
        return mapped
    return None
