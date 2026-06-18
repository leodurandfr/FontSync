# FontSync

Font manager **self-hosted** avec synchronisation multi-machines en temps réel :
un serveur Docker centralise la bibliothèque de polices, un agent Python détecte et
synchronise automatiquement les fonts entre machines, une interface web permet de
naviguer et gérer la collection.

> ℹ️ README minimal (mention de licence — P0.1). Le quickstart public complet
> « 2 machines » arrive en **P4.2** (cf. `PLAN-PUBLICATION.md`). Voir `SPECS.md`
> pour la vision produit et l'architecture.

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
