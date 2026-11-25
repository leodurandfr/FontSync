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

"""`fontsync-agent login` : connecter ce Mac à un compte FontSync.

Échange email + mot de passe contre un **jeton d'appareil**
(`POST /api/auth/device-login`), rangé dans `server.device_token` de
`~/.fontsync/config.yaml`. Le mot de passe n'est jamais écrit sur le disque.
Le token d'instance hérité, s'il y en avait un, est retiré : le jeton
d'appareil le remplace, et il se révoque seul depuis l'interface web.

L'app Mac fait la même chose depuis son assistant ; cette commande sert aux
installations sans app (dev, scripts).
"""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable

import httpx

from agent.config import AGENT_VERSION, AgentConfig

_TIMEOUT = 15.0


class LoginError(Exception):
    """Connexion refusée ou impossible, avec un message lisible."""


def device_login(
    config: AgentConfig,
    *,
    email: str,
    password: str,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Demande un jeton d'appareil au serveur et l'enregistre dans la config.

    Returns:
        L'email du compte, tel que le serveur l'a normalisé.

    Raises:
        LoginError: identifiants refusés, trop d'essais, serveur injoignable.
    """
    url = f"{config.server_url.rstrip('/')}/api/auth/device-login"
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            resp = client.post(
                url,
                json={
                    "email": email,
                    "password": password,
                    "deviceName": config.get_device_name(),
                },
                headers={"User-Agent": f"fontsync-agent/{AGENT_VERSION}"},
            )
    except httpx.HTTPError as exc:
        raise LoginError(f"Serveur injoignable ({config.server_url}) : {exc}") from exc

    if resp.status_code == 401:
        raise LoginError("Email ou mot de passe incorrect.")
    if resp.status_code == 429:
        raise LoginError("Trop d'essais. Réessayez dans une minute.")
    if resp.status_code == 404:
        raise LoginError(
            "Ce serveur ne connaît pas les comptes : mettez-le à jour, ou "
            "utilisez le token d'instance (`server.token`)."
        )
    if resp.status_code != 201:
        raise LoginError(f"Connexion refusée (HTTP {resp.status_code}).")

    body = resp.json()
    config.device_token = body["token"]
    config.account_email = body.get("user", {}).get("email") or email
    config.server_token = None
    config.save()
    return config.account_email


def main(
    *,
    server: str | None = None,
    email: str | None = None,
    password_stdin: bool = False,
    prompt: Callable[[str], str] = input,
    secret_prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    """Point d'entrée CLI. Renvoie le code de sortie."""
    config = AgentConfig.load()
    if server:
        config.server_url = server.strip()
    address = (email or prompt("Email : ")).strip()
    if password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = secret_prompt("Mot de passe : ")
    if not address or not password:
        print("Email et mot de passe requis.", file=sys.stderr)
        return 2
    try:
        account = device_login(config, email=address, password=password)
    except LoginError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Ce Mac est connecté au compte {account} ({config.server_url}).")
    return 0
