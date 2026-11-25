# FontSync — Testing locally (without a NAS)

This guide explains how to run **the server and clients locally**,
on a single Mac, without ever pushing to the NAS or touching your real
`~/Library/Fonts`.

Architecture reminder: the **server is the source of truth**, the **agent is
stateless** (each `sync` restarts from the real state of the disk). A "machine B"
is therefore nothing more than **a 2nd device_id + an isolated fonts folder** that
points to the same server — all of which fits on a single machine.

> A 2nd physical Mac is only useful **once**, as a final smoke test
> before publishing (real Core Text discovery + launchd + font activation
> in apps). Not for day-to-day dev.

## Prerequisites

A virtualenv with the backend **and** agent deps:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r agent/requirements.txt
```

## 1. Start the server

Two options, your choice:

```bash
# A) Host (fastest loop, hot reload, disposable SQLite in .dev/):
scripts/dev/run-server.sh

# B) Near-prod (Docker):
docker compose up
```

With option A, a fresh `.dev/` database gets a **dev administrator account**:
`dev@example.com` / `fontsync-dev-password` (override with
`FONTSYNC_DEV_EMAIL` / `FONTSYNC_DEV_PASSWORD`). Sign in to the web interface
with it; the dev agents (`run-agent.sh`) sign in with it on their own.

### Server + frontend in one command ("dev:full")

To start **server + frontend** together (Ctrl-C stops both):

```bash
scripts/dev/up.sh
# or, from frontend/:
npm run dev:full
```

> The agent is intentionally not included: it is one-shot (`sync`) or per-device
> (`listen`). The client side always goes through `run-agent.sh` / `demo.sh`
> (steps 2-4).

Both expose the server on **http://localhost:8080** — which is already the
agent's default (`server.url` in the config). Check:

```bash
curl http://localhost:8080/health   # → {"status":"ok"}
```

The interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are **off by
default** (they map the whole API surface for anyone who can reach the server).
Turn them on for development only:

```bash
FONTSYNC_API_DOCS=true scripts/dev/run-server.sh   # → http://localhost:8080/docs
```

## 2. Simulate multiple machines

`scripts/dev/run-agent.sh <profile> <command>` runs the agent under an isolated
device **profile** (`A`, `B`, …). Each profile has, under `.dev/<profile>/`:

- its own state (config + hash cache + `disabled/`);
- its own fonts folder (`.dev/<profile>/fonts`);
- a **distinct hostname** → the server sees it as a separate device
  (registration is an upsert by hostname);
- its own device session: on first use, the profile signs in with the dev
  account (`run-agent.sh A login` to sign it in again by hand).

This relies on environment variables that are neutral in production
(resolved in [`agent/paths.py`](agent/paths.py) and `agent/config.py`):

| Variable              | Role                                            |
|-----------------------|-------------------------------------------------|
| `FONTSYNC_HOME`       | state folder (instead of `~/.fontsync`)         |
| `FONTSYNC_FONTS_DIR`  | install folder (instead of `~/Library/Fonts`)   |
| `FONTSYNC_DISCOVERY`  | `directories` → scan the isolated folder, not Core Text |
| `FONTSYNC_HOSTNAME`   | hostname (server upsert key)                    |
| `FONTSYNC_DEVICE_NAME`| device display name                             |

## 3. End-to-end demo

```bash
# Server started (step 1), then:
scripts/dev/demo.sh
```

The script: seeds a font on device A → `sync A` (push) →
`sync B` (pull + install) → checks that the font arrived on B. This is the
proof that the **A → server → B** loop works.

Manually, step by step:

```bash
# Drop a test font on A (generates a real, valid TTF):
.venv/bin/python scripts/dev/seed-font.py .dev/A/fonts --family "Inter" --style Regular

