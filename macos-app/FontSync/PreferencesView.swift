// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import AppKit
import SwiftUI

/// Fenêtre de préférences (P3.3 + P3.4).
///
/// - **Compte** : URL du serveur + email + mot de passe, échangés contre un
///   jeton d'appareil (`AccountConnection.connect`) écrit dans le
///   `~/.fontsync/config.yaml` partagé avec l'agent. Le mot de passe n'est
///   jamais stocké ; sans mot de passe, « Se connecter » vérifie le jeton actuel.
/// - **Agent (P3.4)** : installe/désinstalle les LaunchAgents via le venv
///   embarqué (`AgentController` → `fontsync-agent setup/teardown`), et reflète
///   l'état launchd. Le dossier d'installation y est affiché en **lecture
///   seule** : ce n'est pas un choix (cf. `AppConfig.fontsDirectoryURL`), mais
///   l'utilisateur doit pouvoir savoir où atterrissent ses polices.
struct PreferencesView: View {
    @ObservedObject var model: AppModel

    @State private var urlString = ""
    @State private var email = ""
    @State private var password = ""
    @State private var loaded = false
    /// Compte actuellement enregistré (`nil` : pas encore connecté).
    @State private var connectedEmail: String?

    /// Retour utilisateur de la connexion.
    @State private var serverFeedback: Feedback?
    @State private var testing = false

    /// Retour utilisateur des actions agent (install/désinstall).
    @State private var agentFeedback: Feedback?
    @State private var agentBusy = false

    var body: some View {
        Form {
            Section("Compte") {
                if let connectedEmail {
                    LabeledContent("Connecté en tant que") { Text(connectedEmail) }
                }

                TextField("URL", text: $urlString, prompt: Text("http://nas.local:8080"))
                    .textContentType(.URL)
                    .disableAutocorrection(true)
                TextField("Email", text: $email)
                    .textContentType(.username)
                    .disableAutocorrection(true)
                SecureField("Mot de passe", text: $password)
                    .textContentType(.password)
                    .onSubmit { connect() }

                if let feedback = serverFeedback {
                    feedback.view
                }

                HStack {
                    if testing { ProgressView().controlSize(.small) }
                    Spacer()
                    Button("Se connecter") { connect() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(testing || trimmedURL.isEmpty || trimmedEmail.isEmpty)
                }
            }

            Section("Agent") {
                LabeledContent("État") { Text(agentStatusLabel) }

                LabeledContent("Dossier d'installation") {
                    HStack(spacing: 8) {
                        Text(fontsDirectoryLabel)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.head)
                        Button("Afficher") { revealFontsDirectory() }
                            .buttonStyle(.link)
                            .disabled(!fontsDirectoryExists)
                    }
                }
                .help(
                    "Emplacement d'installation par défaut de macOS, celui de "
                        + "Livre de polices. Les polices installées pour tous les "
                        + "utilisateurs (/Library/Fonts) sont lues mais jamais modifiées."
                )

                if !model.agentAvailable {
                    Text(
                        "Agent introuvable. Dans une app distribuée, il est "
                            + "embarqué ; en développement, exportez "
                            + "FONTSYNC_AGENT_PYTHON vers le Python du repo."
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                }

                if let feedback = agentFeedback {
                    feedback.view
                }

                HStack {
                    Button("Installer l'agent") { runAgent { await model.installAgent() } }
                        .disabled(agentBusy || !model.agentAvailable)
                    Button("Désinstaller l'agent") { runAgent { await model.uninstallAgent() } }
                        .disabled(agentBusy || !model.agentAvailable)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
        .onAppear(perform: loadFields)
    }

    // MARK: - Champs

    private var trimmedURL: String {
        urlString.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var trimmedEmail: String {
        email.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Pré-remplit depuis la config existante (une seule fois par ouverture).
    private func loadFields() {
        guard !loaded else { return }
        loaded = true
        let config = AppConfig.load()
        urlString = config.serverURL?.absoluteString ?? ""
        email = config.accountEmail ?? ""
        connectedEmail = config.deviceToken == nil ? nil : config.accountEmail
    }

    /// Chemin d'installation, abrégé avec `~` comme le Finder l'affiche.
    private var fontsDirectoryLabel: String {
        (AppConfig.fontsDirectoryURL.path as NSString).abbreviatingWithTildeInPath
    }

    private var fontsDirectoryExists: Bool {
        FileManager.default.fileExists(atPath: AppConfig.fontsDirectoryURL.path)
    }

    private func revealFontsDirectory() {
        NSWorkspace.shared.open(AppConfig.fontsDirectoryURL)
    }

    private var agentStatusLabel: String {
        if let problem = model.locationProblem { return problem }
        switch (model.syncJobState, model.listenJobState) {
        case (.active, .active): return "Actif (sync + listen)"
        case (.absent, .absent): return "Arrêté"
        case (let sync, let listen):
            return "sync : \(sync.label) · listen : \(listen.label)"
        }
    }

    // MARK: - Actions compte

    private func connect() {
        testing = true
        serverFeedback = nil
        let url = trimmedURL
        let address = trimmedEmail
        let secret = password
        Task {
            defer { testing = false }
            do {
                let count = try await AccountConnection.connect(
                    urlString: url, email: address, password: secret)
                password = ""
                let config = AppConfig.load()
                connectedEmail = config.accountEmail
                serverFeedback = .success("Connecté — \(count) police(s).")
                model.refresh()
            } catch {
                serverFeedback = .failure(AccountConnection.message(for: error))
            }
        }
    }

    // MARK: - Actions agent (P3.4)

    private func runAgent(_ action: @escaping () async -> AgentResult) {
        agentBusy = true
        agentFeedback = nil
        Task {
            defer { agentBusy = false }
            let result = await action()
            agentFeedback =
                result.succeeded
                ? .success(result.output.isEmpty ? "Terminé." : result.output)
                : .failure(result.output.isEmpty ? "Échec." : result.output)
        }
    }
}

/// Petit retour visuel (succès/erreur) partagé entre les sections.
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
