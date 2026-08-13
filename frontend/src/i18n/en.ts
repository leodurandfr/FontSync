export default {
  common: {
    back: "Back",
    retry: "Retry",
    download: "Download",
    install: "Install",
    installed: "Installed",
    offline: "Offline",
    connected: "Connected",
    loadError: "Failed to load",
    unknownError: "Unknown error",
    variable: "Variable",
  },
  sidebar: {
    library: "Library",
    allFonts: "All fonts",
    categories: "Categories",
    manage: "Manage",
    duplicates: "Duplicates",
    trash: "Trash",
    upload: "Upload",
    settings: "Settings",
    collapse: "Collapse",
    openSidebar: "Open sidebar",
    reconnecting: "Reconnecting…",
  },
  window: {
    close: "Close",
    minimize: "Minimize",
    zoom: "Zoom",
  },
  categories: {
    serif: "Serif",
    "sans-serif": "Sans-serif",
    monospace: "Monospace",
    display: "Display",
    handwriting: "Handwriting",
    symbol: "Symbol",
  },
  theme: {
    label: "Theme",
    light: "Light",
    dark: "Dark",
    system: "System",
    aria: "Theme",
  },
  toolbar: {
    preview: "Preview",
    typeSomething: "Type something…",
    search: "Search…",
    specimen: "Specimen",
    list: "List",
    familyCount: "{n} family | {n} families",
  },
  fonts: {
    noFontsFound: "No fonts found",
    adjustFilters: "Adjust the filters",
    loadError: "Failed to load",
    styleCount: "{n} style | {n} styles",
    installedOnCount: "Installed on {n} of your {total} machines",
  },
  fontDetail: {
    openDetails: "View details",
    cannotLoad: "Could not load the font.",
    fonts: "Fonts",
    preview: "Preview",
    inputPlaceholder: "Type something…",
    waterfall: "Waterfall",
    metadata: "Metadata",
    designer: "Designer",
    foundry: "Foundry",
    version: "Version",
    license: "License",
    format: "Format",
    size: "Size",
    hash: "Hash",
    weight: "Weight",
    width: "Width",
    style: "Style",
    italic: "Italic",
    oblique: "Oblique",
    glyphs: "Glyphs",
    description: "Description",
    import: "Import",
    importDate: "Import date",
    source: "Source",
    importedFrom: "Imported from",
    languages: "Languages",
    classification: {
      serif: "Serif",
      "sans-serif": "Sans-serif",
      monospace: "Monospace",
      display: "Display",
      handwriting: "Handwriting",
      symbol: "Symbol",
    },
    sources: {
      upload: "Web upload",
      local_scan: "Agent (local scan)",
      google_fonts: "Google Fonts",
    },
  },
  tokenGate: {
    subtitle: "Enter your instance access token to continue.",
    tokenLabel: "Server token",
    connect: "Sign in",
    verifying: "Verifying…",
    definedBy: "Set by {code} on the server.",
    errors: {
      enterToken: "Please enter a token.",
      invalid: "Invalid token.",
      server: "Server error ({status}).",
      unreachable: "Server unreachable. Check the URL and your network.",
    },
  },
  settings: {
    title: "Settings",
    subtitle: "Configure your FontSync instance.",
    appearance: "Appearance",
    theme: "Theme",
    themeDesc: "Choose the light, dark, or system appearance.",
    language: "Language",
    languageDesc: "Choose the interface language.",
    server: "Server",
    serverUrl: "Server URL",
    websocket: "WebSocket",
    wsConnected: "Connected",
    wsConnecting: "Connecting…",
    wsDisconnected: "Disconnected",
    version: "Version",
    updateServer: "Update server",
    // The update recreates the very container serving this page. The wait is
    // normal and has to be said, or it reads as a crash.
    updateRestarting:
      "The server is being replaced. This page reconnects on its own — it can take a minute.",
    updateDone: "Server updated — now running {version}.",
    updateAlreadyCurrent: "Already on the latest published image.",
    updateTimeout:
      "The server has not come back yet. It may still be starting; reload in a moment, or check the container on your NAS.",
    updateNotConfigured:
      "Updating from here is not set up on this server. Add the watchtower service from the deployment compose file, or update manually.",
    accessToken: "Access token",
    tokenDesc:
      "The instance token ({code}) protects access to this library. It is stored in this browser. Change it to enter another token or sign out of this instance.",
    changeToken: "Change token",
    agent: "Sync agent",
    agentDesc:
      "The FontSync agent runs in the background on your Mac. It automatically detects newly installed fonts and syncs them with the server.",
    downloadAgent: "Download FontSync.app for macOS",
    agentSoon: "The agent download will be available soon.",
  },
  devices: {
    title: "Devices",
    desc: "Machines connected to your FontSync library.",
    none: "No registered device.",
    installHint: "Install the FontSync agent on a machine to get started.",
    connected: "Connected",
    seenAgo: "Seen {time}",
    never: "Never",
    justNow: "Just now",
    minutesAgo: "{n} min ago",
    hoursAgo: "{n} h ago",
    daysAgo: "{n} d ago",
    rescan: "Re-scan",
    autoPush: "Auto push",
    autoPushDesc: "Sends new fonts to the server",
    autoPull: "Auto pull",
    autoPullDesc: "Installs server fonts on this device",
    // Deliberately worded as a two-way exchange, and kept apart from push/pull:
    // this is the only setting that can make a file disappear.
    propagateDeletions: "Propagate deletions",
    propagateDeletionsDesc:
      "Uninstalls from this device the fonts deleted on the server. Off by default: without it, no file is ever erased here. Deletions made on this device are recorded by the server either way — this setting only governs what gets erased.",
    delete: "Remove device",
    deleteConfirm:
      "Remove “{name}”? Your fonts stay on the server. What is lost is the record of which fonts this machine held — the basis for detecting local deletions.",
    watchedFolders: "Watched folders",
  },
  duplicates: {
    title: "Duplicates",
    subtitle:
      "The same font under several filenames. Each name yields a different checksum, so import-time deduplication never sees them — they are found here on the face's real identity: typographic family and style.",
    none: "No duplicates.",
    noneDesc: "{n} font examined. | {n} fonts examined.",
    summary:
      "{files} redundant file across {faces} face, {size} to reclaim. | {files} redundant files across {faces} faces, {size} to reclaim.",
    // State the rule, not just the number: the rule is what you review here —
    // group by group would take hours.
    rule: "For each face the most complete file is kept — a variable font or a collection always wins, since it carries styles the others don't.",
    reversible:
      "Nothing is erased: files go to the trash, one click away from coming back for as long as you haven't emptied it.",
    resolve: "Move {n} file to trash | Move {n} files to trash",
    review: "What will be removed",
    showing: "Showing {shown} of {total} faces",
    kept: "Kept:",
    exclude: "Keep",
    include: "Remove",
    doneTitle: "{n} file moved to trash. | {n} files moved to trash.",
    doneDesc:
      "{size} will be reclaimed when you empty the trash. Until then everything is restorable.",
    seeTrash: "Open the trash",
  },

  trash: {
    title: "Trash",
    subtitle:
      "Deleted fonts stay here until you restore them or empty the trash.",
    deletedFonts: "Deleted fonts",
    none: "The trash is empty.",
    restore: "Restore",
    empty: "Empty trash",
    deletedOn: "Deleted {date}",
    // Emptying is irreversible and the gesture does not say so on its own. The
    // note about fingerprints stays: without it, "the font came back by itself"
    // reads as a bug rather than as what makes a deletion stick.
    emptyExplainer:
      "Emptying permanently removes the files from storage: those fonts leave the trash and can no longer be restored. FontSync keeps their fingerprint — without it they would come back the next time a machine that still has the file syncs. Deletions awaiting review are not emptied.",
    emptyDone:
      "{n} file removed from storage. | {n} files removed from storage.",
    emptyRetained:
      "{n} deletion awaiting review was not emptied: confirm it or restore it. | {n} deletions awaiting review were not emptied: confirm them or restore them.",
    restoreAutoPullNote:
      "Restoring puts the font back in the library. These devices have auto pull off and will not reinstall it: {devices}.",
    pendingTitle:
      "{n} deletion awaiting review | {n} deletions awaiting review",
    pendingDesc:
      "A device reported more disappearances at once than the safety threshold allows. They are out of the library and recoverable, but no other machine will uninstall them until you confirm.",
    confirmPending: "Confirm and propagate",
    awaitingArbitration: "Awaiting review",
  },
  upload: {
    trigger: "Upload",
    title: "Upload fonts",
    acceptedFormats: "Accepted formats: TTF, OTF, TTC, WOFF, WOFF2.",
    uploading: "Uploading…",
    dropHint: "Drag your files or a folder, or click",
    imported: "{n} font imported. | {n} fonts imported.",
    duplicates:
      "{n} already present (skipped). | {n} already present (skipped).",
  },
  deviceInstall: {
    devices: "Devices",
    title: "Per-device installation",
    descSingle: "Sync this font to your connected machines.",
    descMulti: "Sync these {n} fonts to your connected machines.",
    mirrorNote:
      "Fonts sync as a mirror based on each device's “auto pull” setting. Per-device uninstall is coming in a future version.",
    none: "No registered device.",
    present: "Present on the device",
    disabledHere: "Disabled on this device",
    disabledPartially: "Disabled on some styles",
    toggleActive: "Active on this device",
    notInstalledSingle: "Not installed",
    notInstalledMulti: "Not installed",
    installedOn: "Installed on {date}",
    // Normally the font shows up within seconds; if macOS's index has gone
    // stale, the agent has it rebuilt and that takes longer. The message covers
    // both cases without promising a delay that usually doesn't happen — and
    // without letting the wait read as a failure.
    indexing: "Installing",
    indexingHint:
      "The file is copied. If it doesn't show up right away, macOS is rebuilding its font index — allow up to a minute.",
  },
};
