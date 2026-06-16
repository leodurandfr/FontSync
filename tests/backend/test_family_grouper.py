"""Tests pour le service family_grouper."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.font import Font
from backend.models.font_family import FontFamily, FontFamilyMember
from backend.services.family_grouper import (
    compute_sort_order,
    group_font,
    regroup_all,
    resolve_family_name,
    slugify,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


async def _add_font(
    db: AsyncSession,
    *,
    family_name: str | None = None,
    full_name: str | None = None,
    postscript_name: str | None = None,
    original_filename: str = "Test.ttf",
    weight_class: int | None = 400,
    is_italic: bool = False,
    classification: str | None = None,
    designer: str | None = None,
) -> Font:
    """Insère une font minimale en base et la retourne (déjà flushée)."""
    font = Font(
        file_hash=uuid.uuid4().hex + uuid.uuid4().hex,  # 64 hex uniques
        original_filename=original_filename,
        file_size=1000,
        file_format="ttf",
        storage_path=f"fonts/{uuid.uuid4().hex}.ttf",
        source="upload",
        family_name=family_name,
        full_name=full_name,
        postscript_name=postscript_name,
        weight_class=weight_class,
        is_italic=is_italic,
        classification=classification,
        designer=designer,
    )
    db.add(font)
    await db.flush()
    return font


# --- Tests slugify ---


class TestSlugify:
    def test_simple_name(self) -> None:
        assert slugify("Suisse Intl") == "suisse-intl"

    def test_accented_characters(self) -> None:
        assert slugify("Hélvética Nüe") == "helvetica-nue"

    def test_special_characters(self) -> None:
        assert slugify("Font Name (Pro)") == "font-name-pro"

    def test_multiple_spaces(self) -> None:
        assert slugify("TT   Hoves   Pro") == "tt-hoves-pro"

    def test_leading_trailing_special(self) -> None:
        assert slugify("--My Font--") == "my-font"

    def test_single_word(self) -> None:
        assert slugify("Roboto") == "roboto"

    def test_normalizes_case_and_whitespace(self) -> None:
        """La clé de regroupement ignore casse et espaces superflus."""
        assert slugify("Inter ") == slugify("inter") == "inter"
        assert slugify("  Suisse   Intl  ") == slugify("Suisse Intl")

    def test_cjk_name_gets_fallback(self) -> None:
        slug = slugify("蘋方-簡")
        assert slug.startswith("family-")
        assert len(slug) > 7

    def test_cjk_fallback_is_deterministic(self) -> None:
        """Un même nom non-ASCII produit toujours le même slug (→ regroupement)."""
        assert slugify("明朝") == slugify("明朝")
        assert slugify("明朝") != slugify("蘋方-簡")

    def test_empty_string_gets_fallback(self) -> None:
        slug = slugify("")
        assert slug.startswith("family-")


# --- Tests resolve_family_name ---


class TestResolveFamilyName:
    def _font(self, **kwargs: object) -> Font:
        defaults: dict[str, object] = {
            "family_name": None,
            "full_name": None,
            "postscript_name": None,
            "original_filename": "Whatever.ttf",
        }
        defaults.update(kwargs)
        return Font(**defaults)  # type: ignore[arg-type]

    def test_prefers_family_name(self) -> None:
        font = self._font(family_name="Inter", full_name="Inter Regular")
        assert resolve_family_name(font) == "Inter"

    def test_falls_back_to_full_name(self) -> None:
        font = self._font(family_name="  ", full_name="Mystery Display")
        assert resolve_family_name(font) == "Mystery Display"

    def test_falls_back_to_postscript(self) -> None:
        font = self._font(postscript_name="WeirdMono")
        assert resolve_family_name(font) == "WeirdMono"

    def test_falls_back_to_filename_stem(self) -> None:
        font = self._font(original_filename="Some Weird File.ttf")
        assert resolve_family_name(font) == "Some Weird File"


# --- Tests compute_sort_order ---


class TestComputeSortOrder:
    def test_weight_ordering(self) -> None:
        """Les poids plus lourds doivent avoir un sort_order plus élevé."""
        thin = compute_sort_order(100, False)
        light = compute_sort_order(300, False)
        regular = compute_sort_order(400, False)
        medium = compute_sort_order(500, False)
        semibold = compute_sort_order(600, False)
        bold = compute_sort_order(700, False)
        black = compute_sort_order(900, False)

        assert thin < light < regular < medium < semibold < bold < black

    def test_italic_after_upright(self) -> None:
        """L'italique d'un poids donné vient juste après l'upright."""
        regular = compute_sort_order(400, False)
        regular_italic = compute_sort_order(400, True)
        medium = compute_sort_order(500, False)

        assert regular < regular_italic < medium

    def test_bold_italic_after_bold(self) -> None:
        bold = compute_sort_order(700, False)
        bold_italic = compute_sort_order(700, True)
        assert bold_italic == bold + 1

    def test_none_weight_defaults_to_regular(self) -> None:
        """weight_class=None doit être traité comme 400 (Regular)."""
        default = compute_sort_order(None, False)
        regular = compute_sort_order(400, False)
        assert default == regular

    def test_full_weight_range(self) -> None:
        """Vérifie l'ordre complet Thin → ... → Black avec italiques."""
        weights = [100, 200, 300, 400, 500, 600, 700, 800, 900]
        all_orders: list[int] = []
        for w in weights:
            all_orders.append(compute_sort_order(w, False))
            all_orders.append(compute_sort_order(w, True))

        # Vérifier que la liste est strictement croissante
        for i in range(1, len(all_orders)):
            assert all_orders[i] > all_orders[i - 1], (
                f"sort_order non croissant à l'index {i}: "
                f"{all_orders[i - 1]} >= {all_orders[i]}"
            )


