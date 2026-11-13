"""Doublons de face : ce que le hash ne peut pas voir.

Le défaut mesuré sur une bibliothèque réelle de 3 328 fichiers : **0 groupe** de
doublons détecté par hash, pour 918 faces en plusieurs exemplaires et 1 019
fichiers en trop. Trois noms pour une seule face donnent trois empreintes ; la
déduplication à l'import ne compare que des empreintes, donc ne voit rien.

Les tests suivent les garanties qui rendent une résolution **en bloc**
acceptable, puisque réviser 918 groupes à la main n'est pas une option :

1. le regroupement voit les vrais doublons et seulement eux ;
2. rien de ce qui couvre plusieurs styles n'est jamais proposé au retrait ;
3. la proposition est reproductible — sinon elle n'est pas révisable ;
4. bout en bout, ce qui part est récupérable et ne revient pas tout seul.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from backend.models.font import Font
from backend.services.duplicate_faces import (
    decode_key,
    encode_key,
    face_key,
    group_by_face,
)
from tests.backend.conftest import AUTH_HEADERS

# ---------- Helpers ----------


def _font(
    *,
    family: str | None = "GT Maru Mono",
    subfamily: str | None = "Bold Oblique",
    fmt: str = "otf",
    glyphs: int = 300,
    size: int = 10_000,
    variable: bool = False,
    scripts: list[str] | None = None,
    digest: str | None = None,
) -> Font:
    """Font en mémoire (jamais persistée) : `group_by_face` est une lecture pure."""
    return Font(
        id=uuid.uuid4(),
        file_hash=digest or uuid.uuid4().hex,
        original_filename=f"{family}-{subfamily}.{fmt}",
        file_size=size,
        file_format=fmt,
        source="local_scan",
        family_name=family,
        subfamily_name=subfamily,
        glyph_count=glyphs,
        supported_scripts=scripts or ["latin"],
        is_variable=variable,
    )


async def _upload(client: AsyncClient, data: bytes, name: str) -> dict:
    resp = await client.post(
        "/api/fonts/upload",
        headers=AUTH_HEADERS,
        files=[("files", (name, data, "font/ttf"))],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# =====================================================================
# 1. Le regroupement voit les vrais doublons
# =====================================================================


def test_same_face_under_three_names_is_one_group() -> None:
    """Le cas qui a motivé tout ça : trois noms, trois hashes, une seule face."""
    fonts = [
        _font(glyphs=300),
        _font(fmt="ttf", glyphs=300),
        _font(glyphs=280),
    ]

    groups = group_by_face(fonts)

    assert len(groups) == 1
    assert groups[0].total_files == 3
    assert len(groups[0].redundant) == 2


def test_different_styles_are_not_duplicates() -> None:
    """Deux styles d'une même famille sont deux faces, pas un doublon."""
    fonts = [_font(subfamily="Bold"), _font(subfamily="Regular")]

    assert group_by_face(fonts) == []


def test_case_and_spacing_do_not_split_a_face() -> None:
    """« Bold  Oblique » et « bold oblique » sont la même face."""
    fonts = [_font(subfamily="Bold Oblique"), _font(subfamily="bold  oblique")]

    assert len(group_by_face(fonts)) == 1


def test_incomplete_identity_is_never_grouped() -> None:
    """Sans famille *ou* sans style, on ne sait pas ce qu'on tient.

    Une police malformée est stockée avec des métadonnées partielles ; elle ne
    doit pas pour autant s'empiler avec ses semblables sous une identité vide,
    où la résolution en bloc les enverrait toutes à la corbeille sauf une.
    """
    fonts = [
        _font(family=None),
        _font(family=None),
        _font(subfamily=None),
        _font(subfamily=None),
        _font(family="   ", subfamily="   "),
        _font(family="   ", subfamily="   "),
    ]

    assert group_by_face(fonts) == []
    assert face_key(_font(family=None)) is None


def test_most_complete_file_is_kept() -> None:
    """Le gardé est celui qui couvre le plus, pas le premier venu."""
    poor = _font(glyphs=200, scripts=["latin"])
    rich = _font(glyphs=900, scripts=["latin", "cyrillic", "greek"])

    group = group_by_face([poor, rich])[0]

    assert group.keeper is rich
    assert group.redundant == [poor]


# =====================================================================
# 2. Rien qui couvre plusieurs styles n'est retiré
# =====================================================================


