# FontSync — Spécifications techniques v3.0

> Font manager self-hosted avec synchronisation multi-machines en temps réel
> Document de référence pour le développement avec Claude Code — Mars 2026

> ⚠️ **Refonte en cours (juin 2026).** Ce document décrit la **vision produit** d'origine.
> L'**architecture technique cible** (base **SQLite**, agent **stateless** déclenché par launchd,
> push réactif par **SSE** au lieu d'un WebSocket côté agent) est définie dans **`PLAN.md`** à la
> racine — c'est la source de vérité en cas de divergence. Les sections **3 (stack)**, **6 (agent)**
> et **8 (déploiement)** ont été mises à jour pour refléter cette cible ; d'autres passages (ex. le
> WebSocket agent, la table `sync_queue`, le file watcher `watchdog`) restent décrits dans leur forme
> d'origine et sont en cours de retrait — se référer à PLAN.md.

---

## 1. Vision du projet

FontSync est un gestionnaire de polices auto-hébergé qui centralise toutes les fonts d'un utilisateur sur un serveur Docker (NAS local ou serveur cloud), les rend accessibles via une interface web en temps réel, et les synchronise automatiquement avec les machines connectées via un agent Python.

### Le principe central

Le serveur FontSync est le **hub central** de toutes les polices. Quand une nouvelle font est installée sur n'importe quelle machine (Machine A), l'agent la détecte en temps réel, la push vers le serveur, et le serveur notifie instantanément tous les autres agents connectés (Machine B, C...) qui peuvent alors récupérer la font automatiquement. Le frontend web reflète ces changements en temps réel sans rechargement de page.

```
Machine A                    Serveur FontSync                Machine B
(MacBook)                    (NAS Docker)                   (Mac Mini)
                             
  Installe                                                   
  "Inter.ttf"                                                
      │                                                      
      ▼                                                      
  Agent détecte    ──push──►  Reçoit + stocke    ──notify──► Agent reçoit
  (file watcher)              Parse métadonnées               notification
                              Notifie via WebSocket           
                                     │                        ▼
                              ┌──────┴──────┐          Télécharge +
                              │  Frontend   │          installe "Inter.ttf"
                              │  mis à jour │          (auto ou manuel
                              │  en temps   │           selon config)
                              │  réel       │
                              └─────────────┘
```

### Objectifs principaux

- **Centraliser** : un seul endroit pour toutes ses polices (système, projets clients, Google Fonts)
- **Synchroniser en temps réel** : détection automatique des nouvelles fonts, propagation instantanée
- **Naviguer** : interface web riche pour prévisualiser, chercher et télécharger
- **Auto-héberger** : Docker sur NAS local ou serveur cloud européen

### Principes directeurs

- Le **serveur est la source de vérité** pour la bibliothèque et les métadonnées
- L'agent peut **désinstaller** des fonts localement sur ordre explicite de l'utilisateur (via le frontend), mais la font reste toujours sur le serveur
- L'utilisateur a toujours le **contrôle explicite** sur ce qui est installé sur sa machine
- La communication est **temps réel** : WebSocket entre serveur, agents et frontend
- Le code dans ce document est **purement illustratif** — Claude Code implémente selon les meilleures pratiques

---

## 2. Scope — MVP vs. Évolutions futures

### MVP (Phases 1-3)

Le MVP cible un **usage personnel** entre les machines d'un seul utilisateur. C'est le cœur du produit : l'agent détecte les fonts, le serveur centralise, les machines se synchronisent.

**Inclus dans le MVP :**
- Serveur Docker (FastAPI + SQLite)
- Agent Python avec détection automatique des fonts (commande `sync` stateless déclenchée par launchd)
- Synchronisation bidirectionnelle (push nouvelles fonts vers serveur, pull depuis serveur)
- Parsing automatique des métadonnées via fonttools (famille, style, poids, classification, langues, glyphes)
- Stockage sur filesystem ou object storage S3-compatible
- Interface web avec mise à jour temps réel (WebSocket)
- Grille de fonts avec lazy loading des previews via @font-face
- Page de détail d'une font (preview waterfall, métadonnées, langues)
- Recherche full-text + filtres (classification, format, scripts, poids)
- Upload basique depuis l'interface (formulaire simple, pas de drag & drop élaboré)
- Téléchargement de fonts depuis l'interface
- UX de première synchronisation (scan initial avec progression)
- Page Devices (machines connectées, état de sync)
- Packaging agent macOS signé + notarisé

**Explicitement exclus du MVP :**
- Auto-groupement en familles (Phase 4)
- Catégories, collections, tags (Phase 4)
- Google Fonts (Phase 5)
- Détection de doublons visuels (Phase 5)
- Mode comparaison de fonts (Phase 5)
- Variable Fonts interactifs (Phase 6)
- Conversion TTF/OTF → WOFF2 (Phase 6)
- Authentification / multi-utilisateurs / rôles (Phase 7)
- Partage public via lien URL (Phase 7)

---

## 3. Architecture globale

### Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend API | Python 3.12+, FastAPI, Uvicorn |
| Base de données | **SQLite** (`aiosqlite`, `journal_mode=WAL`, `foreign_keys=ON`) |
| ORM | SQLAlchemy (async) + Alembic (migrations) |
| Parsing de fonts | fonttools |
| Temps réel | **WebSocket frontend** (FastAPI natif) + **SSE** pour le push « re-sync » vers l'agent |
| Stockage fonts | Filesystem local OU S3-compatible (abstraction) |
| Frontend | Vue 3 (Composition API, TypeScript), shadcn-vue, Tailwind CSS, Vite |
| State management | Pinia |
| Agent client | Python 3.12+, **commande `sync` stateless** déclenchée par **launchd**, `httpx` (HTTP + SSE), pyobjc (Core Text) |
| Déploiement | Docker Compose (un seul conteneur) |

> **Pourquoi SQLite ?** Usage mono-utilisateur, un seul process serveur sur le NAS, base petite et
> jetable en dev. Postgres ne redevient pertinent qu'à un éventuel mode multi-utilisateurs (Phase 7).

### Abstraction storage

Le stockage des fonts est abstrait derrière une interface commune pour supporter deux backends :

**Filesystem local** (défaut, NAS) : les fonts sont stockées dans un volume Docker monté, organisées par hash SHA-256 (`/data/fonts/{hash[0:2]}/{hash}.{ext}`).

**Object storage S3-compatible** (cloud) : pour un déploiement sur serveur distant. Compatible avec Scaleway Object Storage, OVH Object Storage, MinIO, AWS S3, etc.

L'abstraction expose : `store(hash, file_data) → path`, `retrieve(hash) → file_data`, `delete(hash)`, `exists(hash) → bool`. Le backend choisit l'implémentation selon la configuration (`STORAGE_BACKEND=filesystem` ou `STORAGE_BACKEND=s3`).

### Communication temps réel

Deux canaux distincts, selon l'interlocuteur :

#### Frontend ↔ Serveur — WebSocket

Le frontend maintient une connexion WebSocket permanente (`WS /ws/client`) et met à jour l'interface en temps réel sans rechargement.

**Serveur → Frontend :**
- `font.added` : nouvelle font ajoutée (par un agent ou par upload) → rafraîchir la grille
- `font.deleted` : font supprimée → retirer de la grille
- `font.updated` : métadonnées modifiées (édition, restore) → mettre à jour la carte
- `device.connected` / `device.disconnected` : un agent se manifeste / disparaît
- `sync.progress` : progression d'une sync en cours
- `sync.completed` : sync terminée (stats)

