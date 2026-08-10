# FontSync — Architecture & technical specifications

> Self-hosted font manager with real-time multi-machine synchronization.
> **Technical source of truth**: architecture, data model, API, agent.
> Delivered architecture: **SQLite** database, **stateless** agent triggered by launchd,
> reactive server→agent push via **SSE** (the frontend keeps a **WebSocket**). The
> long-term vision (multi-user, cloud, cross-platform) lives in
> [`ROADMAP.md`](ROADMAP.md).

---

## 1. Project vision

FontSync is a self-hosted font manager that centralizes all of a user's fonts on a Docker server (local NAS or cloud server), makes them accessible through a real-time web interface, and automatically synchronizes them with connected machines via a Python agent.

### The central principle

The FontSync server is the **central hub** for all fonts. When a new font is installed on any machine (Machine A), the agent detects it in real time, pushes it to the server, and the server instantly notifies all other connected agents (Machine B, C...) which can then fetch the font automatically. The web frontend reflects these changes in real time without a page reload.

```
Machine A                    FontSync Server                 Machine B
(MacBook)                    (Docker NAS)                    (Mac Mini)
                             
  Installs                                                   
  "Inter.ttf"                                                
      │                                                      
      ▼                                                      
  Agent detects   ──push──►  Receives + stores  ─SSE signal► Agent receives
  (launchd sync)             Parses metadata                 the signal
                              Signal: SSE→agent, WS→UI        
                                     │                        ▼
                              ┌──────┴──────┐          Downloads +
                              │  Frontend   │          installs "Inter.ttf"
                              │  updated    │          (auto or manual
                              │  in real    │           depending on config)
                              │  time       │
                              └─────────────┘
```

### Main objectives

- **Centralize**: a single place for all your fonts (system, client projects, Google Fonts)
- **Synchronize in real time**: automatic detection of new fonts, instant propagation
- **Browse**: rich web interface to preview, search and download
- **Self-host**: Docker on a local NAS or a European cloud server

### Guiding principles

- The **server is the source of truth** for the library and the metadata
- **Nothing is erased without an explicit yes.** A deletion is an *intention* the
  server records and keeps (trash + tombstone, cf. §4.4); an agent only uninstalls
  if that device opted into propagation, and a mass disappearance is held back
  until confirmed
- The user always has **explicit control** over what is installed on their machine
- Communication is **real time**: WebSocket server↔frontend, SSE server→agent (« re-sync » signal)
- The code in this document is **purely illustrative** — Claude Code implements according to best practices

---

## 2. Scope — MVP vs. Future evolutions

### MVP (Phases 1-3)

The MVP targets **personal use** across the machines of a single user. This is the core of the product: the agent detects fonts, the server centralizes, the machines synchronize.

**Included in the MVP:**
- Docker server (FastAPI + SQLite)
- Python agent with automatic font detection (stateless `sync` command triggered by launchd)
- Bidirectional synchronization (push new fonts to the server, pull from the server)
- Automatic metadata parsing via fonttools (family, style, weight, classification, languages, glyphs)
- Storage on filesystem or S3-compatible object storage
- Web interface with real-time updates (WebSocket)
- Font grid with lazy loading of previews via @font-face
- Font detail page (waterfall preview, metadata, languages)
- Full-text search + filters (classification, format, scripts, weight)
- Basic upload from the interface (simple form, no elaborate drag & drop)
- Font download from the interface
- First-sync UX (initial scan with progress)
- Devices page (connected machines, sync state)
- Signed + notarized macOS agent packaging

**Explicitly excluded from the MVP:**
- Auto-grouping into families (Phase 4)
- Categories, collections, tags (Phase 4)
- Google Fonts (Phase 5)
- Visual duplicate detection (Phase 5)
- Font comparison mode (Phase 5)
- Interactive Variable Fonts (Phase 6)
- TTF/OTF → WOFF2 conversion (Phase 6)
- Authentication / multi-user / roles (Phase 7)
- Public sharing via URL link (Phase 7)

---

## 3. Overall architecture

### Technical stack

| Component | Technology |
|-----------|-------------|
| Backend API | Python 3.12+, FastAPI, Uvicorn |
| Database | **SQLite** (`aiosqlite`, `journal_mode=WAL`, `foreign_keys=ON`) |
| ORM | SQLAlchemy (async) + Alembic (migrations) |
| Font parsing | fonttools |
| Real time | **Frontend WebSocket** (native FastAPI) + **SSE** for the « re-sync » push to the agent |
| Font storage | Local filesystem OR S3-compatible (abstraction) |
| Frontend | Vue 3 (Composition API, TypeScript), shadcn-vue, Tailwind CSS, Vite |
| State management | Pinia |
| Client agent | Python 3.12+, **stateless `sync` command** triggered by **launchd**, `httpx` (HTTP + SSE), pyobjc (Core Text) |
| Deployment | Docker Compose (a single container) |

> **Why SQLite?** Single-user usage, a single server process on the NAS, a small and
> disposable database in dev. Postgres only becomes relevant again with a possible multi-user mode (long term).

### Storage abstraction

Font storage is abstracted behind a common interface to support two backends:

**Local filesystem** (default, NAS): fonts are stored in a mounted Docker volume, organized by SHA-256 hash (`/data/fonts/{hash[0:2]}/{hash}.{ext}`).

**S3-compatible object storage** (cloud): for a deployment on a remote server. Compatible with Scaleway Object Storage, OVH Object Storage, MinIO, AWS S3, etc.

The abstraction exposes: `store(hash, file_data) → path`, `retrieve(hash) → file_data`, `delete(hash)`, `exists(hash) → bool`. The backend chooses the implementation according to the configuration (`STORAGE_BACKEND=filesystem` or `STORAGE_BACKEND=s3`).

