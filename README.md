# FontSync

Font manager **self-hosted** avec synchronisation multi-machines en temps réel :
un serveur Docker centralise la bibliothèque de polices, un agent Python détecte et
synchronise automatiquement les fonts entre vos Macs, et une interface web permet de
naviguer et gérer la collection.

- 🗄️ **Serveur source de vérité** — toutes vos polices au même endroit (NAS, Docker).
- 🔄 **Sync automatique** — l'agent surveille `~/Library/Fonts` et propage les
  changements en quasi temps réel (push/pull + signal SSE).
- 🍎 **App Mac native** — menu bar Swift signée, agent embarqué, premier lancement
  guidé, notifications et mises à jour automatiques.
- 🌐 **UI web** — parcourir, prévisualiser, importer et gérer la bibliothèque.
- 🔒 **Token d'instance** — tout `/api/*` protégé par un secret partagé.

> Pour la vision produit complète et le modèle de données, voir [`SPECS.md`](SPECS.md).
> Plan de publication : [`PLAN-PUBLICATION.md`](PLAN-PUBLICATION.md).

## Architecture

```
   Mac (utilisateur)                              Serveur FontSync (NAS, Docker)
 ┌───────────────────────────┐                 ┌──────────────────────────────────┐
 │ App FontSync (menu bar)    │── HTTP+token ──►│ FastAPI + SQLite + storage        │
 │  • statut / sync / prefs   │                 │  • /api/* protégé par token       │
 │  • fenêtre webview ────────┼─── web UI ─────►│  • sert l'UI web (SPA)            │
 │  • gère l'agent (launchd)  │                 │  • SSE « re-sync » → agents       │
 │      │                                       │  • migrations au boot             │
 │      ▼                                       └──────────────────────────────────┘
 │ fontsync-agent (launchd)   │── push/pull ───────────────▲
 │  sync (WatchPaths) + listen (SSE) ───────── signal ──────┘
 └───────────────────────────┘
```

Le **serveur** (toujours allumé) est la **source de vérité**. L'agent est
**stateless** : chaque `sync` repart de l'état réel du disque.

---

## Quickstart « 2 machines »

L'objectif : un serveur, deux Macs, les polices synchronisées entre les deux.

### 1. Démarrer le serveur (une fois)

Sur le NAS (ou tout hôte Docker) :

```bash
# Générer un token d'instance et le placer dans un .env
echo "FONTSYNC_TOKEN=$(openssl rand -base64 32)" > .env

# Récupérer l'exemple de compose et démarrer
curl -O https://raw.githubusercontent.com/leodurand/FontSync/main/docker-compose.nas.yml
docker compose -f docker-compose.nas.yml up -d
```

Le serveur écoute sur `http://<hôte>:8080`. Notez son URL et le token : ce sont les
**deux seules informations** à saisir sur chaque Mac. Guide NAS détaillé (Synology,
volumes, sauvegarde) : [`docs/INSTALL-NAS.md`](docs/INSTALL-NAS.md).

### 2. Configurer le **premier** Mac

1. Téléchargez `FontSync-X.Y.Z.dmg` depuis la
   [dernière release](https://github.com/leodurand/FontSync/releases/latest),
   ouvrez-le et glissez **FontSync** dans `Applications`.
2. Lancez l'app : l'icône apparaît dans la barre des menus et l'**assistant de
   premier lancement** s'ouvre. Il vous guide en quatre étapes :
   - **Serveur** : collez l'URL (`http://<hôte>:8080`) et le token, puis
     « Tester la connexion » ;
   - **Agent** : « Installer l'agent » (met en place les jobs launchd qui
     surveillent `~/Library/Fonts`) ;
   - **Première synchronisation** : récupère la bibliothèque du serveur ;
   - **Terminé**.
3. Vos polices locales remontent vers le serveur ; vérifiez-les dans la fenêtre
   « Ouvrir FontSync » (UI web) ou via le navigateur sur l'URL serveur.

### 3. Configurer le **second** Mac

Répétez l'étape 2 sur le deuxième Mac (même URL, même token). À la première sync,
il **récupère** toutes les polices déjà présentes sur le serveur et les installe.

### 4. Vérifier la synchronisation temps réel

Ajoutez une police dans `~/Library/Fonts` sur le Mac A (ou importez-la depuis l'UI
web) : en quelques secondes, le serveur la reçoit, émet un signal SSE, et le Mac B
la récupère et l'installe automatiquement. ✅

---

## Installer le serveur (NAS / Docker)

L'image serveur est **multi-arch** (amd64 + arm64), publiée sur
`ghcr.io/leodurandfr/fontsync`. Déploiement en un conteneur :

```bash
# 1. Générer un token d'instance
openssl rand -base64 32          # → à mettre dans un fichier .env : FONTSYNC_TOKEN=...
# 2. Démarrer (exemple NAS fourni)
docker compose -f docker-compose.nas.yml up -d
```

Les migrations de schéma s'appliquent automatiquement au démarrage. Guide
détaillé (Synology Container Manager, variables, volumes, **sauvegarde &
restauration**) : [`docs/INSTALL-NAS.md`](docs/INSTALL-NAS.md).

## Installer l'agent (app Mac)

L'agent de synchronisation est **embarqué dans l'app Mac** (menu bar, signée et
notarisée) : il n'y a **rien à installer séparément**.

