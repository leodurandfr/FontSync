# FontSync — Spécifications techniques v3.0

> Font manager self-hosted avec synchronisation multi-machines en temps réel
> Document de référence pour le développement avec Claude Code — Mars 2026

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
- L'agent **ne supprime jamais** de fonts localement de manière automatique
- L'utilisateur a toujours le **contrôle explicite** sur ce qui est installé sur sa machine
- La communication est **temps réel** : WebSocket entre serveur, agents et frontend
- Le code dans ce document est **purement illustratif** — Claude Code implémente selon les meilleures pratiques

---

## 2. Scope — MVP vs. Évolutions futures

### MVP (Phases 1-3)

Le MVP cible un **usage personnel** entre les machines d'un seul utilisateur. C'est le cœur du produit : l'agent détecte les fonts, le serveur centralise, les machines se synchronisent.

**Inclus dans le MVP :**
- Serveur Docker (FastAPI + PostgreSQL)
- Agent Python avec détection automatique des fonts (file watcher + scan périodique)
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
| Base de données | PostgreSQL 16 |
| ORM | SQLAlchemy (async) + Alembic (migrations) |
| Parsing de fonts | fonttools |
| Temps réel | WebSocket (FastAPI natif) |
| Stockage fonts | Filesystem local OU S3-compatible (abstraction) |
| Frontend | Vue 3 (Composition API, TypeScript), shadcn-vue, Tailwind CSS, Vite |
| State management | Pinia |
| Agent client | Python 3.12+, watchdog (file watcher), PyInstaller |
| Déploiement | Docker Compose |

### Abstraction storage

Le stockage des fonts est abstrait derrière une interface commune pour supporter deux backends :

**Filesystem local** (défaut, NAS) : les fonts sont stockées dans un volume Docker monté, organisées par hash SHA-256 (`/data/fonts/{hash[0:2]}/{hash}.{ext}`).

**Object storage S3-compatible** (cloud) : pour un déploiement sur serveur distant. Compatible avec Scaleway Object Storage, OVH Object Storage, MinIO, AWS S3, etc.

L'abstraction expose : `store(hash, file_data) → path`, `retrieve(hash) → file_data`, `delete(hash)`, `exists(hash) → bool`. Le backend choisit l'implémentation selon la configuration (`STORAGE_BACKEND=filesystem` ou `STORAGE_BACKEND=s3`).

### Communication temps réel (WebSocket)

Un unique canal WebSocket persistant gère toutes les communications temps réel entre le serveur, le frontend et les agents :

**Serveur → Frontend :**
- `font.added` : nouvelle font ajoutée (par un agent ou par upload) → rafraîchir la grille
- `font.deleted` : font supprimée → retirer de la grille
- `font.updated` : métadonnées modifiées → mettre à jour la carte
- `device.connected` / `device.disconnected` : un agent se connecte/déconnecte
- `sync.progress` : progression d'une sync en cours
- `sync.completed` : sync terminée (stats)

**Serveur → Agent :**
- `font.available` : nouvelle font disponible sur le serveur → l'agent peut la pull
- `sync.request` : le serveur demande un re-scan (déclenché manuellement depuis le frontend)

