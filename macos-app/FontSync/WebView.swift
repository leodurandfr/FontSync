// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

import SwiftUI
import WebKit

/// Enveloppe SwiftUI d'une `WKWebView` (P3.2).
///
/// La fenêtre est « nue » : pas de chrome custom, on charge directement l'UI
/// web servie par le serveur (`backend/main.py` sert le SPA). Inutile de faire
/// servir le frontend par l'app — on pointe l'URL configurée.
struct WebView: NSViewRepresentable {
    let url: URL

    /// Requête qui **ignore le cache local** pour le document principal : le SPA
    /// est servi par le serveur et change à chaque mise à jour (assets hashés +
    /// index.html). Sans ça, WKWebView peut resservir une version périmée du
    /// frontend (ex. antérieure à l'auth par token) → REST 401 / WS déconnecté.
    private func freshRequest() -> URLRequest {
        URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.allowsBackForwardNavigationGestures = true
        webView.load(freshRequest())
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

    final class Coordinator {
        var currentURL: URL?
    }
}

/// Contenu de la fenêtre « Ouvrir FontSync » : la webview si une URL serveur est
/// configurée, sinon un message d'invite.
struct WebWindowContent: View {
    let serverURL: URL?

    var body: some View {
        Group {
            if let url = serverURL {
                WebView(url: url)
            } else {
                ContentUnavailableView {
                    Label("Serveur non configuré", systemImage: "exclamationmark.circle")
                } description: {
                    Text("Renseignez l'URL du serveur dans la configuration de l'agent (~/.fontsync/config.yaml).")
                }
            }
        }
        .frame(minWidth: 900, minHeight: 600)
    }
}
