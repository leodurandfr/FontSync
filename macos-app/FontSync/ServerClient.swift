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
    case http(Int)
    case transport(Error)
    case malformed
}

/// Client HTTP minimal vers le serveur FontSync.
///
/// Porte le token d'instance en `Authorization: Bearer` (cf. P1.1/P1.3) sur
/// `/api/*`. Utilisé par le menu pour vérifier la connectivité et le nombre de
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
}
