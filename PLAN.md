# FontSync — Plan de refonte (backend + agent)

> Reprise d'un projet bâti en sprint (8–10 mars 2026), dormant ~3 mois.
> Objectif : rendre **robuste et optimisé** le backend + l'agent. Le design frontend
> est traité dans un second temps (on garde juste le frontend compilable).

**STATUT : A4 (sémantique de sync) fait. → Prochaine étape : A5 (canal temps réel : SSE agent + events clients).**

---

## Comment travailler ce plan (multi-conversations)

À chaque nouvelle conversation, l'utilisateur écrit « **Implémente la prochaine étape du plan** ». Alors :

1. Lire ce fichier en entier, repérer la **première tâche non cochée**.
2. L'implémenter complètement, avec tests si applicable. **Rester dans le périmètre de l'étape** — ne pas anticiper les suivantes (règle CLAUDE.md : pas de hors-scope).
3. Cocher la/les tâche(s) faites, mettre à jour la ligne **STATUT** ci-dessus.
4. `ruff format` + `ruff check` (backend/agent) ou `prettier` (front), lancer les tests, puis **commit** en Conventional Commits.
5. S'arrêter à la fin de l'étape et résumer ce qui a été fait + quelle est la prochaine.

Une « étape » = un bloc Axx/Bxx/Cxx. Si un bloc est gros, on peut le faire en plusieurs conversations (cocher les sous-tâches au fur et à mesure).

---

## Décisions arrêtées (ne pas re-litiguer)

- **Cœur produit** = sync auto multi-machines. Le serveur (NAS) est le hub **toujours allumé** et la **source de vérité**. Les machines ne sont pas toutes allumées en même temps → le serveur est le pont.
- **Base de données : SQLite** (+ `aiosqlite`). Plus de PostgreSQL, plus de conteneur `db`. (Postgres redeviendra pertinent seulement à un éventuel mode multi-utilisateurs — Phase 7.)
- **Agent = stateless, déclenché par launchd.** Commande `sync` sans état long-vécu : `discover → hash (avec cache) → delta → push inconnues → pull manquantes → install → exit`.
- **Pull réactif = push serveur via SSE** vers un petit process `listen` (launchd `KeepAlive`) qui ne fait que **déclencher `sync`**. L'événement SSE est un simple signal « re-sync » (sans payload exploité → pas de bug de clé). Pas de polling comme mécanisme principal ; `StartInterval` long = filet de sécurité. *(Alternative acceptable : réutiliser le WS existant au lieu de SSE.)*
- **Agent ↔ serveur = HTTP + SSE.** Plus de WebSocket **côté agent** (on supprime `sync_client.py` WS, la reconnexion, etc.). Le WS **frontend** peut rester.
- **Frontend = plus tard.** On le garde juste compilable ; on décidera des features gardées avant d'investir le design.

---

## Architecture cible

```
Machine A (MacBook)            Serveur FontSync (NAS, toujours ON)        Machine B (Mac Mini)
                               FastAPI + SQLite + storage (FS/S3)
 install "Inter.ttf"                                                       (allumée)
   │                                                                        listen (SSE) ──┐
   │ launchd WatchPaths                                                                    │
   ▼                                                                                       ▼
 fontsync sync ───HTTP push──►  import + insert (idempotent) ───SSE "sync"────►  fontsync sync
                                source de vérité                                  (delta → pull → install)
```

Déclencheurs de `fontsync sync` (commande stateless, identique quelle que soit la source) :
- **launchd `WatchPaths`** (`~/Library/Fonts`) → changement local → push prompt.
- **`listen` (SSE)** → signal distant → pull réactif.
- **launchd `StartInterval` (~600 s)** → filet de sécurité / rattrapage.

Deux jobs launchd : `com.fontsync.sync` (déclenché, RunAtLoad) et `com.fontsync.listen` (KeepAlive, RunAtLoad).

---

## Phase A — Socle backend (SQLite + correctness + robustesse)

