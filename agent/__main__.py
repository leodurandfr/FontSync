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

"""Point d'entrée CLI de l'agent FontSync.

Invocations équivalentes : `fontsync-agent <commande>` (console entry point du
paquet, cf. pyproject.toml) ou `python -m agent <commande>`.

Commandes (architecture cible, cf. PLAN.md) :
- `sync`     : synchronisation ponctuelle stateless (déclenchée par launchd ou `listen`).
- `listen`   : flux SSE longue durée qui relance `sync` à chaque signal serveur.
- `setup`    : génère les plists et (re)charge les LaunchAgents launchd (macOS).
- `teardown` : décharge les LaunchAgents et supprime les plists.
- `status`   : état des LaunchAgents.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fontsync-agent",
        description="Agent FontSync — synchronisation de polices.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("sync", help="Synchronisation ponctuelle (stateless)")
    sub.add_parser("listen", help="Flux SSE qui relance `sync` à chaque signal")
    sub.add_parser("setup", help="Installe et charge les LaunchAgents (macOS)")
    sub.add_parser("teardown", help="Décharge et supprime les LaunchAgents")
    sub.add_parser("status", help="État des LaunchAgents")

    args = parser.parse_args(argv)

    if args.command in (None, "sync"):
        from agent.sync_command import main as sync_main

        return sync_main()

    if args.command == "listen":
        from agent.listen_command import main as listen_main

        return listen_main()

    if args.command in ("setup", "teardown", "status"):
        from agent import launchd_setup

        return getattr(launchd_setup, args.command)()

    parser.error(f"commande inconnue : {args.command}")
    return 2  # inatteignable (argparse.error sort), pour le type-checker


if __name__ == "__main__":
    sys.exit(main())
