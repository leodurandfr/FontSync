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
import os
import shutil
from enum import StrEnum
from pathlib import Path

from agent import font_registry
from agent.paths import fonts_dir, state_dir

logger = logging.getLogger(__name__)

INSTALL_DIR = fonts_dir()
DISABLED_DIR = state_dir() / "disabled"
INSTALLABLE_FORMATS = {".ttf", ".otf", ".ttc"}

_CHUNK_SIZE = 65536  # 64 Ko


class MoveResult(StrEnum):
    """Issue d'une activation ou d'une désactivation.

    Seul `MOVED` (et, pour une désactivation, `DEDUPLICATED`) change ce que
    voit le système : c'est ce qui justifie une réindexation. Les autres
    issues ne doivent jamais en déclencher — une activation « déjà faite »
    comptée comme réussie relançait `fontd` à chaque sync (M-02).
    """

    MOVED = "moved"  # fichier déplacé (éventuellement sous un nom désambiguïsé)
    DEDUPLICATED = "deduplicated"  # doublon exact (même hash) retiré de la source
    ALREADY = "already"  # le contenu demandé est déjà à sa place, rien à faire
    MISSING = "missing"  # introuvable des deux côtés
    CHANGED = "changed"  # le fichier n'a plus le contenu demandé : rien ne bouge
    CONFLICT = "conflict"  # nom et nom désambiguïsé pris par d'autres contenus
    REFUSED = "refused"  # chemin hors des dossiers gérés, ou lien symbolique

    def __bool__(self) -> bool:
        raise TypeError(
            "MoveResult n'a pas de valeur de vérité : comparer à une issue précise"
        )


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


def _move_no_clobber(source: Path, dest: Path) -> bool:
    """Déplace `source` en `dest` seulement si `dest` n'existe pas.

    `shutil.move`/`os.rename` remplacent sans rien dire un fichier apparu
    entre la vérification et le déplacement ; un lien dur échoue au contraire
    (`FileExistsError`). Repli hors volume : copie en création exclusive.

    Returns:
        False si `dest` existe déjà (rien n'a bougé).
    """
    try:
        os.link(source, dest)
    except FileExistsError:
        return False
    except OSError:
        try:
            with open(source, "rb") as src, open(dest, "xb") as dst:
                shutil.copyfileobj(src, dst)
        except FileExistsError:
            return False
        shutil.copystat(source, dest)
    os.unlink(source)
    return True


def _write_new(dest: Path, data: bytes) -> bool:
    """Crée `dest` avec `data`, jamais par-dessus un fichier existant."""
    try:
        with open(dest, "xb") as handle:
            handle.write(data)
    except FileExistsError:
        logger.error("Fichier apparu entre-temps, non écrasé : %s", dest)
        return False
    return True


def _is_exact_copy(candidate: Path, source: Path, digest: str) -> bool:
    """`candidate` est un fichier ordinaire, distinct de `source`, de même hash."""
    if candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        if os.path.samefile(candidate, source):
            return False
    except OSError:
        return False
    return _hash_or_none(candidate) == digest


def _find_copy(directory: Path, name: str, digest: str | None) -> bool:
    """Le contenu `digest` (ou, à défaut, le nom) est-il déjà rangé dans `directory` ?"""
    if digest is None:
        return (directory / name).exists()
    for candidate in (directory / name, directory / _disambiguated_name(name, digest)):
        if (
            not candidate.is_symlink()
            and candidate.is_file()
            and _hash_or_none(candidate) == digest
        ):
            return True
    return False


