import AppKit
import SwiftUI

struct ScoreBadge: View {
    let llmScore: Double?
    let prescore: Double

    var body: some View {
        if let s = llmScore {
            Text(String(format: "%.1f", s))
                .font(.system(.callout, design: .rounded).weight(.bold))
                .foregroundStyle(.white)
                .frame(minWidth: 36)
                .padding(.vertical, 4)
                .background(
                    LinearGradient(colors: [Palette.score(s), Palette.score(s).opacity(0.72)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing),
                    in: RoundedRectangle(cornerRadius: 8, style: .continuous)
                )
                .help(t("AI score (0 to 5)"))
        } else {
            Text("\(Int(prescore))")
                .font(.system(.caption, design: .rounded).weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(minWidth: 36)
                .padding(.vertical, 4)
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(Color.secondary.opacity(0.4)))
                .help(t("Quick score (0 to 100). Not evaluated by the AI model yet."))
        }
    }
}

struct Chip: View {
    let text: String
    var color: Color = .secondary
    var systemImage: String? = nil

    var body: some View {
        HStack(spacing: 3) {
            if let systemImage { Image(systemName: systemImage) }
            Text(text).lineLimit(1)
        }
        .font(.caption)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .foregroundStyle(color)
        .background(color.opacity(0.14), in: Capsule())
    }
}

/// Lays its subviews out in rows and wraps to the next row when one is full.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let limit = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var widest: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > limit {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width
            widest = max(widest, x)
            x += spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: widest, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

/// Chips that wrap onto several lines.
struct ChipGrid: View {
    let items: [(text: String, color: Color)]

    var body: some View {
        FlowLayout(spacing: 6) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                Chip(text: item.text, color: item.color)
            }
        }
    }
}

/// Offer to continue with the data of an earlier JobRadar (the command line version), and its result.
struct EarlierDataOffer: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if model.offersEarlierData || !model.earlierImportMessage.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                if model.offersEarlierData {
                    Label(t("Data from an earlier JobRadar was found in %@.", EarlierData.folder.path),
                          systemImage: "tray.and.arrow.down")
                        .font(.callout.weight(.semibold))
                    Text(t("Bring it over to continue where you left off: your profile, jobs, documents and settings are copied into JobRadar's own folder. The earlier folder is left as it is."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack {
                        Button(t("Bring my data over")) { Task { await model.importEarlierData() } }
                            .buttonStyle(.glassProminent).accentFill()
                            .disabled(model.earlierImportRunning || model.localState != .running)
                        if model.earlierImportRunning { ProgressView().controlSize(.small) }
                    }
                }
                if !model.earlierImportMessage.isEmpty {
                    Text(model.earlierImportMessage)
                        .font(.caption)
                        .foregroundStyle(model.earlierImportRunning ? Color.secondary
                                         : (model.earlierImportFailed ? Color.red : Color.green))
                }
            }
        }
    }
}

/// A titled content box on glass.
struct SectionBox<Content: View>: View {
    let title: String
    var systemImage: String? = nil
    var tint: Color? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 7) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .foregroundStyle(tint ?? ThemeStore.shared.accentText)
                }
                Text(title).font(.headline)
            }
            content
        }
        .card()
    }
}

struct BulletList: View {
    let items: [String]
    var color: Color = .primary

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("•").foregroundStyle(color)
                    Text(item).textSelection(.enabled)
                }
            }
        }
    }
}

/// A coloured note: something is missing, went wrong, or worked.
struct Banner: View {
    enum Kind {
        case info
        case warning
        case error
        case success
    }

    let kind: Kind
    let text: String

    private var color: Color {
        switch kind {
        case .info: return .blue
        case .warning: return .orange
        case .error: return .red
        case .success: return .green
        }
    }

