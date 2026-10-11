import CryptoKit
import Foundation

/// The web content: the copy built into the app, or a newer one fetched from the depot, file by file.
///
/// Layout under Application Support/WebShell: bundles/<version>/ (complete trees, each with its manifest.json) and
/// current.json naming the one in use. A new version is assembled in bundles/<version>.partial — files the phone
/// already has are copied from the bundle in use, the rest downloaded and checked against their SHA-256 — then
/// renamed into place, so a half-finished update is never shown. The built-in copy is used whenever it is newer.
final class ContentStore {
    struct Manifest: Codable {
        struct File: Codable { let sha256: String; let size: Int? }
        struct Shell: Codable { let version: String; let install: String }
        let version: String
        let entry: String?
        let files: [String: File]
        let shell: Shell?
    }

    static let shared = ContentStore()
    private let fm = FileManager.default
    private let root: URL
    private let builtIn: URL
    private let queue = DispatchQueue(label: "webshell.content")
    private var busy = false

    init() {
        root = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("WebShell", isDirectory: true)
        builtIn = Bundle.main.resourceURL!.appendingPathComponent("web", isDirectory: true)
        try? fm.createDirectory(at: root.appendingPathComponent("bundles"), withIntermediateDirectories: true)
        var url = root
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? url.setResourceValues(values)
    }

    private func manifest(at dir: URL) -> Manifest? {
        guard let data = try? Data(contentsOf: dir.appendingPathComponent("manifest.json")) else { return nil }
        return try? JSONDecoder().decode(Manifest.self, from: data)
    }

    private static func newer(_ a: String, than b: String) -> Bool { a.compare(b, options: .numeric) == .orderedDescending }

    /// The folder pages are served from right now.
    var activeRoot: URL {
        let builtInVersion = manifest(at: builtIn)?.version ?? "0"
        if let data = try? Data(contentsOf: root.appendingPathComponent("current.json")),
           let cur = try? JSONDecoder().decode([String: String].self, from: data), let v = cur["version"] {
            let dir = root.appendingPathComponent("bundles/\(v)", isDirectory: true)
            if manifest(at: dir) != nil && !Self.newer(builtInVersion, than: v) { return dir }
        }
        return builtIn
    }

    var activeVersion: String { manifest(at: activeRoot)?.version ?? "0" }

    enum Outcome { case upToDate, updated(String), failed(String) }

    /// Asks the depot for its newest manifest and brings that version in when it is newer. Calls back on the main queue
    /// with the outcome and the newest shell the depot offers (if any).
    func update(done: @escaping (Outcome, Manifest.Shell?) -> Void) {
        guard let base = ShellConfig.shared.depot, let url = URL(string: base + "/manifest.json") else {
            return done(.failed("updates are not set up"), nil)
        }
        queue.async {
            guard !self.busy else { return DispatchQueue.main.async { done(.upToDate, nil) } }
            self.busy = true
            defer { self.busy = false }
            let result: (Outcome, Manifest.Shell?)
            do {
                let data = try Self.fetch(url, timeout: 20)
                let m = try JSONDecoder().decode(Manifest.self, from: data)
                if Self.newer(m.version, than: self.activeVersion) {
                    try self.assemble(m, raw: data, base: base)
                    result = (.updated(m.version), m.shell)
                } else {
                    result = (.upToDate, m.shell)
                }
            } catch {
                result = (.failed(error.localizedDescription), nil)
            }
            DispatchQueue.main.async { done(result.0, result.1) }
        }
    }

    private func assemble(_ m: Manifest, raw: Data, base: String) throws {
        let from = activeRoot
        var have: [String: URL] = [:]                                   // sha256 → a file already on the phone
        if let cur = manifest(at: from) {
            for (name, f) in cur.files { have[f.sha256] = from.appendingPathComponent(name) }
        }
        let bundles = root.appendingPathComponent("bundles", isDirectory: true)
        let stage = bundles.appendingPathComponent("\(m.version).partial", isDirectory: true)
        try? fm.removeItem(at: stage)
        try fm.createDirectory(at: stage, withIntermediateDirectories: true)
        for (name, f) in m.files {
            guard !name.hasPrefix("/"), !name.split(separator: "/").contains("..") else { throw ShellError("bad file name \(name)") }
            let dest = stage.appendingPathComponent(name)
            try fm.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            if let src = have[f.sha256], fm.fileExists(atPath: src.path) {
                try fm.copyItem(at: src, to: dest)                       // a clone on APFS: no extra space
                continue
            }
            guard let url = URL(string: "\(base)/files/\(f.sha256)") else { throw ShellError("bad url") }
            let data = try Self.fetch(url, timeout: 120)
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard digest == f.sha256 else { throw ShellError("\(name) arrived damaged") }
            try data.write(to: dest, options: .atomic)
            have[f.sha256] = dest
        }
        try raw.write(to: stage.appendingPathComponent("manifest.json"), options: .atomic)
        let final = bundles.appendingPathComponent(m.version, isDirectory: true)
        try? fm.removeItem(at: final)
        try fm.moveItem(at: stage, to: final)
        try JSONEncoder().encode(["version": m.version]).write(to: root.appendingPathComponent("current.json"), options: .atomic)
        // keep the one in use and the one before it
        let keep: Set<String> = [m.version, from.lastPathComponent]
        for name in (try? fm.contentsOfDirectory(atPath: bundles.path)) ?? [] where !keep.contains(name) {
            try? fm.removeItem(at: bundles.appendingPathComponent(name))
        }
    }

    private static func fetch(_ url: URL, timeout: TimeInterval) throws -> Data {
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        req.setValue("WebShell/\(ShellConfig.shared.shellVersion)", forHTTPHeaderField: "User-Agent")
        let sem = DispatchSemaphore(value: 0)
        var out: Result<Data, Error> = .failure(ShellError("no answer"))
        URLSession.shared.dataTask(with: req) { data, resp, err in
            if let err = err { out = .failure(err) }
            else if let http = resp as? HTTPURLResponse, http.statusCode != 200 { out = .failure(ShellError("the server said \(http.statusCode)")) }
            else { out = .success(data ?? Data()) }
            sem.signal()
        }.resume()
        sem.wait()
        return try out.get()
    }
}

struct ShellError: LocalizedError {
    let message: String
    init(_ m: String) { message = m }
    var errorDescription: String? { message }
}
