"""Installation / désinstallation des LaunchAgents de l'agent (macOS).

Ce module absorbe la logique historiquement portée par
`agent/launchd/install.sh` (cf. PLAN.md B10) : résolution du Python,
substitution des gabarits *.plist, `launchctl bootstrap/bootout`, kickstart.
Les sous-commandes CLI `setup` / `teardown` / `status` (`agent/__main__.py`)
s'appuient dessus, de sorte que tous les canaux de packaging (Homebrew, .pkg,
installation manuelle) appellent la même CLI.

Deux jobs (cf. PLAN.md B8 / SPECS.md §6.10) :
- `com.fontsync.sync`   : commande `sync` déclenchée (WatchPaths + StartInterval + RunAtLoad)
- `com.fontsync.listen` : process SSE long-vécu (KeepAlive + RunAtLoad)

Les fonctions de rendu (`render_plist`, `write_plists`) sont des opérations
pures côté filesystem, indépendantes de la plateforme et donc testables
partout ; seules `setup` / `teardown` / `status` parlent à `launchctl`.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

# Gabarits embarqués dans le paquet (cf. package-data du pyproject).
TEMPLATE_DIR = Path(__file__).resolve().parent / "launchd"
PACKAGE_DIR = Path(__file__).resolve().parent

LABELS = ("com.fontsync.sync", "com.fontsync.listen")
SUBSTITUTION_TOKENS = ("@PYTHON@", "@WORKDIR@", "@HOME@", "@LOGDIR@")

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = Path.home() / "Library" / "Logs" / "FontSync"


def is_macos() -> bool:
    """True si l'on tourne sur macOS (les LaunchAgents y sont spécifiques)."""
    return sys.platform == "darwin"


def resolve_python(env: dict[str, str] | None = None) -> str:
    """Python à inscrire dans les plists.

    Priorité : `$FONTSYNC_PYTHON`, sinon l'interpréteur courant
    (`sys.executable`). En invocation normale (`fontsync-agent setup` ou
    `python -m agent setup`), `sys.executable` est déjà le bon venv — celui où
    l'agent est importable —, donc plus besoin de deviner un `.venv`.
    """
    env = os.environ if env is None else env
    override = env.get("FONTSYNC_PYTHON")
    return override if override else sys.executable


def workdir() -> str:
    """Répertoire à mettre en `WorkingDirectory`/`PYTHONPATH`.

    C'est le parent du paquet `agent` : la racine du repo en mode développement,
    le `site-packages` en mode installé. Dans les deux cas, l'ajouter au
    `PYTHONPATH` rend `import agent` fiable (redondant mais inoffensif une fois
    installé).
    """
    return str(PACKAGE_DIR.parent)


def render_plist(
    label: str, *, python: str, workdir: str, home: str, logdir: str
) -> str:
    """Substitue les jetons d'un gabarit et valide le plist résultant.

    Lève si le plist n'est pas parsable (`plistlib`) ou si un jeton reste non
    substitué — équivalent portable du `plutil -lint` de l'ancien script.
    """
    rendered = (TEMPLATE_DIR / f"{label}.plist").read_text()
    for token, value in (
        ("@PYTHON@", python),
        ("@WORKDIR@", workdir),
        ("@HOME@", home),
        ("@LOGDIR@", logdir),
    ):
        rendered = rendered.replace(token, value)

    leftover = [t for t in SUBSTITUTION_TOKENS if t in rendered]
    if leftover:
        raise ValueError(f"jetons non substitués dans {label}.plist : {leftover}")

    plistlib.loads(rendered.encode())  # lève si le plist est invalide
    return rendered


def write_plists(
    target_dir: Path, *, python: str, workdir: str, home: str, logdir: str
) -> list[Path]:
    """Rend et écrit (atomiquement) les deux plists dans `target_dir`.

    Retourne les chemins écrits, dans l'ordre de `LABELS`.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for label in LABELS:
        rendered = render_plist(
            label, python=python, workdir=workdir, home=home, logdir=logdir
        )
        target = target_dir / f"{label}.plist"
        tmp = target.with_suffix(".plist.tmp")
        tmp.write_text(rendered)
        os.replace(tmp, target)
        written.append(target)
    return written


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Lance `launchctl <args>` sans jamais lever (résultat inspectable)."""
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _is_loaded(domain: str, label: str) -> bool:
    """True si le job est encore enregistré dans le domaine launchd."""
    return _launchctl("print", f"{domain}/{label}").returncode == 0


