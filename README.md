# FontSync

A **self-hosted** font manager with real-time multi-machine synchronization:
a Docker server centralizes your font library, a Python agent automatically detects and
synchronizes fonts across your Macs, and a web interface lets you browse and manage the
collection.

- 🗄️ **Server as source of truth** — all your fonts in one place (NAS, Docker).
- 🔄 **Automatic sync** — the agent watches `~/Library/Fonts` and propagates
  changes in near real time (push/pull + SSE signal).
- 🍎 **Native Mac app** — signed Swift menu bar app, embedded agent, guided first
  launch, notifications, and automatic updates.
- 🌐 **Web UI** — browse, preview, import, and manage the library.
- 🔒 **Instance token** — all of `/api/*` protected by a shared secret.

> For the complete architecture, the data model, and the API, see [`ARCHITECTURE.md`](ARCHITECTURE.md).
> Long-term vision: [`ROADMAP.md`](ROADMAP.md).

## Architecture

```
   Mac (user)                                     FontSync server (NAS, Docker)
 ┌───────────────────────────┐                 ┌──────────────────────────────────┐
 │ FontSync app (menu bar)    │── HTTP+token ──►│ FastAPI + SQLite + storage        │
 │  • status / sync / prefs   │                 │  • /api/* protected by token      │
 │  • webview window ─────────┼─── web UI ─────►│  • serves the web UI (SPA)        │
 │  • manages the agent (launchd) │             │  • SSE “re-sync” → agents         │
 │      │                                       │  • migrations at boot             │
 │      ▼                                       └──────────────────────────────────┘
 │ fontsync-agent (launchd)   │── push/pull ───────────────▲
 │  sync (WatchPaths) + listen (SSE) ───────── signal ──────┘
 └───────────────────────────┘
```

The **server** (always on) is the **source of truth**. The agent is
**stateless**: each `sync` starts over from the actual state of the disk.

---

## “2 machines” quickstart

The goal: one server, two Macs, fonts synchronized between them.

### 1. Start the server (once)

On the NAS (or any Docker host):

```bash
# Generate an instance token and put it in a .env
echo "FONTSYNC_TOKEN=$(openssl rand -base64 32)" > .env

# Fetch the example compose file and start
curl -O https://raw.githubusercontent.com/leodurandfr/FontSync/main/docker-compose.nas.yml
docker compose -f docker-compose.nas.yml up -d
```

The server listens on `http://<host>:8080`. Note its URL and the token: these are the
**only two pieces of information** to enter on each Mac. Detailed NAS guide (Synology,
volumes, backup): [`docs/INSTALL-NAS.md`](docs/INSTALL-NAS.md).

### 2. Configure the **first** Mac

