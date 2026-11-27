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
/// Préférence « Garder l'icône dans le Dock » (`keepInDockKey`) : l'app reste
/// alors en `.regular` en permanence, même sans fenêtre. Un clic sur l'icône du
/// Dock (persistante, ou épinglée via « Options › Garder dans le Dock ») ouvre
/// l'interface : cf. `AppDelegate`.
@MainActor
final class DockIcon {
    static let shared = DockIcon()

    /// Clé `UserDefaults` de la préférence « Garder l'icône dans le Dock ».
    static let keepInDockKey = "keepInDock"

    /// Vrai si l'utilisateur veut une icône de Dock permanente.
    static var keepInDock: Bool {
        UserDefaults.standard.bool(forKey: keepInDockKey)
    }

    private var observers: [NSObjectProtocol] = []

    private init() {}

    /// Branche l'observation des fenêtres. Idempotent : à appeler au lancement,
    /// avant l'ouverture de toute fenêtre.
    func start() {
        guard observers.isEmpty else { return }
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
        // La préférence peut changer à tout moment (fenêtre Préférences).
        observers.append(
            center.addObserver(
                forName: UserDefaults.didChangeNotification, object: nil, queue: .main
            ) { _ in
                MainActor.assumeIsolated { DockIcon.shared.update(closing: nil) }
            })
        // État initial : icône permanente dès le lancement si demandée.
        update(closing: nil)
    }

    private func update(closing: NSWindow?) {
        let hasWindow = NSApp.windows.contains { window in
            window !== closing && Self.isAppWindow(window)
                && (window.isVisible || window.isMiniaturized)
        }
        let policy: NSApplication.ActivationPolicy =
            hasWindow || Self.keepInDock ? .regular : .accessory
        guard NSApp.activationPolicy() != policy else { return }
        NSApp.setActivationPolicy(policy)
        // Passée en `.regular` pour une fenêtre, l'app doit être réactivée pour
        // que sa barre de menus et son icône prennent le premier plan. Pas pour
        // la seule préférence : on ne vole pas le focus sans fenêtre à montrer.
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
