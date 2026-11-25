"""Capabilities this agent announces to the server at register time (B-32).

The server stores them on the device and exposes them; nothing is gated on
them yet. A future server can then tell an agent that declares its whole
library, deactivates and uninstalls from an older one that does not, instead
of guessing from ``agent_version``.

- ``full-declaration``: every delta lists all fonts found on disk, so a
  missing hash means a missing file.
- ``deactivate``: honours ``toDeactivate`` (moves files to and from the
  disabled folder).
- ``uninstall``: honours ``toUninstall`` when deletion propagation is on.
"""

from __future__ import annotations

CAPABILITIES: tuple[str, ...] = ("full-declaration", "deactivate", "uninstall")
