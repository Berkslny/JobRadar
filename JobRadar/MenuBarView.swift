import AppKit
import SwiftUI

struct MenuBarView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(verbatim: "JobRadar").font(.headline)
                Spacer()
                if let s = model.summary, !model.cycleRunning, !s.lastCycle.isEmpty {
                    Text(t("Last scan %@", Dates.relative(s.lastCycle)))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            if model.cycleRunning || model.cycleResult != nil {
                ScanProgressView(compact: true)
            }
            if !model.config.isComplete {
                Text(t("No server is set up. Open the app and go to Settings."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else if model.config.mode == .local && model.localState != .running {
                Text(model.localStatusText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            } else if let s = model.summary {
                HStack(spacing: 14) {
                    stat("\(s.views["inbox"] ?? 0)", t("inbox"), .blue)
                    stat("\(s.strongOpen)", t("strong"), .orange)
                    stat("\(s.pendingEvaluation)", t("waiting"), .gray)
                    stat("\(s.counts["applied"] ?? 0)", t("applied"), .purple)
                }
            }
            if model.pendingReplies > 0 {
                Button {
                    openReplies()
                } label: {
                    Label(t("%@ company replies to review", model.pendingReplies), systemImage: "envelope.badge")
                        .foregroundStyle(.red)
                }
                .buttonStyle(.plain)
            }
            if !model.newStrongJobs.isEmpty {
                Divider()
                Text(t("Strong matches")).font(.subheadline.bold())
                ForEach(model.newStrongJobs.prefix(6)) { job in
                    Button {
                        open(job.id)
                    } label: {
                        HStack(spacing: 8) {
                            ScoreBadge(llmScore: job.llmScore, prescore: job.prescore)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(job.title).lineLimit(1)
                                Text(job.company).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            Divider()
            HStack {
                Button(t("Open JobRadar")) { open(nil) }
                Button(t("Scan now")) { Task { await model.runCycle() } }
                    .disabled(!model.connectionReady || model.cycleRunning || model.summary?.running == true)
                Spacer()
                Button {
                    Task { await model.backgroundTick() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help(t("Refresh"))
                Button {
                    NSApplication.shared.terminate(nil)
                } label: {
                    Image(systemName: "power")
                }
                .help(t("Quit"))
            }
        }
        .padding(14)
        .frame(width: 360)
    }

    private func stat(_ value: String, _ label: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(value).font(.title3.bold().monospacedDigit()).foregroundStyle(color)
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }

    private func openReplies() {
        openWindow(id: "main")
        NSApplication.shared.activate()
        model.sidebar = .replies
    }

    private func open(_ jobID: String?) {
        openWindow(id: "main")
        NSApplication.shared.activate()
        if let jobID {
            Task { await model.show(jobID: jobID) }
        }
    }
}