### Real-time communication

Two distinct channels, depending on the interlocutor:

#### Frontend ↔ Server — WebSocket

The frontend maintains a permanent WebSocket connection (`WS /ws/client`) and updates the interface in real time without reloading.

**Server → Frontend:**
- `font.added`: new font added (by an agent or via upload) → refresh the grid
- `font.deleted`: font deleted → remove from the grid
- `font.updated`: metadata modified (edit, restore) → update the card
- `device.connected` / `device.disconnected`: an agent appears / disappears
- `sync.progress`: progress of an ongoing sync
- `sync.completed`: sync finished (stats)

**Frontend → Server:**
- `install.request`: request to install a font on a specific device (relayed to the agent)

#### Server → Agent — SSE (« re-sync » signal)

No more WebSocket on the agent side. The server exposes an **SSE** endpoint (`GET /api/agent/{device_id}/events`) that the agent's `listen` process consumes. When a font becomes available for that device, the server emits a **`sync`** event: a **simple signal with no exploited payload** (no `font_id` to interpret → no key bug). On receipt, `listen` simply **triggers the `sync` command** (with debounce), which recomputes the delta from the real disk state.

The agent does not "push" real-time events to the server: everything goes through the HTTP calls of the `sync` command (register/update device, `POST /api/sync/delta`, push, pull). The device's `last_seen_at` is updated on every HTTP call from the agent.

---

## 4. Data model

### 4.1 MVP tables

> The types below are **portable** (mapped to the corresponding SQLAlchemy
> types — `Uuid`, `DateTime(timezone=True)`, `JSON`, `String`, `Boolean`…):
> on SQLite, `Uuid` is stored as `CHAR(32)` and `JSON` as `TEXT`. No
> dialect-specific type (no Postgres `UUID`/`JSONB`/`TIMESTAMPTZ`).

#### `fonts`

Each record = a unique physical font file, identified by its SHA-256 hash.

| Column | Type | Description |
|---------|------|-------------|
| `id` | UUID (PK) | Unique identifier |
| `file_hash` | VARCHAR(64), UNIQUE | SHA-256 of the file — deduplication key |
| `original_filename` | VARCHAR(500) | Original filename |
| `file_size` | INTEGER | Size in bytes |
| `file_format` | VARCHAR(10) | `ttf`, `otf`, `woff`, `woff2`, `ttc` |
| `storage_path` | VARCHAR(500) | Relative path in storage |
| `family_name` | VARCHAR(500) | nameID 16 or fallback nameID 1 |
| `subfamily_name` | VARCHAR(200) | nameID 17 or fallback nameID 2 (Regular, Bold...) |
| `full_name` | VARCHAR(500) | nameID 4 |
| `postscript_name` | VARCHAR(500) | nameID 6 |
| `version` | VARCHAR(100) | nameID 5 |
| `designer` | VARCHAR(500) | nameID 9 |
| `manufacturer` | VARCHAR(500) | nameID 8 (foundry) |
| `license` | TEXT | nameID 13 |
| `license_url` | VARCHAR(1000) | nameID 14 |
| `description` | TEXT | nameID 10 |
| `weight_class` | INTEGER | usWeightClass (100-900), OS/2 table |
| `width_class` | INTEGER | usWidthClass (1-9), OS/2 table |
| `is_italic` | BOOLEAN | fsSelection flag |
| `is_oblique` | BOOLEAN | fsSelection flag |
| `panose` | VARCHAR(30) | Panose classification |
| `classification` | VARCHAR(50) | Auto-detected: `serif`, `sans-serif`, `monospace`, `display`, `handwriting`, `symbol` |
| `unicode_ranges` | JSON | Supported Unicode ranges |
| `supported_scripts` | JSON | Ex: `["latin", "cyrillic", "arabic"]` |
| `glyph_count` | INTEGER | Number of glyphs |
| `is_variable` | BOOLEAN | Is it a Variable Font? |
| `variable_axes` | JSON | Variation axes if variable (tag, min, max, default) |
| `source` | VARCHAR(50) | `upload`, `local_scan`, `google_fonts` |
| `source_device_id` | UUID, nullable | Origin device if local scan |
| `google_fonts_id` | VARCHAR(200) | Google Fonts identifier if applicable |
| `created_at` | DateTime (tz) | |
| `updated_at` | DateTime (tz) | |
| `deleted_at` | DateTime (tz), nullable | Soft delete |
| `deleted_reason` | VARCHAR(30), nullable | `manual`, `quarantine`, `quarantine_pending` — cf. §4.4 |
| `purged_at` | DateTime (tz), nullable | File removed from storage; the row (and its fingerprint) is kept |

Indexes: `family_name`, `classification`, `file_hash`, `source`, `deleted_at`.

#### `devices`

Machines registered with the server.

| Column | Type | Description |
|---------|------|-------------|
| `id` | UUID (PK) | |
| `name` | VARCHAR(200) | Ex: "Léo's MacBook Pro" |
| `hostname` | VARCHAR(200) | |
| `os` | VARCHAR(50) | `macos`, `linux`, `windows` |
| `os_version` | VARCHAR(100) | |
| `agent_version` | VARCHAR(20) | |
| `last_seen_at` | DateTime (tz) | Last heartbeat |
| `last_sync_at` | DateTime (tz) | Last full sync |
| `sync_status` | VARCHAR(20) | `idle`, `syncing`, `error` |
| `font_directories` | JSON | Watched directories |
| `auto_pull` | BOOLEAN | Auto-install new fonts from the server (default `false`) |
| `auto_push` | BOOLEAN | Auto-push local fonts to the server (default `true`) |
| `propagate_deletions` | BOOLEAN | Take part in deletion propagation, both ways (default `false`) — cf. §4.4 |
| `created_at` | DateTime (tz) | |

