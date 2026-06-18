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
- P3.3+ (préférences, cycle de vie agent, actions, notifications, signature) : à venir.

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
| `Info.plist` | `LSUIElement` (hors Dock) + ATS (HTTP clair en LAN) |

## Build

Prérequis : Xcode 16+ (testé avec Xcode 26, macOS 14+ comme cible).

```bash
# Compiler
xcodebuild -project macos-app/FontSync.xcodeproj -scheme FontSync -configuration Debug build

# Ou ouvrir dans Xcode
open macos-app/FontSync.xcodeproj
```

La cible se signe en ad-hoc (`CODE_SIGN_IDENTITY = -`) pour le dev. La signature
Developer ID + notarisation est traitée en P3.7.