def test_variable_font_is_kept_over_the_statics_it_restates() -> None:
    """Une variable dit plusieurs styles depuis un fichier : elle prime.

    Et elle prime *même* en étant plus pauvre sur les critères de couverture
    lus ici — `subfamily_name` ne décrit que sa première instance, donc ces
    critères la sous-estiment par construction.
    """
    static = _font(glyphs=900)
    variable = _font(fmt="ttf", glyphs=300, variable=True)

    group = group_by_face([static, variable])[0]

    assert group.keeper is variable
    assert group.redundant == [static]


def test_collection_is_never_proposed_for_removal() -> None:
    """Un `.ttc` embarque plusieurs polices ; l'identité lue n'est que la première."""
    collection = _font(fmt="ttc", glyphs=100)
    plain = _font(glyphs=900)

    group = group_by_face([collection, plain])[0]

    assert group.keeper is collection
    assert group.redundant == [plain]


def test_two_variables_are_both_kept() -> None:
    """On ne départage pas deux fichiers multi-styles : on les garde tous les deux.

    Le statique qu'ils redisent, lui, reste retirable — c'est la seule perte
    qu'on sache sans risque.
    """
    first = _font(fmt="ttf", glyphs=400, variable=True)
    second = _font(fmt="otf", glyphs=400, variable=True)
    static = _font(glyphs=300)

    group = group_by_face([first, second, static])[0]

    assert group.redundant == [static]
    assert {f.file_hash for f in [group.keeper, *group.also_kept]} == {
        first.file_hash,
        second.file_hash,
    }


def test_group_without_anything_to_remove_is_not_reported() -> None:
    """Deux variables seules : aucun geste possible, donc aucune ligne à réviser."""
    fonts = [_font(variable=True), _font(fmt="ttf", variable=True)]

    assert group_by_face(fonts) == []


# =====================================================================
# 3. La proposition est reproductible
# =====================================================================


def test_keeper_does_not_depend_on_input_order() -> None:
    """Un classement total, sinon la revue porte sur une cible mouvante."""
    fonts = [
        _font(glyphs=500, size=10_000, digest="a" * 64),
        _font(glyphs=500, size=10_000, digest="b" * 64),
        _font(glyphs=500, size=10_000, digest="c" * 64),
    ]

    keepers = {
        group_by_face(list(reversed(fonts)))[0].keeper.file_hash,
        group_by_face(fonts)[0].keeper.file_hash,
        group_by_face([fonts[1], fonts[2], fonts[0]])[0].keeper.file_hash,
    }

    assert len(keepers) == 1


def test_key_survives_a_round_trip_through_the_api() -> None:
    """Un nom de famille peut contenir « / » ou « | » : le séparateur, non."""
    key = ("gt maru mono | display / text", "bold oblique", "1", "700", "5")

    assert decode_key(encode_key(key)) == key
    assert decode_key("pas-de-separateur") is None


# =====================================================================
# 4. Bout en bout, par l'API
# =====================================================================


@pytest.mark.asyncio
async def test_api_finds_what_the_hash_cannot(
    api_client: AsyncClient, font_factory
) -> None:
    """Deux fichiers, deux empreintes, une seule face : l'import n'y voit rien."""
    poor = font_factory(family="Doublon", subfamily="Bold")
    rich = font_factory(
        family="Doublon", subfamily="Bold", extra_codepoints=list(range(0xC0, 0xD0))
    )
    first = await _upload(api_client, poor, "doublon-bold.ttf")
    second = await _upload(api_client, rich, "Doublon-Bold.ttf")
    # L'import les tient pour deux polices distinctes : c'est bien le défaut.
    assert first["duplicates"] == [] and second["duplicates"] == []

    resp = await api_client.get("/api/fonts/duplicates", headers=AUTH_HEADERS)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["totalGroups"] == 1
    assert body["totalRedundant"] == 1
    assert body["scanned"] == 2
    group = body["items"][0]
    # Le plus couvrant est gardé.
    assert group["keeper"]["id"] == second["imported"][0]["id"]
    assert [f["id"] for f in group["redundant"]] == [first["imported"][0]["id"]]


@pytest.mark.asyncio
async def test_dry_run_changes_nothing(api_client: AsyncClient, font_factory) -> None:
    """Confirmer un chiffre avant de le déclencher ne doit rien déplacer."""
    await _upload(api_client, font_factory(family="Sec", subfamily="Bold"), "a.ttf")
    await _upload(
        api_client,
        font_factory(family="Sec", subfamily="Bold", extra_codepoints=[0xC0]),
        "b.ttf",
    )

    resp = await api_client.post(
        "/api/fonts/duplicates/resolve",
        headers=AUTH_HEADERS,
        json={"dryRun": True},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["trashed"] == 1
    assert resp.json()["dryRun"] is True
    listing = await api_client.get("/api/fonts", headers=AUTH_HEADERS)
    assert listing.json()["total"] == 2
    trash = await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)
    assert trash.json()["total"] == 0


