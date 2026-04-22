from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from ..errors import AgentBusyError
from ..logs import (
    clip_text,
    get_logger,
    summarize_tool_calls,
    to_log_json,
)
from ..memory import HistoryManager
from ..route.response import Response
from ..tools import SandboxExecutor, parse_execute_code_call, parse_route_call
from .context import RequestContext
from .runner import Runner

logger = get_logger("route.dispatch")


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
        request_id = str(ctx.request_id)
        logger.debug(
            "dispatch.run start request_id=%s user_id=%s entry_agent=%s initial_body=%s",
            request_id,
            ctx.user_id,
            ctx.entry_agent,
            clip_text(initial_body, max_chars=240),
        )
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
            logger.debug("dispatch.run operator_lock acquired request_id=%s", request_id)

        try:
            while hops < self.max_hops:
                hops += 1
                logger.debug(
                    "dispatch.run hop request_id=%s hop=%s active_agent=%s stack_depth=%s chain=%s",
                    request_id,
                    hops,
                    active_agent,
                    len(stack),
                    ctx.chain,
                )
                turn_result = await self.runner.run_turn(active_agent)
                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": turn_result.content,
                }
                if turn_result.tool_calls:
                    assistant_message["tool_calls"] = turn_result.tool_calls
                logger.debug(
                    "dispatch.run turn_result request_id=%s agent=%s content=%s tool_calls=%s",
                    request_id,
                    active_agent,
                    clip_text(turn_result.content or "", max_chars=240),
                    to_log_json(summarize_tool_calls(turn_result.tool_calls)),
                )
                self.history.append(active_agent, assistant_message)

                execute_call = self._try_extract_execute_code(turn_result.tool_calls)
                if execute_call is not None and active_agent == "operator":
                    logger.debug(
                        "dispatch.run execute_code request_id=%s tool_call_id=%s is_final=%s code=%s",
                        request_id,
                        execute_call.id,
                        execute_call.is_final,
                        clip_text(execute_call.code, max_chars=320),
                    )
                    exec_result = await self.sandbox_executor.execute(execute_call.code)
                    artifacts.extend(exec_result.artifacts)
                    tool_content = self._serialize_execute_result(exec_result)
                    logger.debug(
                        "dispatch.run execute_result request_id=%s success=%s artifacts=%s stdout=%s stderr=%s",
                        request_id,
                        exec_result.success,
                        len(exec_result.artifacts),
                        clip_text(exec_result.stdout, max_chars=240),
                        clip_text(exec_result.stderr, max_chars=240),
                    )
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
                        logger.warning(
                            "dispatch.run operator_failures_exceeded request_id=%s failures=%s",
                            request_id,
                            operator_failures,
                        )
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
                            logger.debug(
                                "dispatch.run return_failure_to_caller request_id=%s caller=%s tool_call_id=%s",
                                request_id,
                                frame.caller,
                                frame.tool_call_id,
                            )
                            active_agent = frame.caller
                            operator_failures = 0
                            continue
                        logger.debug(
                            "dispatch.run terminal_operator_failure request_id=%s",
                            request_id,
                        )
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
                        logger.debug(
                            "dispatch.run return_operator_result request_id=%s caller=%s tool_call_id=%s",
                            request_id,
                            frame.caller,
                            frame.tool_call_id,
                        )
                        active_agent = frame.caller
                        continue

                    # direct call: run operator for one more natural-language turn
                    logger.debug(
                        "dispatch.run operator_direct_mode request_id=%s",
                        request_id,
                    )
                    continue

                route_call = self._try_extract_route(turn_result.tool_calls)
                if route_call is not None:
                    if route_call.to not in self.runner.agents:
                        logger.warning(
                            "dispatch.run route_unknown_target request_id=%s from_agent=%s to_agent=%s",
                            request_id,
                            active_agent,
                            route_call.to,
                        )
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
                        logger.debug(
                            "dispatch.run operator_lock acquired_on_route request_id=%s",
                            request_id,
                        )

                    stack.append(_RouteFrame(caller=active_agent, tool_call_id=route_call.id))
                    ctx.chain.append(route_call.to)
                    logger.debug(
                        "dispatch.run route request_id=%s from_agent=%s to_agent=%s tool_call_id=%s content=%s",
                        request_id,
                        active_agent,
                        route_call.to,
                        route_call.id,
                        clip_text(route_call.content, max_chars=240),
                    )
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
                    logger.debug(
                        "dispatch.run final_without_stack request_id=%s has_content=%s artifacts=%s",
                        request_id,
                        bool(turn_result.content),
                        len(artifacts),
                    )
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
                logger.debug(
                    "dispatch.run bubble_result request_id=%s to_caller=%s tool_call_id=%s",
                    request_id,
                    frame.caller,
                    frame.tool_call_id,
                )
                active_agent = frame.caller

            logger.warning(
                "dispatch.run hop_limit_exceeded request_id=%s max_hops=%s",
                request_id,
                self.max_hops,
            )
            return Response(
                text="route loop exceeded hop limit",
                files=artifacts,
            )
        finally:
            if operator_lock_owned and self.operator_lock.locked():
                self.operator_lock.release()
                logger.debug("dispatch.run operator_lock released request_id=%s", request_id)

    def _try_extract_route(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> Any | None:
        for tool_call in tool_calls:
            if tool_call.get("name") != "route":
                continue
            try:
                return parse_route_call(tool_call)
            except Exception as exc:
                logger.warning(
                    "dispatch.parse route_failed raw=%s error=%s",
                    to_log_json(tool_call),
                    exc,
                )
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
            except Exception as exc:
                logger.warning(
                    "dispatch.parse execute_code_failed raw=%s error=%s",
                    to_log_json(tool_call),
                    exc,
                )
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
            logger.debug("dispatch.lock operator_busy")
            raise AgentBusyError("operator busy")
        await self.operator_lock.acquire()
