"""Point d'entrée de l'agent FontSync.

Orchestre le scan initial, le file watcher, la connexion WebSocket
et le scan périodique en boucle persistante.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from agent.config import AgentConfig
from agent.discovery import discover_fonts
from agent.font_installer import install_font
from agent.notifier import notify
from agent.scanner import (
    ScannedFont,
    WatcherService,
    hash_file,
    run_periodic_scan,
    scan_fonts,
)
from agent.sync_client import SyncClient, WebSocketClient
from agent.tray import TrayIcon, TrayState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")

# Réduire le bruit des libs HTTP et WebSocket
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)


def print_progress(current: int, total: int, *, label: str = "Progression") -> None:
    """Affiche la progression dans le terminal."""
    bar_len = 40
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = (current / total * 100) if total > 0 else 0
    sys.stdout.write(f"\r  {label} : [{bar}] {current}/{total} ({pct:.0f}%)")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


class FontSyncAgent:
    """Agent FontSync — détection, synchronisation et installation de fonts."""

    def __init__(self) -> None:
        self.config = AgentConfig.load()
        self.client = SyncClient(self.config)
        self.device_id: str = ""
        self.known_hashes: set[str] = set()
        self._watcher: WatcherService | None = None
        self._ws_client: WebSocketClient | None = None
        self._watcher_queue: asyncio.Queue[Path] = asyncio.Queue()
        self._shutdown_event = asyncio.Event()
        self._tray: TrayIcon | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_connected: bool = False
        self._last_sync_time: str = "Jamais"

    async def run(self) -> None:
        """Lance l'agent : scan initial puis surveillance continue."""
        self._print_banner()
        print(f"  Serveur : {self.config.server_url}")
        print(f"  Dossiers : {', '.join(self.config.directories)}")
        print()

        # 1. Enregistrement
        if not self._register():
            return

        # 2. Scan initial + push
        await self._initial_sync()

        # 3. Lancer les services en parallèle
        print()
        print("→ Mode surveillance continue activé")
        print("  File watcher + WebSocket + scan périodique")
        print("  Ctrl+C pour quitter")
        print()

        loop = asyncio.get_running_loop()
        self._loop = loop

        # Note: signal handlers are managed by the main thread (tray),
        # shutdown is triggered via _request_shutdown() from tray callbacks.

        # File watcher
        self._watcher = WatcherService(
            directories=self.config.directories,
            ignore_patterns=self.config.ignore_patterns,
            queue=self._watcher_queue,
            loop=loop,
        )
        self._watcher.start()

        # WebSocket client
        self._ws_client = WebSocketClient(
            config=self.config,
            device_id=self.device_id,
            on_font_available=self._handle_font_available,
            on_sync_request=self._handle_sync_request,
            on_connected=self._handle_ws_connected,
            on_disconnected=self._handle_ws_disconnected,
        )

        tasks = [
            asyncio.create_task(self._process_watcher_events(), name="watcher"),
            asyncio.create_task(self._ws_client.run(), name="websocket"),
            asyncio.create_task(
                run_periodic_scan(
                    directories=self.config.directories,
                    ignore_patterns=self.config.ignore_patterns,
                    known_hashes=self.known_hashes,
                    interval_minutes=self.config.scan_interval_minutes,
                    on_new_font=self._on_periodic_new_font,
                ),
                name="periodic_scan",
            ),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
        ]

        # Attendre le shutdown
        await self._shutdown_event.wait()
        await self._cleanup(tasks)

    def _register(self) -> bool:
        """Enregistre le device auprès du serveur."""
        print("→ Enregistrement du device...")
        try:
            device_data = self.client.register_device()
        except Exception as e:
            print(f"  ✗ Impossible de contacter le serveur : {e}")
            print(f"  Vérifiez que le serveur est démarré sur {self.config.server_url}")
            return False

        self.device_id = device_data["id"]
        self.config.device_id = self.device_id
        self.config.save()
        print(f"  ✓ Device enregistré : {device_data['name']} (id={self.device_id})")
        print()
        return True

    async def _initial_sync(self) -> None:
        """Scan initial : découverte, hash, delta, push."""
        # Découverte
        print("→ Scan des polices en cours...")
        discovered = discover_fonts(self.config.directories, self.config.ignore_patterns)
        print(f"  {len(discovered)} fichiers de polices détectés")
        print()

        if not discovered:
            print("  Aucune police trouvée dans les dossiers surveillés.")
            return

        # Hash
        print("→ Calcul des empreintes SHA-256...")
        scanned = scan_fonts(
            discovered,
            on_progress=lambda c, t: print_progress(c, t, label="Hash"),
        )
        print(f"  ✓ {len(scanned)} polices analysées")
        print()

        # Mémoriser les hashes connus
        self.known_hashes = {f.file_hash for f in scanned}

        # Delta sync
        print("→ Comparaison avec le serveur...")
        try:
            delta = self.client.delta_sync(self.device_id, scanned)
        except Exception as e:
            print(f"  ✗ Erreur delta sync : {e}")
            return

        unknown = set(delta.get("unknown_to_server", []))
        missing = delta.get("missing_on_device", [])
        already = delta.get("already_synced", 0)

        print(f"  Nouvelles pour le serveur : {len(unknown)}")
        print(f"  Déjà synchronisées : {already}")
        print(f"  Disponibles depuis le serveur : {len(missing)}")
        print()

        # Push
        if unknown and self.config.auto_push:
            print(f"→ Envoi de {len(unknown)} polices vers le serveur...")
            pushed, duplicates, errors = self.client.push_fonts(
                self.device_id,
                scanned,
                unknown,
                on_progress=lambda c, t: print_progress(c, t, label="Push"),
            )
            print(f"  ✓ {pushed} envoyées, {duplicates} doublons, {errors} erreurs")
        elif unknown:
            print(f"  ⏸ {len(unknown)} polices à envoyer (auto_push désactivé)")

        self._last_sync_time = datetime.now().strftime("%H:%M")
        self._push_tray_state()

    # ---- Watcher events ----

    async def _process_watcher_events(self) -> None:
        """Traite les événements du file watcher (nouveaux fichiers font)."""
        while True:
            path = await self._watcher_queue.get()

            # Petit délai pour laisser le fichier se stabiliser (copie en cours)
            await asyncio.sleep(0.5)

            if not path.exists():
                continue

            try:
                file_hash = hash_file(path)
            except OSError:
                logger.warning("Watcher : impossible de lire %s", path)
                continue

            if file_hash in self.known_hashes:
                logger.debug("Watcher : hash déjà connu, ignoré — %s", path.name)
                continue

            self.known_hashes.add(file_hash)
            font = ScannedFont(
                path=path,
                filename=path.name,
                file_hash=file_hash,
                file_size=path.stat().st_size,
            )

            logger.info("Watcher : nouvelle font → push %s", font.filename)

            if self.config.auto_push:
                try:
                    result = self.client.push_font(self.device_id, font)
                    dup = result.get("is_duplicate", False)
                    family = result.get("family_name", font.filename)
                    if dup:
                        logger.info("Push %s : doublon existant", font.filename)
                    else:
                        logger.info("Push %s : OK (famille=%s)", font.filename, family)
                        if self.config.show_notifications:
                            notify(
                                "FontSync",
                                f"Police {family} envoyée au serveur",
                            )
                except Exception:
                    logger.exception("Erreur push %s", font.filename)

    # ---- WebSocket handlers ----

    async def _send_status(self, status: str) -> None:
        """Envoie un changement d'état au serveur."""
        if self._ws_client:
            await self._ws_client.send_message({"type": "sync.status", "status": status})

    async def _handle_font_available(self, data: dict) -> None:
        """Gère un événement font.available du serveur."""
        font_id = data.get("fontId")
        family_name = data.get("familyName", "Inconnue")
        filename = data.get("originalFilename", "unknown")
        file_format = data.get("fileFormat", "")

        if not font_id:
            return

        if self.config.auto_pull:
            logger.info("Auto-pull : téléchargement de %s...", filename)
            await self._send_status("syncing")
            try:
                dl_filename, dl_data = self.client.pull_font(font_id)
                dest = install_font(dl_filename, dl_data)
                if dest:
                    self.known_hashes.add(hash_file(dest))
                    logger.info("Installée : %s → %s", dl_filename, dest)
                    if self.config.show_notifications:
                        notify(
                            "FontSync",
                            f"Police {family_name} installée — "
                            "redémarrez vos applications design pour l'utiliser",
                        )
                else:
                    logger.info(
                        "Format %s non installable, téléchargement seul", file_format
                    )
            except Exception:
                logger.exception("Erreur pull/install %s", filename)
            finally:
                await self._send_status("idle")
        else:
            logger.info("Nouvelle font disponible : %s (auto_pull désactivé)", family_name)
            if self.config.show_notifications:
                notify(
                    "FontSync",
                    f"Nouvelle police disponible : {family_name}",
                )

    async def _handle_sync_request(self) -> None:
        """Gère une demande de re-scan du serveur."""
        logger.info("Re-scan demandé par le serveur...")
        await self._send_status("scanning")
        await self._initial_sync()
        await self._send_status("idle")

    async def _handle_ws_connected(self) -> None:
        """Appelé quand la connexion WebSocket est (re)établie.

        Déclenche un delta sync pour rattraper les changements manqués.
        """
        self._ws_connected = True
        self._push_tray_state()
        logger.info("WebSocket connecté — delta sync de rattrapage...")
        try:
            entries = [{"hash": h, "filename": ""} for h in self.known_hashes]
            self.client.delta_sync_hashes(self.device_id, entries)
        except Exception:
            logger.exception("Erreur delta sync de rattrapage")

    async def _handle_ws_disconnected(self) -> None:
        """Appelé quand la connexion WebSocket est perdue."""
        self._ws_connected = False
        self._push_tray_state()

    async def _heartbeat_loop(self) -> None:
        """Envoie un heartbeat au serveur toutes les 30 secondes."""
        while True:
            await asyncio.sleep(30)
            if self._ws_client:
                await self._ws_client.send_heartbeat()

    # ---- Periodic scan callback ----

    def _on_periodic_new_font(self, font: ScannedFont) -> None:
        """Callback du scan périodique quand une nouvelle font est détectée."""
        if not self.config.auto_push:
            return

        logger.info("Scan périodique : push %s", font.filename)
        try:
            self.client.push_font(self.device_id, font)
        except Exception:
            logger.exception("Erreur push (scan périodique) %s", font.filename)

    # ---- Tray icon ----

    def _push_tray_state(self, *, connected: bool | None = None) -> None:
        """Pousse l'état courant vers le tray icon. Thread-safe."""
        if self._tray is None:
            return

        state = TrayState(
            connected=connected if connected is not None else self._ws_connected,
            font_count=len(self.known_hashes),
            last_sync=self._last_sync_time,
            server_url=self.config.server_url,
        )
        self._tray.update_state(state)

    def _on_quit_from_tray(self) -> None:
        """Appelé depuis le thread principal (pystray) quand l'utilisateur clique Quitter."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._request_shutdown)

    def _on_rescan_from_tray(self) -> None:
        """Appelé depuis le thread principal (pystray) quand l'utilisateur clique Re-scanner."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._rescan_requested(), self._loop
            )

    def _on_open_from_tray(self) -> None:
        """Appelé depuis le thread principal (pystray) quand l'utilisateur clique Ouvrir."""
        import webbrowser

        url = self.config.server_url or "http://localhost:8080"
        try:
            webbrowser.open(url)
        except Exception:
            logger.warning("Impossible d'ouvrir le navigateur")

    async def _rescan_requested(self) -> None:
        """Exécute un re-scan complet déclenché depuis le tray."""
        logger.info("Re-scan demandé depuis le tray...")
        await self._initial_sync()

    # ---- Shutdown ----

    def _request_shutdown(self) -> None:
        """Demande un arrêt propre."""
        print("\n→ Arrêt en cours...")
        self._shutdown_event.set()

    async def _cleanup(self, tasks: list[asyncio.Task]) -> None:
        """Arrête proprement les services."""
        if self._watcher:
            self._watcher.stop()

        if self._ws_client:
            await self._ws_client.stop()

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        self.client.close()

        if self._tray:
            self._tray.stop()

        print("  ✓ Agent arrêté proprement")

    @staticmethod
    def _print_banner() -> None:
        print("╔══════════════════════════════════════╗")
        print("║        FontSync Agent v0.1.0         ║")
        print("╚══════════════════════════════════════╝")
        print()


def main() -> None:
    """Point d'entrée principal.

    macOS impose que AppKit (tray icon) tourne sur le thread principal.
    On lance donc asyncio dans un thread daemon, et le tray sur le main thread.
    """
    agent = FontSyncAgent()

    # Créer le tray icon (sera lancé sur le main thread)
    tray = TrayIcon(
        on_quit=agent._on_quit_from_tray,
        on_rescan=agent._on_rescan_from_tray,
        on_open=agent._on_open_from_tray,
    )
    agent._tray = tray

    def run_asyncio() -> None:
        """Lance l'event loop asyncio dans un thread daemon."""
        try:
            asyncio.run(agent.run())
        except KeyboardInterrupt:
            pass
        finally:
            # Quand asyncio se termine, arrêter le tray (débloque le main thread)
            tray.stop()

    # Lancer asyncio en background
    asyncio_thread = threading.Thread(target=run_asyncio, name="asyncio", daemon=True)
    asyncio_thread.start()

    # Bloquer le main thread sur le tray icon (requis par macOS AppKit)
    try:
        tray.run()
    except KeyboardInterrupt:
        agent._request_shutdown()
        tray.stop()

    asyncio_thread.join(timeout=5)


if __name__ == "__main__":
    main()
