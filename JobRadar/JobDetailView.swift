import AppKit
import PDFKit
import SwiftUI

struct JobDetailView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @Environment(\.openSettings) private var openSettings
    let jobID: String

    var body: some View {
        Group {
            if let d = model.detail, d.id == jobID {
                CardPage {
                    header(d)
                    actions(d)
                    if let ev = d.extra.evaluation {
                        EvaluationView(record: ev, facts: d.extra.facts)
                    } else {
                        SectionBox(title: t("Evaluation"), systemImage: "sparkles") {
                            if model.summary?.llmReady == false {
                                Text(t("No AI model is connected yet, so jobs cannot be evaluated."))
                                    .foregroundStyle(.secondary)
                                Button(t("Connect an AI model…")) { openSettings() }
                                    .buttonStyle(.glass).plainGlass()
                            } else {
                                Text(t("This posting has not been evaluated yet. Start with \"Evaluate\"."))
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    DocumentsView(job: d)
                    AnswersView(jobID: d.id)
                    JobRepliesView(signals: d.extra.mailSignals ?? [])
                    NotesView(jobID: d.id, initial: d.extra.notes)
                    if !d.extra.contacts.isEmpty {
                        SectionBox(title: t("Your contacts at this company"), systemImage: "person.2") {
                            ForEach(d.extra.contacts, id: \.self) { c in
                                HStack {
                                    Text(c.name).bold()
                                    Text(c.position ?? "").foregroundStyle(.secondary)
                                    Spacer()
                                    if let s = c.url, let u = URL(string: s) {
                                        Link(t("Profile"), destination: u)
                                    }
                                }
                            }
                        }
                    }
                    DescriptionView(text: d.extra.description)
                    HistoryView(events: d.extra.events)
                }
                .textSelection(.enabled)
            } else {
                ProgressView(t("Loading…"))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: jobID) {
            if model.detail?.id != jobID { await model.loadDetail(jobID) }
        }
    }

    @ViewBuilder
    private func header(_ d: JobDetail) -> some View {
        let s = d.summary
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                ScoreBadge(llmScore: s.llmScore, prescore: s.prescore)
                    .scaleEffect(1.3, anchor: .topLeading)
                    .padding(.trailing, 10)
                    .padding(.bottom, 6)
                VStack(alignment: .leading, spacing: 4) {
                    Text(s.title).font(.title2.bold())
                    Text([s.company, s.location].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
            }
            ChipGrid(items: headerChips(d))
        }
        .card(tint: s.llmScore.map { Palette.score($0) })
    }

    private func headerChips(_ d: JobDetail) -> [(text: String, color: Color)] {
        let s = d.summary
        var chips: [(text: String, color: Color)] = [(s.statusLabel, Palette.status(s.status))]
        if let v = s.verdict, !v.isEmpty { chips.append((Palette.verdict(v), Palette.score(s.llmScore))) }
        if let name = d.extra.trackName { chips.append((name, .teal)) }
        if !s.salaryText.isEmpty { chips.append((s.salaryText, .green)) }
        if !s.remoteLabel.isEmpty { chips.append((s.remoteLabel, .blue)) }
        if !s.employmentLabel.isEmpty { chips.append((s.employmentLabel, .blue)) }
        for b in s.badges { chips.append((b.label, Palette.badge(b.kind))) }
        if s.liveStatus == "closed" { chips.append((t("The posting may be closed"), .red)) }
        if let f = d.extra.filteredReason, !f.isEmpty { chips.append((t("Filtered out: %@", f), .red)) }
        chips.append((t("Quick score %@", Int(s.prescore)), .secondary))
        if let semantic = d.extra.match?.semantic {
            chips.append((t("Semantic score %@", Int((semantic * 100).rounded())), .secondary))
        }
        if let label = d.extra.label, label != "skip" {
            chips.append((t("Your verdict: %@", Verdict.title(label)), Verdict.color(label)))
        }
        if !s.sources.isEmpty { chips.append((s.sources.joined(separator: ", "), .secondary)) }
        if let p = s.postedAt, !p.isEmpty { chips.append((t("Posted %@", Dates.short(p)), .secondary)) }
        // the same word can come from two places (remote work and a note of the posting): show it once
        var seen = Set<String>()
        return chips.filter { seen.insert($0.text).inserted }
    }

    @ViewBuilder
    private func actions(_ d: JobDetail) -> some View {
        let running = model.runningTasks[d.id]
        FlowLayout(spacing: 8) {
            Menu {
                StatusMenuItems(jobID: d.id)
            } label: {
                Label(d.summary.statusLabel, systemImage: "flag")
            }
            .fixedSize()
            if model.summary?.features?.contains("labels") == true {
                Menu {
                    Button(Verdict.title("good")) { Task { await model.setLabel(d.id, "good") } }
                    Button(Verdict.title("maybe")) { Task { await model.setLabel(d.id, "maybe") } }
                    Button(Verdict.title("bad")) { Task { await model.setLabel(d.id, "bad") } }
                    if d.extra.label != nil {
                        Divider()
                        Button(t("Take my verdict back")) { Task { await model.setLabel(d.id, "") } }
                    }
                } label: {
                    Label(t("My verdict"), systemImage: "hand.thumbsup")
                }
                .fixedSize()
                .help(t("Say whether this job fits you. JobRadar measures its rankings and rules against your verdicts."))
            }
            Button {
                Task { await model.evaluate(d.id) }
            } label: {
                Label(d.extra.evaluation == nil ? t("Evaluate") : t("Evaluate again"), systemImage: "sparkles")
            }
            .disabled(running != nil)
            Menu {
                Button(t("Automatic language")) { Task { await model.tailor(d.id, language: "") } }
                Divider()
                ForEach(commonLanguageCodes, id: \.self) { code in
                    Button(languageName(code)) { Task { await model.tailor(d.id, language: code) } }
                }
            } label: {
                Label(t("Write CV and cover letter"), systemImage: "doc.badge.plus")
            }
            .fixedSize()
            .disabled(running != nil)
            if let u = d.summary.postingURL {
                Button {
                    openURL(u)
                } label: {
                    Label(t("Open posting"), systemImage: "safari")
                }
            }
            if model.config.mode == .remote, let u = model.api.panelURL(jobID: d.id) {
                Button {
                    openURL(u)
                } label: {
                    Label(t("Open in the web panel"), systemImage: "globe")
                }
            }
        }
        .buttonStyle(.glass).plainGlass()
        if let running {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(running.kind == "tailor"
                     ? t("Writing your CV and cover letter. This can take a few minutes.")
                     : t("Evaluating the posting. This takes a minute or two."))
                    .foregroundStyle(.secondary)
            }
            .font(.callout)
        }
    }
}

struct EvaluationView: View {
    let record: EvaluationRecord
    let facts: [String: String]

    var body: some View {
        let r = record.result
        SectionBox(title: t("Evaluation"), systemImage: "sparkles") {
            HStack(spacing: 10) {
                Text(String(format: "%.1f / 5", record.score))
                    .font(.title3.bold())
                    .foregroundStyle(Palette.score(record.score))
                Text(Palette.verdict(record.verdict))
                    .font(.headline)
                Spacer()
                Text("\(record.provider) · \(record.model) · \(Dates.relative(record.createdAt))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if !r.summary.isEmpty {
                Text(r.summary)
            }
            if let dim = r.dimensions {
                DimensionsView(dimensions: dim)
            }
        }
        if !r.requirements.isEmpty {
            SectionBox(title: t("Requirements and evidence"), systemImage: "checklist") {
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                    ForEach(Array(r.requirements.enumerated()), id: \.offset) { _, req in
                        let m = Palette.match(req.match)
                        GridRow(alignment: .top) {
                            Image(systemName: m.symbol).foregroundStyle(m.color)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(req.requirement)
                                if !req.note.isEmpty {
                                    Text(req.note).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            Text(req.importance == "must" ? t("must") : t("plus"))
                                .font(.caption)
                                .foregroundStyle(req.importance == "must" ? Color.primary : Color.secondary)
                            HStack(spacing: 4) {
                                ForEach(req.evidence, id: \.self) { fid in
                                    Text(fid)
                                        .font(.caption.monospaced())
                                        .padding(.horizontal, 5)
                                        .padding(.vertical, 1)
                                        .background(Color.secondary.opacity(0.15), in: RoundedRectangle(cornerRadius: 4))
                                        .help(facts[fid] ?? t("Evidence in your profile"))
                                }
                            }
                        }
                    }
                }
                Text(t("Hover over an evidence code to see the matching line of your profile."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        if !r.strengths.isEmpty || !r.gaps.isEmpty {
            HStack(alignment: .top, spacing: 14) {
                if !r.strengths.isEmpty {
                    SectionBox(title: t("Strengths"), systemImage: "hand.thumbsup", tint: .green) {
                        BulletList(items: r.strengths, color: .green)
                    }
                }
                if !r.gaps.isEmpty {
                    SectionBox(title: t("Gaps"), systemImage: "puzzlepiece", tint: .orange) {
                        BulletList(items: r.gaps, color: .orange)
                    }
                }
            }
        }
        if !r.redFlags.isEmpty {
            SectionBox(title: t("Risks"), systemImage: "exclamationmark.triangle", tint: .red) {
                BulletList(items: r.redFlags, color: .red)
            }
        }
        if !r.tailoringHints.isEmpty || !r.interviewTopics.isEmpty || !r.legitimacyNotes.isEmpty {
            SectionBox(title: t("Application notes"), systemImage: "lightbulb", tint: .yellow) {
                if !r.legitimacyNotes.isEmpty {
                    Text(t("How genuine the posting looks: %@. %@", r.legitimacy, r.legitimacyNotes))
                        .foregroundStyle(.secondary)
                }
                if !r.tailoringHints.isEmpty {
                    DisclosureGroup(t("Tips for the CV")) { BulletList(items: r.tailoringHints) }
                }
                if !r.interviewTopics.isEmpty {
                    DisclosureGroup(t("Interview topics")) { BulletList(items: r.interviewTopics) }
                }
            }
        }
        if !record.notes.isEmpty {
            Text(record.notes.joined(separator: " · "))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

struct DimensionRow {
    let name: String
    let value: Double
}

struct DimensionsView: View {
    let dimensions: Dimensions

    private var rows: [DimensionRow] {
        let all: [(String, Double?)] = [
            (t("CV match"), dimensions.cvMatch),
            (t("Fit with your goal"), dimensions.northStar),
            (t("Pay"), dimensions.comp),
            (t("Culture"), dimensions.culture),
            (t("Risk (high = low risk)"), dimensions.redFlags),
        ]
        return all.compactMap { item in item.1.map { DimensionRow(name: item.0, value: $0) } }
    }

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 4) {
            ForEach(rows, id: \.name) { row in
                GridRow {
                    Text(row.name).font(.caption).foregroundStyle(.secondary)
                    ProgressView(value: min(max(row.value, 0), 5), total: 5)
                        .tint(Palette.score(row.value))
                        .frame(width: 160)
                    Text(String(format: "%.1f", row.value)).font(.caption.monospacedDigit())
                }
            }
        }
    }
}

struct DescriptionView: View {
    let text: String
    @State private var expanded = false

    var body: some View {
        SectionBox(title: t("Posting text"), systemImage: "doc.plaintext") {
            if text.isEmpty {
                Text(t("The posting has no text.")).foregroundStyle(.secondary)
            } else {
                Text(text)
                    .lineLimit(expanded ? nil : 14)
                Button(expanded ? t("Show less") : t("Show all")) { expanded.toggle() }
                    .buttonStyle(.link)
            }
        }
    }
}

struct HistoryView: View {
    let events: [JobEvent]

    var body: some View {
        if !events.isEmpty {
            SectionBox(title: t("History"), systemImage: "clock.arrow.circlepath") {
                DisclosureGroup(t("%@ entries", events.count)) {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(events) { e in
                            HStack(alignment: .firstTextBaseline) {
                                Text(Dates.short(e.ts)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                                Text(e.kind).font(.caption.bold())
                                Text(e.detail ?? "").font(.caption)
                            }
                        }
                    }
                }
            }
        }
    }
}

struct NotesView: View {
    @Environment(AppModel.self) private var model
    let jobID: String
    let initial: String
    @State private var text = ""
    @State private var saved = true

    var body: some View {
        SectionBox(title: t("Notes"), systemImage: "note.text") {
            TextEditor(text: $text)
                .font(.body)
                .frame(minHeight: 70)
                .scrollContentBackground(.hidden)
                .padding(4)
                .background(Color(nsColor: .textBackgroundColor).opacity(0.55), in: RoundedRectangle(cornerRadius: 8))
                .onChange(of: text) { saved = (text == initial) }
            HStack {
                Spacer()
                Button(t("Save")) {
                    Task {
                        await model.saveNotes(jobID, text)
                        saved = true
                    }
                }
                .disabled(saved)
            }
        }
        .onAppear { text = initial }
        .onChange(of: jobID) { text = initial }
    }
}

struct DocumentsView: View {
    @Environment(AppModel.self) private var model
    let job: JobDetail
    @State private var preview: PreviewFile?
    @State private var busyFile: String?
    @State private var diffTarget: DiffTarget?

    var body: some View {
        if !job.extra.documents.isEmpty {
            SectionBox(title: t("Documents"), systemImage: "doc.on.doc") {
                ForEach(job.extra.documents) { doc in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(alignment: .top) {
                            FlowLayout(spacing: 6) {
                                Text(t("Version %@", doc.version)).bold().padding(.vertical, 2)
                                Text((doc.language ?? "").uppercased()).foregroundStyle(.secondary).padding(.vertical, 2)
                                Text(Dates.relative(doc.createdAt)).foregroundStyle(.secondary).padding(.vertical, 2)
                                if doc.validation?.ok == false {
                                    Chip(text: t("Check the notes"), color: .orange, systemImage: "exclamationmark.triangle")
                                } else {
                                    Chip(text: t("Verified"), color: .green, systemImage: "checkmark.seal")
                                }
                                if doc.isApproved {
                                    Chip(text: t("Approved"), color: .purple, systemImage: "hand.thumbsup")
                                }
                            }
                            Spacer(minLength: 8)
                            if !doc.isApproved {
                                Button(t("Approve")) { Task { await model.approve(docID: doc.id, jobID: job.id) } }
                            }
                        }
                        FlowLayout(spacing: 6) {
                            ForEach(doc.files.filter { $0.hasSuffix(".pdf") || $0.hasSuffix(".md") || $0.hasSuffix(".html") },
                                    id: \.self) { name in
                                Button {
                                    Task { await open(doc: doc, name: name) }
                                } label: {
                                    Label(name, systemImage: name.hasSuffix(".pdf") ? "doc.richtext" : "doc.text")
                                }
                                .disabled(busyFile != nil)
                            }
                            Button {
                                diffTarget = DiffTarget(id: doc.id)
                            } label: {
                                Label(t("See what changed"), systemImage: "arrow.left.arrow.right")
                            }
                            .help(t("The profile fact behind every bullet and paragraph"))
                            if busyFile != nil { ProgressView().controlSize(.small) }
                        }
                        DocumentQualityView(validation: doc.validation)
                        if let violations = doc.validation?.violations, !violations.isEmpty {
                            DisclosureGroup(t("%@ verification notes", violations.count)) {
                                BulletList(items: violations.map(violationText), color: .orange)
                            }
                            .font(.caption)
                        }
                    }
                    Divider()
                }
            }
            .sheet(item: $preview) { file in
                PDFPreviewSheet(file: file)
            }
            .background {
                Color.clear.sheet(item: $diffTarget) { target in
                    DiffSheet(docID: target.id)
                }
            }
        }
    }

    private func violationText(_ v: Violation) -> String {
        let prefix = [v.severity, v.place].compactMap { $0 }.joined(separator: " · ")
        return prefix.isEmpty ? v.message : "\(prefix): \(v.message)"
    }

    private func open(doc: DocumentInfo, name: String) async {
        busyFile = name
        defer { busyFile = nil }
        do {
            let url = try await model.api.downloadFile(docID: doc.id, name: name)
            if name.hasSuffix(".pdf") {
                preview = PreviewFile(url: url, name: name)
            } else {
                saveWithPanel(url, suggested: name)
            }
        } catch {
            model.errorMessage = error.localizedDescription
        }
    }
}

struct PreviewFile: Identifiable {
    let url: URL
    let name: String
    var id: String { url.path }
}

struct PDFPreviewSheet: View {
    @Environment(\.dismiss) private var dismiss
    let file: PreviewFile

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(file.name).font(.headline)
                Spacer()
                Button(t("Open in Preview")) { NSWorkspace.shared.open(file.url) }
                Button(t("Save…")) { saveWithPanel(file.url, suggested: file.name) }
                Button(t("Close")) { dismiss() }.keyboardShortcut(.cancelAction)
            }
            .padding(10)
            Divider()
            PDFKitView(url: file.url)
        }
        .frame(minWidth: 680, minHeight: 820)
    }
}

struct PDFKitView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.document = PDFDocument(url: url)
        return view
    }

    func updateNSView(_ view: PDFView, context: Context) {
        if view.document?.documentURL != url {
            view.document = PDFDocument(url: url)
        }
    }
}
