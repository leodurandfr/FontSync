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
  },
  fontDetail: {
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
  tokenGate: {
    subtitle: "Saisissez le token d'accès de votre instance pour continuer.",
    tokenLabel: "Token serveur",
    connect: "Se connecter",
    verifying: "Vérification…",
    definedBy: "Défini par {code} côté serveur.",
    errors: {
      enterToken: "Veuillez saisir un token.",
      invalid: "Token invalide.",
      server: "Erreur serveur ({status}).",
      unreachable: "Serveur injoignable. Vérifiez l'URL et le réseau.",
    },
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
    accessToken: "Token d'accès",
    tokenDesc:
      "Le token d'instance ({code}) protège l'accès à cette bibliothèque. Il est mémorisé dans ce navigateur. Changez-le pour saisir un autre token ou vous déconnecter de cette instance.",
    changeToken: "Changer le token",
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
    seenAgo: "Vu {time}",
    never: "Jamais",
    justNow: "À l'instant",
    minutesAgo: "Il y a {n} min",
    hoursAgo: "Il y a {n} h",
    daysAgo: "Il y a {n} j",
    scanning: "Scan en cours…",
    syncing: "Synchronisation…",
    rescan: "Re-scan",
    autoPush: "Push automatique",
    autoPushDesc: "Envoie les nouvelles polices au serveur",
    autoPull: "Pull automatique",
    autoPullDesc: "Installe les polices du serveur sur cet appareil",
    // Formulé comme un échange dans les deux sens, et gardé à part de
    // push/pull : c'est le seul réglage qui puisse faire disparaître un fichier.
    propagateDeletions: "Propager les suppressions",
    propagateDeletionsDesc:
      "Désinstalle de cet appareil les polices supprimées du serveur. Désactivé par défaut : sans ça, aucun fichier n'est jamais effacé ici. Les suppressions faites sur cet appareil, elles, sont enregistrées par le serveur dans tous les cas — ce réglage ne commande que ce qui s'efface.",
    delete: "Retirer l'appareil",
    deleteConfirm:
      "Retirer « {name} » ? Vos polices restent sur le serveur. Ce qui est perdu, c'est la trace des polices que cette machine détenait — la base de la détection des suppressions locales.",
    watchedFolders: "Dossiers surveillés",
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
    rule: "Pour chaque face, le fichier le plus complet est gardé — une police variable ou une collection l'emporte toujours, puisqu'elle porte des styles que les autres n'ont pas.",
    reversible:
      "Rien n'est effacé : les fichiers partent à la corbeille, d'où ils reviennent d'un clic tant que vous ne l'avez pas vidée.",
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
    // Vider garde la ligne, à dessein. Le dire franchement : ça ressemble à une
    // demi-mesure tant qu'on n'en connaît pas la raison.
    emptyExplainer:
      "Vider retire les fichiers du stockage mais conserve l'empreinte de chaque police. C'est cette empreinte qui rend une suppression durable : sans elle, la police reviendrait au premier sync d'une machine qui détient encore le fichier.",
    purged: "Fichier retiré",
    purgedHint:
      "Le fichier a été retiré du stockage. Ré-importez-le pour retrouver cette police.",
    restoreAutoPullNote:
      "Restaurer remet la police dans la bibliothèque. Ces appareils ont le pull automatique désactivé et ne la réinstalleront pas : {devices}.",
    pendingTitle:
      "{n} suppression en attente d'arbitrage | {n} suppressions en attente d'arbitrage",
    pendingDesc:
      "Un appareil a signalé d'un coup plus de disparitions que le seuil de sécurité n'en autorise. Elles sont hors de la bibliothèque et récupérables, mais aucune autre machine ne les désinstallera tant que vous n'aurez pas confirmé.",
    confirmPending: "Confirmer et propager",
    reasons: {
      quarantine: "Supprimée sur un appareil",
      quarantine_pending: "En attente d'arbitrage",
    },
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
      "Les polices se synchronisent en miroir selon le réglage « pull automatique » de chaque appareil. La désinstallation et l'activation par appareil arrivent dans une prochaine version.",
    none: "Aucun appareil enregistré.",
    present: "Présente sur l'appareil",
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
