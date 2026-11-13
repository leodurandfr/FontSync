"""Doublons de **face** : une seule police, plusieurs fichiers.

Le hash ne voit rien. Mesuré sur une bibliothèque réelle de 3 328 fichiers :
**0 groupe** de doublons par hash, pour **918 faces** présentes en plusieurs
exemplaires et **1 019 fichiers en trop**. « GT Maru Mono Bold Oblique.otf »,
« GT-Maru-Mono-Bold-Oblique.ttf » et « GTMaruMono-BoldOblique.otf » ont trois
noms et trois empreintes pour une seule face — et Livre des polices les affiche
en triple. Un taux de détection nul, donc, sur ce qui gêne vraiment.

L'identité d'une face est `(nameID 16 sinon 1, nameID 17 sinon 2, italique,
graisse, chasse)` — famille typographique, style déclaré, et les trois axes de
l'en-tête OS/2. Le style déclaré ne suffit pas : « Normal » romain et « Normal »
italique, ou « Text » 400 et « Text » 700, sont deux faces (M-37, audit
2026-10). Tout est **déjà en base** (`font_analyzer`) : rien à re-parser, rien à
migrer. Prix assumé de la prudence : deux exports d'une même face dont la
graisse déclarée diffère (800 et 850, ou un bit italique mal posé) ne sont plus
rapprochés — le manque va dans le sens sûr.

**Ce module ne supprime jamais de lui-même.** Il propose : un gardé, des
redondants. C'est l'appelant — un geste explicite de l'utilisateur — qui tranche,
et ce qui part va en corbeille, récupérable.

Trois règles protègent contre la perte de matière :

1. **Identité incomplète ou suspecte, aucun regroupement.** Sans famille *et*
   sans style, on ne sait pas ce qu'on tient ; une famille `false`/`null`/
   `none`/`undefined` trahit un outil qui a écrit une variable vide. Une police
   malformée est stockée avec des métadonnées partielles (cf. CLAUDE.md) ; elle
   ne doit pas pour autant se retrouver empilée avec ses semblables sous une
   identité vide ou factice.
2. **Un fichier qui couvre plusieurs styles n'est jamais proposé au retrait.**
   Une police variable déclare plusieurs instances nommées depuis un seul
   fichier, une collection `.ttc` embarque plusieurs polices ; dans les deux cas
   l'identité lue ne décrit que la première. Les retirer perdrait le reste. Ils
   sont donc toujours gardés, et préférés comme gardé — c'est la traduction
   directe de « préférer le fichier qui couvre le plus de styles ».
3. **Le gardé est le plus complet des installables** : une TTF/OTF passe devant
   une WOFF même plus riche (une police web n'est jamais installée), et une face
   dont seuls des fichiers web sont gardés d'office (variable ou collection
   WOFF) garde aussi sa meilleure copie installable. Le classement est *total* :
   à caractéristiques égales l'empreinte départage, donc deux exécutions donnent
   le même résultat. Une proposition qui changerait d'une fois sur l'autre ne
   serait pas révisable.

Limite assumée : une variable n'est rapprochée des statiques qu'elle redit que
si le style qu'elle *déclare* coïncide. Ses instances nommées (`fvar`) ne sont
pas stockées ; les rapprocher toutes demanderait une migration et une
ré-analyse de la bibliothèque. Sur la mesure ci-dessus (identité à deux champs),
cela concernait 87 des 918 faces — le manque va toujours dans le sens sûr : ces
groupes ne sont pas détectés, jamais mal résolus. Remesuré avec l'identité à
cinq champs sur la bibliothèque du 10 août 2026 : 917 → 913 groupes, 1 015 →
1 001 fichiers proposés.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device_font import DeviceFont
from backend.models.font import Font

logger = logging.getLogger(__name__)

# Départage à couverture égale. Le rang n'exprime pas une qualité mais une
# préférence stable : l'outline du fondeur d'abord, puis l'installable, puis le
# web — qu'on ne propose jamais à l'installation système (cf. CLAUDE.md).
_FORMAT_RANK: dict[str, int] = {"otf": 0, "ttf": 1, "ttc": 2, "woff2": 3, "woff": 4}
_FORMAT_RANK_UNKNOWN = 9

_COLLECTION_FORMATS = frozenset({"ttc", "otc"})
# Formats proposés à l'installation système (jamais WOFF/WOFF2, cf. CLAUDE.md).
_INSTALLABLE_FORMATS = frozenset({"otf", "ttf", "ttc", "otc"})

# Familles qui trahissent des métadonnées cassées (un outil a écrit la valeur
# d'une variable vide) : les regrouper empilerait des polices sans rapport.
_BOGUS_FAMILIES = frozenset({"false", "null", "none", "undefined"})

# (famille, sous-famille, italique, graisse, chasse), normalisés. La
# sous-famille déclarée ne suffit pas : « Normal » romain et « Normal »
# italique, ou « Text » 400 et « Text » 700, sont deux faces (M-37).
FaceKey = tuple[str, str, str, str, str]

# Séparateur d'identité côté API. Un caractère de contrôle (Unit Separator)
# plutôt qu'un « / » ou un « | » : ceux-là apparaissent dans de vrais noms de
# famille, et un aller-retour JSON re-couperait la clé au mauvais endroit.
_KEY_SEPARATOR = "\x1f"


def encode_key(key: FaceKey) -> str:
    """Sérialise une identité de face pour l'API."""
    return _KEY_SEPARATOR.join(key)