# --- Tests group_font (intégration DB) ---


class TestGroupFont:
    @pytest.mark.asyncio
    async def test_creates_family_and_member(self, db: AsyncSession) -> None:
        font = await _add_font(db, family_name="Inter")
        family = await group_font(font, db)

        assert family is not None
        assert family.name == "Inter"
        assert family.style_count == 1

    @pytest.mark.asyncio
    async def test_normalizes_grouping_key(self, db: AsyncSession) -> None:
        """« Inter » et « Inter » (espace) tombent dans la même famille."""
        f1 = await _add_font(db, family_name="Inter", weight_class=400)
        f2 = await _add_font(db, family_name="Inter ", weight_class=700)

        await group_font(f1, db)
        await group_font(f2, db)

        count = await db.scalar(select(func.count()).select_from(FontFamily))
        assert count == 1
        family = (await db.execute(select(FontFamily))).scalar_one()
        assert family.style_count == 2

    @pytest.mark.asyncio
    async def test_orphan_grouped_via_fallback(self, db: AsyncSession) -> None:
        """Une font sans family_name est regroupée sous son nom de repli."""
        font = await _add_font(db, family_name=None, full_name="Mystery Display")
        family = await group_font(font, db)

        assert family.name == "Mystery Display"
        assert family.style_count == 1

    @pytest.mark.asyncio
    async def test_orphan_no_names_uses_filename(self, db: AsyncSession) -> None:
        font = await _add_font(
            db,
            family_name=None,
            full_name=None,
            postscript_name=None,
            original_filename="Weird File.ttf",
        )
        family = await group_font(font, db)
        assert family.name == "Weird File"

    @pytest.mark.asyncio
    async def test_different_families_separate(self, db: AsyncSession) -> None:
        f1 = await _add_font(db, family_name="Inter")
        f2 = await _add_font(db, family_name="Roboto")
        await group_font(f1, db)
        await group_font(f2, db)

        count = await db.scalar(select(func.count()).select_from(FontFamily))
        assert count == 2

    @pytest.mark.asyncio
    async def test_metadata_from_most_regular_member(self, db: AsyncSession) -> None:
        """Les métadonnées de la famille viennent du membre le plus Regular."""
        bold = await _add_font(
            db, family_name="Inter", weight_class=700, classification="display"
        )
        regular = await _add_font(
            db, family_name="Inter", weight_class=400, classification="sans-serif"
        )
        # Bold importée en premier → crée la famille avec « display »…
        await group_font(bold, db)
        # …puis Regular rejoint → les métadonnées basculent sur « sans-serif ».
        family = await group_font(regular, db)

        assert family.classification == "sans-serif"


# --- Tests regroup_all (intégration DB) ---


