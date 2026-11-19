# FontSync — Procédure de release de l'app Mac

Signature **Developer ID**, **notarisation** (notarytool), **stapling**, artefact
**`.dmg`**, et mises à jour automatiques via **Sparkle**.

> Toute la chaîne est scriptée par [`../scripts/release-macos-app.sh`](../scripts/release-macos-app.sh).
> Ce document explique les **prérequis** (à faire **une fois**), puis la
> **release courante** (à chaque version). Aucun secret n'est commité : identité,
> équipe, profil de notarisation et clés Sparkle vivent dans le Trousseau / l'env.

---

## Vue d'ensemble

```
build-agent-venv.sh ─► agent Python relocatable (Contents/Resources/agent-venv/)
        │
xcodebuild Release ─► FontSync.app signée Developer ID (+ Sparkle.framework)
        │
   embarquement   ─► agent-venv copié dans le bundle
        │
 signature inside-out ─► .so/.dylib → interpréteur (PythonAgent.entitlements)
        │                 → app (FontSync.entitlements), Hardened Runtime, horodatage
        │
      .dmg  ─► notarytool submit --wait ─► stapler staple
        │
   Sparkle  ─► sign_update / generate_appcast ─► appcast.xml
        │
 GitHub Release : FontSync-X.Y.Z.dmg + appcast.xml
```

L'app reste une **télécommande** : l'agent embarqué *est* `python -m agent`
(P0.3), aucun code de sync n'est réécrit.

---

## Prérequis (une seule fois)

### 1. Outils

```bash
xcode-select --install                 # ou Xcode complet (testé : Xcode 26)
brew install create-dmg                # facultatif (repli hdiutil sinon)
# uv : https://docs.astral.sh/uv/  (CPython standalone pour l'agent embarqué)
```

### 2. Certificat Developer ID Application

Déjà en possession (cf. décision P3). Vérifier qu'il est dans le Trousseau :

```bash
security find-identity -v -p codesigning | grep "Developer ID Application"
# → "Developer ID Application: Leo Durand (TEAMID)"
```

### 3. Profil de notarisation (notarytool)

Créer un mot de passe **app-specific** sur https://account.apple.com puis :

```bash
xcrun notarytool store-credentials FontSyncNotary \
  --apple-id "<apple-id>" \
  --team-id "TEAMID" \
  --password "xxxx-xxxx-xxxx-xxxx"      # app-specific password
```

`FontSyncNotary` = la valeur à passer en `NOTARY_PROFILE`.

### 4. Clés Sparkle (EdDSA)

Génère la paire **une fois**. La clé **privée** reste dans le Trousseau (jamais
commitée) ; la clé **publique** va dans `Info.plist`.

```bash
# Outils livrés par le paquet SPM Sparkle après une 1re résolution :
SPARKLE_BIN="$(find macos-app/build/SourcePackages/artifacts -path '*/Sparkle/bin' -type d | head -1)"
"$SPARKLE_BIN/generate_keys"
# → affiche la clé publique <SUPublicEDKey>. La copier dans macos-app/Info.plist :
#     <key>SUPublicEDKey</key><string>…</string>   (remplace le placeholder)
```

> Sauvegarder la clé privée (export Trousseau) : la **perdre** = impossible de
> publier des mises à jour signées que les anciens clients accepteront.

### 5. URL du flux Sparkle (`SUFeedURL`)

`Info.plist` pointe sur `…/releases/latest/download/appcast.xml`. Ajuster
l'`owner/repo` GitHub si nécessaire. L'`appcast.xml` est uploadé sur **chaque**
GitHub Release sous ce nom stable.

---

## Release courante

```bash
export DEVELOPER_ID_APP="Developer ID Application: Leo Durand (TEAMID)"
export TEAM_ID="TEAMID"
export NOTARY_PROFILE="FontSyncNotary"
export VERSION="1.0.0"     # CFBundleShortVersionString (visible)
export BUILD="1"           # CFBundleVersion (entier monotone — Sparkle compare dessus)

scripts/release-macos-app.sh
```

Sortie : `macos-app/dist/FontSync-1.0.0.dmg` (signé, notarisé, staplé) +
`macos-app/dist/appcast.xml`.

### Architecture : Apple silicon requis

Par défaut, la release vise **Apple silicon seul**, app ET agent (`ARCH=host`,
à lancer depuis un Mac Apple silicon) : `xcodebuild` reçoit `ARCHS=arm64
ONLY_ACTIVE_ARCH=NO`. La 0.1.1 était universelle avec un agent arm64 seul — sur
un Mac Intel l'app se lançait sans pouvoir synchroniser (M-21).

Deux contrôles bloquent la release en cas d'écart :

