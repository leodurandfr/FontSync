# FontSync — Process de release (GitHub Releases)

Runbook **unifié** pour publier une version.
Une release FontSync = **deux artefacts versionnés** attachés à une même
**GitHub Release** taggée `vX.Y.Z** :

| Artefact | Construit par | Où |
|---|---|---|
| **Image Docker** multi-arch (amd64 + arm64) | CI (`.github/workflows/docker-publish.yml`) | `ghcr.io/<owner>/<repo>:X.Y.Z` (+ `X.Y`, `latest`) |
| **`FontSync-X.Y.Z.dmg`** signé + notarisé | **localement** (Mac + Developer ID) | attaché à la Release |
| **`appcast.xml`** (flux Sparkle) | localement (Sparkle) | attaché à la Release |

Le `.dmg` est signé/notarisé **hors CI** : la signature Developer ID exige le
certificat et les clés Sparkle, jamais commités (cf.
[`../macos-app/RELEASE.md`](../macos-app/RELEASE.md) pour les prérequis détaillés).

---

## Pourquoi cette séparation

- **Le serveur** se distribue par image OCI : reproductible, multi-arch, publiée
  automatiquement par GitHub Actions sur chaque tag.
- **L'app Mac** doit être signée avec un secret personnel (Developer ID) et
  notarisée par Apple → l'étape vit sur une machine du mainteneur, pas dans un
  runner public.

Les deux convergent sur **une seule GitHub Release par version**. Le flux de
mise à jour Sparkle vit à part, sur une URL stable qui ne dépend pas de
« latest » : l'asset `appcast.xml` de la release fixe `appcast`
(`SUFeedURL` → `releases/download/appcast/appcast.xml`, depuis la 0.1.2), et
chaque enclosure pointe sur sa release versionnée
(`releases/download/vX.Y.Z/FontSync-X.Y.Z.dmg`).

---

## Étapes d'une release

> **Un tag `v*` publié ne se déplace jamais et ne se supprime pas** : pour
> corriger une release, on publie la version de patch suivante. Le dépôt
> l'impose (ruleset `protect-release-tags`), comme il interdit le force-push et
> la suppression de `main` (ruleset `protect-main`). Les actions des workflows
> doivent être épinglées par SHA de commit (réglage du dépôt) ;
> `scripts/check-repo-settings.sh` vérifie ces réglages.

### 1. Tagger la version

```bash
git tag v1.0.0
git push origin v1.0.0
```

Le push du tag déclenche **deux workflows** en parallèle :

- `docker-publish.yml` → **d'abord le job `test`** (le workflow `ci.yml` : ruff,
  pytest, build typé et tests du frontend), **puis seulement** le build & push
  de l'image `ghcr.io/<owner>/<repo>:1.0.0` (+ `1.0`, `latest`), amd64 + arm64.
  Un test rouge = aucune image publiée.
- `release.yml` → création de la **GitHub Release en draft** `v1.0.0`, avec des
  notes auto-générées et la commande `docker pull` pré-remplie.

> La Release est en **draft** : elle n'apparaît pas encore comme « latest » et
> son `appcast.xml` n'est pas servi tant qu'on ne l'a pas publiée — on attache
> d'abord le `.dmg`.

### 2. Construire et téléverser l'app Mac (sur un Mac avec Developer ID)

```bash
export DEVELOPER_ID_APP="Developer ID Application: Leo Durand (TEAMID)"
export TEAM_ID="TEAMID"
export NOTARY_PROFILE="FontSyncNotary"
export VERSION="1.0.0"     # = le tag sans le « v »
export BUILD="1"           # CFBundleVersion, entier monotone (Sparkle compare dessus)

