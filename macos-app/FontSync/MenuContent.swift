// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import SwiftUI

/// Contenu de la `MenuBarExtra` (P3.1) : statut de connexion, nombre de fonts,
/// dernière sync, état de l'agent launchd, et les actions principales.
struct MenuContent: View {
    @ObservedObject var model: AppModel
    @ObservedObject var updater: UpdaterViewModel
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

        Button("Synchroniser maintenant") {
            model.syncNow()
        }
        .disabled(!model.agentAvailable && !model.syncJobLoaded)

        Button("Rafraîchir") {
            model.refresh()
        }

        Divider()

        SettingsLink {
            Text("Préférences…")
        }
        .keyboardShortcut(",")

        Button("Ouvrir les journaux") {
            openLogs()
        }

        Button("Assistant de configuration…") {
            NSApp.activate(ignoringOtherApps: true)
            openWindow(id: FontSyncApp.onboardingWindowID)
        }

        Button("Rechercher des mises à jour…") {
            updater.checkForUpdates()
        }
        .disabled(!updater.canCheckForUpdates)

        Divider()

        Button("Quitter FontSync") {
            NSApp.terminate(nil)
        }
        .keyboardShortcut("q")
    }

    /// Ouvre `~/Library/Logs/FontSync/` dans le Finder (P3.5). Crée le dossier
    /// s'il n'existe pas encore (avant la 1re sync, il peut être absent).
    private func openLogs() {
        let dir = AgentController.logDirectory
        try? FileManager.default.createDirectory(
            at: dir, withIntermediateDirectories: true)
        NSWorkspace.shared.open(dir)
    }

    private var statusLine: String {
        "● \(model.connection.label)"
    }

    private var agentLine: String {
        if let problem = model.locationProblem { return problem }
        switch (model.syncJobState, model.listenJobState) {
        case (.active, .active): return "actif"
        case (.absent, .absent): return "arrêté"
        case (let sync, .active): return "sync \(sync.label)"
        case (.active, let listen): return "listen \(listen.label)"
        case (let sync, let listen): return "sync \(sync.label), listen \(listen.label)"
        }
    }

    private func relativeString(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}
