// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import AppKit
import QuartzCore
import SwiftUI
import WebKit

/// Enveloppe SwiftUI d'une `WKWebView` (P3.2).
///
/// La fenêtre est « nue » : pas de barre de titre native, on charge directement
/// l'UI web servie par le serveur (`backend/main.py` sert le SPA). L'app injecte
/// au `documentStart` un flag `__FONTSYNC_NATIVE__` (qui fait afficher au front
/// ses propres contrôles de fenêtre) et un pont `fontsyncWindow` qui exécute
/// close/minimize/zoom/drag sur le `NSWindow` et aligne l'apparence (clair/
/// sombre) de la fenêtre sur le thème de l'UI — sans quoi le cadre natif suit
/// l'OS et garde une bordure sombre en thème clair sous un OS en mode sombre.
/// Hors app (navigateur), rien de tout ça n'existe : le front garde le chrome
/// du navigateur.
struct WebView: NSViewRepresentable {
    let url: URL

    /// Requête qui **ignore le cache local** pour le document principal : le SPA
    /// est servi par le serveur et change à chaque mise à jour (assets hashés +
    /// index.html). Sans ça, WKWebView peut resservir une version périmée du
    /// frontend (ex. antérieure à l'auth par token) → REST 401 / WS déconnecté.
    private func freshRequest() -> URLRequest {
        URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
    }