@pytest.mark.asyncio
async def test_resolving_trashes_the_redundant_and_keeps_the_keeper(
    api_client: AsyncClient, font_factory
) -> None:
    """Un seul « oui » suffit, et ce qui part reste récupérable."""
    dropped = await _upload(
        api_client, font_factory(family="Bloc", subfamily="Bold"), "a.ttf"
    )
    kept = await _upload(
        api_client,
        font_factory(family="Bloc", subfamily="Bold", extra_codepoints=[0xC0]),
        "b.ttf",
    )
    untouched = await _upload(
        api_client, font_factory(family="Seule", subfamily="Regular"), "c.ttf"
    )

    resp = await api_client.post(
        "/api/fonts/duplicates/resolve", headers=AUTH_HEADERS, json={}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["trashed"] == 1
    assert resp.json()["groups"] == 1

    listing = await api_client.get("/api/fonts", headers=AUTH_HEADERS)
    remaining = {f["id"] for f in listing.json()["items"]}
    assert remaining == {kept["imported"][0]["id"], untouched["imported"][0]["id"]}

    trash = (await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)).json()
    assert [f["id"] for f in trash["items"]] == [dropped["imported"][0]["id"]]
    # Une résolution est un geste de l'utilisateur, pas une observation d'agent.
    assert trash["items"][0]["deletionConfirmed"] is True

    # Et le recensement est retombé à zéro.
    again = await api_client.get("/api/fonts/duplicates", headers=AUTH_HEADERS)
    assert again.json()["totalGroups"] == 0


@pytest.mark.asyncio
async def test_only_the_named_faces_are_resolved(
    api_client: AsyncClient, font_factory
) -> None:
    """La résolution peut être partielle : on choisit les faces à traiter."""
    for family in ("Alpha", "Beta"):
        await _upload(
            api_client, font_factory(family=family, subfamily="Bold"), f"{family}1.ttf"
        )
        await _upload(
            api_client,
            font_factory(family=family, subfamily="Bold", extra_codepoints=[0xC0]),
            f"{family}2.ttf",
        )

    listing = (
        await api_client.get("/api/fonts/duplicates", headers=AUTH_HEADERS)
    ).json()
    alpha = next(g for g in listing["items"] if g["family"] == "Alpha")

    resp = await api_client.post(
        "/api/fonts/duplicates/resolve",
        headers=AUTH_HEADERS,
        json={"keys": [alpha["key"]]},
    )

    assert resp.json()["trashed"] == 1
    remaining = (
        await api_client.get("/api/fonts/duplicates", headers=AUTH_HEADERS)
    ).json()
    assert [g["family"] for g in remaining["items"]] == ["Beta"]


@pytest.mark.asyncio
async def test_a_malformed_key_is_refused(api_client: AsyncClient) -> None:
    """Mieux vaut un 400 qu'une résolution silencieusement vide."""
    resp = await api_client.post(
        "/api/fonts/duplicates/resolve",
        headers=AUTH_HEADERS,
        json={"keys": ["famille-sans-separateur"]},
    )

    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_a_resolved_duplicate_does_not_come_back_on_the_next_sync(
    api_client: AsyncClient, font_factory
) -> None:
    """Le geste doit tenir : c'est tout l'objet de la pierre tombale.

    Sans elle, la machine qui détient encore le fichier le repousserait au sync
    suivant et le doublon reviendrait — exactement la boucle qui rendait les
    suppressions illusoires.
    """
    device = await api_client.post(
        "/api/devices/register",
        headers=AUTH_HEADERS,
        json={"name": "Mac", "hostname": "mac-dup", "os": "macos"},
    )
    device_id = device.json()["id"]
    data = font_factory(family="Tenace", subfamily="Bold")
    await _upload(api_client, data, "tenace-a.ttf")
    await _upload(
        api_client,
        font_factory(family="Tenace", subfamily="Bold", extra_codepoints=[0xC0]),
        "tenace-b.ttf",
    )

    await api_client.post(
        "/api/fonts/duplicates/resolve", headers=AUTH_HEADERS, json={}
    )

    pushed = await api_client.post(
        "/api/sync/push",
        headers=AUTH_HEADERS,
        files={"file": ("tenace-a.ttf", data, "font/ttf")},
        data={"device_id": device_id, "local_path": "/Users/x/tenace-a.ttf"},
    )

    assert pushed.json()["refusedDeleted"] is True
    listing = await api_client.get("/api/fonts", headers=AUTH_HEADERS)
    assert listing.json()["total"] == 1


