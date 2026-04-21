from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agents import OrchestratorAgent
from .config import AppConfig
from .llm import LLMClient
from .memory import HistoryManager
from .route.response import Response


@dataclass(slots=True)
class Sickle:
    config: AppConfig
    llm_client: Any | None = None
    allowed_user_ids: set[int] = field(init=False, default_factory=set)
    history: HistoryManager = field(init=False)
    orchestrator: OrchestratorAgent = field(init=False)

    def __post_init__(self) -> None:
        self.allowed_user_ids = set(self.config.telegram.allowed_user_ids)
        self.history = HistoryManager()
        if self.llm_client is None:
            self.llm_client = LLMClient(
                default_model=self.config.llm.default_model,
                timeout=self.config.llm.timeout,
                retry=self.config.llm.retry,
            )
        self.orchestrator = OrchestratorAgent(
            llm_client=self.llm_client,
            model=self.config.llm.default_model,
        )

    def _is_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_user_ids

    async def handle_message(self, user_id: int, text: str) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()

        self.history.append(
            "orchestrator",
            {
                "role": "user",
                "content": text,
            },
        )
        turn_result = await self.orchestrator.run_turn(self.history.get("orchestrator"))

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": turn_result.content,
        }
        if turn_result.tool_calls:
            assistant_message["tool_calls"] = turn_result.tool_calls
        self.history.append("orchestrator", assistant_message)

        if turn_result.content:
            return Response.text_only(turn_result.content)
        return Response.empty()

    async def handle_command(
        self,
        user_id: int,
        cmd: str,
        args: list[str],
    ) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()
        return Response.text_only("ok")

    async def handle_button(self, user_id: int, callback_id: str) -> Response:
        if not self._is_allowed(user_id):
            return Response.empty()
        return Response.empty()