class TestRegroupAll:
    @pytest.mark.asyncio
    async def test_groups_all_including_orphans(self, db: AsyncSession) -> None:
        await _add_font(db, family_name="Inter", weight_class=400)
        await _add_font(db, family_name="Inter", weight_class=700)
        await _add_font(db, family_name=None, full_name="Lonely Sans")

        stats = await regroup_all(db)

        assert stats["fonts_grouped"] == 3
        assert stats["families_created"] == 2  # Inter + Lonely Sans
        assert stats["fonts_orphaned"] == 1

        count = await db.scalar(select(func.count()).select_from(FontFamily))
        assert count == 2

    @pytest.mark.asyncio
    async def test_excludes_soft_deleted(self, db: AsyncSession) -> None:
        from datetime import datetime

        alive = await _add_font(db, family_name="Inter")
        dead = await _add_font(db, family_name="Roboto")
        dead.deleted_at = datetime(2026, 1, 1)
        await db.flush()

        stats = await regroup_all(db)

        assert stats["fonts_grouped"] == 1
        members = (await db.execute(select(FontFamilyMember))).scalars().all()
        assert len(members) == 1
        assert members[0].font_id == alive.id


# --- Tests sort_order avec de vraies fonts (fixtures commerciales) ---


class TestSortOrderWithFixtures:
    """Vérifie le tri logique avec les métadonnées extraites des fixtures."""

    def test_suisse_intl_family_order(self) -> None:
        """Les styles Suisse Intl doivent se trier Thin → Light → Regular → SemiBold."""
        from backend.services.font_analyzer import analyze

        fonts_data = []
        for name in [
            "SuisseIntl-Thin.otf",
            "SuisseIntl-Light.otf",
            "SuisseIntl-Regular.otf",
            "SuisseIntl-SemiBold.otf",
        ]:
            path = FIXTURES / name
            if path.exists():
                meta = analyze(path)
                fonts_data.append((name, meta))

        if len(fonts_data) < 2:
            pytest.skip("Pas assez de fixtures Suisse Intl")

        # Calculer les sort_orders
        orders = []
        for name, meta in fonts_data:
            order = compute_sort_order(
                meta.get("weight_class"),
                meta.get("is_italic", False),
            )
            orders.append((name, order))

        # Vérifier que l'ordre est croissant
        for i in range(1, len(orders)):
            assert orders[i][1] > orders[i - 1][1], (
                f"{orders[i][0]} (order={orders[i][1]}) devrait être après "
                f"{orders[i - 1][0]} (order={orders[i - 1][1]})"
            )

    def test_italic_variants_order(self) -> None:
        """Les italiques doivent venir après leur variante droite."""
        from backend.services.font_analyzer import analyze

        pairs = [
            ("SuisseIntlCond-Regular.otf", "SuisseIntlCond-RegularItalic.otf"),
            ("SuisseIntlCond-Bold.otf", "SuisseIntlCond-BoldItalic.otf"),
        ]

        for upright_name, italic_name in pairs:
            upright_path = FIXTURES / upright_name
            italic_path = FIXTURES / italic_name
            if not upright_path.exists() or not italic_path.exists():
                continue

            upright_meta = analyze(upright_path)
            italic_meta = analyze(italic_path)

            upright_order = compute_sort_order(
                upright_meta.get("weight_class"),
                upright_meta.get("is_italic", False),
            )
            italic_order = compute_sort_order(
                italic_meta.get("weight_class"),
                italic_meta.get("is_italic", False),
            )

            assert upright_order < italic_order, (
                f"{upright_name} (order={upright_order}) devrait être avant "
                f"{italic_name} (order={italic_order})"
            )

    def test_different_families_grouped_separately(self) -> None:
        """Les fonts de familles différentes doivent avoir des family_name distincts."""
        from backend.services.font_analyzer import analyze

        suisse_path = FIXTURES / "SuisseIntl-Regular.otf"
        mono_path = FIXTURES / "SuisseIntlMono-Regular.otf"
        if not suisse_path.exists() or not mono_path.exists():
            pytest.skip("Fixtures commerciales Suisse Intl absentes")

        suisse_meta = analyze(suisse_path)
        mono_meta = analyze(mono_path)

        suisse_family = suisse_meta.get("family_name")
        mono_family = mono_meta.get("family_name")

        assert suisse_family is not None
        assert mono_family is not None
        assert suisse_family != mono_family, (
            f"Les deux fonts ont le même family_name : {suisse_family}"
        )
