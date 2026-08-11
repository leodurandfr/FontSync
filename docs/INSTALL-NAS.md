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
- Two secrets. Generate each with:

  ```bash
  openssl rand -base64 32
  # or: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

  - `FONTSYNC_TOKEN` — the **instance token**, which protects the whole API.
  - `WATCHTOWER_TOKEN` — used only by the **Update** button in the interface
    (§4). Never leaves the NAS. If you would rather update by hand, delete the
    `watchtower` service from the compose file and this one becomes pointless.

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
   WATCHTOWER_TOKEN=paste-the-second-one-here
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
| `TRASH_RETENTION_DAYS` | Auto-empty the trash after N days. `0` = never (default) | `0`                                     |
| `WATCHTOWER_TOKEN`  | Shared secret for the update button (see §4)       | output of `openssl rand -base64 32`           |
| `WATCHTOWER_URL`    | Where the update request goes; already set by the compose file | `http://watchtower:8080`          |
| `BACKUP_DIR`        | Enables automatic backups (§5), written here. Empty = disabled | `/backups`                        |

> If `FONTSYNC_TOKEN` is left empty, the server **generates** a token at
> startup and **logs** it (never an open server by default). The example
> compose makes it **mandatory** to prevent it from changing at every
> restart.

| Volume  | Mounted on | Content                                         |
|---------|-----------|-------------------------------------------------|
| `db`    | `/data`   | SQLite database: `fontsync.db` (+ `-wal`, `-shm`)  |
| `fonts` | `/fonts`  | Font files (organized by hash prefix) |
| `backups` | `/backups` | Automatic backups (§5) — only used if `BACKUP_DIR` is set |

The **`db`** and **`fonts`** volumes make up the entire state of the server:
backing them up means backing up FontSync (see §5, and `backups` if enabled).

---

## 4. Updates

### By hand

```bash
docker compose -f docker-compose.nas.yml pull
docker compose -f docker-compose.nas.yml up -d
```

At every startup, the entrypoint re-runs `alembic upgrade head`: the schema
migrations are applied automatically, without intervention. `alembic` is
idempotent — no effect if the schema is already up to date.

> Pin a version tag (`:1.0.0`) rather than `:latest` if you want to
> control when updates happen.

### From the web interface

**Settings → Server** shows the running version and, when it is set up, an
**Update** button — nothing to do beyond the `WATCHTOWER_TOKEN` from §1.

The button reaches a **Watchtower** container included in the example compose
file. FontSync itself never touches the Docker socket: a container cannot
replace itself without access to the Docker daemon, and giving FontSync that
access would hand root-equivalent control of the NAS to an application
protected by a single shared token. Watchtower holds that privilege, and only
it. Its API is not published on the LAN — it is reachable only from FontSync,
over the compose network.

Watchtower runs with `--http-api-update` and **without** periodic polling: it
does nothing on its own, and nothing updates behind your back. `--label-enable`
restricts it to containers carrying
`com.centurylinklabs.watchtower.enable=true` — installing FontSync does not
make Watchtower the manager of everything else running on your NAS.

Two things to expect:

- **The page waits, then reconnects.** The update recreates the very container
  serving the interface. The request may die without a reply; that is the
  success case, not a failure. The interface waits for `/health` to come back.
- **Nothing happens if the image has not changed.** The interface then says the
  server is already on the latest published image.

Prefer to keep updates manual? Delete the `watchtower` service and the two
`WATCHTOWER_*` lines from the compose file. The button disappears; the version
is still shown.

---

## 5. Backup & restore

The complete state fits in the **two volumes**: `db` (the database) and `fonts` (the
files). The database is in **WAL** mode: writes may reside in the
`-wal` file not yet merged. A **consistent** copy is therefore required.

### Automatic (built in, on by default in the example compose)

`docker-compose.nas.yml` sets `BACKUP_DIR=/backups`, mounted on a third
volume (`backups`). With it set, the server itself takes care of backups —
no cron job, no NAS Task Scheduler, no `docker exec` from the host:

- a **daily** consistent snapshot of the database (same `sqlite3.backup()`
  API as below, run from inside the process — nothing to merge, nothing to
  stop), rotated to the last 14;
- a **weekly** incremental mirror of the fonts folder (write-once files,
  copies only what's new after the first pass).

Leave `BACKUP_DIR` empty to disable it — a snapshot written without a
mounted volume would just vanish on the next container recreation, silently.
Inspect what's there with `docker compose -f docker-compose.nas.yml exec
fontsync ls -la /backups /backups/fonts`.

This is enough on its own. The two methods below are for a **one-off**
manual copy (e.g. right before a risky operation, or to export a copy to
external storage) — `scripts/backup-prod.sh` in the repo does the same thing
as Method B, callable straight from the NAS shell.

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