1. Download `FontSync-X.Y.Z.dmg` from the
   [latest release](https://github.com/leodurandfr/FontSync/releases/latest),
   open it, and drag **FontSync** into `Applications`.
2. Launch the app: the icon appears in the menu bar and the **first-launch
   assistant** opens. It guides you through four steps:
   - **Server**: paste the URL (`http://<host>:8080`) and the token, then
     “Test the connection”;
   - **Agent**: “Install the agent” (sets up the launchd jobs that
     watch `~/Library/Fonts`);
   - **First synchronization**: fetches the library from the server;
   - **Done**.
3. Your local fonts are uploaded to the server; check them in the
   “Open FontSync” window (web UI) or via the browser at the server URL.

### 3. Configure the **second** Mac

Repeat step 2 on the second Mac (same URL, same token). On the first sync,
it **fetches** all the fonts already present on the server and installs them.

### 4. Verify real-time synchronization

Add a font to `~/Library/Fonts` on Mac A (or import it from the web
UI): within a few seconds, the server receives it, emits an SSE signal, and Mac B
fetches and installs it automatically. ✅

---

## Install the server (NAS / Docker)

The server image is **multi-arch** (amd64 + arm64), published on
`ghcr.io/leodurandfr/fontsync`. Single-container deployment:

```bash
# 1. Generate an instance token
openssl rand -base64 32          # → put it in a .env file: FONTSYNC_TOKEN=...
# 2. Start (provided NAS example)
docker compose -f docker-compose.nas.yml up -d
```

Schema migrations are applied automatically at startup. Detailed
guide (Synology Container Manager, variables, volumes, **backup &
restore**): [`docs/INSTALL-NAS.md`](docs/INSTALL-NAS.md).

## Install the agent (Mac app)

The synchronization agent is **embedded in the Mac app** (menu bar, signed and
notarized): there is **nothing to install separately**.

1. Download the `.dmg` from the
   [GitHub Releases](https://github.com/leodurandfr/FontSync/releases/latest).
2. Drag **FontSync** into `Applications` and launch it.
3. The **first-launch assistant** (URL + token → test → agent
   installation → first sync) does the rest. You can re-run it at any time
   from the menu (“Setup assistant…”).

The app updates the agent and updates itself automatically (Sparkle).
Preferences, status, “Sync now”, and logs are accessible
from the menu bar menu.

> A **Homebrew CLI** channel for headless servers / power users is
> available (optional): see [`packaging/homebrew/`](packaging/homebrew/).

---

## Network transport & security

FontSync listens over **plain HTTP** (the container exposes port `8000`, mapped to
`8080` in the example `docker-compose`). This is the mode intended for a **trusted
local network** (home LAN, a NAS VLAN): simple, with no certificate to
manage.

Access is protected by a **shared instance token** (`FONTSYNC_TOKEN`, see
below), but this token travels **in the clear** over an HTTP connection — readable
by anyone on the network path.

> ⚠️ **Never expose FontSync directly on the Internet over HTTP.** On an untrusted
> network, **always** place a TLS reverse proxy in front of the server: the
> token and all traffic must travel encrypted. This is the standard approach on a
> NAS (Synology, etc.).

### The instance token (`FONTSYNC_TOKEN`)

The token protects all of `/api/*`, the SSE stream (`/api/agent/<device>/events`), and the
WebSockets (`/ws/*`). Set it via the container’s environment:

```yaml
environment:
  FONTSYNC_TOKEN: "<a long, random secret>"
```

If it is **not** set, the server **generates one at startup and logs it**
(to be retrieved from the container logs) — never an open server by default. The
browser asks for it on first access and remembers it (`localStorage`); the agent
reads it from its config (`server.token`). To generate it:

```bash
openssl rand -base64 32
# or: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### TLS reverse proxy — Caddy

Caddy obtains and renews the certificate automatically (Let's Encrypt) and natively
relays WebSocket and SSE — no additional configuration:

```caddy
fontsync.example.com {
    reverse_proxy localhost:8080
}
```

### TLS reverse proxy — nginx

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

        # SSE: no buffering, long-lived connections
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

Once behind TLS, point the browser and the agent at
`https://fontsync.example.com`: WebSockets switch automatically to `wss://`.

---

## Troubleshooting

| Symptom | Likely cause / solution |
|---|---|
| **“Invalid token” in the app** | Incorrect URL or token. Re-test the connection in Preferences; compare with `FONTSYNC_TOKEN` (or the token logged at container startup). |
| **“Server unreachable”** | Wrong URL/port, container stopped, or firewall. Check `docker compose ps` and that `http://<host>:8080/health` responds. |
| **Fonts don’t sync** | The agent isn’t loaded. Menu → “Setup assistant…” → reinstall the agent, or “Sync now”. Logs: menu → “Open logs” (`~/Library/Logs/FontSync/`). |
| **A font doesn’t appear on the other Mac** | Wait for the next sync (`StartInterval` safety net) or force it via “Sync now”. `.woff`/`.woff2` files are stored and previewable but **never installed** at the system level. |
| **App “unidentified” on first launch** | Download the official signed/notarized `.dmg` from the Releases. As a last resort: right-click → “Open”. |
| **`unable to open database file` at server boot** | The DB volume isn’t mounted as writable. Check the `db:/data` volume in the compose file. |

The server exposes `GET /health` (unauthenticated) for probes; everything else
under `/api/*` requires the token.

---

## Development

```bash
docker compose up -d                                   # server + dependencies
docker compose exec fontsync alembic upgrade head      # migrations
docker compose exec fontsync pytest tests/backend/ -v  # backend tests
cd frontend && npm run dev                             # web UI in dev
```

The Mac app lives in [`macos-app/`](macos-app/) (release procedure:
[`macos-app/RELEASE.md`](macos-app/RELEASE.md)). The code conventions and the
project structure are described in [`CLAUDE.md`](CLAUDE.md).

---

## License

FontSync is distributed under the **GNU Affero General Public License v3.0 or later**
(AGPL-3.0-or-later) — see [`LICENSE`](LICENSE).

The AGPL guarantees that the **self-hosted version stays free and open**: anyone
who runs a modified version as a network service must publish its sources
(network copyleft, §13). This is the model of “free self-host + paid cloud”
projects like Plausible and Cal.com.

The copyright holder (Leo Durand) retains all rights and
reserves the ability to offer **commercial licenses** and to operate a
cloud service — the AGPL does not bind the author. To preserve this ability, external
contributions are accepted under the **DCO** (`Signed-off-by`), guaranteeing
that the author can continue to relicense the project.

```
Copyright (C) 2026 Leo Durand
This program is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version.
```
