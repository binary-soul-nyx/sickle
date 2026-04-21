from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agents import Agent, OrchestratorAgent
from .config import AppConfig
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


@dataclass(slots=True)
class Sickle:
    config: AppConfig
    llm_client: Any | None = None
    extra_agents: dict[str, Agent] | None = None
    allowed_user_ids: set[int] = field(init=False, default_factory=set)
    history: HistoryManager = field(init=False)
    orchestrator: OrchestratorAgent = field(init=False)
    agents: dict[str, Agent] = field(init=False, default_factory=dict)
    runner: Runner = field(init=False)
    dispatch: Dispatch = field(init=False)

    def __post_init__(self) -> None:
        self.allowed_user_ids = set(self.config.telegram.allowed_user_ids)
        self.history = HistoryManager()
        if self.llm_client is None:
            self.llm_client = LLMClient(
                default_model=self.config.llm.default_model,
                timeout=self.config.llm.timeout,
                retry=self.config.llm.retry,
            )
        extra_agents = self.extra_agents or {}
        routable_agents = sorted(extra_agents.keys())
        self.orchestrator = OrchestratorAgent(
            llm_client=self.llm_client,
            model=self.config.llm.default_model,
            routable_agents=routable_agents,
        )
        self.agents = {"orchestrator": self.orchestrator, **extra_agents}
        self.runner = Runner(agents=self.agents, history=self.history)
        self.dispatch = Dispatch(history=self.history, runner=self.runner)

    def _is_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_user_ids

    async def handle_message(self, user_id: int, text: str) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()
        trigger = parse_trigger(text, available_agents=set(self.agents.keys()))
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
        ctx = RequestContext.create(
            user_id=user_id,
            entry_agent=trigger.message.entry_agent,
        )
        return await self.dispatch.run(ctx, trigger.message.body)

    async def handle_command(
        self,
        user_id: int,
        cmd: str,
        args: list[str],
    ) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()
        if cmd == "cancel":
            return Response.empty()
        if cmd == "clear":
            agent_name = args[0] if args else "orchestrator"
            self.history.clear(agent_name)
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
