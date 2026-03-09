"""Icône de la barre de menu macOS pour l'agent FontSync.

Sur macOS, AppKit impose que le tray tourne sur le thread principal.
L'asyncio event loop tourne dans un thread daemon séparé.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

_PYSTRAY_AVAILABLE = False
_PIL_AVAILABLE = False

try:
    import pystray

    _PYSTRAY_AVAILABLE = True
except ImportError:
    pystray = None  # type: ignore[assignment]
    logger.debug("pystray non disponible, tray icon désactivée")

try:
    from PIL import Image, ImageDraw

    _PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore[assignment, misc]
    ImageDraw = None  # type: ignore[assignment, misc]
    logger.debug("Pillow non disponible, icône générée désactivée")


@dataclass(frozen=True)
class TrayState:
    """Snapshot immuable de l'état affiché dans le menu tray."""

    connected: bool = False
    font_count: int = 0
    last_sync: str = "Jamais"
    server_url: str = ""


class TrayIcon:
    """Icône tray pystray tournant sur le thread principal (requis par macOS).

    Le thread asyncio met à jour l'état via update_state().
    Les actions utilisateur (Quitter, Re-scanner) sont relayées vers
    la boucle asyncio via les callbacks fournis à la construction.
    """

    def __init__(
        self,
        on_quit: Callable[[], None],
        on_rescan: Callable[[], None],
        on_open: Callable[[], None],
    ) -> None:
        self._on_quit_cb = on_quit
        self._on_rescan_cb = on_rescan
        self._on_open_cb = on_open

        self._state = TrayState()
        self._state_lock = threading.Lock()

        self._icon: pystray.Icon | None = None  # type: ignore[union-attr]
        self._available = _PYSTRAY_AVAILABLE and _PIL_AVAILABLE

    @property
    def available(self) -> bool:
        return self._available

    def run(self) -> None:
        """Lance le tray icon sur le thread courant (doit être le main thread).

        Bloque jusqu'à l'appel de stop().
        """
        if not self._available:
            logger.warning("Tray icon non disponible (pystray ou Pillow manquant)")
            # Bloquer indéfiniment pour ne pas quitter le main thread
            threading.Event().wait()
            return

        image = self._make_icon()
        self._icon = pystray.Icon(  # type: ignore[union-attr]
            name="FontSync",
            icon=image,
            title="FontSync",
            menu=pystray.Menu(self._build_menu),  # type: ignore[union-attr]
        )
        logger.info("Tray icon démarrée (main thread)")
        self._icon.run()

    def stop(self) -> None:
        """Arrête le tray icon. Thread-safe."""
        icon = self._icon
        self._icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                logger.debug("Erreur lors de l'arrêt du tray icon", exc_info=True)

    def update_state(self, state: TrayState) -> None:
        """Met à jour l'état affiché. Thread-safe."""
        with self._state_lock:
            self._state = state
            icon = self._icon

        if icon is not None:
            try:
                icon.update_menu()
            except Exception:
                logger.debug("Erreur update_menu", exc_info=True)

    # ---- Construction du menu ----

    def _build_menu(self) -> tuple:  # type: ignore[type-arg]
        with self._state_lock:
            state = self._state

        status_dot = "\u25cf " if state.connected else "\u25cb "
        status_label = "Connecté" if state.connected else "Déconnecté"
        font_label = f"{state.font_count} police{'s' if state.font_count != 1 else ''}"
        sync_label = f"Sync : {state.last_sync}"

        return (
            pystray.MenuItem(  # type: ignore[union-attr]
                f"{status_dot}{status_label}",
                action=None,
                enabled=False,
            ),
            pystray.MenuItem(font_label, action=None, enabled=False),  # type: ignore[union-attr]
            pystray.MenuItem(sync_label, action=None, enabled=False),  # type: ignore[union-attr]
            pystray.Menu.SEPARATOR,  # type: ignore[union-attr]
            pystray.MenuItem(  # type: ignore[union-attr]
                "Ouvrir FontSync",
                action=self._on_open,
            ),
            pystray.MenuItem("Re-scanner", action=self._on_rescan),  # type: ignore[union-attr]
            pystray.Menu.SEPARATOR,  # type: ignore[union-attr]
            pystray.MenuItem("Quitter", action=self._on_quit),  # type: ignore[union-attr]
        )

    # ---- Callbacks ----

    def _on_quit(self, icon: object, item: object) -> None:
        self._on_quit_cb()

    def _on_rescan(self, icon: object, item: object) -> None:
        self._on_rescan_cb()

    def _on_open(self, icon: object, item: object) -> None:
        self._on_open_cb()

    # ---- Icône template macOS ----

    @staticmethod
    def _make_icon() -> Image.Image:  # type: ignore[name-defined]
        """Charge l'icône template depuis agent/assets/.

        Icône monochrome noire sur fond transparent — macOS gère
        automatiquement l'adaptation dark/light mode via le template.
        """
        from pathlib import Path

        assets_dir = Path(__file__).parent / "assets"
        icon_path = assets_dir / "tray_iconTemplate.png"

        if icon_path.exists():
            return Image.open(icon_path)  # type: ignore[union-attr]

        # Fallback : générer un "F" basique si le fichier manque
        size = 22
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))  # type: ignore[union-attr]
        draw = ImageDraw.Draw(img)  # type: ignore[union-attr]
        color = (0, 0, 0, 255)
        draw.rectangle([(5, 3), (8, 18)], fill=color)
        draw.rectangle([(5, 3), (17, 6)], fill=color)
        draw.rectangle([(5, 9), (14, 12)], fill=color)
        return img