# =====================================================================
# 5. Axes de style dans l'identité, installable avant couverture (M-37, B-117)
# =====================================================================


def _woff_from(data: bytes) -> bytes:
    """Ré-encode une vraie TTF en WOFF (mêmes tables, autre enveloppe)."""
    from io import BytesIO

    from fontTools.ttLib import TTFont

    font = TTFont(BytesIO(data))
    font.flavor = "woff"
    out = BytesIO()
    font.save(out)
    return out.getvalue()


async def _import_all(db, storage, files: list[tuple[str, bytes]]) -> None:
    from backend.services.font_importer import import_font

    for name, data in files:
        await import_font(name, data, storage, db)


@pytest.mark.asyncio
async def test_italic_not_grouped_with_upright(db, storage, font_factory) -> None:
    """M-37 : même famille, même sous-famille déclarée, mais l'une est
    italique — deux faces, pas un doublon (l'italique proposée au retrait
    perdrait la face)."""
    from backend.services.duplicate_faces import find_duplicate_faces

    await _import_all(
        db,
        storage,
        [
            ("Switz-Normal.ttf", font_factory(family="Switz", subfamily="Normal")),
            (
                "Switz-NormalItalic.ttf",
                font_factory(family="Switz", subfamily="Normal", italic=True),
            ),
        ],
    )

    assert await find_duplicate_faces(db) == []


@pytest.mark.asyncio
async def test_weight_mismatch_not_grouped(db, storage, font_factory) -> None:
    """M-37 : sous-famille identique, graisses différentes — deux faces."""
    from backend.services.duplicate_faces import find_duplicate_faces

    await _import_all(
        db,
        storage,
        [
            ("Kern-400.ttf", font_factory(family="Kern", subfamily="Text")),
            (
                "Kern-700.ttf",
                font_factory(family="Kern", subfamily="Text", weight_class=700),
            ),
        ],
    )

    assert await find_duplicate_faces(db) == []


@pytest.mark.parametrize("family", ["false", "False", "NULL", "none", " undefined "])
def test_bogus_family_excluded(family: str) -> None:
    """B-117 : une famille « false » (valeur d'une variable vide écrite par un
    outil) trahit des métadonnées cassées : hors recensement plutôt qu'un faux
    groupe, quelle que soit la casse."""
    bogus = [_font(family=family, subfamily="Regular") for _ in range(2)]
    assert [face_key(f) for f in bogus] == [None, None]
    assert group_by_face(bogus) == []


def test_single_word_family_equal_to_postscript_name_is_grouped() -> None:
    """Un Regular à nom d'un seul mot a pour nom PostScript sa famille
    (« Georgia ») : c'est normal, et sa paire OTF/TTF reste un doublon. (Une
    règle « famille = nom PostScript → écartée » cachait 52 polices système et
    leurs vrais doublons.)"""
    fonts = [
        _font(family="Georgia", subfamily="Regular", fmt=f) for f in ("otf", "ttf")
    ]
    for f in fonts:
        f.postscript_name = "Georgia"
    groups = group_by_face(fonts)
    assert len(groups) == 1 and len(groups[0].redundant) == 1


def test_otf_kept_over_ttf_of_equal_coverage() -> None:
    """Deux installables de même couverture : l'OTF (outline du fondeur)
    reste le gardé, comme avant."""
    otf = _font(fmt="otf")
    ttf = _font(fmt="ttf")
    group = group_by_face([ttf, otf])[0]
    assert group.keeper is otf and group.redundant == [ttf]


@pytest.mark.asyncio
async def test_variable_woff_never_costs_the_only_installable_copy(
    db, storage, font_factory
) -> None:
    """B-117 : une variable WOFF est gardée d'office (elle porte plusieurs
    styles), mais elle n'est pas installable — la seule TTF de la face ne doit
    pas être proposée au retrait pour autant."""
    from backend.services.duplicate_faces import find_duplicate_faces

    variable = font_factory(
        family="Vary", subfamily="Regular", variable_axes=[("wght", 100, 400, 900)]
    )
    await _import_all(
        db,
        storage,
        [
            ("Vary-VF.woff", _woff_from(variable)),
            ("Vary-Regular.ttf", font_factory(family="Vary", subfamily="Regular")),
        ],
    )

    from sqlalchemy import select

    fonts = (await db.execute(select(Font))).scalars().all()
    woff = next(f for f in fonts if f.file_format.lower() == "woff")
    ttf = next(f for f in fonts if f.file_format.lower() == "ttf")
    assert woff.is_variable and face_key(woff) == face_key(ttf) is not None

    for group in await find_duplicate_faces(db):
        assert all(f.file_format.lower() != "ttf" for f in group.redundant)