- [x] **A1 — Docs.** Mettre à jour `CLAUDE.md` (stack : SQLite, agent stateless+SSE) et `SPECS.md` (section 3 stack, section 6 agent, section 8 déploiement) pour refléter l'architecture cible. *(En premier : les futures conversations chargent CLAUDE.md et seraient sinon induites en erreur par « PostgreSQL ».)*
- [x] **A2 — Migration SQLite.** *(Vérifié via venv : `alembic upgrade head` + import app OK, PRAGMA `foreign_keys=ON`/`journal_mode=WAL` confirmés. Build Docker non exécuté — le frontend casse encore le `docker build`, cf. C1.)*
  - Remplacer les types `postgresql.dialects` dans `backend/models/*` : `JSONB`→`JSON`, `UUID`→type portable (SQLAlchemy `Uuid`/`String`), `TIMESTAMP(timezone=True)`→`DateTime`.
  - Retirer l'index GIN (`backend/models/font.py`) et les `server_default` Postgres `gen_random_uuid()/now()` (`backend/models/base.py`) — les `default=` Python existent déjà.
  - `backend/database.py` + `backend/config.py` : driver `aiosqlite`, `DATABASE_URL` par défaut sur un fichier (ex. `/data/fontsync.db`). Activer `PRAGMA foreign_keys=ON` et `journal_mode=WAL`.
  - Réécrire la requête stats Postgres-only (`backend/routers/stats.py` ~L60-72 : `jsonb_array_elements_text`/`jsonb_typeof`) en `json_each` (json1) ou agrégation applicative.
  - Alembic : repartir d'**une migration baseline unique** SQLite (la DB de dev est jetable). Vérifier `alembic/env.py`.
  - `docker-compose.yml` : supprimer le service `db`, son healthcheck et le volume `pg_data` ; un seul conteneur ; volume pour le fichier SQLite + volume fonts.
  - `requirements.txt` : retirer `asyncpg`, ajouter `aiosqlite`.
  - Vérifier que `docker compose up` démarre et `alembic upgrade head` passe.
- [x] **A3 — Pipeline d'import robuste & idempotent** (`backend/services/font_importer.py`). *(Vérifié via smoke tests sur de vraies fonts système, dont un `.ttc` ; race concurrent reproduit → une seule ligne en base.)*
  - [x] Insertion idempotente sur `file_hash` : `_find_by_hash` (sans filtre `deleted_at`) + `try/except IntegrityError` → rollback puis retour de la font existante. Course de deux pushs concurrents du même hash testée. Re-import d'une font soft-deleted → ressuscitée (`_revive_if_deleted`).
  - [x] Pas de fichier orphelin : store→insert dans un `try`, cleanup `_safe_delete_storage` si l'insert échoue hors doublon ; en cas de doublon le fichier (même hash → même chemin) appartient légitimement à la font existante. Regroupement famille isolé dans une transaction best-effort (n'annule plus l'import).
  - [x] `.ttc` : `font_analyzer` détecte la collection (magic `ttcf`) et parse la **première** sous-font (`fontNumber=0`) → plus de métadonnées vides. Éclatement multi-sous-fonts explicitement reporté (nécessiterait une clé unique composite hash+index).
  - [x] `unicode_ranges` peuplé : couverture quantitative `{script: nb_codepoints}` dérivée de la cmap (`_compute_unicode_ranges`), plus fine que `supported_scripts`.
- [x] **A4 — Sémantique de sync** (`backend/services/sync_manager.py`, `backend/routers/sync.py`). *(Vérifié via smoke test : 3 ensembles delta corrects + 0 `device_fonts` fantôme écrit ; migration baseline ré-appliquée sans `sync_queue` ; app importe.)*
  - [x] `compute_delta` : lecture pure — ne crée plus d'associations `device_fonts` et ne `commit()` plus (param `device_id` retiré de la signature, devenu inutile).
  - [x] `pull_font` : `device_id` désormais **requis** ; l'association `device_font` n'est enregistrée **qu'après** récupération réussie du fichier (un échec storage ne laisse plus d'association « installée » fantôme).
  - [x] Table/modèle morts `sync_queue` supprimés (`backend/models/sync_queue.py`, relations `device`/`font`, export `__init__`, table de la migration baseline).
