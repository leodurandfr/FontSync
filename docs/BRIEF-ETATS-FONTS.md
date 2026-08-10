# Brief — remise à plat des états d'une police

> Document de cadrage pour un chantier d'architecture. Rédigé le 10 août 2026 à
> l'issue d'une session de diagnostic. **Tout ce qui figure ici a été mesuré**,
> pas supposé : ne pas re-mesurer, mais vérifier avant de contredire.

## 1. Objectif

Simplifier le modèle d'état d'une police et sa gestion automatique. Le but n'est
pas une réécriture : les états existants sont, pour la plupart, justifiés et
documentés. Le but est de **retirer l'état mort, séparer le stocké du dérivé, et
trancher une asymétrie d'architecture** qui force aujourd'hui un compromis
visible par l'utilisateur.

## 2. Constats établis — ne pas re-dériver

### 2.1 Trois champs d'état sont morts

L'agent ne parle plus WebSocket depuis la migration vers SSE (`agent/` ne
contient aucun client WS). Or `backend/routers/ws.py` → `/ws/agent/{device_id}`
est le **seul écrivain** de trois champs :

| Champ | Valeur réelle en production |
|---|---|
| `Device.sync_status` | `"idle"` à vie |
| `Device.last_sync_at` | `null` à vie |
| `DeviceFont.activated` | `true` à vie |

`register_device_font` (`backend/services/sync_manager.py`) n'accepte même pas de
paramètre `activated` : le drapeau ne peut jamais passer à `false`, alors que
l'agent sait détecter les polices désactivées (`~/.fontsync/disabled/`, cf.
`agent/sync_command.py`). Fonctionnalité à moitié câblée sur un canal débranché.

### 2.2 L'asymétrie qui force la pierre tombale

L'agent **scanne et pousse** `/Library/Fonts` mais ne l'a **jamais nettoyé** (par
conception : dossier tous-utilisateurs). Sur le Mac mini, **84 des 1025 empreintes
purgées** correspondent à des fichiers encore présents dans ce dossier.

Conséquence : supprimer réellement la ligne d'une police purgée la ferait
remonter au sync suivant, se recréer, et aucune suppression ne la ferait partir
durablement. C'est **exactement** ce que la ligne conservée empêche
(`backend/routers/sync.py`, refus de push si `deleted_at` est posé).

**C'est le point d'architecture central du chantier**, et il tient en une
décision : `/Library/Fonts` entre-t-il dans le périmètre de FontSync, oui ou non ?
Tant qu'un dossier alimente la bibliothèque sans pouvoir être nettoyé,
l'empreinte est obligatoire.

### 2.3 Le garde-fou anti-suppression massive est réel et utile

`quarantine_pending` n'est pas de la complexité gratuite. Le 10 août 2026, 625
fichiers ont disparu d'un coup de `~/Library/Fonts` (nettoyage manuel de
doublons) ; sans seuil, une autre machine en aurait perdu 225 automatiquement.
Sur les 1025 entrées actuelles en corbeille, 10 portent `deleted_reason =
quarantine`.

Ce mécanisme doit survivre à toute simplification. Il peut changer de forme —
c'est un attribut de la *suppression*, pas un état de la police, donc un booléen
suffirait — mais pas disparaître.

### 2.4 État actuel, tel qu'il est réellement implémenté

**Côté serveur** (ligne `Font`) :

| État | `deleted_at` | `purged_at` | Fichier sur le NAS | Restaurable |
|---|---|---|---|---|
| En bibliothèque | `NULL` | — | oui | — |
| En corbeille | posé | `NULL` | oui | oui |
| Empreinte purgée | posé | posé | non | non |

**Côté appareil** (`DeviceFont`) : absente / installée active / installée
désactivée (`activated`, cf. §2.1 — inerte aujourd'hui).

**Motif** (`deleted_reason`, `backend/models/font.py`) :

| Valeur | Origine | Se propage aux appareils ? |
|---|---|---|
| `manual` | suppression depuis le web | oui |
| `quarantine` | disparue d'un appareil qui propage | oui |
| `quarantine_pending` | disparition au-delà du seuil | **non**, tant que non confirmée |

Autres faits : `trash_retention_days = 0` par défaut, donc **la purge automatique
est désactivée** — la corbeille ne se vide qu'à la main. Une suppression sur un
appareil ne remonte que si `propagate_deletions` y est activé (`false` par
défaut).

## 3. Direction proposée — à challenger, pas à appliquer telle quelle

Le modèle mental de l'utilisateur (« installé sur toutes les machines / sur
quelques-unes / sur aucune / corbeille / plus rien ») est un bon **vocabulaire
d'affichage** mais un mauvais **axe de stockage** : les trois premiers ne sont pas
des états de la police, ce sont des agrégats sur `DeviceFont`, à recalculer à
chaque install/désinstall, avec dérive garantie s'ils sont stockés.

