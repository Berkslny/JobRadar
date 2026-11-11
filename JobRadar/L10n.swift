import Foundation
import Observation

/// Interface language. The English text is the key; Turkish comes from `L10n.turkish`.
enum AppLanguage: String, CaseIterable, Identifiable {
    case system
    case en
    case tr

    var id: String { rawValue }

    /// "en" or "tr" for this choice on this Mac.
    var code: String {
        switch self {
        case .en: return "en"
        case .tr: return "tr"
        case .system:
            let preferred = Locale.preferredLanguages.first?.lowercased() ?? "en"
            return preferred.hasPrefix("tr") ? "tr" : "en"
        }
    }
}

/// The current language, readable from any thread (error texts are built off the main actor too).
nonisolated enum L10n {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var current = "en"

    static var code: String {
        get {
            lock.lock()
            defer { lock.unlock() }
            return current
        }
        set {
            lock.lock()
            current = newValue == "tr" ? "tr" : "en"
            lock.unlock()
        }
    }

    static var isTurkish: Bool { code == "tr" }

    /// Locale for dates and numbers in the interface language.
    static var locale: Locale {
        if isTurkish { return Locale(identifier: "tr_TR") }
        let system = Locale.current
        return system.language.languageCode?.identifier == "en" ? system : Locale(identifier: "en_US")
    }

    /// Replaces `%@` (in order) and `%1$@`, `%2$@` … (by position) with the arguments.
    static func fill(_ template: String, _ args: [String]) -> String {
        var out = ""
        var next = 0
        var i = template.startIndex
        while i < template.endIndex {
            let ch = template[i]
            if ch == "%" {
                let rest = template[template.index(after: i)...]
                if rest.hasPrefix("@") {
                    if next < args.count { out += args[next] }
                    next += 1
                    i = template.index(i, offsetBy: 2)
                    continue
                }
                if let digit = rest.first, let n = digit.wholeNumberValue, n >= 1,
                   rest.dropFirst().hasPrefix("$@") {
                    if n <= args.count { out += args[n - 1] }
                    i = template.index(i, offsetBy: 4)
                    continue
                }
            }
            out.append(ch)
            i = template.index(after: i)
        }
        return out
    }
}

/// Text in the interface language: `t("Scan now")`, `t("%@ jobs", count)`.
nonisolated func t(_ key: String, _ args: CustomStringConvertible...) -> String {
    let template = L10n.isTurkish ? (L10n.turkish[key] ?? key) : key
    return args.isEmpty ? template : L10n.fill(template, args.map { $0.description })
}

/// The language choice of the user. Views below a `.id(LanguageStore.shared.code)` are rebuilt
/// when it changes, so every `t()` call is evaluated again.
@MainActor
@Observable
final class LanguageStore {
    static let shared = LanguageStore()
    private static let key = "appLanguage"

    var choice: AppLanguage {
        didSet {
            UserDefaults.standard.set(choice.rawValue, forKey: Self.key)
            // the menus and dialogs macOS itself supplies (Edit, Window, file panels) follow from the next start
            if choice == .system {
                UserDefaults.standard.removeObject(forKey: "AppleLanguages")
            } else {
                UserDefaults.standard.set([choice.code], forKey: "AppleLanguages")
            }
            apply()
            onChange?()
        }
    }
    /// "en" or "tr".
    private(set) var code: String = "en"
    /// Called after the user chose another language (the app tells the engine).
    @ObservationIgnored var onChange: (() -> Void)? = nil

    private init() {
        let stored = UserDefaults.standard.string(forKey: Self.key).flatMap { AppLanguage(rawValue: $0) }
        choice = stored ?? .system
        apply()
    }

    private func apply() {
        code = choice.code
        L10n.code = code
    }

    func title(_ language: AppLanguage) -> String {
        switch language {
        case .system: return t("System language")
        case .en: return "English"
        case .tr: return "Türkçe"
        }
    }
}
