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

**On this Mac (server, exposed on the LAN):**

```bash
HOST=0.0.0.0 scripts/dev/run-server.sh        # reuses the already-populated .dev/ database
# LAN IP of this Mac: `ipconfig getifaddr en0`  (e.g. 192.168.1.172)
```

macOS may ask you to allow incoming connections → accept.

**On the 2nd Mac (client):**

```bash
git clone <repo> FontSync && cd FontSync
python3 -m venv .venv && .venv/bin/pip install -e .   # provides `fontsync-agent`
mkdir -p ~/.fontsync && cat > ~/.fontsync/config.yaml <<YAML
server:
  url: http://192.168.1.172:8080      # LAN IP of the 1st Mac
  token: <server's FONTSYNC_TOKEN>    # instance token (logged at boot if not set)
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

## Resetting

All local dev state lives in `.dev/` (gitignored). To start fresh:

```bash
rm -rf .dev
```