- **`scripts/lib/check-archs.sh`** (avant toute signature, `lipo -archs`) :
  `Contents/MacOS/FontSync` doit porter **exactement** les arches visées ;
  l'interpréteur de l'agent, chaque `.so`/`.dylib` (liens compris) et chaque
  exécutable hors de l'agent (Sparkle.framework : `Sparkle`, `Autoupdate`,
  `Updater`, services XPC) doivent **au moins** les porter (les roues
  universal2, pyobjc par exemple, et Sparkle, précompilé, gardent une tranche
  x86_64 inoffensive). Une énumération incomplète du bundle (dossier
  illisible…) arrête aussi la release.
- **`scripts/lib/check-appcast-arch.py`** (après `generate_appcast`) : l'item de
  la version doit déclarer `<sparkle:hardwareRequirements>arm64`. Sparkle ≥ 2.9
  l'ajoute **lui-même** quand le binaire principal n'a pas de tranche x86_64
  (et que `LSMinimumSystemVersion` < 27) ; le script le vérifie au lieu de
  retoucher le flux après coup, ce qui casserait un flux signé. Les Mac Intel
  ne se voient donc jamais proposer la mise à jour.

Mac Intel (P3-9, **non validé**) : `ARCH=universal2` construit l'app et le venv
pour les deux arches (venv fusionné au `lipo`, l'arche x86_64 demande **Rosetta
2** pour l'introspection uv) ; les mêmes contrôles exigent alors x86_64 partout
et l'absence d'exigence arm64 dans l'appcast. À valider sur du matériel Intel
réel avant toute release annoncée Intel.

```bash
ARCH=universal2 scripts/release-macos-app.sh
```

### Publication

La publication (tag → image Docker + `.dmg` attachés à une même GitHub Release)
est décrite de bout en bout dans **[`../docs/RELEASE.md`](../docs/RELEASE.md)** et
automatisée par `scripts/publish-release.sh` (build du `.dmg` ici + `gh release
upload`). En résumé :

1. `git tag vX.Y.Z && git push origin vX.Y.Z` → CI publie l'image Docker
   (`docker-publish.yml`) et crée la **Release en draft** (`release.yml`).
2. Sur ce Mac : `scripts/publish-release.sh` construit le `.dmg` signé +
   `appcast.xml` et les téléverse sur la Release.
3. `PUBLISH=1 scripts/publish-release.sh` (ou via l'UI) retire le draft.

`appcast.xml` doit rester accessible à l'URL `SUFeedURL` (lien
`releases/latest/download/appcast.xml`) → les clients existants y trouvent la
mise à jour. `generate_appcast` accumule les versions : republier le fichier
à jour à chaque release (le garder versionné/archivé hors-git si besoin).

---

## Ce que fait le script, étape par étape

| Étape | Détail |
|---|---|
| 1. Agent | `build-agent-venv.sh` : CPython standalone relocatable + `pip install .` (agent + httpx + pyyaml + pyobjc). |
| 2. Build | `xcodebuild` Release, signé Developer ID, Hardened Runtime + `--timestamp` ; Sparkle embarqué par SPM. |
| 3. Embarquement | `agent-venv` copié dans `Contents/Resources/`. |
| 4. Signature | **inside-out, sans `--deep`** : d'abord chaque `.so`/`.dylib`, puis les binaires interpréteur (entitlements `PythonAgent.entitlements` : `allow-unsigned-executable-memory` pour libffi/pyobjc + `disable-library-validation`), **puis re-signature de `Sparkle.framework`** (XPC, `Updater.app`, `Autoupdate`, binaire du framework) avec notre Developer ID + horodatage — l'artefact SPM arrive pré-signé par l'équipe Sparkle, non notarisable tel quel —, enfin re-sceau de l'app (`FontSync.entitlements`). |
| 5. Vérif | `codesign --verify --deep --strict` + `spctl` (refusé avant notarisation : normal). |
| 6. DMG | `create-dmg` (ou repli `hdiutil`), lien `/Applications`, puis signé. |
| 7. Notarisation | `notarytool submit --wait` puis `stapler staple` sur le `.dmg` **et** l'app. |
| 8. Sparkle | `generate_appcast` (signe avec la clé privée du Trousseau) → `appcast.xml`. |

---

## Dépannage

- **`spctl` refuse l'app/le DMG** : la notarisation n'a pas réussi ou le staple
  manque. `xcrun notarytool log <submission-id> --keychain-profile …` donne le
  détail (souvent : un binaire sans Hardened Runtime ou sans horodatage).
- **L'agent ne démarre pas une fois installé** : vérifier les entitlements de
  l'interpréteur (`codesign -d --entitlements - …/agent-venv/bin/python3`) — sans
  `allow-unsigned-executable-memory`, le Hardened Runtime tue pyobjc (libffi).
- **Sparkle ne propose pas la mise à jour** : `SUFeedURL` injoignable, `BUILD`
  non incrémenté (Sparkle compare `CFBundleVersion`), ou `SUPublicEDKey` ≠ clé de
  signature. L'item d'appcast doit pointer une URL d'enclosure HTTPS valide.
- **`safe.bareRepository` casse la résolution SPM** : le script exporte déjà
  `GIT_CONFIG_* = safe.bareRepository=all` pour le run.
