from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .agents import Agent, OperatorAgent, OrchestratorAgent
from .config import AppConfig
from .errors import AgentBusyError
from .llm import LLMClient
from .logs import clip_text, get_logger
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

logger = get_logger("host")


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
        logger.debug(
            "host.init allowed_users=%s",
            sorted(self.allowed_user_ids),
        )
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
        logger.debug("host.init agents=%s", sorted(self.agents.keys()))
        self.history = HistoryManager()
        logger.info(
            "host.init model=%s agents=%s allowed_users=%s",
            self.config.llm.default_model,
            sorted(self.agents.keys()),
            len(self.allowed_user_ids),
        )

    def _is_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_user_ids

    def get_history(self, user_id: int) -> HistoryManager:
        runtime = self._get_user_runtime(user_id)
        self.history = runtime.history
        return runtime.history

    async def handle_message(self, user_id: int, text: str) -> Response:
        if not self._is_allowed(user_id):
            logger.warning("host.handle_message rejected user_id=%s reason=not_allowed", user_id)
            return Response.empty()
        runtime = self._get_user_runtime(user_id)
        self.history = runtime.history
        logger.info("host.handle_message user_id=%s text_len=%s", user_id, len(text))
        logger.debug(
            "host.handle_message received user_id=%s text=%s",
            user_id,
            clip_text(text, max_chars=260),
        )

        trigger = parse_trigger(
            text,
            available_agents=set(self.agents.keys()),
            target_aliases={"op": "operator"},
        )
        logger.debug(
            "host.handle_message trigger user_id=%s kind=%s entry_agent=%s command=%s",
            user_id,
            trigger.kind,
            trigger.message.entry_agent if trigger.message else None,
            trigger.command.name if trigger.command else None,
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
        logger.debug(
            "host.handle_message snapshot user_id=%s snapshot=%s", user_id, snapshot
        )
        current_task = asyncio.current_task()
        if current_task is not None and (
            runtime.active_task is None or runtime.active_task.done()
        ):
            runtime.active_task = current_task
            runtime.active_snapshot = snapshot

        ctx = RequestContext.create(
            user_id=user_id,
            entry_agent=trigger.message.entry_agent,
        )
        logger.debug(
            "host.handle_message dispatch_start user_id=%s request_id=%s entry_agent=%s",
            user_id,
            ctx.request_id,
            ctx.entry_agent,
        )
        try:
            response = await runtime.dispatch.run(ctx, trigger.message.body)
            logger.debug(
                "host.handle_message dispatch_done user_id=%s request_id=%s text=%s files=%s",
                user_id,
                ctx.request_id,
                clip_text(response.text or "", max_chars=200),
                len(response.files),
            )
            logger.info(
                "host.handle_message done user_id=%s request_id=%s has_text=%s files=%s flow=%s",
                user_id,
                ctx.request_id,
                bool(response.text),
                len(response.files),
                "→".join(ctx.chain) if ctx.chain else ctx.entry_agent,
            )
            return response
        except AgentBusyError:
            runtime.history.rollback(snapshot)
            logger.warning(
                "host.handle_message dispatch_busy user_id=%s request_id=%s snapshot_rollback=true",
                user_id,
                ctx.request_id,
            )
            return Response.text_only("操作员正忙，请稍后再试")
        except asyncio.CancelledError:
            runtime.history.rollback(snapshot)
            logger.warning(
                "host.handle_message dispatch_cancelled user_id=%s request_id=%s snapshot_rollback=true",
                user_id,
                ctx.request_id,
            )
            return Response.empty()
        except Exception:
            runtime.history.rollback(snapshot)
            logger.exception(
                "host.handle_message dispatch_failed user_id=%s request_id=%s snapshot_rollback=true",
                user_id,
                ctx.request_id,
            )
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
            logger.warning(
                "host.handle_command rejected user_id=%s cmd=%s reason=not_allowed",
                user_id,
                cmd,
            )
            return Response.empty()
        runtime = self._get_user_runtime(user_id)
        self.history = runtime.history
        logger.debug(
            "host.handle_command user_id=%s cmd=%s args=%s",
            user_id,
            cmd,
            args,
        )
        if cmd == "cancel":
            task = runtime.active_task
            snapshot = runtime.active_snapshot
            current_task = asyncio.current_task()
            if task is not None and not task.done() and task is not current_task:
                task.cancel()
                if snapshot is not None:
                    runtime.history.rollback(snapshot)
                logger.debug(
                    "host.handle_command cancel_applied user_id=%s had_snapshot=%s",
                    user_id,
                    snapshot is not None,
                )
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
            logger.warning("host.handle_button rejected user_id=%s reason=not_allowed", user_id)
            return Response.empty()
        logger.debug(
            "host.handle_button user_id=%s callback_id=%s",
            user_id,
            callback_id,
        )
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
        logger.debug("host.runtime created user_id=%s", user_id)
        return runtime
