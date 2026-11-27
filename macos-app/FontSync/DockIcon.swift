// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import AppKit

/// Affiche l'icône FontSync dans le Dock tant qu'une fenêtre de l'app est
/// ouverte (interface web, assistant, Préférences, mises à jour), et la retire
/// à la fermeture de la dernière : l'app redevient une simple app de barre de
/// menus.
///
/// Mécanisme natif : `LSUIElement` (Info.plist) fait démarrer l'app en
/// `.accessory` (hors Dock) ; on bascule en `.regular` (Dock, ⌘⇥, barre de
/// menus de l'app) dès qu'une fenêtre apparaît, et on revient en `.accessory`
/// quand il n'en reste plus. Une fenêtre réduite dans le Dock compte comme
/// ouverte : sans l'icône, on ne pourrait plus la rouvrir.
///
/// Préférence « Toujours afficher dans le Dock » (`alwaysShowKey`) : l'app
/// reste alors en `.regular` en permanence. Un clic sur l'icône sans fenêtre
/// ouverte affiche l'interface (`handleReopen`, appelé par `AppDelegate`).
@MainActor
final class DockIcon {
    static let shared = DockIcon()

    /// Clé `UserDefaults` de la préférence « Toujours afficher dans le Dock ».
    static let alwaysShowKey = "alwaysShowInDock"

    /// Ouvre la fenêtre principale. Fourni par la scène SwiftUI (seule à
    /// disposer d'`openWindow`), cf. `MenuBarLabel`.
    var openMainWindow: (() -> Void)?

    private var observers: [NSObjectProtocol] = []

    private init() {}

    private var alwaysShow: Bool {
        UserDefaults.standard.bool(forKey: Self.alwaysShowKey)
    }

    /// Réapplique la politique (après un changement de la préférence).
    func refresh() {
        update(closing: nil)
    }

    /// Clic sur l'icône du Dock. Sans fenêtre d'app visible, ouvre l'interface
    /// (et la ramène si elle est réduite) ; renvoie `true` si l'événement a été
    /// traité ici. Le drapeau `hasVisibleWindows` d'AppKit n'est pas utilisé :
    /// l'item de la barre de menus peut y compter comme fenêtre visible.
    func handleReopen() -> Bool {
        let hasVisibleWindow = NSApp.windows.contains {
            Self.isAppWindow($0) && $0.isVisible
        }
        guard !hasVisibleWindow, let openMainWindow else { return false }
        openMainWindow()
        return true
    }

    /// Branche l'observation des fenêtres. Idempotent : à appeler au lancement,
    /// avant l'ouverture de toute fenêtre.
    func start() {
        guard observers.isEmpty else { return }
        // Préférence active : l'icône est là dès le lancement.
        update(closing: nil)
        let center = NotificationCenter.default
        // Une fenêtre qui s'ouvre (ou revient du Dock) devient clé.
        for name in [NSWindow.didBecomeKeyNotification, NSWindow.didDeminiaturizeNotification] {
            observers.append(center.addObserver(forName: name, object: nil, queue: .main) { _ in
                MainActor.assumeIsolated { DockIcon.shared.update(closing: nil) }
            })
        }
        // `willClose` arrive avant que la fenêtre ne disparaisse : on l'exclut
        // du décompte.
        observers.append(
            center.addObserver(forName: NSWindow.willCloseNotification, object: nil, queue: .main) {
                note in
                let window = note.object as? NSWindow
                MainActor.assumeIsolated { DockIcon.shared.update(closing: window) }
            })
    }

    private func update(closing: NSWindow?) {
        let hasWindow = NSApp.windows.contains { window in
            window !== closing && Self.isAppWindow(window)
                && (window.isVisible || window.isMiniaturized)
        }
        let policy: NSApplication.ActivationPolicy =
            hasWindow || alwaysShow ? .regular : .accessory
        guard NSApp.activationPolicy() != policy else { return }
        NSApp.setActivationPolicy(policy)
        // Passée en `.regular` pour une fenêtre, l'app doit être réactivée pour
        // que sa barre de menus prenne le premier plan. Pas pour la seule
        // préférence : au lancement, on ne vole pas le focus.
        if policy == .regular && hasWindow {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    /// Vraie fenêtre d'app (titrée, pouvant être principale). Exclut le menu
    /// de la barre de menus, l'item de statut et les fenêtres techniques.
    private static func isAppWindow(_ window: NSWindow) -> Bool {
        window.styleMask.contains(.titled) && window.canBecomeMain
    }
}
