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
