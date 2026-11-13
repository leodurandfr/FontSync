// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Foundation

/// État des LaunchAgents de l'agent FontSync (`sync` + `listen`).
///
/// Source équivalente à `fontsync-agent status` (cf. `agent/launchd_setup.py`) :
/// on interroge `launchctl print gui/<uid>/<label>` directement, ce qui évite
/// d'avoir à résoudre le chemin de l'agent embarqué (laissé à P3.4). Le job
/// `listen` (process SSE long-vécu) reflète au mieux l'activité de sync.
enum LaunchdStatus {
    static let syncLabel = "com.fontsync.sync"
    static let listenLabel = "com.fontsync.listen"

    /// `true` si le job est chargé dans le domaine de l'utilisateur courant.
    static func isLoaded(_ label: String) -> Bool {
        let uid = getuid()
        let result = run("/bin/launchctl", ["print", "gui/\(uid)/\(label)"])
        return result == 0
    }

    /// État réel du job : « chargé » ne dit rien d'un job qui ne démarre plus
    /// (interpréteur disparu → `spawn failed`, `last exit code = 78`).
    static func state(_ label: String) -> AgentJobState {
        let uid = getuid()
        let (code, output) = runCapturing("/bin/launchctl", ["print", "gui/\(uid)/\(label)"])
        return AgentJobState.parse(printOutput: output, returnCode: code) {
            FileManager.default.fileExists(atPath: $0)
        }
    }

    /// Interpréteur inscrit dans le plist installé (`ProgramArguments[0]`).
    static func installedInterpreter(_ label: String) -> String? {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(label).plist")
        guard let data = try? Data(contentsOf: url),
            let plist = try? PropertyListSerialization.propertyList(from: data, format: nil)
                as? [String: Any],
            let arguments = plist["ProgramArguments"] as? [String]
        else { return nil }
        return arguments.first
    }

    /// Clé mémorisée après une réparation : la version ET l'interpréteur qu'on a
    /// trouvé dans les plists. Une même incohérence n'est réparée qu'une fois
    /// par version (pas de boucle) ; une nouvelle (app déplacée) l'est encore.
    static func repairKey(version: String, installedInterpreter: String) -> String {
        "\(version)|\(installedInterpreter)"
    }

    /// Faut-il (ré)installer les LaunchAgents ? Fonction pure (testable).
    ///
    /// - Bundle sur un volume en lecture seule (DMG) ou en quarantaine
    ///   (`AppTranslocation`) : aucune installation — des plists pointant là
    ///   cesseraient de fonctionner à l'éjection.
    /// - Plists absents : rien (l'assistant s'en charge).
    /// - Seulement pour une app dans un dossier Applications : une build de
    ///   développement réécrirait sinon les LaunchAgents réels vers un bundle
    ///   éphémère.
    /// - Plists vers un AUTRE agent : réparés seulement s'il est introuvable,
    ///   dans une autre copie de l'app ou un venv de build ; un agent installé
    ///   exprès (Homebrew, venv de développement) n'est jamais repris.
    /// - Plists vers cet agent et version changée depuis le dernier lancement
    ///   (clé absente comprise) → réinstaller, ce qui relance `listen` sur le
    ///   nouveau code.
    static func repairDecision(
        bundlePath: String,
        onReadOnlyVolume: Bool,
        bundleInterpreter: String?,
        installedInterpreter: String?,
        installedInterpreterExists: Bool,
        currentVersion: String,
        lastSeenVersion: String?,
        lastRepairKey: String?
    ) -> RepairDecision {
        if onReadOnlyVolume || bundlePath.contains("/AppTranslocation/") {
            return .refuseLocation
        }
        guard let bundleInterpreter, let installedInterpreter else { return .none }
        guard bundlePath.contains("/Applications/") else { return .none }
        let installed = URL(fileURLWithPath: installedInterpreter).standardizedFileURL.path
        let expected = URL(fileURLWithPath: bundleInterpreter).standardizedFileURL.path
        if lastRepairKey == repairKey(version: currentVersion, installedInterpreter: installed) {
            return .none
        }
        if installed != expected {
            let ours = installed.contains("/Contents/Resources/agent-venv/")
                || installed.contains("/macos-app/build/")
            if !installedInterpreterExists || ours {
                return .reinstall(reason: "interpréteur des LaunchAgents périmé (\(installed))")
            }
            return .none
        }
        if !installedInterpreterExists {
            return .reinstall(reason: "interpréteur introuvable (\(installed))")
        }
        if lastSeenVersion != currentVersion {
            return .reinstall(
                reason: "mise à jour \(lastSeenVersion ?? "antérieure") → \(currentVersion)")
        }
        return .none
    }

    /// Le bundle est-il sur un volume en lecture seule (DMG monté) ?
    static var bundleOnReadOnlyVolume: Bool {
        let values = try? Bundle.main.bundleURL.resourceValues(forKeys: [.volumeIsReadOnlyKey])
        return values?.volumeIsReadOnly ?? false
    }

    /// Message à afficher si l'app tourne depuis un emplacement où l'on
    /// n'installe rien ; `nil` sinon.
    static var locationProblem: String? {
        if bundleOnReadOnlyVolume || Bundle.main.bundleURL.path.contains("/AppTranslocation/") {
            return "Déplacez FontSync dans le dossier Applications, puis relancez-la."
        }
        return nil
    }

