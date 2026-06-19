# FontSync

## Projet

FontSync est un font manager self-hosted avec synchronisation multi-machines en temps réel. Le serveur Docker centralise toutes les polices de l'utilisateur, un agent Python détecte et synchronise automatiquement les fonts entre machines, et une interface web permet de naviguer et gérer la bibliothèque.

Lire `ARCHITECTURE.md` pour l'architecture complète, le modèle de données et les endpoints API. `ROADMAP.md` porte la vision long terme (non-actionable).

## Stack technique

### Backend
- Python 3.12+
- FastAPI + Uvicorn
- SQLAlchemy (async) + aiosqlite
- Alembic (migrations)
- SQLite (un seul fichier, `journal_mode=WAL`, `PRAGMA foreign_keys=ON`)
- fonttools (parsing des métadonnées de fonts)
- WebSocket natif FastAPI (canal **frontend** uniquement) + SSE (push « re-sync » vers l'agent)

> Postgres a été abandonné. Il ne redevient pertinent qu'à un éventuel mode multi-utilisateurs (Phase 7).

### Agent
- Python 3.12+
- **Commande `sync` stateless**, déclenchée par launchd (`WatchPaths` sur `~/Library/Fonts` + `StartInterval` filet de sécurité), `RunAtLoad`
- **Process `listen`** (launchd `KeepAlive`) : ouvre une connexion SSE vers le serveur et relance `sync` à chaque signal
- pyobjc (Core Text, découverte macOS)
- httpx (HTTP synchrone côté `sync` + `httpx.stream` pour la SSE côté `listen`)
- pyyaml (config)
- Cache de hash local `(path, size, mtime)` dans `~/.fontsync/`

### Frontend
- Vue 3 (Composition API, `<script setup>`)
- TypeScript strict
- shadcn-vue
- Tailwind CSS
- Vite
- Pinia (state management)

### Infra
- Docker Compose
- Abstraction storage : filesystem local (défaut) ou S3-compatible

## Conventions de code

### Python (backend + agent)
- Type hints systématiques sur toutes les fonctions
- async/await pour tout le code I/O (DB, filesystem, réseau)
- Formatage : `ruff format` + `ruff check`
- Imports triés avec `ruff` (isort intégré)
- Docstrings en français pour les services métier, en anglais pour les utilitaires
- Tests avec `pytest` + `pytest-asyncio`
- Schémas Pydantic pour toute validation d'entrée/sortie API

### TypeScript / Vue
- TypeScript strict (`strict: true` dans tsconfig)
- Composition API avec `<script setup lang="ts">` uniquement (jamais Options API)
- shadcn-vue pour les composants UI de base
- Tailwind CSS pour le styling (pas de CSS custom sauf exception justifiée)
- Formatage : `prettier`
- Stores Pinia en setup syntax (`defineStore` avec fonction)
- Composables dans `src/composables/` pour la logique réutilisable

### Général
- Git : Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`)
- Base de données : snake_case pour colonnes et tables
- API REST : kebab-case pour les URLs, camelCase pour le JSON
- UUID pour toutes les clés primaires (type SQLAlchemy portable `Uuid`/`String`, pas de type dialect-spécifique)
- Soft delete avec colonne `deleted_at` (`DateTime` nullable)

## Structure du projet

```
fontsync/
├── CLAUDE.md                  # Ce fichier
├── ARCHITECTURE.md            # Architecture, modèle de données, API (source de vérité technique)
├── ROADMAP.md                 # Vision long terme (non-actionable)
├── DEVELOPMENT.md             # Tester en local (serveur + clients simulés)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/
├── backend/
│   ├── main.py                # FastAPI app
│   ├── config.py              # Pydantic BaseSettings
│   ├── database.py            # SQLAlchemy async engine + session
│   ├── models/
│   ├── schemas/
│   ├── routers/
│   ├── services/
│   └── utils/
├── agent/
├── frontend/
│   ├── src/
│   │   ├── router/
│   │   ├── stores/
│   │   ├── composables/
│   │   ├── components/
│   │   └── pages/
│   └── ...
├── tests/
│   ├── fixtures/              # Fichiers fonts de test (TTF libres de droits)
│   ├── backend/
│   └── agent/
└── scripts/
```

## Règles importantes

- **Refonte + publication terminées : `0.0.1` est livrée** (self-hosted v1 publiable — SQLite, agent stateless + SSE, auth par token, image Docker NAS, app Mac menu bar Swift/SwiftUI signée/notarisée). Plus de « plan actif » : l'architecture livrée est documentée dans `ARCHITECTURE.md`, la **vision long terme** (dual-mode self-host/cloud, cross-platform, multi-utilisateurs) vit dans `ROADMAP.md` — orientante, **non-actionable**. *(Les plans historiques `PLAN.md`/`PLAN-PUBLICATION.md` ont été retirés ; récupérables via l'historique git.)*
- **Ne pas implémenter de fonctionnalités du `ROADMAP.md` (long terme) sans demande explicite.** Le prochain palier (0.1.0) regroupe les ajustements UI/serveur décidés au coup par coup.
- **Le serveur (NAS, toujours allumé) est la source de vérité.** L'agent est **stateless** : chaque `sync` repart de l'état réel du disque, jamais d'un état mémoire mutable. Le push réactif serveur→agent est un simple signal SSE « re-sync » (sans payload exploité).
- **Toujours tester avec de vraies fonts.** Des fichiers TTF de test sont dans `tests/fixtures/`.
- **Robustesse du parsing fonttools** : toujours wrapper dans try/except. Une font malformée doit être stockée avec des métadonnées partielles, jamais rejetée.
- **Auth = token partagé d'instance** (`FONTSYNC_TOKEN`), vérifié sur tout `/api/*` + SSE + WS (header `Authorization: Bearer` ; query `?token=` accepté pour le WS navigateur uniquement, **URL-encodé** car un token base64 contient des `+`). **Pas de comptes utilisateurs** — ça reste mode cloud / multi-utilisateurs (long terme).
- **L'agent peut désinstaller des fonts localement sur ordre explicite de l'utilisateur** (via le frontend), mais la font reste toujours sur le serveur.
- **Formats WOFF/WOFF2** : acceptés au stockage et prévisualisables, mais jamais proposés à l'installation système.

## Commandes utiles

```bash
# Démarrer les services Docker
docker compose up -d

# Lancer les migrations
docker compose exec fontsync alembic upgrade head

# Lancer les tests backend
docker compose exec fontsync pytest tests/backend/ -v

# Frontend dev
cd frontend && npm run dev

# Formatage
ruff format backend/ agent/
cd frontend && npx prettier --write src/
```
