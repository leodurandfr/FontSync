"""Installation et activation de fonts per-user sur macOS.

Copie les fichiers dans ~/Library/Fonts/ (pas de droits admin nécessaires).
Seuls les formats installables (TTF, OTF, TTC) sont acceptés.

Activation/désactivation : déplace les fonts entre ~/Library/Fonts (actif)
et ~/.fontsync/disabled/ (inactif). Le fichier reste toujours sur le disque.

**Poser ou retirer le fichier ne suffit pas toujours sur macOS 14+.** Si l'index
du système se fige, une font copiée n'existe pour aucune application et une font
retirée reste utilisable — indéfiniment. Chaque opération se termine donc par
`agent.font_registry.reindex()`, dont l'effet n'est jamais immédiat. C'est un
filet, pas la réparation d'un défaut constaté : en régime normal macOS prend
l'ajout au vol en quelques secondes. Voir ce module pour la mesure et les limites.

Sécurité (B7) — deux invariants protègent les données locales de l'utilisateur :

- **Install** : on n'écrase jamais une font homonyme dont le **contenu diffère**
  (une police personnelle de l'utilisateur portant le même nom). Si le nom est
  déjà pris par un contenu différent, la font FontSync est posée sous un nom
  désambiguïsé dérivé de son hash. Un nom déjà occupé par le **même** contenu est
  une no-op idempotente.
- **Uninstall** : la suppression est **gardée par le hash**. On ne supprime qu'un
  fichier dont le contenu correspond exactement au hash demandé ; un fichier
  homonyme au contenu différent n'est jamais touché. L'identification par hash
  reste *stateless* : elle est dérivée du disque réel (re-hachage des candidats),
  pas d'un manifeste mutable.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from agent import font_registry
from agent.paths import fonts_dir, state_dir

logger = logging.getLogger(__name__)

INSTALL_DIR = fonts_dir()
DISABLED_DIR = state_dir() / "disabled"
INSTALLABLE_FORMATS = {".ttf", ".otf", ".ttc"}

_CHUNK_SIZE = 65536  # 64 Ko


def _is_within(path: Path, directory: Path) -> bool:
    """True si `path` est bien contenu dans `directory` (anti path-traversal)."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _hash_or_none(path: Path) -> str | None:
    """SHA-256 du fichier, ou None s'il est illisible (jamais bloquant)."""
    try:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(_CHUNK_SIZE):
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        logger.warning("Impossible de hacher %s", path)
        return None


def _disambiguated_name(safe_name: str, digest: str) -> str:
    """Nom de fichier désambiguïsé dérivé du hash (collision quasi impossible)."""
    p = Path(safe_name)
    return f"{p.stem}__fontsync-{digest[:12]}{p.suffix}"


def _maybe_reindex(refresh_index: bool) -> None:
    """Demande la prise en compte système, sauf si l'appelant la groupe lui-même."""
    if refresh_index:
        font_registry.reindex(INSTALL_DIR)


