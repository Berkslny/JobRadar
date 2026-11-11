import AppKit
import Observation
import SwiftUI

/// Light, dark, or whatever the Mac uses.
enum AppearanceChoice: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var title: String {
        switch self {
        case .system: return t("Match the system")
        case .light: return t("Light")
        case .dark: return t("Dark")
        }
    }

    var icon: String {
        switch self {
        case .system: return "circle.lefthalf.filled"
        case .light: return "sun.max"
        case .dark: return "moon"
        }
    }
}

/// How the boxes that hold content are drawn.
enum CardStyle: String, CaseIterable, Identifiable {
    case glass
    case frosted

    var id: String { rawValue }

    var title: String {
        switch self {
        case .glass: return t("Liquid Glass")
        case .frosted: return t("Frosted")
        }
    }
}

/// Accent colour plus the three colours of the window background.
struct ThemePalette: Identifiable, Equatable {
    let id: String
    let name: String
    let accent: Color
    let glow: [Color]

    static let all: [ThemePalette] = [
        ThemePalette(id: "aurora", name: "Aurora",
                     accent: Color(red: 0.42, green: 0.38, blue: 0.96),
                     glow: [Color(red: 0.56, green: 0.36, blue: 0.98), Color(red: 0.10, green: 0.76, blue: 0.80),
                            Color(red: 0.98, green: 0.38, blue: 0.62)]),
        ThemePalette(id: "sunset", name: "Sunset",
                     accent: Color(red: 0.95, green: 0.42, blue: 0.24),
                     glow: [Color(red: 1.00, green: 0.60, blue: 0.20), Color(red: 0.98, green: 0.30, blue: 0.52),
                            Color(red: 0.58, green: 0.32, blue: 0.92)]),
        ThemePalette(id: "ocean", name: "Ocean",
                     accent: Color(red: 0.10, green: 0.52, blue: 0.96),
                     glow: [Color(red: 0.16, green: 0.48, blue: 1.00), Color(red: 0.10, green: 0.80, blue: 0.90),
                            Color(red: 0.30, green: 0.88, blue: 0.68)]),
        ThemePalette(id: "forest", name: "Forest",
                     accent: Color(red: 0.14, green: 0.64, blue: 0.42),
                     glow: [Color(red: 0.20, green: 0.72, blue: 0.40), Color(red: 0.10, green: 0.62, blue: 0.62),
                            Color(red: 0.93, green: 0.82, blue: 0.30)]),
        ThemePalette(id: "graphite", name: "Graphite",
                     accent: Color(red: 0.40, green: 0.46, blue: 0.56),
                     glow: [Color(red: 0.56, green: 0.60, blue: 0.68), Color(red: 0.44, green: 0.50, blue: 0.62),
                            Color(red: 0.66, green: 0.66, blue: 0.72)]),
    ]

    var title: String {
        switch id {
        case "aurora": return t("Aurora")
        case "sunset": return t("Sunset")
        case "ocean": return t("Ocean")
        case "forest": return t("Forest")
        default: return t("Graphite")
        }
    }
}

/// Appearance settings; every window reads them.
@MainActor
@Observable
final class ThemeStore {
    static let shared = ThemeStore()

    var appearance: AppearanceChoice {
        didSet {
            UserDefaults.standard.set(appearance.rawValue, forKey: "appearance")
            applyAppearance()
        }
    }
    var paletteID: String {
        didSet { UserDefaults.standard.set(paletteID, forKey: "palette") }
    }
    var cardStyle: CardStyle {
        didSet { UserDefaults.standard.set(cardStyle.rawValue, forKey: "cardStyle") }
    }
    /// The desktop shines through the window background.
    var seeThrough: Bool {
        didSet { UserDefaults.standard.set(seeThrough, forKey: "seeThroughWindow") }
    }

    private init() {
        let d = UserDefaults.standard
        appearance = d.string(forKey: "appearance").flatMap { AppearanceChoice(rawValue: $0) } ?? .system
        paletteID = d.string(forKey: "palette") ?? "aurora"
        cardStyle = d.string(forKey: "cardStyle").flatMap { CardStyle(rawValue: $0) } ?? .glass
        seeThrough = d.object(forKey: "seeThroughWindow") as? Bool ?? true
    }

    var palette: ThemePalette {
        ThemePalette.all.first { $0.id == paletteID } ?? ThemePalette.all[0]
    }

    /// The solid accent: fills under a white label (primary buttons, the chosen segment, step numbers).
    var accent: Color { palette.accent }

    /// The accent for text, symbols and thin controls: lighter in dark mode and a little deeper in light
    /// mode, so links and menus stay readable on glass.
    var accentText: Color { Color(nsColor: AccentShade.text(for: NSColor(palette.accent))) }

    /// Light or dark for every window, sheet and menu of the app; `system` follows the Mac.
    func applyAppearance() {
        switch appearance {
        case .system: NSApplication.shared.appearance = nil
        case .light: NSApplication.shared.appearance = NSAppearance(named: .aqua)
        case .dark: NSApplication.shared.appearance = NSAppearance(named: .darkAqua)
        }
    }
}

