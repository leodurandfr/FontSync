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

Les deux convergent sur **une seule GitHub Release par version**, qui sert aussi
de flux de mise à jour Sparkle (`SUFeedURL` →
`releases/latest/download/appcast.xml`).

---

## Étapes d'une release

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

> Pour couvrir les Macs Intel, viser `ARCH=universal2` (cf.
> `macos-app/RELEASE.md` → « Architecture (Intel) »).

### 3. Publier la Release

Vérifier le contenu (DMG présent, notes correctes), puis retirer le draft :

```bash
PUBLISH=1 scripts/publish-release.sh      # ou : gh release edit v1.0.0 --draft=false --latest
```

Publier rend l'`appcast.xml` accessible à l'URL Sparkle stable
(`releases/latest/download/appcast.xml`) → les clients existants détectent la
mise à jour. Si seul l'appcast a changé (re-signature), `--clobber` le remplace
en place.

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

# Appcast servi à l'URL Sparkle
curl -fsSL https://github.com/<owner>/<repo>/releases/latest/download/appcast.xml | head
```

Un Mac déjà installé en version antérieure doit proposer la mise à jour
(menu → « Rechercher des mises à jour… », ou vérification quotidienne automatique).

---

## Rollback

- **Serveur** : chaque build publie aussi un tag **immuable** `sha-<7 caractères>`
  (les tags de version et de branche peuvent bouger, `latest` ne suit que la
  plus haute version). Avant toute mise à jour, noter l'image en cours :
  `docker inspect --format '{{.Image}}' fontsync`. Pour revenir en arrière,
  épingler dans le compose l'image précédente par son tag
  (`image: ghcr.io/<owner>/<repo>:sha-<court>`) ou son digest, puis
  `docker compose -f docker-compose.nas.yml up -d`. Ne jamais déplacer un tag
  `v*` déjà publié.
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
