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

    /// Identifiant de la fenêtre webview, ouverte à la demande via `openWindow`.
    static let webWindowID = "fontsync-web"

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model)
        } label: {
            Image(systemName: model.connection.symbolName)
        }
        .menuBarExtraStyle(.menu)

        Window("FontSync", id: Self.webWindowID) {
            WebWindowContent(serverURL: model.serverURL)
        }
        .windowResizability(.contentMinSize)
    }
}
