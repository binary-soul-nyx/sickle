from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..llm import LLMClient, LLMResponse
from ..logs import get_logger, summarize_messages, summarize_tools, to_log_json

logger = get_logger("agents.base")


@dataclass(slots=True)
class Agent:
    name: str
    description: str
    model: str
    llm_client: LLMClient
    config: dict[str, Any] = field(default_factory=dict)

    def build_system_prompt(self) -> str:
        raise NotImplementedError

    def build_tools(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def run_turn(self, history: list[dict[str, Any]]) -> LLMResponse:
        system_prompt = self.build_system_prompt()
        tools = self.build_tools()
        messages = [{"role": "system", "content": system_prompt}, *history]
        logger.debug(
            "agent.run_turn build_request agent=%s model=%s history_len=%s tools=%s messages=%s",
            self.name,
            self.model,
            len(history),
            summarize_tools(tools),
            to_log_json(summarize_messages(messages)),
        )
        return await self.llm_client.chat(
            model=self.model,
            messages=messages,
            tools=tools,
        )
