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
| `TRASH_RETENTION_DAYS` | Auto-empty the trash after N days. `0` = never (default). Emptying deletes the **files** (the fonts can no longer be restored, only re-uploaded): leave it at `0` unless you want that to happen on its own | `0`                                     |
| `TOMBSTONE_HARVEST_ENABLED` | Lets the server delete, for good, the database rows of emptied fonts once every guard holds — to keep the database lean; only their hash is kept, so they never come back by themselves, but they can no longer be seen or restored (only re-uploaded). `false` = never (default) | `false` |
| `TOMBSTONE_HARVEST_GRACE_HOURS` | With the harvest on: how long a row waits, after it qualifies, before it is deleted — a Mac whose declaration missed the file once gets to declare it again. Default `24` | `24` |
| `TOMBSTONE_HARVEST_MAX_PER_PASS` | With the harvest on: at most this many rows deleted per sync. Default `5` | `5` |
| `WATCHTOWER_TOKEN`  | Shared secret for the update button (see §4)       | output of `openssl rand -base64 32`           |
| `WATCHTOWER_URL`    | Where the update request goes; already set by the compose file | `http://watchtower:8080`          |
| `BACKUP_DIR`        | Enables automatic backups (§5), written here. Empty = disabled | `/backups`                        |
| `ALLOWED_HOSTS`     | Extra host names accepted in the `Host` header (comma-separated, `*.suffix` allowed). `*` disables the check | `nas.home.lan,*.example.com` |
| `DEVICE_OVERDUE_MINUTES` | A device whose agent has not synced for this long is flagged "overdue" in Settings → Devices, even when connected. Default `30` (3 × the agent's 600 s interval) | `30` |

> If `FONTSYNC_TOKEN` is left empty, the server **generates** a token at
> startup and **logs** it (never an open server by default). The example
> compose makes it **mandatory** to prevent it from changing at every
> restart.

> **Host check (DNS rebinding protection).** The server answers only when the
> `Host` header is an IP address, `localhost`, a `*.local` name or a Tailscale
> `*.ts.net` name. Any other name — a custom domain, a reverse proxy name, a
> router-provided name like `nas.home.lan`, a single-label name like `nas` —
> gets **HTTP 400 "Invalid Host header"** (a WebSocket handshake is refused
> with HTTP 403) until it is added to `ALLOWED_HOSTS`. List **names without
> port**, comma-separated; `*.example.com` matches subdomains only, not
> `example.com` itself. The example compose passes `ALLOWED_HOSTS` from your
> `.env` to the container. Setting `ALLOWED_HOSTS=*` disables the check
> entirely (not recommended).

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
idempotent — no effect if the schema is already up to date. When a migration
is pending, the container first writes a `pre-migrate-<revision>-<date>.db`
snapshot into `/backups` — the way back if the update goes wrong (§5, Roll
back an update).

> Pin a version tag (`:1.0.0`) rather than `:latest` if you want to
> control when updates happen.

### From the web interface

**Settings → Server** shows the running version and, when it is set up, an
**Update** button — nothing to do beyond the `WATCHTOWER_TOKEN` from §1.

Before clicking it, note the image you are running, so you can come back to
it: `docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
fontsync` gives its commit; every published build also carries an immutable
`sha-<7 characters>` tag. Rolling back is pinning that
tag (or the digest) in the `image:` line — plus restoring the pre-migration
snapshot if the update migrated the database: see §5, Roll back an update.

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
**Settings → Server** shows the latest snapshot and the last mirror pass, and
warns when no snapshot is younger than 36 h, when the last backup failed, or
when fonts could not be mirrored (same data: `GET /api/system/backups`).
Inspect what's there with `docker compose -f docker-compose.nas.yml exec
fontsync ls -la /backups /backups/fonts`.

It protects against a bad migration, a mistaken trash emptying or a damaged
database — **not against losing the NAS**: `/backups` sits on the same disks
as the data. Copy it elsewhere as well (Hyper Backup, `rclone`, an external
drive). The two methods below are for a **one-off** manual copy (e.g. right
before a risky operation, or to export a copy to external storage) —
`scripts/backup-prod.sh` in the repo does the same thing as Method B, callable
straight from the NAS shell.

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

### Restore from `/backups` (database snapshot)

Use this after a damaged database, a mistaken mass deletion, or a failed
update. The snapshots are `/backups/fontsync-<date>.db` (daily) and
`/backups/pre-migrate-<revision>-<date>.db` (taken by the container before
every schema migration; after a failed update, take the **first** one written
since the update).

**With the script** (recommended) — on the NAS, as root, in the folder of the
compose file. Copy it there once from a checkout of the repository (`scp`
does not work on DSM; a `tar` pipe does):

```bash
# On your Mac, from the repository
COPYFILE_DISABLE=1 tar czf - scripts/restore-from-backup.sh \
  | ssh -p <ssh-port> <user>@<nas> 'tar xzf - -C <compose-folder>'

# On the NAS, in <compose-folder>
sudo scripts/restore-from-backup.sh fontsync-20261112-030000.db
```

The compose file must point to an image that ships the restore tool (this
version or later): the script needs it for its checks and for the restore
itself. It asks before each step, deletes nothing, and numbers its steps
like this:

1. **Checks**, server still running: docker reachable under `sudo`, the image
   has the restore tool, the snapshot is valid (its schema revision is
   printed). A refusal here changes nothing.
2. **Stop** (`docker compose down`, volumes kept).
3. **Restore**, in a throwaway container: the snapshot is copied and checked;
   **auto-pull and *Propagate deletions* are switched off on every device in
   the restored database** (hidden ones included; previous values saved in
   `/backups/pre-restore-devices-<date>.json`); then `fontsync.db`,
   `fontsync.db-wal` and `fontsync.db-shm` are **moved** into
   `/data/pre-restore-<date>/` (an old `-wal` left in place would replay on
   top of the snapshot and silently undo the restore), next to a copy of the
   restored snapshot, and the prepared copy takes their place. The existing
   daily snapshots are moved into `/backups/pre-restore-<date>/`, out of reach
   of the rotation that runs at every server start. Fonts are copied back from
   `/backups/fonts` without removing anything.
4. **Restart with a maintenance token** (printed once): the script first lets
   you pin the previous image (rollback, see below), shows the image about to
   start, then starts it. The Macs get `401` and write nothing ("invalid
   token" — do not type the maintenance token into the Mac app). If the token
   does not take effect, the script stops the server again.
5. **Audit** in the web interface, with the maintenance token.
6. **Back to the real token**: every service of the compose file restarts with
   `.env`; the script checks that the real token answers and the maintenance
   one is refused.

At every step it writes where things stand, and the exact command to type
next, into `restore-state-<date>.txt` (compose folder, readable by root only),
and prints it if it stops — your answer, an error, a dropped SSH session. Even
a premature `docker compose up -d` after step 3 reinstalls and propagates
nothing, since the restored database has those settings off; it only lets the
Macs reconnect before you have looked.

Then turn auto-pull and propagation back on device by device (Settings →
Devices), after each Mac has synced once and you have looked at the trash.

**What to expect** (measured on a rehearsal, 2026-11-13). Fonts deleted
**after** the snapshot are active again. Those the Macs had removed — deleted
on a Mac, or in the web interface with *Propagate deletions* on — go back to
the trash at each Mac's first sync (to quarantine, waiting for your
confirmation, when many are missing at once); they are **not** reinstalled. A
font deleted in the web interface *without* propagation stays active, since the
Macs still have it — trash it again if needed. Fonts uploaded after the
snapshot are no longer in the library (their files stay in `/fonts`; a Mac
that has them sends them again). After a **mistaken mass deletion**: let each
Mac sync once, restore the fonts from the trash, and only then turn auto-pull
back on to reinstall them — and keep *Propagate deletions* off until the trash
holds only what you mean to delete.

**By hand** — the same steps: `docker compose down`; in the `db` volume,
**move** `fontsync.db`, `fontsync.db-wal` and `fontsync.db-shm` into a
`pre-restore-<date>/` folder (never leave the old `-wal` next to the restored
file, never overwrite the old database), then copy the snapshot in as
`fontsync.db`; copy `/backups/fonts` back into the `fonts` volume without
`--delete`; start with a temporary token — as root on DSM, `env` and the
full path matter: `sudo env FONTSYNC_TOKEN=<temporary> /usr/local/bin/docker
compose -f docker-compose.nas.yml up -d fontsync` (a variable placed before
`sudo` is dropped, and the server would start with the real token); switch
auto-pull and propagation off on every device, audit, then `sudo
/usr/local/bin/docker compose -f docker-compose.nas.yml up -d` with the real
token.

### Restore from archives (methods A/B)

1. `docker compose -f docker-compose.nas.yml down` (without `-v`: keeps the volumes).
2. Move the current content of the `db` volume aside, then restore the
   archives into the `db` and `fonts` volumes (symmetric to method A:
   `tar xzf … -C /data` / `-C /fonts`).
3. Start with a maintenance token and audit as above. At boot, an **older**
   database is migrated forward (after a `pre-migrate` snapshot); a database
   written by a **newer** image is refused — see below.

### Roll back an update

Before any update, note the commit of the running image — every build is also
published under an immutable `sha-<first 7 characters>` tag:

```bash
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' fontsync
```

- **The update ran no migration** (no new `pre-migrate-*` file in
  `/backups`): pin the previous tag in the `image:` line
  (`ghcr.io/<owner>/<repo>:sha-<short>`) and `docker compose -f
  docker-compose.nas.yml up -d`. Done.
- **It did migrate**: run the restore script on the first `pre-migrate-*`
  snapshot written since the update, **with the compose file still on the new
  image** (its checks and restore need it), and pin the previous tag at its
  step 4, just before it restarts the server. Writes made since the
  update are lost — that is what the audit is for.

Images from this version on refuse to start on a database migrated by a newer
image, with a message naming the revision; older images fail in Alembic
("Can't locate revision"). Either way, nothing is changed.

`alembic downgrade` is an alternative only when the migration's `downgrade()`
loses nothing — the release notes say so for each migrating release; read it in
`alembic/versions/` otherwise. Then: keep the new image pinned, `docker compose
-f docker-compose.nas.yml stop fontsync`, copy the `db` volume aside (Method A),
`docker compose -f docker-compose.nas.yml run --rm --entrypoint alembic fontsync
downgrade <previous revision>`, pin the previous tag, `up -d`.

At boot, the container also refuses — with a message saying why — a
half-applied migration it cannot repair safely, and stops after three failed
migration attempts within 24 h instead of taking a snapshot on every restart.

---

## 6. Network exposure

By default, the server listens over **plain HTTP** on the LAN. The token travels in
clear text: **never expose it directly on the Internet**. For remote access,
place a **TLS reverse proxy** (Caddy / nginx) in front — see the
"Transport & network security" section of the [README](../README.md). On Synology, the
built-in **Reverse Proxy** (Control Panel → Application Portal)
does the job, provided you relay WebSocket and SSE.
The name the proxy forwards in `Host` (your domain, or the upstream name
such as `fontsync` if the proxy rewrites it) must be listed in
`ALLOWED_HOSTS` (§3), otherwise every request gets HTTP 400.

### Remote access through Tailscale

A Tailscale sidecar (`tailscale serve` in front of the container) gives you
HTTPS on a `*.ts.net` name, accepted by default by the Host check (§3). Tailscale
node keys **expire** (180 days by default): when the key of the sidecar, of the
NAS or of a Mac running the agent expires, that node silently drops off the
tailnet and the agents lose the server — no data is lost, but nothing syncs
until the node is re-authenticated.

For an always-on server, open the Tailscale admin console → **Machines**, and
choose **Disable key expiry** for the FontSync sidecar, the NAS itself and
every Mac whose agent uses the `*.ts.net` URL. To check from a Mac:

```bash
tailscale status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); \
  [print(p.get("DNSName"), p.get("KeyExpiry", "no expiry")) for p in [d["Self"], *d.get("Peer", {}).values()]]'
