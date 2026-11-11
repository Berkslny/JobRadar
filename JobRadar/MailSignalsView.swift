import SwiftUI

/// Replies from companies (rejections, interview invitations, tests, offers) matched to applications.
/// Nothing changes on its own: every proposal is applied or dismissed here.
struct MailSignalsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings

    private var pending: [MailSignal] { model.mailSignals.filter { $0.isPending } }
    private var recent: [MailSignal] { model.mailSignals.filter { !$0.isPending } }

    var body: some View {
        CardPage {
            SectionBox(title: t("Replies from companies"), systemImage: "envelope") {
                Text(t("Rejections, interview invitations, tests and offers in your inbox are matched to your applications. Nothing changes by itself: you apply every suggestion. The mailbox is opened read-only and no mail is marked as read."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                HStack {
                    Text(model.mailLastSync.isEmpty ? t("Not checked yet")
                                                    : t("Last checked %@", Dates.relative(model.mailLastSync)))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    if model.mailSyncRunning { ProgressView().controlSize(.small) }
                    Button {
                        Task { await model.syncMail() }
                    } label: {
                        Label(t("Check now"), systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.glass).plainGlass()
                    .disabled(model.mailSyncRunning)
                    Button(t("E-mail settings…")) { openSettings() }
                        .buttonStyle(.glass).plainGlass()
                }
                if !model.mailError.isEmpty {
                    Text(model.mailError).font(.caption).foregroundStyle(.red)
                }
            }
            if pending.isEmpty {
                ContentUnavailableView(t("No reply is waiting"), systemImage: "tray",
                                       description: Text(t("When a company answers, the reply shows up here with a suggestion.")))
            } else {
                Text(t("Waiting for you (%@)", pending.count)).font(.headline)
                ForEach(pending) { signal in
                    MailSignalCard(signal: signal, showJob: true)
                }
            }
            if !recent.isEmpty {
                SectionBox(title: t("Recently handled"), systemImage: "clock.arrow.circlepath") {
                    ForEach(recent.prefix(40)) { signal in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(Dates.short(signal.receivedAt))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                            Chip(text: signal.kindLabel, color: signal.color)
                            Text(signal.jobTitle.isEmpty ? signal.subject : "\(signal.jobTitle) · \(signal.jobCompany)")
                                .lineLimit(1)
                            Spacer(minLength: 4)
                            Text(signal.stateLabel).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle(t("E-mail replies"))
        .task {
            await model.loadMailSignals()
            await model.loadPickerJobs()
        }
        .toolbar {
            Button {
                Task { await model.loadMailSignals() }
            } label: {
                Label(t("Refresh"), systemImage: "arrow.clockwise")
            }
        }
    }
}

struct MailSignalCard: View {
    @Environment(AppModel.self) private var model
    let signal: MailSignal
    var showJob = true
    @State private var chosenJob = ""
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Chip(text: signal.kindLabel, color: signal.color, systemImage: "envelope")
                Text(Dates.short(signal.receivedAt)).font(.caption).foregroundStyle(.secondary)
                Text(signal.sender).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer(minLength: 0)
            }
            Text(signal.subject).font(.headline).textSelection(.enabled)
            if !signal.snippet.isEmpty {
                Text(signal.snippet)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
                    .textSelection(.enabled)
            }
            if showJob {
                jobLine
            }
            if signal.isPending {
                actions
            } else {
                Text(signal.stateLabel).font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(signal.color.opacity(0.09), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(signal.color.opacity(0.25))
        }
    }

    @ViewBuilder
    private var jobLine: some View {
        if let jobID = signal.jobId {
            HStack(spacing: 6) {
                Image(systemName: "briefcase").foregroundStyle(.secondary)
                Text("\(signal.jobTitle) · \(signal.jobCompany)").lineLimit(1)
                Button(t("Show job")) {
                    Task { await model.showFromReplies(jobID: jobID) }
                }
                .buttonStyle(.link)
            }
            .font(.callout)
        } else if signal.isPending {
            Picker(t("Job"), selection: $chosenJob) {
                Text(t("No match: choose the job…")).tag("")
                ForEach(signal.candidates, id: \.jobId) { c in
                    Text("\(c.title) · \(c.company)").tag(c.jobId)
                }
                ForEach(otherJobs) { j in
                    Text("\(j.title) · \(j.company)").tag(j.id)
                }
            }
            .frame(maxWidth: 460)
        }
    }

    private var applyTitle: String {
        if signal.jobId == nil { return t("Apply to the chosen job") }
        return signal.proposedLabel.isEmpty ? t("Add to the history") : t("Apply: %@", signal.proposedLabel)
    }

    private var otherJobs: [JobSummary] {
        let known = Set(signal.candidates.map { $0.jobId })
        return model.pickerJobs.filter { !known.contains($0.id) }
    }

    private var actions: some View {
        HStack(spacing: 8) {
            Button {
                let target: String? = signal.jobId == nil ? chosenJob : nil
                busy = true
                Task {
                    await model.applySignal(signal, jobID: target)
                    busy = false
                }
            } label: {
                Label(applyTitle, systemImage: "checkmark.circle")
            }
            .buttonStyle(.glassProminent).accentFill()
            .disabled(busy || (signal.jobId == nil && chosenJob.isEmpty))
            Button(t("Ignore")) {
                busy = true
                Task {
                    await model.dismissSignal(signal)
                    busy = false
                }
            }
            .buttonStyle(.glass).plainGlass()
            .disabled(busy)
            if busy { ProgressView().controlSize(.small) }
        }
    }
}
