"""Shared helpers for the execution harness scripts."""
from __future__ import annotations

import shlex
from pathlib import Path


def to_posix_bash(path: Path) -> str:
    """Convert a Path to a POSIX path suitable for Git Bash / MSYS2 on Windows.

    On Windows, paths like C:/Users/foo are rewritten to /c/Users/foo.
    On Linux/macOS the path is returned as-is.
    """
    p = path.as_posix()
    if len(p) >= 2 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


def bash_shell_cmd(script_path: Path, args: list[str]) -> str:
    """Build a shell=True-safe `bash <script> <args...>` command string.

    Uses to_posix_bash to fix Windows drive letters and shlex.quote for safe
    argument escaping. Required because subprocess list-form passes argv[1]
    directly to bash, which on MSYS2 / Git Bash fails to resolve C:\\ paths
    containing spaces. shell=True delegates quoting to the host shell.
    """
    script_posix = to_posix_bash(script_path)
    quoted_args = " ".join(shlex.quote(a) for a in args)
    return f"bash {shlex.quote(script_posix)} {quoted_args}".strip()
