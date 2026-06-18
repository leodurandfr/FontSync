# FontSync — App Mac (menu bar)

App macOS native (Swift/SwiftUI) servant de **télécommande** au-dessus de l'agent
FontSync. Couvre la Phase P3 de [`../PLAN-PUBLICATION.md`](../PLAN-PUBLICATION.md).

> L'app ne réécrit aucune logique de sync : l'agent Python (`../agent/`) reste le
> moteur, le serveur reste la source de vérité. L'app lit l'URL serveur + le token
> dans le **même** `~/.fontsync/config.yaml` que l'agent.

## État

- **P3.1 — Menu bar** ✅ `MenuBarExtra` : statut connecté/déconnecté, nombre de
  fonts (`GET /api/stats`), dernière vérification, état de l'agent launchd
  (`com.fontsync.sync` / `com.fontsync.listen`).
- **P3.2 — Fenêtre « nue »** ✅ « Ouvrir FontSync » → fenêtre `WKWebView` chargeant
  l'UI web servie par le serveur.
- **P3.3 — Préférences** ✅ Fenêtre `Settings` (⌘,) : saisie URL + token, **écriture
  chirurgicale** dans `~/.fontsync/config.yaml` (préserve `device_id`/`scan`/`sync`),
  avec **test de connexion** (`GET /api/stats`).
- **P3.4 — Cycle de vie de l'agent** ✅ `AgentController` résout le venv Python
  **embarqué** (`Contents/Resources/agent-venv/`, cf. P0.3) et pilote
  `fontsync-agent setup`/`teardown` ; installation/désinstallation depuis les
  préférences, statut launchd remonté.
- **P3.5 — Actions menu** ✅ Synchroniser maintenant (`launchctl kickstart`, repli
  `agent sync`), Ouvrir les journaux (`~/Library/Logs/FontSync/`), Préférences, Quitter.
- **P3.6 — Notifications natives** ✅ `UNUserNotifications` (`NotificationManager`) :
  fonts pull/install (delta du total serveur) + erreurs de sync.
- **P3.7 — Signature & distribution** ✅ Sparkle intégré (mises à jour auto),
  chaîne Developer ID + notarisation + `.dmg` scriptée. Voir **[`RELEASE.md`](RELEASE.md)**.

## Architecture

| Fichier | Rôle |
|---|---|
| `FontSync/FontSyncApp.swift` | `@main`, scènes `MenuBarExtra` (P3.1) + `Window` webview (P3.2) |
| `FontSync/MenuContent.swift` | Contenu du menu : statut + actions |
| `FontSync/AppModel.swift` | État observable (connexion, fonts, launchd), sonde périodique |
| `FontSync/ServerClient.swift` | Client `GET /api/stats` avec `Authorization: Bearer` |
| `FontSync/LaunchdStatus.swift` | État des LaunchAgents via `launchctl print` |
| `FontSync/AppConfig.swift` | Lecture de `~/.fontsync/config.yaml` (URL + token) |
| `FontSync/WebView.swift` | `WKWebView` (NSViewRepresentable) + contenu de la fenêtre |
| `FontSync/PreferencesView.swift` | Préférences (URL/token + test de connexion, actions agent) |
| `FontSync/AgentController.swift` | Résolution du venv embarqué + `fontsync-agent setup/teardown/sync` |
| `FontSync/NotificationManager.swift` | Notifications natives (`UNUserNotifications`, P3.6) |
| `FontSync/Updater.swift` | Pont SwiftUI au-dessus de Sparkle (mises à jour, P3.7) |
| `Info.plist` | `LSUIElement` (hors Dock) + ATS (HTTP clair) + clés Sparkle (`SUFeedURL`/`SUPublicEDKey`) |
| `FontSync.entitlements` | Entitlements de l'app (Hardened Runtime, non sandboxée) |
| `PythonAgent.entitlements` | Entitlements de l'interpréteur embarqué (libffi/pyobjc) |

> **Développement sans bundle agent** : tant que le venv embarqué n'est pas packagé
> (P3.7), exportez `FONTSYNC_AGENT_PYTHON` vers le Python du repo (`pip install -e .`)
> pour activer les actions agent depuis l'app lancée à la main.

## Build

Prérequis : Xcode 16+ (testé avec Xcode 26, macOS 14+ comme cible).

```bash
# Compiler
xcodebuild -project macos-app/FontSync.xcodeproj -scheme FontSync -configuration Debug build

# Ou ouvrir dans Xcode
open macos-app/FontSync.xcodeproj
```

La cible se signe en ad-hoc (`CODE_SIGN_IDENTITY = -`) pour le dev. La **release**
signée Developer ID + notarisée + `.dmg` + appcast Sparkle est entièrement
scriptée — voir **[`RELEASE.md`](RELEASE.md)** :

```bash
# Construit l'agent embarqué seul (debug)
../scripts/build-agent-venv.sh --out build/agent-venv

# Release complète (signature/notarisation/dmg/appcast)
VERSION=1.0.0 BUILD=1 DEVELOPER_ID_APP="Developer ID Application: …" \
  TEAM_ID=… NOTARY_PROFILE=… ../scripts/release-macos-app.sh
```

> Note SPM : Sparkle est résolu depuis https://github.com/sparkle-project/Sparkle.
> Si `git config safe.bareRepository=explicit` est posé globalement, exporter
> `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.bareRepository GIT_CONFIG_VALUE_0=all`
> avant `xcodebuild` (le script de release le fait déjà).
