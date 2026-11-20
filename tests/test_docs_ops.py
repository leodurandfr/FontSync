"""Docs d'exploitation alignées sur la prod (P1-8e, B-53, B-177).

- Plus d'ancien canal WebSocket agent (supprimé côté serveur, l'agent écoute la
  SSE) ni de script qui le vise ; plus du décompte périmé de la bibliothèque.
- La CHECKLIST E2E et DEVELOPMENT §6 réécrivent `~/.fontsync/config.yaml` : une
  mise en garde (jamais sur un Mac de prod, compte macOS dédié) doit précéder la
  première commande qui le fait.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHECKLIST = REPO / "tests" / "e2e" / "CHECKLIST.md"
DEVELOPMENT = REPO / "DEVELOPMENT.md"
# Écrits par morceaux pour ne pas se trouver eux-mêmes.
STALE = ["ws/" + "agent", "22" + "96"]
# Archives de chantier (historique daté, pas de la doc d'exploitation).
HISTORY = ["docs/PLAN-ETATS-FONTS.md", "docs/BRIEF-ETATS-FONTS.md"]
# Toute écriture du config.yaml de l'agent : redirection, tee, cp, mv.
CONFIG_WRITE = re.compile(
    # `>` en début de ligne = citation Markdown, pas une redirection.
    r"(?:(?<!\n)>|\btee\b|\bcp\b|\bmv\b)[^\n]*?"
    r"(?:~|\$HOME|\$\{HOME\})/\.fontsync/config\.yaml"
)
PROD = re.compile(r"\bprod(?:uction)?\b", re.IGNORECASE)
# Tolère le retour à la ligne et le préfixe « > » d'une citation Markdown.
_GAP = r"(?:\s|>)+"
WARNING = re.compile(
    rf"compte{_GAP}macOS{_GAP}dédié|dedicated{_GAP}macOS{_GAP}account", re.IGNORECASE
)


def tracked_matches(needle: str) -> list[str]:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != REPO.resolve():
        pytest.skip("pas dans le dépôt FontSync (copie sans .git)")
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-F",
            needle,
            "--",
            ":!alembic",
            *(f":!{h}" for h in HISTORY),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        pytest.skip(f"git grep indisponible : {result.stderr.strip()}")
    return result.stdout.splitlines()


@pytest.mark.parametrize("needle", STALE)
def test_no_stale_reference_left(needle: str) -> None:
    assert tracked_matches(needle) == []


def test_dead_ws_script_is_gone() -> None:
    assert not (REPO / "scripts" / "test_ws.py").exists()


_CFG = "/.fontsync/config.yaml"


@pytest.mark.parametrize(
    ("line", "is_write"),
    [
        (f"cat > ~{_CFG} <<YAML", True),
        (f"cat >~{_CFG}", True),
        (f"echo x | tee ~{_CFG}", True),
        (f'cat > "$HOME{_CFG}"', True),
        (f"cp sample.yaml ${{HOME}}{_CFG}", True),
        (f"mv new.yaml ~{_CFG}", True),
        (f"\n> This checklist rewrites `~{_CFG}`.", False),
        (f"Edit ~{_CFG} by hand.", False),
    ],
)
def test_config_write_pattern(line: str, is_write: bool) -> None:
    assert bool(CONFIG_WRITE.search(line)) is is_write


@pytest.mark.parametrize("doc", [CHECKLIST, DEVELOPMENT], ids=lambda p: p.name)
def test_warning_precedes_the_first_config_rewrite(doc: Path) -> None:
    text = doc.read_text()
    first_write = CONFIG_WRITE.search(text)
    assert first_write is not None, "plus d'écriture du config.yaml : test à revoir"
    warning = WARNING.search(text)
    assert warning is not None, "mise en garde absente"
    assert warning.start() < first_write.start()
    # La mise en garde nomme la production, juste avant le compte dédié.
    assert PROD.search(text[max(0, warning.start() - 600) : warning.start()])


def test_development_documents_the_reference_deployment() -> None:
    text = DEVELOPMENT.read_text()
    match = re.search(
        r"^## Deploying the reference instance\n(.*?)^## ",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    body = match.group(1)
    for needle in ("digest", "Back up", "restore", "pendingConfirmation"):
        assert needle in body, needle
