from __future__ import annotations

from dataclasses import dataclass

from ..agents import Agent
from ..llm import LLMResponse
from ..logs import get_logger
from ..memory import HistoryManager

logger = get_logger("route.runner")


@dataclass(slots=True)
class Runner:
    agents: dict[str, Agent]
    history: HistoryManager

    async def run_turn(self, agent_name: str) -> LLMResponse:
        agent = self.agents.get(agent_name)
        if agent is None:
            raise KeyError(f"unknown agent: {agent_name}")
        history = self.history.get(agent_name)
        logger.debug(
            "runner.run_turn start agent=%s history_len=%s",
            agent_name,
            len(history),
        )
        result = await agent.run_turn(history)
        logger.debug(
            "runner.run_turn done agent=%s content_len=%s tool_calls=%s",
            agent_name,
            len(result.content or ""),
            len(result.tool_calls),
        )
        return result
