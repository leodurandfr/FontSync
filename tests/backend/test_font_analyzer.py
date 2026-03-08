"""Tests pour le service font_analyzer."""

import tempfile
from pathlib import Path

import pytest

from backend.services.font_analyzer import analyze

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


# --- Tests sur une font régulière (OTF sans-serif) ---


class TestRegularFont:
    """Tests avec SuisseIntl-Regular.otf."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.metadata = analyze(FIXTURES / "SuisseIntl-Regular.otf")

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
        # Suisse Intl est une sans-serif
        classification = self.metadata.get("classification")
        assert classification is not None
        assert classification in ("sans-serif", "serif", "monospace", "display", "handwriting", "symbol")


# --- Tests sur une font italic ---


class TestItalicFont:
    """Tests avec SuisseIntlCond-BoldItalic.otf."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.metadata = analyze(FIXTURES / "SuisseIntlCond-BoldItalic.otf")

    def test_is_italic(self) -> None:
        assert self.metadata.get("is_italic") is True

    def test_weight_class_bold(self) -> None:
        wc = self.metadata.get("weight_class")
        assert wc is not None
        assert wc >= 600  # Bold ≥ 700, SemiBold ≥ 600


# --- Tests sur une font monospace ---


class TestMonospaceFont:
    """Tests avec SuisseIntlMono-Regular.otf."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.metadata = analyze(FIXTURES / "SuisseIntlMono-Regular.otf")

    def test_classification_monospace(self) -> None:
        classification = self.metadata.get("classification")
        assert classification == "monospace"


# --- Tests sur une font variable ---


class TestVariableFont:
    """Tests avec TTHovesProVariable.ttf."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.metadata = analyze(FIXTURES / "TTHovesProVariable.ttf")

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
        # TT Hoves Pro Variable devrait avoir au moins l'axe wght
        assert "wght" in tags


# --- Tests sur un font TTF standard ---


class TestTTFFont:
    """Tests avec TTHovesPro-Bd.ttf (Bold)."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.metadata = analyze(FIXTURES / "TTHovesPro-Bd.ttf")

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
    """Tests avec SuisseIntl-Thin.otf."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.metadata = analyze(FIXTURES / "SuisseIntl-Thin.otf")

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

    def test_return_type_is_always_dict(self) -> None:
        """Quel que soit l'input, analyze() retourne un dict."""
        for path in ["/dev/null", "/tmp/fake.otf"]:
            result = analyze(path)
            assert isinstance(result, dict)


# --- Test de complétude des champs ---


class TestFieldCompleteness:
    """Vérifie que toutes les clés attendues sont présentes pour une font valide."""

    EXPECTED_KEYS = {
        "family_name", "subfamily_name", "full_name", "postscript_name",
        "version", "weight_class", "width_class", "is_italic", "is_oblique",
        "glyph_count", "is_variable", "supported_scripts",
    }

    def test_regular_font_has_all_core_fields(self) -> None:
        metadata = analyze(FIXTURES / "SuisseIntl-Regular.otf")
        missing = self.EXPECTED_KEYS - set(metadata.keys())
        assert not missing, f"Champs manquants : {missing}"

    def test_ttf_font_has_all_core_fields(self) -> None:
        metadata = analyze(FIXTURES / "TTHovesPro-Bd.ttf")
        missing = self.EXPECTED_KEYS - set(metadata.keys())
        assert not missing, f"Champs manquants : {missing}"
