// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

// Vérifications des fonctions pures de LaunchdStatus.swift. Le projet n'a pas
// de cible XCTest : compilées à part avec le fichier testé (macos-app/checks/run.sh).

import Foundation

func check(_ condition: Bool, _ message: String) {
    if !condition {
        print("ÉCHEC : \(message)")
        exit(1)
    }
    print("ok : \(message)")
}

let exists: (String) -> Bool = { $0 == "/app/python3" }

func printOutput(_ program: String, state: String, last: String, jobState: String? = nil) -> String {
    var text = "gui/501/com.fontsync.sync = {\n\tstate = \(state)\n\tprogram = \(program)\n"
    text += "\targuments = {\n\t\t\(program)\n\t}\n"
    if let jobState { text += "\tjob state = \(jobState)\n" }
    text += "\tlast exit code = \(last)\n}\n"
    return text
}

func parse(_ output: String, _ code: Int32 = 0) -> AgentJobState {
    AgentJobState.parse(printOutput: output, returnCode: code, fileExists: exists)
}

let appPython = "/Applications/FontSync.app/Contents/Resources/agent-venv/bin/python3"

func decide(
    bundle: String = "/Applications/FontSync.app",
    readOnly: Bool = false,
    installed: String? = appPython,
    installedExists: Bool = true,
    current: String = "7",
    lastSeen: String? = "7",
    lastRepairKey: String? = nil
) -> RepairDecision {
    LaunchdStatus.repairDecision(
        bundlePath: bundle,
        onReadOnlyVolume: readOnly,
        bundleInterpreter: appPython,
        installedInterpreter: installed,
        installedInterpreterExists: installedExists,
        currentVersion: current,
        lastSeenVersion: lastSeen,
        lastRepairKey: lastRepairKey)
}

func isReinstall(_ decision: RepairDecision) -> Bool {
    if case .reinstall = decision { return true }
    return false
}

@main
enum LaunchdStatusChecks {
    static func main() {
        jobStateChecks()
        repairDecisionChecks()
        print("TOUT EST VERT")
    }
}

// --- État des jobs ---------------------------------------------------------
func jobStateChecks() {
    check(parse("", 113) == .absent, "absent")
    check(parse("format inattendu\n") == .unknown, "sortie illisible → état inconnu, jamais actif")
    check(
        parse(printOutput("/app/python3", state: "not running", last: "78: EX_CONFIG", jobState: "spawn failed"))
            == .failing(exitCode: 78), "job state = spawn failed → en échec (78)")
    check(
        parse(printOutput("/app/python3", state: "not running", last: "2", jobState: "spawn failed"))
            == .failing(exitCode: 2), "spawn failed quel que soit le code")
    check(
        parse(printOutput("/gone/python3", state: "not running", last: "0")) == .missingInterpreter,
        "interpréteur introuvable")
    check(
        parse(printOutput("/app/python3", state: "running", last: "1")) == .active,
        "en cours d'exécution → actif malgré un dernier code 1")
    check(
        parse(printOutput("/app/python3", state: "not running", last: "1")) == .lastRunFailed(exitCode: 1),
        "dernier passage en erreur → sain, signalé")
    check(AgentJobState.lastRunFailed(exitCode: 1).isHealthy, "dernier passage en erreur reste sain")
    check(
        parse(printOutput("/app/python3", state: "running", last: "(never exited)")) == .active,
        "actif (jamais sorti)")
}

// --- Décision de réparation -----------------------------------------------
func repairDecisionChecks() {
    check(decide() == .none, "à jour → rien")
    check(decide(bundle: "/Volumes/FontSync/FontSync.app", readOnly: true) == .refuseLocation, "DMG → refus")
    check(decide(bundle: "/Volumes/Externe/Applications/FontSync.app") == .none, "Applications sur disque externe → accepté")
    check(
        decide(bundle: "/private/var/folders/x/AppTranslocation/y/d/FontSync.app") == .refuseLocation,
        "quarantaine → refus")
    check(decide(installed: nil) == .none, "non installé → rien (l'assistant s'en charge)")
    check(
        decide(bundle: "/Users/x/Library/Developer/Xcode/DerivedData/F/Build/Products/Debug/FontSync.app", lastSeen: "6")
            == .none, "build de développement → jamais de réparation auto")
    check(isReinstall(decide(bundle: "/Users/x/Applications/FontSync.app", lastSeen: "6")), "~/Applications → réparation possible")
    check(isReinstall(decide(installed: "/Users/x/FontSync/macos-app/build/agent-venv/bin/python3")), "venv de build → réinstaller")
    check(isReinstall(decide(installed: "/Applications/Old FontSync.app/Contents/Resources/agent-venv/bin/python3", installedExists: false)), "autre copie disparue → réinstaller")
    check(isReinstall(decide(installedExists: false)), "interpréteur disparu → réinstaller")
    check(decide(installed: "/opt/homebrew/Cellar/fontsync/0.1.1/libexec/bin/python", lastSeen: "6") == .none, "agent Homebrew installé exprès → jamais repris")
    check(isReinstall(decide(lastSeen: "6")), "mise à jour → réinstaller (relance listen)")
    check(isReinstall(decide(lastSeen: nil)), "clé absente + agents de cette app → réinstaller une fois")
    check(decide(installed: nil, lastSeen: nil) == .none, "installation neuve (agents absents) → rien")
    let doneKey = LaunchdStatus.repairKey(version: "7", installedInterpreter: appPython)
    check(decide(installedExists: false, lastRepairKey: doneKey) == .none, "même incohérence déjà réparée pour cette version → pas de boucle")
    check(
        isReinstall(decide(installed: "/Applications/Ancienne.app/Contents/Resources/agent-venv/bin/python3", installedExists: false, lastRepairKey: doneKey)),
        "nouvelle incohérence dans la même version (app déplacée) → réparer encore")
}
