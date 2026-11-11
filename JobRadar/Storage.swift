import Foundation
import Security

/// Secrets (API keys, the e-mail app password, a remote server's key) live in the macOS Keychain.
@MainActor
enum Keychain {
    static var service: String { Bundle.main.bundleIdentifier ?? "JobRadar" }

    static func get(_ account: String) -> String {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else { return "" }
        return value
    }

    @discardableResult
    static func set(_ value: String, for account: String) -> Bool {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        if value.isEmpty { return true }
        var add = base
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }
}

/// Names of the Keychain entries.
enum Secret {
    static let remoteToken = "apiToken"
    static let accessID = "cfAccessClientId"
    static let accessSecret = "cfAccessClientSecret"
    static let anthropicKey = "anthropicAPIKey"
    static let openAIKey = "openAIAPIKey"
    static let mailPassword = "mailPassword"
}

/// Small settings that are not secret.
enum Prefs {
    static let mailUser = "mailUser"
    static let mailTo = "mailTo"
    static let onboardingDone = "onboardingDone"
    static let autoScan = "autoScan"
    static let notifications = "notificationsEnabled"
    static let installJobBoards = "installJobBoards"
    static let earlierDataImported = "earlierDataImported"
}

@MainActor
enum ConfigStore {
    private static let urlKey = "serverURL"
    private static let modeKey = "serverMode"
    private static let folderKey = "workspaceFolder"

    static func load() -> ServerConfig {
        let defaults = UserDefaults.standard
        let url = defaults.string(forKey: urlKey) ?? ""
        let mode = defaults.string(forKey: modeKey).flatMap { ServerMode(rawValue: $0) } ?? .local
        // the remote key is only read when it is used, so a local setup never touches the Keychain for it
        let remote = mode == .remote
        return ServerConfig(
            mode: mode,
            localFolder: defaults.string(forKey: folderKey) ?? EnginePaths.defaultWorkspace.path,
            baseURL: url,
            token: remote ? Keychain.get(Secret.remoteToken) : "",
            accessClientID: remote ? Keychain.get(Secret.accessID) : "",
            accessClientSecret: remote ? Keychain.get(Secret.accessSecret) : ""
        )
    }

    static func save(_ c: ServerConfig) {
        let defaults = UserDefaults.standard
        defaults.set(c.mode.rawValue, forKey: modeKey)
        defaults.set(c.localFolder, forKey: folderKey)
        defaults.set(c.normalizedBaseURL, forKey: urlKey)
        guard c.mode == .remote else { return }
        Keychain.set(c.token.trimmingCharacters(in: .whitespacesAndNewlines), for: Secret.remoteToken)
        Keychain.set(c.accessClientID.trimmingCharacters(in: .whitespacesAndNewlines), for: Secret.accessID)
        Keychain.set(c.accessClientSecret.trimmingCharacters(in: .whitespacesAndNewlines), for: Secret.accessSecret)
    }
}

/// Daily copies of the database, kept apart from the workspace in case that folder is lost.
@MainActor
enum Backups {
    static var folder: URL {
        EnginePaths.support.appendingPathComponent("backups", isDirectory: true)
    }

    static func files() -> [URL] {
        let items = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        return items.filter { $0.lastPathComponent.hasPrefix("jobradar-") && $0.pathExtension == "db" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    static func prune(keep: Int = 14) {
        let all = files()
        guard all.count > keep else { return }
        for url in all.prefix(all.count - keep) {
            try? FileManager.default.removeItem(at: url)
        }
    }
}

/// Small date helpers for the engine's ISO timestamps ("2026-11-08T21:31:13+00:00" or "2026-11-05").
@MainActor
enum Dates {
    private static let full: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let day: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone.current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static func parse(_ s: String?) -> Date? {
        guard let s, !s.isEmpty else { return nil }
        if let d = full.date(from: s) ?? fractional.date(from: s) { return d }
        return day.date(from: String(s.prefix(10)))
    }

    /// "22 hours ago", "yesterday" in the interface language.
    static func relative(_ s: String?) -> String {
        guard let d = parse(s) else { return "" }
        return d.formatted(Date.RelativeFormatStyle(presentation: .named, locale: L10n.locale))
    }

    static func short(_ s: String?) -> String {
        guard let d = parse(s) else { return "" }
        let hasTime = (s?.count ?? 0) > 10
        return display(d, time: hasTime)
    }

    static func display(_ d: Date, time: Bool = true) -> String {
        let timeStyle: Date.FormatStyle.TimeStyle = time ? .shortened : .omitted
        return d.formatted(Date.FormatStyle(date: .abbreviated, time: timeStyle, locale: L10n.locale))
    }
}