```

A node shows `no expiry` once expiry is disabled.

---

## 7. Rotate or revoke the instance token

This procedure is for the NAS install (`docker-compose.nas.yml`, token in
`.env`). Rotate `FONTSYNC_TOKEN` when it may have leaked (pasted in a chat, a
log, a screenshot) or when a machine that knew it is retired. The server
accepts a single token: from the moment the container is recreated with the
new one, every client still holding the old one gets **HTTP 401** (the web
interface and its WebSocket ask for the token again). Plan a few minutes with
all your Macs at hand.

1. **Generate the new token** (keep it out of shell history and of any chat):

   ```bash
   openssl rand -base64 32
   ```

   Rotate `WATCHTOWER_TOKEN` in the same pass if it may have leaked too: the
   same `.env` feeds both the `fontsync` and `watchtower` services.

2. **Back up `.env`**, then edit it next to `docker-compose.nas.yml`:

   ```bash
   cp .env ".env.bak-$(date +%Y%m%d-%H%M%S)"
   # replace the FONTSYNC_TOKEN= (and WATCHTOWER_TOKEN=) value(s)
   ```

3. **Recreate the containers** — `restart` keeps the old environment, only a
   recreation reads the new `.env`:

   ```bash
   docker compose -f docker-compose.nas.yml up -d
   ```

   In Synology Container Manager, change the variable in the project's
   environment, then rebuild the project. With Docker's default log driver,
   the recreated container starts with empty logs: lines written by the old
   one (which may contain the old token in older versions) go away with it.

4. **Check the switch** from any machine on the network, without putting the
   tokens in your shell history. Each `read -rs` waits silently: paste the old
   token (first line) or the new one (second line), then press Enter. Expect
   `401` for the old token, then `200` for the new one.

   ```bash
   read -rs OLD && curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $OLD" http://<nas-ip>:8080/api/stats
   read -rs NEW && curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $NEW" http://<nas-ip>:8080/api/stats
   unset OLD NEW
   ```

   Use the NAS's IP address or `*.local` name: another host name gets HTTP 400
   unless it is listed in `ALLOWED_HOSTS` (§3).

5. **Each Mac with the app**: FontSync menu → **Préférences…** (⌘,) → paste
   the new token → **Enregistrer**, then click **Installer l'agent** again.
   Installing reloads both background jobs; the `listen` job keeps the token
   it read at start-up, so saving alone is not enough. Check that the Mac shows
   **Connected** under Settings → Devices in the web interface (French UI:
   Paramètres → Appareils, « Connecté »).

   **Each Mac with the command-line agent** (Homebrew): edit `server.token` in
   `~/.fontsync/config.yaml`, then run `fontsync-agent setup` (it reloads both
   jobs the same way).

6. **Each browser, and the app's own web window**, asks for the token again on
   its next request: paste the new one.

Revoking without a replacement is the same procedure: every client stays at 401
until it receives the new token.
