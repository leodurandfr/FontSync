"""The public repository must not map a real deployment.

Scans every file tracked by git for private or Tailscale addresses, SSH ports
written as literals, real e-mail addresses, real tailnet host names and
personal home directories. Machine names (e.g. `*.home`) cannot be told apart
from generic examples by a pattern: review them by hand. Documentation uses placeholders
(`<user>@<nas>`, `-p <ssh-port>`, `<apple-id>`, `/Users/<user>/`) and RFC 5737
addresses (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24). A line that must
keep such a value can be marked with `infra-leak: allow`.

This file is excluded from the scan: its samples must match the patterns. They
are made-up values, never real ones.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
ALLOW_MARKER = "infra-leak: allow"

_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_FILE_EXTENSIONS = (
    r"(?:png|jpe?g|svg|gif|pdf|ttf|otf|woff2?|ttc|json|ya?ml|md|txt|py|js|ts|css)"
)
PATTERNS: dict[str, re.Pattern[str]] = {
    "private IPv4": re.compile(
        rf"(?<![\d.])(?:10\.{_OCTET}|192\.168|172\.(?:1[6-9]|2\d|3[01]))"
        rf"\.{_OCTET}\.{_OCTET}(?![\d.]*\d)"
    ),
    "CGNAT/Tailscale IPv4": re.compile(
        rf"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.{_OCTET}\.{_OCTET}"
        r"(?![\d.]*\d|/)"
    ),
    "Tailscale IPv6": re.compile(r"\bfd7a:115c:a1e0:[0-9a-f:]+", re.IGNORECASE),
    "literal SSH port": re.compile(
        r"\b(?:ssh|scp|sftp|ssh-copy-id)\b[^\n]*(?:\s-[pP]\s*\d+|-o\s*Port[= ]\d+)"
        r"|^\s*Port\s+\d+\s*$"
    ),
    "real tailnet name": re.compile(
        r"\b[a-z0-9-]+\.tail[0-9a-f]{4,}\.ts\.net\b", re.IGNORECASE
    ),
    "personal home directory": re.compile(
        r"/(?:Users|home)/(?!<|Shared/|runner/|x/|user/|me/|test/)[A-Za-z][A-Za-z0-9._-]+/"
    ),
    "e-mail address": re.compile(
        rf"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?!{_FILE_EXTENSIONS}\b)"
        r"[A-Za-z]{2,}\b"
    ),
}
ALLOWED_EMAILS = re.compile(
    r"(@example\.(?:com|org|net)$|^noreply@anthropic\.com$|^git@github\.com$"
    r"|@users\.noreply\.github\.com$)",
    re.IGNORECASE,
)


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [REPO_ROOT / n for n in out.decode().split("\0") if n and n != SELF]


def scan_text(name: str, text: str) -> list[str]:
    """Return `name:line: kind: match` for every suspicious value in `text`."""
    leaks: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                value = match.group(0)
                if kind == "e-mail address" and ALLOWED_EMAILS.search(value):
                    continue
                leaks.append(f"{name}:{number}: {kind}: {value}")
    return leaks


def find_leaks(files: list[Path]) -> list[str]:
    leaks: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: fonts, images
        leaks += scan_text(str(path.relative_to(REPO_ROOT)), text)
    return leaks


def test_tracked_files_do_not_map_real_infrastructure() -> None:
    leaks = find_leaks(_tracked_files())
    assert not leaks, "real infrastructure values in the public repo:\n" + "\n".join(
        leaks
    )


# Made-up values only (see module docstring).
@pytest.mark.parametrize(
    "line",
    [
        "ssh -p 2201 admin@box",
        "scp -P 4422 file user@host:/x",
        "ssh -oPort=4422 admin@box",
        "    Port 4422",
        "url: http://192.168.77.5:8080",
        "server at 10.20.30.40",
        "tailnet 100.99.88.77",
        "fd7a:115c:a1e0::dead:beef",
        "https://box.tail1a2b3c.ts.net",
        "open /Users/alexandre/Library/Fonts/A.ttf",
        "contact: someone@real-domain.fr",
    ],
)
def test_detector_flags_real_values(line: str) -> None:
    assert scan_text("sample.md", line), line


@pytest.mark.parametrize(
    "line",
    [
        "ssh -p <ssh-port> <user>@<nas>",
        "url: http://192.0.2.172:8080",
        "fontsync.example.ts.net",
        "the 100.64.0.0/10 range",
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "git clone git@github.com:owner/repo.git",
        '"filename": "icon_16x16@2x.png"',
        '"version": "10.6.0"',
        "local_path /Users/x/Library/Fonts/A.ttf",
        "/Users/<user>/Library/Fonts",
        "Mac-mini-de-Alex.local",
        "ssh -p 2201 admin@box  # infra-leak: allow",
    ],
)
def test_detector_accepts_placeholders(line: str) -> None:
    assert scan_text("sample.md", line) == []
