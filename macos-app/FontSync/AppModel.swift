// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Combine
import Foundation

/// État de connexion au serveur, dérivé de la dernière sonde `/api/stats`.
enum ConnectionState: Equatable {
    case unknown
    case notConfigured
    case connected
    case unauthorized
    case offline

    var label: String {
        switch self {
        case .unknown: return "Vérification…"
        case .notConfigured: return "Non configuré"
        case .connected: return "Connecté"
        case .unauthorized: return "Token invalide"
        case .offline: return "Serveur injoignable"
        }
    }

    /// Nom de symbole SF pour l'icône de la barre de menus.
    var symbolName: String {
        switch self {
        case .connected: return "textformat"
        case .unknown: return "ellipsis.circle"
        case .notConfigured: return "exclamationmark.circle"
        case .unauthorized: return "lock.trianglebadge.exclamationmark"
        case .offline: return "bolt.horizontal.circle"
        }
    }
}

/// Source de vérité observable du menu : connectivité, nombre de fonts, état
/// launchd et horodatage du dernier rafraîchissement réussi. Rafraîchie par un
/// minuteur et à l'ouverture du menu.
@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var connection: ConnectionState = .unknown
    @Published private(set) var fontCount: Int?
    @Published private(set) var lastSync: Date?
    @Published private(set) var syncJobLoaded = false
    @Published private(set) var listenJobLoaded = false
    @Published private(set) var serverURL: URL?

    /// `true` si un agent (venv embarqué ou override dev) est pilotable :
    /// conditionne l'activation des actions de cycle de vie / sync (P3.4/P3.5).
    @Published private(set) var agentAvailable = AgentController.isAvailable

    private var timer: Timer?
    private var isRefreshing = false

    /// Intervalle de sonde — assez court pour un menu vivant, assez long pour
    /// rester discret.
    private let refreshInterval: TimeInterval = 20

    func start() {
        refresh()
        let timer = Timer.scheduledTimer(withTimeInterval: refreshInterval, repeats: true) {
            [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        timer.tolerance = 5
        self.timer = timer
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    /// Recharge config + sonde serveur + état launchd. Idempotent ; ignore les
    /// appels concurrents.
    func refresh() {
        guard !isRefreshing else { return }
        isRefreshing = true

        let config = AppConfig.load()
        serverURL = config.serverURL
        agentAvailable = AgentController.isAvailable

        // État launchd (rapide, hors réseau).
        syncJobLoaded = LaunchdStatus.isLoaded(LaunchdStatus.syncLabel)
        listenJobLoaded = LaunchdStatus.isLoaded(LaunchdStatus.listenLabel)

        guard let baseURL = config.serverURL else {
            connection = .notConfigured
            fontCount = nil
            isRefreshing = false
            return
        }

        let client = ServerClient(baseURL: baseURL, token: config.token)
        Task { @MainActor in
            defer { isRefreshing = false }
            do {
                let count = try await client.fetchTotalFonts()
                fontCount = count
                connection = .connected
                lastSync = Date()
            } catch ServerError.unauthorized {
                connection = .unauthorized
                fontCount = nil
            } catch {
                connection = .offline
            }
        }
    }

    // MARK: - Actions (P3.4 / P3.5)

    /// Déclenche une synchronisation immédiate (P3.5 « Sync now »).
    ///
    /// Voie privilégiée : `launchctl kickstart -k` du job `sync` — identique à
    /// un déclenchement `WatchPaths`. Si le job n'est pas chargé, on retombe sur
    /// un `fontsync-agent sync` direct via le venv embarqué. Rafraîchit le menu
    /// une fois terminé.
    func syncNow() {
        Task.detached {
            if !LaunchdStatus.kickstartSync() {
                _ = AgentController.sync()
            }
            await MainActor.run { self.refresh() }
        }
    }

    /// Installe et charge les LaunchAgents de l'agent (`fontsync-agent setup`).
    /// Renvoie le résultat pour affichage dans les préférences, puis rafraîchit.
    func installAgent() async -> AgentResult {
        let result = await Task.detached { AgentController.setup() }.value
        refresh()
        return result
    }

    /// Décharge et supprime les LaunchAgents (`fontsync-agent teardown`).
    func uninstallAgent() async -> AgentResult {
        let result = await Task.detached { AgentController.teardown() }.value
        refresh()
        return result
    }
}