#### `device_fonts`

Fonts known to be present on a device.

| Column | Type | Description |
|---------|------|-------------|
| `device_id` | UUID (FK → devices) | |
| `font_id` | UUID (FK → fonts) | |
| `local_path` | VARCHAR(1000) | Path on the device |
| `activated` | BOOLEAN | Font active on the device (default `true`) |
| `installed_at` | DateTime (tz) | |
| PK | (device_id, font_id) | |

> **Note**: the former `sync_queue` table was removed during the overhaul —
> the agent is **stateless** (each `sync` recomputes the delta from the real disk
> state), so there is no longer a queue on the server side.

### 4.2 Families (delivered)

Grouping into families is implemented. Two real tables (cf.
[`backend/models/font_family.py`](backend/models/font_family.py)):

- `font_families` (id, name, slug, designer, manufacturer, classification, description, style_count, is_auto_grouped)
- `font_family_members` (font_id PK → fonts, family_id → font_families, sort_order)

> The **organization** tables (categories, collections, tags) and **duplicate**
> tables mentioned in the [`ROADMAP.md`](ROADMAP.md) are **not** created to date.

#### Semantics of family grouping (frozen)

> Since the frontend pivot (Phase C), the family view is the **main view**
> of the library (no more flat list). The family model thus
> becomes structural; these rules are settled and implemented in
> `backend/services/family_grouper.py`.

1. **Grouping key = typographic family name.** `family_name` =
   nameID 16 (Typographic Family) with fallback to nameID 1 (Family). nameID 16
   groups all weights/styles of the same family (old fonts that
   encode the weight in nameID 1 — « Helvetica Bold » — are thus avoided).

2. **Key normalization.** Grouping is done on the **normalized slug**
   of the name (case-insensitive, insensitive to superfluous spaces and accents), not on
   the exact name: « Inter », « inter » and « Inter  » fall into the same
   family. One slug = one family identity. The display name keeps the
   original casing of the first member encountered. Entirely non-ASCII names
   (CJK…) receive a **deterministic** fallback slug (hash of the normalized name)
   so they group together instead of scattering.

3. **No font is invisible.** A font without `family_name` is not
   a « hidden orphan »: it is grouped under a **fallback** name —
   `family_name` → `full_name` (nameID 4) → `postscript_name` (nameID 6) → filename
   without extension. Since `original_filename` is non-null, there is always
   a name. A font with no family metadata therefore appears as a single-member
   family.

4. **Flat families, no superfamily.** « Roboto », « Roboto Condensed » and
   « Roboto Mono » are distinct families (nameID 16 separates them). No parent
   level is introduced in the MVP.

5. **Invariant: 1 font = 1 family** (primary key `font_id` on
   `font_family_members`). `.ttc` files only import their first sub-font
   (cf. Phase A3), so there is no multi-sub-font case to arbitrate.

6. **100% automatic grouping for the MVP.** `group_font` runs on each
   import/sync; `regroup_all` (endpoint `POST /api/font-families/regroup`) is a
   maintenance rebuild, **destructive on auto-grouped families** (and
   safe since there is no manual editing to preserve). **Manual family
   editing** (merge, member move, creation/rename) is
   **deferred beyond the MVP**: the endpoints exist on the backend side but are not
   exposed in the UI, and as long as they are not, `group_font` prevails (no
   notion of « pinned » placement to manage).

7. **Deterministic family metadata.** A family's `designer` / `manufacturer` /
   `classification` are derived from its most « Regular » member (weight
   closest to 400, upright before italic), independently of
   the import order, and no longer from the first font encountered.

### 4.3 File storage

Organization by the first 2 characters of the SHA-256 hash:

```
/data/fonts/
├── ab/
│   ├── abcdef1234567890...ttf
│   └── ab12fe9876543210...otf
├── cd/
│   └── cd5678abcdef1234...ttf
└── ...
```

In S3 mode, the same structure is used as the object key (`fonts/ab/abcdef...ttf`).

---

### 4.4 Deletion: tombstones, trash, quarantine

A deletion is an **intention**, not an observation. That distinction is the whole
design; without it, no deletion was durable. The original failure chain, verified
end to end: a font deleted on the server was excluded from the delta, so the
machine that still held the file saw it as *unknown to the server*, pushed it
back, and the import pipeline revived it. Three links, any one of which was
enough to undo the gesture.

**The tombstone.** `deleted_reason` records *why* a font fell. It is what keeps
`deleted_at` from being ambiguous between "deleted" and "merely absent":

| Reason | Set by | Propagates to devices? |
|---|---|---|
| `manual` | `DELETE /api/fonts/{id}` (web UI) | yes |
| `quarantine` | a device that stopped declaring the font | yes |
| `quarantine_pending` | same, but **beyond the safety threshold** | **no**, until confirmed |

Consequences, all deliberate:

- `compute_delta` reads deleted fonts too. A deleted hash is neither
  `unknown_to_server` (which would make the holder push it every single sync, in
  a loop) nor `missing_on_device`. The delta says *known, deleted*.
- `import_font(revive_deleted=…)` gates the resurrection. `True` for a web
  upload — re-uploading is a deliberate restore. `False` for an agent push,
  which is answered with `refused_deleted: true`. That is not an error and the
  agent does not count it as one.

