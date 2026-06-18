# FontSync — Checklist de validation end-to-end (P0.2)

> **But (cf. `PLAN-PUBLICATION.md` → P0.2).** Les 99 tests agent tournent sur FS
> isolé / `MockTransport`. Le cœur produit — `push → import serveur → signal SSE →
> pull → install` **entre deux machines réelles** — n'a jamais été validé bout-en-bout.
> Cette checklist le déroule sur **2 Macs + 1 serveur**, avec commandes exactes et
> résultats attendus. **Objectif : trouver les bugs réels avant le packaging.**
>
> ⚠️ **Ne cocher P0.2 dans `PLAN-PUBLICATION.md` qu'après avoir réellement déroulé
> cette checklist et consigné les résultats** (section *Résultat observé* de chaque
> scénario + *Journal des bugs* en fin de fichier). Tant que la colonne « observé »
> est vide, P0.2 n'est pas validé.

---

## Topologie de test

Trois rôles. Idéalement trois machines, mais le **serveur** peut être un NAS
(Docker) **ou** un Mac sur le LAN (mode dev). Si tu n'as que 2 Macs : l'un fait
aussi serveur — mais dans ce cas, fais tourner les scénarios « réception » sur le
**Mac qui n'est pas le serveur** pour rester proche du réel.

| Rôle  | Notation | Quoi                                                            |
|-------|----------|---------------------------------------------------------------|
| Serveur | `[S]`  | FastAPI + SQLite + storage (NAS Docker, ou Mac LAN via dev)    |
| Mac 1 | `[M1]`   | Agent FontSync (launchd : `sync` + `listen`), vrai `~/Library/Fonts` |
| Mac 2 | `[M2]`   | Idem M1, 2ᵉ machine                                            |
| UI    | `[UI]`   | Navigateur sur l'interface web (depuis n'importe quelle machine) |

**Convention :** chaque commande est préfixée par le rôle où l'exécuter.
Remplace `<IP-SERVEUR>` par l'IP LAN du serveur (`[S] ipconfig getifaddr en0`).

---

## Notes techniques à connaître avant de commencer

Ces points conditionnent les résultats attendus — les ignorer fait conclure à tort
à un bug (ou en masque un vrai).

1. **`auto_pull` vaut `false` par défaut** (`agent/config.py` **et**
   `backend/models/device.py` : le serveur fait foi). **Un Mac n'installe rien tant
   que `auto_pull` n'est pas activé pour son device.** On l'active ici dans le
   `config.yaml` *avant le premier `sync`* (valeur envoyée au `register`) **et/ou**
   via l'UI (onglet Appareils). `auto_push` vaut `true` par défaut.
2. **Deux canaux temps réel distincts :**
   - **SSE** `GET /api/agent/{device_id}/events` → signal « re-sync » serveur→agent.
     C'est le **seul** canal que l'agent (`listen`) écoute aujourd'hui.
   - **WebSocket legacy** `/ws/agent/{device_id}` → utilisé par les endpoints
     install/uninstall/activate/deactivate (`ws_manager.send_to_agent`). **L'agent
     refondu ne s'y connecte plus** (cf. `CLAUDE.md` : WS = canal frontend). ⚠️ Voir
     **S3** : les actions UI vers l'agent risquent donc de renvoyer `503`.
3. **L'agent est stateless.** Chaque `sync` repart de l'état réel du disque
   (`~/Library/Fonts`) ; le delta est calculé côté serveur par **hash** seulement
   (`compute_delta`), pas via les associations `device_font`.
4. **Conséquence du point 3 + `auto_pull` :** une font **présente sur le serveur et
   absente du disque** sera (re)pullée au prochain `sync`. C'est central pour
   comprendre S3 (désinstallation) et S8 (soft-delete).
5. **Logs agent (launchd) :** `~/Library/Logs/FontSync/{sync,listen}.{out,err}.log`.
   État des jobs : `fontsync-agent status`.
6. **Découverte = Core Text en premier sur un vrai Mac** (`FONTSYNC_DISCOVERY` non
   défini → `discover_via_core_text`). Conséquences à connaître :
   - `scan.directories` du `config.yaml` n'est qu'un **fallback** (utilisé seulement
     si Core Text ne renvoie rien). Inutile de s'acharner dessus.
   - **Latence de registration :** une font fraîchement déposée dans `~/Library/Fonts`
     peut mettre quelques secondes à être vue par Core Text. Donc un `sync` déclenché
     par WatchPaths peut tourner **avant** que la font soit découvrable. Si un push
     n'a pas lieu, **attendre quelques secondes puis relancer** `fontsync-agent sync`.
   - Core Text émet **une entrée par face** : un `.ttc` à 2 faces compte « 2
     découvertes » dans les logs, mais le serveur dédoublonne par hash (stocké 1 fois).

