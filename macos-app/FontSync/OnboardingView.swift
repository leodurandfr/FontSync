// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import SwiftUI

/// Assistant de **premier lancement** (P4.1).
///
/// Au tout premier démarrage de l'app (ou sur demande depuis le menu), un
/// assistant guide l'utilisateur à travers les quatre gestes indispensables :
///
///  1. **Serveur** — saisie URL + token, avec un **test de connexion** qui doit
///     réussir avant de continuer (`GET /api/stats`, cf. P1) ; les valeurs sont
///     écrites dans le `~/.fontsync/config.yaml` partagé avec l'agent.
///  2. **Agent** — installation des LaunchAgents launchd (`fontsync-agent setup`,
///     via le venv embarqué P0.3/P3.7).
///  3. **Première sync** — un `fontsync-agent sync` direct pour amorcer la
///     bibliothèque locale.
///  4. **Terminé** — récapitulatif.
///
/// L'app reste une **télécommande** : chaque étape réutilise les canaux
/// existants (`AppConfig.save`, `AgentController`), aucune logique n'est
/// réécrite.
struct OnboardingView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismissWindow) private var dismissWindow

    @State private var step: Step = .welcome

    /// Saisie serveur.
    @State private var urlString = ""
    @State private var token = ""
    @State private var serverFeedback: Feedback?
    @State private var testing = false
    /// La connexion a été testée **avec succès** sur les valeurs courantes : gate
    /// du passage à l'étape suivante. Remis à `false` dès que l'URL/token change.
    @State private var connectionVerified = false

    /// Étape agent.
    @State private var agentFeedback: Feedback?
    @State private var agentBusy = false
    @State private var agentInstalled = false

    /// Étape première sync.
    @State private var syncFeedback: Feedback?
    @State private var syncBusy = false
    @State private var syncDone = false

    enum Step: Int, CaseIterable {
        case welcome, server, agent, sync, done
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(20)
            Divider()
            footer
        }
        .frame(width: 520, height: 420)
        .onAppear(perform: prefill)
    }

    // MARK: - En-tête (titre + progression)

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(step.title)
                .font(.title2.bold())
            ProgressView(value: progress)
                .progressViewStyle(.linear)
        }
        .padding(20)
    }

    /// Avancement 0…1 sur les étapes « actionnables » (hors accueil).
    private var progress: Double {
        Double(step.rawValue) / Double(Step.allCases.count - 1)
    }

    // MARK: - Contenu par étape

    @ViewBuilder private var content: some View {
        switch step {
        case .welcome: welcomeStep
        case .server: serverStep
        case .agent: agentStep
        case .sync: syncStep
        case .done: doneStep
        }
    }

    private var welcomeStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(
                "FontSync synchronise vos polices entre vos Macs via votre serveur.",
                systemImage: "textformat")
            Text(
                "Cet assistant va vous aider à :\n"
                    + "  • connecter cet ordinateur à votre serveur FontSync ;\n"
                    + "  • installer l'agent de synchronisation en arrière-plan ;\n"
                    + "  • lancer une première synchronisation.")
                .foregroundStyle(.secondary)
            Text(
                "Gardez à portée l'URL de votre serveur et son token d'instance "
                    + "(visibles dans les journaux du conteneur, ou définis via "
                    + "FONTSYNC_TOKEN).")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }

    private var serverStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Indiquez l'adresse de votre serveur et son token d'instance.")
                .foregroundStyle(.secondary)
            Form {
                TextField("URL", text: $urlString, prompt: Text("http://nas.local:8080"))
                    .textContentType(.URL)
                    .disableAutocorrection(true)
                    .onChange(of: urlString) { connectionVerified = false; serverFeedback = nil }
                SecureField("Token d'instance", text: $token)
                    .onChange(of: token) { connectionVerified = false; serverFeedback = nil }
            }
            .formStyle(.columns)

            HStack {
                Button("Tester la connexion") { testConnection() }
                    .disabled(testing || trimmedURL.isEmpty)
                if testing { ProgressView().controlSize(.small) }
            }
            if let serverFeedback { serverFeedback.view }
        }
    }

    private var agentStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(
                "FontSync installe un agent léger qui surveille votre dossier de "
                    + "polices (~/Library/Fonts) et le tient synchronisé avec le "
                    + "serveur. Il tourne en arrière-plan via launchd.")
                .foregroundStyle(.secondary)

            if !model.agentAvailable {
                Label(
                    "Agent introuvable dans ce build (développement). Vous pouvez "
                        + "passer cette étape ; en distribution l'agent est embarqué.",
                    systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.callout)
            }

            HStack {
                Button("Installer l'agent") { installAgent() }
                    .disabled(agentBusy || !model.agentAvailable || agentInstalled)
                if agentBusy { ProgressView().controlSize(.small) }
            }
            if let agentFeedback { agentFeedback.view }
        }
    }

    private var syncStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(
                "Lancez une première synchronisation pour récupérer la bibliothèque "
                    + "depuis le serveur et y publier vos polices locales.")
                .foregroundStyle(.secondary)

            HStack {
                Button("Lancer la première synchronisation") { runFirstSync() }
                    .disabled(syncBusy)
                if syncBusy { ProgressView().controlSize(.small) }
            }
            if let syncFeedback { syncFeedback.view }
        }
    }

    private var doneStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Configuration terminée.", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.title3)
            Text(
                "FontSync est actif dans la barre des menus. L'agent synchronisera "
                    + "automatiquement vos polices ; utilisez « Synchroniser "
                    + "maintenant » pour forcer une mise à jour, et « Préférences… » "
                    + "pour changer de serveur.")
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Pied de page (navigation)

    private var footer: some View {
        HStack {
            if step != .welcome, step != .done {
                Button("Passer") { finish() }
            }
            Spacer()
            if canGoBack {
                Button("Précédent") { goBack() }
            }
            Button(step == .done ? "Terminer" : "Continuer") { advance() }
                .keyboardShortcut(.defaultAction)
                .disabled(!canContinue)
        }
        .padding(20)
    }

    private var canGoBack: Bool {
        step != .welcome && step != .done
    }

    /// Gate du bouton « Continuer » selon l'étape.
    private var canContinue: Bool {
        switch step {
        case .welcome, .done: return true
        case .server: return connectionVerified
        // L'agent peut être passé s'il est indisponible (dev) ; sinon on exige
        // l'installation avant de continuer.
        case .agent: return agentInstalled || !model.agentAvailable
        case .sync: return syncDone
        }
    }

    // MARK: - Navigation

    private func advance() {
        switch step {
        case .welcome: step = .server
        case .server: step = .agent
        case .agent: step = .sync
        case .sync: step = .done
        case .done: finish()
        }
    }

    private func goBack() {
        if let previous = Step(rawValue: step.rawValue - 1) {
            step = previous
        }
    }

    /// Termine l'assistant : mémorise l'achèvement, rafraîchit le modèle et ferme
    /// la fenêtre.
    private func finish() {
        model.markOnboardingComplete()
        model.refresh()
        dismissWindow(id: FontSyncApp.onboardingWindowID)
    }

    // MARK: - Actions

    private var trimmedURL: String {
        urlString.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Pré-remplit depuis la config existante (utile si l'assistant est relancé).
    private func prefill() {
        let config = AppConfig.load()
        if urlString.isEmpty { urlString = config.serverURL?.absoluteString ?? "" }
        if token.isEmpty { token = config.token ?? "" }
    }

    /// Teste la connexion **et**, en cas de succès, enregistre la config tout de
    /// suite : l'étape suivante (agent) en a besoin, et le modèle se rafraîchit.
    private func testConnection() {
        guard let baseURL = URL(string: trimmedURL) else {
            serverFeedback = .failure("URL invalide.")
            return
        }
        testing = true
        serverFeedback = nil
        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        let client = ServerClient(baseURL: baseURL, token: trimmedToken)
        Task {
            defer { testing = false }
            do {
                let count = try await client.fetchTotalFonts()
                do {
                    try AppConfig.save(serverURL: trimmedURL, token: trimmedToken)
                    connectionVerified = true
                    model.refresh()
                    serverFeedback = .success("Connecté — \(count) font(s). Configuration enregistrée.")
                } catch {
                    serverFeedback = .failure(
                        "Connecté, mais échec de l'enregistrement : \(error.localizedDescription)")
                }
            } catch ServerError.unauthorized {
                serverFeedback = .failure("Token invalide (401/403).")
            } catch {
                serverFeedback = .failure("Serveur injoignable.")
            }
        }
    }

    private func installAgent() {
        agentBusy = true
        agentFeedback = nil
        Task {
            defer { agentBusy = false }
            let result = await model.installAgent()
            if result.succeeded {
                agentInstalled = true
                agentFeedback = .success(result.output.isEmpty ? "Agent installé." : result.output)
            } else {
                agentFeedback = .failure(result.output.isEmpty ? "Échec." : result.output)
            }
        }
    }

    private func runFirstSync() {
        syncBusy = true
        syncFeedback = nil
        Task {
            defer { syncBusy = false }
            let result = await model.runFirstSync()
            if result.succeeded {
                syncDone = true
                syncFeedback = .success("Synchronisation effectuée.")
            } else {
                // Un échec n'est pas bloquant : l'agent réessaiera tout seul.
                syncDone = true
                syncFeedback = .failure(
                    (result.output.isEmpty ? "Échec de la synchronisation." : result.output)
                        + " L'agent réessaiera automatiquement.")
            }
        }
    }
}

/// Retour visuel succès/erreur, partagé avec les préférences (P3.3).
private enum Feedback {
    case success(String)
    case failure(String)

    @ViewBuilder var view: some View {
        switch self {
        case .success(let message):
            Label(message, systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.callout)
        case .failure(let message):
            Label(message, systemImage: "xmark.octagon.fill")
                .foregroundStyle(.red)
                .font(.callout)
        }
    }
}

extension OnboardingView.Step {
    var title: String {
        switch self {
        case .welcome: return "Bienvenue dans FontSync"
        case .server: return "Connexion au serveur"
        case .agent: return "Installation de l'agent"
        case .sync: return "Première synchronisation"
        case .done: return "C'est prêt"
        }
    }
}
