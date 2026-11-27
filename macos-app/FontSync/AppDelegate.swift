// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import AppKit

extension Notification.Name {
    /// Demande d'ouverture de la fenêtre de l'interface web, émise par
    /// `AppDelegate` et traitée par le label de la barre de menus (seule vue
    /// toujours vivante, qui dispose de `openWindow`).
    static let fontSyncOpenInterface = Notification.Name("FontSyncOpenInterface")
}

/// Délégué AppKit : ouvre l'interface quand l'utilisateur clique sur l'icône
/// FontSync du Dock.
///
/// - App déjà lancée : macOS envoie un « reopen » (icône persistante, ou
///   épinglée via « Options › Garder dans le Dock » alors que l'app tourne en
///   barre de menus seule).
/// - App lancée par l'utilisateur (Dock, Finder, Launchpad) : on ouvre aussi
///   l'interface, sauf lancement en tant qu'élément de connexion, qui doit rester
///   discret.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Demande d'ouverture au lancement, consommée une seule fois.
    private static var launchInterfaceRequested = false

    /// Renvoie `true` (une seule fois) si le lancement doit ouvrir l'interface.
    static func consumeLaunchInterfaceRequest() -> Bool {
        defer { launchInterfaceRequested = false }
        return launchInterfaceRequested
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard !Self.launchedAsLoginItem() else { return }
        Self.launchInterfaceRequested = true
        // Si le label de la barre de menus est déjà prêt, il traite la demande
        // tout de suite ; sinon il la consommera à son apparition.
        NotificationCenter.default.post(name: .fontSyncOpenInterface, object: nil)
    }

    func applicationShouldHandleReopen(
        _ sender: NSApplication, hasVisibleWindows flag: Bool
    ) -> Bool {
        if !flag {
            NotificationCenter.default.post(name: .fontSyncOpenInterface, object: nil)
        }
        return true
    }

    /// Vrai si macOS a lancé l'app à l'ouverture de session.
    private static func launchedAsLoginItem() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return event.eventID == AEEventID(kAEOpenApplication)
            && event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue
                == OSType(keyAELaunchedAsLogInItem)
    }
}