def _bootout_and_wait(domain: str, label: str, timeout: float = 8.0) -> None:
    """Décharge un job et **attend** sa disparition effective.

    `launchctl bootout` est asynchrone : il rend la main avant que le service
    soit réellement détruit, surtout pour un job KeepAlive avec un process vivant
    (`com.fontsync.listen`). Un `bootstrap` lancé trop tôt échoue alors en
    `Bootstrap failed: 5: Input/output error`. On poll jusqu'à ce que le job
    soit absent (ou jusqu'au timeout) pour rendre la réinstallation idempotente.
    """
    _launchctl("bootout", f"{domain}/{label}")  # ignore l'absence
    deadline = time.monotonic() + timeout
    while _is_loaded(domain, label) and time.monotonic() < deadline:
        time.sleep(0.2)


def setup(env: dict[str, str] | None = None) -> int:
    """Génère les plists et (re)charge les deux jobs launchd."""
    if not is_macos():
        print("[fontsync] Les LaunchAgents sont spécifiques à macOS.", file=sys.stderr)
        return 1

    python = resolve_python(env)
    home = str(Path.home())
    wd = workdir()
    domain = _domain()

    print(f"[fontsync] Python       : {python}")
    print(f"[fontsync] WorkingDir   : {wd}")
    print(f"[fontsync] LaunchAgents : {LAUNCH_AGENTS_DIR}")

    probe = subprocess.run(
        [python, "-c", "import agent"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        print(
            "[fontsync] Attention : 'agent' n'est pas importable par ce Python "
            "— vérifier l'installation (pip install -e . ou la formula).",
            file=sys.stderr,
        )

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    written = write_plists(
        LAUNCH_AGENTS_DIR, python=python, workdir=wd, home=home, logdir=str(LOG_DIR)
    )

    for label, target in zip(LABELS, written):
        _bootout_and_wait(domain, label)  # décharge + attend la disparition réelle
        result = _launchctl("bootstrap", domain, str(target))
        if result.returncode != 0:
            # Un résidu a pu survivre au 1er bootout (race async) : on réessaie
            # une fois après une nouvelle attente effective.
            _bootout_and_wait(domain, label)
            result = _launchctl("bootstrap", domain, str(target))
        if result.returncode != 0:
            print(
                f"[fontsync] Échec du chargement de {label} : "
                f"{result.stderr.strip() or result.stdout.strip()}",
                file=sys.stderr,
            )
            return 1
        print(f"[fontsync] Chargé : {label}")

    # Un premier sync immédiat (utile à la 1re installation).
    _launchctl("kickstart", f"{domain}/com.fontsync.sync")
    print(f"[fontsync] Installation terminée. Logs : {LOG_DIR}")
    return 0


def teardown(env: dict[str, str] | None = None) -> int:
    """Décharge les deux jobs et supprime les plists installés."""
    if not is_macos():
        print("[fontsync] Les LaunchAgents sont spécifiques à macOS.", file=sys.stderr)
        return 1

    domain = _domain()
    for label in LABELS:
        _launchctl("bootout", f"{domain}/{label}")
        target = LAUNCH_AGENTS_DIR / f"{label}.plist"
        target.unlink(missing_ok=True)
        print(f"[fontsync] Déchargé et supprimé : {label}")

    print(f"[fontsync] Logs conservés dans {LOG_DIR} (à supprimer manuellement).")
    return 0


def status(env: dict[str, str] | None = None) -> int:
    """Affiche l'état (chargé/absent) des deux jobs."""
    if not is_macos():
        print("[fontsync] Les LaunchAgents sont spécifiques à macOS.", file=sys.stderr)
        return 1

    domain = _domain()
    for label in LABELS:
        result = _launchctl("print", f"{domain}/{label}")
        state = "chargé" if result.returncode == 0 else "absent"
        print(f"[fontsync] {label} : {state}")
    return 0
