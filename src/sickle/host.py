from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .agents import Agent, OperatorAgent, OrchestratorAgent
from .config import AppConfig
from .errors import AgentBusyError
from .llm import LLMClient
from .memory import HistoryManager
from .route import (
    DEFAULT_COMMAND_SPECS,
    Dispatch,
    RequestContext,
    Runner,
    parse_trigger,
)
from .route.response import Response
from .tools import SandboxExecutor


@dataclass(slots=True)
class _UserRuntime:
    history: HistoryManager
    runner: Runner
    dispatch: Dispatch
    operator_lock: asyncio.Lock
    active_task: asyncio.Task[Any] | None = None
    active_snapshot: dict[str, int] | None = None


@dataclass(slots=True)
class Sickle:
    config: AppConfig
    llm_client: Any | None = None
    extra_agents: dict[str, Agent] | None = None
    allowed_user_ids: set[int] = field(init=False, default_factory=set)
    history: HistoryManager = field(init=False)
    orchestrator: OrchestratorAgent = field(init=False)
    agents: dict[str, Agent] = field(init=False, default_factory=dict)
    _user_runtimes: dict[int, _UserRuntime] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.allowed_user_ids = set(self.config.telegram.allowed_user_ids)
        self.history = HistoryManager()
        if self.llm_client is None:
            self.llm_client = LLMClient(
                default_model=self.config.llm.default_model,
                timeout=self.config.llm.timeout,
                retry=self.config.llm.retry,
                api_base=self.config.llm.api_base,
                api_key=self.config.llm.api_key,
            )
        operator = OperatorAgent(
            llm_client=self.llm_client,
            model=self.config.llm.default_model,
        )
        extra_agents = self.extra_agents or {}
        routable_agents = sorted({"operator", *extra_agents.keys()})
        self.orchestrator = OrchestratorAgent(
            llm_client=self.llm_client,
            model=self.config.llm.default_model,
            routable_agents=routable_agents,
        )
        self.agents = {
            "orchestrator": self.orchestrator,
            "operator": operator,
            **extra_agents,
        }
        self.history = HistoryManager()

    def _is_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_user_ids

    def get_history(self, user_id: int) -> HistoryManager:
        runtime = self._get_user_runtime(user_id)
        self.history = runtime.history
        return runtime.history

    async def handle_message(self, user_id: int, text: str) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()
        runtime = self._get_user_runtime(user_id)
        self.history = runtime.history

        trigger = parse_trigger(
            text,
            available_agents=set(self.agents.keys()),
            target_aliases={"op": "operator"},
        )
        if trigger.kind == "empty":
            return Response.empty()
        if trigger.kind == "command" and trigger.command is not None:
            return await self.handle_command(
                user_id=user_id,
                cmd=trigger.command.name,
                args=trigger.command.args,
            )
        if trigger.message is None:
            return Response.empty()

        snapshot = runtime.history.snapshot()
        current_task = asyncio.current_task()
        if (
            current_task is not None
            and (runtime.active_task is None or runtime.active_task.done())
        ):
            runtime.active_task = current_task
            runtime.active_snapshot = snapshot

        ctx = RequestContext.create(
            user_id=user_id,
            entry_agent=trigger.message.entry_agent,
        )
        try:
            return await runtime.dispatch.run(ctx, trigger.message.body)
        except AgentBusyError:
            runtime.history.rollback(snapshot)
            return Response.text_only("操作员正忙，请稍后再试")
        except asyncio.CancelledError:
            runtime.history.rollback(snapshot)
            return Response.empty()
        except Exception:
            runtime.history.rollback(snapshot)
            return Response.text_only("请求处理失败，请稍后重试")
        finally:
            if runtime.active_task is current_task:
                runtime.active_task = None
                runtime.active_snapshot = None

    async def handle_command(
        self,
        user_id: int,
        cmd: str,
        args: list[str],
    ) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()
        runtime = self._get_user_runtime(user_id)
        self.history = runtime.history
        if cmd == "cancel":
            task = runtime.active_task
            snapshot = runtime.active_snapshot
            current_task = asyncio.current_task()
            if task is not None and not task.done() and task is not current_task:
                task.cancel()
                if snapshot is not None:
                    runtime.history.rollback(snapshot)
                runtime.active_task = None
                runtime.active_snapshot = None
            return Response.empty()
        if cmd == "clear":
            agent_name = args[0] if args else "orchestrator"
            runtime.history.clear(agent_name)
            return Response.text_only("ok")
        if cmd == "agents":
            return Response.text_only("\n".join(sorted(self.agents.keys())))
        if cmd == "help":
            names = ", ".join(sorted(DEFAULT_COMMAND_SPECS.keys()))
            return Response.text_only(f"available commands: {names}")
        return Response.text_only("ok")

    async def handle_button(self, user_id: int, callback_id: str) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()
        return Response.empty()

    def _get_user_runtime(self, user_id: int) -> _UserRuntime:
        runtime = self._user_runtimes.get(user_id)
        if runtime is not None:
            return runtime

        history = HistoryManager()
        operator_lock = asyncio.Lock()
        runner = Runner(agents=self.agents, history=history)
        dispatch = Dispatch(
            history=history,
            runner=runner,
            sandbox_executor=SandboxExecutor(
                exec_timeout=float(self.config.operator.exec_timeout),
                large_output_threshold=self.config.operator.large_output_threshold,
            ),
            operator_lock=operator_lock,
            max_operator_failures=self.config.operator.max_consecutive_failures,
        )
        runtime = _UserRuntime(
            history=history,
            runner=runner,
            dispatch=dispatch,
            operator_lock=operator_lock,
        )
        self._user_runtimes[user_id] = runtime
        return runtime
