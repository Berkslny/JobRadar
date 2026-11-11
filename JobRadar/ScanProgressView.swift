import SwiftUI

/// Progress bar of the running scan; after it ends, its result for a while.
/// Shown above the list in the main window and in the menu bar window (`compact`).
struct ScanProgressView: View {
    @Environment(AppModel.self) private var model
    var compact = false

    var body: some View {
        if model.cycleRunning {
            running(model.cycleProgress)
        } else if let result = model.cycleResult {
            finished(result)
        }
    }

    private func running(_ p: CycleProgress?) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .foregroundStyle(.tint)
                    .symbolEffect(.variableColor.iterative)
                Text(Self.title(p))
                    .font(compact ? Font.callout.weight(.semibold) : Font.headline)
                    .lineLimit(1)
                Spacer(minLength: 6)
                if let started = Dates.parse(p?.startedAt) {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        Text(Self.elapsed(from: started, to: context.date))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.tertiary)
                    }
                }
                if let percent = Self.percent(p) {
                    Text(percent)
                        .font(.callout.monospacedDigit().weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }
            if let fraction = Self.fraction(p) {
                ProgressView(value: fraction)
                    .progressViewStyle(.linear)
                    .animation(.easeInOut(duration: 0.6), value: fraction)
            } else {
                ProgressView()
                    .progressViewStyle(.linear)
            }
            Text(Self.detail(p))
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .help(Self.detail(p))
        }
        .modifier(ScanBarStyle(compact: compact))
        .accessibilityElement(children: .combine)
        .accessibilityLabel(t("Scan running"))
        .accessibilityValue(Self.percent(p) ?? "")
    }

    private func finished(_ result: CycleResult) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: result.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(result.ok ? Color.green : Color.orange)
            Text(result.text)
                .font(.callout)
                .lineLimit(3)
                .textSelection(.enabled)
            Spacer(minLength: 6)
            Button {
                model.cycleResult = nil
            } label: {
                Image(systemName: "xmark")
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .help(t("Close"))
        }
        .modifier(ScanBarStyle(compact: compact))
    }

    // MARK: Text

    /// Stages the engine writes while a scan runs (queued, done and failed are not among them).
    private static let activeStages: Set<String> = ["scan", "enrich", "evaluate", "mail", "notify"]

    private static func active(_ p: CycleProgress?) -> CycleProgress? {
        guard let p, let stage = p.stage, activeStages.contains(stage) else { return nil }
        return p
    }

    static func title(_ p: CycleProgress?) -> String {
        let quick = p?.quick == true
        if p?.stage == nil || p?.stage == "queued" {
            return quick ? t("Starting the quick scan") : t("Starting the scan")
        }
        guard let p = active(p), let label = p.label, !label.isEmpty else {
            return quick ? t("Quick scan running") : t("Scan running")
        }
        return quick ? t("Quick scan: %@", label) : t("Scan: %@", label)
    }

    static func detail(_ p: CycleProgress?) -> String {
        if p?.stage == nil || p?.stage == "queued" { return t("JobRadar is preparing the scan…") }
        if let d = active(p)?.detail, !d.isEmpty { return d }
        return t("Working…")
    }

    /// nil while the scan is being prepared (or its stage is unknown): the bar is indeterminate then.
    static func fraction(_ p: CycleProgress?) -> Double? {
        guard let f = active(p)?.fraction else { return nil }
        return min(max(f, 0), 1)
    }

    static func percent(_ p: CycleProgress?) -> String? {
        guard let f = fraction(p) else { return nil }
        let value = Int((f * 100).rounded())
        return L10n.isTurkish ? "%\(value)" : "\(value)%"
    }

    static func elapsed(from start: Date, to now: Date) -> String {
        let s = max(0, Int(now.timeIntervalSince(start)))
        if s < 60 { return t("%@ s", s) }
        if s < 3600 { return t("%@ min %@ s", s / 60, s % 60) }
        return t("%@ h %@ min", s / 3600, (s % 3600) / 60)
    }
}

/// A floating glass bar in the main window; plain in the menu bar window.
private struct ScanBarStyle: ViewModifier {
    let compact: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if compact {
            content
        } else {
            content
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .cardBackground(cornerRadius: 14)
        }
    }
}
