# FontSync — Roadmap (vision long terme)

> **Statut : orientant, non-actionable.** Ce fichier capture les décisions de *cap*
> produit/archi au-delà de la refonte en cours. Il n'est **pas** une checklist
> exécutable. Le plan actif reste `PLAN.md` (finir A/B/C). Chaque initiative
> ci-dessous deviendra son propre `PLAN-xxx.md` **au moment où on l'attaquera**,
> pas avant (découper avant d'exécuter = des docs qui dérivent).

---

## Différenciateur central

Le vrai avantage vs la concurrence (ex. **FontCap**) = **le self-host léger et réel.**
FontCap se dit « self-hostable » mais c'est en fait du **BYO-cloud** : chaque
utilisateur doit provisionner *son propre* Supabase + *son propre* Cloudflare R2
(tiers gratuits) et câbler ~7 clés API. Il n'y a **aucun serveur central** et
**aucune offre cloud payante** — l'archi BYO-cloud l'interdit par conception.

Toute décision de cap doit **protéger** cet atout : démarrage en une commande,
données chez l'utilisateur, zéro dépendance à un SaaS tiers.

---

## Décisions de cap

### 1. Modèle de distribution : self-hosted (gratuit) **ou** cloud (payant)

Deux modes, **un seul cœur de code** (jamais de fork) :

- **Self-hosted — gratuit.** Vrai self-host sur le matériel de l'utilisateur
  (NAS), pas du BYO-cloud. Cible : `docker compose up` → un seul conteneur
  **FastAPI + SQLite** + storage filesystem. Données 100 % chez l'utilisateur,
  fonctionne en LAN/hors-ligne. C'est l'argument que FontCap n'a pas.
- **Cloud — payant.** Même app FastAPI, hébergée par nous. On échange
  SQLite→Postgres (SQLAlchemy abstrait déjà) et storage local→S3/R2 (abstraction
  storage déjà en place), on active le multi-tenant. **On vend la commodité**
  (pas de NAS, backups, fiabilité, volumes), pas des fonctionnalités amputées au
  self-host. Contrairement à FontCap, ce mode est *possible* parce qu'on héberge
  réellement — eux ne le peuvent pas.

### 2. Backend : garder FastAPI + SQLite/Postgres — **pas Supabase**

Supabase tuerait le différenciateur self-host (stack lourde à faire tourner sur
un NAS vs un seul conteneur) et coupler à un vendeur. Notre backend n'est pas du
CRUD : parsing fonttools, pipeline d'import idempotent, regroupement de familles,
sémantique de delta-sync = vraie logique serveur. L'archi anticipe déjà le
dual-mode (types SQLAlchemy portables, storage FS/S3, Postgres flaggé Phase 7).
RLS n'est **pas** exclusif à Supabase : c'est une feature Postgres réutilisable.

### 3. Cross-platform : Windows + Linux via une frontière `PlatformAdapter`

Le cœur agent (`sync_command`, `hashing`, delta, client HTTP, cache) est déjà
platform-agnostique. Le macOS-spécifique est isolé dans 3 endroits :
`discovery.py` (pyobjc/Core Text → dossiers de fonts par OS), `font_installer.py`
(Windows : registre + `AddFontResource` ; Linux : copie + `fc-cache`), et
`agent/launchd/` (le plus pénible : launchd → Windows Task Scheduler, Linux
systemd user units + path units). **Poser l'abstraction `PlatformAdapter`
(discover / install / uninstall / schedule) tôt**, même avec une seule implé
macOS — l'ajouter après coup est douloureux.

### 4. Authentification : décider la **tenancy** tôt, provider pluggable

Le piège n'est pas le *comment* mais le *quand* : ajouter un `account_id` sur un
schéma mono-utilisateur déjà peuplé est un refacto très coûteux. → **Décider la
frontière de tenancy (`account_id` partout) tôt**, même si le self-host MVP a un
compte implicite unique. **Découpler « provider d'auth » de « plateforme »** :
adopter un provider managé léger (WorkOS, Clerk, Authentik, ou Supabase Auth
*seul*) sans adopter toute une plateforme. Deux postures : self-host = auth
simple/optionnelle (mot de passe admin, voire rien sur LAN) ; cloud = vrai IdP.
*(Deviendra `PLAN-auth.md` quand on l'attaquera.)*

### 5. UI : pur localhost-web, **anti-Electron**

Modèle Syncthing : l'agent sert son UI sur `localhost`, le frontend est une web
app, **zéro fenêtre native**. C'est paradoxalement le plus natif possible (aucun
moteur de rendu embarqué, le navigateur de l'OS fait le travail, cross-platform
gratuit). Si un jour un tray/menubar est nécessaire : **Tauri** (webview système,
pas Electron) — mais à différer.

### 6. Licence : à trancher **avant le premier release public**

Décision business la plus irréversible. Le combo « self-host gratuit + cloud
payant » se protège quasi toujours en **AGPL** (Plausible, Cal.com) ou
source-available **BSL** (Sentry), pour empêcher un concurrent de revendre notre
propre cloud. À arbitrer tôt.

---

## Référence concurrente

- **FontCap** (`github.com/pallestcyer/FontCap`) — même pitch produit, exécution
  opposée : Electron + React, Supabase + Cloudflare R2, **BYO-cloud** (pas de vrai
  self-host, pas de cloud payant). Utile comme **référence UX** (dashboard
  multi-devices, flux « one-click install ») pour la Phase C frontend.
