from __future__ import annotations

import shutil
from pathlib import Path


def read(path: str) -> str:
    """Reads the content of a text file.

    Function:
    Reads the entire content of a text file specified by the path, using UTF-8 encoding, and returns it as a string.

    Args:
    path: The string path to the file.

    Returns:
    The complete text content of the file.

    Raises:
    FileNotFoundError: If the file does not exist.
    IsADirectoryError: If the path points to a directory.
    UnicodeDecodeError: If the file content is not encoded in UTF-8.

    Example:
    >>> data = fs.read("/tmp/report.txt")
    >>> print(data)
    """

    return Path(path).read_text(encoding="utf-8")


def write(path: str, data: str) -> None:
    """Writes text data to a file.

    Function:
    Writes the provided text data to the specified path using UTF-8 encoding. If parent directories do not exist, they will be created automatically.

    Args:
    path: The target file path.
    data: The text content to write.

    Returns:
    None.

    Raises:
    PermissionError: If there is no write permission for the target location.
    OSError: Other filesystem errors.

    Example:
    >>> fs.write("/tmp/out.txt", "hello")
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data, encoding="utf-8")


def list_dir(path: str) -> list[str]:
    """Lists the immediate children of a directory.

    Function:
    Returns a list of absolute paths to all files and directories directly inside the given path, sorted alphabetically.

    Args:
    path: The directory path to list.

    Returns:
    A list of absolute paths to all immediate children in that directory.

    Raises:
    FileNotFoundError: If the directory does not exist.
    NotADirectoryError: If the path does not point to a directory.

    Example:
    >>> items = fs.list_dir("/tmp")
    >>> print(items[:3])
    """

    root = Path(path)
    return sorted(str(child.resolve()) for child in root.iterdir())


def exists(path: str) -> bool:
    """Checks if a path exists.

    Function:
    Checks if a file or directory exists at the given path.

    Args:
    path: The file or directory path.

    Returns:
    True if the path exists, False otherwise.

    Raises:
    None.

    Example:
    >>> fs.exists("/tmp/out.txt")
    True
    """

    return Path(path).exists()


def delete(path: str) -> None:
    """Deletes a file or directory.

    Function:
    Deletes a single file. If `path` points to a directory, it recursively removes the entire directory tree.

    Args:
    path: The file or directory to be deleted.

    Returns:
    None.

    Raises:
    FileNotFoundError: If the target does not exist.
    PermissionError: If deletion permissions are insufficient.
    OSError: Other system errors.

    Example:
    >>> fs.delete("/tmp/old.log")
    """

    target = Path(path)
    if target.is_dir():
        shutil.rmtree(target)
        return
    target.unlink()


def size(path: str) -> int:
    """Calculates the size of a file or directory (in bytes).

    Function:
    If the path refers to a file, it returns the file size in bytes. If it refers to a directory, it recursively calculates the total size of all contents within that directory.

    Args:
    path: The file or directory path.

    Returns:
    The total size in bytes.

    Raises:
    FileNotFoundError: If the path does not exist.
    OSError: If there is an error reading the filesystem.

    Example:
    >>> total = fs.size("/tmp/downloads")
    >>> print(total)
    """

    target = Path(path)
    if target.is_file():
        return target.stat().st_size

    # If it's a directory, calculate the recursive size
    total = 0
    for item in target.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total
