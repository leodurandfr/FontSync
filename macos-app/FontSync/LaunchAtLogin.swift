// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import ServiceManagement
import SwiftUI

/// Ouverture de l'app (icône de la barre de menus) à l'ouverture de session.
///
/// Passe par `SMAppService.mainApp` : l'app s'inscrit elle-même dans les
/// « Éléments de connexion » de macOS, visibles et révocables dans Réglages
/// Système. Indépendant de l'agent : la synchronisation tourne par launchd,
/// app ouverte ou non ; ce réglage ne concerne que le menu.
@MainActor
final class LaunchAtLogin: ObservableObject {
    @Published private(set) var isEnabled = false
    /// macOS attend l'accord de l'utilisateur dans Réglages Système.
    @Published private(set) var needsApproval = false
    @Published private(set) var lastError: String?

    init() { refresh() }

    func refresh() {
        let status = SMAppService.mainApp.status
        isEnabled = status == .enabled
        needsApproval = status == .requiresApproval
    }

    func set(_ enabled: Bool) {
        lastError = nil
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            lastError = error.localizedDescription
        }
        refresh()
    }

    func openLoginItemsSettings() {
        SMAppService.openSystemSettingsLoginItems()
    }
}
