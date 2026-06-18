// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Foundation

/// Configuration partagée avec l'agent Python (`~/.fontsync/config.yaml`).
///
/// L'app n'est qu'une télécommande au-dessus de l'agent : elle lit *et écrit*
/// l'URL du serveur et le token d'instance dans le **même** fichier que l'agent
/// (cf. `agent/config.py`), au lieu de dupliquer un stockage de préférences.
/// L'écriture (P3.3) est **chirurgicale** : seules les clés `server.url` et
/// `server.token` sont touchées ; tout le reste du fichier (identité
/// `device_id`/`device_token`, blocs `scan`/`sync`, commentaires) est préservé
/// tel quel, car ce sont des états gérés par l'agent.
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
            let rawValue = String(trimmedLeading[trimmedLeading.index(after: colon)...])
                .trimmingCharacters(in: .whitespaces)
            let value = parseScalar(rawValue)
            if !key.isEmpty { result[key] = value }
        }
        return result
    }

    /// Décode un scalaire YAML simple (valeur après `clé:`).
    ///
    /// Symétrique de l'écriture (`yamlQuote`) : une valeur **entre guillemets**
    /// est prise telle quelle (un `#` à l'intérieur n'est pas un commentaire),
    /// guillemets doubles déséchappés (`\\`, `\"`). Une valeur **nue** voit son
    /// éventuel commentaire de fin de ligne (` #…`) retiré.
    private static func parseScalar(_ raw: String) -> String {
        if let first = raw.first, first == "\"" || first == "'" {
            // Cherche le guillemet fermant correspondant (gère l'échappement
            // par backslash pour les guillemets doubles).
            let chars = Array(raw)
            var i = 1
            var out = ""
            while i < chars.count {
                let c = chars[i]
                if first == "\"", c == "\\", i + 1 < chars.count {
                    out.append(chars[i + 1])
                    i += 2
                    continue
                }
                if c == first { return out }
                out.append(c)
                i += 1
            }
            return out  // guillemet fermant manquant : on rend ce qu'on a lu
        }
        // Valeur nue : un `#` débute un commentaire de fin de ligne.
        if let hash = raw.firstIndex(of: "#") {
            return String(raw[..<hash]).trimmingCharacters(in: .whitespaces)
        }
        return raw
    }

    // MARK: - Écriture (P3.3)

    /// Écrit `server.url` et `server.token` dans `~/.fontsync/config.yaml`.
    ///
    /// L'écriture est chirurgicale : on relit le fichier existant et on remplace
    /// (ou insère) uniquement ces deux clés dans le bloc `server:`, en
    /// conservant le reste (identité du device, `scan`/`sync`, commentaires).
    /// Si le fichier est absent ou vide, on crée un bloc `server:` minimal —
    /// l'agent (`AgentConfig.load`) complétera les défauts manquants au runtime.
    ///
    /// Écriture atomique + permissions `0600` (le fichier porte un token), à
    /// l'identique de `AgentConfig.save` côté Python.
    static func save(serverURL: String, token: String) throws {
        let fileURL = configFileURL
        let dir = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: dir, withIntermediateDirectories: true)

        let existing = try? String(contentsOf: fileURL, encoding: .utf8)
        let text: String
        if let existing, existing.contains(where: { !$0.isWhitespace }) {
            text = mergeServerKeys(into: existing, url: serverURL, token: token)
        } else {
            text = "server:\n  url: \(yamlQuote(serverURL))\n  token: \(yamlQuote(token))\n"
        }

        try text.write(to: fileURL, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
    }

    /// Cite une valeur scalaire YAML en double-guillemets (échappe `\` et `"`).
    /// Évite tout casse-tête de quoting (`:`, `#`, espaces) pour URL et token.
    private static func yamlQuote(_ value: String) -> String {
        let escaped = value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        return "\"\(escaped)\""
    }

    /// Remplace/insère `url:` et `token:` dans le bloc `server:` d'un document
    /// YAML existant, en préservant intégralement le reste des lignes.
    private static func mergeServerKeys(
        into text: String, url: String, token: String
    ) -> String {
        let lines = text.components(separatedBy: "\n")

        func isComment(_ line: String) -> Bool {
            line.drop(while: { $0 == " " || $0 == "\t" }).hasPrefix("#")
        }
        func isTopLevel(_ line: String) -> Bool {
            guard let first = line.first, first != " ", first != "\t" else { return false }
            let leading = line.drop(while: { $0 == " " || $0 == "\t" })
            return !leading.isEmpty && !leading.hasPrefix("#")
        }

        // Localise le bloc `server:`.
        var serverStart: Int?
        for (i, line) in lines.enumerated() where isTopLevel(line) {
            if line.drop(while: { $0 == " " }).hasPrefix("server:") {
                serverStart = i
                break
            }
        }
        guard let start = serverStart else {
            // Aucun bloc server : on le préfixe au document.
            let block = "server:\n  url: \(yamlQuote(url))\n  token: \(yamlQuote(token))"
            return block + "\n" + text
        }

        // Fin du bloc = prochaine clé de premier niveau (ou fin de fichier).
        var end = lines.count
        if start + 1 < lines.count {
            for i in (start + 1)..<lines.count where isTopLevel(lines[i]) {
                end = i
                break
            }
        }

        // Indentation des enfants (déduite de la 1re ligne indentée, défaut 2).
        var indent = "  "
        for i in (start + 1)..<end {
            let line = lines[i]
            if (line.first == " " || line.first == "\t"), !isComment(line) {
                indent = String(line.prefix(while: { $0 == " " || $0 == "\t" }))
                break
            }
        }

        var result = Array(lines[0...start])  // jusqu'à la ligne `server:` incluse
        var urlDone = false
        var tokenDone = false
        for i in (start + 1)..<end {
            let line = lines[i]
            let trimmed = line.drop(while: { $0 == " " || $0 == "\t" })
            if !isComment(line), trimmed.hasPrefix("url:") {
                result.append("\(indent)url: \(yamlQuote(url))")
                urlDone = true
            } else if !isComment(line), trimmed.hasPrefix("token:") {
                result.append("\(indent)token: \(yamlQuote(token))")
                tokenDone = true
            } else {
                result.append(line)
            }
        }

        // Insère les clés manquantes après le dernier enfant du bloc (avant
        // d'éventuelles lignes vides de séparation).
        var insertAt = result.count
        while insertAt > start + 1,
            result[insertAt - 1].trimmingCharacters(in: .whitespaces).isEmpty
        {
            insertAt -= 1
        }
        var additions: [String] = []
        if !urlDone { additions.append("\(indent)url: \(yamlQuote(url))") }
        if !tokenDone { additions.append("\(indent)token: \(yamlQuote(token))") }
        result.insert(contentsOf: additions, at: insertAt)

        if end < lines.count {
            result.append(contentsOf: lines[end..<lines.count])
        }
        return result.joined(separator: "\n")
    }
}