scripts/dev/run-agent.sh A sync     # A pushes to the server
scripts/dev/run-agent.sh B sync     # B pulls + installs into .dev/B/fonts
ls .dev/B/fonts                      # → the font is there
```

## 4. Test reactive sync (SSE)

`listen` opens an SSE stream and re-runs `sync` on each server signal:

```bash
scripts/dev/run-agent.sh B listen     # leave running in one terminal
# in another terminal, push a new font on A:
.venv/bin/python scripts/dev/seed-font.py .dev/A/fonts --family "Roboto" --style Bold
scripts/dev/run-agent.sh A sync
# → B receives the SSE signal and automatically installs the new font
```

## 5. Frontend (optional)

```bash
cd frontend && npm install && npm run dev   # proxies to localhost:8080
```

## 6. Testing with a real 2nd Mac

> ⚠️ **Never on a production agent Mac.** The steps below overwrite
> `~/.fontsync/config.yaml` (server, device token, `device_id`) and, with `auto_pull`,
> install fonts into `~/Library/Fonts`: on a Mac that syncs with the production
> server, that replaces its configuration and touches its real fonts. Use a
> **dedicated macOS account** (e.g. `fontsync-e2e`) on each Mac, pointed at a
> test server.

For a full-scale test (real Core Text discovery, real system installation,
launchd), both Macs need to talk to the **same server**. The simplest approach:
this Mac acts as the server on the LAN, and the other Mac connects its agent to it.

> ⚠️ In real mode, `auto_pull: true` **actually installs** the received fonts into
> the 2nd Mac's `~/Library/Fonts` (that's the product behavior). Reversible: the
> files stay on the server, and the agent can uninstall.

**On this Mac (server, reachable from the 2nd Mac):**

```bash
tailscale ip -4                     # this Mac's tailnet IP (or LAN IP: `ipconfig getifaddr en0`)
HOST=<tailnet IP> scripts/dev/run-server.sh   # reuses the already-populated .dev/ database
# Off loopback the dev account (dev@example.com) never keeps the public
# password: the script prints a random one for this session, to type on the
# 2nd Mac below.
```

macOS may ask you to allow incoming connections → accept.

**On the 2nd Mac (client):**

```bash
git clone <repo> FontSync && cd FontSync
python3 -m venv .venv && .venv/bin/pip install -e .   # provides `fontsync-agent`
mkdir -p ~/.fontsync && cat > ~/.fontsync/config.yaml <<YAML
server:
  url: http://192.0.2.172:8080        # tailnet (or LAN) IP of the 1st Mac
  device_id: null
scan:
  directories: ['~/Library/Fonts', '/Library/Fonts']
  ignore_patterns: ['.*', 'System*']
sync:
  auto_push: true
  auto_pull: true
