"""Session-leash lockfile module.

A lockfile is `.harness/sessions/<pid>.json`. It records that a Claude
Code session is alive in a given repo and tracks its worktree state.

Pure stdlib + cross-platform PID liveness via ctypes on Windows and
os.kill(pid, 0) on POSIX. No git, no subprocess.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = 1

STATE_PRIMARY = "primary"
STATE_PENDING_RESOLUTION = "pending-resolution"
STATE_PENDING_WORKTREE = "pending-worktree"
STATE_IN_WORKTREE = "in-worktree"

VALID_STATES = frozenset(
    {STATE_PRIMARY, STATE_PENDING_RESOLUTION, STATE_PENDING_WORKTREE, STATE_IN_WORKTREE}
)


@dataclass(frozen=True)
class Lockfile:
    schema: int
    pid: int
    started_at: str
    session_id: str
    primary_cwd: str
    state: str
    worktree_path: str | None
    worktree_branch: str | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Lockfile":
        if raw.get("schema") != SCHEMA:
            raise ValueError(f"unsupported lockfile schema: {raw.get('schema')!r}")
        state = raw.get("state")
        if state not in VALID_STATES:
            raise ValueError(f"invalid state: {state!r}")
        return cls(
            schema=raw["schema"],
            pid=int(raw["pid"]),
            started_at=str(raw["started_at"]),
            session_id=str(raw["session_id"]),
            primary_cwd=str(raw["primary_cwd"]),
            state=state,
            worktree_path=raw.get("worktree_path"),
            worktree_branch=raw.get("worktree_branch"),
        )


def is_pid_alive(pid: int) -> bool:
    """Cross-platform PID liveness check.

    Windows: OpenProcess + WaitForSingleObject(handle, 0). We use
    WaitForSingleObject rather than GetExitCodeProcess to avoid the
    well-known STILL_ACTIVE (259) collision — a process that exits
    with code 259 is indistinguishable from "still running" via
    GetExitCodeProcess. WaitForSingleObject returns WAIT_TIMEOUT iff
    the process is still running.
    POSIX: os.kill(pid, 0) with EPERM treated as alive (process exists,
    we just lack permission to signal it).
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        WAIT_TIMEOUT = 0x102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if not handle:
            return False
        result = kernel32.WaitForSingleObject(handle, 0)
        kernel32.CloseHandle(handle)
        return result == WAIT_TIMEOUT
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def write_lockfile(path: Path, lf: Lockfile) -> None:
    """Atomic write: <path>.tmp -> os.replace(<path>)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(lf.to_json(), encoding="utf-8")
    os.replace(tmp, path)


def read_lockfile(path: Path) -> Lockfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Lockfile.from_dict(raw)


def _iter_lockfile_paths(sessions_dir: Path) -> Iterable[Path]:
    if not sessions_dir.exists():
        return ()
    return sorted(sessions_dir.glob("*.json"))


def gc_dead_lockfiles(sessions_dir: Path) -> int:
    """Delete lockfiles whose PID is not alive, or which are corrupt.

    Also collects stale `<pid>.json.tmp` residue from a crashed
    atomic write — a successful write atomically renames the tmp away,
    so any `.tmp` present is from a process that died mid-write and
    will never finish.

    Returns count deleted (lockfiles + tmp residue).
    """
    n = 0
    if sessions_dir.exists():
        for tmp in sessions_dir.glob("*.json.tmp"):
            try:
                tmp.unlink()
                n += 1
            except FileNotFoundError:
                pass
    for path in _iter_lockfile_paths(sessions_dir):
        try:
            lf = read_lockfile(path)
        except (ValueError, KeyError, json.JSONDecodeError):
            try:
                path.unlink()
                n += 1
            except FileNotFoundError:
                pass
            continue
        if not is_pid_alive(lf.pid):
            try:
                path.unlink()
                n += 1
            except FileNotFoundError:
                pass
    return n


def list_live_lockfiles(sessions_dir: Path, *, primary_cwd: str) -> list[Lockfile]:
    """Return all lockfiles whose PID is alive and primary_cwd matches.

    Does not GC; the caller should usually GC first.
    """
    out: list[Lockfile] = []
    for path in _iter_lockfile_paths(sessions_dir):
        try:
            lf = read_lockfile(path)
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        if lf.primary_cwd != primary_cwd:
            continue
        if not is_pid_alive(lf.pid):
            continue
        out.append(lf)
    return out


def resolve_state(*, self_pid: int, live_peer_pids: list[int]) -> str:
    """Two-phase resolution: lowest live PID wins `primary`.

    `live_peer_pids` MUST NOT include `self_pid`. If empty, this session
    is alone -> primary. If non-empty, primary iff self_pid is strictly
    less than every peer.
    """
    if not live_peer_pids:
        return STATE_PRIMARY
    return STATE_PRIMARY if self_pid < min(live_peer_pids) else STATE_PENDING_WORKTREE
