from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
        for agent_name in list(self._histories.keys()):
            target_length = snapshot.get(agent_name)
            if target_length is None:
                self._histories[agent_name] = []
                continue
            self._histories[agent_name] = self._histories[agent_name][:target_length]
