from __future__ import annotations

import subprocess
from typing import Any


def run(cmd: str, timeout: int = 30) -> dict[str, Any]:
    """Executes a shell command and returns a structured result.

    Function:
    Executes the command within the current system shell, capturing the standard output (stdout), standard error (stderr), and the process's return code.

    Args:
    cmd (str): The shell command string to execute.
    timeout (int, optional): The maximum execution time in seconds. Defaults to 30.

    Returns:
    dict[str, Any]: A dictionary containing:
    - stdout: Standard output from the process.
    - stderr: Standard error output from the process.
    - returncode: The exit code of the process.

    Raises:
    subprocess.TimeoutExpired: If the command exceeds the timeout limit.
    OSError: If the operating system fails to execute the command.

    Example:
    >>> out = process.run("ls -la /tmp", timeout=10)
    >>> print(out["returncode"])
    """

    completed = subprocess.run(
        cmd,
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
