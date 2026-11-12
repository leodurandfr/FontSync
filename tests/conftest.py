"""Global sandbox for the whole test suite (loaded before any test module).

At import time, before `agent` is imported anywhere:

- HOME, FONTSYNC_HOME and FONTSYNC_FONTS_DIR point at a throwaway directory
  created with `tempfile.mkdtemp()` (under $TMPDIR, never in the repository),
  so module-level paths such as `agent.config.CONFIG_FILE` or
  `agent.launchd_setup.LAUNCH_AGENTS_DIR` are sandboxed;
- FONTSYNC_NO_REINDEX=1 keeps the real font index untouched;
- an audit hook refuses any write, rename or removal under the real
  ~/.fontsync, ~/Library/Fonts, ~/Library/LaunchAgents and /Library/Fonts
  (captured here, before HOME is changed), and any `launchctl` or `killall`
  subprocess. Reads stay allowed (Core Text tests read the real system).

FONTSYNC_DISCOVERY is left alone: two Core Text tests depend on it.
"""

from __future__ import annotations

import atexit
import os
import pwd
import shlex
import shutil
import sys
import tempfile

# The account's home from the password database, not $HOME (which may already
# have been changed by whoever launched pytest).
REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
SANDBOX_HOME = tempfile.mkdtemp(prefix="fontsync-tests-home-")
atexit.register(shutil.rmtree, SANDBOX_HOME, ignore_errors=True)

PROTECTED_DIRS: tuple[str, ...] = (
    os.path.join(REAL_HOME, ".fontsync"),
    os.path.join(REAL_HOME, "Library", "Fonts"),
    os.path.join(REAL_HOME, "Library", "LaunchAgents"),
    "/Library/Fonts",
)
FORBIDDEN_TOOLS = frozenset({"launchctl", "killall"})

os.environ["HOME"] = SANDBOX_HOME
os.environ["FONTSYNC_HOME"] = os.path.join(SANDBOX_HOME, ".fontsync")
os.environ["FONTSYNC_FONTS_DIR"] = os.path.join(SANDBOX_HOME, "Library", "Fonts")
os.environ["FONTSYNC_NO_REINDEX"] = "1"
os.makedirs(os.environ["FONTSYNC_FONTS_DIR"], exist_ok=True)

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_PATH_EVENTS = {
    "os.rename": 2,
    "os.replace": 2,
    "os.remove": 1,
    "os.rmdir": 1,
    "os.mkdir": 1,
    "os.symlink": 2,
    "os.link": 2,
    "os.truncate": 1,
    "os.chmod": 1,
    "os.utime": 1,
    "shutil.rmtree": 1,
}


def _canonical(path: str) -> str:
    """Resolve symlinks and `//`, strip the APFS firmlink, compare case-insensitively."""
    # POSIX normpath keeps a leading `//`: collapse it.
    resolved = "/" + os.path.realpath(path).lstrip("/")
    data_prefix = "/System/Volumes/Data/"
    if resolved.startswith(data_prefix):
        resolved = resolved[len(data_prefix) - 1 :]
    return resolved.casefold()


def _is_protected(path: object) -> bool:
    if isinstance(path, int) or path is None:
        return False
    try:
        candidate = _canonical(os.fsdecode(path))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    # Read the module attribute each time: tests may substitute stand-ins.
    for root in sys.modules[__name__].PROTECTED_DIRS:
        canonical_root = _canonical(root).rstrip(os.sep)
        if candidate == canonical_root or candidate.startswith(canonical_root + os.sep):
            return True
    return False


def _command_names(command: object) -> list[str]:
    """Every word of a command line or argv, as program names to check."""
    if command is None:
        return []
    if isinstance(command, (str, bytes)):
        text = os.fsdecode(command)
        try:
            words = shlex.split(text)
        except ValueError:
            words = text.split()
        # Nested shells (`sh -c 'sh -c "killall …"'`): split again until flat.
        if len(words) == 1 and words[0] == text:
            return words
        return [name for word in words for name in _command_names(word)]
    if isinstance(command, (list, tuple)):
        # Split each element too: `["sh", "-c", "killall fontd"]`.
        return [
            word
            for part in command
            if isinstance(part, (str, bytes))
            for word in _command_names(part)
        ]
    return [os.fsdecode(command)] if isinstance(command, os.PathLike) else []


def _refuse(what: str) -> None:
    raise PermissionError(f"test sandbox: refused {what}")


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        if writing and _is_protected(path):
            _refuse(f"write to {path}")
    elif event in _PATH_EVENTS:
        for path in args[: _PATH_EVENTS[event]]:
            if _is_protected(path):
                _refuse(f"{event} on {path}")
    elif event in ("subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn"):
        names = _command_names(args[0]) + _command_names(args[1])
        if any(os.path.basename(n) in FORBIDDEN_TOOLS for n in names):
            _refuse(f"{event} {names}")
    elif event == "os.system":
        names = _command_names(args[0])
        if any(os.path.basename(n) in FORBIDDEN_TOOLS for n in names):
            _refuse(f"os.system {names}")


sys.addaudithook(_audit)
