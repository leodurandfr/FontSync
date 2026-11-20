"""Gestionnaire des canaux temps réel.

Maintient :
- les connexions WebSocket des clients frontend ;
- les abonnements SSE des agents (process `listen`), à qui on pousse un simple
  signal « re-sync » quand une font devient disponible.

Diffusion vers les clients frontend (P1-7a, M-10, B-45) : chaque client a sa
file bornée et SA tâche d'envoi, seule à écrire sur son socket (pas
d'entrelacement de `send_json`). `broadcast_to_clients` ne fait que déposer le
message dans les files, sur une copie de la liste : un client qui ne lit plus
ne retient pas les autres. Un client dont un envoi dépasse `send_timeout`, ou
dont la file reste pleine plus de `queue_wait`, est évincé (close 1013, « try
again later » : le frontend se reconnecte) ; une diffusion n'attend donc jamais
plus de `queue_wait`, et seulement quand une file déborde.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# 1013 « Try Again Later » : client évincé parce qu'il ne suit pas.
_CLOSE_TOO_SLOW = 1013


@dataclass
class _Client:
    queue: "asyncio.Queue[dict[str, Any]]"
    sender: "asyncio.Task[None]"
    # Dépôts en attente d'une place : tant qu'il y en a, les diffusions
    # suivantes attendent derrière (verrou FIFO), sinon une diffusion récente
    # doublerait une plus ancienne (font.deleted avant font.added).
    waiting: int = 0
    put_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WebSocketManager:
    """Gère les connexions WebSocket des clients et les abonnements SSE."""

    #: Messages en attente par client avant éviction.
    queue_size: int = 256
    #: Délai maximal d'un envoi à un client (secondes) avant éviction.
    send_timeout: float = 5.0
    #: Attente maximale d'une place dans une file pleine (secondes) : un client
    #: sain la libère en quelques millisecondes, un client muet jamais.
    queue_wait: float = 0.5

    def __init__(self) -> None:
        self._clients: dict[WebSocket, _Client] = {}
        # Abonnements SSE par device_id : une queue par connexion `listen`.
        self._sse_subscribers: dict[str, set[asyncio.Queue[str]]] = {}
        # Fermetures d'évincés en cours (références gardées jusqu'à la fin).
        self._closing: set[asyncio.Task[None]] = set()

    async def connect_client(
        self, websocket: WebSocket, initial: list[dict[str, Any]] | None = None
    ) -> None:
        """Accepte et enregistre une connexion client (frontend).

        `initial` (présence des agents…) passe par la file, avant toute
        diffusion : la tâche d'envoi reste la seule à écrire sur le socket.
        """
        await websocket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        for message in (initial or [])[: self.queue_size]:
            queue.put_nowait(message)
        sender = asyncio.create_task(self._send_loop(websocket, queue))
        self._clients[websocket] = _Client(queue=queue, sender=sender)
        logger.info("Client WebSocket connecté (%d actifs)", len(self._clients))

    def disconnect(self, websocket: WebSocket) -> None:
        """Déconnecte un client : retrait et arrêt de sa tâche d'envoi."""
        client = self._clients.pop(websocket, None)
        if client is None:
            return
        if client.sender is not asyncio.current_task():
            client.sender.cancel()
        # Libère tout de suite une diffusion qui attendait une place.
        while not client.queue.empty():
            client.queue.get_nowait()
        logger.info("Client WebSocket déconnecté (%d actifs)", len(self._clients))

    async def broadcast_to_clients(self, message: dict[str, Any]) -> None:
        """Dépose un message JSON dans la file de chaque client frontend.

        Itère une copie (un client retiré pendant la boucle ne fait sauter
        personne, B-45). Cas courant : dépôt immédiat, aucune attente. File
        pleine (rafale : upload multiple, quarantaine…) : on attend qu'elle se
        libère, au plus `queue_wait`, pour tous ces clients à la fois — un
        onglet sain absorbe la rafale, un client qui ne lit plus est évincé.
        """
        full: list[tuple[WebSocket, _Client]] = []
        for websocket, client in list(self._clients.items()):
            if not client.waiting:
                try:
                    client.queue.put_nowait(message)
                    continue
                except asyncio.QueueFull:
                    pass
            client.waiting += 1  # synchrone : les diffusions suivantes le voient
            full.append((websocket, client))
        if not full:
            return
        try:
            results = await asyncio.gather(
                *(
                    asyncio.wait_for(
                        self._put_in_order(client, message), self.queue_wait
                    )
                    for _, client in full
                ),
                return_exceptions=True,
            )
        finally:
            # Ici, et non dans _put_in_order : une diffusion annulée avant que
            # ses attentes ne démarrent (flux SSE coupé…) ne les exécute jamais.
            for _, client in full:
                client.waiting -= 1
        for (websocket, _), result in zip(full, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "Client WebSocket évincé : file pleine (%d) pendant %.1f s",
                    self.queue_size,
                    self.queue_wait,
                )
                self._evict(websocket)

    @staticmethod
    async def _put_in_order(client: _Client, message: dict[str, Any]) -> None:
        async with client.put_lock:
            await client.queue.put(message)

    async def _send_loop(
        self, websocket: WebSocket, queue: "asyncio.Queue[dict[str, Any]]"
    ) -> None:
        """Seul écrivain du socket d'un client ; l'évince au premier envoi trop lent."""
        while True:
            message = await queue.get()
            try:
                await asyncio.wait_for(websocket.send_json(message), self.send_timeout)
            except TimeoutError:
                logger.warning(
                    "Client WebSocket évincé : envoi bloqué plus de %.1f s",
                    self.send_timeout,
                )
                self._evict(websocket)
                return
            except Exception:  # socket fermé, client parti, message invalide…
                # Évincer (fermeture 1013) plutôt que seulement retirer : un
                # onglet resté connecté ne recevrait plus rien sans le savoir.
                self._evict(websocket)
                return

    def _evict(self, websocket: WebSocket) -> None:
        """Retire un client trop lent et le ferme (1013) sans jamais l'attendre."""
        if websocket not in self._clients:
            return
        self.disconnect(websocket)
        task = asyncio.create_task(self._close_quietly(websocket))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _close_quietly(self, websocket: WebSocket) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                websocket.close(code=_CLOSE_TOO_SLOW), self.send_timeout
            )

    # ---------- Canal SSE (process `listen` des agents) ----------

    def subscribe_agent_events(self, device_id: str) -> "asyncio.Queue[str]":
        """Abonne une connexion `listen` au canal SSE d'un device.

        Retourne une queue dans laquelle sont déposés les signaux « sync ».
        """
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._sse_subscribers.setdefault(device_id, set()).add(queue)
        logger.info(
            "Agent SSE abonné: %s (%d connexions)",
            device_id,
            len(self._sse_subscribers[device_id]),
        )
        return queue

    def unsubscribe_agent_events(
        self, device_id: str, queue: "asyncio.Queue[str]"
    ) -> None:
        """Désabonne une connexion `listen` du canal SSE d'un device."""
        subs = self._sse_subscribers.get(device_id)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            del self._sse_subscribers[device_id]
        logger.info("Agent SSE désabonné: %s", device_id)

    async def signal_sync(self, device_id: str) -> None:
        """Pousse un signal « re-sync » aux connexions SSE d'un device."""
        for queue in self._sse_subscribers.get(device_id, set()):
            queue.put_nowait("sync")

    async def broadcast_sync(self, exclude_device_id: str | None = None) -> None:
        """Pousse un signal « re-sync » à tous les devices abonnés en SSE.

        `exclude_device_id` permet d'éviter de re-signaler le device à
        l'origine du changement (il a déjà la font).
        """
        for device_id, subs in self._sse_subscribers.items():
            if device_id == exclude_device_id:
                continue
            for queue in subs:
                queue.put_nowait("sync")

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def connected_sse_devices(self) -> list[str]:
        """Device_ids ayant au moins une connexion SSE `listen` active.

        Source de présence « en ligne » depuis la migration de l'agent
        WebSocket → SSE : un `listen` connecté = device joignable. Les sets
        vides sont supprimés à la désinscription, donc une clé présente ⇔
        au moins un abonné actif.
        """
        return list(self._sse_subscribers.keys())


# Singleton global
ws_manager = WebSocketManager()
