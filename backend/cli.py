"""Commandes d'administration en ligne de commande (dans le conteneur).

Le seul recours quand l'admin a perdu son mot de passe : il n'y a pas d'email
sortant pour un « mot de passe oublié ».

    docker exec -it fontsync python -m backend.cli reset-password <email>
    docker exec -it fontsync python -m backend.cli create-admin <email>
    docker exec -it fontsync python -m backend.cli list-users

Sans `--password`, le mot de passe est demandé deux fois sans écho (ou généré
avec `--generate`, puis affiché une seule fois).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys

from sqlalchemy import select

from backend.database import async_session
from backend.models.user import ROLE_ADMIN, User
from backend.services.accounts import (
    PASSWORD_MIN_LENGTH,
    adopt_orphan_devices,
    count_users,
    create_user,
    get_user_by_email,
    hash_password,
    revoke_user_sessions,
)


def _read_password(args: argparse.Namespace) -> str:
    if args.generate:
        password = secrets.token_urlsafe(12)
        print(f"Mot de passe généré : {password}")
        return password
    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Nouveau mot de passe : ")
        if getpass.getpass("Confirmez : ") != password:
            sys.exit("Les deux saisies diffèrent.")
    if len(password) < PASSWORD_MIN_LENGTH:
        sys.exit(
            f"Le mot de passe doit faire au moins {PASSWORD_MIN_LENGTH} caractères."
        )
    return password


async def _reset_password(args: argparse.Namespace) -> None:
    async with async_session() as db:
        user = await get_user_by_email(db, args.email)
        if user is None:
            sys.exit(f"Aucun compte pour {args.email}.")
        user.password_hash = await hash_password(_read_password(args))
        user.disabled_at = None
        revoked = await revoke_user_sessions(db, user.id)
        await db.commit()
    print(f"Mot de passe de {user.email} changé ; {revoked} session(s) révoquée(s).")


async def _create_admin(args: argparse.Namespace) -> None:
    async with async_session() as db:
        if await get_user_by_email(db, args.email) is not None:
            sys.exit(f"Un compte existe déjà pour {args.email}.")
        first = await count_users(db) == 0
        user = await create_user(
            db, email=args.email, password=_read_password(args), role=ROLE_ADMIN
        )
        adopted = await adopt_orphan_devices(db, user) if first else 0
        await db.commit()
    print(f"Admin {user.email} créé ({adopted} appareil(s) rattaché(s)).")


async def _list_users(_args: argparse.Namespace) -> None:
    async with async_session() as db:
        users = (await db.execute(select(User).order_by(User.created_at))).scalars()
        for user in users:
            state = " (désactivé)" if user.disabled_at else ""
            print(f"{user.role:7} {user.email}{state}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m backend.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func, help_text in (
        ("reset-password", _reset_password, "Change le mot de passe d'un compte"),
        ("create-admin", _create_admin, "Crée un compte administrateur"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("email")
        group = cmd.add_mutually_exclusive_group()
        group.add_argument("--password", help="Mot de passe (sinon demandé)")
        group.add_argument("--generate", action="store_true", help="En générer un")
        cmd.set_defaults(func=func)

    listing = sub.add_parser("list-users", help="Liste les comptes")
    listing.set_defaults(func=_list_users)

    args = parser.parse_args(argv)
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
