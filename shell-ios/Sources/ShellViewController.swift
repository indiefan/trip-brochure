import UIKit
import WebKit

/// One full-screen web view over the local content. The page talks to the shell through
/// window.webkit.messageHandlers.shell.postMessage({...}):
///   {ready: true}            the page is up: the shell answers with its version and any news
///   {open: "https://…"}      open outside the app (Safari, Maps)
///   {copy: "text"}           put text on the clipboard
///   {reload: true}           show the newest content now
///   {checkUpdates: true}     look for new content now (the answer comes back as an event)
///   {statusBar: "light"|"dark"}
/// The shell talks back with window.dispatchEvent(new CustomEvent("shell", {detail: {...}})):
///   {version, content}       the shell's and the content's versions
///   {contentReady: "<v>"}    a newer itinerary is downloaded; {reload: true} shows it
///   {shellUpdate: {version, install}}   a newer app is waiting at that install page
///   {checked: "upToDate"|"updated"|"failed", detail}
final class ShellViewController: UIViewController, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
    private var webView: WKWebView!
    private var scheme: LocalScheme!
    private var pageReady = false
    private var pending: [[String: Any]] = []
    private var lastCheck = Date.distantPast
    private var lightStatusBar = true
    private let refresh = UIRefreshControl()

    override var preferredStatusBarStyle: UIStatusBarStyle { lightStatusBar ? .lightContent : .darkContent }

    override func loadView() {
        let config = WKWebViewConfiguration()
        scheme = LocalScheme(root: ContentStore.shared.activeRoot)
        config.setURLSchemeHandler(scheme, forURLScheme: LocalScheme.scheme)
        config.userContentController.add(WeakHandler(self), name: "shell")
        config.allowsInlineMediaPlayback = true
        config.dataDetectorTypes = [.phoneNumber, .address]
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.isOpaque = false
        webView.backgroundColor = ShellConfig.shared.backgroundColor
        webView.scrollView.backgroundColor = ShellConfig.shared.backgroundColor
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsLinkPreview = false
        if #available(iOS 16.4, *) { webView.isInspectable = true }
        refresh.addTarget(self, action: #selector(pulled), for: .valueChanged)
        refresh.tintColor = .white
        webView.scrollView.refreshControl = refresh
        view = webView
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        load()
        NotificationCenter.default.addObserver(self, selector: #selector(becameActive), name: UIApplication.didBecomeActiveNotification, object: nil)
    }

    private func load() {
        pageReady = false
        scheme.root = ContentStore.shared.activeRoot
        webView.load(URLRequest(url: URL(string: "\(LocalScheme.scheme)://local/index.html")!))
    }

    // --- updates ---------------------------------------------------------------------------------------------
    @objc private func becameActive() {
        if Date().timeIntervalSince(lastCheck) > 15 * 60 { check(reportBack: false) }
    }

    @objc private func pulled() { check(reportBack: true) }

    private func check(reportBack: Bool) {
        lastCheck = Date()
        ContentStore.shared.update { [weak self] outcome, shell in
            guard let self else { return }
            self.refresh.endRefreshing()
            switch outcome {
            case .updated(let v):
                if reportBack { self.load() } else { self.send(["contentReady": v]) }
            case .upToDate:
                if reportBack { self.send(["checked": "upToDate"]) }
            case .failed(let why):
                if reportBack { self.send(["checked": "failed", "detail": why]) }
            }
            if let shell, shell.version.compare(ShellConfig.shared.shellVersion, options: .numeric) == .orderedDescending {
                self.send(["shellUpdate": ["version": shell.version, "install": shell.install]])
            }
        }
    }

    private func send(_ detail: [String: Any]) {
        guard pageReady else { return pending.append(detail) }
        guard let data = try? JSONSerialization.data(withJSONObject: detail), let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('shell', {detail: \(json)}))")
    }

    // --- the page's messages ------------------------------------------------------------------------------------
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        if body["ready"] != nil {
            pageReady = true
            send(["version": ShellConfig.shared.shellVersion, "content": ContentStore.shared.activeVersion])
            let queued = pending; pending = []
            queued.forEach(send)
            if lastCheck == .distantPast { check(reportBack: false) }
        }
        if let s = body["open"] as? String, let url = URL(string: s) { UIApplication.shared.open(url) }
        if let s = body["copy"] as? String { UIPasteboard.general.string = s }
        if body["reload"] != nil { load() }
        if body["checkUpdates"] != nil { check(reportBack: true) }
        if let s = body["statusBar"] as? String {
            lightStatusBar = s == "light"
            UIView.animate(withDuration: 0.25) { self.setNeedsStatusBarAppearanceUpdate() }
        }
    }

    // --- links leave the app; the content stays inside -------------------------------------------------------------
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        if url.scheme == LocalScheme.scheme || url.scheme == "about" || url.scheme == "data" || url.scheme == "blob" {
            return decisionHandler(.allow)
        }
        if action.navigationType == .linkActivated || action.targetFrame?.isMainFrame == true {
            UIApplication.shared.open(url)
        }
        decisionHandler(.cancel)            // an email's own pictures and trackers never reach the network
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, url.scheme != LocalScheme.scheme { UIApplication.shared.open(url) }
        return nil
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { load() }
}

/// The content controller holds its handlers strongly; this keeps the view controller out of that cycle.
private final class WeakHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ t: WKScriptMessageHandler) { target = t }
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { target?.userContentController(c, didReceive: m) }
}
