# Remise à plat des états d'une police — modèle cible et plan de migration

> **Ce que la cible du brief demandait et ce qu'elle devient.** Le brief §3 vise « d'environ huit champs d'état à trois » : `Font.deleted_at`, `DeviceFont` (qui détient quoi), un booléen de confirmation. **Ce document en livre cinq**, et le dit d'entrée plutôt que de le reformuler en fin de tableau. Les deux écarts : `Font.purged_at` survit (il est le seul bit qui sépare « corbeille restaurable » de « pierre tombale invisible », `backend/services/trash.py:44`, `backend/routers/fonts.py:380`, `:744`, et c'est la pré-condition obligatoire de la récolte — le fondre imposerait de le réinventer sous un autre nom), et `DeviceFont.ingestible` naît (c'est §2.2 du brief traduit en donnée : un détenteur qui ne peut pas repousser ne protège rien). En échange, **cinq colonnes disparaissent**, dont `deleted_reason` que le brief demandait de fondre. Sur la ligne `Font` elle-même, l'objectif est tenu : 4 champs d'état → 3.
>
> Tous les chiffres ci-dessous ont été **remesurés en lecture seule** sur `.dev/backup/fontsync-20260810-1810.db` (`sqlite3 -readonly`, aucune écriture). `pytest tests/ -q` revérifié : **314 passed, 3 skipped**. Aucun fichier écrit, aucune migration lancée.

---

## 0. Où on en est — à tenir à jour à chaque lot

**Ce document est la source de vérité du chantier.** Une session qui reçoit « exécute la
prochaine étape » lit ce tableau, prend le premier lot à `à faire`, et le met à jour en
terminant. Le détail de chaque lot est en §8 ; ne pas commencer un lot sans avoir lu §3
(récolte), §4 (`/Library/Fonts`) et §5.3 (points de non-retour).

| Lot | État | Migration | Vérif. de sortie |
|---|---|---|---|
| **L0 — Hygiène** | **terminé** | — | `pytest tests/ -q` **vert — 329 passed, 3 skipped** ; `npm run build` **vert** ; corbeille affichée à 0 ligne — **vérifié en prod le 11 août 2026** (`GET /api/fonts/trash` → `total: 0`) ; sauvegarde automatique **livrée, déployée et vérifiée en prod** (`BACKUP_DIR=/backups`, instantané 19 Mo intègre + miroir 5180/5180 fichiers) |
| **L1 — Inventaire miroir** | **terminé** | M1 (`6adf18c939c6`) | `DeletionDetection.total == 0` **vérifié** aux deux premiers deltas des deux machines ; registre passé de 8 215 à **11 384** (6 201 MacBook + 5 183 mini) — au-dessus des ~10 400 estimés (dédup par hash réel plus généreux que l'estimation sur l'instantané du 10 août), sans anomalie : `PRAGMA integrity_check`/`foreign_key_check` propres, aucune ligne `WARNING`/quarantine dans les logs — **déployé et vérifié en prod le 11 août 2026** |
| **L2 — Booléen de confirmation** | à faire | M2 | requête de cohérence §5.1 = 0 |
| **L3 — Agent 0.2.0** | à faire | — | `.dmg` posé à la main, mini d'abord ; release **non publiée en `--latest`** |
| **L4 — Nettoyage** | à faire | M3 | `npm run build` vert ; `PRAGMA foreign_key_check` vide |
| **L5 — Récolte + affichage dérivé** | à faire | — | **point de non-retour données** — ne pas activer sans avoir lu §5.3 |

**Prérequis bloquant de L1, levé en L0 :** la sauvegarde automatique (§5.3).

**L0 est terminé.** Le code des dix lignes de §8/L0 est livré et vérifié (tests + build
verts, revérifié le 10 août 2026 dans cette session).

**Révision du mécanisme de sauvegarde (10 août 2026).** `scripts/backup-prod.sh` +
Planificateur de tâches DSM a été écarté comme mécanisme **d'automatisation** : trop
Synology-spécifique pour une app qui doit tourner sur n'importe quel hôte Docker chez
d'autres utilisateurs (cf. brief long terme, `ROADMAP.md`). La sauvegarde automatique
vit désormais **dans le backend** (`backend/services/backup.py`, activée par
`BACKUP_DIR`) : instantané quotidien de la base + miroir hebdomadaire des polices,
depuis le process qui sert déjà la base — zéro `docker exec`, zéro tâche planifiée
externe, zéro clic DSM. `docker-compose.nas.yml` l'active par défaut (volume `backups`
+ `BACKUP_DIR=/backups`). `scripts/backup-prod.sh` reste comme outil manuel ponctuel
(§11, docs/INSTALL-NAS.md §5). Code livré et testé (7 tests, `tests/backend/
test_backup.py`) dans cette session.

**Déploiement du 11 août 2026, sur le NAS réel (`100.104.232.79:93` en Tailscale,
relayé commande par commande — pas d'accès direct depuis cette session).** Le code
n'a pas été transféré par `scp`/`rsync` : les deux protocoles échouent sur ce NAS pour
le compte `Leo` (`scp` : chroot SFTP qui ne voit pas `/volume1/docker/…` ; `rsync` :
même symptôme sur le sous-processus `rsync --server`, cause exacte non creusée). Seul
un exec SSH simple passe — `tar czf - … | ssh … 'tar xzf - -C …'` a fonctionné et reste
la méthode à réutiliser pour un prochain transfert de code vers ce NAS.

**Point d'attention trouvé en cours de route : le compose déployé sur ce NAS diverge
du template du repo** — `image: …:main` (pas `:latest`, suivi manuellement) et port
hôte `8070` (pas `8080`, ciblé par un sidecar Tailscale Serve `ts-fontsync`). Un
écrasement naïf du fichier aurait cassé l'accès réseau et la mécanique de mise à jour.
La fusion a gardé la prod telle quelle et n'a ajouté que les 3 lignes de sauvegarde
(`BACKUP_DIR`, montage, volume). **Toujours diffé `docker-compose.nas.yml` contre
la version en place sur ce NAS avant d'écraser — ne jamais partir du seul template.**

Vérifié en production après déploiement :
- `sudo docker exec fontsync ls /backups` → instantané `fontsync-20260811-071911.db`
  (19 865 600 octets, `PRAGMA integrity_check` → `ok`) ;
- miroir des polices : `5180` fichiers dans `/backups/fonts` — le total exact ;
- `GET /api/fonts/trash?per_page=1` → `{"total": 0, ...}` — corbeille vide en prod.

Sauvegarde manuelle (`scripts/backup-prod.sh`) testée avec succès dans la foulée :
base (19 Mo, intègre) et miroir (5180 fichiers, 1,5 Go) dans
`/volume1/docker/fontsync/backups/`.

**Décision utilisateur (11 août 2026) : le token qui a fuité le 10 août n'est PAS révoqué,
volontairement.** `FONTSYNC_TOKEN` reste inchangé pour toute la durée de ce chantier — ce
n'était pas un prérequis technique de L1 (rien dans le modèle cible n'en dépend), c'était
une précaution de sécurité indépendante, explicitement écartée pour l'instant. §11 est
laissé tel quel comme mémo à reprendre plus tard, hors de ce chantier. **Plus aucun
prérequis ne bloque L1.**

**L1, code livré (11 août 2026), dans cette session.** Tout §8/L1 est en place :

- Migration `6adf18c939c6` (`inventory_mirror`, revises `b7c31a4d90e2`) : `devices.last_declaration_at`,
  `devices.deleted_at`, `device_fonts.ingestible` (+ `ix_device_fonts_font_id`). Additive pure, vérifiée
  contre `Base.metadata.create_all` par le test structurel §7.5 (`tests/backend/test_migrations.py`).
- `backend/services/inventory.py` — `reconcile_inventory` (dédup par hash, arrivées/départs/mises à
  jour), appelée depuis `backend/routers/sync.py:delta_sync` dans le nouvel ordre de §3.2 (détection →
  réconciliation + récolte-aperçu → commit unique → notification → delta).
- `backend/services/harvest.py` — `harvest_tombstones`, livrée **INERTE** : compte et journalise sur
  G3/G4(proxy `deleted_reason`)/G5/G6/G7, ne supprime jamais rien (G8/G9 attendent M2).
- Effacement des associations ajouté à `restore_font` (`routers/fonts.py`) et `_revive_if_deleted`
  (`services/font_importer.py`), comme `delete_font`/`resolve_duplicate_faces` le faisaient déjà —
  ferme la boucle « restauration → re-quarantaine » que la réconciliation rend possible.
- Soft delete de `devices` : `delete_device`, `merge_devices` (sources), `list_devices`, les
  `_get_device_or_404` de `devices.py`/`sync.py`/`fonts.py`, et `register_device` qui ranime.
- `DeviceFontEntry.ingestible` (défaut `True`) + asymétrie dans `compute_delta` (`sync_manager.py`) :
  n'agit que sur `unknown_to_server`.
- Tests : `test_inventory.py` (8), `test_harvest.py` (6), `test_migrations.py` (1, structurel §7.5),
  plus 6 ajoutés à `test_deletion_propagation.py` (G1/G2 au niveau routeur, soft delete, canari
  restauration doublé de la variante à redéclaration). **Suite complète : 348 passed, 3 skipped**
  (+19 vs le 329 de L0), `ruff format`/`ruff check` sans régression sur le code touché.

**Déploiement L1 du 11 août 2026, dans cette session.** Contrairement aux paliers précédents, cette
session tournait *sur* le MacBook lui-même (`hostname` = MacBook-Pro-de-Leo, `device_id` agent
`aef3f593…` — confirmé identique à celui du plan) : accès direct à l'une des deux machines. L'accès
NAS et Mac mini restait nul en début de session ; l'utilisateur a autorisé la clé publique de la
session sur les deux (`~/.ssh/authorized_keys`), puis un `sudoers.d/fontsync-deploy` scopé à la
seule commande `/usr/local/bin/docker` en `NOPASSWD` sur le NAS (`docker.sock` est `root:root`,
aucun groupe `docker` sur ce Synology) — **à révoquer** (`sudo rm /etc/sudoers.d/fontsync-deploy`)
une fois le chantier terminé, ce n'est pas un accès permanent voulu.

Séquence exécutée, dans l'ordre d'§5.2 :
1. Rituel d'arrêt sur les deux Macs (`launchctl bootout` de `com.fontsync.sync`/`.listen` + fermeture
   de l'app) — MacBook piloté directement, Mac mini relayé commande par commande.
2. `git push origin main` (`7832e30`), puis `gh workflow run docker-publish.yml --ref main` — build
   multi-arch en 4 min 44, image `ghcr.io/leodurandfr/fontsync:main` à jour.
3. Sur le NAS : sauvegarde automatique déjà fraîche du jour (07:19, vérifiée avant d'agir — pas de
   sauvegarde manuelle supplémentaire pour ne pas élargir le scope sudo à `backup-prod.sh`, qui
   exige root sur tout le script et pas seulement `docker`), puis `docker compose pull fontsync` +
   `up -d fontsync`. L'entrypoint a appliqué `b7c31a4d90e2 → 6adf18c939c6` avant de redémarrer
   uvicorn — logs propres, `healthy` en ~50 s.
4. Vérification structurelle (`sqlite3` absent de l'image, requêtes faites en `python3 -c` depuis le
   conteneur) : `alembic_version = 6adf18c939c6`, les 3 colonnes/l'index présents,
   `PRAGMA integrity_check` → `ok`, `foreign_key_check` → vide.
5. Relance des agents sur les deux Macs. **Critères de sortie du tableau atteints** : deux deltas par
   machine, **zéro** ligne `WARNING`/quarantine/detection dans les logs serveur sur toute la fenêtre
   (`DeletionDetection.total == 0` aux quatre deltas). Registre `device_fonts` : **8 215 → 11 384**
   (6 201 MacBook + 5 183 mini) — au-dessus des ~10 400 estimés le 10 août, écart expliqué par un
   dédup par hash réel plus généreux que l'estimation sur l'instantané (pas une anomalie : comptes
   par device cohérents avec les tailles déclarées après dédup dans les logs). `last_declaration_at`
   posé sur les deux appareils (précondition de G7 pour une future récolte). Le mini a aussi loggé un
   aperçu de récolte **INERTE** (4 pierres tombales candidates, aucune suppression — attendu tant que
   le flag L5 est éteint).

**L1 est terminé et vérifié en production.** Prochain lot : **L2 — booléen de confirmation** (M2).

---

## 1. Ce qui change, en un tableau