---

## Légende des statuts

- ☐ non testé  ·  ✅ conforme  ·  ❌ bug (→ noter dans le *Journal des bugs*)  ·  ⚠️ comportement à surveiller / bug suspecté

Remplir la ligne **Résultat observé** à chaque scénario (date + ce qui s'est passé).

---

## Phase 0 — Mise en place

### 0.1 — Lancer le serveur `[S]`

**Option A — Mac sur le LAN (dev, boucle rapide, réutilise `.dev/`) :**

```bash
[S] HOST=0.0.0.0 scripts/dev/run-server.sh
[S] ipconfig getifaddr en0          # → note l'IP, ex. 192.168.1.172
```

> macOS peut demander d'autoriser les connexions entrantes → **accepter**.

**Option B — NAS / proche-prod (Docker) :**

```bash
[S] docker compose up -d
[S] docker compose exec fontsync alembic upgrade head   # si pas fait au boot
```

**Vérification (depuis n'importe quelle machine) :**

```bash
curl http://<IP-SERVEUR>:8080/health      # attendu : {"status":"ok"}
```

- **Résultat attendu :** `{"status":"ok"}`.
- **Résultat observé :** _______________________  Statut : ☐

### 0.2 — Ouvrir l'interface web `[UI]`

- **Docker (Option B)** : le serveur sert le SPA → ouvrir `http://<IP-SERVEUR>:8080`.
- **Dev (Option A)** : lancer Vite sur le Mac serveur et l'utiliser depuis ce Mac :

```bash
[S] cd frontend && npm install && npm run dev   # → http://localhost:8765 (proxy → :8080)
```

- **Résultat attendu :** l'UI charge, bibliothèque vide (ou état connu), onglet **Appareils** visible.
- **Résultat observé :** _______________________  Statut : ☐

### 0.3 — Installer l'agent sur M1 et M2 `[M1]` `[M2]`

Identique sur les deux Macs (cf. `DEVELOPMENT.md` §6). **`auto_pull: true` sur les
deux** pour une propagation bidirectionnelle.

```bash
[M1] git clone <repo> FontSync && cd FontSync
[M1] python3 -m venv .venv && .venv/bin/pip install -e .   # fournit `fontsync-agent`
[M1] mkdir -p ~/.fontsync && cat > ~/.fontsync/config.yaml <<'YAML'
server:
  url: http://<IP-SERVEUR>:8080
  device_token: null
  device_id: null
scan:
  directories:
    - '~/Library/Fonts'
  ignore_patterns:
    - '.*'
    - 'System*'
sync:
  auto_push: true
  auto_pull: true
YAML
```

> Remplace `<IP-SERVEUR>` par l'IP réelle. Répéter **à l'identique sur M2**.

Installer les LaunchAgents (active **WatchPaths** + **listen** + 1er `sync`) :

```bash
[M1] .venv/bin/fontsync-agent setup
[M1] .venv/bin/fontsync-agent status     # attendu : com.fontsync.sync : chargé / com.fontsync.listen : chargé
[M2] .venv/bin/fontsync-agent setup
[M2] .venv/bin/fontsync-agent status
```

- **Résultat attendu :** les deux jobs `chargé` sur chaque Mac ; un 1er `sync`
  s'exécute (voir `~/Library/Logs/FontSync/sync.out.log`).
- **Résultat observé :** _______________________  Statut : ☐

### 0.4 — Vérifier la présence des 2 devices `[UI]`

- **Résultat attendu :** onglet **Appareils** → M1 et M2 listés, marqués **connectés**
  (la présence vient de la connexion SSE `listen`). `auto_pull` activé pour les deux.
- **Résultat observé :** _______________________  Statut : ☐

---

## (Optionnel) Répétition générale en local — `tests/e2e/preflight.sh`

Avant le vrai test 2 Macs, on peut **dérouler à blanc** la plupart des scénarios sur
un seul Mac : un banc complet **serveur (LAN) + frontend + 2 agents `listen`**
(profils isolés `A`/`B`). Ne couvre **pas** ce qui exige un 2ᵉ Mac réel
(découverte Core Text, install système `~/Library/Fonts`, déclenchement launchd
`WatchPaths`), mais valide toute la logique réseau/serveur.

```bash
tests/e2e/preflight.sh        # Ctrl-C pour tout arrêter ; logs sous .dev/e2e/
```

Le script imprime les URLs et les commandes pour poser une font chez A et suivre la
propagation A → serveur → B. Voir l'en-tête du script pour le détail.

---

## Scénarios

### S1 — Push local (WatchPaths) → import serveur → SSE → pull + install

**Objectif :** valider la boucle réactive complète entre deux machines.

**Préconditions :** Phase 0 OK ; `listen` actif sur M2 ; `tail` des logs prêt.

```bash
[M2] tail -f ~/Library/Logs/FontSync/listen.out.log    # observer le signal + sync
# Sur M1, poser une vraie font de test dans ~/Library/Fonts (déclenche WatchPaths) :
[M1] .venv/bin/python scripts/dev/seed-font.py ~/Library/Fonts --family "E2E Inter" --style Regular
```

- **Résultat attendu :**
  1. `[M1]` WatchPaths déclenche `com.fontsync.sync` (`sync.out.log` : « 1 découverte… push: 1 ok »).
  2. `[S]` la font est importée (apparaît dans l'UI, famille « E2E Inter »).
  3. `[S→M2]` un signal SSE `sync` est poussé à M2 (`listen.out.log`).
  4. `[M2]` `listen` relance `sync` → pull + install → `~/Library/Fonts/E2EInter-Regular.ttf` présent.

```bash
[M2] ls ~/Library/Fonts | grep -i E2EInter     # attendu : E2EInter-Regular.ttf
```

- **⚠️ Si rien n'arrive sur M2 :** vérifier `auto_pull` du device M2 (UI Appareils),
  et que `listen` est connecté (UI : M2 « connecté »).
- **⚠️ Latence Core Text (cf. note technique 6) :** si M1 ne pousse pas tout de suite
  (la font vient d'être déposée), patienter quelques secondes puis forcer
  `[M1] .venv/bin/fontsync-agent sync`. Ce point vaut aussi pour **S6/S7/S9** (toute
  font déposée dans `~/Library/Fonts`).
- **Résultat observé :** _______________________  Statut : ☐

---

### S2 — Upload via le frontend → apparition sur les deux machines

**Objectif :** valider le chemin d'entrée « UI → serveur → 2 agents ».

```bash
# Générer un fichier à uploader (sur une machine disposant du venv repo, ex. M1 ;
# un serveur NAS Docker n'a pas de venv) :
[M1] .venv/bin/python scripts/dev/seed-font.py /tmp/e2e --family "E2E Roboto" --style Bold
# → /tmp/e2e/E2ERoboto-Bold.ttf   (récupérer ce fichier sur la machine où s'ouvre l'UI)
```

1. `[UI]` Uploader `E2ERoboto-Bold.ttf` via l'écran d'upload.
2. Observer la propagation vers M1 **et** M2.

- **Résultat attendu (intention produit) :**
  - `[UI]` la font apparaît immédiatement (event WS `font.added` vers le frontend).
  - `[M1]` et `[M2]` : `~/Library/Fonts/E2ERoboto-Bold.ttf` finit par être installé.

- **⚠️ Bug suspecté — à confirmer (même racine que S3) :** `POST /api/fonts/upload`
  **n'émet PAS** de signal SSE « re-sync » : il appelle `broadcast_to_clients`
  (frontend, OK) + `broadcast_to_agents` (**WS legacy, canal mort**), mais **jamais
  `ws_manager.broadcast_sync()`** — contrairement à `/sync/push` (S1) et `/restore`
  (S8). Conséquence probable : **aucune propagation réactive** vers les agents ; la
  font n'arrive qu'au prochain `sync` **périodique** (`StartInterval` ~600 s) ou
  **manuel**. Pour le vérifier vite, forcer un sync :

```bash
[M1] .venv/bin/fontsync-agent sync && ls ~/Library/Fonts | grep -i E2ERoboto
[M2] .venv/bin/fontsync-agent sync && ls ~/Library/Fonts | grep -i E2ERoboto
```

  Noter : la font **arrive-t-elle toute seule** (réactif) ou **seulement après sync
  manuel/périodique** ? Si le second cas → bug à consigner.
- **Résultat observé :** _______________________  Statut : ☐

---

### S3 — Désinstallation explicite depuis le frontend (font reste sur le serveur)

**Objectif :** depuis l'UI, désinstaller une font d'**un** device ; le fichier doit
disparaître **localement** sur ce device mais **rester sur le serveur**.

**Préconditions :** une font installée sur M1 et M2 (ex. « E2E Inter » de S1).

1. `[UI]` Onglet de la font → device **M1** → action **Désinstaller**.
2. Observer M1 et le serveur.

- **Résultat attendu (spec produit) :**
  - `[M1]` `~/Library/Fonts/E2EInter-Regular.ttf` supprimé (uninstall gardé par hash).
  - `[S]` la font **reste** dans la bibliothèque (jamais supprimée du serveur).
  - `[M2]` inchangé.

- **⚠️ Bug suspecté — à confirmer pendant le test :** l'endpoint
  `POST /api/fonts/{id}/uninstall/{device_id}` envoie l'ordre via
  `ws_manager.send_to_agent` (**WebSocket legacy `/ws/agent`**). Or l'agent refondu
  **ne se connecte plus** à ce WS (il n'écoute que la SSE). `send_to_agent` devrait
  donc retourner `False` → **`503 "L'agent n'est pas connecté."`**, et **rien ne se
  passe sur M1**. Idem pour **install / activate / deactivate** (même canal).
  → Si confirmé : **❌ bug bloquant** (tout le canal commande UI→agent est mort
  depuis la bascule SSE). À consigner dans le Journal des bugs.

- **⚠️ Tension `auto_pull` (même si l'uninstall marchait) :** la font restant sur le
  serveur et `auto_pull` étant `true`, le **prochain `sync` de M1 la ré-installerait**
  (`compute_delta` : présente serveur + absente disque ⇒ `missing_on_device`). À
  vérifier : la désinstallation est-elle **durable** ou la font revient-elle ?
  Reproduire :

```bash
[M1] .venv/bin/fontsync-agent sync
[M1] ls ~/Library/Fonts | grep -i E2EInter    # revient-elle ?
```

- **Résultat observé :** _______________________  Statut : ☐

---

### S4 — Coupure réseau → reconnexion `listen` → rattrapage

**Objectif :** vérifier que `listen` reconnecte après une coupure et **rattrape** ce
qui a changé pendant l'absence.

```bash
[M2] tail -f ~/Library/Logs/FontSync/listen.out.log   # garder sous les yeux
```

1. `[M2]` Couper le réseau (Wi-Fi off, ou débrancher l'Ethernet).
   - Attendu dans les logs : la connexion SSE tombe, puis « Reconnexion dans 5s… »
     en boucle (`RECONNECT_DELAY_SECONDS = 5`).
2. `[M1]` Pendant la coupure, pousser une nouvelle font :

```bash
[M1] .venv/bin/python scripts/dev/seed-font.py ~/Library/Fonts --family "E2E Offline" --style Regular
```

3. `[M2]` Rétablir le réseau.

- **Résultat attendu :**
  - `[M2]` `listen` reconnecte (`listen.out.log` : « Flux SSE connecté »).
  - Le serveur envoie le **signal initial** `sync` à la reconnexion → `sync` relancé.
  - `[M2]` `~/Library/Fonts/E2EOffline-Regular.ttf` installé (rattrapage stateless via delta).

```bash
[M2] ls ~/Library/Fonts | grep -i E2EOffline     # attendu : présent après reconnexion
```

- **Résultat observé :** _______________________  Statut : ☐

---

### S5 — Cache de hash (2ᵉ scan quasi instantané)

**Objectif :** vérifier que le cache `(path, size, mtime_ns)` évite de re-hacher.

**Préconditions :** au moins quelques fonts présentes dans `~/Library/Fonts` de M1
(le contraste est plus net avec beaucoup de fonts).

```bash
[M1] rm -f ~/.fontsync/hash_cache.json          # repartir sans cache
[M1] time .venv/bin/fontsync-agent sync         # 1er scan : hache tout (lent)
[M1] ls -l ~/.fontsync/hash_cache.json          # le cache est désormais écrit
[M1] time .venv/bin/fontsync-agent sync         # 2e scan : cache chaud (rapide)
```

- **Résultat attendu :**
  - `~/.fontsync/hash_cache.json` existe et contient une entrée par font.
  - Le **2ᵉ `sync` est nettement plus rapide** que le 1er (pas de re-hachage ;
    aucun fichier inchangé n'est relu).
  - Modifier/ajouter une font puis re-`sync` ne re-hache **que** le fichier touché.
- **Résultat observé :** _______________________  Statut : ☐

---

### S6 — Format `.ttc` (collection) — stockage, pull, install

**Objectif :** un `.ttc` doit être accepté, transféré et installable.

Générer un vrai `.ttc` de test (le repo n'embarque pas de fixtures) :

```bash
[M1] .venv/bin/python scripts/dev/seed-font.py /tmp/ttc --family "E2E Coll" --style Regular
[M1] .venv/bin/python scripts/dev/seed-font.py /tmp/ttc --family "E2E Coll" --style Bold
[M1] .venv/bin/python - <<'PY'
from fontTools.ttLib import TTFont, TTCollection
ttc = TTCollection()
ttc.fonts = [TTFont("/tmp/ttc/E2EColl-Regular.ttf"), TTFont("/tmp/ttc/E2EColl-Bold.ttf")]
ttc.save("/tmp/ttc/E2EColl.ttc")
print("OK : /tmp/ttc/E2EColl.ttc")
PY
[M1] cp /tmp/ttc/E2EColl.ttc ~/Library/Fonts/      # déclenche WatchPaths → push
```

- **Résultat attendu :**
  - `[S]` `E2EColl.ttc` importé (`file_format = ttc`), visible dans l'UI.
  - `[M2]` pull + install → `~/Library/Fonts/E2EColl.ttc` présent (`.ttc` est dans
    `INSTALLABLE_FORMATS`).
  - **Normal :** les logs M1 peuvent afficher « 2 découvertes » pour ce seul `.ttc`
    (une par face, cf. note technique 6) → dédoublonné par hash, stocké **1 fois**.

```bash
[M2] ls ~/Library/Fonts | grep -i E2EColl.ttc
```

- **Résultat observé :** _______________________  Statut : ☐

---

### S7 — Font malformée → stockée avec métadonnées partielles (jamais rejetée)

**Objectif :** une font au header valide mais au corps corrompu doit être **stockée**
avec des métadonnées partielles, **pas rejetée** (cf. `CLAUDE.md`).

Fabriquer un `.ttf` au header valide (magic `\x00\x01\x00\x00` conservé) mais tronqué :

```bash
[M1] .venv/bin/python scripts/dev/seed-font.py /tmp/bad --family "E2E Broken" --style Regular
[M1] head -c 400 /tmp/bad/E2EBroken-Regular.ttf > ~/Library/Fonts/E2EBroken-Regular.ttf
```

- **Résultat attendu :**
  - `[M1]` push **réussi** (pas de `400` : les magic bytes passent ; `fonttools`
    échoue au parsing → métadonnées partielles).
  - `[S]` la font apparaît dans l'UI avec des champs vides (ex. `family_name` nul →
    affichée par son nom de fichier), `file_format = ttf`, **jamais en erreur**.
  - `[M2]` la pull + installe normalement (le contenu est transféré tel quel).
- **⚠️ Note :** un fichier avec **mauvais magic bytes** (ou extension non supportée)
  est, lui, **légitimement rejeté** par `400` (`_validate_magic_bytes`). C'est le
  comportement attendu, pas un bug — ce scénario teste le cas « header OK, corps KO ».
- **Résultat observé :** _______________________  Statut : ☐

---

### S8 — Soft-delete + résurrection

**Objectif :** supprimer (soft) une font côté serveur, puis la ressusciter.

**Préconditions :** une font active sur le serveur, **toujours présente sur le disque
de M1** (ex. « E2E Roboto » de S2).

1. `[UI]` Supprimer la font (corbeille).

- **Résultat attendu (suppression) :**
  - `[S]` `deleted_at` renseigné ; la font **disparaît** de la liste active et du
    delta (`compute_delta` filtre `deleted_at IS NULL`).
  - `[M1]`/`[M2]` : le **fichier local n'est pas supprimé** (le soft-delete serveur
    ne désinstalle pas les devices — cohérent avec S3/point technique 4).

2. **Résurrection automatique par re-push** (M1 a toujours le fichier) :

```bash
[M1] .venv/bin/fontsync-agent sync       # le hash est "unknownToServer" → re-push → revive
```

- **Résultat attendu (résurrection) :**
  - `[S]` la font **redevient active** (`_revive_if_deleted` : `deleted_at = NULL` +
    re-regroupement famille).
  - **⚠️ À surveiller :** le re-push d'un doublon **ne diffuse pas** d'event frontend
    (`is_duplicate=True` ⇒ pas de `font.added` ni de SSE). **Rafraîchir l'UI** pour
    confirmer la réapparition. (Variante propre : `POST /api/fonts/{id}/restore`, qui
    **diffuse** bien l'event + le signal SSE.)
- **Résultat observé :** _______________________  Statut : ☐

---

### S9 — Collision de noms à l'install (préservation de la font locale, B7)

**Objectif :** quand M2 reçoit une font dont le **nom de fichier** est déjà pris par
un **contenu différent** (une font perso de l'utilisateur), la font locale doit être
**préservée** ; la font FontSync est posée sous un nom désambiguïsé.

```bash
# [M1] : la font "officielle" (contenu X), poussée vers le serveur.
[M1] .venv/bin/python scripts/dev/seed-font.py ~/Library/Fonts --family "E2E Clash" --style Regular
#     → ~/Library/Fonts/E2EClash-Regular.ttf  (contenu X)  → WatchPaths → push

# [M2] : une font perso DIFFÉRENTE portant LE MÊME nom de fichier (contenu Y),
#        posée AVANT que X n'arrive.
[M2] .venv/bin/python scripts/dev/seed-font.py /tmp/local --family "Ma Police" --style Perso
[M2] cp /tmp/local/MaPolice-Perso.ttf ~/Library/Fonts/E2EClash-Regular.ttf   # même nom, contenu Y
[M2] shasum -a 256 ~/Library/Fonts/E2EClash-Regular.ttf    # note le hash de Y
```

Laisser M2 synchroniser (signal SSE déclenché par le push de M1, ou `fontsync-agent sync`).

- **Résultat attendu :**
  - `[M2]` `~/Library/Fonts/E2EClash-Regular.ttf` **inchangé** (toujours le contenu Y
    — re-vérifier le `shasum`, identique).
  - `[M2]` la font X (de M1) installée sous un nom désambiguïsé :
    `E2EClash-Regular__fontsync-<12 hexa>.ttf`.

```bash
[M2] ls ~/Library/Fonts | grep -i E2EClash         # attendu : 2 fichiers (Y + …__fontsync-…)
[M2] shasum -a 256 ~/Library/Fonts/E2EClash-Regular.ttf   # attendu : INCHANGÉ (= hash de Y noté plus haut)
```

- **Résultat observé :** _______________________  Statut : ☐

---

## Nettoyage (après le test)

```bash
# Sur M1 et M2 : retirer les fonts de test et désinstaller les jobs launchd.
[M1] rm -f ~/Library/Fonts/E2E*.ttf ~/Library/Fonts/E2E*.ttc ~/Library/Fonts/E2EClash-Regular__fontsync-*.ttf
[M1] .venv/bin/fontsync-agent teardown
[M2] rm -f ~/Library/Fonts/E2E*.ttf ~/Library/Fonts/E2E*.ttc ~/Library/Fonts/E2EClash-Regular__fontsync-*.ttf
[M2] .venv/bin/fontsync-agent teardown
# Serveur dev : l'état vit dans .dev/ (gitignoré) → rm -rf .dev pour repartir propre.
```

> ⚠️ Le test réel installe de vraies fonts dans `~/Library/Fonts`. N'utiliser que des
> noms de test (`E2E*`) pour ne pas polluer ta bibliothèque, et nettoyer en fin de run.

---

## Journal des bugs trouvés

À remplir pendant le déroulé. Un bug → une ligne (puis ticket / fix avant packaging).

| # | Scénario | Sévérité | Description | Statut |
|---|----------|----------|-------------|--------|
| _(pré-vérifié)_ | S3 | bloquant ? | Canal commande UI→agent (uninstall/install/activate/deactivate) passe par le WS legacy `/ws/agent` que l'agent SSE n'ouvre plus → probable `503`. | à confirmer |
| _(pré-vérifié)_ | S2 | majeur ? | `/api/fonts/upload` n'appelle pas `broadcast_sync()` (SSE) → pas de propagation réactive après upload UI (seulement au sync périodique/manuel). `push` et `restore` le font, pas `upload`. | à confirmer |
|   |          |          |             |        |

---

## Bilan / sign-off

- Date du run : __________   Macs utilisés : __________   Serveur : __________
- Scénarios ✅ : ____ / 9   ·   ❌ : ____   ·   ⚠️ ouverts : ____
- Décision : ☐ P0.2 validé (cocher dans `PLAN-PUBLICATION.md`) · ☐ bugs à corriger d'abord

> Rappel : **ne cocher P0.2 dans `PLAN-PUBLICATION.md` qu'après confirmation
> explicite que cette checklist a été déroulée.**
