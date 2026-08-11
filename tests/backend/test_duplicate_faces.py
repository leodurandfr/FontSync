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
    key = ("gt maru mono | display / text", "bold oblique")

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
