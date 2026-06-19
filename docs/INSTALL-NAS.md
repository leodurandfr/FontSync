# Install the FontSync server on a NAS

Installation guide for the FontSync **server** (Docker) on a NAS — Synology
(Container Manager), QNAP (Container Station) or any Docker host. The server is
the **source of truth**: it centralizes the library, serves the web UI and pushes
re-sync signals to the agents. The macOS agent and the menu bar app are installed
separately (see [`../README.md`](../README.md) → "Install the agent").

> The image is **multi-arch** (`linux/amd64` + `linux/arm64`): it runs just as
> well on an x86 NAS (Intel/AMD) as on an ARM NAS (Realtek, Annapurna…). Docker
> automatically selects the right variant.

---

## 1. What you need

- A NAS with Docker (Synology **Container Manager**, QNAP **Container Station**)
  or a host with `docker` + `docker compose`.
- The `8080` port free on the NAS (adjustable).
- An **instance token** (shared secret). Generate it:

  ```bash
  openssl rand -base64 32
  # or: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

The image is published on **GitHub Container Registry**:
`ghcr.io/leodurandfr/fontsync:latest` (or a version tag, e.g. `:1.0.0`).

---

## 2. Installation via docker compose (recommended)

This is the simplest and most reproducible method, including on Synology whose
**Container Manager** can import a compose file ("Project").

1. Create a folder on the NAS, e.g. `docker/fontsync/`.
2. Drop the [`docker-compose.nas.yml`](../docker-compose.nas.yml) file from the repo into it.
3. Next to it, create a **`.env`** file containing your token:

   ```dotenv
   FONTSYNC_TOKEN=paste-the-generated-token-here
   ```

4. Start it:

   ```bash
   docker compose -f docker-compose.nas.yml up -d
   ```

   On first startup, the entrypoint applies the schema migrations
   (`alembic upgrade head`) then starts the server. The SQLite database is created
   automatically in the `db` volume.

5. Open `http://<nas-ip>:8080`. The web UI asks for the token on first access.

### On Synology Container Manager (graphical interface)

1. **Container Manager → Project → Create**.
2. Source: "Create a docker-compose.yml" (paste the content of
   `docker-compose.nas.yml`) or "Import" the file.
3. Fill in the `FONTSYNC_TOKEN` variable (environment tab, or via the
   `.env` placed in the project folder).
4. Start the project. Container Manager creates the `db` and `fonts` volumes.

---

## 3. Variables and volumes

| Env variable        | Role                                              | Example value                                 |
|---------------------|---------------------------------------------------|-----------------------------------------------|
| `FONTSYNC_TOKEN`    | Secret protecting `/api/*`, SSE and WS (**required**) | output of `openssl rand -base64 32`           |
| `DATABASE_URL`      | SQLite URL (async)                                 | `sqlite+aiosqlite:////data/fontsync.db`       |
| `STORAGE_BACKEND`   | Storage backend                                    | `filesystem`                                  |
| `FONT_STORAGE_PATH` | Font files folder                                  | `/fonts`                                       |

> If `FONTSYNC_TOKEN` is left empty, the server **generates** a token at
> startup and **logs** it (never an open server by default). The example
> compose makes it **mandatory** to prevent it from changing at every
> restart.

| Volume  | Mounted on | Content                                         |
|---------|-----------|-------------------------------------------------|
| `db`    | `/data`   | SQLite database: `fontsync.db` (+ `-wal`, `-shm`)  |
| `fonts` | `/fonts`  | Font files (organized by hash prefix) |

These **two** volumes make up the entire state of the server: backing them up
means backing up FontSync (see §5).

---

## 4. Updates

```bash
docker compose -f docker-compose.nas.yml pull
docker compose -f docker-compose.nas.yml up -d
```

At every startup, the entrypoint re-runs `alembic upgrade head`: the schema
migrations are applied automatically, without intervention. `alembic` is
idempotent — no effect if the schema is already up to date.

> Pin a version tag (`:1.0.0`) rather than `:latest` if you want to
> control when updates happen.

---

## 5. Backup & restore

The complete state fits in the **two volumes**: `db` (the database) and `fonts` (the
files). The database is in **WAL** mode: writes may reside in the
`-wal` file not yet merged. A **consistent** copy is therefore required.

### Method A — cold backup (the safest)

Stopping the container guarantees that the WAL is merged and that no write is
in progress:

```bash
docker compose -f docker-compose.nas.yml stop

# Copy the two volumes (Docker paths → tar archives)
docker run --rm \
  -v fontsync_db:/data:ro \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/fontsync-db-$(date +%F).tar.gz -C /data .

docker run --rm \
  -v fontsync_fonts:/fonts:ro \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/fontsync-fonts-$(date +%F).tar.gz -C /fonts .

docker compose -f docker-compose.nas.yml start
```

> The actual volume name is prefixed by the compose project (often
> `fontsync_db` / `fontsync_fonts`). Check with `docker volume ls`.

On Synology, these volumes live under
`/volume1/@docker/volumes/<name>/_data` — you can also include them in a
classic **Hyper Backup** task (ideally with the container stopped).

### Method B — hot backup of the database (container running)

SQLite's `.backup` API produces a consistent copy without stopping the service. The
Python stdlib (already in the image) is enough:

```bash
docker compose -f docker-compose.nas.yml exec fontsync \
  python -c "import sqlite3; src=sqlite3.connect('/data/fontsync.db'); dst=sqlite3.connect('/data/backup.db'); src.backup(dst); dst.close(); src.close()"

# Retrieve the copy out of the container
docker compose -f docker-compose.nas.yml cp fontsync:/data/backup.db ./fontsync-db-$(date +%F).db
docker compose -f docker-compose.nas.yml exec fontsync rm /data/backup.db
```

Back up the `fonts` volume **as well** (the files are not in the database).
While running, a `tar` copy of the `fonts` folder is safe: the files are
write-once (named by hash), never modified in place.

### Restore

1. `docker compose -f docker-compose.nas.yml down` (without `-v`: keeps the volumes).
2. Restore the content of the archives into the `db` and `fonts` volumes
   (symmetric to method A: `tar xzf … -C /data` / `-C /fonts`).
3. `docker compose -f docker-compose.nas.yml up -d`. The migrations
   re-apply at boot if needed.

---

## 6. Network exposure

By default, the server listens over **plain HTTP** on the LAN. The token travels in
clear text: **never expose it directly on the Internet**. For remote access,
place a **TLS reverse proxy** (Caddy / nginx) in front — see the
"Transport & network security" section of the [README](../README.md). On Synology, the
built-in **Reverse Proxy** (Control Panel → Application Portal)
does the job, provided you relay WebSocket and SSE.
