"""Icône de la barre de menu macOS pour l'agent FontSync.

Utilise pystray dans un thread daemon séparé. L'asyncio event loop
tourne sur le thread principal et communique via threading.Lock.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import webbrowser
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
    """Icône tray pystray tournant dans un thread daemon.

    Le thread asyncio principal met à jour l'état via update_state().
    Les actions utilisateur (Quitter, Re-scanner) sont relayées vers
    la boucle asyncio via les callbacks fournis à la construction.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_quit: Callable[[], None],
        on_rescan: Callable[[], None],
    ) -> None:
        self._loop = loop
        self._on_quit_cb = on_quit
        self._on_rescan_cb = on_rescan

        self._state = TrayState()
        self._state_lock = threading.Lock()

        self._icon: pystray.Icon | None = None  # type: ignore[union-attr]
        self._thread: threading.Thread | None = None
        self._available = _PYSTRAY_AVAILABLE and _PIL_AVAILABLE

    # ---- Public API (appelé depuis le thread asyncio) ----

    def start(self) -> None:
        """Lance le thread tray. Retourne immédiatement."""
        if not self._available:
            logger.warning("Tray icon non disponible (pystray ou Pillow manquant)")
            return

        self._thread = threading.Thread(
            target=self._thread_main,
            name="tray",
            daemon=True,
        )
        self._thread.start()
        logger.info("Tray icon démarrée")

    def stop(self) -> None:
        """Arrête proprement l'icône tray. Appelé depuis asyncio après cleanup."""
        with self._state_lock:
            icon = self._icon
            self._icon = None

        if icon is not None:
            try:
                icon.stop()
            except Exception:
                logger.debug("Erreur lors de l'arrêt du tray icon", exc_info=True)

        if self._thread is not None:
            self._thread.join(timeout=3)

    def update_state(self, state: TrayState) -> None:
        """Met à jour l'état affiché. Thread-safe, appelable depuis asyncio."""
        with self._state_lock:
            self._state = state
            icon = self._icon

        # Forcer pystray à reconstruire le menu au prochain clic
        if icon is not None:
            try:
                icon.update_menu()
            except Exception:
                logger.debug("Erreur update_menu", exc_info=True)

    # ---- Thread principal pystray ----

    def _thread_main(self) -> None:
        """Point d'entrée du thread tray. Bloque sur icon.run()."""
        try:
            image = self._make_icon()
            icon = pystray.Icon(  # type: ignore[union-attr]
                name="FontSync",
                icon=image,
                title="FontSync",
                menu=pystray.Menu(self._build_menu),  # type: ignore[union-attr]
            )
            with self._state_lock:
                self._icon = icon
            icon.run()
        except Exception:
            logger.exception("Erreur fatale du thread tray")

    # ---- Construction du menu (appelé par pystray à chaque ouverture) ----

    def _build_menu(self) -> tuple:  # type: ignore[type-arg]
        """Construit les items du menu à partir du snapshot courant."""
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
                action=self._on_open_browser,
            ),
            pystray.MenuItem("Re-scanner", action=self._on_rescan),  # type: ignore[union-attr]
            pystray.Menu.SEPARATOR,  # type: ignore[union-attr]
            pystray.MenuItem("Quitter", action=self._on_quit),  # type: ignore[union-attr]
        )

    # ---- Callbacks du menu (thread pystray) ----

    def _on_quit(self, icon: object, item: object) -> None:
        """Relaye la demande de quit vers l'asyncio loop."""
        self._on_quit_cb()

    def _on_rescan(self, icon: object, item: object) -> None:
        """Relaye la demande de re-scan vers l'asyncio loop."""
        self._on_rescan_cb()

    def _on_open_browser(self, icon: object, item: object) -> None:
        """Ouvre le frontend FontSync dans le navigateur par défaut."""
        with self._state_lock:
            url = self._state.server_url or "http://localhost:8080"

        try:
            webbrowser.open(url)
        except Exception:
            logger.warning("Impossible d'ouvrir le navigateur")

    # ---- Génération de l'icône placeholder ----

    @staticmethod
    def _make_icon() -> Image.Image:  # type: ignore[name-defined]
        """Generate a 64x64 placeholder tray icon using PIL.

        No external assets required. Will be replaced by a proper
        .png icon in a later iteration.
        """
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))  # type: ignore[union-attr]
        draw = ImageDraw.Draw(img)  # type: ignore[union-attr]

        # Fond arrondi sombre
        draw.rounded_rectangle(
            [(2, 2), (size - 2, size - 2)],
            radius=12,
            fill=(30, 30, 30, 255),
        )

        # Lettre "F" centrée en blanc (police bitmap PIL par défaut)
        draw.text((20, 14), "F", fill=(255, 255, 255, 255))

        return img
