"""Tests pour le service font_analyzer.

Les fonts sont **générées** par `build_ttf` (cf. `conftest.py`) plutôt que lues
dans `tests/fixtures/`. Ce dossier ne contient que des polices commerciales
volontairement non committées (cf. `.gitignore`) : s'en remettre à lui rendait
ces tests inexécutables partout — clone neuf, image Docker (qui exclut `tests/`)
et CI. Générer donne des fichiers TTF réels, parsables par fontTools, aux
métadonnées choisies : on teste l'analyseur, pas la présence d'un fichier.
"""

import tempfile
from pathlib import Path
from typing import ClassVar

import pytest

from backend.services.font_analyzer import analyze
from tests.backend.conftest import build_ttf


@pytest.fixture
def make_font(tmp_path: Path):
    """Écrit une font générée sur disque et retourne son chemin.

    `analyze` prend un chemin : il lui faut un vrai fichier, pas des octets.
    """

    def _make(filename: str = "TestSans-Regular.ttf", **kwargs) -> Path:
        path = tmp_path / filename
        path.write_bytes(build_ttf(**kwargs))
        return path

    return _make


# --- Tests sur une font régulière (sans-serif, poids 400) ---


class TestRegularFont:
    """Tests avec une sans-serif Regular générée."""

    @pytest.fixture(autouse=True)
    def setup(self, make_font) -> None:
        self.metadata = analyze(make_font(family="Test Sans", subfamily="Regular"))

    def test_family_name(self) -> None:
        assert self.metadata.get("family_name") is not None
        assert len(self.metadata["family_name"]) > 0

    def test_subfamily_name(self) -> None:
        assert self.metadata.get("subfamily_name") is not None

    def test_full_name(self) -> None:
        assert self.metadata.get("full_name") is not None

    def test_postscript_name(self) -> None:
        assert self.metadata.get("postscript_name") is not None
        # Le postscript name ne doit pas contenir d'espaces
        assert " " not in self.metadata["postscript_name"]

    def test_version(self) -> None:
        assert self.metadata.get("version") is not None

    def test_weight_class(self) -> None:
        wc = self.metadata.get("weight_class")
        assert wc is not None
        assert 100 <= wc <= 900
        # Regular = 400
        assert wc == 400

    def test_width_class(self) -> None:
        wc = self.metadata.get("width_class")
        assert wc is not None
        assert 1 <= wc <= 9

    def test_not_italic(self) -> None:
        assert self.metadata.get("is_italic") is False

    def test_not_variable(self) -> None:
        assert self.metadata.get("is_variable") is False

    def test_glyph_count(self) -> None:
        gc = self.metadata.get("glyph_count")
        assert gc is not None
        assert gc > 0

    def test_supported_scripts(self) -> None:
        scripts = self.metadata.get("supported_scripts")
        assert scripts is not None
        assert "latin" in scripts

    def test_panose(self) -> None:
        panose = self.metadata.get("panose")
        if panose is not None:
            parts = panose.split()
            assert len(parts) == 10
            assert all(p.isdigit() for p in parts)

    def test_classification_sans_serif(self) -> None:
        # Panose est neutre sur une font générée : c'est l'heuristique de nom
        # qui tranche, et « Test Sans » doit donner sans-serif.
        assert self.metadata.get("classification") == "sans-serif"


# --- Tests sur une font italic ---


class TestItalicFont:
    """Tests avec une condensée Bold Italic générée."""

    @pytest.fixture(autouse=True)
    def setup(self, make_font) -> None:
        self.metadata = analyze(
            make_font(
                filename="TestSansCond-BoldItalic.ttf",
                family="Test Sans Cond",
                subfamily="Bold Italic",
                weight_class=700,
                width_class=3,
                italic=True,
            )
        )

    def test_is_italic(self) -> None:
        assert self.metadata.get("is_italic") is True

    def test_weight_class_bold(self) -> None:
        wc = self.metadata.get("weight_class")
        assert wc is not None
        assert wc >= 600  # Bold ≥ 700, SemiBold ≥ 600


# --- Tests sur une font monospace ---


class TestMonospaceFont:
    """Tests avec une monospace générée (`post.isFixedPitch`)."""

    @pytest.fixture(autouse=True)
    def setup(self, make_font) -> None:
        self.metadata = analyze(
            make_font(
                filename="TestMono-Regular.ttf",
                family="Test Mono",
                monospace=True,
            )
        )

    def test_classification_monospace(self) -> None:
        classification = self.metadata.get("classification")
        assert classification == "monospace"


# --- Tests sur une font variable ---


