from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


@dataclass(slots=True)
class RouteCall:
    id: str
    kind: str
    to: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def build_route_tool_schema(routable_agents: list[str]) -> dict[str, Any]:
    unique_agents = sorted(set(routable_agents))
    return {
        "type": "function",
        "function": {
            "name": "route",
            "description": "Route a task to another specialist agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "enum": unique_agents,
                        "description": "The target agent name.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Task content to send to target agent.",
                    },
                },
                "required": ["to", "content"],
                "additionalProperties": False,
            },
        },
    }


def parse_route_call(tool_call: dict[str, Any]) -> RouteCall:
    if tool_call.get("name") != "route":
        raise ValueError("tool call is not route")

    raw_arguments = tool_call.get("arguments", "{}")
    if not isinstance(raw_arguments, str):
        raise ValueError("route arguments must be a JSON string")

    payload = json.loads(raw_arguments)
    to = payload.get("to")
    content = payload.get("content")
    if not isinstance(to, str) or not to:
        raise ValueError("route.to must be a non-empty string")
    if not isinstance(content, str):
        raise ValueError("route.content must be a string")

    return RouteCall(
        id=str(tool_call.get("id", "")),
        kind="route",
        to=to,
        content=content,
        metadata=dict(tool_call.get("metadata", {})),
    )