@pytest.mark.asyncio
async def test_installable_ttf_kept_over_richer_woff(db, storage, font_factory) -> None:
    """B-117 : une WOFF plus riche en glyphes ne passe pas devant la TTF — la
    WOFF n'est jamais installée, la garder retirerait la seule copie
    installable de la face."""
    from backend.services.duplicate_faces import find_duplicate_faces

    base = font_factory(family="Webby", subfamily="Regular")
    richer = font_factory(
        family="Webby", subfamily="Regular", extra_codepoints=list(range(0x100, 0x180))
    )
    await _import_all(
        db, storage, [("Webby.ttf", base), ("Webby.woff", _woff_from(richer))]
    )

    groups = await find_duplicate_faces(db)
    assert len(groups) == 1
    assert groups[0].keeper.file_format.lower() == "ttf"
    assert [f.file_format.lower() for f in groups[0].redundant] == ["woff"]


def test_key_roundtrip_five_fields() -> None:
    """La clé porte famille, sous-famille, italique, graisse, chasse ; une
    clé à deux champs (ancienne page restée ouverte) est refusée."""
    font = _font(family="Switz", subfamily="Normal")
    font.is_italic = True
    font.weight_class = 700
    font.width_class = 5
    key = face_key(font)
    assert key == ("switz", "normal", "1", "700", "5")
    assert decode_key(encode_key(key)) == key
    assert decode_key("switz\x1fnormal") is None


@pytest.mark.asyncio
async def test_resolve_refuses_a_two_field_key(api_client: AsyncClient) -> None:
    """Une page ouverte avant le passage à l'identité à cinq champs renvoie
    une clé à deux champs : 400 (la page recharge alors sa liste), jamais une
    résolution sur une autre face."""
    resp = await api_client.post(
        "/api/fonts/duplicates/resolve",
        headers=AUTH_HEADERS,
        json={"keys": ["switz\x1fnormal"]},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_width_mismatch_not_grouped(db, storage, font_factory) -> None:
    """M-37 : sous-famille identique, chasses différentes — deux faces."""
    from backend.services.duplicate_faces import find_duplicate_faces

    await _import_all(
        db,
        storage,
        [
            ("Wide-5.ttf", font_factory(family="Wide", subfamily="Text")),
            (
                "Wide-3.ttf",
                font_factory(family="Wide", subfamily="Text", width_class=3),
            ),
        ],
    )

    assert await find_duplicate_faces(db) == []


# =====================================================================
# 6. Jamais la seule copie d'une face sur un appareil (M-36)
# =====================================================================


async def _pair(db, storage, font_factory, family: str) -> tuple[Font, Font]:
    """K (plus riche, gardé) et R (redondant) : une même face."""
    from backend.services.font_importer import import_font

    keeper, _ = await import_font(
        f"{family}-Full.ttf",
        font_factory(family=family, extra_codepoints=list(range(0x100, 0x140))),
        storage,
        db,
    )
    redundant, _ = await import_font(
        f"{family}.ttf", font_factory(family=family), storage, db
    )
    return keeper, redundant


async def _device(db, name: str, *, propagate: bool, auto_pull: bool):
    from backend.models.device import Device

    device = Device(
        name=name,
        hostname=name.lower(),
        os="macos",
        propagate_deletions=propagate,
        auto_pull=auto_pull,
    )
    db.add(device)
    await db.flush()
    return device


async def _hold(db, device, font) -> None:
    from backend.models.device_font import DeviceFont

    db.add(DeviceFont(device_id=device.id, font_id=font.id, local_path=f"/u/{font.id}"))
    await db.flush()


@pytest.mark.asyncio
async def test_resolve_keeps_sole_copy_on_propagating_device_without_autopull(
    db, storage, font_factory
) -> None:
    """M-36 : X propage les suppressions sans installation automatique et ne
    détient que R ; Y détient K. Mettre R en corbeille le désinstallerait de X
    sans que K y revienne : X perdrait la face. R est gardé, et dit pourquoi."""
    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "SoleCopy")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    y = await _device(db, "Mac-Y", propagate=True, auto_pull=False)
    await _hold(db, x, redundant)
    await _hold(db, y, keeper)
    await db.commit()

    outcome = await resolve_duplicate_faces(db)
    await db.commit()

    await db.refresh(redundant)
    assert redundant.deleted_at is None
    assert [(p.font.id, p.devices) for p in outcome.protected] == [
        (redundant.id, ["Mac-X"])
    ]


