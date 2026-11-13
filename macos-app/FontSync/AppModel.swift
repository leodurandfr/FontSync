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
    /// État réel des jobs (actif / en échec / interpréteur introuvable / absent).
    @Published private(set) var syncJobState: AgentJobState = .absent
    @Published private(set) var listenJobState: AgentJobState = .absent
    /// Emplacement d'où l'app ne doit rien installer (DMG, quarantaine) ; `nil` sinon.
    @Published private(set) var locationProblem: String? = LaunchdStatus.locationProblem

    private let lastSeenVersionKey = "fontsync.lastSeenBundleVersion"
    private let lastRepairedVersionKey = "fontsync.lastRepairedBundleVersion"
    @Published private(set) var serverURL: URL?

    /// `true` si un agent (venv embarqué ou override dev) est pilotable :
    /// conditionne l'activation des actions de cycle de vie / sync (P3.4/P3.5).
    @Published private(set) var agentAvailable = AgentController.isAvailable

    private var timer: Timer?
    private var isRefreshing = false

    /// Clé `UserDefaults` mémorisant que l'assistant de premier lancement (P4.1)
    /// a été mené à son terme (ou explicitement passé). Évite de le ré-imposer à
    /// chaque démarrage une fois l'utilisateur configuré.
    private let onboardingCompletedKey = "fontsync.onboardingCompleted"

    /// Dernier total de fonts notifié avec succès — base de comparaison pour
    /// détecter les polices nouvellement synchronisées (P3.6). `nil` tant
    /// qu'aucune sonde n'a abouti ⇒ pas de notification au tout premier scan.
    private var lastNotifiedFontCount: Int?

    /// Intervalle de sonde — assez court pour un menu vivant, assez long pour
    /// rester discret.
    private let refreshInterval: TimeInterval = 20

    func start() {
        guard timer == nil else { return }
        NotificationManager.requestAuthorization()
        repairLaunchAgentsIfNeeded()
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

        // État launchd (rapide, hors réseau) : l'état réel, pas seulement « chargé ».
        syncJobState = LaunchdStatus.state(LaunchdStatus.syncLabel)
        listenJobState = LaunchdStatus.state(LaunchdStatus.listenLabel)
        syncJobLoaded = syncJobState != .absent
        listenJobLoaded = listenJobState != .absent

        guard let baseURL = config.serverURL else {
            connection = .notConfigured
            fontCount = nil
            isRefreshing = false
            return
        }

        let client = ServerClient(baseURL: baseURL, token: config.token)
        let previousConnection = connection
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
            notifyTransition(from: previousConnection)
        }
    }

    /// Émet les notifications natives (P3.6) déduites du changement d'état
    /// observé lors de cette sonde :
    /// - **polices synchronisées** quand le total serveur augmente (pull/install) ;
    /// - **erreur de sync** quand une connexion qui marchait vient de tomber
    ///   (injoignable) ou d'être rejetée (token invalide). On exige `previous ==
    ///   .connected` pour ne notifier qu'une *interruption* réelle, pas un
    ///   serveur déjà éteint au lancement ni une sonde offline répétée.
    private func notifyTransition(from previous: ConnectionState) {
        if connection == .connected, let count = fontCount {
            if let baseline = lastNotifiedFontCount, count > baseline {
                NotificationManager.notifyFontsSynced(delta: count - baseline, total: count)
            }
            lastNotifiedFontCount = count
        }

        guard previous == .connected else { return }
        switch connection {
        case .offline: NotificationManager.notifySyncOffline()
        case .unauthorized: NotificationManager.notifySyncUnauthorized()
        default: break
        }
    }

    // MARK: - Actions (P3.4 / P3.5)

    /// Déclenche une synchronisation immédiate (P3.5 « Sync now »).
    ///
    /// Voie privilégiée : `launchctl kickstart` (sans `-k`) du job `sync` —
    /// identique à un déclenchement `WatchPaths` ; un sync déjà en cours n'est
    /// pas interrompu, il refait un tour. Si le job n'est pas chargé, on
    /// retombe sur un `fontsync-agent sync` direct via le venv embarqué
    /// (sérialisé par le même verrou). Rafraîchit le menu une fois terminé.
    func syncNow() {
        Task.detached {
            // `kickstart` ne fait que relancer le job launchd (ses erreurs
            // restent dans les journaux de l'agent) ; seul le repli `sync`
            // direct nous remonte un code de sortie exploitable (P3.6).
            var failure: String?
            if !LaunchdStatus.kickstartSync() {
                let result = AgentController.sync()
                if !result.succeeded { failure = result.output }
            }
            await MainActor.run {
                if let failure {
                    NotificationManager.notifySyncFailed(detail: failure)
                }
                self.refresh()
            }
        }
    }

    /// Installe et charge les LaunchAgents de l'agent (`fontsync-agent setup`).
    /// Renvoie le résultat pour affichage dans les préférences, puis rafraîchit.
    /// Refuse depuis un DMG ou une app en quarantaine : des LaunchAgents pointant
    /// vers ce bundle cesseraient de fonctionner dès son éjection.
    func installAgent() async -> AgentResult {
        if let problem = LaunchdStatus.locationProblem {
            return AgentResult(exitCode: 1, output: problem)
        }
        let result = await Task.detached { AgentController.setup() }.value
        refresh()
        return result
    }

    /// Au lancement : réinstalle les LaunchAgents s'ils pointent vers un
    /// interpréteur disparu, une autre copie de l'app ou un venv de build, ou si
    /// l'app vient d'être mise à jour (ce qui relance aussi `listen` sur le
    /// nouveau code). Règles : `LaunchdStatus.repairDecision`. Une même
    /// incohérence n'est réparée qu'une fois par version ; un échec de `setup`
    /// sera retenté au prochain lancement.
    private func repairLaunchAgentsIfNeeded() {
        let defaults = UserDefaults.standard
        let current = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?"
        let bundlePath = Bundle.main.bundleURL.path
        let installed = LaunchdStatus.installedInterpreter(LaunchdStatus.syncLabel)
        let decision = LaunchdStatus.repairDecision(
            bundlePath: bundlePath,
            onReadOnlyVolume: LaunchdStatus.bundleOnReadOnlyVolume,
            bundleInterpreter: AgentController.pythonInterpreter()?.path,
            installedInterpreter: installed,
            installedInterpreterExists: installed.map { FileManager.default.fileExists(atPath: $0) }
                ?? false,
            currentVersion: current,
            lastSeenVersion: defaults.string(forKey: lastSeenVersionKey),
            lastRepairKey: defaults.string(forKey: lastRepairedVersionKey)
        )
        // La version n'est retenue que pour une app installée (une version
        // lancée depuis le DMG puis copiée dans Applications doit encore
        // relancer les agents à son premier vrai lancement), et qu'une fois
        // les agents à jour : un `setup` en échec est retenté au lancement suivant.
        switch decision {
        case .none:
            if bundlePath.contains("/Applications/") {
                defaults.set(current, forKey: lastSeenVersionKey)
            }
        case .refuseLocation:
            locationProblem = LaunchdStatus.locationProblem
        case .reinstall(let reason):
            NSLog("FontSync : réinstallation des LaunchAgents (%@)", reason)
            let key = LaunchdStatus.repairKey(
                version: current,
                installedInterpreter: URL(fileURLWithPath: installed ?? "")
                    .standardizedFileURL.path)
            Task {
                let result = await Task.detached { AgentController.setup() }.value
                if result.succeeded {
                    defaults.set(key, forKey: lastRepairedVersionKey)
                    defaults.set(current, forKey: lastSeenVersionKey)
                } else {
                    NSLog("FontSync : réinstallation en échec : %@", result.output)
                }
                refresh()
            }
        }
    }

    /// Décharge et supprime les LaunchAgents (`fontsync-agent teardown`).
    func uninstallAgent() async -> AgentResult {
        let result = await Task.detached { AgentController.teardown() }.value
        refresh()
        return result
    }

    /// Lance une **première** synchronisation directe (`fontsync-agent sync`),
    /// utilisée par l'assistant de premier lancement (P4.1). On passe par
    /// l'appel direct plutôt que `kickstart` car les jobs viennent peut-être
    /// d'être installés et `sync` n'est pas forcément déjà chargé ; on veut de
    /// plus un code de sortie exploitable pour le retour visuel de l'assistant.
    func runFirstSync() async -> AgentResult {
        let result = await Task.detached { AgentController.sync() }.value
        refresh()
        return result
    }

    // MARK: - Premier lancement guidé (P4.1)

    /// `true` si l'assistant de configuration doit s'ouvrir automatiquement au
    /// démarrage : jamais mené à terme **et** serveur pas encore configuré (on
    /// ne ré-impose pas l'assistant à un utilisateur qui a déjà une config —
    /// cas d'une mise à jour depuis une version antérieure à P4.1).
    var shouldPresentOnboarding: Bool {
        !UserDefaults.standard.bool(forKey: onboardingCompletedKey)
            && AppConfig.load().serverURL == nil
    }

    /// Marque l'assistant comme terminé (ou explicitement passé) : il ne se
    /// rouvrira plus tout seul. L'utilisateur peut toujours le relancer depuis
    /// le menu.
    func markOnboardingComplete() {
        UserDefaults.standard.set(true, forKey: onboardingCompletedKey)
    }
}
