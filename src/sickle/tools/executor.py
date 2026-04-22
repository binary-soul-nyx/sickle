from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
import io
import json
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from ..errors import SandboxRejected
from ..logs import clip_text, get_logger
from .checker import AstChecker
from .toolkit import get_toolkit_modules

logger = get_logger("tools.executor")


@dataclass(slots=True)
class ExecuteCodeResult:
    success: bool
    result: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timeout: bool = False
    artifacts: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecuteCodeCall:
    id: str
    kind: str
    code: str
    is_final: bool
    metadata: dict[str, Any] = field(default_factory=dict)


def build_execute_code_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Execute Python code in the sandbox and return structured result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Must set a result dict.",
                    },
                    "is_final": {
                        "type": "boolean",
                        "description": "Whether this is the final execution step.",
                    },
                },
                "required": ["code", "is_final"],
                "additionalProperties": False,
            },
        },
    }


def parse_execute_code_call(tool_call: dict[str, Any]) -> ExecuteCodeCall:
    if tool_call.get("name") != "execute_code":
        raise ValueError("tool call is not execute_code")

    raw_arguments = tool_call.get("arguments", "{}")
    if not isinstance(raw_arguments, str):
        raise ValueError("execute_code arguments must be a JSON string")

    payload = json.loads(raw_arguments)
    code = payload.get("code")
    is_final = payload.get("is_final")
    if not isinstance(code, str):
        raise ValueError("execute_code.code must be a string")
    if not isinstance(is_final, bool):
        raise ValueError("execute_code.is_final must be a bool")

    return ExecuteCodeCall(
        id=str(tool_call.get("id", "")),
        kind="execute_code",
        code=code,
        is_final=is_final,
        metadata=dict(tool_call.get("metadata", {})),
    )


@dataclass(slots=True)
class SandboxExecutor:
    checker: AstChecker = field(default_factory=AstChecker)
    exec_timeout: float = 30.0
    large_output_threshold: int = 1000

    async def execute(self, code: str) -> ExecuteCodeResult:
        started = time.perf_counter()
        logger.info("sandbox.execute start code_len=%s", len(code))

        try:
            self.checker.check(code)
        except SandboxRejected as exc:
            logger.warning(
                "sandbox.execute rejected code_len=%s reason=%s",
                len(code),
                clip_text(str(exc), max_chars=200),
            )
            return ExecuteCodeResult(
                success=False,
                result={},
                stderr=str(exc),
                duration_ms=self._duration_ms(started),
            )

        loop = asyncio.get_running_loop()
        try:
            success, result, stdout_text, stderr_text = await asyncio.wait_for(
                loop.run_in_executor(None, self._run_in_sandbox, code),
                timeout=self.exec_timeout,
            )
        except TimeoutError:
            duration = self._duration_ms(started)
            logger.warning(
                "sandbox.execute timeout code_len=%s timeout=%ss duration_ms=%s",
                len(code),
                self.exec_timeout,
                duration,
            )
            return ExecuteCodeResult(
                success=False,
                result={},
                stdout="",
                stderr=f"TimeoutError: execution exceeded {self.exec_timeout} seconds",
                duration_ms=duration,
                timeout=True,
            )
        except Exception as exc:  # pragma: no cover - defensive wrapper
            duration = self._duration_ms(started)
            logger.error(
                "sandbox.execute unexpected_error code_len=%s error=%s duration_ms=%s",
                len(code),
                exc,
                duration,
            )
            return ExecuteCodeResult(
                success=False,
                result={},
                stdout="",
                stderr=str(exc),
                duration_ms=duration,
            )

        artifacts: list[Path] = []
        if len(stdout_text) > self.large_output_threshold:
            logger.warning(
                "sandbox.execute stdout_truncated code_len=%s stdout_len=%s threshold=%s",
                len(code),
                len(stdout_text),
                self.large_output_threshold,
            )
            artifact_path = self._write_artifact(
                prefix="sickle-stdout-",
                suffix=".log",
                content=stdout_text,
            )
            artifacts.append(artifact_path)
            stdout_text = (
                stdout_text[: self.large_output_threshold]
                + "\n... [truncated, full output in artifact]"
            )

        duration = self._duration_ms(started)
        logger.info(
            "sandbox.execute done success=%s duration_ms=%s artifacts=%s",
            success,
            duration,
            len(artifacts),
        )
        return ExecuteCodeResult(
            success=success,
            result=result,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=duration,
            timeout=False,
            artifacts=artifacts,
        )

    def _run_in_sandbox(self, code: str) -> tuple[bool, dict[str, Any], str, str]:
        globals_dict: dict[str, Any] = {
            "__builtins__": self._safe_builtins(),
            **get_toolkit_modules(),
        }
        locals_dict: dict[str, Any] = {}

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        success = False
        traceback_text = ""

        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                compiled = compile(code, "<operator_code>", "exec")
                exec(compiled, globals_dict, locals_dict)
            success = True
        except Exception:
            traceback_text = traceback.format_exc()

        result_value = locals_dict.get("result", globals_dict.get("result", {}))
        if not isinstance(result_value, dict):
            result_value = {"value": result_value}

        stderr_text = stderr_buffer.getvalue()
        if traceback_text:
            stderr_text = f"{stderr_text}{traceback_text}"

        return success, result_value, stdout_buffer.getvalue(), stderr_text

    def _safe_builtins(self) -> dict[str, Any]:
        return {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "print": print,
            "range": range,
            "reversed": reversed,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
            "True": True,
            "False": False,
            "None": None,
        }

    def _write_artifact(self, prefix: str, suffix: str, content: str) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=prefix,
            suffix=suffix,
            delete=False,
        ) as handle:
            handle.write(content)
            return Path(handle.name)

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