**Frontend → Serveur :**
- `install.request` : demande d'installation d'une font sur un device spécifique (relayé à l'agent)

#### Serveur → Agent — SSE (signal « re-sync »)

Plus de WebSocket côté agent. Le serveur expose un endpoint **SSE** (`GET /api/agent/{device_id}/events`) que le process `listen` de l'agent consomme. Quand une font devient disponible pour ce device, le serveur émet un événement **`sync`** : un **simple signal sans payload exploité** (pas de `font_id` à interpréter → pas de bug de clé). À réception, `listen` se contente de **déclencher la commande `sync`** (avec debounce), qui recalcule le delta depuis l'état réel du disque.

L'agent ne « pousse » pas d'événements temps réel vers le serveur : tout passe par les appels HTTP de la commande `sync` (register/update device, `POST /api/sync/delta`, push, pull). Le `last_seen_at` du device est mis à jour à chaque appel HTTP de l'agent.

---

## 4. Modèle de données

### 4.1 Tables MVP

#### `fonts`

Chaque enregistrement = un fichier font physique unique, identifié par son hash SHA-256.

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | UUID (PK) | Identifiant unique |
| `file_hash` | VARCHAR(64), UNIQUE | SHA-256 du fichier — clé de déduplication |
| `original_filename` | VARCHAR(500) | Nom de fichier d'origine |
| `file_size` | INTEGER | Taille en bytes |
| `file_format` | VARCHAR(10) | `ttf`, `otf`, `woff`, `woff2`, `ttc` |
| `storage_path` | VARCHAR(500) | Chemin relatif dans le storage |
| `family_name` | VARCHAR(500) | nameID 16 ou fallback nameID 1 |
| `subfamily_name` | VARCHAR(200) | nameID 17 ou fallback nameID 2 (Regular, Bold...) |
| `full_name` | VARCHAR(500) | nameID 4 |
| `postscript_name` | VARCHAR(500) | nameID 6 |
| `version` | VARCHAR(100) | nameID 5 |
| `designer` | VARCHAR(500) | nameID 9 |
| `manufacturer` | VARCHAR(500) | nameID 8 (foundry) |
| `license` | TEXT | nameID 13 |
| `license_url` | VARCHAR(1000) | nameID 14 |
| `description` | TEXT | nameID 10 |
| `weight_class` | INTEGER | usWeightClass (100-900), table OS/2 |
| `width_class` | INTEGER | usWidthClass (1-9), table OS/2 |
| `is_italic` | BOOLEAN | fsSelection flag |
| `is_oblique` | BOOLEAN | fsSelection flag |
| `panose` | VARCHAR(30) | Classification Panose |
| `classification` | VARCHAR(50) | Auto-détecté : `serif`, `sans-serif`, `monospace`, `display`, `handwriting`, `symbol` |
| `unicode_ranges` | JSONB | Ranges Unicode supportés |
| `supported_scripts` | JSONB | Ex: `["latin", "cyrillic", "arabic"]` |
| `glyph_count` | INTEGER | Nombre de glyphes |
| `is_variable` | BOOLEAN | Est-ce une Variable Font ? |
| `variable_axes` | JSONB | Axes de variation si variable (tag, min, max, default) |
| `source` | VARCHAR(50) | `upload`, `local_scan`, `google_fonts` |
| `source_device_id` | UUID (FK → devices, nullable) | Device d'origine si scan local |
| `google_fonts_id` | VARCHAR(200) | Identifiant Google Fonts si applicable |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `deleted_at` | TIMESTAMPTZ, nullable | Soft delete |

Index : `family_name`, `classification`, `file_hash`, `source`, `deleted_at`, GIN sur `supported_scripts`.

#### `devices`

Machines enregistrées auprès du serveur.

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | UUID (PK) | |
| `name` | VARCHAR(200) | Ex: "MacBook Pro de Léo" |
| `hostname` | VARCHAR(200) | |
| `os` | VARCHAR(50) | `macos`, `linux`, `windows` |
| `os_version` | VARCHAR(100) | |
| `agent_version` | VARCHAR(20) | |
| `last_seen_at` | TIMESTAMPTZ | Dernier heartbeat |
| `last_sync_at` | TIMESTAMPTZ | Dernière sync complète |
| `sync_status` | VARCHAR(20) | `idle`, `syncing`, `error` |
| `font_directories` | JSONB | Dossiers surveillés |
| `auto_pull` | BOOLEAN | Installer auto les nouvelles fonts du serveur |
| `created_at` | TIMESTAMPTZ | |

#### `device_fonts`

Fonts connues comme étant présentes sur un device.

| Colonne | Type | Description |
|---------|------|-------------|
| `device_id` | UUID (FK → devices) | |
| `font_id` | UUID (FK → fonts) | |
| `local_path` | VARCHAR(1000) | Chemin sur le device |
| `installed_at` | TIMESTAMPTZ | |
| PK | (device_id, font_id) | |

#### `sync_queue`

File d'attente pour les opérations de sync.

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | UUID (PK) | |
| `device_id` | UUID (FK → devices) | |
| `font_id` | UUID (FK → fonts) | |
| `operation` | VARCHAR(20) | `push_to_server`, `pull_to_device` |
| `status` | VARCHAR(20) | `pending`, `in_progress`, `completed`, `failed` |
| `error_message` | TEXT | |
| `created_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |

### 4.2 Tables ajoutées en phases ultérieures

**Phase 4 — Familles & Organisation :**
- `font_families` (id, name, slug, designer, manufacturer, classification, description, style_count, is_auto_grouped)
- `font_family_members` (font_id PK → fonts, family_id → font_families, sort_order)
- `categories` (id, name, slug, description, color, parent_id self-ref, sort_order)
- `font_categories` (font_id, category_id)
- `collections` (id, name, slug, description, color, icon)
- `collection_fonts` (collection_id, font_id, sort_order, added_at)

**Phase 5 — Doublons :**
- `duplicate_groups` (id, status, resolved_font_id, created_at, resolved_at)
- `duplicate_group_members` (group_id, font_id)

### 4.3 Stockage des fichiers

Organisation par les 2 premiers caractères du hash SHA-256 :

```
/data/fonts/
├── ab/
│   ├── abcdef1234567890...ttf
│   └── ab12fe9876543210...otf
├── cd/
│   └── cd5678abcdef1234...ttf
└── ...
```

En mode S3, même structure utilisée comme clé d'objet (`fonts/ab/abcdef...ttf`).

---

## 5. API Backend (FastAPI)

### 5.1 Endpoints MVP

#### Fonts

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/fonts` | Lister (filtres, pagination, tri) |
| `GET` | `/api/fonts/{id}` | Détail complet |
| `GET` | `/api/fonts/{id}/file` | Télécharger le fichier |
| `GET` | `/api/fonts/{id}/preview` | Fichier pour @font-face |
| `POST` | `/api/fonts/upload` | Upload basique de fichier(s) |
| `PATCH` | `/api/fonts/{id}` | Modifier les métadonnées |
| `DELETE` | `/api/fonts/{id}` | Soft delete |
| `POST` | `/api/fonts/{id}/restore` | Restaurer |

**Filtres sur `GET /api/fonts` :**

| Paramètre | Description |
|-----------|-------------|
| `search` | Recherche full-text (nom, famille, designer) |
| `classification` | serif, sans-serif, monospace, display, handwriting, symbol |
| `format` | ttf, otf (filtres multiples séparés par virgule) |
| `scripts` | latin, cyrillic, arabic, etc. |
| `is_variable` | true/false |
| `weight_min` / `weight_max` | Plage de poids (100-900) |
| `sort` | name, created_at, family_name, glyph_count, file_size |
| `order` | asc, desc |
| `page` / `per_page` | Pagination (défaut 50) |

#### Devices & Sync

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/devices/register` | Enregistrer un device |
| `GET` | `/api/devices` | Lister les devices |
| `PATCH` | `/api/devices/{id}` | Mettre à jour |
| `DELETE` | `/api/devices/{id}` | Supprimer |
| `POST` | `/api/sync/delta` | Delta sync : hashes locaux → différences |
| `POST` | `/api/sync/push` | Push font(s) vers le serveur |
| `GET` | `/api/sync/pull/{font_id}` | Pull une font depuis le serveur |
| `GET` | `/api/sync/queue/{device_id}` | File d'attente de sync |

#### WebSocket

| Endpoint | Description |
|----------|-------------|
| `WS /ws/client` | Connexion WebSocket pour le frontend |
| `WS /ws/agent/{device_id}` | Connexion WebSocket pour un agent |

#### Statistiques

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/stats` | Stats globales |

### 5.2 Endpoints ajoutés par phase

| Phase | Endpoints |
|-------|-----------|
| Phase 4 | CRUD `/api/families`, CRUD `/api/categories`, CRUD `/api/collections`, batch operations |
| Phase 5 | `/api/google-fonts` (browse, import), `/api/duplicates` (scan, resolve) |
| Phase 7 | `/api/auth/login`, `/api/share/create`, `GET /api/share/{token}` (public, sans auth) |

### 5.3 Pipeline d'import

Déclenché par un upload web OU par un push d'agent :

```
1. Réception du fichier
   └─► Validation (magic bytes, extension, taille max)
   
2. Hash SHA-256
   └─► Doublon exact ? → skip, retourner la font existante
   
3. Stockage (filesystem ou S3 selon config)
   
4. Parsing fonttools (wrappé dans try/catch — ne jamais rejeter une font)
   ├─► Table 'name' : family, subfamily, designer, version, license...
   ├─► Table 'OS/2' : weight, width, panose, italic/oblique
   ├─► Table 'cmap' : codepoints → scripts/langues
   ├─► Table 'fvar' : axes variable (si applicable)
   ├─► Table 'post' : isFixedPitch
   └─► Table 'maxp' : glyph count
   
5. Auto-classification (heuristique : Panose + nom + isFixedPitch)
   
6. Insertion en base
   
7. Notification WebSocket → font.added (tous les clients connectés)
```

Formats acceptés : **TTF, OTF** (installables par l'agent). **WOFF, WOFF2** : acceptés au stockage et prévisualisables dans le navigateur, mais non proposés à l'installation système (ce sont des formats web uniquement). **TTC** : chaque font du TrueType Collection est extraite individuellement.

---

## 6. Agent client Python (MVP)

> Architecture refondue (cf. PLAN.md, Phase B). L'agent **n'est plus un démon WebSocket** : c'est une
> **commande `sync` stateless** déclenchée par launchd, plus un petit process `listen` qui ne fait que
> relayer le signal SSE du serveur. Cette section décrit la cible.

### 6.1 Rôle

L'agent est le composant critique du MVP — c'est lui qui fait de FontSync plus qu'un simple hébergeur de fonts. Il se décompose en **deux exécutables sans état persistant mutable** :

- **`fontsync sync`** — commande courte, idempotente, exécutée puis terminée :
  `discover (Core Text + dossiers) → hash (avec cache) → register/update device → POST /sync/delta → push les inconnues → pull les manquantes (si auto_pull) → install → exit`.
- **`fontsync listen`** — process long-vécu minimal (launchd `KeepAlive`) : ouvre la connexion **SSE** au serveur et, à chaque signal, **déclenche `sync`** (debounce ~2 s). Zéro état, zéro hash.

Le serveur (NAS, toujours allumé) est la **source de vérité**. L'agent repart toujours de l'état réel du disque — aucun ensemble de hashes en mémoire à maintenir entre deux exécutions.

### 6.2 Déclencheurs de `sync`

La commande `sync` est **identique quelle que soit sa source**. Trois déclencheurs (launchd) :

| Déclencheur | Mécanisme launchd | Rôle |
|-------------|-------------------|------|
| Changement local | `WatchPaths` sur `~/Library/Fonts` (option `/Library/Fonts`) | Push réactif des fonts ajoutées localement |
| Signal distant | process `listen` (SSE) → lance `sync` | Pull réactif quand une font devient disponible |
| Filet de sécurité | `StartInterval` (~600 s) + `RunAtLoad` | Rattrapage des événements manqués |

#### Découverte des fonts via APIs système

| OS | API de découverte | Dossiers gérés (per-user) |
|----|-------------------|---------------------------|
| macOS | Core Text via `pyobjc` | `~/Library/Fonts`, `/Library/Fonts` |
| Linux | `fc-list` (fontconfig) | `~/.local/share/fonts`, `/usr/local/share/fonts` |
| Windows | DirectWrite via `ctypes` | `%LOCALAPPDATA%\Microsoft\Windows\Fonts` |

Les dossiers système read-only (`/System/Library/Fonts` sur macOS, `/usr/share/fonts` sur Linux, `C:\Windows\Fonts` sur Windows) ne sont **pas gérés** — ce sont des fonts OS qu'on ne veut pas syncer. (MVP : macOS prioritaire.)

#### Cache de hash local

Calculer le SHA-256 de centaines de fichiers à chaque `sync` serait coûteux. L'agent maintient un cache `(path, size, mtime) → hash` dans `~/.fontsync/` : seuls les fichiers nouveaux ou modifiés (mtime/size changés) sont re-hashés. Un scan de 500 fonts devient quasi gratuit après la première fois. **C'est le seul état persisté côté agent — purement un cache, reconstructible.**

### 6.3 Première synchronisation

Le premier `sync` fait le gros du travail (cache vide → tout est hashé) :

1. `discover` : énumère les fonts via Core Text + les dossiers gérés.
2. Hash SHA-256 de chaque fichier (cache vide au premier passage).
3. Register / update du device auprès du serveur (`POST /api/devices/register`).
4. Envoi du delta (`POST /api/sync/delta`).
5. Push des fonts inconnues du serveur.
6. Pull des fonts manquantes si `auto_pull`.

Les `sync` suivants sont quasi instantanés grâce au cache.

### 6.4 Protocole de sync

**Enregistrement :** l'agent s'enregistre avec nom, hostname, OS, version → reçoit/réutilise un `device_id` (persisté localement, cf. config).

**Delta sync :** l'agent envoie ses hashes → le serveur répond avec trois ensembles :
- `unknown_to_server` : fonts à pusher
- `missing_on_device` : fonts disponibles à puller
- `already_synced` : à jour

Le calcul du delta côté serveur est une **lecture pure** (pas d'écriture, pas de `commit` au milieu).

**Push :** pour chaque font de `unknown_to_server`, l'agent envoie le fichier (`POST /api/sync/push`). L'import serveur est **idempotent** sur le `file_hash` (deux pushs concurrents du même hash → une seule font). Le serveur émet alors le signal SSE `sync` vers les autres devices concernés.

**Pull :** pour chaque font de `missing_on_device`, si `auto_pull: true`, l'agent télécharge (`GET /api/sync/pull/{font_id}`) et installe. Le serveur enregistre de façon fiable l'association `device_font`. Si `auto_pull: false`, rien n'est installé automatiquement — l'utilisateur déclenche l'installation via le frontend (relayé à l'agent).

### 6.5 Installation de fonts par OS

L'agent installe toujours en **per-user** (pas de droits admin nécessaires) :
- **macOS** : copie dans `~/Library/Fonts/`
- **Linux** : copie dans `~/.local/share/fonts/` + rebuild cache fontconfig
- **Windows** : copie dans le dossier per-user + écriture registre HKCU

Après installation, l'agent peut afficher une notification système : "Font Inter installée — redémarrez vos applications design pour l'utiliser".

### 6.6 Comportement de suppression

**L'agent ne supprime jamais de fonts localement de manière automatique.**
- L'utilisateur peut désinstaller une font d'un appareil via le frontend. La font reste toujours sur le serveur — seule l'installation locale est supprimée. (La désinstallation devrait s'appuyer sur un mapping **par hash** plutôt que par nom, cf. PLAN.md B7.)
- Font supprimée sur le serveur (soft delete) → les devices ne sont pas affectés, le prochain `sync` n'installe simplement plus cette font.
- Font supprimée localement par l'utilisateur (hors FontSync) → le prochain `sync` la voit disparaître du disque ; le serveur ne supprime pas la font de sa bibliothèque (il reste la source de vérité).

### 6.7 Canal temps réel (SSE)

Plus de WebSocket côté agent (ni reconnexion avec backoff, ni delta-sync « au rétablissement »). Le process **`listen`** ouvre une connexion **SSE** (`GET /api/agent/{device_id}/events`) via `httpx.stream`. À chaque événement `sync` reçu, il déclenche la commande `fontsync sync` (debounce ~2 s). La résilience se réduit à une **boucle de reconnexion triviale** (sleep + retry) ; le `StartInterval` launchd sert de filet. L'événement étant un simple signal, aucune donnée n'est à interpréter → pas de désynchronisation possible.

### 6.8 Configuration

Fichier `~/.fontsync/config.yaml` :
- `server.url` : URL du serveur FontSync
- `device_token` : token d'identification (généré à l'enregistrement, **persisté**)
- `device_id` : identifiant du device (reçu à l'enregistrement, **persisté**)
- `scan.directories` : override des dossiers gérés
- `scan.ignore_patterns` : patterns à ignorer (ex: `.*`, `System*`)
- `sync.auto_pull` : install auto des fonts du serveur

> Bug historique à corriger (PLAN.md B5) : `device_id`/token n'étaient pas réécrits au `save()`. Le push étant désormais déclenché par `WatchPaths`, il n'y a plus de flag `auto_push` ni d'`interval_minutes` (remplacé par `StartInterval` launchd).

### 6.9 Déclenchement depuis le frontend

Il n'y a plus d'endpoint local `localhost:7850` (la contrainte CORS/mixed-content disparaît). Pour installer une font sur un device, le frontend envoie `install.request` au **serveur** (via son WebSocket frontend) ; le serveur émet le signal SSE `sync` vers le device concerné, qui pull et installe au prochain `sync`. Aucun contournement CORS nécessaire.

### 6.10 Packaging macOS

Beaucoup moins critique qu'avec un démon `.app` (on n'a plus qu'une CLI `sync` + un petit `listen`). Décision différée (PLAN.md B10) : binaire/pkg signé simple vs PyInstaller. La friction de notarisation est largement levée. L'installation se fait via deux **LaunchAgents** :
- `com.fontsync.sync.plist` : `WatchPaths` + `StartInterval` ~600 s + `RunAtLoad`
- `com.fontsync.listen.plist` : `KeepAlive` + `RunAtLoad`

chargés/déchargés par `launchctl bootstrap` / `bootout`.

---

## 7. Frontend (Vue 3 + shadcn-vue)

### 7.1 Pages MVP

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Stats, fonts récemment ajoutées, devices connectés |
| `/fonts` | Bibliothèque | Grille de fonts avec filtres et recherche |
| `/fonts/:id` | Détail font | Preview, waterfall, métadonnées, langues |
| `/devices` | Devices | Machines connectées, état de sync, config |
| `/settings` | Paramètres | Configuration serveur |

Pages ajoutées par phase :

| Phase | Routes |
|-------|--------|
| Phase 4 | `/families`, `/families/:id`, `/categories`, `/collections`, `/collections/:id` |
| Phase 5 | `/google-fonts`, `/duplicates` |

### 7.2 Temps réel (WebSocket)

Le frontend établit une connexion WebSocket au chargement (`WS /ws/client`) et la maintient tout au long de la session. Tous les changements sont reflétés instantanément :

- Nouvelle font ajoutée (par un agent ou un upload) → apparaît dans la grille sans refresh
- Font supprimée → disparaît de la grille
- Device connecté/déconnecté → mise à jour de la page Devices
- Sync en cours → indicateur de progression dans le header

En cas de perte de connexion WebSocket, le frontend tente une reconnexion automatique et affiche un indicateur "Reconnexion en cours..." dans l'interface.

### 7.3 Composants clés

#### FontCard

Chaque carte affiche :
- Un rendu live dans la font (chargé via `FontFace API` + Intersection Observer pour le lazy loading)
- Nom + style
- Classification + nombre de glyphes
- Badges langues/scripts principaux
- Bouton "Télécharger" (si pas d'agent) ou "Installer" (si agent connecté, commande relayée via WebSocket)

**Lazy loading** : les fonts ne sont chargées via @font-face que quand la carte entre dans le viewport. Les fonts hors viewport sont déchargées pour économiser la mémoire.

#### FontPreview (page de détail)

- **Preview interactive** : texte personnalisable (défaut : pangram), rendu dans la font
- **Waterfall** : tailles 12, 16, 20, 24, 32, 48, 64, 72px
- **Métadonnées** : toutes les infos fonttools
- **Langues** : badges scripts avec couverture
- **Glyphes** : grille paginée des caractères disponibles
- **Présence** : sur quels devices cette font est installée (icônes devices)
- **Infos fichier** : format, taille, hash, date d'ajout, source

#### Filtres

Panneau de filtres combinables : recherche texte, classification, format (TTF/OTF), scripts/langues, plage de poids (slider), Variable Fonts uniquement, tri multi-critères.

#### DevicePage

Liste des devices enregistrés avec : nom, OS, dernière connexion, état de sync (idle/syncing/error), nombre de fonts synchro. Possibilité de déclencher un re-scan depuis l'interface. Indicateur temps réel de la connexion de chaque agent.

### 7.4 Détection de l'agent

Plutôt que de contacter `localhost:7850` (problème CORS/mixed-content en HTTPS), la détection passe par le **WebSocket du serveur**. Le frontend sait quels agents sont connectés grâce aux événements `device.connected`/`device.disconnected`. Pour envoyer une commande d'installation, le frontend envoie un message `install.request` au serveur via WebSocket, qui le relaie à l'agent concerné.

---

## 8. Déploiement

### 8.1 NAS local (Docker Compose)

Configuration par défaut pour un NAS Synology ou similaire :

**Un seul service Docker** : `fontsync` (FastAPI + static Vue 3 + SQLite embarqué). Plus de service `db`, plus de healthcheck Postgres, plus de volume `pg_data`.

Variables d'environnement :
- `DATABASE_URL` : chemin SQLite, défaut `sqlite+aiosqlite:////data/fontsync.db`
- `STORAGE_BACKEND` : `filesystem` (défaut)
- `FONT_STORAGE_PATH` : chemin du volume monté (défaut `/data/fonts`)
- `GOOGLE_FONTS_API_KEY` : optionnel

Volumes : un pour les fonts, un pour le fichier SQLite (`/data`). Avec `journal_mode=WAL`, prévoir que les fichiers `-wal`/`-shm` vivent à côté du `.db` dans ce même volume.

Accès : port 8080 en local, reverse proxy (Traefik / Nginx Proxy Manager) pour l'accès distant en HTTPS. Le reverse proxy doit laisser passer le **WebSocket frontend** et le **flux SSE** de l'agent (pas de buffering sur l'endpoint SSE).

### 8.2 Serveur cloud européen

Pour un déploiement cloud, les mêmes images Docker sont utilisées avec quelques ajustements :

| Provider | Service recommandé | Stockage fonts | Notes |
|----------|-------------------|----------------|-------|
| **Scaleway** (FR) | Serverless Containers ou VPS (Stardust/DEV1) | Scaleway Object Storage (S3-compatible) | Français, RGPD, bon prix |
| **Hetzner** (DE) | VPS (CX22+) + Docker Compose | Volume attaché ou MinIO | Allemand, excellent rapport qualité/prix |
| **OVHcloud** (FR) | VPS ou Managed Kubernetes | OVH Object Storage (S3-compatible) | Français, datacenters FR |

Variables d'environnement pour le mode cloud :
- `STORAGE_BACKEND` : `s3`
- `S3_ENDPOINT` : URL du service S3-compatible
- `S3_BUCKET` : nom du bucket
- `S3_ACCESS_KEY` / `S3_SECRET_KEY` : credentials
- `S3_REGION` : région

Le choix NAS vs. cloud n'impacte pas l'agent ni le frontend — seule la config serveur change.

---

## 9. Structure du projet

```
fontsync/
├── docker-compose.yml
├── docker-compose.cloud.yml          # Override pour déploiement cloud
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/
│   └── versions/
│
├── backend/
│   ├── main.py                        # FastAPI app, static files, WebSocket
│   ├── config.py                      # Pydantic BaseSettings
│   ├── database.py                    # SQLAlchemy async
│   ├── models/                        # SQLAlchemy models
│   ├── schemas/                       # Pydantic schemas
│   ├── routers/                       # Endpoints (fonts, devices, sync, stats, ws)
│   ├── services/
│   │   ├── font_analyzer.py           # Parsing fonttools
│   │   ├── font_importer.py           # Pipeline d'import
│   │   ├── storage.py                 # Abstraction filesystem / S3
│   │   ├── sync_manager.py            # Logique de sync
│   │   ├── ws_manager.py              # Gestionnaire WebSocket (connexions, broadcast)
│   │   ├── family_grouper.py          # (Phase 4)
│   │   ├── duplicate_detector.py      # (Phase 5)
│   │   └── google_fonts.py            # (Phase 5)
│   └── utils/
│
├── agent/
│   ├── main.py                        # Point d'entrée
│   ├── config.py                      # Lecture config.yaml
│   ├── scanner.py                     # File watcher (watchdog) + scan périodique
│   ├── discovery.py                   # APIs système (Core Text, fontconfig, DirectWrite)
│   ├── sync_client.py                 # Communication WebSocket avec le serveur
│   ├── font_installer.py             # Installation par OS (per-user)
│   ├── local_server.py                # Endpoint localhost:7850 (optionnel)
│   ├── tray.py                        # Tray icon (pystray)
│   └── notifier.py                    # Notifications système
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.ts
│   │   ├── router/
│   │   ├── stores/                    # Pinia (fonts, devices, filters, ws)
│   │   ├── composables/
│   │   │   ├── useFontPreview.ts      # @font-face dynamique + lazy loading
│   │   │   ├── useWebSocket.ts        # Connexion WS + reconnexion auto
│   │   │   └── useInfiniteScroll.ts
│   │   ├── components/
│   │   │   ├── fonts/                 # FontCard, FontGrid, FontPreview, FontWaterfall, etc.
│   │   │   ├── devices/               # DeviceList, DeviceStatus
│   │   │   ├── filters/               # FilterPanel, SearchBar
│   │   │   ├── layout/                # AppSidebar, AppHeader, AppLayout
│   │   │   └── ...                    # Dossiers ajoutés par phase
│   │   └── pages/
│   └── dist/
│
└── scripts/
    ├── setup_dev.sh
    └── build_agent.sh
```

---

## 10. Roadmap détaillée

### Phase 1 — Backend serveur

> Un backend qui accepte des fonts, les parse et les sert via API.

- [ ] Docker Compose (FastAPI + PostgreSQL)
- [ ] Configuration (BaseSettings, storage backend, DB)
- [ ] Modèles SQLAlchemy : `fonts`, `devices`, `device_fonts`, `sync_queue`
- [ ] Migrations Alembic
- [ ] Service `storage` : abstraction filesystem + S3 (store, retrieve, delete, exists)
- [ ] Service `font_analyzer` : parsing fonttools complet (métadonnées, classification, scripts/langues)
- [ ] Service `font_importer` : pipeline (validation → hash → doublon check → store → parse → classify → insert)
- [ ] API fonts : upload, liste avec filtres/pagination, détail, fichier, delete, restore
- [ ] API devices : register, list, update, delete
- [ ] API sync : delta, push, pull, queue
- [ ] API stats
- [ ] WebSocket manager : connexions clients et agents, broadcast d'événements
- [ ] Gestion d'erreurs (fonts malformées, doublons, formats inconnus)

### Phase 2 — Agent Python

> L'agent détecte, push et installe les fonts automatiquement.

- [ ] Structure agent (config YAML, point d'entrée)
- [ ] Découverte initiale via APIs système (macOS prioritaire)
- [ ] File watcher (watchdog) sur les dossiers de fonts
- [ ] Scan périodique en backup
- [ ] Hashing SHA-256
- [ ] UX première sync (progression, compteur, résumé)
- [ ] Connexion WebSocket persistante avec le serveur (+ reconnexion auto)
- [ ] Push auto : détection → hash → push vers serveur
- [ ] Pull : téléchargement + installation per-user
- [ ] Gestion auto_pull (on/off)
- [ ] Tray icon (pystray) avec menu contextuel
- [ ] Notifications système
- [ ] Endpoint local `localhost:7850/status` (optionnel)
- [ ] Packaging PyInstaller + signature + notarisation macOS

### Phase 3 — Interface web

> L'interface pour naviguer, chercher et gérer les fonts.

- [ ] Setup Vue 3 + Vite + TypeScript + shadcn-vue + Tailwind
- [ ] Layout (sidebar, header, routing)
- [ ] Composable `useWebSocket` : connexion WS, reconnexion auto, mise à jour réactive des stores
- [ ] Composable `useFontPreview` : chargement @font-face dynamique + lazy loading
- [ ] Page Dashboard (stats, fonts récentes, devices connectés)
- [ ] Page Fonts : grille FontCards, lazy loading, mise à jour temps réel
- [ ] Panneau de filtres : recherche, classification, format, scripts, poids, tri
- [ ] Upload basique (formulaire simple)
- [ ] Page détail font : preview interactive, waterfall, métadonnées, langues, glyphes, devices
- [ ] Page Devices : liste, état temps réel, config, déclenchement re-scan
- [ ] Page Settings
- [ ] Build production servi par FastAPI en static files

### Phase 4 — Familles & Organisation

> Auto-groupement, catégories, collections, actions en lot.

- [ ] Tables familles, catégories, collections + migrations
- [ ] Service `family_grouper` : auto-regroupement par family_name
- [ ] Re-parse des fonts existantes pour groupement
- [ ] API familles (CRUD, merge, membres)
- [ ] API catégories (CRUD, hiérarchie)
- [ ] API collections (CRUD, membres)
- [ ] API batch (suppression, catégorisation en lot)
- [ ] Frontend : page familles, détail famille
- [ ] Frontend : sidebar catégories + drag & drop
- [ ] Frontend : collections, gestion, vue par collection
- [ ] Frontend : sélection multiple + actions en lot

### Phase 5 — Google Fonts & Doublons

> Enrichissement et nettoyage.

- [ ] Proxy API Google Fonts avec cache 24h
- [ ] Page "Explorer Google Fonts" (recherche, filtres, preview)
- [ ] Import en un clic
- [ ] Service détection de doublons visuels
- [ ] Tables doublons + migrations
- [ ] Page résolution doublons
- [ ] Mode comparaison (2-3 fonts côte à côte)

### Phase 6 — Polish & Features avancées

> Finitions.

- [ ] Conversion TTF/OTF → WOFF2 (fonttools) pour export web
- [ ] Variable Fonts : preview interactive (sliders axes)
- [ ] Export webfont kit (CSS + fichiers)
- [ ] Grille de glyphes complète
- [ ] Thème sombre / clair
- [ ] Agent : support Windows et Linux
- [ ] Recherche avancée (pg_trgm ou tsvector)

### Phase 7 — Multi-utilisateurs & Partage

> Usage en équipe.

- [ ] Authentification JWT
- [ ] Rôles (admin, éditeur, viewer)
- [ ] Espace personnel vs. bibliothèque d'équipe
- [ ] Gestion licences (tags, quotas, alertes)
- [ ] Sync sélective par device
- [ ] Invitation d'utilisateurs
- [ ] Partage public via lien URL (preview + téléchargement sans auth)
- [ ] Logs d'activité

---

## 11. Contraintes et points d'attention

### Contraintes techniques

| Contrainte | Impact | Mitigation |
|------------|--------|------------|
| **CORS / mixed-content (agent ↔ frontend)** | Frontend HTTPS ne peut pas contacter agent HTTP local | Relayer les commandes via le WebSocket du serveur (solution recommandée) |
| **Fonts malformées** | fonttools peut crasher | Try/catch systématique, stocker avec métadonnées partielles |
| **Mémoire navigateur** | 500+ fonts @font-face saturent la RAM | Lazy loading + déchargement hors viewport |
| **Scan initial lent** | SHA-256 de 500+ fichiers ~30s | UX explicite avec progression, puis watcher temps réel |
| **TrueType Collections (.ttc)** | Un fichier = plusieurs fonts | Extraire chaque font individuellement (fonttools) |
| **Apps design ignorent le font cache** | Font installée mais invisible dans Photoshop/Figma | Notification "Redémarrez [app]" |
| **WebSocket derrière reverse proxy** | Nginx/Traefik doivent supporter WS | Config reverse proxy spécifique (upgrade headers) |
| **WOFF/WOFF2** | Formats web, pas installables système | Accepter au stockage, prévisualiser, ne pas proposer à l'installation |

### Décisions techniques

- **Pas d'auth pour le MVP** — réseau de confiance
- **SQLite** comme base (mono-utilisateur) ; Postgres réservé à un éventuel multi-utilisateurs (Phase 7)
- **Soft delete** (`deleted_at`) pour toutes les suppressions
- **UUID** pour toutes les PK (type SQLAlchemy portable)
- **Le serveur (NAS, toujours ON) est la source de vérité** ; l'agent est **stateless**
- **L'agent peut désinstaller** des fonts locales sur ordre explicite de l'utilisateur via le frontend, mais la font reste sur le serveur
- **WebSocket** pour le canal **frontend** ; **SSE** pour le push « re-sync » vers l'agent (pas de WebSocket côté agent)
- **launchd** pilote l'agent : `WatchPaths` (push réactif) + `listen`/SSE (pull réactif) + `StartInterval` (filet). Plus de file watcher `watchdog`.
- **Per-user font installation** — jamais de droits admin nécessaires
- **Abstraction storage** dès le départ (filesystem / S3)

### Conventions

- **Backend** : Python 3.12+, type hints, async/await, ruff
- **Frontend** : TypeScript strict, Composition API `<script setup>`, prettier
- **API** : REST, kebab-case URLs, camelCase JSON
- **DB** : snake_case, UUID PK
- **Git** : Conventional Commits

---

*Document v3.0 — 8 mars 2026*
*À utiliser comme contexte initial pour Claude Code.*
*Le code d'implémentation n'est pas dans ce document — Claude Code implémente selon les meilleures pratiques.*
