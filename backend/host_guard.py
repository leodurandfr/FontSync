# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# This file is part of FontSync, a self-hosted font manager.
# FontSync is free software: you can redistribute it and/or modify it under the
# terms of the GNU Affero General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. It is distributed WITHOUT ANY WARRANTY; see the GNU AGPL for details.
# You should have received a copy of the license with this program (see LICENSE),
# or at <https://www.gnu.org/licenses/>.

"""Host header validation (DNS rebinding guard).

A page served from an attacker's domain can make the browser resolve that
domain to the FontSync server and talk to it with the attacker's `Host`.
Requests whose `Host` is not an IP literal, `localhost`, a `*.local` or
`*.ts.net` name, or an entry of `ALLOWED_HOSTS` are refused before reaching
the app: HTTP 400, or WebSocket close 1008.

`ALLOWED_HOSTS` is a comma-separated list of names or `*.suffix` patterns;
`*` disables the guard. It is read from `settings` on every request.
"""

import ipaddress
import re

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.config import settings

# Always accepted, whatever ALLOWED_HOSTS says.
_DEFAULT_NAMES = frozenset({"localhost"})
_DEFAULT_SUFFIXES = (".local", ".ts.net")

_PORT = re.compile(r"[0-9]{1,5}")
_NAME = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*")

_REJECTION = (
    b"Invalid Host header. Add this host name to ALLOWED_HOSTS "
    b"(comma-separated; '*' disables the check)."
)


def _hostname(host_header: str) -> str | None:
    """Lowercased host name of a `Host` header, without port; None if malformed.

    Only ASCII DNS-style names (letters, digits, hyphens, dot-separated labels,
    one optional trailing dot), IPv4 literals and bracketed IPv6 literals pass.
    """
    host = host_header.strip(" \t").lower()
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return None
        rest = host[end + 1 :]
        if rest and not (rest[0] == ":" and _PORT.fullmatch(rest[1:])):
            return None
        inner = host[1:end]
        return inner if ":" in inner and _is_ip_literal(inner) else None
    if host.count(":") == 1:
        host, port = host.split(":")
        if not _PORT.fullmatch(port):
            return None
    elif host.count(":") > 1:
        return None
    host = host.removesuffix(".")
    return host if _NAME.fullmatch(host) else None


def _is_ip_literal(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def _matches(name: str, pattern: str) -> bool:
    if pattern.count(":") == 1:  # tolerate `name:port` entries: the port is ignored
        pattern = pattern.split(":")[0]
    pattern = pattern.removesuffix(".")
    if pattern.startswith("*."):
        return name.endswith(pattern[1:])
    return name == pattern


def host_is_allowed(host_header: str | None, allowed_hosts: str) -> bool:
    """Whether `host_header` is acceptable given the `ALLOWED_HOSTS` value."""
    patterns = [p.strip().lower() for p in allowed_hosts.split(",") if p.strip()]
    if "*" in patterns:
        return True
    if host_header is None:
        return False
    name = _hostname(host_header)
    if name is None:
        return False
    if _is_ip_literal(name) or name in _DEFAULT_NAMES:
        return True
    if name.endswith(_DEFAULT_SUFFIXES):
        return True
    return any(_matches(name, pattern) for pattern in patterns)


_ORIGIN = re.compile(r"(https?)://(\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::([0-9]{1,5}))?")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _parse_origin(value: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) of an `Origin` value; None if not http(s)://host[:port]."""
    match = _ORIGIN.fullmatch(value.strip().lower())
    if match is None:
        return None
    scheme, host, port = match.groups()
    host = host[1:-1] if host.startswith("[") else host.removesuffix(".")
    number = int(port) if port else _DEFAULT_PORTS[scheme]
    return (scheme, host, number) if 0 < number < 65536 else None


def _explicit_port(host_header: str) -> int | None:
    host = host_header.strip(" \t")
    if host.startswith("["):
        rest = host[host.find("]") + 1 :]
        return int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else None
    if host.count(":") == 1:
        port = host.split(":")[1]
        return int(port) if port.isdigit() else None
    return None


def origin_is_allowed(
    origin: str | None,
    host_header: str | None,
    allowed_hosts: str,
    allowed_origins: str,
) -> bool:
    """Whether a WebSocket handshake `Origin` may connect (CSWSH guard).

    No `Origin` (non-browser client): allowed, the token still decides. Else the
    origin must be the server itself as reached (same host as the `Host`
    header, same port — a `Host` without port, as behind a TLS proxy, matches
    the scheme's default port), a host listed explicitly in `ALLOWED_HOSTS`
    (not its defaults, and `*` opens nothing), or an `ALLOWED_ORIGINS` entry
    (`scheme://host[:port]`, comma-separated).
    """
    if origin is None:
        return True
    parsed = _parse_origin(origin)
    if parsed is None:
        return False
    scheme, name, port = parsed
    if host_header is not None and _hostname(host_header) == name:
        host_port = _explicit_port(host_header)
        if port == (host_port if host_port is not None else _DEFAULT_PORTS[scheme]):
            return True
    for entry in allowed_origins.split(","):
        if entry.strip() and _parse_origin(entry) == parsed:
            return True
    for pattern in allowed_hosts.split(","):
        pattern = pattern.strip().lower()
        if pattern and pattern != "*" and _matches(name, pattern):
            return True
    return False


class HostGuardMiddleware:
    """Pure ASGI middleware refusing requests with an unexpected `Host`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        hosts = [
            value.decode("latin-1")
            for key, value in scope.get("headers", ())
            if key == b"host"
        ]
        # Exactly one Host header (RFC 9112 §3.2): a duplicate is refused too.
        host_header = hosts[0] if len(hosts) == 1 else None
        if host_is_allowed(host_header, settings.allowed_hosts):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(_REJECTION)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _REJECTION})
