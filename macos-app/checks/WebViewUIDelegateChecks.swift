// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Leo Durand
//
// This file is part of FontSync, a self-hosted font manager.

// Vérifications du délégué d'interface de la WebView (P1-6e, M-38).
//
// Sans `WKUIDelegate`, une WKWebView ignore en silence `window.confirm` (qui
// renvoie false), `window.alert`, `<input type=file>` et les liens
// `target=_blank` : supprimer un appareil, importer des polices ou ouvrir un
// lien de licence ne faisaient rien dans l'app.
//
// Compilé avec WebView.swift par checks/run.sh ; pas de cible XCTest.

import AppKit
import SwiftUI
import WebKit

/// Action de navigation factice : seule son URL compte pour `createWebViewWith`.
final class FakeNavigationAction: WKNavigationAction {
    private let fakeRequest: URLRequest
    init(url: URL?) {
        fakeRequest = URLRequest(url: url ?? URL(string: "about:blank")!)
        super.init()
    }
    override var request: URLRequest { fakeRequest }
}

@main
enum WebViewUIDelegateChecks {
    static var failures = 0

    static func check(_ condition: Bool, _ label: String) {
        if condition {
            print("ok   \(label)")
        } else {
            print("FAIL \(label)")
            failures += 1
        }
    }

    static func findWebView(in view: NSView) -> WKWebView? {
        if let webView = view as? WKWebView { return webView }
        for subview in view.subviews {
            if let found = findWebView(in: subview) { return found }
        }
        return nil
    }

    static func main() {
        _ = NSApplication.shared
        NSApplication.shared.setActivationPolicy(.prohibited)

        let coordinator = WebView.Coordinator()
        let selectors: [(Selector, String)] = [
            (
                #selector(WKUIDelegate.webView(_:runJavaScriptAlertPanelWithMessage:initiatedByFrame:completionHandler:)),
                "alert"
            ),
            (
                #selector(WKUIDelegate.webView(_:runJavaScriptConfirmPanelWithMessage:initiatedByFrame:completionHandler:)),
                "confirm"
            ),
            (
                #selector(WKUIDelegate.webView(_:runJavaScriptTextInputPanelWithPrompt:defaultText:initiatedByFrame:completionHandler:)),
                "prompt"
            ),
            (
                #selector(WKUIDelegate.webView(_:runOpenPanelWith:initiatedByFrame:completionHandler:)),
                "sélecteur de fichiers"
            ),
            (
                #selector(WKUIDelegate.webView(_:createWebViewWith:for:windowFeatures:)),
                "target=_blank"
            ),
        ]
        for (selector, label) in selectors {
            check(coordinator.responds(to: selector), "le coordinateur répond à \(label)")
        }

        // Le câblage réel : la vue SwiftUI, hébergée dans une fenêtre, doit
        // fabriquer une WKWebView dont les deux délégués sont son coordinateur.
        // (C'est `makeNSView` qui oubliait l'uiDelegate.)
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 300),
            styleMask: [.titled], backing: .buffered, defer: false
        )
        let host = NSHostingView(rootView: WebView(url: URL(string: "about:blank")!))
        host.frame = window.contentLayoutRect
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        let hosted = findWebView(in: host)
        check(hosted != nil, "la vue hébergée contient une WKWebView")
        check(hosted?.uiDelegate is WebView.Coordinator, "makeNSView pose l'uiDelegate")
        check(
            hosted?.navigationDelegate is WebView.Coordinator,
            "makeNSView pose le navigationDelegate"
        )
        if let hosted, let ui = hosted.uiDelegate, let nav = hosted.navigationDelegate {
            check(ui === nav, "un seul coordinateur pour les deux délégués")
        }

        // Un lien `target=_blank` ne s'ouvre au navigateur que pour http(s).
        let cases: [(String?, Bool)] = [
            ("https://example.com/licence", true),
            ("http://example.com/", true),
            ("HTTPS://Example.COM/Lic", true),
            ("file:///etc/passwd", false),
            ("fIlE:///etc/passwd", false),
            ("javascript:alert(1)", false),
            ("data:text/html,hi", false),
            ("blob:http://nas.local:8070/0b5c", false),
            ("fontsync://x", false),
            (nil, false),
        ]
        for (raw, expected) in cases {
            let url = raw.flatMap(URL.init(string:))
            let opened = WebView.Coordinator.externalURL(for: url) != nil
            check(opened == expected, "externalURL(\(raw ?? "nil")) → \(expected)")
        }

        // Et le délégué lui-même passe bien par ce filtre, sans jamais créer de
        // nouvelle WebView.
        let blank = WebView.Coordinator()
        var opened: [URL] = []
        blank.openExternally = { opened.append($0) }
        let probe = WKWebView(frame: .zero)
        for (raw, expected) in cases {
            opened.removeAll()
            let created = blank.webView(
                probe,
                createWebViewWith: WKWebViewConfiguration(),
                for: FakeNavigationAction(url: raw.flatMap(URL.init(string:))),
                windowFeatures: WKWindowFeatures()
            )
            check(created == nil, "target=_blank \(raw ?? "nil") : pas de nouvelle WebView")
            check(
                opened.map(\.absoluteString) == (expected ? [raw!] : []),
                "target=_blank \(raw ?? "nil") : ouvert au navigateur → \(expected)"
            )
        }

        // confirm : « OK » accepte, le reste refuse, et Échap vaut « Annuler »
        // (l'app n'est localisée qu'en anglais : AppKit ne le ferait pas seul).
        check(WebView.Coordinator.accepted(.alertFirstButtonReturn), "OK accepte")
        check(!WebView.Coordinator.accepted(.alertSecondButtonReturn), "Annuler refuse")
        check(!WebView.Coordinator.accepted(.abort), "une alerte interrompue refuse")
        let alert = WebView.Coordinator.confirmAlert(message: "Retirer ?")
        alert.layout()
        check(
            alert.buttons.map(\.title) == ["OK", "Annuler"],
            "confirm : boutons OK / Annuler"
        )
        check(
            alert.buttons.map(\.keyEquivalent) == ["\r", "\u{1b}"],
            "confirm : Entrée valide, Échap annule"
        )

        _ = window
        if failures > 0 {
            print("\(failures) échec(s)")
            exit(1)
        }
        print("toutes les vérifications passent")
    }
}
