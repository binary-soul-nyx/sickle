from __future__ import annotations

import platform

from ..base import Agent
from ...llm import LLMClient
from ...tools.executor import build_execute_code_tool_schema
from ...tools.toolkit import render_toolkit_docs


class OperatorAgent(Agent):
    def __init__(self, llm_client: LLMClient, model: str) -> None:
        super().__init__(
            name="operator",
            description="Executes code tasks in sandbox.",
            model=model,
            llm_client=llm_client,
        )
        self._toolkit_docs = render_toolkit_docs()
        self._system_info = self._collect_system_info()

    def build_tools(self) -> list[dict[str, object]]:
        return [build_execute_code_tool_schema()]

    def build_system_prompt(self) -> str:
        return "\n".join(
            [
                "You are the operator agent in Sickle.",
                "Your job is to complete execution tasks by calling execute_code.",
                "Always produce Python that defines a `result` dict.",
                "Do not use import statements.",
                "Follow sandbox and safety constraints strictly.",
                "",
                self._toolkit_docs,
                "",
                f"System info: {self._system_info}",
            ],
        )

    def _collect_system_info(self) -> str:
        return (
            f"os={platform.system()} {platform.release()}, "
            f"hostname={platform.node()}, "
            f"python={platform.python_version()}"
        )
