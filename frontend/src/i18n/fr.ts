import type en from "./en";

const fr: typeof en = {
  common: {
    back: "Retour",
    retry: "Réessayer",
    download: "Télécharger",
    install: "Installer",
    installed: "Installée",
    offline: "Hors ligne",
    connected: "Connecté",
    loadError: "Erreur de chargement",
    unknownError: "Erreur inconnue",
    variable: "Variable",
    cancel: "Annuler",
  },
  sidebar: {
    library: "Bibliothèque",
    allFonts: "Toutes les polices",
    categories: "Catégories",
    manage: "Gestion",
    duplicates: "Doublons",
    trash: "Corbeille",
    upload: "Uploader",
    settings: "Paramètres",
    collapse: "Replier",
    openSidebar: "Ouvrir la sidebar",
    reconnecting: "Reconnexion…",
  },
  window: {
    close: "Fermer",
    minimize: "Réduire",
    zoom: "Agrandir",
  },
  categories: {
    serif: "Serif",
    "sans-serif": "Sans-serif",
    monospace: "Monospace",
    display: "Display",
    handwriting: "Manuscrite",
    symbol: "Symbole",
  },
  theme: {
    label: "Thème",
    light: "Clair",
    dark: "Sombre",
    system: "Système",
    aria: "Thème",
  },
  toolbar: {
    preview: "Aperçu",
    typeSomething: "Saisissez un texte…",
    search: "Rechercher…",
    specimen: "Specimen",
    list: "Liste",
    familyCount: "{n} famille | {n} familles",
  },
  fonts: {
    noFontsFound: "Aucune police trouvée",
    adjustFilters: "Ajustez les filtres",
    loadError: "Erreur de chargement",
    styleCount: "{n} style | {n} styles",
    installedOnCount: "Installée sur {n} de vos {total} machines",
  },
  fontDetail: {
    trash: "Mettre à la corbeille",
    trashTitle: "Mettre « {name} » à la corbeille ?",
    trashConfirm:
      "La police sort de la bibliothèque mais reste dans la Corbeille, d'où vous pouvez la restaurer. Un Mac ne la désinstalle que si « Propager les suppressions » est activé pour cet appareil.",
    trashFailed: "Impossible de mettre la police à la corbeille : {error}",
    openDetails: "Voir les détails",
    cannotLoad: "Impossible de charger la police.",
    fonts: "Polices",
    preview: "Aperçu",
    inputPlaceholder: "Saisissez un texte…",
    waterfall: "Cascade",
    metadata: "Métadonnées",
    designer: "Designer",
    foundry: "Fonderie",
    version: "Version",
    license: "Licence",
    format: "Format",
    size: "Taille",
    hash: "Hash",
    weight: "Graisse",
    width: "Largeur",
    style: "Style",
    italic: "Italique",
    oblique: "Oblique",
    glyphs: "Glyphes",
    description: "Description",
    import: "Import",
    importDate: "Date d'import",
    source: "Source",
    importedFrom: "Importée depuis",
    languages: "Langues",
    classification: {
      serif: "Serif",
      "sans-serif": "Sans-serif",
      monospace: "Monospace",
      display: "Display",
      handwriting: "Manuscrite",
      symbol: "Symbole",
    },
    sources: {
      upload: "Upload web",
      local_scan: "Agent (scan local)",
      google_fonts: "Google Fonts",
    },
  },
  auth: {
    setupTitle: "Bienvenue sur FontSync",
    setupSubtitle: "Créez le compte administrateur de ce serveur.",
    loginSubtitle: "Connectez-vous pour continuer.",
    inviteSubtitle: "Créez votre compte : votre email et un mot de passe.",
    inviteSubtitleFixed: "Choisissez le mot de passe du compte {email}.",
    email: "Email",
    password: "Mot de passe",
    newPassword: "Mot de passe",
    confirmPassword: "Confirmez le mot de passe",
    passwordHint: "{n} caractères minimum.",
    createAdmin: "Créer le compte",
    acceptInvite: "Créer mon compte",
    signIn: "Se connecter",
    forgotPassword:
      "Mot de passe oublié ? Demandez à l'administrateur de le réinitialiser.",
    errors: {
      badCredentials: "Email ou mot de passe incorrect.",
      tooManyAttempts: "Trop de tentatives. Réessayez dans une minute.",
      passwordTooShort: "Le mot de passe doit faire au moins {n} caractères.",
      passwordMismatch: "Les deux mots de passe diffèrent.",
      invitationInvalid: "Cette invitation est invalide ou a expiré.",
      unreachable: "Serveur injoignable. Vérifiez l'URL et le réseau.",
    },
  },
  account: {
    title: "Mon compte",
    signedInAs: "Connecté en tant que {email}",
    roleAdmin: "Administrateur",
    roleMember: "Membre",
    changePassword: "Changer le mot de passe",
    currentPassword: "Mot de passe actuel",
    newPassword: "Nouveau mot de passe",
    save: "Enregistrer",
    passwordChanged:
      "Mot de passe changé. Vos autres sessions ont été déconnectées.",
    logout: "Se déconnecter",
    sessions: "Mes sessions",
    sessionsDesc:
      "Chaque navigateur et chaque Mac a sa propre session. Révoquez celles que vous ne reconnaissez pas.",
    browser: "Navigateur",
    mac: "Mac",
    thisSession: "Cette session",
    lastUsed: "Dernière activité : {date}",
    revoke: "Révoquer",
    noSessions: "Aucune autre session.",
  },
  removals: {
    title: "Polices retirées de mes Mac",
    desc: "Les polices que vous avez supprimées sur un de vos Mac. Elles restent dans la bibliothèque partagée, mais vos Mac ne les réinstallent plus. Ceux où « Suivre mes suppressions » est activé les désinstallent.",
    empty: "Aucune police retirée.",
    removedFrom: "Retirée de {device} le {date}",
    removedOn: "Retirée le {date}",
    pendingTitle:
      "{n} retrait en attente de confirmation | {n} retraits en attente de confirmation",
    pendingDesc:
      "Un de vos Mac a perdu beaucoup de polices d'un coup. Par sécurité, vos autres Mac ne les désinstalleront qu'après votre confirmation.",
    confirm: "Confirmer",
    pending: "En attente",
    undo: "Remettre",
  },
  users: {
    title: "Comptes",
    desc: "Tous les comptes partagent la même bibliothèque. Chacun gère ses propres Mac.",
    you: "vous",
    disabled: "Désactivé",
    devices: "{n} Mac | {n} Mac | {n} Mac",
    makeAdmin: "Rendre administrateur",
    makeMember: "Rendre membre",
    disable: "Désactiver",
    enable: "Réactiver",
    resetPassword: "Réinitialiser le mot de passe",
    resetPasswordDesc:
      "Toutes les sessions de {email} seront déconnectées. Transmettez-lui le nouveau mot de passe.",
    inviteDesc:
      "La personne y saisit son email et choisit son mot de passe. Le lien sert une seule fois et reste valable 7 jours.",
    createInvite: "Créer un lien d'invitation",
    inviteLink: "Lien d'invitation, à copier et envoyer :",
    linkCreated: "Lien créé le {date}",
    copy: "Copier",
    copied: "Copié",
    pending: "Invitations en attente",
    expires: "Expire le {date}",
    cancelInvite: "Annuler",
    cancel: "Annuler",
    confirm: "Valider",
  },
  settings: {
    title: "Paramètres",
    subtitle: "Configuration de votre instance FontSync.",
    appearance: "Apparence",
    theme: "Thème",
    themeDesc: "Choisissez l'apparence claire, sombre ou celle du système.",
    language: "Langue",
    languageDesc: "Choisissez la langue de l'interface.",
    server: "Serveur",
    serverUrl: "URL du serveur",
    websocket: "WebSocket",
    wsConnected: "Connecté",
    wsConnecting: "Connexion...",
    wsDisconnected: "Déconnecté",
    version: "Version",
    updateServer: "Mettre à jour",
    // La mise à jour recrée le conteneur qui sert cette page. L'attente est
    // normale et doit être annoncée, sinon elle passe pour un plantage.
    updateRestarting:
      "Le serveur est en cours de remplacement. Cette page se reconnecte toute seule — comptez jusqu'à une minute.",
    updateDone: "Serveur mis à jour — version {version}.",
    updateAlreadyCurrent: "Déjà sur la dernière image publiée.",
    updateTimeout:
      "Le serveur n'est pas encore revenu. Il démarre peut-être encore : rechargez dans un instant, ou vérifiez le conteneur sur votre NAS.",
    updateNotConfigured:
      "La mise à jour depuis l'interface n'est pas configurée sur ce serveur. Ajoutez le service watchtower du compose de déploiement, ou mettez à jour à la main.",
    backups: "Sauvegardes",
    backupsDisabled:
      "Sauvegardes automatiques désactivées sur ce serveur (BACKUP_DIR non défini).",
    backupsLast: "Dernier instantané de la base : {date} ({size}).",
    backupsNone: "Aucun instantané de la base pour l'instant.",
    backupsMirror:
      "Miroir des polices : {date} — {copied} copiés, {repaired} réparés, {failed} en échec.",
    backupsStale:
      "Aucune sauvegarde de la base depuis plus de 36 h. Vérifiez le dossier de sauvegarde et les journaux du serveur.",
    backupsNeverOk:
      "Aucun instantané de la base n'a encore réussi. Vérifiez le dossier de sauvegarde et les journaux du serveur.",
    backupsError: "La dernière sauvegarde a échoué : {error}",
    backupsMirrorFailed:
      "{n} police n'a pas pu être copiée dans le miroir. Voir les journaux du serveur. | {n} polices n'ont pas pu être copiées dans le miroir. Voir les journaux du serveur.",
    agent: "Agent de synchronisation",
    agentDesc:
      "L'agent FontSync tourne en arrière-plan sur votre Mac. Il détecte automatiquement les nouvelles polices installées et les synchronise avec le serveur.",
    downloadAgent: "Télécharger FontSync.app pour macOS",
    agentSoon: "Le téléchargement de l'agent sera disponible prochainement.",
  },
  devices: {
    title: "Appareils",
    desc: "Machines connectées à votre bibliothèque FontSync.",
    none: "Aucun appareil enregistré.",
    installHint: "Installez l'agent FontSync sur une machine pour commencer.",
    connected: "Connecté",
    // Connecté (listen vivant) mais l'agent n'est pas passé depuis le seuil
    // serveur : son job sync ne démarre peut-être plus (M-39).
    connectedOverdue: "Connecté — dernier sync {time}",
    connectedNeverSynced: "Connecté — aucun sync enregistré",
    seenAgo: "Vu {time}",
    // En minuscules : insérés dans une phrase (« Vu il y a 5 min »).
    never: "jamais",
    justNow: "à l'instant",
    minutesAgo: "il y a {n} min",
    hoursAgo: "il y a {n} h",
    daysAgo: "il y a {n} j",
    rescan: "Re-scan",
    autoPush: "Push automatique",
    autoPushDesc: "Envoie les nouvelles polices au serveur",
    autoPull: "Pull automatique",
    autoPullDesc: "Installe les polices du serveur sur cet appareil",
    // Formulé comme un échange dans les deux sens, et gardé à part de
    // push/pull : c'est le seul réglage qui puisse faire disparaître un fichier.
    propagateDeletions: "Suivre mes suppressions",
    propagateDeletionsDesc:
      "Désinstalle de ce Mac les polices que vous supprimez sur vos autres Mac. Désactivé par défaut : sans ça, aucun fichier n'est jamais effacé ici. Ni la corbeille de la bibliothèque ni un autre compte, admin compris, ne retirent jamais une police de ce Mac.",
    delete: "Retirer l'appareil",
    deleteTitle: "Retirer « {name} » ?",
    deleteConfirm:
      "L'appareil sort de cette liste. Rien n'est effacé : vos polices restent sur le serveur et sur la machine. Si son agent tourne encore, il réapparaîtra à son prochain sync — pour le retirer pour de bon, désinstallez d'abord l'agent sur cette machine.",
    watchedFolders: "Dossiers surveillés",
    // Agent ≤ 0.1.2 : il n'annonce pas ses capacités (B-32, M-32).
    agentTooOld:
      "Agent trop ancien : les suppressions faites sur ce Mac ne sont pas suivies. Mettez à jour l'app FontSync sur ce Mac.",
    agentTooOldAction:
      "L'agent de ce Mac est trop ancien pour cette action. Mettez à jour l'app FontSync.",
  },
  duplicates: {
    title: "Doublons",
    subtitle:
      "La même police sous plusieurs noms de fichier. Comme chaque nom donne une empreinte différente, la déduplication à l'import ne les voit pas — ils sont repérés ici sur l'identité réelle de la face : famille typographique et style.",
    none: "Aucun doublon.",
    noneDesc: "{n} police passée au crible. | {n} polices passées au crible.",
    summary:
      "{files} fichier en trop sur {faces} face, {size} à libérer. | {files} fichiers en trop sur {faces} faces, {size} à libérer.",
    // Dire la règle, pas seulement le chiffre : c'est elle qu'on révise ici,
    // groupe par groupe ce serait des heures.
    rule: "Pour chaque face, le fichier le plus complet est gardé, un format installable (OTF, TTF) passant avant une police web — une police variable ou une collection l'emporte toujours, puisqu'elle porte des styles que les autres n'ont pas.",
    reversible:
      "Rien n'est effacé du serveur : les fichiers partent à la corbeille, d'où ils se restaurent d'un clic tant que vous ne l'avez pas vidée. Une police restaurée n'est réinstallée que sur les appareils en « Pull automatique ».",
    protectedSummary:
      "{n} fichier en trop est gardé : c'est la seule copie de sa face sur {devices}, qui a « Propager les suppressions » sans « Pull automatique » — le retirer l'y effacerait sans rien réinstaller. Activer le pull automatique sur cet appareil le rendrait retirable. | {n} fichiers en trop sont gardés : chacun est la seule copie de sa face sur {devices}, qui a « Propager les suppressions » sans « Pull automatique » — les retirer les y effacerait sans rien réinstaller. Activer le pull automatique sur ces appareils les rendrait retirables.",
    protectedOn: "Gardé (seule copie sur {devices}) :",
    doneProtected:
      "{n} fichier en trop a été gardé : seule copie de sa face sur un appareil. | {n} fichiers en trop ont été gardés : seule copie de leur face sur un appareil.",
    resolve:
      "Envoyer {n} fichier à la corbeille | Envoyer {n} fichiers à la corbeille",
    review: "Ce qui sera retiré",
    showing: "{shown} faces affichées sur {total}",
    kept: "Gardé :",
    exclude: "Garder",
    include: "Retirer",
    doneTitle:
      "{n} fichier envoyé à la corbeille. | {n} fichiers envoyés à la corbeille.",
    doneDesc:
      "{size} seront libérés au vidage de la corbeille. D'ici là, tout est restaurable.",
    seeTrash: "Voir la corbeille",
  },

  trash: {
    title: "Corbeille",
    subtitle:
      "Les polices supprimées restent ici jusqu'à ce que vous les restauriez ou vidiez la corbeille.",
    deletedFonts: "Polices supprimées",
    none: "La corbeille est vide.",
    restore: "Restaurer",
    empty: "Vider la corbeille",
    deletedOn: "Supprimée le {date}",
    // Vider est irréversible et le geste ne le dit pas de lui-même. La note sur
    // l'empreinte reste : sans elle, « la police revient toute seule » passerait
    // pour un bug plutôt que pour la mécanique qui rend une suppression durable.
    emptyExplainer:
      "Vider retire définitivement les fichiers du stockage : les polices concernées quittent la corbeille et ne sont plus restaurables. FontSync conserve leur empreinte, sans quoi elles reviendraient au premier sync d'une machine qui détient encore le fichier. Les suppressions en attente d'arbitrage ne sont pas vidées.",
    emptyDone:
      "{n} fichier retiré du stockage. | {n} fichiers retirés du stockage.",
    emptyRetained:
      "{n} suppression en attente d'arbitrage n'a pas été vidée : confirmez-la ou restaurez-la. | {n} suppressions en attente d'arbitrage n'ont pas été vidées : confirmez-les ou restaurez-les.",
    restoreAutoPullNote:
      "Restaurer remet la police dans la bibliothèque. Ces appareils ont le pull automatique désactivé et ne la réinstalleront pas : {devices}.",
    pendingTitle:
      "{n} suppression en attente d'arbitrage | {n} suppressions en attente d'arbitrage",
    pendingDesc:
      "Une version précédente de FontSync a sorti ces polices de la bibliothèque après une disparition massive sur un appareil. Confirmez pour pouvoir vider la corbeille, ou restaurez-les. Aucun Mac ne les désinstallera.",
    confirmPending: "Confirmer",
    awaitingArbitration: "En attente d'arbitrage",
  },
  upload: {
    trigger: "Uploader",
    title: "Uploader des polices",
    acceptedFormats: "Formats acceptés : TTF, OTF, TTC, WOFF, WOFF2.",
    uploading: "Upload en cours…",
    dropHint: "Glissez vos fichiers ou un dossier, ou cliquez",
    imported: "{n} police importée. | {n} polices importées.",
    duplicates: "{n} déjà présente (ignorée). | {n} déjà présentes (ignorées).",
  },
  deviceInstall: {
    devices: "Appareils",
    title: "Installation par appareil",
    descSingle: "Synchronisez cette police sur vos machines connectées.",
    descMulti: "Synchronisez ces {n} polices sur vos machines connectées.",
    mirrorNote:
      "Les polices se synchronisent en miroir selon le réglage « pull automatique » de chaque appareil. La désinstallation par appareil arrive dans une prochaine version.",
    none: "Aucun appareil enregistré.",
    present: "Présente sur l'appareil",
    disabledHere: "Désactivée sur cet appareil",
    disabledPartially: "Désactivée sur certains styles",
    toggleActive: "Active sur cet appareil",
    notInstalledSingle: "Non installée",
    notInstalledMulti: "Non installées",
    installedOn: "Installée le {date}",
    // En régime normal la police apparaît en quelques secondes ; si l'index de
    // macOS s'est figé, l'agent le fait reconstruire et ça prend plus longtemps.
    // Le message couvre les deux cas sans promettre un délai qui n'a pas lieu
    // d'être — et sans laisser l'attente passer pour un échec.
    indexing: "Installation en cours",
    indexingHint:
      "Le fichier est copié. Si elle n'apparaît pas tout de suite, macOS reconstruit son index de polices — comptez jusqu'à une minute.",
  },
};

export default fr;