| # | Champ AVANT | Devenir | Ancrage / mesure |
|---|---|---|---|
| 1 | `Font.deleted_at DATETIME NULL` | **INCHANGÉ — pivot unique** | 5 écrivains (`routers/fonts.py:683`, `:752`, `services/deletion_propagation.py:130`, `services/duplicate_faces.py:274`, `services/font_importer.py:134`). Index `ix_fonts_deleted_at` conservé (`models/font.py:123`). |
| 2 | `Font.deleted_reason VARCHAR(30)`, 3 valeurs, **décisionnel** | **SUPPRIMÉ** (L4) | Un seul lecteur décide : `row.deleted_reason in PROPAGATING_DELETION_REASONS` (`services/sync_manager.py:99`). Le conserver imposerait une double écriture sur 6 sites (`fonts.py:684`, `:407`, `:753`, `duplicate_faces.py:275`, `deletion_propagation.py:131`, `font_importer.py:135`) sans mécanisme de cohérence — la dérive exacte que le brief §3 interdit. |
| 3 | — | **`Font.deletion_confirmed BOOLEAN NOT NULL DEFAULT '0'`** — NOUVEAU, seul verrou | Défaut `0` = *fail-safe*. Traduction structurelle de la liste blanche actuelle (`models/font.py:39`). Un `DEFAULT '1'` serait **1 025 ordres de désinstallation latents** sur deux machines à `propagate_deletions=1` (mesuré : `SELECT propagate_deletions FROM devices` → `1`, `1`). |
| 4 | `Font.purged_at DATETIME NULL` | **CONSERVÉ**, promu discriminant de visibilité | `deleted_at NOT NULL ∧ purged_at NULL` = corbeille visible ; `∧ purged_at NOT NULL` = pierre tombale invisible, récoltable. Récolter sans lui abandonnerait le blob (chemin dérivé du seul hash, `services/storage.py:40-44`). |
| 5 | `Font.storage_path VARCHAR(500) NOT NULL` | **SUPPRIMÉ** (L4) | **Zéro lecture fonctionnelle** : tout accès fichier passe par `(file_hash, file_format)` — `fonts.py:481`, `:509`, `sync.py:237`, `trash.py:48`, `font_importer.py:81`. Écrit en `font_importer.py:115` et `:232`, exposé (`schemas/font.py:33`, `frontend/src/types/api.ts:7`), jamais rendu. |
| 6 | — | **`Font.harvest_candidate_since DATETIME NULL`** — NOUVEAU, comptable | Mémoire du délai de grâce de la récolte (§3.4). Aucune lecture d'affichage. |
| 7 | `Device.sync_status VARCHAR(20)` | **SUPPRIMÉ** (L4) | `'idle'` sur les 2 appareils (mesuré). Écrivains vivants : `routers/ws.py:157`, `:178`, canal `/ws/agent/{device_id}` que l'agent n'ouvre plus. Champ **requis** de `DeviceResponse` (`schemas/device.py:74`) et **optionnel** de `DeviceUpdate` (`:42`, `str \| None`) → retrait simultané modèle/schéma/frontend obligatoire (§6). |
| 8 | `Device.last_sync_at DATETIME` | **SUPPRIMÉ** (L4) | `NULL` sur les 2 appareils. Écrivain unique `routers/ws.py:159`. **0 occurrence** dans `tests/`. |
| 9 | — | **`Device.last_declaration_at DATETIME NULL`** — NOUVEAU | La place sémantique laissée vacante, remplie honnêtement : un seul écrivain, le traitement d'une déclaration **non vide et non suspecte** dans `POST /api/sync/delta`. `last_seen_at` ne peut pas jouer ce rôle — posé par le register (`devices.py:90`), donc *avant* le delta (`agent/sync_command.py:174`, `:189`), et déplacé par un PATCH d'UI (`devices.py:133`). |
| 10 | — | **`Device.deleted_at DATETIME NULL`** — NOUVEAU (soft delete) | Convention projet (`CLAUDE.md`). `delete_device` fait aujourd'hui un **hard delete** de l'appareil *et* de ses associations (`routers/devices.py:242-245`) : sous le modèle cible, ce geste **relâche** la condition de récolte au lieu de la resserrer (§3.5). |
| 11 | existence d'une ligne `DeviceFont` | **CHANGE DE SENS** — reconstruite à chaque delta | Aujourd'hui écrite au seul transfert (`sync_manager.py:114-142`, appelée depuis `sync.py:174` et `:244`), `compute_delta` étant en lecture pure (`sync_manager.py:33-38`). Mesuré : mini **5 184** lignes / MacBook **3 031** ; **2 155 polices vivantes n'ont qu'un seul détenteur enregistré** ; **1 015 des 1 025 tombes n'ont aucune association**. |
| 12 | `DeviceFont.activated BOOLEAN NOT NULL` | **SUPPRIMÉ** (L4) | `SELECT activated, COUNT(*) FROM device_fonts GROUP BY 1` → `1|8215`. `register_device_font` n'accepte pas le paramètre (`sync_manager.py:114-119`) : la valeur ne peut structurellement jamais quitter `True`. |
| 13 | — | **`DeviceFont.ingestible BOOLEAN NOT NULL DEFAULT '1'`** — NOUVEAU | « Ce détenteur peut-il alimenter la bibliothèque ? » Défaut `True` = un agent ancien **bloque** la récolte, jamais l'inverse. |
| 14 | `DeviceFont.local_path VARCHAR(1000) NOT NULL` | **CONSERVÉ NOT NULL**, écrit par la réconciliation | Hétérogène aujourd'hui — mesuré : mini 4 456 chemins `/Users` + **551** `/Library/Fonts` + 177 noms nus ; MacBook **3 031/3 031 noms nus** (`sync.py:247` écrit `original_filename` au pull). Le rendre NULL-able forcerait une **recréation de table** en M1 : refusé (§5.1). Repli à l'insertion : `entry.local_path or entry.filename`, comme `sync.py:177`. |
| 15 | — | **INDEX `ix_device_fonts_font_id (font_id)`** — NOUVEAU | PK = `(device_id, font_id)` : rien ne couvre `font_id` seul. Plan mesuré sur l'instantané : `SCAN df USING COVERING INDEX sqlite_autoindex_device_fonts_1`. Coût disque ≈ 180 Ko (page 4 Ko, 4 850 pages). |