- [ ] **A5 — Canal temps réel : SSE agent + events clients.**
  - Nouvel endpoint **SSE** `GET /api/agent/{device_id}/events` (ou équivalent) qui émet un signal `sync` quand une font devient disponible pour ce device. Consommé par le process `listen`. *(Décider SSE vs réutilisation WS ; SSE recommandé.)*
  - Émettre les events manquants vers les clients frontend : `font.deleted` (dans `delete_font`), `font.updated` (dans `update_font`/`restore`) — `backend/routers/fonts.py`.
  - `backend/services/ws_manager.py` : `asyncio.Lock` sur les broadcasts ; évincer l'ancien socket à la reconnexion ; mettre à jour `devices.last_seen_at` au `heartbeat`. *(Le WS agent peut être retiré puisque l'agent passe en HTTP+SSE ; garder le WS client.)*
  - `backend/main.py` : garder le catch-all SPA mais **ne pas** renvoyer `index.html` pour les chemins `/api/*` (renvoyer 404 JSON).
- [ ] **A6 — Tests backend** (`tests/backend/`). Pipeline d'import (dédup, font malformée non rejetée, idempotence), delta-sync (les 3 ensembles), stats. Utiliser de vraies TTF de `tests/fixtures/`.
- [ ] **A7 — Nettoyage.** Exposer `width_class` dans `FontResponse` (`backend/schemas/font.py`). Retirer le `FontFilters` mort et les imports inutilisés (`cast`/`JSONB` dans `stats.py`). Inclure `glyph_count`/`name` dans `FontSortField` (specs §5.1).

## Phase B — Agent stateless launchd + listener SSE

- [ ] **B1 — Commande `sync` stateless** : `discover (Core Text + dossiers) → hash (avec cache B2) → register/update device → POST /sync/delta → push inconnues → pull manquantes (si auto_pull) → install → exit`. **Aucun état global mutable.** Réutiliser `agent/discovery.py` et `agent/font_installer.py` (déjà sûrs).
- [ ] **B2 — Cache de hash local** par clé `(path, size, mtime)` dans `~/.fontsync/state.(db|json)` → ne re-hasher que ce qui a changé (scan de 500 fonts quasi gratuit après la 1re fois).
- [ ] **B3 — Suppressions.** Retirer `agent/tray.py`, les parties WS persistant de `agent/sync_client.py`, le watcher watchdog et la boucle asyncio/reconnexion. Mettre à jour `agent/requirements.txt` (retirer `watchdog`, `pystray` ; garder `pyobjc-framework-CoreText`, `httpx`, `pyyaml`).
- [ ] **B4 — Process `listen`** : ouvre la connexion SSE au serveur ; à chaque event → (debounce ~2 s) → lance `sync` (in-process gardé par try/except, ou subprocess). Boucle de reconnexion triviale (sleep + retry). **Zéro état, zéro hash.**
- [ ] **B5 — Config** (`agent/config.py`). Persister correctement `device_id`/token (bug actuel : non sauvegardés au `save()`). Cohérence du défaut `auto_pull`. Champs : `server.url`, `device_token`, `scan.directories`, `scan.ignore_patterns`, `sync.auto_pull`.
- [ ] **B6 — HTTP propre.** `sync` étant une commande courte, HTTP synchrone `httpx` suffit (plus d'event loop → le bug « blocage de l'event loop » disparaît). Le `listen` utilise `httpx.stream` pour la SSE.
- [ ] **B7 — Sécurité install/désinstall** (`agent/font_installer.py`). Garder les gardes path-traversal (déjà bonnes). Durcir contre l'**écrasement d'une font locale homonyme** (install) et la **désinstallation par nom** (préférer un mapping par hash). Respecter « jamais de suppression auto » (déjà respecté).
- [ ] **B8 — launchd.**
  - `com.fontsync.sync.plist` : `WatchPaths` (`~/Library/Fonts`, option `/Library/Fonts`), `StartInterval` ~600 s, `RunAtLoad`.
  - `com.fontsync.listen.plist` : `KeepAlive`, `RunAtLoad`.
  - Script d'installation/désinstallation des LaunchAgents (`launchctl bootstrap/bootout`).