    private var icon: String {
        switch kind {
        case .info: return "info.circle.fill"
        case .warning: return "exclamationmark.triangle.fill"
        case .error: return "xmark.octagon.fill"
        case .success: return "checkmark.circle.fill"
        }
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: icon).foregroundStyle(color)
            Text(text)
                .font(.callout)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(10)
        .background(color.opacity(0.13), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

/// Words or short phrases as removable chips, with a field to add more (Return, or commas for several).
struct TagEditor: View {
    var title: String = ""
    @Binding var tags: [String]
    var placeholder: String = ""
    var color: Color = .blue
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if !title.isEmpty {
                Text(title).font(.caption).foregroundStyle(.secondary)
            }
            FlowLayout(spacing: 6) {
                ForEach(Array(tags.enumerated()), id: \.offset) { index, tag in
                    HStack(spacing: 4) {
                        Text(tag).lineLimit(1)
                        Button {
                            if tags.indices.contains(index) { tags.remove(at: index) }
                        } label: {
                            Image(systemName: "xmark").font(.system(size: 8, weight: .bold))
                        }
                        .buttonStyle(.plain)
                        .help(t("Remove"))
                    }
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .foregroundStyle(color)
                    .background(color.opacity(0.14), in: Capsule())
                }
                TextField(placeholder.isEmpty ? t("Add…") : placeholder, text: $draft)
                    .textFieldStyle(.plain)
                    .font(.caption)
                    .frame(width: 170)
                    .padding(.vertical, 4)
                    .focused($focused)
                    .onSubmit(add)
            }
        }
        .onChange(of: focused) {
            if !focused { add() }
        }
    }

    private func add() {
        let parts = draft.split(whereSeparator: { $0 == "," || $0 == ";" || $0.isNewline })
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        for part in parts where !tags.contains(where: { $0.caseInsensitiveCompare(part) == .orderedSame }) {
            tags.append(part)
        }
        draft = ""
    }
}

@MainActor
enum Clipboard {
    static func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}

struct CopyButton: View {
    let text: String
    @State private var copied = false

    var body: some View {
        Button {
            Clipboard.copy(text)
            copied = true
            Task {
                try? await Task.sleep(for: .seconds(1.2))
                copied = false
            }
        } label: {
            Image(systemName: copied ? "checkmark" : "doc.on.doc")
                .foregroundStyle(copied ? AnyShapeStyle(Color.green) : AnyShapeStyle(.tint))
                .frame(width: 18)
        }
        .buttonStyle(.borderless)
        .help(copied ? t("Copied") : t("Copy"))
        .disabled(text.isEmpty)
    }
}

/// Name of a language for a two-letter code, in the interface language ("German", "Almanca").
func languageName(_ code: String) -> String {
    let clean = code.trimmingCharacters(in: .whitespaces).lowercased()
    guard !clean.isEmpty else { return "" }
    let name = L10n.locale.localizedString(forLanguageCode: clean) ?? clean.uppercased()
    return name.prefix(1).uppercased() + name.dropFirst()
}

/// Languages offered for documents and evaluation texts.
let commonLanguageCodes = ["en", "de", "tr", "fr", "es", "it", "nl", "pt", "pl", "sv", "da", "nb", "fi"]

/// Shows a save panel and copies `source` to the chosen place.
@MainActor
func saveWithPanel(_ source: URL, suggested name: String) {
    let panel = NSSavePanel()
    panel.nameFieldStringValue = name
    panel.canCreateDirectories = true
    guard panel.runModal() == .OK, let target = panel.url else { return }
    try? FileManager.default.removeItem(at: target)
    do {
        try FileManager.default.copyItem(at: source, to: target)
    } catch {
        NSAlert(error: error).runModal()
    }
}

/// A scrolling page of content boxes. The boxes share one glass container, which is how
/// Liquid Glass wants several glass shapes on screen to be drawn.
struct CardPage<Content: View>: View {
    var maxWidth: CGFloat = 900
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            GlassEffectContainer(spacing: 0) {
                VStack(alignment: .leading, spacing: 14) {
                    content
                }
                .padding(18)
                .frame(maxWidth: maxWidth, alignment: .leading)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