def install_font(
    filename: str,
    data: bytes,
    *,
    expected_hash: str | None = None,
    refresh_index: bool = True,
) -> Path | None:
    """Installe une font dans ~/Library/Fonts/ sans écraser de font homonyme locale.

    Une font déjà en place (même contenu) repasse elle aussi par la réindexation :
    c'est la signature de l'index figé — fichier présent mais invisible, donc
    inutilisable, et signalé « manquant » par le serveur puisque la découverte
    Core Text ne le voit pas. Réindexer là est auto-guérisseur, et ne coûte rien
    en régime normal (le cas ne se présente pas).

    Args:
        filename: nom du fichier (ex: "Inter-Regular.ttf").
        data: contenu binaire du fichier.
        expected_hash: hash SHA-256 attendu (issu du serveur). S'il est fourni et
            ne correspond pas au contenu reçu, l'installation est refusée
            (téléchargement corrompu).
        refresh_index: déclencher la réindexation macOS (`fontd`/`fontworker`).
            Laisser à True pour une installation isolée. Un appelant qui installe
            un lot doit passer False et appeler `reindex_installed()` **une seule
            fois** à la fin : la relancer par fichier ferait repartir la
            reconstruction de l'index à chaque font.

    Returns:
        Le path d'installation (éventuellement désambiguïsé), ou None si le format
        n'est pas installable, si le contenu est corrompu, ou si l'installation
        ne peut se faire sans écraser un fichier au contenu différent.
    """
    safe_name = Path(filename).name  # Strip directory components
    ext = Path(safe_name).suffix.lower()
    if ext not in INSTALLABLE_FORMATS:
        logger.warning("Format %s non installable, ignoré : %s", ext, safe_name)
        return None

    digest = hashlib.sha256(data).hexdigest()
    if expected_hash is not None and digest != expected_hash:
        logger.error(
            "Hash reçu (%s) ≠ attendu (%s) pour %s : contenu corrompu, refus",
            digest[:12],
            expected_hash[:12],
            safe_name,
        )
        return None

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    dest = INSTALL_DIR / safe_name
    # Sécurité : ne jamais écrire hors de ~/Library/Fonts
    if not _is_within(dest, INSTALL_DIR):
        logger.error("Tentative d'installation hors de ~/Library/Fonts : %s", dest)
        return None

    if not dest.exists():
        dest.write_bytes(data)
        logger.info("Font installée : %s", dest)
        _maybe_reindex(refresh_index)
        return dest

    # Le nom est déjà pris.
    if _hash_or_none(dest) == digest:
        logger.info("Font déjà en place (hash identique) : %s", dest)
        _maybe_reindex(refresh_index)
        return dest

    # Contenu différent : c'est une font homonyme (probablement locale à
    # l'utilisateur). On ne l'écrase pas → installation sous un nom désambiguïsé.
    disambig = INSTALL_DIR / _disambiguated_name(safe_name, digest)
    if disambig.exists():
        if _hash_or_none(disambig) == digest:
            logger.info("Font déjà en place (nom désambiguïsé) : %s", disambig)
            _maybe_reindex(refresh_index)
            return disambig
        logger.error(
            "Impossible d'installer %s sans écraser un fichier différent (%s), ignoré",
            safe_name,
            disambig.name,
        )
        return None

    disambig.write_bytes(data)
    logger.warning(
        "Font homonyme locale préservée ; %s installée sous %s",
        safe_name,
        disambig.name,
    )
    _maybe_reindex(refresh_index)
    return disambig


def reindex_installed() -> bool:
    """Déclenche la réindexation macOS du dossier d'installation.

    À appeler une fois après un lot d'`install_font(..., refresh_index=False)`.
    Retourne True si la réindexation a été amorcée — son effet n'est pas immédiat.
    """
    return font_registry.reindex(INSTALL_DIR)


def uninstall_font(
    filename: str, file_hash: str, *, refresh_index: bool = True
) -> bool:
    """Désinstalle la font de hash `file_hash` de ~/Library/Fonts/ et de disabled.

    La suppression est **gardée par le hash** : seuls les fichiers dont le contenu
    correspond exactement à `file_hash` sont supprimés. Un fichier homonyme au
    contenu différent (font locale de l'utilisateur) n'est jamais touché. Ne
    touche jamais /Library/Fonts ni /System/Library/Fonts.

    Args:
        filename: nom du fichier attendu (ex: "Inter-Regular.ttf"), utilisé comme
            chemin rapide ; non suffisant à lui seul pour autoriser la suppression.
        file_hash: hash SHA-256 de la font à désinstaller (autorité de suppression).
        refresh_index: déclencher la réindexation macOS. Même règle qu'à
            l'installation : un appelant qui traite un lot passe False et groupe
            un seul `reindex_installed()` à la fin.

    Returns:
        True si au moins un fichier correspondant a été supprimé, False sinon.
    """
    safe_name = Path(filename).name
    removed = False
    # Une suppression dans ~/Library/Fonts est aussi invisible du système qu'un
    # ajout tant qu'il n'a pas réindexé : on note s'il faut le lui demander.
    touched_install_dir = False

    def _remove(path: Path, *, from_install_dir: bool, note: str) -> None:
        nonlocal removed, touched_install_dir
        touched_install_dir = touched_install_dir or from_install_dir
        path.unlink()
        removed = True
        logger.info("Font désinstallée%s : %s", note, path)

    # Chemin rapide : noms attendus (nom direct + nom désambiguïsé éventuel),
    # supprimés uniquement si le hash correspond.
    candidate_names = {safe_name, _disambiguated_name(safe_name, file_hash)}
    for directory in (INSTALL_DIR, DISABLED_DIR):
        for name in candidate_names:
            path = directory / name
            if not _is_within(path, directory):
                logger.error(
                    "Tentative de suppression hors de %s : %s", directory, path
                )
                continue
            if path.is_file() and _hash_or_none(path) == file_hash:
                _remove(path, from_install_dir=directory == INSTALL_DIR, note="")

    # Repli : la font a pu être renommée par l'utilisateur. On balaie les dossiers
    # gérés et on ne supprime que ce qui correspond au hash (jamais un homonyme).
    if not removed:
        for directory in (INSTALL_DIR, DISABLED_DIR):
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                if not path.is_file() or path.name in candidate_names:
                    continue
                if _hash_or_none(path) == file_hash:
                    _remove(
                        path,
                        from_install_dir=directory == INSTALL_DIR,
                        note=" (nom divergent)",
                    )

    if touched_install_dir:
        _maybe_reindex(refresh_index)

    if not removed:
        logger.warning(
            "Aucune font de hash %s trouvée pour désinstallation (%s)",
            file_hash[:12],
            safe_name,
        )
    return removed


