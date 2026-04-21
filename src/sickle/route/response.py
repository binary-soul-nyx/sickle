"""Response schema for Sickle bot responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(slots=True)
class Button:
    text: str
    callback_id: str
    style: Literal["default", "primary", "danger"] = "default"
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Response:
    text: str | None = None
    files: list[Path] = field(default_factory=list)
    buttons: list[list[Button]] = field(default_factory=list)
    silent: bool = False
    voice: Path | None = None
    image: Path | None = None
    edit_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "Response":
        return cls()

    @classmethod
    def text_only(cls, text: str) -> "Response":
        return cls(text=text)

    @classmethod
    def with_file(cls, text: str | None, file: Path) -> "Response":
        return cls(text=text, files=[file])

    def is_empty(self) -> bool:
        return (
            not self.text
            and not self.files
            and not self.buttons
            and self.voice is None
            and self.image is None
            and self.edit_message_id is None
        )
