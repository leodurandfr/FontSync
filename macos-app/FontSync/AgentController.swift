// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Foundation

/// Résultat d'une invocation de l'agent : code de sortie + sortie fusionnée
/// (stdout+stderr), pour un retour utilisateur lisible dans les préférences.
struct AgentResult {
    let exitCode: Int32
    let output: String

    var succeeded: Bool { exitCode == 0 }
}

/// Pilotage du cycle de vie de l'agent Python embarqué (P3.4).
///
/// Conformément à la décision **P0.3** (cf. PLAN-PUBLICATION.md), l'agent est
/// embarqué sous forme de **venv Python relocatable** dans
/// `FontSync.app/Contents/Resources/agent-venv/`. L'app ne réécrit aucune
/// logique : elle invoque la **même** CLI que les autres canaux de packaging
/// (`python -m agent <commande>`, cf. `agent/__main__.py`).
///
/// `setup`/`teardown` installent/désinstallent les LaunchAgents launchd via
/// `fontsync-agent setup` (déjà implémenté en B10) : comme `resolve_python()`
/// inscrit `sys.executable` dans les plists, les jobs pointent **automatiquement**
/// sur l'interpréteur du bundle — la relocalisation est un non-problème (le path
/// absolu est résolu à l'install, l'app étant dans `/Applications`).
enum AgentController {
    /// Sous-chemin du venv embarqué dans `Contents/Resources/`.
    private static let embeddedRelativePath = "agent-venv/bin/python3"

    /// Dossier des journaux de l'agent (cf. `agent/launchd_setup.py`).
    static var logDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/FontSync", isDirectory: true)
    }

    /// Résout l'interpréteur Python qui sait `import agent`.
    ///
    /// Priorité :
    /// 1. le venv embarqué dans le bundle (cas distribué, P0.3) ;
    /// 2. `FONTSYNC_AGENT_PYTHON` (échappatoire de développement : pointer le
    ///    `.venv` du repo où `pip install -e .` a été lancé).
    /// `nil` ⇒ agent indisponible (l'app reste une télécommande lecture seule).
    static func pythonInterpreter() -> URL? {
        if let resources = Bundle.main.resourceURL {
            let embedded = resources.appendingPathComponent(embeddedRelativePath)
            if FileManager.default.isExecutableFile(atPath: embedded.path) {
                return embedded
            }
        }
        let env = ProcessInfo.processInfo.environment
        if let override = env["FONTSYNC_AGENT_PYTHON"], !override.isEmpty {
            let url = URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
            if FileManager.default.isExecutableFile(atPath: url.path) {
                return url
            }
        }
        return nil
    }

    /// `true` si un interpréteur agent est disponible (bundle ou dev override).
    static var isAvailable: Bool { pythonInterpreter() != nil }

    /// Lance `python -m agent <args>` de façon **synchrone** et capture la
    /// sortie. À appeler hors du thread principal (les commandes `setup`/`sync`
    /// parlent à `launchctl` et au réseau).
    @discardableResult
    static func run(_ args: [String]) -> AgentResult {
        guard let python = pythonInterpreter() else {
            return AgentResult(
                exitCode: -1,
                output: "Agent introuvable : aucun venv embarqué ni "
                    + "FONTSYNC_AGENT_PYTHON valide.")
        }

        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "agent"] + args

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        do {
            try process.run()
        } catch {
            return AgentResult(
                exitCode: -1,
                output: "Échec du lancement de l'agent : \(error.localizedDescription)")
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let output = String(data: data, encoding: .utf8) ?? ""
        return AgentResult(
            exitCode: process.terminationStatus,
            output: output.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    /// Installe et charge les LaunchAgents (`fontsync-agent setup`).
    static func setup() -> AgentResult { run(["setup"]) }

    /// Décharge et supprime les LaunchAgents (`fontsync-agent teardown`).
    static func teardown() -> AgentResult { run(["teardown"]) }

    /// Lance une synchronisation ponctuelle directe (`fontsync-agent sync`).
    /// Utilisé comme repli quand le job launchd `sync` n'est pas chargé (le
    /// `kickstart` n'aurait alors rien à relancer).
    static func sync() -> AgentResult { run(["sync"]) }
}
