from __future__ import annotations

from datetime import datetime
import platform

from ..base import Agent
from ...llm import LLMClient
from ...tools.route import build_route_tool_schema


class OrchestratorAgent(Agent):
    def __init__(
        self,
        llm_client: LLMClient,
        model: str,
        routable_agents: list[str] | None = None,
    ) -> None:
        super().__init__(
            name="orchestrator",
            description="Default user-facing coordinator agent.",
            model=model,
            llm_client=llm_client,
        )
        self._system_info = self._collect_system_info()
        self._routable_agents = routable_agents or []

    def build_tools(self) -> list[dict[str, object]]:
        if not self._routable_agents:
            return []
        return [build_route_tool_schema(self._routable_agents)]

    def build_system_prompt(self) -> str:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        agents_text = ", ".join(self._routable_agents) if self._routable_agents else "none"
        return "\n".join(
            [
                "You are the orchestrator agent in Sickle.",
                "Reply clearly and directly to the user request.",
                "Use route tool when another specialist agent should handle a task.",
                "Do not invent tool outputs.",
                "",
                f"Routable agents: {agents_text}",
                f"System info: {self._system_info}",
                f"Current time: {now}",
            ],
        )

    def _collect_system_info(self) -> str:
        return (
            f"os={platform.system()} {platform.release()}, "
            f"hostname={platform.node()}, "
            f"python={platform.python_version()}"
        )
