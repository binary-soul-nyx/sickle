from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from ..errors import AgentBusyError
from ..memory import HistoryManager
from ..route.response import Response
from ..tools import SandboxExecutor, parse_execute_code_call, parse_route_call
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
    sandbox_executor: SandboxExecutor = field(default_factory=SandboxExecutor)
    operator_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    max_operator_failures: int = 3
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
        artifacts: list[Path] = []
        operator_failures = 0
        operator_lock_owned = False
        hops = 0

        if active_agent == "operator":
            await self._acquire_operator_lock()
            operator_lock_owned = True

        try:
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

                execute_call = self._try_extract_execute_code(turn_result.tool_calls)
                if execute_call is not None and active_agent == "operator":
                    exec_result = await self.sandbox_executor.execute(execute_call.code)
                    artifacts.extend(exec_result.artifacts)
                    tool_content = self._serialize_execute_result(exec_result)
                    self.history.append(
                        "operator",
                        {
                            "role": "tool",
                            "tool_call_id": execute_call.id,
                            "content": tool_content,
                        },
                    )

                    if exec_result.success:
                        operator_failures = 0
                    else:
                        operator_failures += 1

                    if operator_failures >= self.max_operator_failures:
                        payload = json.dumps(
                            {
                                "success": False,
                                "error": "operator repeated failures",
                                "stderr": exec_result.stderr,
                            },
                            ensure_ascii=False,
                        )
                        if stack:
                            frame = stack.pop()
                            self._append_operator_closing_message()
                            self.history.append(
                                frame.caller,
                                {
                                    "role": "tool",
                                    "tool_call_id": frame.tool_call_id,
                                    "content": payload,
                                },
                            )
                            active_agent = frame.caller
                            operator_failures = 0
                            continue
                        return Response(
                            text="operator repeated failures",
                            files=artifacts,
                        )

                    if not execute_call.is_final:
                        continue

                    if stack:
                        frame = stack.pop()
                        self._append_operator_closing_message()
                        self.history.append(
                            frame.caller,
                            {
                                "role": "tool",
                                "tool_call_id": frame.tool_call_id,
                                "content": tool_content,
                            },
                        )
                        active_agent = frame.caller
                        continue

                    # direct call: run operator for one more natural-language turn
                    continue

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

                    if route_call.to == "operator" and not operator_lock_owned:
                        await self._acquire_operator_lock()
                        operator_lock_owned = True

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
                        return Response(text=turn_result.content, files=artifacts)
                    if artifacts:
                        return Response(files=artifacts)
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

            return Response(
                text="route loop exceeded hop limit",
                files=artifacts,
            )
        finally:
            if operator_lock_owned and self.operator_lock.locked():
                self.operator_lock.release()

    def _try_extract_route(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> Any | None:
        for tool_call in tool_calls:
            if tool_call.get("name") != "route":
                continue
            try:
                return parse_route_call(tool_call)
            except Exception:
                return None
        return None

    def _try_extract_execute_code(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> Any | None:
        for tool_call in tool_calls:
            if tool_call.get("name") != "execute_code":
                continue
            try:
                return parse_execute_code_call(tool_call)
            except Exception:
                return None
        return None

    def _serialize_execute_result(self, exec_result: Any) -> str:
        return json.dumps(
            {
                "success": exec_result.success,
                "result": exec_result.result,
                "stdout": exec_result.stdout,
                "stderr": exec_result.stderr,
            },
            ensure_ascii=False,
        )

    def _append_operator_closing_message(self) -> None:
        self.history.append(
            "operator",
            {
                "role": "assistant",
                "content": "",
            },
        )

    async def _acquire_operator_lock(self) -> None:
        if self.operator_lock.locked():
            raise AgentBusyError("operator busy")
        await self.operator_lock.acquire()