    /// Demande un sync au job `sync` via `launchctl kickstart` — la même voie
    /// qu'un déclenchement `WatchPaths` (P3.5 « Sync now »). Sans `-k` : un
    /// sync en cours n'est jamais tué ; la demande de tour posée avant
    /// (`~/.fontsync/sync.rerun`, lue par l'agent sous son verrou) lui fait
    /// refaire un passage. Le job doit être chargé ET capable de démarrer ;
    /// `false` sinon (l'appelant retombe sur `agent sync`, même verrou).
    static func kickstartSync() -> Bool {
        guard state(syncLabel).isHealthy else { return false }
        requestRerun()
        let uid = getuid()
        return run("/bin/launchctl", ["kickstart", "gui/\(uid)/\(syncLabel)"]) == 0
    }

    /// Pose la demande de tour supplémentaire lue par `run_sync` (agent).
    private static func requestRerun() {
        let stateDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fontsync", isDirectory: true)
        try? FileManager.default.createDirectory(at: stateDir, withIntermediateDirectories: true)
        FileManager.default.createFile(
            atPath: stateDir.appendingPathComponent("sync.rerun").path, contents: nil)
    }

    /// Lance un process ; code de sortie et sortie standard (-1 si non lançable).
    private static func runCapturing(_ launchPath: String, _ arguments: [String]) -> (Int32, String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launchPath)
        process.arguments = arguments
        let stdout = Pipe()
        process.standardOutput = stdout
        process.standardError = Pipe()
        do {
            try process.run()
            let data = stdout.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return (process.terminationStatus, String(decoding: data, as: UTF8.self))
        } catch {
            return (-1, "")
        }
    }

    /// Lance un process et renvoie son code de sortie (-1 si non lançable).
    private static func run(_ launchPath: String, _ arguments: [String]) -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launchPath)
        process.arguments = arguments
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus
        } catch {
            return -1
        }
    }
}

/// État réel d'un job launchd de l'agent (même lecture que
/// `fontsync-agent status`, cf. `agent/launchd_setup.py:job_health`).
enum AgentJobState: Equatable {
    case active
    /// Le job démarre, mais son dernier passage a échoué (serveur injoignable
    /// à l'ouverture de session…) : pas une panne, il se rattrapera.
    case lastRunFailed(exitCode: Int)
    /// Le job ne démarre pas (configuration, interpréteur non exécutable).
    case failing(exitCode: Int?)
    case missingInterpreter
    /// Sortie de `launchctl print` illisible : jamais « actif » par défaut.
    case unknown
    case absent

    var isHealthy: Bool {
        switch self {
        case .active, .lastRunFailed: return true
        default: return false
        }
    }

    var label: String {
        switch self {
        case .active: return "actif"
        case .lastRunFailed(let code): return "actif (dernier passage en erreur, exit \(code))"
        case .failing(let code): return code.map { "en échec (exit \($0))" } ?? "en échec"
        case .missingInterpreter: return "interpréteur introuvable"
        case .unknown: return "état inconnu"
        case .absent: return "absent"
        }
    }

    /// Codes d'un job qui ne démarre pas (cf. `_SPAWN_FAILURE_CODES` côté agent).
    private static let spawnFailureCodes: Set<Int> = [78, 126, 127]

    /// Lecture pure de `launchctl print` (champs de premier niveau seulement).
    static func parse(
        printOutput: String, returnCode: Int32, fileExists: (String) -> Bool
    ) -> AgentJobState {
        guard returnCode == 0 else { return .absent }
        var fields: [String: String] = [:]
        for line in printOutput.split(separator: "\n", omittingEmptySubsequences: true) {
            guard line.hasPrefix("\t"), !line.hasPrefix("\t\t") else { continue }
            let parts = line.trimmingCharacters(in: .whitespaces).components(separatedBy: " = ")
            guard parts.count >= 2 else { continue }
            let key = parts[0]
            if ["state", "job state", "program", "last exit code"].contains(key),
                fields[key] == nil
            {
                fields[key] = parts.dropFirst().joined(separator: " = ")
            }
        }
        if fields["program"] == nil && fields["state"] == nil { return .unknown }
        if let program = fields["program"], !fileExists(program) {
            return .missingInterpreter
        }
        let exitText = fields["last exit code"]?
            .components(separatedBy: ":").first?
            .trimmingCharacters(in: .whitespaces) ?? ""
        let exitCode = Int(exitText)
        let states = "\(fields["state"] ?? "") \(fields["job state"] ?? "")"
        if states.contains("spawn failed") || exitCode.map(spawnFailureCodes.contains) == true {
            return .failing(exitCode: exitCode)
        }
        let state = fields["state"] ?? ""
        if state.contains("running") && !state.contains("not running") {
            return .active
        }
        if let exitCode, exitCode != 0 {
            return .lastRunFailed(exitCode: exitCode)
        }
        return .active
    }
}

/// Décision de réparation des LaunchAgents au lancement de l'app.
enum RepairDecision: Equatable {
    case none
    case reinstall(reason: String)
    case refuseLocation
}
