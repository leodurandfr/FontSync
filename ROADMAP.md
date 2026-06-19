# FontSync — Roadmap (long-term vision)

> **Status: orienting, non-actionable.** This file captures the product/architecture
> *direction* decisions beyond the shipped version (self-hosted v1, `0.0.1`). It is
> **not** an executable checklist. The current architecture lives in
> [`ARCHITECTURE.md`](ARCHITECTURE.md). Each initiative below will be broken down
> **when we actually tackle it**, not before (breaking it down too early = docs that drift).

---

## Core differentiator

The real advantage vs. the competition (e.g. **FontCap**) = **lightweight, genuine self-hosting.**
FontCap calls itself "self-hostable" but it's actually **BYO-cloud**: every
user must provision *their own* Supabase + *their own* Cloudflare R2
(free tiers) and wire up ~7 API keys. There is **no central server** and
**no paid cloud offering** — the BYO-cloud architecture forbids it by design.

Every direction decision must **protect** this asset: one-command startup, the
user's data on their own hardware, zero dependency on a third-party SaaS.

---

## Direction decisions

### 1. Distribution model: self-hosted (free) **or** cloud (paid)

Two modes, **a single code core** (never a fork):

- **Self-hosted — free.** Genuine self-host on the user's own hardware
  (NAS), not BYO-cloud. Target: `docker compose up` → a single
  **FastAPI + SQLite** container + filesystem storage. Data 100% on the user's
  side, works on LAN/offline. This is the argument FontCap doesn't have.
- **Cloud — paid.** Same FastAPI app, hosted by us. We swap
  SQLite→Postgres (SQLAlchemy already abstracts it) and local storage→S3/R2 (storage
  abstraction already in place), and enable multi-tenancy. **We sell convenience**
  (no NAS, backups, reliability, volumes), not features crippled in
  self-host. Unlike FontCap, this mode is *possible* because we actually host —
  they can't.

### 2. Backend: keep FastAPI + SQLite/Postgres — **not Supabase**

Supabase would kill the self-host differentiator (a heavy stack to run on
a NAS vs. a single container) and couple us to a vendor. Our backend isn't
CRUD: fonttools parsing, idempotent import pipeline, family grouping,
delta-sync semantics = real server logic. The architecture already anticipates
dual-mode (portable SQLAlchemy types, FS/S3 storage, Postgres flagged Phase 7).
RLS is **not** exclusive to Supabase: it's a reusable Postgres feature.

### 3. Cross-platform: Windows + Linux via a `PlatformAdapter` boundary

The agent core (`sync_command`, `hashing`, delta, HTTP client, cache) is already
platform-agnostic. The macOS-specific parts are isolated in 3 places:
`discovery.py` (pyobjc/Core Text → font folders per OS), `font_installer.py`
(Windows: registry + `AddFontResource`; Linux: copy + `fc-cache`), and
`agent/launchd/` (the most painful: launchd → Windows Task Scheduler, Linux
systemd user units + path units). **Lay down the `PlatformAdapter` abstraction
(discover / install / uninstall / schedule) early**, even with a single macOS
implementation — adding it after the fact is painful.

### 4. Authentication: decide **tenancy** early, pluggable provider

The trap isn't the *how* but the *when*: adding an `account_id` to an
already-populated single-user schema is a very costly refactor. → **Decide the
tenancy boundary (`account_id` everywhere) early**, even if the self-host MVP has a
single implicit account. **Decouple "auth provider" from "platform"**:
adopt a lightweight managed provider (WorkOS, Clerk, Authentik, or Supabase Auth
*alone*) without adopting a whole platform. Two stances: self-host = simple/optional
auth (admin password, or even nothing on LAN); cloud = a real IdP.
*(Will become `PLAN-auth.md` when we tackle it.)*

### 5. UI: pure localhost-web, **anti-Electron**

Syncthing model: the agent serves its UI on `localhost`, the frontend is a web
app, **zero native window**. This is paradoxically as native as possible (no
embedded rendering engine, the OS browser does the work, cross-platform for
free). If a tray/menubar is ever needed: **Tauri** (system webview,
not Electron) — but to be deferred.

### 6. License: to be settled **before the first public release**

The most irreversible business decision. The "free self-host + paid cloud"
combo is almost always protected with **AGPL** (Plausible, Cal.com) or
source-available **BSL** (Sentry), to prevent a competitor from reselling our
own cloud. To be settled early.

---

## Competitive reference

- **FontCap** (`github.com/pallestcyer/FontCap`) — same product pitch, opposite
  execution: Electron + React, Supabase + Cloudflare R2, **BYO-cloud** (no genuine
  self-host, no paid cloud). Useful as a **UX reference** (multi-device
  dashboard, "one-click install" flow) for frontend Phase C.
