# FontSync — Plan de refonte (backend + agent)

> Reprise d'un projet bâti en sprint (8–10 mars 2026), dormant ~3 mois.
> Objectif : rendre **robuste et optimisé** le backend + l'agent. Le design frontend
> est traité dans un second temps (on garde juste le frontend compilable).

**STATUT : B8 (launchd) fait. Prochaine étape : B9 (notifications).**

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
- [x] **A5 — Canal temps réel : SSE agent + events clients.** *(Vérifié : plomberie SSE du `ws_manager` (signal/exclude/unsubscribe) + generator de l'endpoint pilotés en direct → event initial, coalescing de signaux multiples, et cleanup à la déconnexion OK ; `ruff check` + import app OK.)*
  - [x] Nouvel endpoint **SSE** `GET /api/agent/{device_id}/events` (`backend/routers/agent_events.py`) : event `sync` initial au connect, signal `sync` quand une font devient disponible, keep-alive ~25 s, coalescing des signaux en attente, désabonnement en `finally`. Émis par `push_font` (`broadcast_sync(exclude_device_id=source)`) et `restore_font`.
  - [x] Events frontend manquants : `font.deleted` (dans `delete_font`), `font.updated` (dans `update_font` et `restore_font`) — `backend/routers/fonts.py`.
  - [x] `backend/services/ws_manager.py` : `asyncio.Lock` sur les broadcasts ; éviction (fermeture) de l'ancien socket agent à la reconnexion ; `devices.last_seen_at` mis à jour à chaque `heartbeat` (`backend/routers/ws.py`). *(WS agent conservé pour l'instant — sa suppression côté agent est Phase B.)*
  - [x] `backend/main.py` : catch-all SPA renvoie un **404 JSON** pour les chemins `/api/*` non résolus au lieu de `index.html`.
- [x] **A6 — Tests backend** (`tests/backend/`). Pipeline d'import (dédup, font malformée non rejetée, idempotence + résurrection soft-delete), delta-sync (3 ensembles + lecture pure A4 + exclusion soft-deleted), stats (total/format/classification/script + exclusion soft-deleted). *(Les fixtures `tests/fixtures/*.otf|ttf` sont des polices commerciales gitignorées, donc absentes en CI/Docker → `conftest.py` génère de **vraies** TTF valides à la volée avec fontTools `FontBuilder`, rendant la suite A6 autoportante. Fixtures partagées : session SQLite in-memory `StaticPool` + FK ON, storage filesystem en tmp_path. 14 tests, tous verts. NB : `test_font_analyzer.py`/`test_storage.py` pré-existants restent dépendants des fixtures commerciales et échouent/skippent sans elles — hors périmètre A6.)*
- [x] **A7 — Nettoyage.** `width_class` exposé dans `FontResponse` (déjà présent, vérifié). `FontFilters` mort supprimé + import `Field` devenu inutile retiré (`backend/schemas/font.py`). `glyph_count`/`name` ajoutés à `FontSortField` (specs §5.1) ; `name` n'ayant pas de colonne dédiée, le tri mappe sur `full_name` dans `backend/routers/fonts.py`. *(Les imports `cast`/`JSONB` de `stats.py` avaient déjà disparu en A2 — rien à retirer.)* Vérifié : `ruff check` OK, app importe, 14 tests A6 verts.

## Phase B — Agent stateless launchd + listener SSE