@pytest.mark.asyncio
async def test_resolve_trashes_when_device_also_holds_keeper(
    db, storage, font_factory
) -> None:
    """X détient aussi K : retirer R ne lui fait rien perdre."""
    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "AlsoKeeper")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, redundant)
    await _hold(db, x, keeper)
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert [f.id for f in outcome.trashed] == [redundant.id]
    assert outcome.protected == []


@pytest.mark.asyncio
async def test_resolve_trashes_when_device_autopulls(db, storage, font_factory) -> None:
    """X installe automatiquement : il recevra K au sync suivant, R peut partir."""
    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "AutoPulls")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=True)
    await _hold(db, x, redundant)
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert [f.id for f in outcome.trashed] == [redundant.id]
    assert outcome.protected == []


@pytest.mark.asyncio
async def test_dry_run_reports_protected(api_client: AsyncClient, font_factory) -> None:
    """Le dry-run et le recensement disent, avant le clic, combien de fichiers
    restent gardés et sur quel appareil."""
    full = font_factory(family="DryProt", extra_codepoints=list(range(0x100, 0x140)))
    thin = font_factory(family="DryProt")
    await _upload(api_client, full, "DryProt-Full.ttf")
    thin_id = (await _upload(api_client, thin, "DryProt.ttf"))["imported"][0]["id"]
    resp = await api_client.post(
        "/api/devices/register",
        headers=AUTH_HEADERS,
        json={"name": "Mac-X", "hostname": "mac-x", "os": "macos"},
    )
    device = resp.json()["id"]
    await api_client.patch(
        f"/api/devices/{device}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": True, "autoPull": False},
    )
    resp = await api_client.post(
        "/api/sync/delta",
        headers=AUTH_HEADERS,
        json={
            "deviceId": device,
            "fonts": [{"hash": _sha(thin), "filename": "DryProt.ttf"}],
        },
    )
    assert resp.status_code == 200, resp.text

    dry = await api_client.post(
        "/api/fonts/duplicates/resolve",
        headers=AUTH_HEADERS,
        json={"dryRun": True},
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["trashed"] == 0
    assert dry.json()["protected"] == 1
    assert dry.json()["groups"] == 0

    listing = (
        await api_client.get("/api/fonts/duplicates", headers=AUTH_HEADERS)
    ).json()
    # Plus rien à retirer sur cette face : hors de la liste et du décompte,
    # mais le fichier gardé et son appareil restent annoncés.
    assert listing["items"] == []
    assert listing["totalGroups"] == 0
    assert listing["totalProtected"] == 1
    assert listing["protectedDevices"] == ["Mac-X"]
    assert thin_id


@pytest.mark.asyncio
async def test_mixed_group_lists_its_protected_file(db, storage, font_factory) -> None:
    """Une face où un fichier part et un autre est gardé reste listée, avec
    sa ligne « seule copie sur X »."""
    from backend.services.duplicate_faces import actionable, find_duplicate_faces
    from backend.services.font_importer import import_font

    keeper, second = await _pair(db, storage, font_factory, "Mixed")
    third, _ = await import_font(
        "Mixed-Mid.ttf",
        font_factory(family="Mixed", extra_codepoints=list(range(0x100, 0x110))),
        storage,
        db,
    )
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, second)
    await db.commit()

    groups = actionable(await find_duplicate_faces(db))

    assert len(groups) == 1
    assert [f.id for f in groups[0].redundant] == [third.id]
    assert [(p.font.id, p.devices) for p in groups[0].protected] == [
        (second.id, ["Mac-X"])
    ]


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_resolve_ignores_holders_outside_managed_folders(
    db, storage, font_factory
) -> None:
    """X détient R dans `/Library/Fonts` (non ingérable) : l'agent n'y
    désinstalle rien, X ne perd pas la face — R peut partir."""
    from backend.models.device_font import DeviceFont
    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "SharedLayer")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    db.add(
        DeviceFont(
            device_id=x.id,
            font_id=redundant.id,
            local_path="/Library/Fonts/SharedLayer.ttf",
            ingestible=False,
        )
    )
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert [f.id for f in outcome.trashed] == [redundant.id]
    assert outcome.protected == []


