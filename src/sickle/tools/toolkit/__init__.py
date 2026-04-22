from __future__ import annotations

from importlib import import_module
import inspect
from types import ModuleType
from typing import Callable

from . import fs, process


def get_toolkit_modules() -> dict[str, ModuleType]:
    return {
        "fs": import_module(".fs", __name__),
        "process": import_module(".process", __name__),
    }


def render_toolkit_docs() -> str:
    lines = ["# Toolkit Functions"]
    for module_name, module in get_toolkit_modules().items():
        lines.append("")
        lines.append(f"## {module_name}")
        for func in _iter_public_functions(module):
            signature = inspect.signature(func)
            lines.append(f"- `{module_name}.{func.__name__}{signature}`")
            doc = inspect.getdoc(func) or "No documentation."
            lines.append(f"  {doc.splitlines()[0]}")
    return "\n".join(lines)


def _iter_public_functions(module: ModuleType) -> list[Callable]:
    functions: list[Callable] = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_"):
            continue
        if obj.__module__ != module.__name__:
            continue
        functions.append(obj)
    return functions


__all__ = ["fs", "get_toolkit_modules", "process", "render_toolkit_docs"]
