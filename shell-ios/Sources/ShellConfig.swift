import UIKit

/// What this build of the shell is: written into the app bundle as shell.json by scripts/build.sh.
struct ShellConfig: Decodable {
    let app: String            // the depot's name for the app ("trip")
    let title: String
    let depot: String?         // public base for updates: https://…/inbox/<secret>/apps/<app>; nil = never updates
    let background: String     // hex, shown before the page paints (and behind the status bar)

    static let shared: ShellConfig = {
        guard let url = Bundle.main.url(forResource: "shell", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let cfg = try? JSONDecoder().decode(ShellConfig.self, from: data) else {
            return ShellConfig(app: "app", title: "App", depot: nil, background: "#ffffff")
        }
        return cfg
    }()

    var shellVersion: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0" }

    var backgroundColor: UIColor {
        var hex = background.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        if hex.count == 3 { hex = hex.map { "\($0)\($0)" }.joined() }
        let v = UInt64(hex, radix: 16) ?? 0xffffff
        return UIColor(red: CGFloat((v >> 16) & 0xff) / 255, green: CGFloat((v >> 8) & 0xff) / 255, blue: CGFloat(v & 0xff) / 255, alpha: 1)
    }
}