@pytest.mark.asyncio
async def test_one_kept_copy_is_enough_per_device(db, storage, font_factory) -> None:
    """X détient deux redondants de la même face, et pas le gardé : on lui en
    garde un (le meilleur), l'autre peut partir — la face reste sur X."""
    from backend.services.duplicate_faces import resolve_duplicate_faces
    from backend.services.font_importer import import_font

    keeper, second = await _pair(db, storage, font_factory, "TwoCopies")
    third, _ = await import_font(
        "TwoCopies-Mid.ttf",
        font_factory(family="TwoCopies", extra_codepoints=list(range(0x100, 0x110))),
        storage,
        db,
    )
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, second)
    await _hold(db, x, third)
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert [p.font.id for p in outcome.protected] == [third.id]
    assert [f.id for f in outcome.trashed] == [second.id]


@pytest.mark.asyncio
async def test_resolve_trashes_when_device_does_not_propagate(
    db, storage, font_factory
) -> None:
    """X n'applique pas les suppressions : il garde son fichier quoi qu'il
    arrive au serveur, rien à protéger."""
    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "NoPropagate")
    x = await _device(db, "Mac-X", propagate=False, auto_pull=False)
    await _hold(db, x, redundant)
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert [f.id for f in outcome.trashed] == [redundant.id]
    assert outcome.protected == []


@pytest.mark.asyncio
async def test_resolve_protects_a_removed_device_that_may_come_back(
    db, storage, font_factory
) -> None:
    """Un appareil retiré de l'interface revient au sync suivant de son agent
    (`register` le ranime, réglages compris) : sa seule copie est protégée
    comme celle d'un appareil vivant (même règle que la récolte)."""
    from datetime import datetime, timezone

    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "RemovedDevice")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, redundant)
    x.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert outcome.trashed == []
    assert [(p.font.id, p.devices) for p in outcome.protected] == [
        (redundant.id, ["Mac-X"])
    ]


@pytest.mark.asyncio
async def test_autopull_does_not_help_when_no_kept_copy_is_installable(
    db, storage, font_factory
) -> None:
    """X installe automatiquement, mais le gardé est une WOFF (jamais
    installée) : X ne récupérerait rien — sa copie est protégée."""
    from backend.services.duplicate_faces import resolve_duplicate_faces
    from backend.services.font_importer import import_font

    richer = font_factory(family="WebOnly", extra_codepoints=list(range(0x100, 0x140)))
    keeper, _ = await import_font("WebOnly-Full.woff", _woff_from(richer), storage, db)
    redundant, _ = await import_font(
        "WebOnly.woff", _woff_from(font_factory(family="WebOnly")), storage, db
    )
    x = await _device(db, "Mac-X", propagate=True, auto_pull=True)
    await _hold(db, x, redundant)
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert outcome.trashed == []
    assert [p.font.id for p in outcome.protected] == [redundant.id]


@pytest.mark.asyncio
async def test_deactivated_keeper_does_not_cover(db, storage, font_factory) -> None:
    """X détient K mais l'a désactivé : retirer R lui laisserait la face
    seulement en `disabled/` — R est gardé."""
    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "Deactivated")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, redundant)
    await _hold(db, x, keeper)
    from sqlalchemy import update

    from backend.models.device_font import DeviceFont

    await db.execute(
        update(DeviceFont)
        .where(DeviceFont.device_id == x.id, DeviceFont.font_id == keeper.id)
        .values(active=False)
    )
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert [p.font.id for p in outcome.protected] == [redundant.id]


@pytest.mark.asyncio
async def test_keeper_in_shared_layer_covers(db, storage, font_factory) -> None:
    """X détient K dans `/Library/Fonts` (non ingérable) : la face y reste
    installée pour tous les utilisateurs, R peut partir."""
    from backend.models.device_font import DeviceFont
    from backend.services.duplicate_faces import resolve_duplicate_faces

    keeper, redundant = await _pair(db, storage, font_factory, "SharedKeeper")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, redundant)
    db.add(
        DeviceFont(
            device_id=x.id,
            font_id=keeper.id,
            local_path="/Library/Fonts/SharedKeeper.ttf",
            ingestible=False,
        )
    )
    await db.commit()

    outcome = await resolve_duplicate_faces(db)

    assert [f.id for f in outcome.trashed] == [redundant.id]


