// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Foundation

/// Réponse partielle de `GET /api/stats` (JSON camelCase, cf. backend).
/// On ne décode que `totalFonts` : c'est tout ce dont le menu a besoin.
private struct StatsResponse: Decodable {
    let totalFonts: Int
}

enum ServerError: Error {
    case notConfigured
    case unauthorized
    /// Trop d'essais de connexion (le serveur limite à 5 échecs par minute).
    case tooManyAttempts
    /// Serveur d'avant les comptes : pas de `/api/auth/device-login`.
    case accountsUnsupported
    case http(Int)
    case transport(Error)
    case malformed
}

/// Réponse partielle de `POST /api/auth/device-login`.
private struct DeviceLoginResponse: Decodable {
    struct User: Decodable { let email: String }
    let token: String
    let user: User
}

private struct DeviceLoginRequest: Encodable {
    let email: String
    let password: String
    let deviceName: String
}

/// Client HTTP minimal vers le serveur FontSync.
///
/// Porte le jeton d'appareil (ou, hérité, le token d'instance) en
/// `Authorization: Bearer` sur `/api/*`. Utilisé par le menu pour vérifier la connectivité et le nombre de
/// fonts ; la fenêtre webview (P3.2) charge l'UI web directement.
struct ServerClient {
    let baseURL: URL
    let token: String?

    /// Récupère le nombre total de fonts. Sert aussi de sonde de connectivité
    /// (et de validité du token) : un succès ⇒ « connecté ».
    func fetchTotalFonts() async throws -> Int {
        let url = baseURL.appendingPathComponent("api/stats")
        var request = URLRequest(url: url)
        request.timeoutInterval = 8
        if let token, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw ServerError.transport(error)
        }

        guard let http = response as? HTTPURLResponse else {
            throw ServerError.malformed
        }
        if http.statusCode == 401 || http.statusCode == 403 {
            throw ServerError.unauthorized
        }
        guard (200..<300).contains(http.statusCode) else {
            throw ServerError.http(http.statusCode)
        }
        guard let stats = try? JSONDecoder().decode(StatsResponse.self, from: data) else {
            throw ServerError.malformed
        }
        return stats.totalFonts
    }

    /// Échange email + mot de passe contre un **jeton d'appareil** propre à ce
    /// Mac (`POST /api/auth/device-login`). Le mot de passe n'est jamais
    /// stocké : seul le jeton l'est, dans `~/.fontsync/config.yaml`.
    ///
    /// - Returns: le jeton et l'email du compte, tel que le serveur l'a écrit.
    static func deviceLogin(
        baseURL: URL, email: String, password: String, deviceName: String
    ) async throws -> (token: String, email: String) {
        let url = baseURL.appendingPathComponent("api/auth/device-login")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            DeviceLoginRequest(email: email, password: password, deviceName: deviceName))

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw ServerError.transport(error)
        }
        guard let http = response as? HTTPURLResponse else {
            throw ServerError.malformed
        }
        switch http.statusCode {
        case 201, 200: break
        case 401, 403: throw ServerError.unauthorized
        case 429: throw ServerError.tooManyAttempts
        case 404, 405: throw ServerError.accountsUnsupported
        default: throw ServerError.http(http.statusCode)
        }
        guard let body = try? JSONDecoder().decode(DeviceLoginResponse.self, from: data) else {
            throw ServerError.malformed
        }
        return (body.token, body.user.email)
    }
}

extension ServerError {
    /// Message affiché dans l'assistant et les préférences.
    var userMessage: String {
        switch self {
        case .unauthorized: return "Email ou mot de passe incorrect."
        case .tooManyAttempts: return "Trop d'essais. Réessayez dans une minute."
        case .accountsUnsupported:
            return "Ce serveur ne gère pas encore les comptes : mettez-le à jour."
        case .notConfigured: return "Serveur non configuré."
        case .http(let code): return "Le serveur a répondu une erreur (HTTP \(code))."
        case .transport: return "Serveur injoignable."
        case .malformed: return "Réponse inattendue du serveur."
        }
    }
}

/// Connexion de ce Mac à un compte, partagée par l'assistant et les préférences.
enum AccountConnection {
    /// Nom du Mac montré dans « Mes sessions » de l'interface web.
    static var deviceName: String {
        Host.current().localizedName ?? "Mac"
    }

    /// Se connecte (ou vérifie la connexion existante) puis enregistre la config.
    ///
    /// - Mot de passe saisi : échange email + mot de passe contre un jeton
    ///   d'appareil, vérifie qu'il ouvre bien l'API, puis l'enregistre (l'ancien
    ///   token d'instance est retiré du fichier).
    /// - Mot de passe vide, même serveur, jeton déjà présent : vérifie seulement
    ///   ce jeton, sans ouvrir une nouvelle session.
    ///
    /// - Returns: le nombre de polices de la bibliothèque (affiché en retour).
    static func connect(urlString: String, email: String, password: String) async throws -> Int {
        guard let baseURL = URL(string: urlString), baseURL.scheme != nil else {
            throw ConnectionInputError.invalidURL
        }
        let existing = AppConfig.load()
        if password.isEmpty {
            guard let token = existing.deviceToken,
                existing.serverURL?.absoluteString == urlString
            else {
                throw ConnectionInputError.missingPassword
            }
            return try await ServerClient(baseURL: baseURL, token: token).fetchTotalFonts()
        }
        let login = try await ServerClient.deviceLogin(
            baseURL: baseURL, email: email, password: password, deviceName: deviceName)
        let count = try await ServerClient(baseURL: baseURL, token: login.token)
            .fetchTotalFonts()
        try AppConfig.saveAccount(
            serverURL: urlString, deviceToken: login.token, accountEmail: login.email)
        return count
    }

    /// Message lisible pour n'importe quelle erreur de `connect`.
    static func message(for error: Error) -> String {
        if let error = error as? ServerError { return error.userMessage }
        if let error = error as? ConnectionInputError { return error.message }
        return "Échec de l'enregistrement : \(error.localizedDescription)"
    }
}

enum ConnectionInputError: Error {
    case invalidURL
    case missingPassword

    var message: String {
        switch self {
        case .invalidURL: return "URL invalide."
        case .missingPassword: return "Saisissez votre mot de passe."
        }
    }
}