YAML
.venv/bin/fontsync-agent login --email dev@example.com   # password printed by run-server.sh
.venv/bin/fontsync-agent sync          # pushes its fonts + pulls the server's
.venv/bin/fontsync-agent listen        # (optional) real-time reactive sync
```

You'll see both Macs appear in the **Devices** tab, and the fonts from
one Mac propagate to the other.

> In production both Macs point to the permanent server (see *Deploying the
> reference instance* below). This section is for testing a branch that is not
> deployed yet, with this Mac as the server.

## Continuous integration and image builds

`.github/workflows/ci.yml` runs on every push and pull request: `ruff check`,
`ruff format --check` and `pytest tests/` (Linux, so the Core Text tests are
skipped), then `npm ci`, `npm run build` (vue-tsc strict) and `npm test` in
`frontend/`. Run the same locally before pushing:

```bash
.venv/bin/pip install -r requirements-dev.txt -e .
.venv/bin/ruff check backend agent tests && .venv/bin/pytest tests/ -q
cd frontend && npm run build && npm test
```

`docker-publish.yml` calls `ci.yml` first: no image is pushed unless the tests
pass on the same commit. A `v*` tag publishes a release image; a manual
dispatch publishes an image tagged with the branch name. **Dispatch only from
`main`** (`gh workflow run docker-publish.yml --ref main`): that `:main` image
is what the server's **Update** button (Settings → Server) installs. A dispatch
from another branch builds a test image the button never picks up.

## Resetting

All local dev state lives in `.dev/` (gitignored). To start fresh:

```bash
rm -rf .dev
```

## Deploying the reference instance

The reference instance runs the image that CI publishes (`docker-publish.yml`),
**pinned by digest** — never a moving tag, so what runs is exactly what was
tested, and going back means naming the previous digest. One deployment:

1. **Test first**: `pytest tests/ -q`, `npm run build` (vue-tsc), then the same
   digest on a staging copy of the production database (a restored backup, never
   the live volumes).
2. **Back up** right before (database snapshot + checked copy off the server,
   see *Backing up production* and [docs/INSTALL-NAS.md](docs/INSTALL-NAS.md) §5).
3. **Deploy**: set the new digest in the server's compose file and
   `docker compose up -d` (the entrypoint applies Alembic migrations).
4. **Check** that `/api/system/info` reports the new version, and that `/health`,
   `/api/stats`, the trash and its `pendingConfirmation` count did not move
   because of the deployment. Watch for a while before calling it done.
5. **Going back**: the previous digest, as long as no migration ran; after a
   migration the old image refuses the newer schema, so going back means a
   restore — follow [docs/INSTALL-NAS.md](docs/INSTALL-NAS.md) §5 *Roll back an
   update* (`scripts/restore-from-backup.sh`; the server also keeps an automatic
   `pre-migrate-*.db` snapshot).

The digest is in the `docker-publish.yml` run log, or from the immutable tag:
`docker buildx imagetools inspect ghcr.io/<owner>/<repo>:sha-<short-sha>`. An
instance pinned by digest ignores the **Update** button (Watchtower follows
`:main`): on the reference instance, updates go through the steps above.

## Backing up production

`scripts/backup-prod.sh` runs **on the NAS, as root**. Two halves, two regimes:
a timestamped snapshot of the database (rotated, `KEEP=14` by default) and an
incremental rsync mirror of the font blobs.

```bash
COPYFILE_DISABLE=1 tar czf - -C scripts backup-prod.sh | ssh -p <ssh-port> <user>@<nas> 'tar xzf - -C /volume1/docker/fontsync'
ssh -p <ssh-port> <user>@<nas>
sudo bash /volume1/docker/fontsync/backup-prod.sh --db-only
```

The file has to be *placed* on the NAS, not piped into `bash -s`: `sudo` asks
for a password there, and with the script on standard input there is no terminal
left to type it on. `scp` fails against this NAS; the `tar` pipe above places it.
Docker also lives in `/usr/local/bin`, which DSM leaves out of the PATH of a
non-interactive SSH shell — the script puts it back itself.

The database goes through `sqlite3.Connection.backup` **inside the container**,
never through a file copy: the database runs in WAL mode, so copying the `.db`
alone yields an invalid backup — the latest transactions live in the `-wal`
beside it. The copy is checked with `PRAGMA integrity_check` before it leaves the
container. The blob mirror never deletes (`rsync` without `--delete`): emptying
the trash in production must not propagate to the backup.

With `BACKUP_DIR` set (the default in `docker-compose.nas.yml`), the server
already takes these backups by itself; this script is for a one-off copy or an
export outside the Docker volumes. Restoring is not done by hand from here:
follow [docs/INSTALL-NAS.md](docs/INSTALL-NAS.md) §5
(`scripts/restore-from-backup.sh`).

Scheduling the script as well is **optional**. If you do, use **DSM → Task
Scheduler**, as root, not a hand-edited `/etc/crontab`: DSM materialises its own
tasks into that file and rewrites it, so a hand-added line disappears silently. A
backup that quietly stops is worse than no backup — you think you have a net.