- [x] **B1 — Commande `sync` stateless** : `discover (Core Text + dossiers) → hash (avec cache B2) → register/update device → POST /sync/delta → push inconnues → pull manquantes (si auto_pull) → install → exit`. **Aucun état global mutable.** Réutiliser `agent/discovery.py` et `agent/font_installer.py` (déjà sûrs). *(`agent/sync_command.py` : `run_sync(config, client=None)` pur, client HTTP injectable, bilan `SyncResult`. Drapeaux `auto_pull`/`auto_push` lus depuis la réponse `register` — **le serveur fait foi**. Primitives de hachage extraites dans `agent/hashing.py` (importable sans `watchdog`) ; `scanner.py` les ré-exporte. CLI `python -m agent sync` (`agent/__main__.py` argparse). `SyncClient` importé en différé → testable sans `httpx`. **Le cache de hash est laissé à B2** : `scan_fonts` re-hache tout pour l'instant. Le process `listen` arrive en B4. 6 tests `tests/agent/test_sync_command.py` (flux complet, drapeaux serveur, format non installable, échec register fatal, statelessness). NB : le persistant `agent/main.py`/`tray.py` reste sur disque jusqu'à sa suppression en B3.)*
- [x] **B2 — Cache de hash local** par clé `(path, size, mtime)` dans `~/.fontsync/state.(db|json)` → ne re-hasher que ce qui a changé (scan de 500 fonts quasi gratuit après la 1re fois). *(`agent/hash_cache.py` : `HashCache` JSON (`~/.fontsync/hash_cache.json`), clé `(path, size, mtime_ns)` — nanoseconde entier pour éviter les pièges de comparaison float après aller-retour JSON. Écriture atomique (`os.replace`), élagage des chemins disparus à `save()`. Cache purement reconstructible → fichier absent/corrompu/mauvaise version = re-hash, jamais bloquant ; aucun état de sync mutable introduit. `scan_fonts(discovered, cache=...)` : stat → lookup cache → hash seulement si miss. `run_sync` charge le cache, scanne, `save()` immédiatement (le hachage est valide quelle que soit l'issue réseau). 12 tests `tests/agent/test_hash_cache.py` : hit/miss (mtime, size, chemin inconnu), persistance, élagage, fichier absent/corrompu/entrées corrompues/mauvaise version, intégration `scan_fonts` (réutilisation + ré-hash sur changement). NB : les tests `run_sync` existants stubbent `HashCache` pour ne pas toucher `~`.)*
- [x] **B3 — Suppressions.** Supprimé `agent/tray.py`, `agent/main.py` (la boucle asyncio/reconnexion persistante) et `agent/assets/` (icônes tray orphelines). `WebSocketClient` retiré de `agent/sync_client.py` (qui ne garde que le `SyncClient` HTTP synchrone). `scanner.py` réduit à un simple module de ré-exports des primitives de hachage — `WatcherService`/`_FontEventHandler`/`run_periodic_scan` (watchdog) supprimés. `agent/requirements.txt` : retiré `watchdog`, `websockets`, `pystray`, `Pillow` ; gardé `pyobjc-framework-Cocoa` (encore utilisé par `notifier.py`, traité en B9). *(Vérifié : `ruff format` + `ruff check` agent/ OK ; aucune référence pendante aux symboles retirés ; 18 tests `tests/agent/` verts. NB : `scripts/test_ws.py` (script de dev manuel ciblant le WS frontend serveur) laissé en place — hors périmètre agent.)*
- [x] **B4 — Process `listen`** : ouvre la connexion SSE au serveur ; à chaque event → (debounce ~2 s) → lance `sync` (in-process gardé par try/except, ou subprocess). Boucle de reconnexion triviale (sleep + retry). **Zéro état, zéro hash.** *(`agent/listen_command.py` : producteur (thread daemon) lit le flux SSE `GET /api/agent/{device_id}/events` et empile un jeton par `event: sync` (`parse_sse_signals`, keep-alive ignorés) ; consommateur (thread principal) débounce ~2 s, draine la rafale → un seul `run_sync`. Reconnexion = `signals_factory` rappelée après fin/échec du flux + `stop.wait(reconnect_delay)`. `_resolve_device_id` : id caché en config sinon `register_device` (persisté). `read timeout` SSE 60 s > keep-alive 25 s. Échec de `run_sync` journalisé, n'arrête pas le listener. CLI `python -m agent listen`. Producteur/consommateur/parser sont des fonctions pures de `queue`/`stop`/factory → 11 tests `tests/agent/test_listen_command.py` (parsing, coalescing, reconnexion après coupure, résolution device_id, intégration threads réels) sans réseau réel. NB : `httpx` importé en différé ; persistance fiable de `device_id`/token = B5.)*
- [x] **B5 — Config** (`agent/config.py`). *(Round-trip `device_id`/token vérifié par tests. Défaut `auto_pull` rendu cohérent : le dataclass passe à `False` pour s'aligner sur `load()` **et** sur le défaut serveur `backend/models/device.py` — c'est le serveur qui fait foi après le 1er `register`. `load()` réutilise désormais une instance `cls()` comme **unique** source de défauts → plus de divergence dataclass/lecture possible, et tolérance aux sections YAML nulles/partielles. `save()` rendu atomique (`os.replace`, comme `hash_cache.py`) et restreint à 0600 puisque le fichier porte un token. Champs morts retirés : `scan_interval_minutes` (remplacé par launchd `StartInterval`, B8) et `show_notifications` (inutilisé ; les notifications sont rouvertes en B9). 7 tests `tests/agent/test_config.py` ; 35 tests agent verts.)*
- [x] **B6 — HTTP propre.** `sync` étant une commande courte, HTTP synchrone `httpx` suffit (plus d'event loop → le bug « blocage de l'event loop » disparaît). Le `listen` utilise `httpx.stream` pour la SSE. *(`SyncClient` refondu : un `httpx.Client` unique avec `base_url`, `httpx.Timeout` explicite — `REQUEST_TIMEOUT` connect/read/write/pool, `TRANSFER_TIMEOUT` plus long pour upload/download — et en-têtes par défaut (`User-Agent: fontsync-agent/{version}`, `Accept: application/json`, repris aussi par le flux SSE du `listen`). Helper `_send(build, what=…)` centralisant `raise_for_status` + réessais bornés (`MAX_ATTEMPTS=3`, backoff linéaire injectable via `sleep`) sur les seules erreurs **de transport** (`ConnectError`/`*Timeout`/`RemoteProtocolError`) — les erreurs HTTP applicatives remontent sans réessai ; toutes les opérations REST étant idempotentes côté serveur, un réessai ne duplique rien. `build()` ré-ouvre le fichier à chaque tentative pour que le push reste rejouable. Épuisement → `SyncClientError`. **Bug corrigé** : le log de `push_font` lisait des clés snake_case (`font_id`/`is_duplicate`) toujours absentes de la réponse camelCase → corrigé en `fontId`/`isDuplicate` ; parsing du `Content-Disposition` extrait dans `_filename_from_disposition` (RFC 5987 + forme simple). 13 tests `tests/agent/test_sync_client.py` via `httpx.MockTransport` injecté (config client, payloads/lectures camelCase, dédup push, comptage erreur HTTP, filename pull, réessai→succès / épuisement→`SyncClientError` / pas de réessai sur 4xx) ; `pytest.importorskip("httpx")` garde la suite verte là où httpx n'est pas installé. 48 tests agent verts.)*
- [x] **B7 — Sécurité install/désinstall** (`agent/font_installer.py`). *(Gardes path-traversal conservées et factorisées dans `_is_within`. **Install** : `install_font(filename, data, *, expected_hash=None)` ne écrase plus jamais une font homonyme au contenu différent — un `expected_hash` ≠ contenu reçu est refusé (téléchargement corrompu) ; un nom déjà pris par le **même** hash = no-op idempotente ; un nom pris par un contenu **différent** → installation sous un nom désambiguïsé `{stem}__fontsync-{hash12}{ext}` (la font locale de l'utilisateur est préservée). Le hash attendu vient du `fileHash` du delta serveur, threadé via `_pull_and_install` (`sync_command.py`). **Uninstall** : `uninstall_font(filename, file_hash)` — suppression **gardée par le hash** : on ne supprime qu'un fichier dont le contenu correspond exactement (un homonyme au contenu différent n'est jamais touché). Chemin rapide par nom (direct + désambiguïsé), repli par balayage des dossiers gérés pour un fichier renommé mais de même contenu. L'identification par hash reste **stateless** : re-hachage des candidats sur disque, pas de manifeste mutable. « Jamais de suppression auto » toujours respecté. 13 tests `tests/agent/test_font_installer.py` (vrai FS en tmp_path) ; 61 tests agent verts. NB : `activate_font`/`deactivate_font` (par nom, non câblés) laissés en l'état — hors périmètre B7.)*
- [x] **B8 — launchd.** Deux gabarits LaunchAgent (jetons `@PYTHON@`/`@WORKDIR@`/`@HOME@`/`@LOGDIR@`) dans `agent/launchd/` + script `install.sh` (`install`/`uninstall`/`status`). *(Vérifié : `plutil -lint` OK sur les deux plists substitués via le flux réel du script, `agent` importable depuis `.venv`, 4 tests `tests/agent/test_launchd.py` (substitution → plist valide + clés launchd), 66 tests agent verts.)*
  - [x] `com.fontsync.sync.plist` : `WatchPaths` (`~/Library/Fonts` + `/Library/Fonts`), `StartInterval` 600 s, `RunAtLoad`, **pas** de `KeepAlive` (commande courte), `ProcessType=Background`, logs dans `~/Library/Logs/FontSync/`.
  - [x] `com.fontsync.listen.plist` : `KeepAlive`, `RunAtLoad`, `ThrottleInterval` 10 s.
  - [x] `agent/launchd/install.sh` : résolution du Python (`$FONTSYNC_PYTHON` → `.venv` → `python3`), substitution `sed` des gabarits vers `~/Library/LaunchAgents/`, `plutil -lint`, `launchctl bootout`+`bootstrap gui/$(id -u)`, `kickstart` d'un 1er `sync`. Sous-commandes `install`/`uninstall`/`status`.
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
| 13 | `device_id`/token non persistés | `agent/config.py` | B5 ✓ |
| 14 | Install écrase une font homonyme / uninstall par nom | `agent/font_installer.py` | B7 ✓ |
| 15 | Notifications dépréciées (silencieuses) | `agent/notifier.py` | B9 |
