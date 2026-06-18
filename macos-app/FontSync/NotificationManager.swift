// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Foundation
import UserNotifications

/// Notifications natives macOS (P3.6, rouvre B9).
///
/// `UNUserNotifications` exige un **bundle signé** : impossible depuis le CLI nu
/// de l'agent (raison du retrait en B9), débloqué par l'app signée (cf.
/// PLAN-PUBLICATION.md, « Décisions arrêtées »).
///
/// L'app étant une **télécommande** au-dessus de l'agent, on ne notifie que les
/// événements qu'elle observe réellement :
/// - **fonts synchronisées** (pull/install) : le total serveur (`/api/stats`)
///   augmente entre deux sondes ⇒ de nouvelles polices ont été importées et
///   l'agent local les a pull/installées ;
/// - **erreurs de sync** : une connexion qui marchait bascule vers
///   « injoignable » / « token invalide », ou une commande `sync` directe échoue.
///
/// Les appels sont **sans-effet** hors bundle (tests, exécution CLI) : on
/// court-circuite avant de toucher `UNUserNotificationCenter.current()`, qui
/// requiert un bundle valide.
@MainActor
enum NotificationManager {
    /// `true` si l'app tourne dans un bundle applicatif (présence d'un bundle id).
    /// Garde-fou avant d'appeler `UNUserNotificationCenter.current()`.
    private static var isBundled: Bool {
        Bundle.main.bundleIdentifier != nil
    }

    /// Demande l'autorisation (alertes + sons) au lancement. Idempotent : l'OS
    /// ne ré-affiche pas le prompt si une décision a déjà été prise.
    static func requestAuthorization() {
        guard isBundled else { return }
        UNUserNotificationCenter.current()
            .requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    /// Poste une notification immédiate. Sans-effet si l'utilisateur a refusé
    /// l'autorisation (l'OS filtre silencieusement). Un même `identifier`
    /// remplace la notification précédente plutôt que d'en empiler une copie.
    static func notify(title: String, body: String, identifier: String) {
        guard isBundled else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(
            identifier: identifier, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    // MARK: - Événements métier

    /// Notifie l'arrivée de `delta` nouvelles polices synchronisées (pull/install).
    static func notifyFontsSynced(delta: Int, total: Int) {
        let plural = delta > 1 ? "s" : ""
        notify(
            title: "FontSync",
            body: "\(delta) nouvelle\(plural) police\(plural) synchronisée\(plural).",
            // Identifiant indexé sur le total ⇒ chaque vague distincte s'affiche.
            identifier: "fontsync.fonts.\(total)")
    }

    /// Notifie une interruption de synchronisation (serveur injoignable).
    static func notifySyncOffline() {
        notify(
            title: "FontSync — synchronisation interrompue",
            body: "Le serveur est injoignable.",
            identifier: "fontsync.error.offline")
    }

    /// Notifie un rejet d'authentification (token d'instance invalide/révoqué).
    static func notifySyncUnauthorized() {
        notify(
            title: "FontSync — synchronisation interrompue",
            body: "Token d'instance invalide. Mettez-le à jour dans les préférences.",
            identifier: "fontsync.error.unauthorized")
    }

    /// Notifie l'échec d'une commande `sync` lancée explicitement (P3.5).
    static func notifySyncFailed(detail: String) {
        let trimmed = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        notify(
            title: "FontSync — échec de la synchronisation",
            body: trimmed.isEmpty ? "La commande sync a échoué." : String(trimmed.prefix(200)),
            identifier: "fontsync.error.sync")
    }
}
