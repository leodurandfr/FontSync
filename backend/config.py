from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:////data/fontsync.db"
    storage_backend: str = "filesystem"
    font_storage_path: str = "/data/fonts"

    # Token partagé d'instance (P1, PLAN-PUBLICATION.md). Secret unique vérifié
    # sur tout `/api/*`. Vide → un token est généré et loggé au boot (cf.
    # `backend.auth`) pour ne jamais démarrer un serveur ouvert. Pas de comptes
    # utilisateurs (ça reste le mode cloud / Phase 7).
    fontsync_token: str = ""

    # ---------- Corbeille et suppression propagée ----------

    # Purge automatique des polices supprimées depuis plus de N jours.
    # **0 = désactivée** (défaut) : la corbeille ne se vide qu'à la main. Vider
    # retire le fichier du stockage mais garde la ligne — l'empreinte survit au
    # fichier, sinon la police reviendrait au push suivant.
    trash_retention_days: int = 0

    # Garde-fous de la propagation des suppressions. Une machine qui déclare
    # avoir perdu des polices doit rester crédible : au-delà de ces seuils, la
    # disparition est mise en quarantaine (récupérable) mais **non propagée**
    # tant que l'utilisateur n'a pas confirmé.
    #
    # Le 10 août 2026, 625 fichiers ont disparu d'un coup de `~/Library/Fonts`
    # (nettoyage manuel de doublons) : sans seuil, une autre machine en aurait
    # perdu 225 automatiquement.
    #
    # Les deux seuils s'appliquent ensemble — c'est le plus contraignant qui
    # décide. Un seuil absolu réglé pour une bibliothèque de 4000 polices est
    # trop permissif pour une machine qui en a 200 ; un pourcentage seul laisse
    # passer 200 suppressions d'un coup sur une grosse bibliothèque.
    deletion_propagation_max_fonts: int = 25
    deletion_propagation_max_ratio: float = 0.05
    # Plancher : en deçà, la propagation passe toujours. Sans lui, supprimer une
    # seule police sur une machine qui en a trente serait bloqué par le
    # pourcentage, et la fonctionnalité paraîtrait cassée.
    deletion_propagation_min_fonts: int = 3

    # ---------- Sauvegarde automatique ----------

    # Répertoire de sauvegarde, monté en volume par l'hôte. Vide (défaut) =
    # sauvegarde désactivée : un instantané écrit dans la couche éphémère du
    # conteneur, sans volume monté, disparaîtrait au prochain redémarrage sans
    # que personne ne le remarque — mieux vaut l'absence visible d'un filet.
    # Reprend la mécanique de `scripts/backup-prod.sh` (même méthode de copie,
    # même politique write-once sur les polices) depuis le process qui sert
    # déjà la base, sans `docker exec` ni tâche planifiée externe — portable
    # sur n'importe quel hôte Docker, pas seulement un NAS Synology.
    backup_dir: str = ""

    # ---------- Version et mise à jour ----------

    # Version de l'image, injectée au build (cf. Dockerfile `ARG`). Vide en
    # développement — l'interface affiche alors « dev », ce qui est la vérité.
    fontsync_version: str = ""

    # Mise à jour à la demande depuis l'interface. FontSync ne touche **jamais**
    # au socket Docker : il délègue à un conteneur Watchtower voisin, qui seul
    # détient ce privilège. Sans ces deux valeurs, le bouton est simplement
    # absent de l'interface (l'endpoint répond 503).
    watchtower_url: str = ""
    watchtower_token: str = ""

    # S3 settings (utilisés si storage_backend == "s3")
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = ""

    model_config = {"env_prefix": ""}


settings = Settings()
