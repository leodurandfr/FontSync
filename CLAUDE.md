# FontSync

## Projet

FontSync est un font manager self-hosted avec synchronisation multi-machines en temps réel. Le serveur Docker centralise toutes les polices de l'utilisateur, un agent Python détecte et synchronise automatiquement les fonts entre machines, et une interface web permet de naviguer et gérer la bibliothèque.

Lire `SPECS.md` pour l'architecture complète, le modèle de données, les endpoints API et le scope de chaque phase.

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
├── SPECS.md                   # Spécifications techniques complètes
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

- **Refonte en cours : la source de vérité du périmètre est `PLAN.md` à la racine.** SPECS.md décrit la vision produit ; pour l'architecture cible (SQLite, agent stateless + SSE) c'est PLAN.md qui prime.
- **Ne jamais implémenter de fonctionnalités hors de la phase en cours.** Consulter PLAN.md (puis SPECS.md) pour connaître le scope de chaque phase.
- **Le serveur (NAS, toujours allumé) est la source de vérité.** L'agent est **stateless** : chaque `sync` repart de l'état réel du disque, jamais d'un état mémoire mutable. Le push réactif serveur→agent est un simple signal SSE « re-sync » (sans payload exploité).
- **Toujours tester avec de vraies fonts.** Des fichiers TTF de test sont dans `tests/fixtures/`.
- **Robustesse du parsing fonttools** : toujours wrapper dans try/except. Une font malformée doit être stockée avec des métadonnées partielles, jamais rejetée.
- **Pas d'authentification dans le MVP** (Phases 1-3).
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
