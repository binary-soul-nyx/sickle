from __future__ import annotations

from dataclasses import dataclass

from ..agents import Agent
from ..llm import LLMResponse
from ..memory import HistoryManager


@dataclass(slots=True)
class Runner:
    agents: dict[str, Agent]
    history: HistoryManager

    async def run_turn(self, agent_name: str) -> LLMResponse:
        agent = self.agents.get(agent_name)
        if agent is None:
            raise KeyError(f"unknown agent: {agent_name}")
        return await agent.run_turn(self.history.get(agent_name))
