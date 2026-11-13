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

    /// Demande un sync au job `sync` via `launchctl kickstart` — la même voie
    /// qu'un déclenchement `WatchPaths` (P3.5 « Sync now »). Sans `-k` : un
    /// sync en cours n'est jamais tué ; la demande de tour posée avant
    /// (`~/.fontsync/sync.rerun`, lue par l'agent sous son verrou) lui fait
    /// refaire un passage. Le job doit être chargé ; `false` sinon
    /// (l'appelant retombe sur `agent sync`, protégé par le même verrou).
    static func kickstartSync() -> Bool {
        guard isLoaded(syncLabel) else { return false }
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