**The trash** (`GET /api/fonts/trash`) makes the gesture reversible without
making it illusory. Emptying it (`POST /api/fonts/trash/empty`) removes the
*file* from storage and keeps the *row*: the fingerprint has to outlive the
file, otherwise the font returns on the next push from a machine that still has
it — and a day-30 purge would make it reappear on day 31, forever. A purged font
can no longer be restored; re-importing the file is the way back (it also
rewrites the file to storage). Automatic purge is opt-in and off by default
(`TRASH_RETENTION_DAYS=0`).

**Quarantine** ([`backend/services/deletion_propagation.py`](backend/services/deletion_propagation.py))
turns a device's disappearances into deletions. It lives in the sync **router**,
not in `compute_delta`, because it writes — the delta stays a pure read. Three
guardrails, in order:

1. **A device declaring nothing has not emptied its library.** An unmounted
   folder or a failed scan is far likelier. Nothing is concluded.
2. **Only fonts associated with that device.** A font never transferred there
   cannot have disappeared from it.
3. **Thresholds.** `DELETION_PROPAGATION_MAX_FONTS` (25) and
   `_MAX_RATIO` (5 %) apply together — the stricter one decides — lifted by
   `_MIN_FONTS` (3) so that small deletions always go through. Beyond them the
   fonts still leave the library (recoverable in one click) but **nothing is
   propagated** until the user confirms via `POST /api/fonts/trash/confirm`.
   The case this exists for: 625 files vanished at once from `~/Library/Fonts`
   during a manual de-duplication; without a threshold another Mac would have
   lost 225 of them automatically.

Handled disappearances drop their `device_fonts` row — the registry has to match
the disk. Keeping it would re-detect the same disappearance every sync and, worse,
restoring the font from the trash would re-quarantine it on the next one.

Two agent-side properties are load-bearing here (cf. §6.6).

## 5. Backend API (FastAPI)

> **Auth:** all of `/api/*`, the SSE stream and the WebSocket require the shared
> instance token (`FONTSYNC_TOKEN`) in the `Authorization: Bearer` header — except the
> browser WS which accepts it in the query `?token=` (URL-encoded). Only `GET /health`
> is public. Actual prefixes: `/api/fonts`, `/api/devices`, `/api/sync`,
> `/api/font-families`, `/api/stats`, `/api/agent`.

### 5.1 MVP endpoints

#### Fonts

| Method | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/fonts` | List (filters, pagination, sort) |
| `GET` | `/api/fonts/{id}` | Full detail |
| `GET` | `/api/fonts/{id}/file` | Download the file |
| `GET` | `/api/fonts/{id}/preview` | File for @font-face |
| `POST` | `/api/fonts/upload` | Basic upload of file(s) |
| `PATCH` | `/api/fonts/{id}` | Modify the metadata |
| `DELETE` | `/api/fonts/{id}` | Soft delete (tombstone, reason `manual`) |
| `POST` | `/api/fonts/{id}/restore` | Restore — `409` if the file was purged |
| `GET` | `/api/fonts/trash` | Deleted fonts + count awaiting review |
| `POST` | `/api/fonts/{id}/purge` | Remove the file from storage, keep the row |
| `POST` | `/api/fonts/trash/empty` | Same, for the whole trash |
| `POST` | `/api/fonts/trash/confirm` | Confirm the quarantines held back by the threshold |
| `GET` | `/api/fonts/{id}/devices` | On which devices the font is installed |
| `POST` | `/api/fonts/{id}/install/{device_id}` | Request installation (SSE signal → agent) |

> The `/trash*` routes are declared **before** `/{font_id}` — FastAPI resolves in
> declaration order, and `trash` would otherwise be parsed as a font UUID (`422`).

> The `uninstall` / `activate` / `deactivate` routes (`POST /api/fonts/{id}/{action}/{device_id}`)
> exist as **stubs** (`501` response) — uninstall by hash and activation/deactivation
> are deferred beyond the MVP.

**Filters on `GET /api/fonts`:**

| Parameter | Description |
|-----------|-------------|
| `search` | Full-text search (name, family, designer) |
| `classification` | serif, sans-serif, monospace, display, handwriting, symbol |
| `format` | ttf, otf (multiple filters separated by comma) |
| `scripts` | latin, cyrillic, arabic, etc. |
| `is_variable` | true/false |
| `weight_min` / `weight_max` | Weight range (100-900) |
| `sort` | name, created_at, family_name, glyph_count, file_size |
| `order` | asc, desc |
| `page` / `per_page` | Pagination (default 50) |

#### Devices & Sync

| Method | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/devices/register` | Register a device — keyed on `device_id`, hostname only as a fallback |
| `GET` | `/api/devices` | List the devices |
| `PATCH` | `/api/devices/{id}` | Update (name, `auto_pull`, `auto_push`, `propagate_deletions`…) |
| `POST` | `/api/devices/{id}/merge` | Absorb duplicate devices, keeping their font registry |
| `DELETE` | `/api/devices/{id}` | Delete (its `device_fonts` rows go with it; the library does not) |

> **Identity is the `device_id`, not the hostname.** macOS changes its hostname
> with the network (`.local` under Bonjour, `.home` under DHCP), and an upsert
> keyed on hostname created one row per variant — three for a single Mac mini in
> production. The agent has persisted its `device_id` since its first
> registration; it now sends it, and the server prefers it. A `device_id` the
> server does not know falls back to the hostname, so a wiped database does not
> lock the agent out. `/merge` repairs pre-existing duplicates: it reassigns
> `device_fonts` before deleting, because a survivor with a partial registry
> makes local-deletion detection blind to those fonts, permanently — a font
> already in sync never goes through a transfer that would recreate the row.
| `POST` | `/api/devices/{id}/rescan` | Force a re-scan (SSE signal → agent) |
| `POST` | `/api/sync/delta` | Delta sync: local hashes → differences, plus `to_uninstall` |
| `POST` | `/api/sync/push` | Push font(s) to the server |
| `GET` | `/api/sync/pull/{font_id}` | Pull a font from the server |