**Décompte honnête.** AVANT : **8 champs d'état**, dont **4 morts** (7, 8, 12, 5 — le dernier hors brief) et **1 sur-spécifié** (2 : trois valeurs pour une question binaire).
APRÈS : **5 axes qui décident** — `deleted_at`, `deletion_confirmed`, `purged_at`, existence de `device_fonts`, `device_fonts.ingestible` — dont **3 sur la ligne `Font`** (l'objectif du brief, tenu là où il portait) ; **1 attribut descriptif** (`local_path`) ; **3 champs comptables** que rien n'affiche (`last_declaration_at`, `devices.deleted_at`, `harvest_candidate_since`).
**5 colonnes retirées, 5 ajoutées** : le gain n'est pas volumétrique, il est là — le verrou de propagation passe de « appartenance à une liste blanche de 3 valeurs écrite en 6 endroits » à **un booléen lu en 1 endroit**, et 4 colonnes mortes disparaissent.

---

## 2. Le modèle cible

### 2.1 Schéma stocké (après L4)

```sql
-- ─────────────────────────────── fonts ───────────────────────────────
CREATE TABLE fonts (
    id                      CHAR(32)     NOT NULL,
    file_hash               VARCHAR(64)  NOT NULL,
    original_filename       VARCHAR(500) NOT NULL,
    file_size               INTEGER      NOT NULL,
    file_format             VARCHAR(10)  NOT NULL,
    -- … 22 colonnes de métadonnées INCHANGÉES (family_name … variable_axes) …
    source                  VARCHAR(50)  NOT NULL,
    source_device_id        CHAR(32),                            -- pas de FK : délibéré
    google_fonts_id         VARCHAR(200),
    created_at              DATETIME     NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at              DATETIME     NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    deleted_at              DATETIME,                            -- pivot : NULL = bibliothèque
    deletion_confirmed      BOOLEAN      NOT NULL DEFAULT '0',   -- LE verrou de propagation
    purged_at               DATETIME,                            -- le blob a quitté le stockage
    harvest_candidate_since DATETIME,                            -- délai de grâce (§3.4)
    PRIMARY KEY (id),
    UNIQUE (file_hash)                                           -- contrainte ANONYME (vérifié)
);
CREATE INDEX ix_fonts_family_name    ON fonts (family_name);
CREATE INDEX ix_fonts_classification ON fonts (classification);
CREATE INDEX ix_fonts_file_hash      ON fonts (file_hash);
CREATE INDEX ix_fonts_source         ON fonts (source);
CREATE INDEX ix_fonts_deleted_at     ON fonts (deleted_at);
-- retirés : storage_path VARCHAR(500) NOT NULL, deleted_reason VARCHAR(30)

-- ────────────────────────────── devices ──────────────────────────────
CREATE TABLE devices (
    id                  CHAR(32)     NOT NULL,
    name                VARCHAR(200) NOT NULL,
    hostname            VARCHAR(200) NOT NULL,
    os                  VARCHAR(50)  NOT NULL,
    os_version          VARCHAR(100),
    agent_version       VARCHAR(20),
    last_seen_at        DATETIME,                          -- activité HTTP (register / PATCH)
    last_declaration_at DATETIME,                          -- dernier delta CRÉDIBLE
    deleted_at          DATETIME,                          -- soft delete : sort de l'UI, reste au registre
    font_directories    JSON,
    auto_pull           BOOLEAN      NOT NULL,
    auto_push           BOOLEAN      NOT NULL,
    propagate_deletions BOOLEAN      NOT NULL DEFAULT '0',
    created_at          DATETIME     NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    PRIMARY KEY (id)
);
-- retirés : sync_status VARCHAR(20) NOT NULL, last_sync_at DATETIME

-- ─────────────────────────── device_fonts ────────────────────────────
CREATE TABLE device_fonts (
    device_id    CHAR(32)      NOT NULL REFERENCES devices(id),
    font_id      CHAR(32)      NOT NULL REFERENCES fonts(id),
    local_path   VARCHAR(1000) NOT NULL,
    ingestible   BOOLEAN       NOT NULL DEFAULT '1',
    installed_at DATETIME      NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    PRIMARY KEY (device_id, font_id)
);
CREATE INDEX ix_device_fonts_font_id ON device_fonts (font_id);
-- retiré : activated BOOLEAN NOT NULL

-- font_families / font_family_members : structure INCHANGÉE.
-- font_family_members.font_id est une FK SANS ON DELETE (models/font_family.py:57-61)
-- et PRAGMA foreign_keys=ON (database.py:19) : la récolte DOIT nettoyer cette
-- table avant fonts. Mesuré : 1 025 membres pointent des polices en corbeille.
```

**Contrat agent → serveur** (`backend/schemas/sync.py:10-15`) :

```python
class DeviceFontEntry(CamelModel):
    hash: str = Field(..., min_length=64, max_length=64)
    filename: str
    local_path: str | None = None
    ingestible: bool = True    # NOUVEAU — défaut = rétrocompatibilité stricte
```

`CamelModel` (`schemas/base.py:13-16`) n'impose pas `extra='forbid'` : un agent 0.2.0 face à un serveur ancien voit le champ **ignoré**, un agent 0.1.0 face à un serveur neuf est traité comme **entièrement ingestible**. Il n'existe aucun versionnement du contrat : c'est le défaut qui tient la compatibilité, dans la direction conservatrice, **dans les deux sens**.

`DeltaSyncResponse` n'accueille **aucun** champ nouveau. Un `out_of_scope` informatif serait mort à la naissance : l'agent ne consomme que six clés (`agent/sync_command.py:193-197`) et il connaît déjà son propre décompte.

### 2.2 États dérivés

| Dérivé | Requête exacte | Coût à la volumétrie réelle |
|---|---|---|
| **« installée sur N de tes M machines »** | Numérateur, **une requête par page** : `SELECT font_id, COUNT(*) FROM device_fonts WHERE font_id IN (:page_ids) GROUP BY font_id`. Dénominateur : `SELECT COUNT(*) FROM devices WHERE deleted_at IS NULL`, **une fois**, dans l'enveloppe. | `per_page ≤ 200` (`fonts.py:140`) → ≤ 200 seeks sur `ix_device_fonts_font_id` + 1 COUNT sur 2 lignes. Négligeable. **Interdit** : réutiliser `fetchDeviceStatuses` (`DeviceInstallSheet.vue:131`, une requête HTTP par police). **Le chiffre n'a aucun sens avant L1** : le MacBook a 3 025 associations vivantes pour 5 180 polices, l'agrégat mentirait sur **2 155** d'entre elles. |
| **Corbeille visible** | `… WHERE deleted_at IS NOT NULL AND purged_at IS NULL ORDER BY deleted_at DESC` — une clause ajoutée à `fonts.py:340`. | **Effet immédiat, sans migration** : les 1 025 entrées sont **toutes purgées** (mesuré : `manual|1|1015`, `quarantine|1|10`) → l'écran passe de 1 025 lignes inertes (toutes badgées « Fichier retiré », bouton Restaurer désactivé, `TrashPage.vue:218-220`, `:229`) à **0**. |
| **`pending_confirmation`** | `SELECT COUNT(*) FROM fonts WHERE deleted_at IS NOT NULL AND purged_at IS NULL AND deletion_confirmed = 0` — remplace `fonts.py:345-349`. **La clause `purged_at IS NULL` est obligatoire** : sans elle le bandeau annonce « N en attente » au-dessus d'une liste vide, et le seul bouton offert propage une désinstallation pour des polices que l'utilisateur ne peut plus voir. | Index `ix_fonts_deleted_at`. Sub-ms. |
| **`is_online`** | `str(device.id) in ws_manager.connected_sse_devices` — déjà correct en `devices.py:47`. | **Correction d'une ligne** : `fonts.py:575` lit `ws_manager.connected_agents`, registre du canal WS agent mort (`ws_manager.py:164`). Conséquence mesurable : `GET /api/fonts/{id}/devices` renvoie `isOnline=false` pour **toute** machine, donc le bouton « Installer » (`DeviceInstallSheet.vue:249`) est grisé en permanence. Sa propre ligne de changelog. |
| **`storage_path`** | Fonction pure : `base / hash[:2] / f"{hash}.{ext}"` (`services/storage.py:40-44`). | Nul, et une colonne `String(500)` de moins sur 6 205 lignes + un champ de moins dans chaque payload. |
| **Candidats à la récolte** | Cf. §3.4. | `SCAN fonts` (6 205) + `SEARCH df USING ix_device_fonts_font_id`. Même ordre de grandeur que le `SELECT` sans `WHERE` que `compute_delta` fait déjà à chaque delta (`sync_manager.py:58-69`). |

`FontFamily.style_count` **reste stocké** (§9), mais la récolte le recale sur les familles touchées : elle n'a pas le choix, elle supprime des `font_family_members`.

### 2.3 Le vocabulaire d'affichage

| Ce que l'utilisateur voit | D'où ça vient | Site |
|---|---|---|
| « En bibliothèque » | `deleted_at IS NULL` | `fonts.py:144` |
| « installée sur 2 de tes 2 machines » | COUNT dérivé (§2.2) — **jamais stocké** | nouveau, L5 |
| « présente sur cette machine, hors bibliothèque synchronisée » | ligne `device_fonts` avec `ingestible = 0` | nouveau, L5 |
| « détenue depuis le … » | `device_fonts.installed_at` | `fonts.py:589` → `DeviceInstallSheet.vue:215-220`. **Les lignes créées par la réconciliation prennent `installed_at = font.created_at`**, borne inférieure vraie : `server_default=func.now()` (`models/device_font.py:21-23`) daterait ~2 000 polices du jour de la migration. |
| « Dans la corbeille » + bouton Restaurer | `deleted_at NOT NULL ∧ purged_at NULL` | `fonts.py:340` (à amender) |
| « En attente d'arbitrage » (badge ambre) + bandeau | `deletion_confirmed = 0` (**et** `deleted_at NOT NULL`) | `TrashPage.vue:205-210` (badge, à repiquer sur le booléen), `:115` (bandeau) |
| « N suppressions retenues n'ont pas été vidées » | retour de `empty_trash` | **texte neuf**, L0 — sinon « vider » laisse des lignes sans dire pourquoi (`TrashPage.vue:143-158`) |
| *(rien)* | pierre tombale : `purged_at NOT NULL` | invisible par construction |
| « Machine hors ligne » | `connected_sse_devices` | `devices.py:47` ✔ / `fonts.py:575` ✘ |

Trois textes deviennent **faux** et doivent être **réécrits**, pas supprimés : `trash.emptyExplainer` (fr.ts:220 / en.ts:216 — « vider conserve l'empreinte » : la cible dit l'inverse à l'écran), la docstring `frontend/src/stores/trash.ts:6-14`, et le libellé « Dossiers surveillés » (`DevicesSection.vue:304-321`) qui imprimera `/Library/Fonts` verbatim alors qu'il n'alimente plus la bibliothèque. `fr.ts` est typé `typeof en` (`fr.ts:1-3`) : toute clé retirée d'un fichier doit l'être de l'autre **dans le même commit**.

---

## 3. La suppression : marqueur, quarantaine, récolte

### 3.0 Pourquoi la condition littérale du brief ne marche pas

`device_fonts` n'est pas l'inventaire que le brief §3.1 décrit, c'est un **journal de transferts**. Mesuré :

```
SELECT COUNT(*) FROM fonts f WHERE f.deleted_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM device_fonts df WHERE df.font_id = f.id);   →  1015 / 1025
```

Le prédicat « plus aucun appareil ne détient l'empreinte » est donc **VRAI à l'instant même de la suppression** (`fonts.py:692` efface toutes les associations), y compris pour les 84 empreintes dont le fichier est encore dans `/Library/Fonts`. Le brancher tel quel est un générateur de résurrections. **La réconciliation est la pré-étape obligatoire**, pas un raffinement.

### 3.1 La réconciliation

Nouveau service `backend/services/inventory.py`, appelé **depuis le routeur** `backend/routers/sync.py:delta_sync` — jamais depuis `compute_delta`, dont la pureté en lecture est la raison documentée pour laquelle la détection vit déjà dehors (`sync_manager.py:31-42`, `sync.py:63-68`).

```python
async def reconcile_inventory(device_id, entries, font_index, db) -> ReconcileStats:
    """device_fonts devient le MIROIR de ce que la machine déclare."""
    # ÉTAPE 0 — DÉDUPLICATION PAR HASH, AGRÉGATION PAR OU LOGIQUE.
    by_hash: dict[str, DeviceFontEntry] = {}
    for e in entries:
        prev = by_hash.get(e.hash)
        if prev is None or (e.ingestible and not prev.ingestible):
            by_hash[e.hash] = e          # ingestible=True l'emporte TOUJOURS
```

**L'étape 0 n'est pas défensive, elle est nécessaire.** La découverte déduplique par **chemin résolu**, jamais par contenu (`agent/discovery.py:125-128`, `:159-171`), `scan_fonts` ne déduplique rien (`agent/hashing.py:62-93`), et le delta envoie **une entrée par fichier** (`agent/sync_client.py:176-183`). Le dépôt sait que le cas existe : `push_fonts` déduplique explicitement par `file_hash` avec un `seen_hashes` (`agent/sync_client.py:251-256`) ; `compute_delta` s'en tire parce qu'il réduit tout à un set dès la première ligne (`sync_manager.py:55`), ce qui a masqué le problème. Une police installée à la fois pour l'utilisateur et pour tous — Office, Adobe, exactement la population que §2.2 vise — produit deux entrées de même hash, `ingestible=True` puis `False`, dans cet ordre (`agent/config.py:47-51`). Sans l'étape 0 : soit `IntegrityError` sur la PK `(device_id, font_id)` (`models/device_font.py:13-18`) et `POST /api/sync/delta` renvoie 500 à chaque sync, soit « le dernier gagne » stocke `ingestible=0` pour une police que la machine détient *aussi* dans `~/Library/Fonts` — et `compute_delta`, qui agrège par OU, la juge poussable. Les deux moitiés du modèle en désaccord permanent, récolte puis push, **boucle déterministe**. L'agent déduplique aussi côté client, mais le serveur ne doit pas dépendre de la version d'en face pour ne pas se planter sur sa propre clé primaire.

- **ARRIVÉES** — hash déclaré ∧ police connue (**active OU tombée**) ∧ pas d'association → `INSERT` par lots de 500 (patron `_DELETE_BATCH`, `deletion_propagation.py:47`, motivé par la limite de variables liées de SQLite), avec `installed_at = font.created_at` et `local_path = entry.local_path or entry.filename`. **Créer l'association d'une police en corbeille est contre-intuitif et c'est le geste le plus important du chantier** : c'est lui qui protège les 84 empreintes de `/Library/Fonts`. Toute arrivée sur une tombe remet `font.harvest_candidate_since = NULL`.
- **DÉPARTS** — association ∧ police **TOMBÉE** ∧ hash non déclaré → `DELETE` par lots de 500, **sans quarantaine ni notification** (il n'y a rien à quarantiner : la police est déjà hors bibliothèque). Cette branche n'existe pas aujourd'hui — `deletion_propagation.py:115` filtre `Font.deleted_at.is_(None)` (mesuré : 10 associations survivantes sur des tombes, 4 mini / 6 MacBook, toutes `quarantine`). **C'est elle qui débloque la récolte, et c'est le point le plus dangereux du chantier** : les tombes sont invisibles au seuil `propagation_limit`, donc un départ n'est métré par rien. La parade n'est pas ici mais dans le délai de grâce de la récolte (§3.4, G8) : un départ ne détruit qu'une ligne d'index reconstructible, jamais la police.
- **MISE À JOUR** — `local_path` et `ingestible` si la valeur agrégée diffère. En régime établi : 0 écriture.
- Les polices **ACTIVES** non déclarées ne sont **jamais** touchées ici : domaine exclusif de `detect_local_deletions`, avec son seuil et sa quarantaine. Le chemin destructeur n'est ni élargi ni contourné.

**Commutativité par construction** — `detect_local_deletions` cherche (associée ∧ active ∧ non déclarée) ; `reconcile_inventory` n'insère que du déclaré et ne supprime que du tombé. Ensembles disjoints. L'ordre documenté reste imposé et épinglé par un test, en défense en profondeur : une réconciliation placée avant la détection élaguerait les associations que la détection doit lire, et la propagation des suppressions mourrait **en silence, tests verts**.

### 3.2 Nouvel ordre dans `delta_sync` (`backend/routers/sync.py:80-91`)

```python
device   = await _get_device_or_404(body.device_id, db)
declared = {e.hash for e in body.fonts}

# 1. Détection — INCHANGÉE. Lit le registre AVANT la réconciliation.
detection = await detect_local_deletions(device.id, declared, db)

# 2-3. Écritures : uniquement sur une déclaration CRÉDIBLE.
if declared and not detection.pending:
    await reconcile_inventory(device.id, body.fonts, font_index, db)
    device.last_declaration_at = datetime.now(timezone.utc)
    harvested = await harvest_tombstones(db)      # inerte tant que le flag est off

await db.commit()                                 # commit unique
if detection.total:
    await _notify_quarantined(detection, source_device_id=str(device.id))

# 4. Delta — lecture pure, voit ses propres quarantaines et sa propre récolte.
return await compute_delta(body.fonts, db,
                           propagate_deletions=device.propagate_deletions)
```

**`harvest_tombstones` vit DANS la branche de confiance.** La seule passe irréversible du serveur ne doit jamais s'exécuter sur le dos d'une requête que les garde-fous viennent de disqualifier. C'est structurel, pas cosmétique.

`compute_delta` change d'une seule ligne :

```python
ingestible_hashes = {e.hash for e in device_fonts if e.ingestible}
unknown_to_server = list(ingestible_hashes - known_hashes)      # sync_manager.py:83
```

**L'asymétrie est la clé** : `ingestible` n'agit **que** sur `unknown_to_server`. Ni sur `already_synced` (`:89`), ni sur `missing_on_device` (`:86`), ni sur `detect_local_deletions`. `known_hashes = actives ∪ tombées` (`:78-83`) reste intact — le restreindre aux polices vivantes remettrait chaque tombe en « inconnue » et ferait repousser toute la corbeille à chaque sync.

`compute_delta` conserve sa propre lecture de `fonts` (elle doit s'exécuter **après** le commit pour voir quarantaines et récolte). La détection et la réconciliation partagent un index chargé une fois. Coût net : un scan de `fonts` en plus par delta (6 205 lignes).

### 3.3 Cycle de vie complet d'une police

```
                     upload / push
                          │
                          ▼
   ┌──────────────────────────────────────────┐
   │ EN BIBLIOTHÈQUE   deleted_at NULL        │◄──── restore  (fonts.py:752)
   │ détenteurs : lignes device_fonts         │◄──── ré-upload (font_importer.py:134)
   └──────────────────────────────────────────┘         │ toutes deux EFFACENT
        │ delete_font / duplicates/resolve               │ les associations (§3.5)
        │ ou detect_local_deletions
        ▼
   ┌──────────────────────────────────────────┐
   │ CORBEILLE   deleted_at posé, purged NULL │  visible, restaurable
   │ deletion_confirmed = 1 (manuelle,        │
   │   ou quarantaine sous le seuil)          │
   │ deletion_confirmed = 0 (au-delà du seuil)│  visible, badge ambre, NON propagée
   └──────────────────────────────────────────┘
        │ empty_trash / purge — REFUSÉS si deletion_confirmed = 0
        ▼
   ┌──────────────────────────────────────────┐
   │ PIERRE TOMBALE   purged_at posé          │  INVISIBLE, non restaurable (409)
   │ protège tant qu'un détenteur ingestible  │  refuse le push (sync.py:150-165)
   └──────────────────────────────────────────┘
        │ plus aucun détenteur ingestible, toutes les machines ont re-déclaré,
        │ délai de grâce écoulé
        ▼
   ┌──────────────────────────────────────────┐
   │ RÉCOLTÉE — la ligne n'existe plus        │  IRRÉVERSIBLE
   └──────────────────────────────────────────┘
```

**L'invariant gratuit devient un vrai garde-fou** : `empty_trash`, `POST /{id}/purge` et `purge_expired` refusant tous les trois une suppression non confirmée, une quarantaine en attente garde **toujours** `purged_at IS NULL`, donc n'est **jamais** récoltable. G3 et G4 se recouvrent — c'est le prix d'un garde-fou, on l'écrit deux fois.

### 3.4 Condition exacte de la récolte (`backend/services/harvest.py`)

Deux phases, une seule transaction, appelées depuis la branche de confiance de `delta_sync`. Une récolte ne peut devenir vraie qu'à la suite d'une déclaration : un janitor de fond tournerait à vide entre les syncs.

```sql
-- PHASE 1 — ouverture de candidature. Aucune suppression.
UPDATE fonts SET harvest_candidate_since = :now
WHERE deleted_at              IS NOT NULL
  AND purged_at               IS NOT NULL                                  -- G3
  AND deletion_confirmed       = 1                                         -- G4
  AND harvest_candidate_since IS NULL
  AND EXISTS (SELECT 1 FROM devices d WHERE d.deleted_at IS NULL)          -- G5
  AND NOT EXISTS (SELECT 1 FROM device_fonts df
                  WHERE df.font_id = fonts.id AND df.ingestible = 1)       -- G6
  AND NOT EXISTS (SELECT 1 FROM devices d
                  WHERE d.deleted_at IS NULL
                    AND (d.last_declaration_at IS NULL
                         OR d.last_declaration_at <= fonts.deleted_at));   -- G7

-- PHASE 2 — récolte.
SELECT f.id FROM fonts f
WHERE f.deleted_at              IS NOT NULL
  AND f.purged_at               IS NOT NULL                                -- G3
  AND f.deletion_confirmed       = 1                                       -- G4
  AND f.harvest_candidate_since IS NOT NULL
  AND f.harvest_candidate_since <= :now - :grace                           -- G8
  AND EXISTS (SELECT 1 FROM devices d WHERE d.deleted_at IS NULL)          -- G5
  AND NOT EXISTS (SELECT 1 FROM device_fonts df
                  WHERE df.font_id = f.id AND df.ingestible = 1)           -- G6
  AND NOT EXISTS (SELECT 1 FROM devices d
                  WHERE d.deleted_at IS NULL
                    AND (d.last_declaration_at IS NULL
                         OR d.last_declaration_at <= f.harvest_candidate_since))  -- G8
LIMIT :max_per_pass;                                                       -- G9
```

Puis, **dans la même transaction** et **dans cet ordre** (`PRAGMA foreign_keys=ON`, `database.py:19`) :

```sql
SELECT DISTINCT family_id FROM font_family_members WHERE font_id IN (:ids);
DELETE FROM font_family_members WHERE font_id IN (:ids);
DELETE FROM device_fonts        WHERE font_id IN (:ids);   -- non-ingestibles restantes
DELETE FROM fonts               WHERE id      IN (:ids);
UPDATE font_families SET style_count =
   (SELECT COUNT(*) FROM font_family_members m WHERE m.family_id = font_families.id)
 WHERE id IN (:familles_touchées);
DELETE FROM font_families
 WHERE id IN (:familles_touchées) AND style_count = 0 AND is_auto_grouped = 1;
```

Le dernier `DELETE` ferme un défaut mesuré : `list_families` (`routers/font_families.py:109-130`) ne filtre ni sur `style_count > 0` ni sur l'existence d'un membre. Sans lui, la récolte laisse des familles fantômes à `styleCount: 0`. Mesuré sur l'instantané : **1** famille deviendrait vide, et les **569** familles sont `is_auto_grouped = 1` — on ne détruit jamais une famille créée à la main.

Journalisation **WARNING** avec décompte et identifiants : c'est le **premier `DELETE` de l'histoire du schéma sur la table `fonts`** (vérifié : les seules suppressions dures du dépôt portent sur `FontFamilyMember`/`FontFamily`, `family_grouper.py:199-205`). Aucun événement WebSocket : les lignes étaient déjà invisibles.

**Les neuf garde-fous**

| # | Garde-fou | Ce qu'il ferme |
|---|---|---|
| G1 | **Déclaration vide → on ne conclut rien** : ni détection, ni réconciliation, ni horodatage, ni récolte | Extension du garde-fou existant (`deletion_propagation.py:97-103`). Sans lui, un dossier démonté viderait l'inventaire d'une machine et rendrait toute la corbeille candidate en un sync raté. |
| G2 | **Déclaration suspecte** (`detection.pending` non vide) → mêmes conséquences | Réutilise le seuil existant (`propagation_limit`, `deletion_propagation.py:66-76`, `config.py:36-41`) : gratuit. |
| G3 | `purged_at IS NOT NULL` | Récolter une ligne non purgée abandonnerait le blob (`storage.py:40-44`). |
| G4 | `deletion_confirmed = 1` | Une quarantaine en attente ne disparaît jamais toute seule. |
| G5 | `EXISTS (… devices WHERE deleted_at IS NULL)` | Sur un serveur sans machine, G6 et G7 seraient vrais par vacuité et toute la corbeille partirait au premier delta. |
| G6 | **Aucun détenteur ingestible**, appareils soft-supprimés **compris** | La formulation du brief §3.1 raffinée par §2.2 : c'est ce raffinement qui libère les ~84 empreintes. Un appareil retiré de l'UI continue de protéger ce qu'il détient. |
| G7 | **Toutes les machines vivantes ont déclaré depuis la suppression** | Couvre l'intervalle entre `delete_font` (qui efface les associations, `fonts.py:692`) et le delta suivant de chaque machine — l'intervalle où « aucun détenteur » est trivialement vrai. Rend aussi le déploiement **auto-séquencé** : après L1, `last_declaration_at` est NULL partout. |
| G8 | **Délai de grâce** : candidature ouverte depuis `tombstone_harvest_grace` (défaut 24 h) **et** toutes les machines vivantes ont re-déclaré **depuis l'ouverture** | **Le garde-fou qui rend une omission de déclaration non fatale.** L'agent perd silencieusement toute police dont `stat()`/`open()` lève `OSError` (`agent/hashing.py:85-88`), ignore en `debug` un dossier momentanément absent (`agent/discovery.py:111-113`), et son en-tête de module énonce que l'index Core Text se fige (`agent/discovery.py:5-14`). La déclaration suivante recrée l'association et remet `harvest_candidate_since` à NULL : **rien n'a été détruit entre-temps**. Sans G8, une seule déclaration incomplète suffit à récolter une tombe dont le fichier est encore poussable — et la police revient au sync d'après, en boucle. |
| G9 | `tombstone_harvest_max_per_pass` + log par identifiant + `tombstone_harvest_enabled` | Le flag protège d'une **erreur de raisonnement** (livrer inerte, lire les chiffres, puis autoriser) ; G7/G8 protègent d'une **erreur d'ordonnancement** et d'une **erreur de mesure**. Trois risques, trois protections. Le plafond démarre à **5** au premier cycle réel, pas à 200. |

### 3.5 Cas limites, un par un

- **Police jamais associée à un appareil** (uploadée depuis le web, jamais pullée). Sa ligne `device_fonts` n'existe pas et n'existera pas. Elle devient candidate dès G3+G7, récoltée après G8. **C'est correct** : rien ne peut la ressusciter. Aujourd'hui ce cas est indiscernable du cas dangereux parce que `fonts.py:692` détruit exactement l'information qui les sépare ; la réconciliation la rétablit.
- **Machine éteinte au moment de la suppression.** G7 gèle la récolte tant qu'elle n'a pas re-déclaré. À son retour, si elle détient encore le fichier ingestiblement, elle recrée l'association (G6 bloque) et reçoit `to_uninstall`. C'est le scénario qui *justifie* la pierre tombale, et **aucun test ne le joue** (§7).
- **Machine éteinte depuis des mois.** G7 gèle toute la corbeille. **C'est le bon échec, et il est indolore** : sous la règle d'affichage cible, une pierre tombale n'est listée nulle part ; une récolte gelée ne coûte que des lignes invisibles. Cette asymétrie autorise à être maximalement conservateur.
- **Appareil retiré depuis l'interface.** `delete_device` fait aujourd'hui un hard delete de l'appareil *et* de ses associations (`devices.py:242-245`) derrière un simple `window.confirm` (`DevicesSection.vue:88-95`), alors que les fichiers sur le Mac ne bougent pas. Sous le modèle cible, **cela relâche G6 et G7 au lieu de les resserrer** : la ligne quitte `devices` donc cesse d'être quantifiée, ses associations partent, et les 1 025 tombes deviennent candidates en bloc. Le ré-enregistrement par hostname (`devices.py:74-78`) gèle les récoltes *suivantes* mais ne défait pas celles déjà faites — puis la machine repousse tout ce qu'elle détient encore (`auto_push=1` sur les deux). **Décision : `devices` passe en soft delete** (`deleted_at`, convention `CLAUDE.md`). L'appareil sort de l'UI, ses associations restent, G6 continue de le compter, G7 cesse de l'attendre. `register_device` le ranime. `merge_devices` (`devices.py:139-206`) soft-supprime ses sources **après** avoir déplacé leurs associations, donc n'ouvre rien. Un 409 bloquant serait un cul-de-sac : l'utilisateur ne peut pas vider des tombes qu'il ne voit pas.
- **Boucle restauration → re-quarantaine** (invariant I4, `tests/backend/test_deletion_propagation.py:600`). Séquence de régression **créée par la réconciliation** : suppression → la machine détient encore le fichier et le déclare → l'association est recréée → `to_uninstall` → elle désinstalle → l'utilisateur restaure → au delta d'après la police est active, associée, non déclarée → **re-quarantinée avec propagation**. **Parade obligatoire, dans le même commit que la réconciliation** : `restore_font` (`fonts.py:752`) et `_revive_if_deleted` (`font_importer.py:134`) effacent les associations de la police, comme `delete_font` (`:692`) et `resolve_duplicate_faces` (`duplicate_faces.py:283`) le font déjà. **Invariant à écrire noir sur blanc : tout franchissement de la frontière supprimée ↔ active remet l'inventaire de cette police à zéro ; chaque machine le réinscrit à son propre delta suivant.** Quatre sites, deux existent, deux sont à ajouter.
- **Course avec un push en vol.** Structurellement impossible sur le chemin normal : l'agent ne pousse que ce que le delta a listé (`sync_command.py:208-214`, `sync_client.py:251-256`), or une police récoltée ne peut l'avoir été que si aucun détenteur ingestible ne la déclarait. La course étroite restante (récolte entre le `SELECT` de `compute_delta` et un push sans delta préalable) est **inoffensive** : `import_font` réinsère par hash unique (`font_importer.py:96`) et la police revient — comportement attendu d'un push explicite.
- **Les ~84 pendant la fenêtre L1→L5.** La réconciliation recrée leurs associations, la récolte est inerte : `to_uninstall` contient ces 84 références à chaque sync du mini et `uninstall_font` renvoie `False` (il ne cherche que dans `INSTALL_DIR` et `DISABLED_DIR`, `agent/font_installer.py:222`), compté en `uninstall_missing`. **Bruit préexistant, borné par la récolte** — ne pas le confondre avec une régression pendant l'observation des paliers.

### 3.6 Effet attendu sur la production

- **L0, sans migration** : l'écran corbeille passe de **1 025 lignes inertes à 0**, par le seul filtre de visibilité.
- **Après L5** : sont récoltables les 1 015 tombes sans détenteur, **plus** celles dont le seul détenteur est non ingestible (les ~84 de `/Library/Fonts`), **plus** les 10 `quarantine` dont un détenteur cesse de déclarer. Ordre de grandeur : **la corbeille tombe à zéro ligne en base**, étalée sur plusieurs cycles par G8 et G9.

---

## 4. `/Library/Fonts` : scanner sans ingérer

### 4.1 Ce qui change côté agent

| Fichier | Changement |
|---|---|
| `agent/config.py:47-51` | `DEFAULT_MACOS_DIRECTORIES` **INCHANGÉ**. Nouvelle clé `scan.ingest_directories`, défaut `[~/Library/Fonts]`, ajoutée **à la fois** dans `load()` (`:111`) et dans `save()` (`:133-135`) — `save()` réécrit tout le fichier depuis les seuls champs qu'il connaît, une clé absente de l'un des deux disparaît en silence. Compatible avec le mini-parseur Swift, qui ne touche que le bloc `server:` et préserve `scan:` verbatim (`macos-app/FontSync/AppConfig.swift:15`, `:139`, `:192`). |
| `agent/discovery.py:34-38` | `DiscoveredFont` gagne `ingestible: bool`. |
| `agent/discovery.py:130` **et** `:87` | Le drapeau est posé **dans les deux sources**, sur le chemin **résolu**, avec `Path.is_relative_to` — jamais un préfixe de chaîne (`~/Library/Fonts` vaut `/Users/leo/Library/Fonts`). **Point critique** : `discover_via_core_text` code `/Library/Fonts` en dur dans `allowed_prefixes` (`:65-68`), hors de toute configuration, et `discover_fonts` réinjecte par union (`:159-171`). |
| `agent/hashing.py:26-33` | `ScannedFont` propage `ingestible`. |
| `agent/sync_client.py:169-185` | `"ingestible": f.ingestible` dans chaque entrée ; **déduplication par hash avec OU logique avant l'envoi** (le serveur la refait, §3.1). |
| `agent/sync_command.py:208` | `unknown &= {f.file_hash for f in scanned if f.ingestible}` ; compteur `push_out_of_scope` dans `SyncResult` (`:79-129`). Coût réel nul : `push_fonts` filtre déjà par set de hashes (`sync_client.py:251-256`). |
| `agent/sync_command.py:264` | `~/.fontsync/disabled/` → **`ingestible=True` forcé**. `DISABLED_DIR = state_dir()/"disabled"` (`font_installer.py:43`) n'est sous aucun `ingest_directories` : le calcul générique donnerait `False`. Oublier cet override ferait cesser de protéger la tombe d'une police simplement désactivée sur un appareil à `propagate_deletions=false` (**le défaut**, `models/device.py:30-32`) ; `activate_font` (`font_installer.py:261`) la remettrait dans `~/Library/Fonts`, elle redeviendrait ingestible, elle serait poussée. Le mécanisme `SyncResult.deactivated` (`:85`, testé `tests/agent/test_sync_command.py:238`) est **vivant** : ne pas le confondre avec `DeviceFont.activated`. |
| `agent/launchd/com.fontsync.sync.plist:39-43` | **INCHANGÉ** : `/Library/Fonts` reste en `WatchPaths` — un changement là modifie ce que la machine possède, donc sa déclaration. |

### 4.2 Ce qui ne change pas — et pourquoi c'est le piège n°1

**La déclaration reste complète.** On ne retire `/Library/Fonts` ni de `scan.directories`, ni de `discover_fonts`, ni du plist. Trois raisons, par gravité décroissante :

1. **Ça ne marcherait pas.** `discover_via_core_text` réinjecte `/Library/Fonts` hors de toute configuration (`discovery.py:65-68`, `:159-171`) : l'exclusion serait partielle et **non déterministe**, dépendante de l'état de l'index macOS qui se fige. Des quarantaines intermittentes, ni reproductibles ni imputables.
2. **Si ça marchait, ce serait la catastrophe.** Mesuré : **551** lignes `device_fonts` du Mac mini pointent `/Library/Fonts`, **toutes sur des polices vivantes**, et pour les 551 le mini est le **seul** détenteur (`sys-only-holder-live → 551`). Retirées de la déclaration, elles tombent toutes dans `detect_local_deletions` (`deletion_propagation.py:112-119`). Le seuil vaut `max(3, min(25, 5 %×~4 630)) = 25` : 551 > 25 → quarantaine **en attente**, aucun fichier effacé sur le MacBook, mais **551 polices hors bibliothèque en un sync**, 551 broadcasts `font.deleted`, et aucune restauration groupée (`/restore` est unitaire, `fonts.py:729`).
3. **Le symétrique est aussi mauvais, mais sur une autre population.** Retirer un hash de la déclaration le fait entrer dans `active_hashes - device_hashes` (`sync_manager.py:86`) → `missing_on_device` → `auto_pull=1` le **retélécharge** dans `~/Library/Fonts` : le même fichier deux fois sur le disque. Ce cas et le précédent **s'excluent police par police** — `detect_local_deletions` tourne avant `compute_delta` (`sync.py:82-89`) et une police quarantinée quitte `active_hashes`. Le point 3 ne vaut donc que pour les polices **sans association**, c'est-à-dire les 2 155 du trou `already_synced` (`sync_manager.py:89`), en pratique le MacBook.

**Ce qui change, c'est la candidature au push, pas la découverte.**

### 4.3 Protection contre la fausse détection au premier sync — sept couches

1. **La déclaration ne rétrécit jamais** (§4.2). Protection de fond.
2. **Asymétrie d'`ingestible`** : il n'agit que sur `unknown_to_server` (`sync_manager.py:83`), jamais sur `already_synced`, `missing_on_device` ni `detect_local_deletions`.
3. **Défaut `True` partout, dans les deux sens** : Pydantic **et** `server_default '1'`.
4. **Serveur avant agent** (§5.2).
5. **G1 et G2** : déclaration vide ou suspecte → aucune écriture.
6. **Critères d'acceptation, énoncés avant le déploiement.** Au **premier** delta de chaque machine sous L1 : `DeletionDetection.total == 0` dans les logs. Au **deuxième** delta de chaque machine : `DeletionDetection.total == 0` encore — c'est le premier qui s'exécute sur un registre complet, donc **le delta risqué**. Si l'un des deux ne vaut pas 0, on arrête et on restaure.
7. **La récolte est triplement inerte** au premier sync : flag off, `last_declaration_at IS NULL` (G7), candidature pas encore ouverte (G8).

### 4.4 Impact chiffré sur les 2 appareils de prod

**Effet de L1 sur les données : uniquement des `INSERT` dans `device_fonts`.** Aucune ligne `fonts` touchée, aucune suppression.

| | Avant L1 | Après réconciliation |
|---|---|---|
| Mac mini (`9e6343d6…`) | 5 184 (5 180 vivantes + 4 tombes) | + les tombes qu'il détient encore, dont les ~84 de `/Library/Fonts` |
| MacBook Pro (`aef3f593…`) | 3 031 (3 025 vivantes + 6 tombes) | → sa déclaration complète, soit **~2 100 arrivées** |
| Total | **8 215** | **~10 400** |

**Élargissement du rayon de souffle — à porter au changelog.** Rendre `device_fonts` fidèle fait entrer dans le champ de `detect_local_deletions` les polices qui tombaient dans `already_synced` sans jamais créer d'association. Mesuré : **2 155 polices vivantes n'ont qu'un détenteur enregistré** (le mini couvre les 5 180, le MacBook 3 025). C'est une **correction de bug** — supprimer une police sur le MacBook n'a aujourd'hui aucun effet pour 2 155 polices — **et** une extension du domaine du chemin destructeur : un scan raté sur le MacBook pouvait perdre au pire 3 025 polices, il peut en perdre ~5 180. Sous le seuil de 25, une disparition **se propage** et le mini (`propagate_deletions=1`) efface les fichiers. **Le seuil n'est pas modifié** (il est bon), mais L1 livre un log WARNING chiffré à chaque delta comparant `len(declared)` à la taille du registre **avant** réconciliation : « le registre du MacBook a doublé d'un coup » doit être un fait attendu et vérifié, pas un effet de bord découvert. **Ce chantier rend la détection de suppressions réellement active sur les deux machines pour la première fois.**

---

## 5. Plan de migration

### 5.1 Révisions Alembic

Convention suivie à la lettre, celle de `b7c31a4d90e2` : docstring **française** qui justifie chaque colonne, `batch_alter_table` (`alembic/env.py:29`, `:40` posent `render_as_batch=True`), `server_default` explicite sur tout NOT NULL ajouté à une table peuplée (`b7c31a4d90e2:41-48`), backfill en `op.execute` précédé du commentaire qui le justifie, `downgrade()` en ordre inverse strict. Identifiants hexadécimaux générés par Alembic ; seuls les slugs sont fixés ici. Révision de départ : **`b7c31a4d90e2`**.

**Contrainte de conception commune à M1 et M2 : aucune recréation de table.** `alembic.ddl.sqlite.SQLiteImpl.transactional_ddl` vaut **`False`** (vérifié) : une migration SQLite n'est pas atomique, et un processus tué entre le `DROP` et le `RENAME` d'un batch laisse la table détruite et un `_alembic_tmp_*` qui fait échouer tout redémarrage en boucle. `ADD COLUMN` et `CREATE INDEX` sont natifs et ne recréent rien ; `alter_column` et `drop_column` recréent. **C'est pour cela que `local_path` reste `NOT NULL`** (§1, ligne 14) : le rendre nullable coûterait une recréation de `device_fonts` pour de la cosmétique.

#### M1 — `inventory_mirror` (revises `b7c31a4d90e2`) — additive pure, aucune recréation

```python
def upgrade() -> None:
    with op.batch_alter_table("devices") as b:
        b.add_column(sa.Column("last_declaration_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("deleted_at",          sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("device_fonts") as b:
        b.add_column(sa.Column("ingestible", sa.Boolean(), nullable=False, server_default="1"))
    op.create_index("ix_device_fonts_font_id", "device_fonts", ["font_id"])

def downgrade() -> None:
    op.drop_index("ix_device_fonts_font_id", table_name="device_fonts")
    with op.batch_alter_table("device_fonts") as b:
        b.drop_column("ingestible")            # recrée device_fonts — downgrade uniquement
    with op.batch_alter_table("devices") as b:
        b.drop_column("deleted_at")
        b.drop_column("last_declaration_at")
```

**Backfill : aucun.** `last_declaration_at` naît NULL sur les 2 appareils — c'est ce qui tient la récolte gelée. `ingestible` naît à 1 partout — la direction sûre.

**Code livré avec** : `reconcile_inventory` (dédup par hash incluse) + son appel, l'horodatage, l'effacement d'associations ajouté à `restore_font` et `_revive_if_deleted`, `DeviceFontEntry.ingestible`, l'asymétrie dans `compute_delta`, le soft delete de `devices` (`delete_device`, `merge_devices`, `list_devices`, `register_device`, `fonts.py:566`), et **`harvest_tombstones` livré INERTE** qui **logge à chaque passage le nombre de lignes qu'il récolterait**. C'est la répétition à blanc sur les vraies données.

#### M2 — `deletion_confirmed_flag` (revises M1) — additive + backfill de 1 025 lignes

```python
def upgrade() -> None:
    with op.batch_alter_table("fonts") as b:
        b.add_column(sa.Column("deletion_confirmed", sa.Boolean(), nullable=False, server_default="0"))
        b.add_column(sa.Column("harvest_candidate_since", sa.DateTime(timezone=True), nullable=True))
    # Traduction littérale de PROPAGATING_DELETION_REASONS (models/font.py:39) :
    # seuls 'manual' et 'quarantine' descendaient jusqu'aux appareils. Forme
    # LISTE BLANCHE : un motif NULL ou inattendu reste NON confirmé, donc inerte.
    op.execute("UPDATE fonts SET deletion_confirmed = 1 "
               "WHERE deleted_at IS NOT NULL AND deleted_reason IN ('manual','quarantine')")

def downgrade() -> None:
    with op.batch_alter_table("fonts") as b:
        b.drop_column("harvest_candidate_since")
        b.drop_column("deletion_confirmed")
```

**Backfill mesuré** : `manual|purged=1|1015` + `quarantine|purged=1|10`, **zéro `quarantine_pending`**, zéro ligne supprimée sans motif, zéro ligne vivante avec motif. Le backfill est exact et sans ambiguïté. `deleted_reason` **reste en place** à ce stade : M2 est donc **entièrement réversible sur le schéma comme sur le sens**, contrairement à une fusion en une seule révision.

**Code livré avec** : double écriture pendant une révision (les 6 écrivains posent `deleted_reason` **et** `deletion_confirmed`), **lecture uniquement sur le booléen**. Les 6 écrivains, dans le même commit — `fonts.py:684`, `:407`, `:753`, `duplicate_faces.py:275`, `deletion_propagation.py:131`, `font_importer.py:135`. **Le plus facile à rater est le dernier** : il remet trois marqueurs à zéro d'un geste et ne ressemble pas à un chemin de suppression. Requête de cohérence à rejouer après **chaque** palier tant que la double écriture est en place :

```sql
SELECT COUNT(*) FROM fonts
WHERE (deleted_at IS NOT NULL AND ((deleted_reason IN ('manual','quarantine')) <> (deletion_confirmed = 1)))
   OR (deleted_at IS     NULL AND deletion_confirmed = 1);      -- DOIT valoir 0
```

**Règle absolue de traduction** : la valeur d'enum `quarantine_pending` **impliquait** `deleted_at IS NOT NULL` ; le booléen à `server_default '0'` est partagé par les 5 180 polices vivantes. **Toute lecture de `deletion_confirmed` porte les deux clauses.** Le site que la traduction littérale casserait : `fonts.py:402-404` (`/trash/confirm`) s'écrit aujourd'hui `select(Font).where(Font.deleted_reason == DELETION_PENDING)` sans clause `deleted_at`. Traduit tel quel, un clic sur « Confirmer et propager » (`TrashPage.vue:129-137`) passe **toute la bibliothèque** à `deletion_confirmed = 1`, logge « 5180 quarantaine(s) confirmée(s) » et déclenche `broadcast_sync()`. Aucun test n'observe la table après confirm.

#### M3 — `drop_dead_columns` (revises M2) — la seule qui recrée des tables

```python
def upgrade() -> None:
    with op.batch_alter_table("device_fonts") as b:
        b.drop_column("activated")
    with op.batch_alter_table("devices") as b:
        b.drop_column("sync_status")
        b.drop_column("last_sync_at")
    with op.batch_alter_table("fonts") as b:          # une seule recréation de `fonts`
        b.drop_column("deleted_reason")
        b.drop_column("storage_path")

def downgrade() -> None:
    with op.batch_alter_table("fonts") as b:
        b.add_column(sa.Column("storage_path",   sa.String(500), nullable=False, server_default=""))
        b.add_column(sa.Column("deleted_reason", sa.String(30),  nullable=True))
    # Le chemin est déterministe (services/storage.py:40-44) : reconstruction exacte.
    op.execute("UPDATE fonts SET storage_path = "
               "substr(file_hash,1,2) || '/' || file_hash || '.' || file_format")
    # Reconstruction du motif : FIDÈLE AU COMPORTEMENT, approximative sur le libellé.
    # 'manual' et 'quarantine' sont interchangeables pour PROPAGATING_DELETION_REASONS ;
    # ce que le downgrade doit restituer, c'est le VERROU, et il le restitue exactement.
    op.execute("UPDATE fonts SET deleted_reason = "
               "CASE WHEN deletion_confirmed = 1 THEN 'manual' ELSE 'quarantine_pending' END "
               "WHERE deleted_at IS NOT NULL")
    with op.batch_alter_table("devices") as b:
        b.add_column(sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("sync_status",  sa.String(20), nullable=False, server_default="idle"))
    with op.batch_alter_table("device_fonts") as b:
        b.add_column(sa.Column("activated", sa.Boolean(), nullable=False, server_default="1"))
```

`server_default` obligatoire au retour : la baseline déclare `sync_status` NOT NULL sans défaut (`fbca947b83c5`) et 2 lignes existent. Les valeurs recréées (`'idle'`, NULL, 1) sont **exactement** celles observées en production.

**Pas de `copy_from`.** Mesuré par réflexion en lecture seule sur l'instantané réel : `inspect(engine).get_unique_constraints('fonts')` → `[{'name': None, 'column_names': ['file_hash']}]`, `get_indexes('fonts')` → les 5 `ix_fonts_*`, `get_check_constraints('fonts')` → `[]`, et `CreateTable(Table('fonts', autoload_with=conn))` régénère `UNIQUE (file_hash)` à l'identique. La réflexion ne perd rien. À l'inverse, `copy_from` coupe la réflexion et fait autorité sur les colonnes **et** les index : une colonne oubliée dans une transcription manuelle de 35 colonnes part silencieusement à la poubelle sur 6 205 lignes, et un `Index` oublié efface les 5 index. **On prescrit donc l'option la plus sûre : laisser réfléchir**, et vérifier après coup (§5.4).

**`PRAGMA foreign_keys` doit rester OFF pendant les migrations**, et la docstring de M3 doit le dire. `alembic/env.py:45-54` construit son propre engine, sans le listener de `backend/database.py:12-22` : ce n'est pas une négligence, c'est **la condition d'exécution** de la stratégie copy-and-move. Avec l'enforcement actif, le `DROP TABLE devices` d'un batch déclenche le DELETE implicite sur les enfants `device_fonts` (deux FK anonymes vérifiées dans le DDL réel) et échoue. La vérification d'intégrité se fait **après**, par `PRAGMA foreign_key_check`.

**Code livré avec** : suppression complète de `/ws/agent/{device_id}` (`routers/ws.py:52-195`), du registre agent de `ws_manager` (`connect_agent` `:37`, `broadcast_to_agents` `:85`, `send_to_agent` `:97`, `agent_count` `:160`, `connected_agents` `:164`), des deux appelants orphelins (`sync.py:195`, `font_families.py:262`), de la référence en `ws.py:35`, des trois endpoints 501 conservés ou non (§6), et de tout le nettoyage frontend/i18n nominatif de §6. **Attention** : retirer `/ws/agent` retire aussi le heartbeat qui écrit `last_seen_at` (`ws.py:87`) — champ **vivant**, alimenté redondamment par le register HTTP (`devices.py:90`, appelé à chaque sync) ; vérifier qu'il continue de bouger.

### 5.2 Ordre de déploiement agent / serveur / app macOS

**Le serveur avant l'agent est l'unique contrainte d'ordre dure du chantier.** Le serveur seul est un **no-op intégral** : sans agent à jour, `ingestible` vaut `True` partout et le filtre de push ne mord sur rien. L'agent seul **change le comportement** — il cesse de pousser ce que le serveur continue de lui réclamer dans `unknownToServer` — sans que le serveur le sache : incohérence silencieuse. Et la récolte n'est activée qu'**après** que les deux agents ont basculé et resynchronisé : tant qu'un dossier non nettoyable peut pousser, une ligne récoltée revient.

**L'agent est embarqué dans l'app macOS, et Sparkle publie à tout le monde d'un coup.** `SUEnableAutomaticChecks=true`, `SUScheduledCheckInterval=86400` (`macos-app/Info.plist:36-39`), `SUFeedURL` = `releases/latest/download/appcast.xml` (`:32-33`), et `scripts/publish-release.sh:67` exécute `gh release edit --draft=false --latest`. Les deux Macs verraient la mise à jour dans les 24 h, indépendamment l'un de l'autre, et rien n'empêcherait un Mac de passer en 0.2.0 avant que le serveur soit à jour. **Décision : pour ce palier, installer le `.dmg` machine par machine à la main et ne PAS publier la release en `--latest` tant que les deux Macs n'ont pas basculé** (ou la marquer en pré-release). Mini d'abord, un cycle d'observation, puis MacBook.

**Rituel d'arrêt, avant chaque palier migré.** `launchctl bootout` de `com.fontsync.listen` **et** `com.fontsync.sync` sur les deux Macs, **et quitter l'app FontSync** : le bouton « Synchroniser » du menu retombe sur `AgentController.sync()` — un `python -m agent sync` direct — quand `LaunchdStatus.kickstartSync()` échoue faute de job chargé (`AppModel.swift:166-167`, `LaunchdStatus.swift:28-31`, `AgentController.swift:111`). Raison de l'arrêt : le flux SSE émet un signal `sync` **dès la connexion** (`routers/agent_events.py:43`) et `broadcast_sync` réveille tous les abonnés d'un coup (`ws_manager.py:143-153`) — **il n'y a pas de fenêtre calme après un redémarrage**. Toute mesure avant/après faite agents allumés mesure un état déjà modifié. *Contrepartie rassurante : l'agent est fail-safe face à un serveur en migration — `_send` lève `SyncClientError` après 3 tentatives (`sync_client.py:111-131`) et `run_sync` lève `SyncError` avant tout push, pull ou désinstallation (`sync_command.py:188-191`). L'arrêt est une exigence de MESURE, pas de sûreté.*

**Prérequis technique de tout palier qui migre : `connect_args={"timeout": 30}` dans `backend/database.py:8`, livré en L0.** Aujourd'hui `POST /api/sync/delta` ne commit que si `detection.total` (`sync.py:85-87`) ; après L1 il écrit à chaque appel. Le premier delta L1 du MacBook insère ~2 100 associations pendant que le mini, réveillé par le même `broadcast_sync`, poste son propre delta. WAL sérialise les écrivains, le busy timeout pysqlite par défaut est de 5 s, et `agent/sync_client.py:46` ne réessaie **que** les erreurs de transport : un `database is locked` remonte en `HTTPStatusError` hors de `_TRANSIENT_ERRORS`, la sync échoue sèchement jusqu'au prochain déclenchement launchd. La réconciliation est en outre lotie par 500 avec des commits bornés, et la récolte plafonnée à **5** au premier cycle.

### 5.3 Points de non-retour et plan de retour arrière

| Moment | Ce qui devient irréversible |
|---|---|
| **M1 — première migration appliquée** | **Point de non-retour sur l'IMAGE, et il arrive bien plus tôt que le retrait des colonnes.** L'entrypoint fait `set -e` puis `alembic upgrade head` avant `exec uvicorn` (`scripts/docker-entrypoint.sh:11`, `:30`) et le dossier `alembic/versions/` est **figé dans l'image** (`Dockerfile:39-40`). Une image antérieure lit `alembic_version = <M1>`, ne trouve pas la révision et lève `CommandError: Can't locate revision identified by '<M1>'` — **vérifié** en exécutant `ScriptDirectory._upgrade_revs('head', '<inconnu>')` sur ce dépôt. Le conteneur ne démarre jamais (crash loop si `restart:` est posé). **« Réversibilité : swap de tag » est faux dès le premier palier migré.** |
| **Premier delta exécuté sous L1** | Les ~2 100 associations créées ne se défont pas. `downgrade()` retire les colonnes, pas les lignes : sous le code L0 revenu, la surface de `detect_local_deletions` sur le MacBook reste passée de 3 025 à sa déclaration complète, **sans** G2 ni la remise à zéro des associations à la restauration que L1 livrait avec. M1 est réversible **sur le schéma, pas sur les données**. |
| **Activation de la récolte (L5, aucune migration)** | **Point de non-retour sur les DONNÉES.** Les lignes `fonts` récoltées disparaissent avec leurs `font_family_members` et leurs associations. Le blob a déjà quitté le stockage (G3) : un ré-upload recréerait une ligne **neuve, d'identifiant différent**. |
| **Rétrogradation de l'agent après L5** | **Le palier agent cesse d'être réversible.** Un agent 0.1.0 ne connaît pas `ingestible` ; le défaut `True` du contrat s'applique, et les ~84 empreintes récoltées — dont la ligne `fonts` n'existe plus — redeviennent `unknown_to_server` et sont poussées. Rien ne peut plus les faire sortir durablement. |

**Le plan de retour n'est pas `alembic downgrade`.** Le `downgrade()` de la révision **actuelle** supprime `deleted_reason` (`b7c31a4d90e2:62-64`) et son `upgrade()` re-backfille `'manual'` sur toute ligne supprimée sans motif (`:52-55`) : un aller-retour transformerait des quarantaines retenues en suppressions **propageables**, sur deux machines à `propagate_deletions = 1`. Les `downgrade()` restent écrits et testés (règle projet) pour la réversibilité en développement et pour prouver qu'on sait défaire ce qu'on fait — **pas** comme procédure d'urgence.

**Procédure de retour officielle, exacte :**

1. `docker compose down` (arrêt complet, pas un restart).
2. Sur le volume de données : **supprimer `fontsync.db-wal` et `fontsync.db-shm`** avant de poser le `.db` de l'instantané. La base tourne en WAL (`database.py:20`) et l'instantané de référence est lui-même accompagné d'un `-wal` et d'un `-shm` de 32 Ko : déposer le seul `.db` fait rejouer des frames étrangères sur une base restaurée.
3. Remettre le tag d'image précédent, `docker compose up -d`.
4. **Garder les agents éteints pendant ET après**, le temps d'auditer la corbeille : la restauration ramène l'état du 10 août, donc **toute police supprimée depuis redevient `deleted_at IS NULL`**, tombe dans `missing_on_device` (`sync_manager.py:86`), et `auto_pull = 1` sur **les deux** appareils (vérifié) la réinstalle. Un retour arrière annule des suppressions sans qu'on l'ait demandé — la règle centrale du projet, en sens inverse.

**Runbook « la migration a échoué au boot »** : **ne pas rejouer**. Chercher `SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp_%'`, et si quelque chose sort, restaurer le `.db` (les migrations SQLite ne sont pas atomiques, `transactional_ddl = False` vérifié). Vérifier aussi l'espace libre du volume avant M3, qui recrée `fonts`.

**Prérequis bloquant de L1 : un vrai dispositif de sauvegarde.** `ls scripts/` n'en contient aucun, et `scripts/dev/pull-prod-snapshot.sh:4-12` n'en est pas un — il rejoue `/api/fonts/upload` vers une base de dev jetable et recrée des lignes avec de **nouveaux UUID**, sans `device_fonts`, sans corbeille, sans pierres tombales. Son propre en-tête explique pourquoi une copie de fichiers n'est pas triviale : base et blobs vivent dans des volumes Docker root-only sur le NAS. Livrer avant L1 un `scripts/backup-prod.sh` qui fait un `sqlite3.backup` **depuis l'intérieur du conteneur** (base en WAL, une copie du seul `.db` est invalide) plus un `tar` du volume `fonts` (fichiers nommés par hash, write-once), et une entrée cron sur le NAS. **Sans ce script, ne pas commencer** : L5 est irréversible et l'unique filet date du 10 août, reproduit par rien.

### 5.4 Vérifications sur données réelles, avant / après

Protocole manuel, sur une **copie** de l'instantané, pour **chaque** révision — les migrations ne sont couvertes par aucun test (`Base.metadata.create_all` en `tests/backend/conftest.py:154` et `:201`, zéro occurrence d'`alembic` dans `tests/`) et ne tournent qu'au démarrage du conteneur : **leur première exécution réelle a lieu en production**.

```bash
cp fontsync-<date>.db /tmp/essai.db     # et supprimer tout -wal/-shm associé
sqlite3 /tmp/essai.db "PRAGMA table_info(fonts);"        > /tmp/avant-fonts.txt
sqlite3 /tmp/essai.db "PRAGMA table_info(device_fonts);" > /tmp/avant-df.txt
sqlite3 /tmp/essai.db "SELECT COUNT(license), COUNT(variable_axes), COUNT(panose), \
                              COUNT(unicode_ranges), COUNT(supported_scripts) FROM fonts;"

DATABASE_URL=sqlite+aiosqlite:////tmp/essai.db alembic upgrade head

sqlite3 /tmp/essai.db "PRAGMA integrity_check; PRAGMA foreign_key_check;"
sqlite3 /tmp/essai.db "SELECT sql FROM sqlite_master WHERE tbl_name IN ('fonts','device_fonts','devices');"
#   → UNIQUE(file_hash) ANONYME présent ? les 5 ix_fonts_* présents ?
#     les 2 FK anonymes de device_fonts présentes ? ix_device_fonts_font_id présent ?
diff <(sqlite3 /tmp/essai.db "PRAGMA table_info(fonts);") /tmp/avant-fonts.txt   # écart ATTENDU uniquement
sqlite3 /tmp/essai.db "SELECT COUNT(license), COUNT(variable_axes), COUNT(panose), \
                              COUNT(unicode_ranges), COUNT(supported_scripts) FROM fonts;"  # IDENTIQUE
sqlite3 /tmp/essai.db "SELECT (SELECT COUNT(*) FROM fonts WHERE deleted_at IS NULL),
                              (SELECT COUNT(*) FROM fonts WHERE deleted_at IS NOT NULL),
                              (SELECT COUNT(*) FROM device_fonts),
                              (SELECT COUNT(*) FROM devices),
                              (SELECT COUNT(*) FROM font_families);"   -- 5180|1025|8215|2|569

DATABASE_URL=... alembic downgrade -1 && DATABASE_URL=... alembic upgrade head   # aller-retour
```

Le comptage de non-NULL sur `license`, `variable_axes`, `panose`, `unicode_ranges`, `supported_scripts` est ce qui attrape une colonne perdue lors de la recréation de `fonts` en M3 : une relecture visuelle du `sqlite_master` ne le verrait pas.

**Après M2, en production**, rejouer la requête de cohérence de §5.1 (doit valoir 0) à chaque palier tant que la double écriture est en place.

**Après chaque delta de L1 et L5**, dans les logs : `DeletionDetection.total`, la taille du registre avant/après réconciliation, et le décompte de récolte à blanc.

Note sur le HEALTHCHECK (`Dockerfile:54`, `--start-period=20s --interval=30s --retries=3`) : les migrations tournent avant uvicorn, `/health` ne répond pas pendant. À 6 205 et 8 215 lignes, M1 et M2 sont des `ADD COLUMN` natifs (instantanés) ; seul M3 recrée trois tables. Chronométrer M3 sur la copie avant de le poser sur le NAS.

---

## 6. Impact sur l'API et les clients

**Endpoints**

| Endpoint | Changement | Palier |
|---|---|---|
| `GET /api/fonts/trash` | + clause `purged_at IS NULL` (`fonts.py:340`) ; `pendingConfirmation` gagne `purged_at IS NULL` (`:345-349`) | L0 |
| `POST /api/fonts/trash/empty` | refuse les non-confirmées (`:379-381`) ; la réponse porte le nombre de retenues | L0 |
| `POST /api/fonts/{id}/purge` | **409** si la suppression n'est pas confirmée (`:716-723` ne teste aujourd'hui que `deleted_at`) | L0 |
| `POST /api/fonts/trash/confirm` | SELECT porte **aussi** `deleted_at IS NOT NULL` (`:402-404`) | L0 |
| `GET /api/fonts/{id}/devices` | `connected_sse_devices` au lieu de `connected_agents` (`:575`) ; `activated` retiré de `FontDeviceStatus` (`schemas/font.py:104`) | L0 / L4 |
| `POST /api/sync/delta` | devient écrivain (réconciliation, horodatage, récolte) ; `DeviceFontEntry.ingestible` | L1 |
| `DELETE /api/devices/{id}` | soft delete : ne détruit plus `device_fonts` | L1 |
| `POST /api/devices/{id}/merge` | soft delete des sources ; retire la recopie d'`activated`/`local_path` (`devices.py:183-184`) ; **docstring à corriger** — sa raison d'être documentée (`:150-153`, « une police déjà synchronisée ne repasse jamais par un transfert qui recréerait l'association ») disparaît avec la réconciliation | L1 / L4 |
| `WS /ws/agent/{device_id}` | **supprimé** (`routers/ws.py:52-195`) | L4 |
| `POST /api/fonts/{id}/uninstall|activate|deactivate/{device_id}` | **conservés en 501** (§10) | — |

**Schémas Pydantic** : `FontResponse.storage_path` (`schemas/font.py:33`) et `.deleted_reason` (`:82`) retirés ; `FontResponse.installed_on` + `FontListResponse.device_count` ajoutés ; `FontDeviceStatus.activated` (`:104`) retiré ; `DeviceResponse.sync_status`/`.last_sync_at` (`schemas/device.py:73-74`) retirés ; **`DeviceUpdate.sync_status` (`:42`) retiré** — un `PATCH` dont le corps ne contenait que `{"syncStatus": …}` basculera en **400 « Aucun champ à modifier »** (`devices.py:128-131`).

**Frontend — inventaire nominatif, chaque palier conditionné à un `npm run build` vert** (`vue-tsc -b` attrape ce que `vite` dev masque) :

| Fichier:ligne | Action | Palier |
|---|---|---|
| `types/api.ts:7` (`storagePath`) | retirer | L4 |
| `types/api.ts:37`, `:51` (`DeletionReason`) | retirer le champ et le type ; **sans quoi** `f.deletedReason === "quarantine_pending"` (`stores/trash.ts:28`) et `font.deletedReason === 'quarantine_pending'` (`TrashPage.vue:206`) lèvent TS2367 | L4 |
| `types/api.ts:139-140` (`lastSyncAt`, `syncStatus`) | retirer | L4 |
| `types/api.ts:236` (`"device.updated"`) | retirer — ses **deux seuls émetteurs** sont `routers/ws.py:163` et `:191`, supprimés avec l'endpoint | L4 |
| `types/api.ts` (`Font`, `FontListResponse`) | ajouter `installedOn`, `deviceCount` | L5 |
| `stores/trash.ts:26-29` (`pending`) | **supprimer** : computed exporté (`:90`) qu'aucun composant n'utilise — code déjà mort | L4 |
| `stores/trash.ts:6-14` (docstring) | réécrire (le vidage ne laisse plus de ligne visible) | L0 |
| `stores/devices.ts:49-54` (`updateDeviceFields`) | supprimer — ne sait manipuler que `syncStatus` et n'a plus d'émetteur | L4 |
| `composables/useWebSocket.ts:58-62` (`case "device.updated"`) | supprimer | L4 |
| `components/settings/DevicesSection.vue:190-207` | retirer le bouton scanning/syncing, ne garder que « Rescan » | L4 |
| `components/settings/DevicesSection.vue:304-321` | libellé « Dossiers surveillés » → distinguer surveillés / ingérés | L3 |
| `pages/TrashPage.vue:205-216` | badge piloté par `deletionConfirmed === false` au lieu de `deletedReason` | L4 |
| `pages/TrashPage.vue:218-220`, `:229` | le badge « Fichier retiré » et le bouton purge deviennent inatteignables (plus aucune ligne purgée listée) → retirer | L0 |
| `pages/TrashPage.vue:143-158` | nouveau texte de résultat de vidage (§2.3) | L0 |
| `components/fonts/DeviceInstallSheet.vue:25` (`activated`) | retirer de l'interface locale | L4 |
| `components/fonts/DeviceInstallSheet.vue:214-223` | libellé « installée le » → « détenue depuis » | L1 |
| `i18n/{fr,en}.ts` | retirer `trash.reasons.quarantine_pending` (fr:234 / en:230), `trash.purged` (fr:222 / en:218), `trash.purgedHint` (fr:223 / en:219), `devices.scanning` (fr:165), `devices.syncing` (fr:166) ; **réécrire** `trash.emptyExplainer` (fr:220 / en:216) et `deviceInstall.mirrorNote` (fr:251 / en:248) ; **ajouter** le texte de vidage partiel et `fonts.installedOnCount` | L0 / L3 / L4 / L5 |

**App macOS : aucune action requise.** `ServerClient.swift:10-11` ne décode que `totalFonts` depuis `/api/stats` ; la fenêtre est une `WKWebView` ; le « Dernière vérif. » du menu est un `Date()` local sans rapport avec `Device.last_sync_at` ; `AppConfig.swift` ne touche que le bloc `server:` et préserve `scan:` verbatim, y compris `ingest_directories`. **Piège inverse** : purger `~/Library/WebKit/com.fontsync.app` avant de juger un écran (brief §6).

**Rappel d'exécution invisible dans le diff** : `/trash`, `/trash/empty`, `/trash/confirm`, `/duplicates` doivent rester déclarées **avant** `/{font_id}` (commentaire explicite `fonts.py:322-327`), sinon FastAPI les capte comme des UUID et renvoie 422. Le chantier réorganise beaucoup ce module ; une relecture ne le verrait pas, les tests d'API si.

---

## 7. Plan de test

État de référence : **314 passed, 3 skipped** (revérifié). Les 3 skips dépendent réellement de polices commerciales absentes : `test_storage.py:124`, `test_family_grouper.py:314`, `:371`. **Tout autre skip apparu est un signal.**

### 7.1 À écrire AVANT de toucher au chemin de suppression (livrés en L0)

1. **Machine éteinte au moment de la suppression, qui revient plus tard.** Le scénario qui *justifie* la pierre tombale et qu'**aucun test ne joue** : tous font pousser la machine immédiatement après (`test_deletion_propagation.py:203-226`, `:558-597`, `:636-661`).
2. **Supprimer → restaurer → re-sync, vu du registre `device_fonts`.** Aucun test ne compte cette table après une suppression (les deux seuls comptages sont `test_sync_manager.py:58` et `test_deletion_propagation.py:433-436`).
3. **`/trash/confirm` avec DEUX appareils**, et **`confirm` ne modifie aucune police dont `deleted_at` est NULL**. L'endpoint est global (`fonts.py:402-407`, sans filtre d'id, d'appareil ni de date) et c'est le seul geste du produit capable de faire disparaître un fichier ailleurs ; le seul test qui l'exerce n'a qu'un appareil (`:691-715`).
4. **Plus de 500 disparitions.** `_DELETE_BATCH = 500` (`deletion_propagation.py:47`, `:138-144`) n'a **jamais** tourné sous test sur plus d'un lot, alors que l'incident fondateur portait sur 625 fichiers ; le test de disparition massive n'utilise que 6 polices (`:484-500`).
5. **`delete_font` efface bien toutes les associations** (`fonts.py:692`) — la propriété sur laquelle repose tout le reste et que rien n'observe.
6. **Purge et vidage refusent une suppression non confirmée** (les deux chemins : `fonts.py:705-724` et `trash.py:81-87`).

### 7.2 À écrire en L1 (réconciliation)

7. Une police `already_synced` obtient son association (le trou de `sync_manager.py:89`).
8. Une pierre tombale déclarée obtient son association.
9. Une pierre tombale non déclarée perd son association, **sans quarantaine ni notification**.
10. Une police **active** non déclarée n'est jamais touchée par la réconciliation.
11. Déclaration vide → ni détection, ni réconciliation, ni horodatage, ni récolte (G1).
12. Détection au-delà du seuil → mêmes conséquences (G2).
13. **Commutativité** : le même scénario dans les deux ordres donne le même état.
14. **Deux entrées de même hash, `ingestible` True puis False** → une seule ligne, `ingestible = 1`, et la tombe n'est pas récoltable. Aucun test existant ne l'attrape.
15. **`delete_device` conserve les associations** et l'appareil retiré continue de bloquer la récolte des tombes qu'il détient.
16. **Le canari** : `test_restore_after_propagated_delete_does_not_loop` (`:600`) doit rester vert, **doublé** d'une variante où la machine déclare encore la police au delta suivant la suppression. Un échec ici signifie « le modèle est faux », pas « le test est à adapter ».

### 7.3 À écrire en L3 (agent) — **au niveau de `agent/discovery.py`, jamais de `sync_command`**

17. Une entrée de `/Library/Fonts` est **déclarée** avec `ingestible=False`.
18. Une entrée réinjectée par Core Text depuis `/Library/Fonts` porte aussi `ingestible=False`. *`_stub_scan` monkeypatche `discover_fonts` en entier (`tests/agent/test_sync_command.py:98`) : un test de la commande `sync` ne verrait jamais la réinjection.*
19. **Une entrée de `~/.fontsync/disabled/` est déclarée avec `ingestible=True`** (override `sync_command.py:264`).
20. Les non-ingestibles sont exclues des candidats au push, **sans** disparaître de la déclaration.
21. **`tests/agent/test_discovery.py:118-134` et `:153-174` restent verts** : ce sont eux qui prouvent que la déclaration n'a pas bougé. À **enrichir** d'une assertion sur `ingestible`, surtout pas à supprimer.

### 7.4 À écrire en L4/L5 (récolte)

22–31. Un test par garde-fou, chacun isolément bloquant : détenteur ingestible (G6), détenteur non ingestible seulement → récoltable, appareil à `last_declaration_at` NULL ou antérieur (G7), `purged_at` NULL (G3), `deletion_confirmed = 0` (G4), aucun appareil vivant (G5), plafond (G9), **délai de grâce non écoulé (G8)**, **une tombe dont un détenteur ingestible omet UNE déclaration puis la reprend n'est jamais récoltée (G8, le test le plus important du lot)**, et **nettoyage `font_family_members` + suppression des familles auto-groupées vides + recalage `style_count` + `PRAGMA foreign_key_check` vide**.

### 7.5 Test structurel à ajouter en L1 — il ferme une classe entière de risque

32. **Monter une base par `alembic upgrade head` et comparer à `Base.metadata.create_all`** (colonnes, types, nullabilité, index, contrainte unique). C'est la seule chose qui empêchera les trois révisions de partir en production sans avoir jamais été exécutées par la suite de tests, et le seul garde-fou contre une divergence silencieuse modèle ↔ migration.

### 7.6 Tests à réécrire, chiffrés

| Test | Nature | Action | Palier |
|---|---|---|---|
| `test_deletion_propagation.py:285-286` | `trash["total"] == 1` + `purgedAt is not None` | → `== 0` ; l'assertion `purgedAt` disparaît. **Sa vraie garantie — le push suivant reste refusé, `:289-291` — conservée mot pour mot**, sinon on remplace un test gênant par un test complaisant | L0 |
| `:126`, `:147`, `:169`, `:357`, `:369`, `:383`, `:385`, `:528` | décor `deleted_reason = DELETION_MANUAL` | ajouter `font.deletion_confirmed = True` (le `server_default '0'` les rendrait non propageantes) | L2 |
| `:500`, `:508` | assertions/décor sur `DELETION_PENDING` | `all(not f.deletion_confirmed …)` ; `deletion_confirmed = False` | L2 |
| `:175`, `:244`, `:410`, `:596`, `test_duplicate_faces.py:316` | lisent `deleted_reason` / `deletedReason` | à retirer ou reporter sur `deletionConfirmed` | L4 |
| `test_camel_alias_warning.py:92`, `:97` | `syncStatus` n'est qu'un véhicule (le sujet est l'absence de `UnsupportedFieldAttributeWarning`) | **2 lignes** : remplacer par `name` | L4 |
| `test_auth.py:228-234` | barrière de token sur `/ws/agent` | le bloc disparaît avec l'endpoint | L4 |
| **Survivent sans modification** | `:294-307` (restore purgée → 409), `:310-339`, `:374`, `:389-390`, `:633`, `test_sync_manager.py`, `test_stats.py`, `test_agent_events.py`, `test_device_sync_propagation.py`, `tests/agent/test_sync_client.py` | — | — |

`last_sync_at` et `activated` : **0 test** (grep sans résultat).

---

## 8. Séquençage du chantier

| Lot | Contenu | Migration | Réversibilité |
|---|---|---|---|
| **L0 — Hygiène, aucun changement de schéma** | `connect_args={"timeout": 30}` (`database.py:8`) ; `scripts/backup-prod.sh` + cron NAS ; `fonts.py:575` → `connected_sse_devices` ; `fonts.py:340` + `purged_at IS NULL` ; `pending_confirmation` + `purged_at IS NULL` ; `empty_trash`, `POST /{id}/purge`, `purge_expired` refusent les non-confirmées ; `/trash/confirm` + `deleted_at IS NOT NULL` ; réécriture i18n corbeille ; **les 6 tests de §7.1** | — | Swap de tag |
| **L1 — Inventaire miroir (serveur)** | M1 + `reconcile_inventory` (dédup par hash) + soft delete `devices` + effacement d'associations à `restore`/`revive` + `ingestible` serveur + récolte **inerte qui logge** + test structurel §7.5 + logs d'observabilité §4.4 | **M1** | **Arrêt + restauration du `.db` + swap de tag.** Pas un swap seul |
| **L2 — Booléen de confirmation** | M2 + double écriture, lecture sur le booléen + requête de cohérence | **M2** | Idem L1 |
| **L3 — Agent 0.2.0** | `ingest_directories`, drapeau `ingestible` dans les deux sources, dédup par hash, filtre de push. **`.dmg` posé à la main, mini d'abord, un cycle d'observation, puis MacBook. Release non publiée en `--latest`** | — | Réinstaller l'agent précédent ; auto-guérissant côté serveur (défaut True) — **jusqu'à L5** |
| **L4 — Nettoyage** | M3 + suppression de `/ws/agent` + nettoyage frontend/i18n nominatif (§6) + `npm run build` vert | **M3** | Idem L1 |
| **L5 — Activation de la récolte + affichage dérivé** | `tombstone_harvest_enabled = True` avec `max_per_pass = 5` au premier cycle, lecture des identifiants dans les logs, **vérification à la main qu'aucun des fichiers correspondants n'est encore dans un dossier ingestible sur l'une des deux machines**, puis remontée à 200 ; « installée sur N de tes M machines » (API + TS + i18n + composant) | — | **NON — point de non-retour données. Et L3 devient irréversible ici** |

Les lots sont livrables indépendamment et **du plus sûr au plus risqué** : L0 n'a aucune migration et améliore l'écran corbeille immédiatement ; L1 et L2 sont des `ADD COLUMN` natifs ; L4 est la seule à recréer des tables ; L5 est le seul geste destructeur.

---

## 9. Hors périmètre — et pourquoi

| Sujet | Décision | Raison |
|---|---|---|
| **Enquête `is_online`** (brief §6 : un `listen` vivant non compté connecté, rétabli par `launchctl kickstart`) | **Hors périmètre.** On corrige uniquement le bug de source `fonts.py:575` | **Aucune clause du modèle cible ne dépend de la présence** : la récolte s'appuie sur `last_declaration_at`, écrit par un delta authentifié sur un device existant. La correction entre quand même — une ligne, dans un fichier qu'on modifie de toute façon, qui réactive un bouton grisé en permanence — avec sa propre ligne de changelog |
| **Validation du `device_id` SSE** (`agent_events.py:28`) | **Hors périmètre**, dette nommée | N'importe quelle chaîne devient « connectée » et émet `device.connected`. Tant que la présence n'est qu'un affichage, c'est cosmétique. **À rouvrir si un jour une décision dépend de la présence** — la conception retenue s'en abstient délibérément |
| **`FontFamily.style_count`** | **Reste stocké** ; la récolte le recale sur les familles touchées | Agrégat stocké qui dérive déjà : mesuré, `sum(style_count) = 6205 = COUNT(font_family_members)`, dont **1 025 pointent des polices en corbeille** → sur-compte de 16,5 %, et `font_families.py:193` choisit le survivant d'une fusion sur cette valeur fausse. Le dériver entièrement toucherait 10 sites : chantier voisin, élargirait la surface sans servir l'objectif |
| **Deux `sync` concurrents sans verrou** | **Hors périmètre**, dette nommée | launchd `WatchPaths`/`StartInterval` + `listen` (`agent/listen_command.py`), scan disque avant le delta : un delta issu d'un scan périmé peut quarantiner une police fraîchement poussée, et isolée elle passe sous le plancher de 3, donc **elle se propage**. Vecteur de perte **réel et préexistant**, que le chantier n'aggrave pas et ne corrige pas. À traiter par un verrou de fichier côté agent |
| **Garde-fou « la déclaration a rétréci de X % »** | **Non ajouté** | Le garde-fou 1 ne couvre que le cas ZÉRO (`deletion_propagation.py:97-103`) ; une déclaration amputée de 10 % passe sans bruit. Mais G2 réutilise gratuitement le seuil existant et G8 rend une omission ponctuelle réversible. Ajouter une colonne `last_declaration_count` pour un garde-fou que rien n'a mesuré comme manquant élargit le chantier le plus dangereux du dépôt |
| **Purge automatique** (`trash_retention_days = 0`, `config.py:21`) | **Reste à 0** | Ne pas la « réparer » au prétexte que la boucle sort immédiatement (`trash.py:113-115`) : une purge qui supprime des fichiers sans demande viole la règle centrale du projet |
| **`Font.source_device_id` sans FK** (`models/font.py:88`) | **Inchangé** | Ajouter la contrainte imposerait de nettoyer des références pendantes que `fonts.py:453` résout déjà silencieusement en `None` |
| **Renommer `device_fonts` → `device_inventory`, `installed_at` → `first_seen_at`** | **Non** | Un `rename_table`/`alter_column` sur SQLite avec FK et index, pour de la sémantique, dans le chantier qui touche déjà le chemin le plus dangereux. La sémantique vit dans la docstring de module et `ARCHITECTURE.md` |
| **Table `font_deletions` dédiée** | **Non** — les colonnes restent sur `fonts` | 41 sites de `deleted_at` sur 12 fichiers backend, tous sur le chemin de suppression. Refondre la table centrale contredit « le chemin de suppression est la zone la plus dangereuse du code » pour un gain qui ne change aucun comportement |

---

## 10. Ce qui demande un arbitrage de l'utilisateur

**Un point, tranché par défaut ci-dessous ; le reste, rien.**

### 10.1 Le sort des 551 polices déjà ingérées depuis `/Library/Fonts` — CORRECTIF

Ce document ne traitait les 551 que comme un **danger de déploiement** (§4.2) et concluait
« rien à arbitrer ». C'est incomplet : leur sort de **membres de la bibliothèque** n'était
décidé nulle part. Mesuré : les deux appareils ont `auto_pull = 1`, donc ces 551 polices —
que seul le mini détient — sont dans le `missing_on_device` du MacBook et **continuent de s'y
installer**. Le brief §2.2 annonçait « les polices installées pour tous les utilisateurs ne
sont plus synchronisées » : c'est vrai des futures, pas de ces 551.

**Décision retenue : elles restent dans la bibliothèque.** « Rien ne s'efface sans un oui
explicite » (`CLAUDE.md`) tranche le défaut, et 551 polices quittant la bibliothèque d'un
seul geste, c'est exactement la forme que le garde-fou de quarantaine existe pour empêcher.
Le modèle cible les gère proprement au passage : leur ligne `device_fonts` porte
`ingestible = 0`, donc une suppression ultérieure les rend **récoltables** (G6) au lieu de
laisser une tombe éternelle.

**Alternative non retenue, rouvrable :** les évincer de la bibliothèque en un geste groupé et
explicite. Lot séparé, **après L5**, qui suppose un écran de confirmation groupée — `/restore`
est unitaire aujourd'hui (`fonts.py:729`). Ne mord pas avant L3 : ne bloque aucun lot amont.

### 10.2 Désactivation par appareil — rien à arbitrer

Le seul autre candidat était la désactivation par appareil, et il se tranche dans le plan. Le code dit ceci : l'UI la **promet** (`frontend/src/i18n/fr.ts:251`, `deviceInstall.mirrorNote`, « la désactivation et l'activation par appareil arrivent dans une prochaine version »), le serveur la classe **reportée** (`backend/routers/fonts.py:613-617`, `_B1_DEFERRED`, « manifeste désiré ») avec trois endpoints 501, et l'agent **sait déjà** distinguer les polices désactivées (`~/.fontsync/disabled/`, `agent/sync_command.py:264-266`, compté dans `SyncResult.deactivated`) mais ne le dit à personne. Le chantier retire `DeviceFont.activated`, colonne morte (0 ligne à `false` sur 8 215) que `register_device_font` n'accepte même pas en paramètre — **retirer ce champ ne ferme rien techniquement** : le jour où la fonctionnalité se fait, elle passera par la déclaration du delta, où l'agent a déjà l'information.

**Décision : garder les trois handlers 501 et reformuler `deviceInstall.mirrorNote` en « prévu, pas encore là ».** C'est la réponse conservatrice, elle découle de la phrase précédente seule, et l'alternative — annoncer que FontSync ne gérera jamais l'activation par appareil — est une promesse produit que rien dans ce chantier n'oblige à faire maintenant. Question rouvrable le jour où le « manifeste désiré » sera réellement mis en chantier. Le brief §7 interdit nommément de remonter un choix dont le défaut sûr est déjà déterminé.

---

## 11. Notes d'exécution

**Installer la sauvegarde sans stocker de mot de passe.** Le NAS est un Synology ; docker y
exige `sudo` avec mot de passe et le chemin complet `/usr/local/bin/docker` (PATH absent sous
sudo). Ne **pas** poser d'entrée crontab sous `Leo` : elle échouerait sur `docker exec` faute
de droits, et l'échec ne se verrait qu'au moment d'avoir besoin de la sauvegarde. Passer par
**Synology Task Scheduler → Tâche planifiée → Script défini par l'utilisateur, exécuté en
`root`** : pas de `sudo`, pas de credential dans un fichier. Aucun secret ne doit entrer dans
ce document — il est suivi par git sur un dépôt public.

**Révoquer le token d'instance avant L1.** Il a fuité dans une conversation le 2026-08-10 et
n'est pas révoqué. Régler ça pendant que le retour arrière est encore un simple swap de tag :
`FONTSYNC_TOKEN` dans le `.env` à côté de `docker-compose.nas.yml`, puis ré-appairer les deux
Macs. Après L1, tout retour arrière passe par une restauration de base (§5.3).

**Deux sessions dans le même arbre de travail se marchent dessus.** Ce chantier se mène un lot
à la fois, une conversation à la fois.

---

### Failles des critiques que je rejette

- **« Le `downgrade()` de M2 n'est pas fidèle si `manual ⟹ confirmed=1` ne tient pas »** — sans objet dans la version retenue : M2 ne touche plus à `deleted_reason`, son downgrade est un simple `drop_column`. La reconstruction du motif est repoussée en M3, où elle est **fidèle au comportement** (`confirmed=1 → 'manual'`, propageant ; `0 → 'quarantine_pending'`, retenu) même si elle perd le libellé `quarantine`, ce qu'aucun code ne lit pour décider.
- **« Ajouter un G9 sur `devices.agent_version` rend le retour arrière de l'agent inoffensif »** — faux : la récolte ayant déjà eu lieu, la ligne `fonts` n'existe plus et aucune condition sur la version d'agent ne l'empêche de repousser. La bonne réponse est de documenter l'irréversibilité, ce qui est fait (§5.3).
- **« Le piège `legacy_alter_table` mérite un paragraphe »** — mesuré sans objet sur SQLite 3.50.4 : la séquence CREATE tmp / INSERT SELECT / DROP / RENAME réussit avec `legacy_alter_table=0` et `PRAGMA foreign_key_check` revient vide. Le paragraphe est retiré ; l'attention se porte sur `foreign_keys` qui doit rester OFF et sur l'absence de transaction.
- **« `copy_from` explicite en M4 pour préserver `UNIQUE (file_hash)` »** — mesuré faux : la réflexion restitue exactement la contrainte anonyme et les 5 index sur l'instantané réel. `copy_from` était le seul chemin capable de perdre une colonne en silence.
- **« Départ métré par `propagation_limit` »** — rejeté au profit de G8 (candidature + délai de grâce), strictement plus fort : le seuil ne protège pas le registre (les suppressions d'associations de `detect_local_deletions` sont déjà inconditionnelles, `deletion_propagation.py:137-144`), alors que G8 rend une omission ponctuelle **auto-réparable sans qu'aucune donnée n'ait été détruite**.