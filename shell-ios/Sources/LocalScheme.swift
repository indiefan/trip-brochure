import UniformTypeIdentifiers
import WebKit

/// Serves app://local/<path> from the content folder in use, so the pages have a real origin (fetch, iframes and
/// storage behave) and need no network at all.
final class LocalScheme: NSObject, WKURLSchemeHandler {
    static let scheme = "app"
    var root: URL

    init(root: URL) { self.root = root }

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { return task.didFailWithError(ShellError("no url")) }
        var path = url.path.removingPercentEncoding ?? url.path
        if path.isEmpty || path == "/" { path = "/index.html" }
        let file = root.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        guard file.path.hasPrefix(root.standardizedFileURL.path), let data = try? Data(contentsOf: file) else {
            let resp = HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "text/plain"])!
            task.didReceive(resp)
            task.didReceive(Data("not found".utf8))
            return task.didFinish()
        }
        let mime = UTType(filenameExtension: file.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
        let type = mime.hasPrefix("text/") || mime.contains("javascript") || mime.contains("json") ? "\(mime); charset=utf-8" : mime
        let resp = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                   headerFields: ["Content-Type": type, "Content-Length": "\(data.count)", "Cache-Control": "no-cache"])!
        task.didReceive(resp)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}
