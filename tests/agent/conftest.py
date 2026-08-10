"""Garde-fou commun aux tests de l'agent.

`agent.font_registry` agit sur la **vraie** session macOS de la machine qui
lance les tests (`killall fontd fontworker`, enregistrement Core Text). Ses
gardes internes suffisent en théorie — il refuse d'agir sur autre chose que le
vrai ~/Library/Fonts, et les tests travaillent en `tmp_path` — mais on ne fait
pas reposer l'intégrité de la machine du développeur sur la justesse du code
testé : l'interrupteur d'environnement est armé pour toute la suite.

Les tests qui vérifient le comportement réel de la réindexation le désarment
explicitement (cf. `test_font_registry.py`).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_reindex(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise toute action sur l'index de polices de la machine hôte."""
    monkeypatch.setenv("FONTSYNC_NO_REINDEX", "1")