/// Builds the colour that follows light and dark mode. Kept off the main actor: AppKit may ask for the
/// colour from any thread.
nonisolated enum AccentShade {
    static func text(for base: NSColor) -> NSColor {
        NSColor(name: nil) { appearance in
            let dark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return base.blended(withFraction: dark ? 0.42 : 0.12, of: dark ? NSColor.white : NSColor.black) ?? base
        }
    }
}

/// A blurred view of whatever is behind the window (the desktop, other windows).
struct BehindWindowBlur: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .sidebar
        view.blendingMode = .behindWindow
        view.state = .followsWindowActiveState
        return view
    }

    func updateNSView(_ view: NSVisualEffectView, context: Context) {}
}

/// Window background: soft colour clouds of the chosen palette over a see-through backdrop.
struct AuroraBackground: View {
    @Environment(\.colorScheme) private var scheme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        let theme = ThemeStore.shared
        let glow = theme.palette.glow
        let strength = scheme == .dark ? 0.46 : 0.36
        ZStack {
            if theme.seeThrough && !reduceTransparency {
                BehindWindowBlur()
            } else {
                Color(nsColor: .windowBackgroundColor)
            }
            EllipticalGradient(colors: [glow[0].opacity(strength), glow[0].opacity(0)],
                               center: UnitPoint(x: 0.05, y: 0.02), startRadiusFraction: 0, endRadiusFraction: 0.75)
            EllipticalGradient(colors: [glow[1].opacity(strength), glow[1].opacity(0)],
                               center: UnitPoint(x: 0.98, y: 0.22), startRadiusFraction: 0, endRadiusFraction: 0.70)
            EllipticalGradient(colors: [glow[2].opacity(strength * 0.9), glow[2].opacity(0)],
                               center: UnitPoint(x: 0.55, y: 1.08), startRadiusFraction: 0, endRadiusFraction: 0.80)
        }
        .ignoresSafeArea()
    }
}

private struct ThemedWindow: ViewModifier {
    func body(content: Content) -> some View {
        content
            .tint(ThemeStore.shared.accentText)
            .containerBackground(for: .window) { AuroraBackground() }
    }
}

private struct CardBackground: ViewModifier {
    var cornerRadius: CGFloat
    var tint: Color?

    func body(content: Content) -> some View {
        if ThemeStore.shared.cardStyle == .glass {
            content.glassEffect(tint.map { Glass.regular.tint($0.opacity(0.28)) } ?? Glass.regular,
                                in: .rect(cornerRadius: cornerRadius))
        } else {
            content
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .strokeBorder((tint ?? Color.primary).opacity(tint == nil ? 0.08 : 0.35))
                }
        }
    }
}

extension View {
    /// The app's window look: palette tint and the aurora background.
    func themedWindow() -> some View {
        modifier(ThemedWindow())
    }

    /// The solid accent under a white label: primary buttons and the chosen segment.
    func accentFill() -> some View {
        tint(ThemeStore.shared.accent)
    }

    /// Plain glass without the accent colour: secondary buttons.
    func plainGlass() -> some View {
        tint(Color?.none)
    }

    /// Background of a content box: Liquid Glass, or a frosted panel when the user prefers that.
    func cardBackground(cornerRadius: CGFloat = 16, tint: Color? = nil) -> some View {
        modifier(CardBackground(cornerRadius: cornerRadius, tint: tint))
    }

    /// A padded content box.
    func card(padding: CGFloat = 14, cornerRadius: CGFloat = 16, tint: Color? = nil) -> some View {
        self.padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .cardBackground(cornerRadius: cornerRadius, tint: tint)
    }
}

/// Colours with a meaning (scores, states), the same in every palette.
enum Palette {
    static func score(_ value: Double?) -> Color {
        guard let value else { return .secondary }
        if value >= 4.0 { return .green }
        if value >= 3.0 { return .orange }
        return .red
    }

    static func badge(_ kind: String) -> Color {
        switch kind {
        case "ok": return .green
        case "warn": return .orange
        case "bad", "err", "error", "danger": return .red
        default: return .blue
        }
    }

    static func match(_ match: String) -> (symbol: String, color: Color) {
        switch match {
        case "strong": return ("checkmark.circle.fill", .green)
        case "partial": return ("circle.lefthalf.filled", .orange)
        default: return ("xmark.circle.fill", .red)
        }
    }

    static func verdict(_ v: String?) -> String {
        switch v {
        case "apply": return t("Apply")
        case "maybe": return t("Maybe")
        case "skip": return t("Skip")
        default: return ""
        }
    }

    static func status(_ status: String) -> Color {
        switch status {
        case "new": return .blue
        case "shortlisted": return .indigo
        case "tailored": return .teal
        case "approved": return .mint
        case "applied": return .purple
        case "interview": return .orange
        case "offer": return .green
        case "rejected": return .red
        default: return .gray
        }
    }
}