# Construit le .dmg signé+notarisé + appcast.xml, puis les téléverse sur la Release.
scripts/publish-release.sh
```

`publish-release.sh` enchaîne :

1. `scripts/release-macos-app.sh` → `macos-app/dist/FontSync-1.0.0.dmg` +
   `appcast.xml` (build agent embarqué → xcodebuild Release signé → signature
   inside-out → `.dmg` → notarisation/stapling → Sparkle) ;
2. `gh release upload v1.0.0 …dmg appcast.xml --clobber`.

> L'app vise **Apple silicon seul** (contrôles `lipo` et appcast bloquants).
> `ARCH=universal2` (Mac Intel) n'est pas validé : cf. `macos-app/RELEASE.md`
> → « Architecture : Apple silicon requis ».

### 3. Publier la Release

Vérifier le contenu (DMG présent, notes correctes), puis retirer le draft :

```bash
PUBLISH=1 SKIP_BUILD=1 scripts/publish-release.sh   # jamais « via l'UI » : le flux stable ne serait pas mis à jour
```

Avant tout envoi, `publish-release.sh` vérifie l'appcast
(`scripts/lib/check-appcast.py`) : un seul item pour `$VERSION`, `BUILD`
identique, enclosure sur `releases/download/v$VERSION/` avec la taille et la
signature EdDSA du DMG (comparée à `sign_update` s'il est disponible), et
chaque autre item sur sa propre release `v<version>/`. Au moindre écart, rien ne part ; sans
appcast, `PUBLISH=1` est refusé.

Avec `PUBLISH=1`, l'ordre est fixe : la release `vX.Y.Z` est publiée
(`--latest`), **puis** l'appcast est téléversé sur la release `appcast` (créée
au besoin en pré-release, `--latest=false`) — jamais avant, sinon le flux
annoncerait un DMG encore en draft (404).

- Clients ≥ 0.1.2 : ils lisent le flux stable, que rien d'autre ne touche.
- Clients ≤ 0.1.1 : ils lisent encore `releases/latest/download/appcast.xml`.
  Tant qu'il en reste, chaque release de l'app doit rester « latest » avec son
  `appcast.xml`, et **aucune autre release** (serveur seul, par exemple) ne
  doit être publiée en « latest » sans appcast : ces clients ne verraient plus
  aucune mise à jour.
- Refus de `PUBLISH=1` : version pré-release (`-rc1`…), tag `vX.Y.Z` absent du
  dépôt local, ou version qui n'est pas le plus haut tag final (le flux stable
  et « latest » reculeraient). Une pré-release se publie à la main, en
  `--prerelease --latest=false`, sans toucher au flux stable.
- `--clobber` retire l'ancien asset avant d'envoyer le nouveau : si l'envoi du
  flux stable échoue, le script le dit et donne la commande de relance ; les
  clients réessaient à leur prochain contrôle, sans rien installer.
- Ne pas activer l'immuabilité des releases du dépôt (réglage GitHub) : la
  release `appcast` ne pourrait plus être mise à jour.

---

## Audit des dépendances

- Le job `audit` de `ci.yml` (`pip-audit` sur `requirements.txt` et ses
  dépendances transitives, `npm audit --omit=dev --audit-level=high` sur le
  frontend) tourne à chaque push, chaque lundi, et **avant toute image** : un
  avis connu bloque la publication.
- Corriger d'abord (montée de version, `npm audit fix`). Si un avis ne concerne
  pas FontSync (code non atteignable), l'ignorer **explicitement** dans
  `ci.yml` (`pip-audit --ignore-vuln <ID>`), avec en commentaire la raison, la
  date et une date de revue. Jamais de contournement silencieux.
- Chaque image publiée est aussi scannée par Trivy (job `image-scan`, non
  bloquant) : le rapport est l'artefact `image-scan` du run.

---

## Vérifications post-release

```bash
# Image serveur réellement multi-arch
docker buildx imagetools inspect ghcr.io/<owner>/<repo>:1.0.0

# DMG signé, notarisé, staplé
spctl --assess --type install --verbose=4 macos-app/dist/FontSync-1.0.0.dmg

# Appcast servi aux deux URL Sparkle (flux stable ≥ 0.1.2, ancien flux ≤ 0.1.1)
curl -fsSL https://github.com/<owner>/<repo>/releases/download/appcast/appcast.xml | head
curl -fsSL https://github.com/<owner>/<repo>/releases/latest/download/appcast.xml | head
# Enclosure versionnée téléchargeable
curl -fsSIL https://github.com/<owner>/<repo>/releases/download/v1.0.0/FontSync-1.0.0.dmg | head -1
```

Un Mac déjà installé en version antérieure doit proposer la mise à jour
(menu → « Rechercher des mises à jour… », ou vérification quotidienne automatique).

---

## Rollback

- **Serveur** : chaque build publie aussi un tag **immuable** `sha-<7 caractères>`
  (les tags de version et de branche peuvent bouger, `latest` ne suit que la
  plus haute version). Avant toute mise à jour, noter l'image en cours :
  `docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' fontsync`
  (le commit ; `--cleanup` de Watchtower efface l'ancienne image locale, son
  identifiant ne sert donc à rien). Pour revenir en arrière,
  épingler dans le compose l'image précédente par son tag
  (`image: ghcr.io/<owner>/<repo>:sha-<court>`) ou son digest, puis
  `docker compose -f docker-compose.nas.yml up -d`. Ne jamais déplacer un tag
  `v*` déjà publié.
- **Release avec migration de schéma** : le conteneur prend un instantané
  `pre-migrate-<révision>-<date>.db` avant de migrer, et une image plus
  ancienne refuse de démarrer sur la base migrée (message explicite). Revenir
  en arrière = restaurer cet instantané (`scripts/restore-from-backup.sh`)
  puis épingler l'image précédente : procédure complète dans
  [INSTALL-NAS.md](INSTALL-NAS.md) §5 (« Roll back an update »). Une release
  qui migre le schéma le signale dans ses notes, en précisant si le
  `downgrade()` de la migration est sans perte (seul cas où `alembic
  downgrade` est une alternative) — à écrire à la main avant de publier.
- **App** : republier l'`appcast.xml` sans l'entrée défaillante (Sparkle ne
  proposera plus la version retirée) ; les `.dmg` déjà téléchargés restent
  valides. Ne **jamais** réutiliser un numéro `BUILD` déjà publié.

---

## Aide-mémoire des fichiers

| Fichier | Rôle |
|---|---|
| `.github/workflows/ci.yml` | Lint + tests (backend, agent, frontend) à chaque push/PR, et avant toute image |
| `.github/workflows/docker-publish.yml` | Tests puis build & push image serveur (P2.2) |
| `.github/workflows/release.yml` | Crée la GitHub Release sur tag (P4.3) |
| `scripts/release-macos-app.sh` | Build app signée + `.dmg` + appcast (P3.7) |
| `scripts/publish-release.sh` | Téléverse `.dmg`/appcast sur la Release (P4.3) |
| `macos-app/RELEASE.md` | Prérequis signature/notarisation/Sparkle |
