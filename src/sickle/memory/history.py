from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..logs import get_logger

logger = get_logger("memory.history")

HistorySnapshot = dict[str, int]


@dataclass(slots=True)
class HistoryManager:
    _histories: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def append(self, agent_name: str, message: dict[str, Any]) -> None:
        self._histories.setdefault(agent_name, []).append(message)

    def get(self, agent_name: str) -> list[dict[str, Any]]:
        return list(self._histories.get(agent_name, []))

    def clear(self, agent_name: str) -> None:
        self._histories[agent_name] = []

    def snapshot(self) -> HistorySnapshot:
        return {
            agent_name: len(messages)
            for agent_name, messages in self._histories.items()
        }

    def rollback(self, snapshot: HistorySnapshot) -> None:
        rolled: dict[str, str] = {}
        for agent_name in list(self._histories.keys()):
            current_length = len(self._histories[agent_name])
            target_length = snapshot.get(agent_name)
            if target_length is None:
                self._histories[agent_name] = []
                rolled[agent_name] = f"{current_length}→0"
            else:
                self._histories[agent_name] = self._histories[agent_name][:target_length]
                if current_length != target_length:
                    rolled[agent_name] = f"{current_length}→{target_length}"
        if rolled:
            logger.info("history.rollback %s", rolled)
