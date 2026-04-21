from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(slots=True)
class RequestContext:
    request_id: UUID
    user_id: int
    entry_agent: str
    chain: list[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(cls, user_id: int, entry_agent: str) -> "RequestContext":
        return cls(
            request_id=uuid4(),
            user_id=user_id,
            entry_agent=entry_agent,
            chain=[entry_agent],
        )

    @property
    def current(self) -> str:
        return self.chain[-1]

    @property
    def is_direct(self) -> bool:
        return len(self.chain) == 1

    @property
    def upstream(self) -> str | None:
        if len(self.chain) < 2:
            return None
        return self.chain[-2]
