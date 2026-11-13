"""Compose guards: backups never live in a volume of the compose project (H-01).

A named volume belongs to the compose project: `docker compose down -v` deletes
it together with `db` and `fonts`, so the backups would vanish with the data
they exist to restore.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.nas.yml"
BACKUP_SCRIPT = ROOT / "scripts" / "backup-prod.sh"

# `${VAR}`, `${VAR:-default}`, `${VAR-default}`, `${VAR:?message}`.
_VARIABLE = re.compile(r"\$\{\w+(?::?-(?P<default>[^}]*)|:?\?[^}]*)?\}")


def _load() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "docker-compose.nas.yml is not a mapping"
    return data


def _split_short_syntax(entry: str) -> tuple[str, str, str]:
    """`source:target[:mode]` -> (source, target, mode); the source may be a
    `${VAR:-default}`, whose default can itself contain a `:`."""
    source = ""
    if entry.startswith("${"):
        end = entry.index("}") + 1
        source, entry = entry[:end], entry[end:]
        assert entry.startswith(":"), entry
        entry = entry[1:]
    else:
        assert ":" in entry, f"anonymous volume: {entry!r}"
        source, entry = entry.split(":", 1)
    target, _, mode = entry.partition(":")
    return source, target, mode


def _resolve(source: str) -> str:
    """What compose mounts when the variable is unset: its default, if any."""
    match = _VARIABLE.fullmatch(source)
    if match is None:
        return source
    # No default: compose refuses to start (`:?`) or the user must set it —
    # either way the value is a path chosen in `.env`.
    return match.group("default") or "/"


def _mounts(service: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    """target -> (type, resolved source, mode) for a service's volumes."""
    out: dict[str, tuple[str, str, str]] = {}
    for entry in service.get("volumes", []) or []:
        if isinstance(entry, str):
            raw, target, mode = _split_short_syntax(entry)
            source = _resolve(raw)
            kind = "bind" if source[:1] in ("/", ".", "~") else "volume"
        else:
            source, target = (
                _resolve(str(entry.get("source", ""))),
                str(entry["target"]),
            )
            kind = str(entry.get("type", "volume"))
            mode = "ro" if entry.get("read_only") else ""
        assert target not in out, f"{target} mounted twice"
        out[target] = (kind, source, mode)
    return out


def test_backups_is_bind_mount() -> None:
    data = _load()
    named = set((data.get("volumes") or {}).keys())
    fontsync = data["services"]["fontsync"]
    assert fontsync["environment"]["BACKUP_DIR"] == "/backups"

    mounts = _mounts(fontsync)
    assert "/backups" in mounts, "BACKUP_DIR=/backups but nothing is mounted there"
    kind, source, mode = mounts["/backups"]
    assert kind == "bind", f"/backups comes from the named volume {source!r}"
    assert source not in named
    assert "backups" not in named, "a `backups` named volume is still declared"
    assert "ro" not in mode.split(","), "the server must be able to write there"


def test_backup_dir_is_configurable_with_a_default() -> None:
    entry = next(
        v
        for v in _load()["services"]["fontsync"]["volumes"]
        if isinstance(v, str) and v.endswith(":/backups")
    )
    raw, _target, _mode = _split_short_syntax(entry)
    # The host folder is chosen in `.env` (another volume, a USB disk...);
    # without it, a folder next to the compose file, still outside `down -v`.
    assert raw.startswith("${FONTSYNC_BACKUP_DIR:-"), raw
    assert _resolve(raw).startswith("./"), raw


def test_default_backup_dir_is_not_the_backup_script_folder() -> None:
    """`scripts/backup-prod.sh` rotates `fontsync-*.db` in `<compose dir>/backups`,
    like the server does in `/backups`: one shared folder would keep 14 files
    for both writers together, half the promised retention."""
    _kind, source, _mode = _mounts(_load()["services"]["fontsync"])["/backups"]
    script = BACKUP_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'^OUT_DIR="\$\{OUT_DIR:-(?P<dir>[^}]+)\}"', script, re.MULTILINE)
    assert match, "OUT_DIR default not found in scripts/backup-prod.sh"
    script_folder = Path(match.group("dir")).name
    assert Path(source).name != script_folder, (source, match.group("dir"))


def test_data_volumes_stay_named() -> None:
    mounts = _mounts(_load()["services"]["fontsync"])
    assert mounts["/data"] == ("volume", "db", "")
    assert mounts["/fonts"] == ("volume", "fonts", "")