def _move_without_overwrite(
    source: Path, target_dir: Path, expected_hash: str | None = None
) -> MoveResult:
    """Déplace `source` dans `target_dir` sans jamais écraser un autre contenu.

    La source doit avoir le contenu attendu (`expected_hash`, si fourni) : un
    fichier remplacé depuis le scan ne bouge pas. Nom libre → déplacement. Nom
    pris par le même contenu → la source est un doublon exact : elle seule est
    retirée. Nom pris par un autre contenu → déplacement sous le nom
    désambiguïsé dérivé du hash (même règle qu'`install_font`) ; s'il est lui
    aussi pris par un autre contenu, rien ne bouge. Les liens symboliques ne
    sont jamais suivis ni déplacés.
    """
    if source.is_symlink():
        logger.error("Lien symbolique ignoré : %s", source)
        return MoveResult.REFUSED
    digest = _hash_or_none(source)
    if digest is None:
        return MoveResult.CONFLICT
    if expected_hash is not None and digest != expected_hash:
        logger.warning(
            "%s n'a plus le contenu attendu (%s ≠ %s) : rien ne bouge",
            source,
            digest[:12],
            expected_hash[:12],
        )
        return MoveResult.CHANGED

    target_dir.mkdir(parents=True, exist_ok=True)
    for dest in (
        target_dir / source.name,
        target_dir / _disambiguated_name(source.name, digest),
    ):
        if dest.is_symlink() or not _is_within(dest, target_dir):
            continue
        if _move_no_clobber(source, dest):
            if dest.name != source.name:
                logger.warning(
                    "Homonyme préservé dans %s ; %s déplacée sous %s",
                    target_dir,
                    source.name,
                    dest.name,
                )
            return MoveResult.MOVED
        if _is_exact_copy(dest, source, digest):
            source.unlink()
            logger.info("Doublon exact retiré : %s (identique à %s)", source, dest)
            return MoveResult.DEDUPLICATED
    logger.error(
        "Impossible de déplacer %s sans écraser un fichier différent dans %s",
        source,
        target_dir,
    )
    return MoveResult.CONFLICT


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

    # Un homonyme au contenu différent attend dans disabled/ : l'installer sous
    # ce nom bloquerait sa réactivation. On prend directement le nom
    # désambiguïsé.
    parked = DISABLED_DIR / safe_name
    if (
        not dest.exists()
        and parked.is_file()
        and _hash_or_none(parked) not in (None, digest)
    ):
        dest = INSTALL_DIR / _disambiguated_name(safe_name, digest)
        if dest.exists() and _hash_or_none(dest) == digest:
            logger.info("Font déjà en place (nom désambiguïsé) : %s", dest)
            _maybe_reindex(refresh_index)
            return dest
        if dest.exists():
            logger.error(
                "Impossible d'installer %s sans écraser un fichier différent (%s)",
                safe_name,
                dest.name,
            )
            return None
        if not _write_new(dest, data):
            return None
        logger.warning(
            "Homonyme désactivé préservé ; %s installée sous %s", safe_name, dest.name
        )
        _maybe_reindex(refresh_index)
        return dest

    if not dest.exists():
        if not _write_new(dest, data):
            return None
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

    if not _write_new(disambig, data):
        return None
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


def _managed_source(local_path: str, directory: Path) -> Path:
    """Le fichier visé : le chemin scanné tel quel s'il est absolu, sinon un nom
    dans `directory`. Agir sur le chemin réel (sous-dossiers compris), et non
    sur `directory/<nom>`, évite de déplacer un homonyme à la place de la font
    demandée."""
    path = Path(local_path)
    return path if path.is_absolute() else directory / path.name