> No « queue » endpoint: since the agent is stateless, each `sync` recomputes
> its delta via `POST /api/sync/delta` (the former `sync_queue` table/route was removed).

#### Real time (WebSocket + SSE)

| Endpoint | Description |
|----------|-------------|
| `WS /ws/client` | Frontend ↔ server channel (token in query `?token=`, URL-encoded) |
| `GET /api/agent/{device_id}/events` | **SSE** server → agent: « re-sync » signal consumed by `listen` |

> A `WS /ws/agent/{device_id}` endpoint **remains in the code but is unused**:
> the agent moved to the SSE channel above. To be considered legacy.

#### Statistics

| Method | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/stats` | Global stats |

#### System (version & update)

| Method | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/system/info` | Running version, and whether self-update is set up |
| `POST` | `/api/system/update` | Ask Watchtower to pull the image and recreate the container |

> FontSync **never** mounts the Docker socket. A container cannot replace itself
> without access to the daemon, and granting that to an app guarded by a single
> shared token would hand over root-equivalent control of the NAS. The privilege
> stays with a neighbouring **Watchtower** (`--http-api-update`, no periodic
> polling, `--label-enable`), reachable only over the compose network.
>
> Consequence to accept: `POST /api/system/update` may never return — Watchtower
> recreates the container that is answering. That is the success case. The
> frontend therefore waits for `/health` to come back rather than for the
> response, then re-reads the version to say whether anything actually changed.
> Without `WATCHTOWER_URL`/`WATCHTOWER_TOKEN`, the endpoint answers `503` and the
> button is absent from the interface.
>
> The version comes from the `FONTSYNC_VERSION` build arg (CI: semver tag or
> branch name, plus the short SHA). A build without it reports `dev`, which is
> the truth.

#### Families (delivered)

Since the family view is the main view of the library, families
are **implemented** (`/api/font-families` prefix, not `/api/families`):

| Method | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/font-families` | List (with members, filters) |
| `GET` | `/api/font-families/{id}` | Detail of a family |
| `POST` | `/api/font-families` | Create |
| `PATCH` | `/api/font-families/{id}` | Rename / edit |
| `DELETE` | `/api/font-families/{id}` | Delete |
| `POST` | `/api/font-families/merge` | Merge |
| `POST` | `/api/font-families/regroup` | Maintenance rebuild (auto-grouping) |
| `POST` / `DELETE` | `/api/font-families/{id}/fonts[/{font_id}]` | Add / remove a member |

> Auto-grouping runs on each import/sync (`family_grouper`). The manual editing
> routes exist but are not (yet) exposed in the UI (cf. §4.2).

### 5.2 Non-implemented endpoints (long-term vision)

Categories, collections, Google Fonts, duplicates, multi-user auth and public
sharing belong to the [`ROADMAP.md`](ROADMAP.md) — **no corresponding endpoint exists
to date**.

### 5.3 Import pipeline

Triggered by a web upload OR by an agent push:

```
1. File reception
   └─► Validation (magic bytes, extension, max size)
   
2. SHA-256 hash
   └─► Exact duplicate? → skip, return the existing font
   
3. Storage (filesystem or S3 depending on config)
   
4. fonttools parsing (wrapped in try/catch — never reject a font)
   ├─► 'name' table: family, subfamily, designer, version, license...
   ├─► 'OS/2' table: weight, width, panose, italic/oblique
   ├─► 'cmap' table: codepoints → scripts/languages
   ├─► 'fvar' table: variable axes (if applicable)
   ├─► 'post' table: isFixedPitch
   └─► 'maxp' table: glyph count
   
5. Auto-classification (heuristic: Panose + name + isFixedPitch)
   
6. Insertion into the database
   
