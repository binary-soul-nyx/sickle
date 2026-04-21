from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..llm import LLMClient, LLMResponse


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
        messages = [{"role": "system", "content": self.build_system_prompt()}, *history]
        return await self.llm_client.chat(
            model=self.model,
            messages=messages,
            tools=self.build_tools(),
        )