D'où une séparation en deux couches :

- **Stocké, minimal** : `Font.deleted_at` (`NULL` = bibliothèque, sinon
  corbeille), `DeviceFont` (qui détient quoi), et un booléen « suppression
  confirmée » remplaçant les trois valeurs de `deleted_reason`.
- **Dérivé, jamais stocké** : « sur toutes tes machines » / « sur 2 de tes 3 » /
  « sur aucune » = un `COUNT` sur `DeviceFont`.

Objectif de réduction : d'environ huit champs d'état à trois.

`purged_at` ne peut disparaître **que** si §2.2 est tranché en faveur du retrait
de `/Library/Fonts` du périmètre. Sinon il reste, et la simplification porte
uniquement sur l'affichage (la corbeille ne liste que le restaurable, les
empreintes deviennent invisibles).

## 4. Contraintes non négociables

- **Rien ne s'efface sans un oui explicite** (cf. `CLAUDE.md`). Le chemin de
  suppression est la zone la plus dangereuse du code.
- Une police malformée doit être stockée avec des métadonnées partielles, jamais
  rejetée — tout parsing fontTools reste sous try/except.
- WOFF/WOFF2 : stockables et prévisualisables, jamais proposés à l'installation.
- Toute évolution du schéma exige une migration Alembic. Révision actuelle :
  `b7c31a4d90e2`.
- Ne pas implémenter de fonctionnalités du `ROADMAP.md` sans demande explicite.

## 5. État du dépôt au moment de la rédaction

- **Suite de tests verte** : `pytest tests/ -q` → `314 passed, 3 skipped`. Les 3
  skips dépendent réellement de polices commerciales absentes et le disent. Tout
  échec est donc un vrai signal.
- **Sauvegarde vérifiée** : instantané SQLite du 10 août 2026 18:10,
  `.dev/backup/fontsync-20260810-1810.db` (19 Mo, gitignoré). `integrity_check`
  ok, `foreign_key_check` sans violation, compteurs identiques à la production
  (5180 polices vivantes, 1025 en corbeille toutes purgées, 2 appareils, 8215
  associations, 569 familles), et **restauration réellement testée** : un backend
  démarré sur une copie répond correctement sur `/api/stats`, `/api/devices`,
  `/api/fonts`, `/api/fonts/trash`.
  → C'est un instantané ponctuel, **pas un dispositif de sauvegarde**. Rien ne le
  reproduit automatiquement sur le NAS.
- **Volumétrie de production** : 5180 polices, 1025 pierres tombales, 2 appareils
  (`propagate_deletions = true` sur les deux).

## 6. Pièges connus

- **Ne pas se fier au frontend affiché** : la WKWebView de l'app macOS a servi un
  build périmé pendant des heures. Corrigé côté serveur, mais purger le cache
  (`~/Library/WebKit/com.fontsync.app`) avant de conclure à un bug d'UI.
- **`is_online` ne mesure pas la joignabilité** : c'est la seule présence d'une
  connexion SSE `listen` (`backend/routers/devices.py`). Une machine peut
  synchroniser parfaitement en étant affichée « hors ligne ». Le point reste
  ouvert : un `listen` vivant n'était pas compté connecté, cause non établie,
  rétabli par `launchctl kickstart`. Les logs sont dans
  `~/Library/Logs/FontSync/listen.err.log`.
- **L'endpoint SSE ne valide pas le `device_id`** : `agent_events.py` enregistre
  n'importe quelle chaîne comme connectée, sans vérifier qu'elle existe en base.
- **Les tests ne tournent pas dans le conteneur** : `.dockerignore` exclut
  `tests/`, et la CI ne lance pas pytest. En local uniquement.

## 7. Ce qu'il ne faut pas faire

- Supprimer `deleted_at` ou la notion de corbeille au nom de la simplicité.
- Stocker les agrégats « sur N machines » (§3).
- Retirer le garde-fou de quarantaine (§2.3).
- Toucher au chemin de suppression sans migration Alembic ni plan de retour.
- Considérer les 3 tests skippés comme des régressions.