7. WebSocket notification → font.added (all connected clients)
```

Accepted formats: **TTF, OTF** (installable by the agent). **WOFF, WOFF2**: accepted for storage and previewable in the browser, but not offered for system installation (these are web-only formats). **TTC**: each font of the TrueType Collection is extracted individually.

---

## 6. Python client agent (MVP)

> **Stateless** architecture (delivered). The agent **is not a WebSocket daemon**: it is a
> **stateless `sync` command** triggered by launchd, plus a small `listen` process that only
> relays the server's SSE signal.

### 6.1 Role

The agent is the critical component of the MVP — it is what makes FontSync more than a simple font host. It breaks down into **two executables with no mutable persistent state**:

- **`fontsync sync`** — short, idempotent command, executed then terminated:
  `discover (Core Text + directories) → hash (with cache) → register/update device → POST /sync/delta → push the unknown ones → pull the missing ones (if auto_pull) → install → exit`.
- **`fontsync listen`** — minimal long-lived process (launchd `KeepAlive`): opens the **SSE** connection to the server and, on each signal, **triggers `sync`** (debounce ~2 s). Zero state, zero hash.

The server (NAS, always on) is the **source of truth**. The agent always starts from the real disk state — no set of hashes in memory to maintain between two executions.

### 6.2 `sync` triggers

The `sync` command is **identical regardless of its source**. Three triggers (launchd):

| Trigger | launchd mechanism | Role |
|-------------|-------------------|------|
| Local change | `WatchPaths` on `~/Library/Fonts` (option `/Library/Fonts`) | Reactive push of fonts added locally |
| Remote signal | `listen` process (SSE) → launches `sync` | Reactive pull when a font becomes available |
| Safety net | `StartInterval` (~600 s) + `RunAtLoad` | Catch-up for missed events |

#### Font discovery via system APIs

| OS | Discovery API | Managed directories (per-user) |
|----|-------------------|---------------------------|
| macOS | Core Text via `pyobjc` | `~/Library/Fonts`, `/Library/Fonts` |
| Linux | `fc-list` (fontconfig) | `~/.local/share/fonts`, `/usr/local/share/fonts` |
| Windows | DirectWrite via `ctypes` | `%LOCALAPPDATA%\Microsoft\Windows\Fonts` |

The read-only system directories (`/System/Library/Fonts` on macOS, `/usr/share/fonts` on Linux, `C:\Windows\Fonts` on Windows) are **not managed** — these are OS fonts we don't want to sync. (MVP: macOS prioritized.)

#### Local hash cache

Computing the SHA-256 of hundreds of files on each `sync` would be costly. The agent maintains a `(path, size, mtime) → hash` cache in `~/.fontsync/`: only new or modified files (changed mtime/size) are re-hashed. A scan of 500 fonts becomes nearly free after the first time. **This is the only state persisted on the agent side — purely a cache, reconstructible.**

### 6.3 First synchronization

The first `sync` does the bulk of the work (empty cache → everything is hashed):

1. `discover`: enumerates fonts via Core Text + the managed directories.
2. SHA-256 hash of each file (empty cache on the first pass).
3. Register / update the device with the server (`POST /api/devices/register`).
4. Sending the delta (`POST /api/sync/delta`).
5. Push the fonts unknown to the server.
6. Pull the missing fonts if `auto_pull`.

The subsequent `sync` runs are nearly instantaneous thanks to the cache.

### 6.4 Sync protocol

**Registration:** the agent registers with name, hostname, OS, version → receives/reuses a `device_id` (persisted locally, cf. config).

**Delta sync:** the agent sends its hashes → the server responds with:
- `unknown_to_server`: fonts to push. A font **deleted** on the server never
  appears here — it is *known*, and listing it as unknown made the machine that
  still held the file push it back on every single sync (cf. §4.4)
- `missing_on_device`: fonts available to pull
- `already_synced`: up to date
- `deleted_on_server`: how many of the declared fonts have fallen (informative)
- `to_uninstall`: fonts to remove from this device — empty unless
  `propagate_deletions` is on, and never a quarantine awaiting review

The delta computation itself (`compute_delta`) is a **pure read** (no writes, no
`commit` in the middle). Interpreting *disappearances* writes, so it lives in the
router, before the delta, so that this same response already reflects it.

**Push:** for each font in `unknown_to_server`, the agent sends the file (`POST /api/sync/push`). The server import is **idempotent** on the `file_hash` (two concurrent pushes of the same hash → a single font). The server then emits the SSE `sync` signal to the other relevant devices.

**Pull:** for each font in `missing_on_device`, if `auto_pull: true`, the agent downloads (`GET /api/sync/pull/{font_id}`) and installs. The server reliably records the `device_font` association. If `auto_pull: false`, nothing is installed automatically — the user triggers the installation via the frontend (relayed to the agent).

### 6.5 Font installation per OS

The agent always installs **per-user** (no admin rights required):
- **macOS**: copy into `~/Library/Fonts/`
- **Linux**: copy into `~/.local/share/fonts/` + fontconfig cache rebuild
- **Windows**: copy into the per-user directory + HKCU registry write

After installation, the agent can display a system notification: "Inter font installed — restart your design applications to use it".

### 6.6 Deletion behavior

**Nothing is deleted on a device unless `propagate_deletions` is on for it**
(default `false`). That setting is deliberately separate from `auto_push` /
`auto_pull`: those two words promise only *to send* and *to install*, and turning
them on must not become destructive. It works both ways — this machine's local
deletions become quarantines on the server, and fonts deleted on the server are
uninstalled here. Server-side rules and thresholds: §4.4.

With the setting off, the behaviour is the historical one: the server records
the font as deleted, the device keeps its file, nothing is erased anywhere.

Uninstall is **guarded by hash** ([`agent/font_installer.py`](agent/font_installer.py)):
only a file whose content matches the requested hash is removed, so a personal
font that merely shares a filename is never touched. Identification stays
stateless — derived from the real disk, not from a mutable manifest.

Two agent-side properties make the whole thing safe, both in
`_declared_fonts` ([`agent/sync_command.py`](agent/sync_command.py)):

- **`~/.fontsync/disabled/` is declared.** `deactivate_font` moves files there
  and it belongs to no `scan.directories`. Staying silent about it would tell
  the server those fonts no longer exist — they would be quarantined and erased
  from every machine, for the crime of having been deactivated.
- **Discovery is anchored to the disk**, not to Core Text alone
  ([`agent/discovery.py`](agent/discovery.py)). macOS's font index can go stale
  (cf. [`agent/font_registry.py`](agent/font_registry.py)) and stop reporting a
  file that is plainly there. That was harmless while discovery only ever
  *added*; now that absence means deletion, it would erase the font everywhere.
  The directory scan is authoritative on "the file exists"; Core Text only adds
  what it sees beyond the scanned folders.

### 6.7 Real-time channel (SSE)

No more WebSocket on the agent side (no backoff reconnection, no « on-restoration » delta-sync either). The **`listen`** process opens an **SSE** connection (`GET /api/agent/{device_id}/events`) via `httpx.stream`. On each `sync` event received, it triggers the `fontsync sync` command (debounce ~2 s). Resilience is reduced to a **trivial reconnection loop** (sleep + retry); the launchd `StartInterval` serves as a net. Since the event is a simple signal, there is no data to interpret → no possible desynchronization.

### 6.8 Configuration

`~/.fontsync/config.yaml` file (cf. [`agent/config.py`](agent/config.py)):
- `server.url`: URL of the FontSync server
- `server.token`: **shared instance token** (= `FONTSYNC_TOKEN`), sent in `Authorization: Bearer`
- `server.device_token`: reserved for a future **per-device** auth (cloud / long term), **unused** in v1
- `server.device_id`: device identifier (received at registration, **persisted**)
- `scan.directories`: managed directories (default `~/Library/Fonts`, `/Library/Fonts`)
- `scan.ignore_patterns`: patterns to ignore (default `.*`, `System*`)
- `sync.auto_pull`: auto-install fonts from the server (default `false`)
- `sync.auto_push`: auto-push local fonts (default `true`)

> `auto_pull`/`auto_push` are only the values sent at the **first** `register`:
> after that, the server prevails (driven via the frontend). There is no longer
> an `interval_minutes` (replaced by the launchd `StartInterval`). The config `save()`
> preserves the persisted identity (`device_id`/tokens).

### 6.9 Triggering from the frontend

There is no longer a local `localhost:7850` endpoint (the CORS/mixed-content constraint disappears). To install a font on a device, the frontend sends `install.request` to the **server** (via its frontend WebSocket); the server emits the SSE `sync` signal to the relevant device, which pulls and installs on the next `sync`. No CORS workaround needed.

### 6.10 macOS packaging

Much less critical than with a `.app` daemon (we now only have a `sync` CLI + a small `listen`). Chosen packaging: **relocatable Python venv embedded** in the signed/notarized Mac app (no PyInstaller). Installation is done via two **LaunchAgents**:
- `com.fontsync.sync.plist`: `WatchPaths` + `StartInterval` ~600 s + `RunAtLoad`
- `com.fontsync.listen.plist`: `KeepAlive` + `RunAtLoad`

loaded/unloaded by `launchctl bootstrap` / `bootout`.

---

## 7. Frontend (Vue 3 + shadcn-vue)

### 7.1 MVP pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Stats, recently added fonts, connected devices |
| `/fonts` | Library | Font grid with filters and search |
| `/fonts/:id` | Font detail | Preview, waterfall, metadata, languages |
| `/devices` | Devices | Connected machines, sync state, config |
| `/trash` | Trash | Deleted fonts: restore, empty, confirm held-back quarantines |
| `/settings` | Settings | Server configuration |

Pages added by phase:

| Phase | Routes |
|-------|--------|
| Phase 4 | `/families`, `/families/:id`, `/categories`, `/collections`, `/collections/:id` |
| Phase 5 | `/google-fonts`, `/duplicates` |

### 7.2 Real time (WebSocket)

The frontend establishes a WebSocket connection on load (`WS /ws/client`) and maintains it throughout the session. All changes are reflected instantly:

- New font added (by an agent or an upload) → appears in the grid without refresh
- Font deleted → disappears from the grid
- Device connected/disconnected → update of the Devices page
- Sync in progress → progress indicator in the header

In case of WebSocket connection loss, the frontend attempts an automatic reconnection and displays a "Reconnecting..." indicator in the interface.

### 7.3 Key components

#### FontCard

Each card displays:
- A live render in the font (loaded via `FontFace API` + Intersection Observer for lazy loading)
- Name + style
- Classification + number of glyphs
- Main language/script badges
- "Download" button (if no agent) or "Install" button (if agent connected, command relayed via WebSocket)

**Lazy loading**: fonts are only loaded via @font-face when the card enters the viewport. Fonts outside the viewport are unloaded to save memory.

#### FontPreview (detail page)

- **Interactive preview**: customizable text (default: pangram), rendered in the font
- **Waterfall**: sizes 12, 16, 20, 24, 32, 48, 64, 72px
- **Metadata**: all the fonttools info
- **Languages**: script badges with coverage
- **Glyphs**: paginated grid of available characters
- **Presence**: on which devices this font is installed (device icons)
- **File info**: format, size, hash, date added, source

#### Filters

Combinable filter panel: text search, classification, format (TTF/OTF), scripts/languages, weight range (slider), Variable Fonts only, multi-criteria sort.

#### DevicePage

List of registered devices with: name, OS, last connection, sync state (idle/syncing/error), number of synced fonts. Ability to trigger a re-scan from the interface. Real-time indicator of each agent's connection.

### 7.4 Agent detection

Rather than contacting `localhost:7850` (CORS/mixed-content problem over HTTPS), detection goes through the **server's WebSocket**. The frontend knows which agents are connected thanks to the `device.connected`/`device.disconnected` events. To send an install command, the frontend sends an `install.request` message to the server via WebSocket, which relays it to the relevant agent.

---

## 8. Deployment

### 8.1 Local NAS (Docker Compose)

Default configuration for a Synology NAS or similar:

**A single Docker service**: `fontsync` (FastAPI + static Vue 3 + embedded SQLite). No more `db` service, no more Postgres healthcheck, no more `pg_data` volume.

Environment variables:
- `DATABASE_URL`: SQLite path, default `sqlite+aiosqlite:////data/fontsync.db`
- `STORAGE_BACKEND`: `filesystem` (default)
- `FONT_STORAGE_PATH`: path of the mounted volume (default `/data/fonts`)
- `GOOGLE_FONTS_API_KEY`: optional