def activate_font(local_path: str, *, refresh_index: bool = True) -> bool:
    """Active une font en la déplaçant de ~/.fontsync/disabled/ vers ~/Library/Fonts/.

    Le déplacement seul ne suffit pas à coup sûr sur macOS 14+ : il est suivi
    d'une réindexation (cf. `agent.font_registry`), dont l'effet n'est pas
    immédiat. L'activation n'est donc jamais instantanée — l'interface doit
    l'annoncer plutôt que de laisser croire à un échec.

    Args:
        local_path: chemin du fichier (absolu ou nom de fichier)
        refresh_index: déclencher la réindexation macOS. Même règle qu'à
            l'installation : un appelant qui traite un lot passe False et
            groupe un seul `reindex_installed()` à la fin — la relancer par
            font ferait repartir de zéro une reconstruction coûteuse.

    Returns:
        True si la font a été activée, False sinon.
    """
    safe_name = Path(local_path).name
    source = DISABLED_DIR / safe_name
    dest = INSTALL_DIR / safe_name

    # Déjà dans ~/Library/Fonts : le fichier est au bon endroit, mais rien ne dit
    # que le système l'a indexé — on le lui redemande (idempotent).
    if dest.exists():
        logger.info("Font déjà en place : %s", dest)
        _maybe_reindex(refresh_index)
        return True

    if not source.exists():
        logger.warning(
            "Font introuvable dans le dossier disabled pour activation : %s",
            source,
        )
        return False

    # Sécurité : vérifier que la destination reste dans ~/Library/Fonts
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    if not _is_within(dest, INSTALL_DIR):
        logger.error("Tentative d'activation hors de ~/Library/Fonts : %s", dest)
        return False

    shutil.move(str(source), str(dest))
    logger.info("Font activée : %s → %s", source, dest)
    _maybe_reindex(refresh_index)
    return True


def deactivate_font(local_path: str, *, refresh_index: bool = True) -> bool:
    """Désactive une font en la déplaçant de ~/Library/Fonts/ vers ~/.fontsync/disabled/.

    Le fichier reste sur le disque mais n'est plus visible par les applications.
    Là encore le déplacement seul ne désactive rien sur macOS 14+ : tant que le
    système n'a pas réindexé, il continue de servir la font retirée. D'où la
    réindexation qui suit le déplacement — différée, elle aussi.

    Args:
        local_path: chemin du fichier (absolu ou nom de fichier)
        refresh_index: déclencher la réindexation macOS. Même règle qu'à
            l'installation : un appelant qui traite un lot passe False et
            groupe un seul `reindex_installed()` à la fin.

    Returns:
        True si la font a été désactivée, False sinon.
    """
    safe_name = Path(local_path).name
    source = INSTALL_DIR / safe_name
    dest = DISABLED_DIR / safe_name

    # Si la source existe dans ~/Library/Fonts → la déplacer
    if source.exists():
        # Sécurité : ne déplacer que depuis ~/Library/Fonts
        if not _is_within(source, INSTALL_DIR):
            logger.error(
                "Tentative de désactivation hors de ~/Library/Fonts : %s", source
            )
            return False

        DISABLED_DIR.mkdir(parents=True, exist_ok=True)
        # Écraser le fichier dans disabled s'il existe déjà (résidu)
        if dest.exists():
            dest.unlink()
        shutil.move(str(source), str(dest))
        logger.info("Font désactivée : %s → %s", source, dest)
        _maybe_reindex(refresh_index)
        return True

    # Source absente de ~/Library/Fonts — vérifier si déjà dans disabled
    if dest.exists():
        logger.info("Font déjà désactivée : %s", dest)
        return True

    logger.warning(
        "Font introuvable pour désactivation : ni dans %s ni dans %s",
        source,
        dest,
    )
    return False