def decode_key(raw: str) -> FaceKey | None:
    """Relit une identité sérialisée, ou None si elle est malformée (dont une
    clé à deux champs d'avant M-37, envoyée par une page restée ouverte)."""
    parts = raw.split(_KEY_SEPARATOR)
    if len(parts) != 5:
        return None
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def covers_several_styles(font: Font) -> bool:
    """Ce fichier porte-t-il plus que la face qu'il déclare ?

    Vrai pour une police variable (instances nommées) et pour une collection
    (plusieurs polices dans un fichier). Dans les deux cas `subfamily_name` ne
    décrit que la première : le retirer perdrait le reste, silencieusement.
    """
    return bool(font.is_variable) or font.file_format.lower() in _COLLECTION_FORMATS


def _normalize(value: str) -> str:
    """Casse et espacement ne font pas deux faces différentes.

    On ne va pas plus loin : retirer tirets et espaces confondrait des styles
    réellement distincts (« Semi Bold » et « Semibold » sont la même face, mais
    « Condensed » et « Con-densed » n'existent pas — le risque est asymétrique).
    """
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _axis(value: object) -> str:
    return "" if value is None else str(int(value))


def face_key(font: Font) -> FaceKey | None:
    """Identité de face, ou None si elle est incomplète ou suspecte (cf. règle 1).

    Suspecte : une famille `false`/`null`/`none`/`undefined` (valeur d'une
    variable vide écrite par un outil) — ces polices sont écartées du
    recensement plutôt qu'empilées à tort. Une famille égale au nom PostScript
    n'est PAS écartée : c'est le cas normal d'un Regular à nom d'un seul mot
    (« Georgia »), et le nom PostScript étant propre à une face, l'égalité ne
    peut pas réunir deux faces différentes.
    """
    family = (font.family_name or "").strip()
    subfamily = (font.subfamily_name or "").strip()
    if not family or not subfamily:
        return None
    normalized = _normalize(family)
    if normalized in _BOGUS_FAMILIES:
        return None
    return (
        normalized,
        _normalize(subfamily),
        _axis(font.is_italic),
        _axis(font.weight_class),
        _axis(font.width_class),
    )


def _installable(font: Font) -> bool:
    return font.file_format.lower() in _INSTALLABLE_FORMATS


def _rank(font: Font) -> tuple:
    """Clé de tri : le meilleur candidat au rôle de gardé vient en premier.

    Ordre : couvre plusieurs styles, puis installable (une WOFF plus riche ne
    passe jamais devant la seule TTF/OTF de la face : la garder retirerait la
    dernière copie installable), puis couverture (glyphes, scripts, points de
    code), format, taille, et enfin empreinte — cette dernière garantit un
    ordre **total**, donc une proposition reproductible.
    """
    unicode_ranges = font.unicode_ranges or {}
    return (
        0 if covers_several_styles(font) else 1,
        0 if _installable(font) else 1,
        -(font.glyph_count or 0),
        -len(font.supported_scripts or []),
        -sum(v for v in unicode_ranges.values() if isinstance(v, int)),
        _FORMAT_RANK.get(font.file_format.lower(), _FORMAT_RANK_UNKNOWN),
        -font.file_size,
        font.file_hash,
    )


@dataclass
class DuplicateGroup:
    """Une face, et les fichiers qui la portent."""

    family: str
    """Nom de famille tel qu'affiché (celui du gardé, non normalisé)."""

    subfamily: str
    """Style tel qu'affiché (celui du gardé)."""

    key: FaceKey
    """Identité normalisée — c'est elle qui sert de référence à la résolution."""

    keeper: Font
    """Le fichier gardé : le plus complet du groupe, installable d'abord."""

    redundant: list[Font]
    """Les fichiers en trop, proposés à la corbeille. Jamais un fichier qui
    couvre plusieurs styles."""

    also_kept: list[Font]
    """Fichiers gardés sans être *le* gardé : plusieurs variables ou collections
    dans le même groupe, qu'on ne saurait départager sans perdre des styles."""

    @property
    def total_files(self) -> int:
        return 1 + len(self.redundant) + len(self.also_kept)