@pytest.mark.asyncio
async def test_also_kept_file_covers(db, storage, font_factory) -> None:
    """Deux variables gardées d'office (gardé + `also_kept`) et une statique
    R : X détient la variable `also_kept` et R — R peut partir."""
    from backend.services.duplicate_faces import (
        find_duplicate_faces,
        resolve_duplicate_faces,
    )
    from backend.services.font_importer import import_font

    axes = [("wght", 100, 400, 900)]
    await import_font(
        "Cov-VF.ttf",
        font_factory(
            family="Cov",
            variable_axes=axes,
            extra_codepoints=list(range(0x100, 0x140)),
        ),
        storage,
        db,
    )
    other_vf, _ = await import_font(
        "Cov-VF2.ttf", font_factory(family="Cov", variable_axes=axes), storage, db
    )
    redundant, _ = await import_font("Cov.ttf", font_factory(family="Cov"), storage, db)
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, other_vf)
    await _hold(db, x, redundant)
    await db.commit()
    (group,) = await find_duplicate_faces(db)
    assert [f.id for f in group.also_kept] == [other_vf.id]

    outcome = await resolve_duplicate_faces(db)

    assert [f.id for f in outcome.trashed] == [redundant.id]


@pytest.mark.asyncio
async def test_protection_holds_across_query_batches(
    db, storage, font_factory, monkeypatch
) -> None:
    """Les détentions sont lues par lots : la protection ne dépend pas de la
    taille du lot (une bibliothèque réelle en compte des milliers)."""
    from backend.services import duplicate_faces

    monkeypatch.setattr(duplicate_faces, "_HOLDINGS_BATCH", 1)
    keeper, redundant = await _pair(db, storage, font_factory, "Batches")
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    y = await _device(db, "Mac-Y", propagate=True, auto_pull=False)
    await _hold(db, x, redundant)
    await _hold(db, y, keeper)
    await db.commit()

    outcome = await duplicate_faces.resolve_duplicate_faces(db)

    assert [p.font.id for p in outcome.protected] == [redundant.id]


@pytest.mark.asyncio
async def test_resolve_response_counts_protected(
    api_client: AsyncClient, font_factory
) -> None:
    """La réponse de la résolution réelle (pas seulement le dry-run) dit
    combien de fichiers sont restés gardés."""
    full = font_factory(family="RespProt", extra_codepoints=list(range(0x100, 0x140)))
    thin = font_factory(family="RespProt")
    await _upload(api_client, full, "RespProt-Full.ttf")
    await _upload(api_client, thin, "RespProt.ttf")
    resp = await api_client.post(
        "/api/devices/register",
        headers=AUTH_HEADERS,
        json={"name": "Mac-X", "hostname": "mac-x", "os": "macos"},
    )
    device = resp.json()["id"]
    await api_client.patch(
        f"/api/devices/{device}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": True, "autoPull": False},
    )
    await api_client.post(
        "/api/sync/delta",
        headers=AUTH_HEADERS,
        json={
            "deviceId": device,
            "fonts": [{"hash": _sha(thin), "filename": "RespProt.ttf"}],
        },
    )

    resp = await api_client.post(
        "/api/fonts/duplicates/resolve", headers=AUTH_HEADERS, json={}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["trashed"] == 0
    assert resp.json()["protected"] == 1


@pytest.mark.asyncio
async def test_web_copy_does_not_cover(db, storage, font_factory) -> None:
    """Gardé = variable WOFF, `also_kept` = la meilleure TTF, R = une TTF
    moins riche. X détient la WOFF et R : retirer R ne lui laisserait qu'une
    police web, jamais installée — R est gardé."""
    from backend.services.duplicate_faces import (
        find_duplicate_faces,
        resolve_duplicate_faces,
    )
    from backend.services.font_importer import import_font

    woff, _ = await import_font(
        "Web-VF.woff",
        _woff_from(font_factory(family="Web", variable_axes=[("wght", 100, 400, 900)])),
        storage,
        db,
    )
    await import_font(
        "Web-Best.ttf",
        font_factory(family="Web", extra_codepoints=list(range(0x100, 0x140))),
        storage,
        db,
    )
    redundant, _ = await import_font("Web.ttf", font_factory(family="Web"), storage, db)
    x = await _device(db, "Mac-X", propagate=True, auto_pull=False)
    await _hold(db, x, woff)
    await _hold(db, x, redundant)
    await db.commit()
    (group,) = await find_duplicate_faces(db)
    assert group.keeper.id == woff.id

    outcome = await resolve_duplicate_faces(db)

    assert [p.font.id for p in outcome.protected] == [redundant.id]