- [ ] **B9 — Notifications** (`agent/notifier.py`) : migrer `NSUserNotification` (déprécié, silencieux hors app signée) → `UNUserNotifications`, **ou** retirer les notifications pour l'instant (basse priorité).
- [ ] **B10 — Packaging.** Beaucoup moins critique qu'avant (CLI + petit `listen`). Décider : simple binaire/pkg signé vs PyInstaller. La friction notarisation est largement levée. *(Détail différé.)*
- [ ] **B11 — Tests agent** (`tests/agent/`, à créer). Logique delta, cache de hash (invalidation par mtime), installer en dry-run, reconnexion `listen`.

## Phase C — Frontend (minimal : juste de quoi tourner)

- [ ] **C1 — Réparer le build.** Importer `Monitor` (lucide) dans `frontend/src/pages/FontDetailPage.vue` (~L399). Vérifier `npm run build` (`vue-tsc -b && vite build`).
- [ ] **C2 — Aligner sur l'API** si sa forme a changé (nouveaux noms d'events, `width_class`, etc.). Brancher le compteur Dashboard sur `/api/stats`.
- [ ] **C3 — Design différé** (à rouvrir quand on décide des features gardées) : UI d'upload, filtres accessibles (sidebar morte), couverture des events WS, indicateur « Reconnexion… », pivot familles à figer dans les specs.

---

## Annexe — bugs concrets relevés à l'audit (traçabilité)

Repris dans les tâches ci-dessus ; conservés ici pour ne rien perdre entre conversations.

| # | Problème | Fichier | Tâche |
|---|----------|---------|-------|
| 1 | Pull temps réel cassé (`fontId` vs `id`) | `agent/main.py:317` | B1/B4 (résolu par design : signal SSE sans payload) |
| 2 | Build front cassé (`Monitor` non importé) | `frontend/src/pages/FontDetailPage.vue:399` | C1 |
| 3 | `font.deleted`/`font.updated` jamais émis | `backend/routers/fonts.py` | A5 |
| 4 | `known_hashes` diverge après reconnect/rescan | `agent/main.py:188` | B1 (résolu par design : stateless) |
| 5 | HTTP bloquant sur l'event loop | `agent/main.py:293,480` | B6 (résolu par design) |
| 6 | `device_fonts` fantômes + `commit()` dans le delta | `backend/services/sync_manager.py:60-71` | A4 |
| 7 | `pull_font` n'enregistre pas l'install de façon fiable | `backend/routers/sync.py:131-169` | A4 |
| 8 | `sync_queue` = code mort | `backend/models/sync_queue.py` | A4 |
| 9 | `stats.py` 100% Postgres (JSONB) | `backend/routers/stats.py:60-72` | A2 |
| 10 | `ws_manager` sans lock / pas d'éviction socket / `last_seen_at` jamais maj | `backend/services/ws_manager.py` | A5 |
| 11 | Catch-all SPA avale les `/api/*` mal orthographiés | `backend/main.py` | A5 |
| 12 | `width_class` parsé mais absent de l'API | `backend/schemas/font.py` | A7 |
| 13 | `device_id`/token non persistés | `agent/config.py` | B5 |
| 14 | Install écrase une font homonyme / uninstall par nom | `agent/font_installer.py` | B7 |
| 15 | Notifications dépréciées (silencieuses) | `agent/notifier.py` | B9 |
