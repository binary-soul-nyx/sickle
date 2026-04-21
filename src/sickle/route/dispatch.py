from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ..memory import HistoryManager
from ..route.response import Response
from ..tools import parse_route_call
from .context import RequestContext
from .runner import Runner


@dataclass(slots=True)
class _RouteFrame:
    caller: str
    tool_call_id: str


@dataclass(slots=True)
class Dispatch:
    history: HistoryManager
    runner: Runner
    max_hops: int = 12

    async def run(self, ctx: RequestContext, initial_body: str) -> Response:
        self.history.append(
            ctx.entry_agent,
            {
                "role": "user",
                "content": initial_body,
            },
        )

        active_agent = ctx.entry_agent
        stack: list[_RouteFrame] = []
        hops = 0

        while hops < self.max_hops:
            hops += 1
            turn_result = await self.runner.run_turn(active_agent)
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": turn_result.content,
            }
            if turn_result.tool_calls:
                assistant_message["tool_calls"] = turn_result.tool_calls
            self.history.append(active_agent, assistant_message)

            route_call = self._try_extract_route(turn_result.tool_calls)
            if route_call is not None:
                if route_call.to not in self.runner.agents:
                    self.history.append(
                        active_agent,
                        {
                            "role": "tool",
                            "tool_call_id": route_call.id,
                            "content": json.dumps(
                                {
                                    "success": False,
                                    "error": f"unknown target agent: {route_call.to}",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    continue

                stack.append(_RouteFrame(caller=active_agent, tool_call_id=route_call.id))
                ctx.chain.append(route_call.to)
                self.history.append(
                    route_call.to,
                    {
                        "role": "user",
                        "content": route_call.content,
                    },
                )
                active_agent = route_call.to
                continue

            if not stack:
                if turn_result.content:
                    return Response.text_only(turn_result.content)
                return Response.empty()

            frame = stack.pop()
            tool_content = json.dumps(
                {
                    "success": True,
                    "result": {"content": turn_result.content or ""},
                },
                ensure_ascii=False,
            )
            self.history.append(
                frame.caller,
                {
                    "role": "tool",
                    "tool_call_id": frame.tool_call_id,
                    "content": tool_content,
                },
            )
            active_agent = frame.caller

        return Response.text_only("route loop exceeded hop limit")

    def _try_extract_route(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> Any | None:
        for tool_call in tool_calls:
            if tool_call.get("name") != "route":
                continue
            return parse_route_call(tool_call)
        return None