Volumes: one for the fonts, one for the SQLite file (`/data`). With `journal_mode=WAL`, plan for the `-wal`/`-shm` files to live next to the `.db` in that same volume.

Access: port 8080 locally, reverse proxy (Traefik / Nginx Proxy Manager) for remote HTTPS access. The reverse proxy must let through the **frontend WebSocket** and the agent's **SSE stream** (no buffering on the SSE endpoint).

### 8.2 European cloud server

For a cloud deployment, the same Docker images are used with a few adjustments:

| Provider | Recommended service | Font storage | Notes |
|----------|-------------------|----------------|-------|
| **Scaleway** (FR) | Serverless Containers or VPS (Stardust/DEV1) | Scaleway Object Storage (S3-compatible) | French, GDPR, good price |
| **Hetzner** (DE) | VPS (CX22+) + Docker Compose | Attached volume or MinIO | German, excellent value for money |
| **OVHcloud** (FR) | VPS or Managed Kubernetes | OVH Object Storage (S3-compatible) | French, FR datacenters |

Environment variables for cloud mode:
- `STORAGE_BACKEND`: `s3`
- `S3_ENDPOINT`: URL of the S3-compatible service
- `S3_BUCKET`: bucket name
- `S3_ACCESS_KEY` / `S3_SECRET_KEY`: credentials
- `S3_REGION`: region

