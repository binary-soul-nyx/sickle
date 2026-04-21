from __future__ import annotations

from datetime import datetime
import platform

from ..base import Agent
from ...llm import LLMClient


class OrchestratorAgent(Agent):
    def __init__(self, llm_client: LLMClient, model: str) -> None:
        super().__init__(
            name="orchestrator",
            description="Default user-facing coordinator agent.",
            model=model,
            llm_client=llm_client,
        )
        self._system_info = self._collect_system_info()

    def build_tools(self) -> list[dict[str, object]]:
        return []

    def build_system_prompt(self) -> str:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        return "\n".join(
            [
                "You are the orchestrator agent in Sickle.",
                "Reply clearly and directly to the user request.",
                "Do not invent tool outputs.",
                "",
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