    /// Script injecté avant tout JS de page : pose le flag « natif » et relaie au
    /// pont les `mousedown`/`dblclick` sur les zones marquées `[data-window-drag]`
    /// (sauf au-dessus d'un élément interactif), pour déplacer / agrandir la
    /// fenêtre depuis les barres flottantes de l'UI.
    private static let bridgeScript = """
    (function () {
      window.__FONTSYNC_NATIVE__ = true;
      var mh = window.webkit && window.webkit.messageHandlers;
      var bridge = mh && mh.fontsyncWindow;
      if (!bridge) return;

      var INTERACTIVE =
        'button, a, input, textarea, select, label,' +
        ' [role="button"], [contenteditable]';

      // Hauteur (px depuis le haut de la fenêtre) de la bande de titre virtuelle :
      // tout le haut de la page y déplace la fenêtre — barres flottantes ET fond
      // entre/autour d'elles —, sauf au-dessus d'un élément interactif. La valeur
      // couvre la hauteur des barres (~48px) + la gouttière (12px).
      var TOP_BAND = 60;

      function onBar(e) {
        var t = e.target;
        if (!(t instanceof Element)) return false;
        if (t.closest(INTERACTIVE)) return false;
        if (e.clientY <= TOP_BAND) return true;
        return !!t.closest('[data-window-drag]');
      }

      document.addEventListener('mousedown', function (e) {
        if (e.button === 0 && onBar(e)) bridge.postMessage({ action: 'drag' });
      }, true);

      document.addEventListener('dblclick', function (e) {
        if (onBar(e)) bridge.postMessage({ action: 'zoom' });
      }, true);

      // Remonte le thème de l'UI (clair/sombre) au natif, qui aligne l'apparence
      // de la fenêtre dessus : sinon le cadre natif (sa bordure 1px) suit l'OS et
      // reste sombre en mode sombre alors que l'UI est claire. Le thème = présence
      // de la classe `dark` sur <html> (cf. frontend useTheme). Re-émis à chaque
      // changement (bascule de thème, préférence système).
      function reportTheme() {
        try {
          bridge.postMessage({
            action: 'theme',
            dark: document.documentElement.classList.contains('dark')
          });
        } catch (e) {}
      }
      document.addEventListener('DOMContentLoaded', reportTheme);
      window.addEventListener('load', reportTheme);
      try {
        new MutationObserver(reportTheme).observe(document.documentElement, {
          attributes: true, attributeFilter: ['class']
        });
      } catch (e) {}
    })();
    """

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()

        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "fontsyncWindow")
        controller.addUserScript(
            WKUserScript(
                source: Self.bridgeScript,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        configuration.userContentController = controller

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.allowsBackForwardNavigationGestures = true
        // Sans délégué de navigation, la WKWebView ignore les téléchargements :
        // le front télécharge les fonts via un blob authentifié + `<a download>`
        // (le token ne peut pas voyager dans un `href` direct sur route `/api`),
        // et un clic sur un tel lien ne produit rien sans `WKDownloadDelegate`.
        webView.navigationDelegate = context.coordinator
        webView.load(freshRequest())
        context.coordinator.webView = webView
        context.coordinator.currentURL = url
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Recharge uniquement si l'URL configurée a changé (évite de relancer
        // la navigation à chaque re-render SwiftUI).
        if context.coordinator.currentURL != url {
            context.coordinator.currentURL = url
            webView.load(freshRequest())
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    /// Pont JS→AppKit. Conserve une réf faible à la webview pour atteindre son
    /// `NSWindow` ; les actions utilisent les méthodes directes (pas `perform*`)
    /// pour ne jamais émettre de bip même sans boutons de titre visibles.
    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate,
        WKDownloadDelegate
    {
        var currentURL: URL?
        weak var webView: WKWebView?

        /// Destination choisie pour chaque téléchargement en cours, pour pouvoir
        /// révéler le fichier dans le Finder une fois terminé (`WKDownload` n'expose
        /// pas de façon fiable l'URL de destination après coup).
        private var downloadDestinations: [ObjectIdentifier: URL] = [:]

        func userContentController(
            _ controller: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            guard
                let body = message.body as? [String: Any],
                let action = body["action"] as? String,
                let window = webView?.window
            else { return }

            switch action {
            case "close":
                window.close()
            case "minimize":
                window.miniaturize(nil)
            case "zoom":
                window.zoom(nil)
            case "drag":
                // `performDrag` prend le run-loop natif pour toute la durée du
                // glissé ; il lui faut l'événement mouse-down courant.
                if let event = NSApp.currentEvent {
                    window.performDrag(with: event)
                }
            case "ensureWidth":
                // L'UI (sidebar « modèle Finder ») demande que la fenêtre soit
                // assez large pour loger la sidebar sans écraser le contenu. On
                // l'agrandit si besoin, jamais on ne la rétrécit.
                if let want = body["width"] as? Double {
                    Self.ensureWidth(window, atLeast: CGFloat(want))
                }
            case "theme":
                // Force l'apparence de la fenêtre à suivre le thème de l'UI : son
                // cadre natif (bordure) est alors clair en thème clair, même si
                // l'OS est en mode sombre (et inversement).
                let dark = body["dark"] as? Bool ?? false
                let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                // `window.appearance` seul ne suffit pas (SwiftUI le réécrase et
                // le cadre suit l'apparence *application*) : on force donc aussi
                // `NSApplication.appearance`. Tout le chrome natif de FontSync
                // (menu, préférences) suit alors le thème de l'UI plutôt que l'OS.
                window.appearance = appearance
                NSApplication.shared.appearance = appearance
            default:
                break
            }
        }

        // MARK: Téléchargements

        /// Un `<a download>` (ou toute réponse en pièce jointe) doit devenir un
        /// téléchargement plutôt qu'une navigation : `shouldPerformDownload` est
        /// vrai quand l'action vient d'un lien marqué `download` (cas du front,
        /// qui clique un `<a download href="blob:…">`).
        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            if navigationAction.shouldPerformDownload {
                decisionHandler(.download)
            } else {
                decisionHandler(.allow)
            }
        }

        /// Filet de sécurité : une réponse `Content-Disposition: attachment` qui
        /// n'a pas été déclenchée par un lien `download` (téléchargement direct)
        /// est elle aussi convertie en téléchargement.
        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationResponse: WKNavigationResponse,
            decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
        ) {
            if let http = navigationResponse.response as? HTTPURLResponse,
                let disposition = http.value(forHTTPHeaderField: "Content-Disposition"),
                disposition.lowercased().contains("attachment")
            {
                decisionHandler(.download)
            } else {
                decisionHandler(.allow)
            }
        }

        func webView(
            _ webView: WKWebView,
            navigationAction: WKNavigationAction,
            didBecome download: WKDownload
        ) {
            download.delegate = self
        }

        func webView(
            _ webView: WKWebView,
            navigationResponse: WKNavigationResponse,
            didBecome download: WKDownload
        ) {
            download.delegate = self
        }

        /// Choisit la destination du téléchargement : `~/Downloads`, en évitant
        /// d'écraser un fichier existant (suffixe ` (n)` comme le navigateur).
        func download(
            _ download: WKDownload,
            decideDestinationUsing response: URLResponse,
            suggestedFilename: String,
            completionHandler: @escaping (URL?) -> Void
        ) {
            let downloads = FileManager.default.urls(
                for: .downloadsDirectory, in: .userDomainMask
            ).first
            guard let downloads else {
                completionHandler(nil)
                return
            }
            let name = suggestedFilename.isEmpty ? "fontsync-download" : suggestedFilename
            let destination = Self.uniqueURL(in: downloads, filename: name)
            downloadDestinations[ObjectIdentifier(download)] = destination
            completionHandler(destination)
        }

        /// Révèle le fichier dans le Finder une fois le transfert terminé, pour
        /// donner un retour visible (la fenêtre web ne montre rien d'autre).
        func downloadDidFinish(_ download: WKDownload) {
            let key = ObjectIdentifier(download)
            if let url = downloadDestinations.removeValue(forKey: key) {
                NSWorkspace.shared.activateFileViewerSelecting([url])
            }
        }

        func download(
            _ download: WKDownload,
            didFailWithError error: Error,
            resumeData: Data?
        ) {
            downloadDestinations.removeValue(forKey: ObjectIdentifier(download))
            NSLog("FontSync: téléchargement échoué — \(error.localizedDescription)")
        }

        /// Construit une URL non utilisée dans `directory` : `name`, puis
        /// `name (1)`, `name (2)`… en préservant l'extension.
        private static func uniqueURL(in directory: URL, filename: String) -> URL {
            let fm = FileManager.default
            var candidate = directory.appendingPathComponent(filename)
            guard fm.fileExists(atPath: candidate.path) else { return candidate }

            let ext = (filename as NSString).pathExtension
            let base = (filename as NSString).deletingPathExtension
            var index = 1
            repeat {
                let suffixed = ext.isEmpty ? "\(base) (\(index))" : "\(base) (\(index)).\(ext)"
                candidate = directory.appendingPathComponent(suffixed)
                index += 1
            } while fm.fileExists(atPath: candidate.path)
            return candidate
        }

        /// Agrandit la fenêtre pour atteindre au moins `want` points de large,
        /// en gardant le bord gauche fixe (le contenu glisse vers la droite avec
        /// la sidebar). Animée pour rester synchrone avec la transition CSS
        /// (~200 ms, easeInEaseOut). Jamais de rétrécissement (modèle Finder) ;
        /// largeur et position bornées à la zone d'écran visible.
        private static func ensureWidth(_ window: NSWindow, atLeast want: CGFloat) {
            // Le contenu remplit le cadre (fullSizeContentView, pas de titlebar) :
            // la largeur de cadre ≈ la largeur en px CSS envoyée par l'UI.
            guard want > window.frame.width else { return }

            var frame = window.frame
            frame.size.width = want

            if let visible = window.screen?.visibleFrame {
                frame.size.width = min(frame.size.width, visible.width)
                // Déborde à droite : on décale vers la gauche pour rester à l'écran.
                if frame.maxX > visible.maxX {
                    frame.origin.x = visible.maxX - frame.size.width
                }
            }

            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.2
                ctx.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
                window.animator().setFrame(frame, display: true)
            }
        }
    }
}