The NAS vs. cloud choice does not impact the agent or the frontend — only the server config changes.

---

## 9. Project structure

```
fontsync/
├── docker-compose.yml
├── docker-compose.cloud.yml          # Override for cloud deployment
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
│   │   ├── font_analyzer.py           # fonttools parsing
│   │   ├── font_importer.py           # Import pipeline
│   │   ├── storage.py                 # Filesystem / S3 abstraction
│   │   ├── sync_manager.py            # Sync logic
│   │   ├── ws_manager.py              # WebSocket manager (connections, broadcast)
│   │   ├── family_grouper.py          # (Phase 4)
│   │   ├── duplicate_detector.py      # (Phase 5)
│   │   └── google_fonts.py            # (Phase 5)
│   └── utils/
│
├── agent/
│   ├── __main__.py                    # CLI entry point (sync/listen/setup/teardown/status)
│   ├── config.py                      # Read/write config.yaml (url, token, device_id)
│   ├── discovery.py                   # Font discovery (Core Text macOS + directories)
│   ├── scanner.py                     # Scan + hashing of font directories
│   ├── hashing.py                     # SHA-256 hash of files
│   ├── hash_cache.py                  # Local hash cache (path, size, mtime)
│   ├── sync_command.py                # Stateless `sync` command (delta computation)
│   ├── sync_client.py                 # HTTP client (httpx) to the server
│   ├── listen_command.py             # `listen` process: SSE → re-triggers `sync`
│   ├── font_installer.py             # Install/uninstall per OS (per-user)
│   ├── launchd_setup.py               # setup/teardown of the LaunchAgents (macOS)
│   └── paths.py                       # Locations (~/.fontsync, logs)
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
│   │   │   ├── useFontPreview.ts      # dynamic @font-face + lazy loading
│   │   │   ├── useWebSocket.ts        # WS connection + auto reconnection
│   │   │   └── useInfiniteScroll.ts
│   │   ├── components/
│   │   │   ├── fonts/                 # FontCard, FontGrid, FontPreview, FontWaterfall, etc.
│   │   │   ├── devices/               # DeviceList, DeviceStatus
│   │   │   ├── filters/               # FilterPanel, SearchBar
│   │   │   ├── layout/                # AppSidebar, AppHeader, AppLayout
│   │   │   └── ...                    # Folders added by phase
│   │   └── pages/
│   └── dist/
│
└── scripts/
    ├── setup_dev.sh
    └── build_agent.sh
```

---

## 10. Constraints and points of attention

### Technical constraints

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| **CORS / mixed-content (agent ↔ frontend)** | HTTPS frontend cannot contact local HTTP agent | Relay commands via the server's WebSocket (recommended solution) |
| **Malformed fonts** | fonttools can crash | Systematic try/catch, store with partial metadata |
| **Browser memory** | 500+ @font-face fonts saturate the RAM | Lazy loading + unload outside viewport |
| **Slow initial scan** | SHA-256 of 500+ files ~30s | Explicit UX with progress, then real-time watcher |
| **TrueType Collections (.ttc)** | One file = several fonts | Extract each font individually (fonttools) |
| **Design apps ignore the font cache** | Font installed but invisible in Photoshop/Figma | "Restart [app]" notification |
| **WebSocket behind reverse proxy** | Nginx/Traefik must support WS | Specific reverse proxy config (upgrade headers) |
| **WOFF/WOFF2** | Web formats, not system-installable | Accept for storage, preview, do not offer for installation |

### Technical decisions

- **Auth = shared instance token** (`FONTSYNC_TOKEN`) verified on all of `/api/*`, the SSE and the WS; no user accounts (reserved for multi-user, long term)
- **SQLite** as the database (single-user); Postgres reserved for a possible multi-user (long term)
- **Soft delete** (`deleted_at`) for all deletions
- **UUID** for all PKs (portable SQLAlchemy type)
- **The server (NAS, always ON) is the source of truth**; the agent is **stateless**
- **The agent can uninstall** local fonts on the user's explicit order via the frontend, but the font stays on the server
- **WebSocket** for the **frontend** channel; **SSE** for the « re-sync » push to the agent (no WebSocket on the agent side)
- **launchd** drives the agent: `WatchPaths` (reactive push) + `listen`/SSE (reactive pull) + `StartInterval` (net). No more `watchdog` file watcher.
- **Per-user font installation** — never any admin rights required
- **Storage abstraction** from the start (filesystem / S3)

### Conventions

- **Backend**: Python 3.12+, type hints, async/await, ruff
- **Frontend**: TypeScript strict, Composition API `<script setup>`, prettier
- **API**: REST, kebab-case URLs, camelCase JSON
- **DB**: snake_case, UUID PK
- **Git**: Conventional Commits

---

*Technical reference of the delivered architecture (0.0.1).*
*The schema excerpts are illustrative: the source of truth for the code remains `backend/` and `agent/`.*