class TestVariableFont:
    """Tests avec une font variable générée (axes wght + wdth)."""

    @pytest.fixture(autouse=True)
    def setup(self, make_font) -> None:
        self.metadata = analyze(
            make_font(
                filename="TestSansVariable.ttf",
                family="Test Sans Variable",
                variable_axes=[("wght", 100, 400, 900), ("wdth", 75, 100, 125)],
            )
        )

    def test_is_variable(self) -> None:
        assert self.metadata["is_variable"] is True

    def test_variable_axes(self) -> None:
        axes = self.metadata.get("variable_axes")
        assert axes is not None
        assert isinstance(axes, list)
        assert len(axes) > 0

    def test_variable_axes_structure(self) -> None:
        axes = self.metadata["variable_axes"]
        for axis in axes:
            assert "tag" in axis
            assert "min" in axis
            assert "max" in axis
            assert "default" in axis
            assert isinstance(axis["tag"], str)
            assert len(axis["tag"]) == 4

    def test_has_weight_axis(self) -> None:
        axes = self.metadata["variable_axes"]
        tags = [a["tag"] for a in axes]
        assert "wght" in tags

    def test_axis_bounds_preserved(self) -> None:
        """Les bornes déclarées ressortent telles quelles, sans réordonnancement."""
        wght = next(a for a in self.metadata["variable_axes"] if a["tag"] == "wght")
        assert (wght["min"], wght["default"], wght["max"]) == (100, 400, 900)


# --- Tests sur un font TTF standard (Bold, non variable) ---


class TestTTFFont:
    """Tests avec une Bold statique générée."""

    @pytest.fixture(autouse=True)
    def setup(self, make_font) -> None:
        self.metadata = analyze(
            make_font(
                filename="TestSans-Bold.ttf",
                family="Test Sans",
                subfamily="Bold",
                weight_class=700,
            )
        )

    def test_family_name(self) -> None:
        assert self.metadata.get("family_name") is not None

    def test_weight_class_bold(self) -> None:
        wc = self.metadata.get("weight_class")
        assert wc is not None
        assert wc >= 600

    def test_not_variable(self) -> None:
        assert self.metadata.get("is_variable") is False

    def test_glyph_count_positive(self) -> None:
        assert self.metadata.get("glyph_count", 0) > 0


# --- Tests sur font thin/light ---


class TestThinFont:
    """Tests avec une Thin générée (poids 100)."""

    @pytest.fixture(autouse=True)
    def setup(self, make_font) -> None:
        self.metadata = analyze(
            make_font(
                filename="TestSans-Thin.ttf",
                family="Test Sans",
                subfamily="Thin",
                weight_class=100,
            )
        )

    def test_weight_class_thin(self) -> None:
        wc = self.metadata.get("weight_class")
        assert wc is not None
        assert wc <= 300  # Thin/ExtraLight range


# --- Tests de robustesse ---


class TestRobustness:
    """Vérifie que le service ne lève jamais d'exception."""

    def test_nonexistent_file(self) -> None:
        result = analyze("/nonexistent/path/font.ttf")
        assert isinstance(result, dict)

    def test_empty_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=True) as f:
            result = analyze(f.name)
        assert isinstance(result, dict)

    def test_garbage_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            f.write(b"this is not a font file at all" * 100)
            f.flush()
            result = analyze(f.name)
        assert isinstance(result, dict)

    def test_truncated_font(self) -> None:
        """Une font tronquée est une font malformée, pas un crash.

        Cas plus vicieux que du bruit : l'en-tête est valide, fontTools s'engage
        dans le parsing puis bute. La règle du projet est qu'on ressort des
        métadonnées partielles, jamais une exception.
        """
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            f.write(build_ttf()[:200])
            f.flush()
            result = analyze(f.name)
        assert isinstance(result, dict)

    def test_return_type_is_always_dict(self) -> None:
        """Quel que soit l'input, analyze() retourne un dict."""
        for path in ["/dev/null", "/tmp/fake.otf"]:
            result = analyze(path)
            assert isinstance(result, dict)


# --- Test de complétude des champs ---


class TestFieldCompleteness:
    """Vérifie que toutes les clés attendues sont présentes pour une font valide."""

    EXPECTED_KEYS: ClassVar[set[str]] = {
        "family_name",
        "subfamily_name",
        "full_name",
        "postscript_name",
        "version",
        "weight_class",
        "width_class",
        "is_italic",
        "is_oblique",
        "glyph_count",
        "is_variable",
        "supported_scripts",
    }

    def test_regular_font_has_all_core_fields(self, make_font) -> None:
        metadata = analyze(make_font())
        missing = self.EXPECTED_KEYS - set(metadata.keys())
        assert not missing, f"Champs manquants : {missing}"

    def test_ttf_font_has_all_core_fields(self, make_font) -> None:
        metadata = analyze(
            make_font(filename="TestSans-Bold.ttf", subfamily="Bold", weight_class=700)
        )
        missing = self.EXPECTED_KEYS - set(metadata.keys())
        assert not missing, f"Champs manquants : {missing}"
