// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import Sparkle
import SwiftUI

/// Pont SwiftUI au-dessus de **Sparkle** (mises à jour de l'app, P3.7).
///
/// Sparkle est piloté par un `SPUStandardUpdaterController` qui démarre dès le
/// lancement : il vérifie périodiquement le flux `SUFeedURL` (cf. Info.plist),
/// télécharge le `.dmg`/`.zip` signé EdDSA (`SUPublicEDKey`) et propose
/// l'installation. On expose juste une commande « Rechercher des mises à jour… »
/// et l'état `canCheckForUpdates` pour griser le menu pendant une vérification.
///
/// Les clés de configuration (`SUFeedURL`, `SUPublicEDKey`, intervalle) vivent
/// dans `Info.plist` ; la signature du flux et des artefacts est faite à la
/// release par `scripts/release-macos-app.sh` (cf. `macos-app/RELEASE.md`).
@MainActor
final class UpdaterViewModel: ObservableObject {
    private let controller: SPUStandardUpdaterController

    /// `false` pendant une vérification en cours (évite les déclenchements
    /// concurrents) — câblé sur le KVO de Sparkle.
    @Published var canCheckForUpdates = false

    init() {
        // `startingUpdater: true` → planificateur actif immédiatement. Pas de
        // délégué custom : le comportement standard (UI Sparkle) suffit pour
        // une télécommande mince.
        controller = SPUStandardUpdaterController(
            startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
        controller.updater.publisher(for: \.canCheckForUpdates)
            .assign(to: &$canCheckForUpdates)
    }

    /// Vérification manuelle (depuis le menu). Affiche l'UI Sparkle même si
    /// aucune mise à jour n'est disponible (retour utilisateur explicite).
    func checkForUpdates() {
        controller.checkForUpdates(nil)
    }
}
