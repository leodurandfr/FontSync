// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import SwiftUI

/// Contenu de la `MenuBarExtra` (P3.1) : statut de connexion, nombre de fonts,
/// dernière sync, état de l'agent launchd, et les actions principales.
struct MenuContent: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        // En-tête : état de connexion.
        Text(statusLine)

        if let count = model.fontCount {
            Text("\(count) font\(count > 1 ? "s" : "")")
        }
        if let lastSync = model.lastSync {
            Text("Dernière vérif. : \(relativeString(lastSync))")
        }

        Divider()

        // État de l'agent local (launchd).
        Text("Agent : \(agentLine)")

        Divider()

        Button("Ouvrir FontSync") {
            NSApp.activate(ignoringOtherApps: true)
            openWindow(id: FontSyncApp.webWindowID)
        }
        .disabled(model.serverURL == nil)

        Button("Rafraîchir") {
            model.refresh()
        }

        Divider()

        Button("Quitter FontSync") {
            NSApp.terminate(nil)
        }
        .keyboardShortcut("q")
    }

    private var statusLine: String {
        "● \(model.connection.label)"
    }

    private var agentLine: String {
        switch (model.syncJobLoaded, model.listenJobLoaded) {
        case (true, true): return "actif"
        case (false, false): return "arrêté"
        default: return "partiel"
        }
    }

    private func relativeString(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}
