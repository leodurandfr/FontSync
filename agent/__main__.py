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
- `login`    : connecte ce Mac à un compte (email + mot de passe → jeton d'appareil).
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
    sync_parser = sub.add_parser("sync", help="Synchronisation ponctuelle (stateless)")
    sync_parser.add_argument(
        "--wait",
        action="store_true",
        help="attendre la fin d'un sync en cours au lieu de se retirer (appels interactifs)",
    )
    sub.add_parser("listen", help="Flux SSE qui relance `sync` à chaque signal")
    login_parser = sub.add_parser(
        "login", help="Connecte ce Mac à un compte (email + mot de passe)"
    )
    login_parser.add_argument(
        "--server", help="URL du serveur (sinon celle de la config)"
    )
    login_parser.add_argument("--email", help="email du compte (sinon demandé)")
    login_parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="lire le mot de passe sur l'entrée standard (scripts)",
    )
    setup_parser = sub.add_parser(
        "setup", help="Installe et charge les LaunchAgents (macOS)"
    )
    setup_parser.add_argument(
        "--allow-dev-python",
        action="store_true",
        help="accepter l'interpréteur du dossier de build de l'app (développement)",
    )
    sub.add_parser("teardown", help="Décharge et supprime les LaunchAgents")
    sub.add_parser(
        "status", help="État réel des LaunchAgents (actif, en échec, absent)"
    )
    sub.add_parser(
        "doctor", help="Vérifie que les LaunchAgents lancent bien cet interpréteur"
    )

    args = parser.parse_args(argv)

    if args.command in (None, "sync"):
        from agent.sync_command import main as sync_main

        return sync_main(wait=bool(getattr(args, "wait", False)))

    if args.command == "listen":
        from agent.listen_command import main as listen_main

        return listen_main()

    if args.command == "login":
        from agent.login_command import main as login_main

        return login_main(
            server=args.server,
            email=args.email,
            password_stdin=args.password_stdin,
        )

    if args.command == "setup":
        from agent import launchd_setup

        return launchd_setup.setup(allow_dev_python=args.allow_dev_python)

    if args.command in ("teardown", "status", "doctor"):
        from agent import launchd_setup

        return getattr(launchd_setup, args.command)()

    parser.error(f"commande inconnue : {args.command}")
    return 2  # inatteignable (argparse.error sort), pour le type-checker


if __name__ == "__main__":
    sys.exit(main())