**Agent → Serveur :**
- `font.detected` : nouvelle font détectée localement → déclenche le push
- `font.removed` : font supprimée localement → notification (pas d'action auto côté serveur)
- `heartbeat` : signal de présence

**Frontend → Serveur :**
- `install.request` : demande d'installation d'une font sur un device spécifique (relayé à l'agent)

Le frontend maintient une connexion WebSocket permanente et met à jour l'interface en temps réel sans rechargement.

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

### 6.1 Rôle

L'agent est le composant critique du MVP. C'est lui qui fait de FontSync plus qu'un simple hébergeur de fonts. Il :
- **Surveille en continu** les dossiers de fonts du système (file watcher)
- **Détecte en temps réel** les nouvelles fonts installées et les fonts supprimées
- **Pousse automatiquement** les nouvelles fonts vers le serveur
- **Reçoit les notifications** du serveur quand de nouvelles fonts sont disponibles
- **Installe** les fonts depuis le serveur (automatiquement ou sur demande)
- **Communique via WebSocket** avec le serveur pour le temps réel

### 6.2 Détection des fonts

#### Mode principal : File watcher (watchdog)

L'agent utilise la bibliothèque `watchdog` pour surveiller les dossiers de fonts en continu. Dès qu'un fichier est créé, modifié ou supprimé dans un dossier surveillé, un événement est déclenché immédiatement.

#### Mode backup : Scan périodique

Un scan complet est effectué toutes les X minutes (configurable, défaut 5 min) pour rattraper les événements éventuellement manqués par le file watcher. Ce scan compare l'état connu (hashes en mémoire) avec l'état actuel du filesystem.

#### Découverte initiale via APIs système

Au premier lancement, l'agent utilise les APIs système pour découvrir toutes les fonts :

| OS | API de découverte | Dossiers surveillés (per-user) |
|----|-------------------|--------------------------------|
| macOS | Core Text via `pyobjc` | `~/Library/Fonts`, `/Library/Fonts` |
| Linux | `fc-list` (fontconfig) | `~/.local/share/fonts`, `/usr/local/share/fonts` |
| Windows | DirectWrite via `ctypes` | `%LOCALAPPDATA%\Microsoft\Windows\Fonts` |

Les dossiers système read-only (`/System/Library/Fonts` sur macOS, `/usr/share/fonts` sur Linux, `C:\Windows\Fonts` sur Windows) ne sont **pas surveillés** — ce sont des fonts OS qu'on ne veut pas syncer.

### 6.3 Première synchronisation

L'UX du premier lancement est critique :

1. L'agent s'enregistre auprès du serveur (POST `/api/devices/register`)
2. Affichage : "Scan de vos polices en cours..."
3. Progression visible : "142/500 polices analysées"
4. Calcul SHA-256 de chaque fichier
5. Envoi du delta au serveur (POST `/api/sync/delta`)
6. Upload des fonts inconnues du serveur (push)
7. Résumé : "Scan terminé — 500 polices détectées, 342 nouvelles envoyées au serveur"

Après ce scan initial, la détection est en temps réel via le file watcher.

### 6.4 Protocole de sync

**Enregistrement :** l'agent s'enregistre avec son nom, hostname, OS, version → reçoit un `device_id`.

**Delta sync :** l'agent envoie ses hashes → le serveur répond avec :
- `unknown_to_server` : fonts à pusher
- `missing_on_device` : fonts disponibles à puller
- `already_synced` : à jour

**Push (auto)** : quand le file watcher détecte une nouvelle font, l'agent la hash, vérifie qu'elle n'est pas déjà sur le serveur, et la push. Le serveur notifie tous les autres agents via WebSocket.

**Pull (auto ou manuel selon config)** : quand le serveur notifie qu'une nouvelle font est disponible (`font.available` via WebSocket), l'agent :
- Si `auto_pull: true` → télécharge et installe silencieusement
- Si `auto_pull: false` → stocke dans la file d'attente, l'utilisateur décide via l'interface

### 6.5 Installation de fonts par OS

L'agent installe toujours en **per-user** (pas de droits admin nécessaires) :
- **macOS** : copie dans `~/Library/Fonts/`
- **Linux** : copie dans `~/.local/share/fonts/` + rebuild cache fontconfig
- **Windows** : copie dans le dossier per-user + écriture registre HKCU

Après installation, l'agent peut afficher une notification système : "Font Inter installée — redémarrez vos applications design pour l'utiliser".

### 6.6 Comportement de suppression

**L'agent ne supprime JAMAIS de fonts localement de manière automatique.**
- Font supprimée sur le serveur → les devices ne sont pas affectés, notification informative uniquement
- Font supprimée localement par l'utilisateur → l'agent notifie le serveur (événement `font.removed`), mais le serveur ne supprime pas la font de sa bibliothèque

### 6.7 Communication WebSocket

L'agent maintient une connexion WebSocket permanente (`WS /ws/agent/{device_id}`) avec le serveur. En cas de perte de connexion, reconnexion automatique avec backoff exponentiel. Quand la connexion est rétablie, un delta sync est déclenché pour rattraper les changements manqués.

### 6.8 Configuration

Fichier `~/.fontsync/config.yaml` :
- `server.url` : URL du serveur FontSync
- `server.device_token` : token d'identification (généré à l'enregistrement)
- `scan.interval_minutes` : fréquence du scan backup (défaut 5)
- `scan.directories` : override des dossiers surveillés
- `scan.ignore_patterns` : patterns à ignorer (ex: `.*`, `System*`)
- `sync.auto_push` : push auto des nouvelles fonts (défaut true)
- `sync.auto_pull` : install auto des fonts du serveur (défaut false)
- `agent.port` : port de l'endpoint local (défaut 7850)
- `agent.show_notifications` : notifications système (défaut true)

### 6.9 Endpoint local

L'agent expose `http://localhost:7850/status` pour que le frontend puisse le détecter. Retourne : version agent, device_id, device_name, sync_status, last_sync, nombre de fonts synchro, config auto_pull.

Le frontend peut aussi envoyer `POST http://localhost:7850/install` avec un font_id pour déclencher l'installation d'une font spécifique.

**⚠️ Contrainte CORS/mixed-content** : si le frontend est servi en HTTPS, les requêtes vers `http://localhost` sont bloquées. Solutions à explorer :
- Relayer les commandes via le WebSocket du serveur (le frontend envoie `install.request` au serveur, qui relaie à l'agent via son WebSocket) — **solution recommandée**, pas de contournement CORS nécessaire
- L'endpoint local devient optionnel / secondaire

### 6.10 Packaging macOS

1. Build PyInstaller → bundle `.app`
2. Signature : `codesign` avec certificat "Developer ID Application"
3. Notarisation : `notarytool` (Apple scanne et approuve)
4. Distribution : DMG téléchargeable depuis l'interface web de FontSync

Résultat : Gatekeeper laisse passer sans avertissement, pas besoin de l'App Store.

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

Deux services Docker : `fontsync` (FastAPI + static Vue 3) et `db` (PostgreSQL 16 Alpine).

Variables d'environnement :
- `DATABASE_URL` : connexion PostgreSQL
- `STORAGE_BACKEND` : `filesystem` (défaut)
- `FONT_STORAGE_PATH` : chemin du volume monté (défaut `/data/fonts`)
- `GOOGLE_FONTS_API_KEY` : optionnel

Volumes : un pour les fonts, un pour PostgreSQL.

Accès : port 8080 en local, reverse proxy (Traefik / Nginx Proxy Manager) pour l'accès distant en HTTPS.

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
- **Soft delete** (`deleted_at`) pour toutes les suppressions
- **UUID** pour toutes les PK
- **Le serveur est la source de vérité**
- **L'agent ne supprime jamais automatiquement** de fonts locales
- **WebSocket** pour tout le temps réel (pas SSE)
- **File watcher** (watchdog) comme mode principal de détection, scan périodique en backup
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
