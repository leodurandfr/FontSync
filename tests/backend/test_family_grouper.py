"""Tests pour le service family_grouper."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.family_grouper import (
    compute_sort_order,
    group_font,
    slugify,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


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

    def test_cjk_name_gets_fallback(self) -> None:
        slug = slugify("蘋方-簡")
        assert slug.startswith("family-")
        assert len(slug) > 7

    def test_empty_string_gets_fallback(self) -> None:
        slug = slugify("")
        assert slug.startswith("family-")


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


# --- Tests group_font ---


class TestGroupFont:
    """Tests pour group_font avec mocks de la session DB."""

    @pytest.mark.asyncio
    async def test_skip_font_without_family_name(self) -> None:
        """Les fonts sans family_name sont ignorées."""
        font = MagicMock()
        font.family_name = None
        db = AsyncMock()

        result = await group_font(font, db)
        assert result is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_font_with_empty_family_name(self) -> None:
        """Les fonts avec family_name vide sont ignorées."""
        font = MagicMock()
        font.family_name = ""
        db = AsyncMock()

        result = await group_font(font, db)
        assert result is None


# --- Tests sort_order avec de vraies fonts ---


class TestSortOrderWithFixtures:
    """Vérifie le tri logique avec les métadonnées extraites des fixtures."""

    def test_suisse_intl_family_order(self) -> None:
        """Les styles Suisse Intl doivent se trier Thin → Light → Regular → SemiBold."""
        from backend.services.font_analyzer import analyze

        fonts_data = []
        for name in ["SuisseIntl-Thin.otf", "SuisseIntl-Light.otf",
                      "SuisseIntl-Regular.otf", "SuisseIntl-SemiBold.otf"]:
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

        suisse_meta = analyze(FIXTURES / "SuisseIntl-Regular.otf")
        mono_meta = analyze(FIXTURES / "SuisseIntlMono-Regular.otf")

        suisse_family = suisse_meta.get("family_name")
        mono_family = mono_meta.get("family_name")

        assert suisse_family is not None
        assert mono_family is not None
        assert suisse_family != mono_family, (
            f"Les deux fonts ont le même family_name : {suisse_family}"
        )