def group_by_face(fonts: list[Font]) -> list[DuplicateGroup]:
    """Regroupe par identité de face et ne garde que les faces en double.

    Lecture pure : n'écrit rien, ne commit rien.
    """
    buckets: dict[FaceKey, list[Font]] = {}
    skipped = 0
    for font in fonts:
        key = face_key(font)
        if key is None:
            skipped += 1
            continue
        buckets.setdefault(key, []).append(font)

    if skipped:
        logger.info(
            "%d police(s) écartée(s) du recensement : identité de face incomplète "
            "ou suspecte.",
            skipped,
        )

    groups: list[DuplicateGroup] = []
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        protected = sorted((f for f in members if covers_several_styles(f)), key=_rank)
        if protected:
            keeper = protected[0]
            also_kept = protected[1:]
            redundant = sorted(
                (f for f in members if not covers_several_styles(f)), key=_rank
            )
        else:
            ordered = sorted(members, key=_rank)
            keeper, redundant, also_kept = ordered[0], ordered[1:], []

        # Une variable ou une collection WOFF gardée d'office n'est pas
        # installable : la seule TTF/OTF de la face ne doit pas partir pour
        # autant. La meilleure copie installable reste aussi gardée.
        if not any(_installable(f) for f in (keeper, *also_kept)):
            installable = [f for f in redundant if _installable(f)]
            if installable:
                redundant.remove(installable[0])
                also_kept.append(installable[0])

        if not redundant:
            # Un groupe sans rien à retirer n'est pas un doublon actionnable :
            # deux variables de la même face, par exemple. L'exposer noierait la
            # revue sous des lignes sans geste possible.
            continue

        groups.append(
            DuplicateGroup(
                family=(keeper.family_name or "").strip(),
                subfamily=(keeper.subfamily_name or "").strip(),
                key=key,
                keeper=keeper,
                redundant=redundant,
                also_kept=also_kept,
            )
        )

    # Les groupes les plus coûteux d'abord, puis l'ordre alphabétique : la revue
    # commence par ce qui pèse, et reste stable d'un appel à l'autre.
    groups.sort(key=lambda g: (-len(g.redundant), g.key))
    return groups


async def find_duplicate_faces(db: AsyncSession) -> list[DuplicateGroup]:
    """Recense les doublons de face parmi les polices **actives**.

    Une police en corbeille n'est pas un doublon : elle a déjà quitté la
    bibliothèque.
    """
    result = await db.execute(select(Font).where(Font.deleted_at.is_(None)))
    return group_by_face(list(result.scalars().all()))


@dataclass
class ResolveOutcome:
    """Bilan d'une résolution."""

    groups: int
    """Nombre de faces traitées."""

    trashed: list[Font]
    """Polices envoyées à la corbeille."""

    bytes_freed: int
    """Octets que le vidage de la corbeille libérerait."""


async def resolve_duplicate_faces(
    db: AsyncSession,
    *,
    keys: set[FaceKey] | None = None,
) -> ResolveOutcome:
    """Envoie à la corbeille les fichiers redondants. Ne commit pas.

    Le motif est `manual` : c'est un geste de l'utilisateur, pas une observation
    de l'agent. Il est donc durable (aucun push ne le ressuscite) et il descend
    aux appareils qui ont opté pour la propagation — les autres gardent leurs
    fichiers, comme pour toute suppression depuis l'interface.

    Args:
        db: session de base de données.
        keys: identités de face à traiter. `None` = toutes celles recensées.

    Returns:
        Le bilan. Vide si rien ne correspond.
    """
    groups = await find_duplicate_faces(db)
    if keys is not None:
        groups = [g for g in groups if g.key in keys]

    now = datetime.now(UTC)
    trashed: list[Font] = []
    for group in groups:
        for font in group.redundant:
            font.deleted_at = now
            font.deletion_confirmed = True
            font.updated_at = now
            trashed.append(font)

    # Les associations « cet appareil détient cette police » tombent avec elle,
    # comme pour une suppression unitaire : les garder ferait re-quarantiner la
    # police au premier sync suivant une restauration.
    for font in trashed:
        await db.execute(delete(DeviceFont).where(DeviceFont.font_id == font.id))
    await db.flush()

    if trashed:
        logger.info(
            "Doublons de face résolus : %d police(s) en corbeille sur %d face(s).",
            len(trashed),
            len(groups),
        )

    return ResolveOutcome(
        groups=len(groups),
        trashed=trashed,
        bytes_freed=sum(f.file_size for f in trashed),
    )