1. Téléchargez le `.dmg` depuis les
   [GitHub Releases](https://github.com/leodurand/FontSync/releases/latest).
2. Glissez **FontSync** dans `Applications`, lancez-le.
3. L'**assistant de premier lancement** (URL + token → test → installation de
   l'agent → première sync) fait le reste. Vous pouvez le relancer à tout moment
   depuis le menu (« Assistant de configuration… »).

L'app met à jour l'agent et se met à jour elle-même automatiquement (Sparkle).
Préférences, statut, « Synchroniser maintenant » et journaux sont accessibles
depuis le menu de la barre des menus.

> Un canal **Homebrew CLI** pour les serveurs headless / power users est prévu
> (optionnel, cf. `PLAN-PUBLICATION.md` P5).

---

## Transport & sécurité réseau

FontSync écoute en **HTTP clair** (le conteneur expose le port `8000`, mappé sur
`8080` dans le `docker-compose` d'exemple). C'est le mode prévu pour un **réseau
local de confiance** (LAN domestique, VLAN d'un NAS) : simple, sans certificat à
gérer.

L'accès est protégé par un **token partagé d'instance** (`FONTSYNC_TOKEN`, voir
plus bas), mais ce token transite **en clair** sur une connexion HTTP — lisible
par quiconque sur le chemin réseau.

> ⚠️ **N'exposez jamais FontSync directement sur Internet en HTTP.** Sur un réseau
> non maîtrisé, placez **toujours** un reverse-proxy TLS devant le serveur : le
> token et tout le trafic doivent voyager chiffrés. C'est la voie standard sur un
> NAS (Synology, etc.).

### Le token d'instance (`FONTSYNC_TOKEN`)

Le token protège tout `/api/*`, le flux SSE (`/api/agent/<device>/events`) et les
WebSocket (`/ws/*`). Définissez-le via l'environnement du conteneur :

```yaml
environment:
  FONTSYNC_TOKEN: "<un secret long et aléatoire>"
```

S'il n'est **pas** défini, le serveur en **génère un au démarrage et le loggue**
(à récupérer dans les logs du conteneur) — jamais de serveur ouvert par défaut. Le
navigateur le demande au premier accès et le mémorise (`localStorage`) ; l'agent le
lit depuis sa config (`server.token`). Pour le générer :

```bash
openssl rand -base64 32
# ou : python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Reverse-proxy TLS — Caddy

Caddy obtient et renouvelle le certificat automatiquement (Let's Encrypt) et relaie
nativement WebSocket et SSE — aucune configuration supplémentaire :

```caddy
fontsync.example.com {
    reverse_proxy localhost:8080
}
```

### Reverse-proxy TLS — nginx

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name fontsync.example.com;

    ssl_certificate     /etc/letsencrypt/live/fontsync.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/fontsync.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket (/ws/*) + SSE (/api/agent/<device>/events)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        # SSE : pas de bufferisation, connexions longues
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

Une fois derrière TLS, pointez le navigateur et l'agent sur
`https://fontsync.example.com` : les WebSocket basculent automatiquement en `wss://`.

---

## Dépannage

| Symptôme | Cause probable / solution |
|---|---|
| **« Token invalide » dans l'app** | URL ou token incorrect. Re-testez la connexion dans Préférences ; comparez avec `FONTSYNC_TOKEN` (ou le token loggé au démarrage du conteneur). |
| **« Serveur injoignable »** | Mauvaise URL/port, conteneur arrêté, ou pare-feu. Vérifiez `docker compose ps` et que `http://<hôte>:8080/health` répond. |
| **Les polices ne se synchronisent pas** | L'agent n'est pas chargé. Menu → « Assistant de configuration… » → réinstaller l'agent, ou « Synchroniser maintenant ». Logs : menu → « Ouvrir les journaux » (`~/Library/Logs/FontSync/`). |
| **Une police n'apparaît pas sur l'autre Mac** | Attendez la prochaine sync (filet de sécurité `StartInterval`) ou forcez-la via « Synchroniser maintenant ». Les `.woff`/`.woff2` sont stockés et prévisualisables mais **jamais installés** au niveau système. |
| **App « non identifiée » au 1er lancement** | Téléchargez le `.dmg` officiel signé/notarisé depuis les Releases. En dernier recours : clic droit → « Ouvrir ». |
| **`unable to open database file` au boot serveur** | Le volume DB n'est pas monté en écriture. Vérifiez le volume `db:/data` du compose. |

Le serveur expose `GET /health` (non authentifié) pour les sondes ; tout le reste
de `/api/*` exige le token.

---

## Développement

```bash
docker compose up -d                                   # serveur + dépendances
docker compose exec fontsync alembic upgrade head      # migrations
docker compose exec fontsync pytest tests/backend/ -v  # tests backend
cd frontend && npm run dev                             # UI web en dev
```

L'app Mac vit dans [`macos-app/`](macos-app/) (procédure de release :
[`macos-app/RELEASE.md`](macos-app/RELEASE.md)). Les conventions de code et la
structure du projet sont décrites dans [`CLAUDE.md`](CLAUDE.md).

---

## Licence

FontSync est distribué sous **GNU Affero General Public License v3.0 ou ultérieure**
(AGPL-3.0-or-later) — voir [`LICENSE`](LICENSE).

L'AGPL garantit que la version **self-hosted reste libre et gratuite** : quiconque
exécute une version modifiée comme service réseau doit en publier les sources
(copyleft réseau, §13). C'est le modèle des projets « self-host gratuit + cloud
payant » comme Plausible et Cal.com.

Le détenteur du copyright (Leo Durand) conserve l'intégralité des droits et se
réserve la possibilité de proposer des **licences commerciales** et d'opérer un
service cloud — l'AGPL ne lie pas l'auteur. Pour préserver cette faculté, les
contributions externes sont acceptées sous **DCO** (`Signed-off-by`), garantissant
que l'auteur peut continuer à relicencier le projet.

```
Copyright (C) 2026 Leo Durand
This program is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version.
```
