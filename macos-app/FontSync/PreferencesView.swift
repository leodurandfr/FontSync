// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import SwiftUI

/// Fenêtre de préférences (P3.3 + P3.4).
///
/// - **Serveur (P3.3)** : saisie URL + token, écrits dans le `~/.fontsync/config.yaml`
///   partagé avec l'agent (`AppConfig.save`), avec un **test de connexion**
///   (`GET /api/stats`) avant/après enregistrement.
/// - **Agent (P3.4)** : installe/désinstalle les LaunchAgents via le venv
///   embarqué (`AgentController` → `fontsync-agent setup/teardown`), et reflète
///   l'état launchd.
struct PreferencesView: View {
    @ObservedObject var model: AppModel

    @State private var urlString = ""
    @State private var token = ""
    @State private var loaded = false

    /// Retour utilisateur du test de connexion / de l'enregistrement.
    @State private var serverFeedback: Feedback?
    @State private var testing = false
    @State private var saving = false

    /// Retour utilisateur des actions agent (install/désinstall).
    @State private var agentFeedback: Feedback?
    @State private var agentBusy = false

    var body: some View {
        Form {
            Section("Serveur") {
                TextField("URL", text: $urlString, prompt: Text("http://nas.local:8080"))
                    .textContentType(.URL)
                    .disableAutocorrection(true)
                SecureField("Token d'instance", text: $token)

                if let feedback = serverFeedback {
                    feedback.view
                }

                HStack {
                    Button("Tester la connexion") { testConnection() }
                        .disabled(testing || trimmedURL.isEmpty)
                    Spacer()
                    Button("Enregistrer") { save() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(saving || trimmedURL.isEmpty)
                }
            }

            Section("Agent") {
                LabeledContent("État") { Text(agentStatusLabel) }

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

    /// Pré-remplit depuis la config existante (une seule fois par ouverture).
    private func loadFields() {
        guard !loaded else { return }
        loaded = true
        let config = AppConfig.load()
        urlString = config.serverURL?.absoluteString ?? ""
        token = config.token ?? ""
    }

    private var agentStatusLabel: String {
        switch (model.syncJobLoaded, model.listenJobLoaded) {
        case (true, true): return "Actif (sync + listen chargés)"
        case (false, false): return "Arrêté"
        default: return "Partiel"
        }
    }

    // MARK: - Actions serveur (P3.3)

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
                serverFeedback = .success("Connecté — \(count) font(s).")
            } catch ServerError.unauthorized {
                serverFeedback = .failure("Token invalide (401/403).")
            } catch {
                serverFeedback = .failure("Serveur injoignable.")
            }
        }
    }

    private func save() {
        saving = true
        serverFeedback = nil
        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            try AppConfig.save(serverURL: trimmedURL, token: trimmedToken)
            serverFeedback = .success("Préférences enregistrées.")
            model.refresh()
        } catch {
            serverFeedback = .failure("Échec de l'écriture : \(error.localizedDescription)")
        }
        saving = false
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
