// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Foundation

/// Configuration partagée avec l'agent Python (`~/.fontsync/config.yaml`).
///
/// L'app n'est qu'une télécommande au-dessus de l'agent : elle lit *et écrit*
/// l'URL du serveur et le jeton d'appareil dans le **même** fichier que l'agent
/// (cf. `agent/config.py`), au lieu de dupliquer un stockage de préférences.
/// L'écriture est **chirurgicale** : seules les clés `server.url`,
/// `server.device_token`, `server.account_email` (et le retrait de l'ancien
/// `server.token`) sont touchées ; tout le reste du fichier (`device_id`,
/// blocs `scan`/`sync`, commentaires) est préservé tel quel.
struct AppConfig {
    var serverURL: URL?
    /// Jeton d'appareil, obtenu en se connectant avec email + mot de passe.
    var deviceToken: String?
    /// Compte du jeton d'appareil (affichage seulement).
    var accountEmail: String?

    /// Le secret envoyé en `Authorization: Bearer` : le jeton d'appareil
    /// (comme l'agent). Une ancienne clé `server.token`, d'avant les comptes,
    /// est ignorée.
    var authToken: String? { deviceToken }

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

    /// Dossier où l'agent installe les fonts, en respectant `FONTSYNC_FONTS_DIR`
    /// comme l'agent (`agent/paths.py: fonts_dir`).
    ///
    /// Purement informatif côté app : ce n'est **pas** un réglage. Sur macOS,
    /// seuls `~/Library/Fonts` et `/Library/Fonts` sont des emplacements
    /// d'activation ; l'agent tourne en LaunchAgent utilisateur et n'écrit donc
    /// que dans le premier. La variable d'environnement n'existe que pour
    /// simuler plusieurs machines sur un seul Mac en développement.
    static var fontsDirectoryURL: URL {
        let env = ProcessInfo.processInfo.environment
        if let override = env["FONTSYNC_FONTS_DIR"], !override.isEmpty {
            return URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Fonts")
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
        if let deviceToken = server["device_token"], !deviceToken.isEmpty {
            config.deviceToken = deviceToken
        }
        if let email = server["account_email"], !email.isEmpty {
            config.accountEmail = email
        }
        return config
    }

    /// Mini-parseur YAML limité au bloc `server:` (clés `url`, `device_token`, …).
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
        var bare = raw
        if let hash = raw.firstIndex(of: "#") {
            bare = String(raw[..<hash]).trimmingCharacters(in: .whitespaces)
        }
        // `null`/`~` : l'agent (PyYAML) écrit ainsi une clé sans valeur.
        if bare == "null" || bare == "~" { return "" }
        return bare
    }

    // MARK: - Écriture (P3.3)

    /// Enregistre la connexion à un compte dans `~/.fontsync/config.yaml` :
    /// `server.url`, `server.device_token`, `server.account_email`, et retire
    /// une éventuelle clé `server.token` d'avant les comptes, devenue inutile.
    ///
    /// L'écriture est chirurgicale : on relit le fichier existant et on remplace
    /// (ou insère) uniquement ces clés dans le bloc `server:`, en conservant le
    /// reste (identité du device, `scan`/`sync`, commentaires). Si le fichier
    /// est absent ou vide, on crée un bloc `server:` minimal — l'agent
    /// (`AgentConfig.load`) complétera les défauts manquants au runtime.
    ///
    /// Écriture atomique + permissions `0600` (le fichier porte un jeton), à
    /// l'identique de `AgentConfig.save` côté Python.
    static func saveAccount(serverURL: String, deviceToken: String, accountEmail: String) throws {
        let values: [(String, String)] = [
            ("url", serverURL),
            ("device_token", deviceToken),
            ("account_email", accountEmail),
        ]
        let fileURL = configFileURL
        let dir = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: dir, withIntermediateDirectories: true)

        let existing = try? String(contentsOf: fileURL, encoding: .utf8)
        let text: String
        if let existing, existing.contains(where: { !$0.isWhitespace }) {
            text = mergeServerKeys(into: existing, values: values, removing: ["token"])
        } else {
            text = serverBlock(values) + "\n"
        }

        try text.write(to: fileURL, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
    }

    private static func serverBlock(_ values: [(String, String)]) -> String {
        (["server:"] + values.map { "  \($0.0): \(yamlQuote($0.1))" })
            .joined(separator: "\n")
    }

    /// Cite une valeur scalaire YAML en double-guillemets (échappe `\` et `"`).
    /// Évite tout casse-tête de quoting (`:`, `#`, espaces) pour URL et jeton.
    private static func yamlQuote(_ value: String) -> String {
        let escaped = value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        return "\"\(escaped)\""
    }

    /// Remplace/insère les clés `values` dans le bloc `server:` d'un document
    /// YAML existant, retire les clés `removing`, et préserve intégralement le
    /// reste des lignes.
    private static func mergeServerKeys(
        into text: String, values: [(String, String)], removing: Set<String>
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
        /// Clé d'une ligne enfant (`  device_token: …` → `device_token`).
        func key(of line: String) -> String? {
            guard !isComment(line) else { return nil }
            let trimmed = line.drop(while: { $0 == " " || $0 == "\t" })
            guard let colon = trimmed.firstIndex(of: ":") else { return nil }
            return String(trimmed[..<colon]).trimmingCharacters(in: .whitespaces)
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
            return serverBlock(values) + "\n" + text
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

        let wanted = Dictionary(values, uniquingKeysWith: { _, last in last })
        var done: Set<String> = []
        var result = Array(lines[0...start])  // jusqu'à la ligne `server:` incluse
        for i in (start + 1)..<end {
            let line = lines[i]
            if let k = key(of: line), let value = wanted[k] {
                result.append("\(indent)\(k): \(yamlQuote(value))")
                done.insert(k)
            } else if let k = key(of: line), removing.contains(k) {
                continue
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
        let additions = values
            .filter { !done.contains($0.0) }
            .map { "\(indent)\($0.0): \(yamlQuote($0.1))" }
        result.insert(contentsOf: additions, at: insertAt)

        if end < lines.count {
            result.append(contentsOf: lines[end..<lines.count])
        }
        return result.joined(separator: "\n")
    }
}
