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

## 2. Simulate multiple machines

`scripts/dev/run-agent.sh <profile> <command>` runs the agent under an isolated
device **profile** (`A`, `B`, …). Each profile has, under `.dev/<profile>/`:

- its own state (config + hash cache + `disabled/`);
- its own fonts folder (`.dev/<profile>/fonts`);
- a **distinct hostname** → the server sees it as a separate device
  (registration is an upsert by hostname).

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
# Off loopback the script refuses the public `fontsync-dev` token and prints a
# random one instead: give it to the 2nd Mac's agent below.
```

macOS may ask you to allow incoming connections → accept.

**On the 2nd Mac (client):**

```bash
git clone <repo> FontSync && cd FontSync
python3 -m venv .venv && .venv/bin/pip install -e .   # provides `fontsync-agent`
mkdir -p ~/.fontsync && cat > ~/.fontsync/config.yaml <<YAML
server:
  url: http://192.0.2.172:8080        # tailnet (or LAN) IP of the 1st Mac
  token: <token printed by run-server.sh>   # random token of that session
  device_id: null
scan:
  directories: ['~/Library/Fonts', '/Library/Fonts']
  ignore_patterns: ['.*', 'System*']
sync:
  auto_push: true
  auto_pull: true
YAML
.venv/bin/fontsync-agent sync          # pushes its fonts + pulls the server's
.venv/bin/fontsync-agent listen        # (optional) real-time reactive sync
```

You'll see both Macs appear in the **Devices** tab, and the fonts from
one Mac propagate to the other.

> The real prod target remains the **NAS** as a permanent server (both Macs
> point to it). But until the reworked backend is deployed to the
> NAS, test with this Mac as the LAN server — otherwise you'd be exercising the old
> server code.

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

## Backing up production

`scripts/backup-prod.sh` runs **on the NAS, as root**. Two halves, two regimes:
a timestamped snapshot of the database (rotated, `KEEP=14` by default) and an
incremental rsync mirror of the font blobs.

```bash
scp -P <ssh-port> scripts/backup-prod.sh <user>@<nas>:/volume1/docker/fontsync/
ssh -p <ssh-port> <user>@<nas>
sudo bash /volume1/docker/fontsync/backup-prod.sh --db-only
```

The file has to be *placed* on the NAS, not piped: `sudo` asks for a password
there, and with the script on standard input there is no terminal left to type it
on. Docker also lives in `/usr/local/bin`, which DSM leaves out of the PATH of a
non-interactive SSH shell — the script puts it back itself.

The database goes through `sqlite3.Connection.backup` **inside the container**,
never through a file copy: the database runs in WAL mode, so copying the `.db`
alone yields an invalid backup — the latest transactions live in the `-wal`
beside it. The copy is checked with `PRAGMA integrity_check` before it leaves the
container. The blob mirror never deletes (`rsync` without `--delete`): emptying
the trash in production must not propagate to the backup.

The script's footer carries the two scheduled tasks to create (daily for the
database, weekly for the blobs) and the restore procedure — including the part
that is easy to get wrong: **delete `fontsync.db-wal` and `fontsync.db-shm`
before putting a snapshot back**, and keep the agents off while auditing the
trash, since an older database re-activates fonts deleted since and `auto_pull`
would reinstall them.

Schedule it through **DSM → Task Scheduler**, as root, not by hand-editing
`/etc/crontab`: DSM materialises its own tasks into that file and rewrites it, so
a hand-added line disappears silently. A backup that quietly stops is worse than
no backup — you think you have a net.
