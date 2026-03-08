"""Notifications système macOS via pyobjc (NSUserNotificationCenter)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_AVAILABLE = False

try:
    from Foundation import NSUserNotification, NSUserNotificationCenter  # type: ignore[import-untyped]

    _AVAILABLE = True
except ImportError:
    logger.debug("pyobjc-framework-Cocoa non disponible, notifications désactivées")


def notify(title: str, message: str) -> None:
    """Affiche une notification système macOS.

    Fallback silencieux si pyobjc n'est pas installé.
    """
    if not _AVAILABLE:
        logger.info("Notification (sans UI) : %s — %s", title, message)
        return

    try:
        notification = NSUserNotification.alloc().init()
        notification.setTitle_(title)
        notification.setInformativeText_(message)
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        center.deliverNotification_(notification)
        logger.debug("Notification envoyée : %s", title)
    except Exception:
        logger.exception("Erreur lors de l'envoi de la notification")
