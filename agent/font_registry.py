"""Prise en compte par macOS des fonts posées dans ~/Library/Fonts (macOS 14+).

**Ceci est un filet de sécurité, pas la réparation d'un défaut constaté.** À
lire avant d'y toucher, pour ne pas refaire la mesure :

En régime normal, `fontd` surveille ~/Library/Fonts et prend un ajout au vol —
mesuré sur ce projet, bibliothèque de ~2800 fichiers, macOS 15 : **2,9 s entre
la copie et la disponibilité**, sans que l'agent fasse quoi que ce soit. La
chaîne d'installation marchait donc déjà. Le cas que ce module couvre est l'état
*dégradé* rapporté sur macOS 14/15, où l'index se fige et n'est plus reconstruit
qu'à l'ouverture de session : la police reste alors invisible de Livre des
polices et des applications, donc de fait non installée, jusqu'au prochain
login, et ni un `touch` du dossier ni l'attente n'y changent rien. Cet état n'a
jamais pu être provoqué sur la machine de développement — le module est là parce
que son coût est nul, pas parce qu'un bug a été observé ici.

Le remède est d'arrêter les deux services de session `fontd` et `fontworker` :
ils repartent à la demande et reconstruisent l'index. `atsutil` ne peut plus
rien (« ATS is not supported starting macOS 14 »).

Coût mesuré du `killall`, même bibliothèque : **aucune dégradation observable**
— le décompte des polices visibles n'a pas bougé pendant le redémarrage (l'index
est relu sur disque, pas reconstruit de zéro). C'est ce qui rend le filet
acceptable en systématique. Si cette hypothèse tombait (machine lente, index
corrompu), le bon réglage serait de ne réindexer que sur preuve de péremption :
un fichier présent sur disque mais absent de la découverte Core Text du sync.

Deux voies ont été écartées, mesurées sur macOS 15 :

- `CTFontManagerRegisterFontsForURLs` en portée **persistante** (2) échoue en
  `paramErr -50` quand le fichier est déjà dans un dossier de polices ; et
  l'utiliser depuis un dossier externe *en plus* de la copie dans
  ~/Library/Fonts additionne les deux voies et duplique massivement les entrées
  dans `fontregistry.user` (mesuré : 595 doublons sur une seule famille).
- La portée **session** (3) rend bien une police utilisable immédiatement, sans
  attendre l'index — mais l'enregistrement **meurt avec le process qui l'a
  fait** (vérifié : enregistrer dans un process qui se termine, puis résoudre la
  police depuis un autre, retombe sur Helvetica). Or `sync` est un process court
  par construction : l'enregistrement serait effacé avant que quiconque puisse
  s'en servir. Sa propagation inter-process s'est en outre montrée erratique
  d'une exécution à l'autre, et il reste invisible de Livre des polices. Le
  raccourci « utilisable tout de suite » n'est donc pas tenable pour un agent
  stateless ; on assume le délai et on l'annonce dans l'interface.

`reindex` est **best-effort et non bloquante** : un échec est journalisé et
renvoie False, jamais une exception. Elle est neutralisée hors macOS, quand
`FONTSYNC_NO_REINDEX` est armé, et — garde-fou important — quand le dossier
touché n'est **pas** le vrai ~/Library/Fonts (tests, et machines simulées via
`FONTSYNC_FONTS_DIR` : on ne perturbe jamais la session de développement).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Majorant du délai avant qu'une font devienne visible après relance de
# `fontd`/`fontworker` — pas une prédiction : en pratique c'est de l'ordre de
# quelques secondes. Sert à formuler l'attente (logs, UI) plutôt qu'à attendre
# réellement : rien n'est bloquant.
REINDEX_DELAY_HINT_SECONDS = 60

_KILLALL = "/usr/bin/killall"
_REINDEX_SERVICES = ("fontd", "fontworker")
_KILLALL_TIMEOUT_SECONDS = 10.0

# Dossier de polices utilisateur réel de macOS — délibérément *pas*
# `agent.paths.fonts_dir()`, qui est surchargeable : c'est justement la
# différence entre les deux qui sert de garde-fou.
_SYSTEM_USER_FONTS_DIR = Path.home() / "Library" / "Fonts"


def _disabled_by_env() -> bool:
    return os.environ.get("FONTSYNC_NO_REINDEX", "").strip() not in ("", "0")


def manages_system_fonts(directory: Path) -> bool:
    """True si agir sur `directory` doit réellement toucher l'index macOS.

    Faux hors macOS, si `FONTSYNC_NO_REINDEX` est armé, ou si `directory` n'est
    pas le vrai ~/Library/Fonts (device simulé via `FONTSYNC_FONTS_DIR`, tests) :
    dans ces cas la session de l'utilisateur ne doit pas être perturbée.
    """
    if sys.platform != "darwin" or _disabled_by_env():
        return False
    try:
        return directory.expanduser().resolve() == _SYSTEM_USER_FONTS_DIR.resolve()
    except OSError:
        return False


def reindex(directory: Path) -> bool:
    """Force macOS à réindexer les dossiers de polices (`killall fontd fontworker`).

    Args:
        directory: dossier qui vient d'être modifié. Sert de garde-fou : la
            réindexation n'a lieu que s'il s'agit du vrai ~/Library/Fonts.

    Returns:
        True si la commande a été lancée. L'effet est **différé** (cf.
        `REINDEX_DELAY_HINT_SECONDS`) : un True ne signifie pas « la police est
        visible », seulement « la reconstruction de l'index est amorcée ».
    """
    if not manages_system_fonts(directory):
        logger.debug("Réindexation ignorée (dossier non système : %s)", directory)
        return False

    try:
        proc = subprocess.run(
            [_KILLALL, *_REINDEX_SERVICES],
            capture_output=True,
            text=True,
            timeout=_KILLALL_TIMEOUT_SECONDS,
            check=False,  # un service absent n'est pas une erreur (cf. plus bas)
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Réindexation des polices impossible (killall)")
        return False

    # `killall` renvoie ≠ 0 dès qu'un des services ne tournait pas (« No matching
    # processes ») : ce n'est pas une erreur, les services démarrent à la demande.
    if proc.returncode != 0:
        logger.debug(
            "killall %s → code %d (%s)",
            " ".join(_REINDEX_SERVICES),
            proc.returncode,
            proc.stderr.strip(),
        )
    logger.info(
        "Réindexation des polices déclenchée ; effet non immédiat "
        "(quelques secondes, jusqu'à ~%d s sur une grosse bibliothèque).",
        REINDEX_DELAY_HINT_SECONDS,
    )
    return True
