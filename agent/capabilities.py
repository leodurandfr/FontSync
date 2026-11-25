"""Capabilities this agent announces to the server at register time (B-32).

The server relies on them rather than on ``agent_version``
(``backend/services/capabilities.py``): it infers deletions only from an agent
that declares its whole library, and refuses deactivation or deletion
propagation for an agent that would not apply them. Never announce a
capability the agent does not fully honour.

- ``full-declaration``: every delta lists all fonts found on disk, so a
  missing hash means a missing file.
- ``deactivate``: honours ``toDeactivate`` (moves files to and from the
  disabled folder).
- ``uninstall``: honours ``toUninstall`` when deletion propagation is on.
"""

from __future__ import annotations

CAPABILITIES: tuple[str, ...] = ("full-declaration", "deactivate", "uninstall")
