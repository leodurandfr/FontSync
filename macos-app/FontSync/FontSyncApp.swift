// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import SwiftUI

/// App menu bar FontSync (Swift/SwiftUI natif, cf. PLAN-PUBLICATION.md P3).
///
/// Architecture : une `MenuBarExtra` (P3.1) qui affiche l'état (connecté/sync/
/// nombre de fonts) et une `Window` « nue » (P3.2) chargeant l'UI web du
/// serveur dans une `WKWebView`. Pas de fenêtre principale par défaut :
/// `LSUIElement` (Info.plist) garde l'app hors du Dock.
@main
struct FontSyncApp: App {
    @StateObject private var model = AppModel()
    @StateObject private var updater = UpdaterViewModel()

    /// Identifiant de la fenêtre webview, ouverte à la demande via `openWindow`.
    static let webWindowID = "fontsync-web"

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model, updater: updater)
        } label: {
            // L'icône de la barre de menus est présente dès le lancement (app
            // LSUIElement, sans fenêtre) : c'est le point d'amorçage de la sonde
            // périodique et de la demande d'autorisation des notifications (P3.6).
            Image(systemName: model.connection.symbolName)
                .task { model.start() }
        }
        .menuBarExtraStyle(.menu)

        Window("FontSync", id: Self.webWindowID) {
            WebWindowContent(serverURL: model.serverURL)
        }
        .windowResizability(.contentMinSize)

        // Fenêtre de préférences standard (⌘,) — P3.3/P3.4.
        Settings {
            PreferencesView(model: model)
        }
    }
}