def activate_font(
    local_path: str,
    *,
    expected_hash: str | None = None,
    refresh_index: bool = True,
) -> MoveResult:
    """Active une font en la déplaçant de ~/.fontsync/disabled/ vers ~/Library/Fonts/.

    Ne remplace jamais un fichier de contenu différent : si le nom est pris
    dans ~/Library/Fonts par un homonyme, la font est posée sous le nom
    désambiguïsé ; si le nom est pris par le même contenu, la copie de
    disabled/ est un doublon exact et seule elle est retirée (la font était
    déjà active : rien à réindexer).

    Le déplacement seul ne suffit pas à coup sûr sur macOS 14+ : il est suivi
    d'une réindexation (cf. `agent.font_registry`), dont l'effet n'est pas
    immédiat — et seulement s'il y a eu déplacement.

    Args:
        local_path: chemin du fichier scanné (absolu) ou nom de fichier
        expected_hash: contenu attendu (hash du scan) ; un fichier qui ne l'a
            plus ne bouge pas (`CHANGED`).
        refresh_index: déclencher la réindexation macOS. Un appelant qui traite
            un lot passe False et groupe un seul `reindex_installed()` à la fin.

    Returns:
        `MOVED` si la font vient d'être rendue active ; `DEDUPLICATED` si elle
        l'était déjà (copie de disabled/ retirée) ; `ALREADY` si le contenu
        demandé est déjà dans ~/Library/Fonts ; `MISSING`, `CHANGED`,
        `CONFLICT` ou `REFUSED` sinon.
    """
    source = _managed_source(local_path, DISABLED_DIR)
    if source.is_symlink() or not _is_within(source, DISABLED_DIR):
        logger.error(
            "Activation refusée (hors du dossier disabled ou lien) : %s", source
        )
        return MoveResult.REFUSED
    if not source.is_file():
        if _find_copy(INSTALL_DIR, source.name, expected_hash):
            return MoveResult.ALREADY
        logger.warning(
            "Font introuvable dans le dossier disabled pour activation : %s",
            source,
        )
        return MoveResult.MISSING

    result = _move_without_overwrite(source, INSTALL_DIR, expected_hash)
    if result is MoveResult.MOVED:
        logger.info("Font activée : %s", source)
        _maybe_reindex(refresh_index)
    return result


def deactivate_font(
    local_path: str,
    *,
    expected_hash: str | None = None,
    refresh_index: bool = True,
) -> MoveResult:
    """Désactive une font en la déplaçant de ~/Library/Fonts/ vers ~/.fontsync/disabled/.

    Le fichier reste sur le disque mais n'est plus visible par les applications.
    Ne remplace jamais un fichier de contenu différent déjà rangé dans
    disabled/ (une autre version désactivée plus tôt sous le même nom) : la
    font est rangée sous le nom désambiguïsé. Si disabled/ contient déjà
    exactement le même contenu, seule la copie active est retirée.

    Le retrait ne désactive rien sur macOS 14+ tant que le système n'a pas
    réindexé : d'où la réindexation qui suit — différée, elle aussi.

    Args:
        local_path: chemin du fichier scanné (absolu, sous-dossiers compris) ou
            nom de fichier
        expected_hash: contenu attendu (hash du scan) ; un fichier qui ne l'a
            plus ne bouge pas (`CHANGED`).
        refresh_index: déclencher la réindexation macOS (groupée par l'appelant
            d'un lot).

    Returns:
        `MOVED` ou `DEDUPLICATED` si la font a quitté ~/Library/Fonts ;
        `ALREADY` si le contenu demandé attend déjà dans disabled/ ;
        `MISSING`, `CHANGED`, `CONFLICT` ou `REFUSED` sinon.
    """
    source = _managed_source(local_path, INSTALL_DIR)
    if source.is_symlink() or not _is_within(source, INSTALL_DIR):
        logger.error(
            "Désactivation refusée (hors de ~/Library/Fonts ou lien) : %s", source
        )
        return MoveResult.REFUSED
    if not source.is_file():
        if _find_copy(DISABLED_DIR, source.name, expected_hash):
            logger.info("Font déjà désactivée : %s", source.name)
            return MoveResult.ALREADY
        logger.warning(
            "Font introuvable pour désactivation : ni dans %s ni dans %s",
            INSTALL_DIR,
            DISABLED_DIR,
        )
        return MoveResult.MISSING

    result = _move_without_overwrite(source, DISABLED_DIR, expected_hash)
    if result in (MoveResult.MOVED, MoveResult.DEDUPLICATED):
        logger.info("Font désactivée : %s", source)
        _maybe_reindex(refresh_index)
    return result
