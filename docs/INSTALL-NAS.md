# Installer le serveur FontSync sur un NAS

Guide d'installation du **serveur** FontSync (Docker) sur un NAS — Synology
(Container Manager), QNAP (Container Station) ou tout hôte Docker. Le serveur est
la **source de vérité** : il centralise la bibliothèque, sert l'UI web et pousse
les signaux de re-sync aux agents. L'agent macOS et l'app menu bar s'installent
séparément (cf. `PLAN-PUBLICATION.md`, P3).

> L'image est **multi-arch** (`linux/amd64` + `linux/arm64`) : elle tourne aussi
> bien sur un NAS x86 (Intel/AMD) que sur un NAS ARM (Realtek, Annapurna…). Docker
> sélectionne automatiquement la bonne variante.

---

## 1. Ce qu'il vous faut

- Un NAS avec Docker (Synology **Container Manager**, QNAP **Container Station**)
  ou un hôte avec `docker` + `docker compose`.
- Le port `8080` libre sur le NAS (ajustable).
- Un **token d'instance** (secret partagé). Générez-le :

  ```bash
  openssl rand -base64 32
  # ou : python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

L'image est publiée sur **GitHub Container Registry** :
`ghcr.io/leodurandfr/fontsync:latest` (ou un tag de version, ex. `:1.0.0`).

---

## 2. Installation via docker compose (recommandé)

C'est la méthode la plus simple et reproductible, y compris sur Synology dont le
**Container Manager** sait importer un fichier compose (« Projet »).

1. Créez un dossier sur le NAS, p. ex. `docker/fontsync/`.
2. Déposez-y le fichier [`docker-compose.nas.yml`](../docker-compose.nas.yml) du dépôt.
3. À côté, créez un fichier **`.env`** contenant votre token :

   ```dotenv
   FONTSYNC_TOKEN=collez-ici-le-token-généré
   ```

4. Lancez :

   ```bash
   docker compose -f docker-compose.nas.yml up -d
   ```

   Au premier démarrage, l'entrypoint applique les migrations de schéma
   (`alembic upgrade head`) puis démarre le serveur. La base SQLite est créée
   automatiquement dans le volume `db`.

5. Ouvrez `http://<ip-du-nas>:8080`. L'UI web demande le token au premier accès.

### Sur Synology Container Manager (interface graphique)

1. **Container Manager → Projet → Créer**.
2. Source : « Créer un docker-compose.yml » (collez le contenu de
   `docker-compose.nas.yml`) ou « Importer » le fichier.
3. Renseignez la variable `FONTSYNC_TOKEN` (onglet environnement, ou via le
   `.env` placé dans le dossier du projet).
4. Lancez le projet. Container Manager crée les volumes `db` et `fonts`.

---

## 3. Variables et volumes

| Variable env        | Rôle                                              | Valeur d'exemple                              |
|---------------------|---------------------------------------------------|-----------------------------------------------|
| `FONTSYNC_TOKEN`    | Secret protégeant `/api/*`, SSE et WS (**requis**) | sortie de `openssl rand -base64 32`           |
| `DATABASE_URL`      | URL SQLite (async)                                 | `sqlite+aiosqlite:////data/fontsync.db`       |
| `STORAGE_BACKEND`   | Backend de stockage                                | `filesystem`                                  |
| `FONT_STORAGE_PATH` | Dossier des fichiers de polices                    | `/fonts`                                       |

> Si `FONTSYNC_TOKEN` est laissé vide, le serveur **génère** un token au
> démarrage et le **loggue** (jamais de serveur ouvert par défaut). Le compose
> d'exemple le rend **obligatoire** pour éviter qu'il change à chaque
> redémarrage.

| Volume  | Monté sur | Contenu                                         |
|---------|-----------|-------------------------------------------------|
| `db`    | `/data`   | Base SQLite : `fontsync.db` (+ `-wal`, `-shm`)  |
| `fonts` | `/fonts`  | Fichiers de polices (organisés par préfixe de hash) |

Ces **deux** volumes constituent l'intégralité de l'état du serveur : les
sauvegarder, c'est sauvegarder FontSync (cf. §5).

---

## 4. Mises à jour

```bash
docker compose -f docker-compose.nas.yml pull
docker compose -f docker-compose.nas.yml up -d
```

À chaque démarrage, l'entrypoint relance `alembic upgrade head` : les migrations
de schéma sont appliquées automatiquement, sans intervention. `alembic` est
idempotent — aucun effet si le schéma est déjà à jour.

> Épinglez un tag de version (`:1.0.0`) plutôt que `:latest` si vous voulez
> maîtriser le moment des mises à jour.

---

## 5. Sauvegarde & restauration

L'état complet tient dans les **deux volumes** : `db` (la base) et `fonts` (les
fichiers). La base est en mode **WAL** : des écritures peuvent résider dans le
fichier `-wal` non encore fusionné. Il faut donc une copie **cohérente**.

### Méthode A — sauvegarde à froid (la plus sûre)

Arrêter le conteneur garantit que le WAL est fusionné et qu'aucune écriture n'est
en cours :

```bash
docker compose -f docker-compose.nas.yml stop

# Copier les deux volumes (chemins Docker → archives tar)
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

> Le nom réel des volumes est préfixé par le projet compose (souvent
> `fontsync_db` / `fontsync_fonts`). Vérifiez avec `docker volume ls`.

Sur Synology, ces volumes vivent sous
`/volume1/@docker/volumes/<nom>/_data` — vous pouvez aussi les inclure dans une
tâche **Hyper Backup** classique (idéalement conteneur arrêté).

### Méthode B — sauvegarde à chaud de la base (conteneur en marche)

L'API `.backup` de SQLite produit une copie cohérente sans arrêter le service. La
stdlib Python (déjà dans l'image) suffit :

```bash
docker compose -f docker-compose.nas.yml exec fontsync \
  python -c "import sqlite3; src=sqlite3.connect('/data/fontsync.db'); dst=sqlite3.connect('/data/backup.db'); src.backup(dst); dst.close(); src.close()"

# Récupérer la copie hors du conteneur
docker compose -f docker-compose.nas.yml cp fontsync:/data/backup.db ./fontsync-db-$(date +%F).db
docker compose -f docker-compose.nas.yml exec fontsync rm /data/backup.db
```

Sauvegardez **en plus** le volume `fonts` (les fichiers ne sont pas dans la base).
À chaud, une copie `tar` du dossier `fonts` est sûre : les fichiers sont en
écriture-une-fois (nommés par hash), jamais modifiés en place.

### Restauration

1. `docker compose -f docker-compose.nas.yml down` (sans `-v` : conserve les volumes).
2. Restaurez le contenu des archives dans les volumes `db` et `fonts`
   (symétrique de la méthode A : `tar xzf … -C /data` / `-C /fonts`).
3. `docker compose -f docker-compose.nas.yml up -d`. Les migrations se
   réappliquent au boot si besoin.

---

## 6. Exposition réseau

Par défaut, le serveur écoute en **HTTP clair** sur le LAN. Le token transite en
clair : **ne l'exposez jamais directement sur Internet**. Pour un accès distant,
placez un **reverse-proxy TLS** (Caddy / nginx) devant — voir la section
« Transport & sécurité réseau » du [README](../README.md). Sur Synology, le
**Reverse Proxy** intégré (Panneau de configuration → Portail des applications)
fait l'affaire, à condition de relayer WebSocket et SSE.
