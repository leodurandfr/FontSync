// Contrôles de fenêtre « façon macOS » (close / minimize / zoom).
//
// Ces boutons n'ont de sens que lorsque l'UI est rendue dans la fenêtre « nue »
// de l'app menu-bar (WKWebView). Dans un navigateur classique (accès via une
// URL), on garde le chrome natif du navigateur et on ne les affiche pas.
//
// Détection « natif » : l'app Swift injectera un handler de message dédié
// (`window.webkit.messageHandlers.fontsyncWindow`) et/ou un flag global. Tant
// que ce câblage natif n'est pas en place, on s'appuie sur `import.meta.env.DEV`
// pour pouvoir valider visuellement le rendu sur le serveur de dev (8765).

type WindowAction = "close" | "minimize" | "zoom";

interface FontSyncBridge {
  postMessage: (message: { action: WindowAction }) => void;
}

function nativeBridge(): FontSyncBridge | undefined {
  return (
    window as unknown as {
      webkit?: { messageHandlers?: { fontsyncWindow?: FontSyncBridge } };
    }
  ).webkit?.messageHandlers?.fontsyncWindow;
}

function isNativeWindow(): boolean {
  return (
    Boolean(nativeBridge()) ||
    (window as unknown as { __FONTSYNC_NATIVE__?: boolean })
      .__FONTSYNC_NATIVE__ === true
  );
}

/** Vrai si on doit afficher les contrôles de fenêtre custom. */
export const showWindowControls = import.meta.env.DEV || isNativeWindow();

/**
 * Relaie une action de fenêtre au natif. No-op dans un navigateur (pas de pont),
 * ce qui est exactement le comportement voulu pendant la validation en dev.
 */
function sendWindowAction(action: WindowAction): void {
  nativeBridge()?.postMessage({ action });
}

export function useWindowControls() {
  return {
    showWindowControls,
    close: () => sendWindowAction("close"),
    minimize: () => sendWindowAction("minimize"),
    zoom: () => sendWindowAction("zoom"),
  };
}
