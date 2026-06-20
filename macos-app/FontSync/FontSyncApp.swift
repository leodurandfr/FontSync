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

    /// Identifiant de la fenêtre de l'assistant de premier lancement (P4.1).
    static let onboardingWindowID = "fontsync-onboarding"

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model, updater: updater)
        } label: {
            // L'icône de la barre de menus est présente dès le lancement (app
            // LSUIElement, sans fenêtre) : c'est le point d'amorçage de la sonde
            // périodique, de la demande d'autorisation des notifications (P3.6) et
            // de l'ouverture de l'assistant de premier lancement (P4.1).
            MenuBarLabel(model: model)
        }
        .menuBarExtraStyle(.menu)

        Window("FontSync", id: Self.webWindowID) {
            WebWindowContent(serverURL: model.serverURL)
        }
        .windowResizability(.contentMinSize)
        // Fenêtre « nue » : contenu plein cadre, barre de titre native masquée.
        // Les feux de circulation (close/min/zoom) et le drag sont fournis par
        // l'UI web elle-même (cf. WebView.swift + frontend useWindowControls).
        .windowStyle(.hiddenTitleBar)

        // Assistant de premier lancement (P4.1) — ouvert automatiquement au 1er
        // démarrage et relançable depuis le menu.
        Window("Configuration de FontSync", id: Self.onboardingWindowID) {
            OnboardingView(model: model)
        }
        .windowResizability(.contentSize)

        // Fenêtre de préférences standard (⌘,) — P3.3/P3.4.
        Settings {
            PreferencesView(model: model)
        }
    }
}

/// Label de la `MenuBarExtra` : point d'amorçage de l'app. Vit dans une vraie
/// `View` (et non une closure de ViewBuilder) pour disposer de
/// `@Environment(\.openWindow)` et déclencher, au premier lancement, l'assistant
/// de configuration (P4.1).
private struct MenuBarLabel: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Image(systemName: model.connection.symbolName)
            .task {
                model.start()
                if model.shouldPresentOnboarding {
                    NSApp.activate(ignoringOtherApps: true)
                    openWindow(id: FontSyncApp.onboardingWindowID)
                }
            }
    }
}