/// Masque **tout** le chrome natif de la fenêtre : barre de titre, titre, et les
/// trois feux de circulation système. On ne se repose pas sur le timing de
/// `makeNSView` (le `NSWindow` y est souvent encore `nil`) : une `NSView`
/// dédiée configure la fenêtre dans `viewDidMoveToWindow`, c.-à-d. exactement
/// quand elle est rattachée. Vue de taille nulle insérée en overlay du contenu.
private struct WindowChromeConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView { ChromeView() }
    func updateNSView(_ nsView: NSView, context: Context) {}

    private final class ChromeView: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard let window else { return }
            Self.strip(window)
            // Re-applique au tour de run-loop suivant : SwiftUI peut (re)poser
            // son style de fenêtre après l'attachement de la vue, ce qui
            // ré-afficherait les feux si on ne repassait pas derrière.
            DispatchQueue.main.async { Self.strip(window) }
        }

        private static func strip(_ window: NSWindow) {
            window.titleVisibility = .hidden
            window.titlebarAppearsTransparent = true
            // Contenu plein cadre (sous l'emplacement de l'ex-barre de titre).
            window.styleMask.insert(.fullSizeContentView)
            window.standardWindowButton(.closeButton)?.isHidden = true
            window.standardWindowButton(.miniaturizeButton)?.isHidden = true
            window.standardWindowButton(.zoomButton)?.isHidden = true
            // Le drag passe par le pont JS (`performDrag`) sur les barres de
            // l'UI, pas par le fond de fenêtre.
            window.isMovableByWindowBackground = false
        }
    }
}

/// Contenu de la fenêtre « Ouvrir FontSync » : la webview si une URL serveur est
/// configurée, sinon un message d'invite.
struct WebWindowContent: View {
    let serverURL: URL?

    var body: some View {
        Group {
            if let url = serverURL {
                // `ignoresSafeArea` : sans ça, SwiftUI insère la webview SOUS
                // l'emplacement de l'ex-barre de titre (safe area), laissant un
                // bandeau de fond visible. On la fait remonter bord à bord.
                WebView(url: url)
                    .ignoresSafeArea()
            } else {
                ContentUnavailableView {
                    Label("Serveur non configuré", systemImage: "exclamationmark.circle")
                } description: {
                    Text("Renseignez l'URL du serveur dans la configuration de l'agent (~/.fontsync/config.yaml).")
                }
            }
        }
        .frame(minWidth: 640, minHeight: 600)
        .background(WindowChromeConfigurator().frame(width: 0, height: 0))
    }
}
