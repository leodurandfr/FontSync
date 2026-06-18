// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Foundation

/// Configuration partagée avec l'agent Python (`~/.fontsync/config.yaml`).
///
/// L'app n'est qu'une télécommande au-dessus de l'agent : elle lit l'URL du
/// serveur et le token d'instance dans le **même** fichier que l'agent
/// (cf. `agent/config.py`), au lieu de dupliquer un stockage de préférences.
/// L'écriture (P3.3) viendra plus tard ; ici on se contente de lire.
struct AppConfig {
    var serverURL: URL?
    var token: String?

    /// Chemin du fichier de config, en respectant `FONTSYNC_HOME` comme l'agent.
    static var configFileURL: URL {
        let env = ProcessInfo.processInfo.environment
        let home: URL
        if let override = env["FONTSYNC_HOME"], !override.isEmpty {
            home = URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
        } else {
            home = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent(".fontsync")
        }
        return home.appendingPathComponent("config.yaml")
    }

    /// Lit la config depuis le disque. Renvoie une config vide si le fichier est
    /// absent ou illisible (premier lancement avant configuration).
    static func load() -> AppConfig {
        guard let text = try? String(contentsOf: configFileURL, encoding: .utf8) else {
            return AppConfig()
        }
        let server = parseServerBlock(text)
        var config = AppConfig()
        if let url = server["url"], let parsed = URL(string: url) {
            config.serverURL = parsed
        }
        if let token = server["token"], !token.isEmpty {
            config.token = token
        }
        return config
    }

    /// Mini-parseur YAML limité au bloc `server:` (clés `url`, `token`, …).
    ///
    /// On n'embarque pas de lib YAML pour deux clés scalaires : on lit le bloc
    /// `server:` et ses lignes indentées `clé: valeur`. Suffisant et sans
    /// dépendance pour le format produit par l'agent.
    private static func parseServerBlock(_ text: String) -> [String: String] {
        var result: [String: String] = [:]
        var inServer = false
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            // Ignore les commentaires en début de ligne.
            let trimmedLeading = line.drop(while: { $0 == " " || $0 == "\t" })
            if trimmedLeading.hasPrefix("#") { continue }

            let isIndented = line.first == " " || line.first == "\t"
            if !isIndented {
                // Nouvelle clé de premier niveau : on (re)entre dans `server`
                // uniquement pour `server:`.
                inServer = trimmedLeading.hasPrefix("server:")
                continue
            }
            guard inServer else { continue }
            guard let colon = trimmedLeading.firstIndex(of: ":") else { continue }
            let key = String(trimmedLeading[..<colon]).trimmingCharacters(in: .whitespaces)
            var value = String(trimmedLeading[trimmedLeading.index(after: colon)...])
                .trimmingCharacters(in: .whitespaces)
            // Retire un commentaire de fin de ligne et d'éventuels guillemets.
            if let hash = value.firstIndex(of: "#") {
                value = String(value[..<hash]).trimmingCharacters(in: .whitespaces)
            }
            value = value.trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            if !key.isEmpty { result[key] = value }
        }
        return result
    }
}
