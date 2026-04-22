from __future__ import annotations

import ast
from dataclasses import dataclass, field

from ..errors import SandboxRejected


@dataclass(slots=True)
class AstChecker:
    forbidden_nodes: tuple[str, ...] = field(
        default_factory=lambda: ("Import", "ImportFrom"),
    )

    def check(self, code: str) -> None:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise SandboxRejected(f"syntax error: {exc}") from exc

        forbidden = set(self.forbidden_nodes)
        for node in ast.walk(tree):
            node_name = type(node).__name__
            if node_name in forbidden:
                lineno = getattr(node, "lineno", "?")
                raise SandboxRejected(
                    f"forbidden syntax: {node_name} at line {lineno}",
                )
