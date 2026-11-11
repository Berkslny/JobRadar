import SwiftUI

// Form answers with copy buttons, document quality (second reading, PDF check),
// the before/after view of a tailored document, and replies for one job.

// MARK: Form answers

struct AnswersView: View {
    @Environment(AppModel.self) private var model
    let jobID: String
    @State private var data: AnswersResponse? = nil
    @State private var language = "de"
    @State private var loadError = ""

    /// Code of the main application language ("DE", "TR" …); its answers sit in the `de` field.
    private var primary: String { (data?.primary ?? "de").lowercased() }

    var body: some View {
        SectionBox(title: t("Form answers"), systemImage: "list.clipboard") {
            HStack {
                Text(t("Copy and paste while you fill in the application form."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if primary != "en" {
                    Picker(t("Language"), selection: $language) {
                        Text(primary.uppercased()).tag("de")
                        Text(verbatim: "EN").tag("en")
                    }
                    .pickerStyle(.segmented).accentFill()
                    .labelsHidden()
                    .frame(width: 96)
                }
            }
            if let data {
                ForEach(data.groups.filter { !$0.items.isEmpty }) { group in
                    Text(group.title).font(.subheadline.bold()).padding(.top, 4)
                    Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                        ForEach(group.items) { item in
                            GridRow(alignment: .firstTextBaseline) {
                                Text(item.label)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .frame(width: 180, alignment: .leading)
                                Text(item.text(language))
                                    .textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                CopyButton(text: item.text(language))
                            }
                        }
                    }
                }
                if !data.missing.isEmpty {
                    Text(t("Not filled in yet: %@. Add your answers under Profile > Form answers.",
                           data.missing.joined(separator: ", ")))
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            } else if !loadError.isEmpty {
                Text(loadError).font(.caption).foregroundStyle(.red)
            } else {
                ProgressView().controlSize(.small)
            }
        }
        .task(id: jobID) { await load() }
    }

    private func load() async {
        data = nil
        loadError = ""
        do {
            let res = try await model.api.answers(jobID: jobID)
            data = res
            language = res.language
        } catch {
            loadError = error.localizedDescription
        }
    }
}

// MARK: Document quality

struct DocumentQualityView: View {
    let validation: ValidationInfo?

    var body: some View {
        if let review = validation?.review, review.enabled == true {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "text.magnifyingglass").foregroundStyle(.secondary)
                Text(t("Second reading: %@", review.statusText)).font(.caption.bold())
                if let s = review.summary, !s.isEmpty {
                    Text(s).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
            }
            if let e = review.error, !e.isEmpty {
                Text(e).font(.caption).foregroundStyle(.orange)
            }
            if let issues = review.issues, !issues.isEmpty {
                DisclosureGroup(t("%@ notes from the second reading", issues.count)) {
                    BulletList(items: issues.map(issueText), color: .blue)
                }
                .font(.caption)
            }
        }
        if let pc = validation?.pdfCheck {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "doc.viewfinder").foregroundStyle(.secondary)
                Text(pdfSummary(pc)).font(.caption.bold())
                    .foregroundStyle(pc.ok == false ? Color.orange : Color.primary)
            }
            if let issues = pc.issues, !issues.isEmpty {
                BulletList(items: issues, color: .orange).font(.caption)
            }
            if let missing = pc.keywords?.missing, !missing.isEmpty {
                DisclosureGroup(t("%@ requirements your profile supports but the CV does not mention", missing.count)) {
                    BulletList(items: missing, color: .secondary)
                }
                .font(.caption)
            }
        }
    }

    private func issueText(_ i: ReviewIssue) -> String {
        var s = i.problem
        if let p = i.place, !p.isEmpty { s = "\(p): \(s)" }
        if let fix = i.suggestion, !fix.isEmpty { s += " → \(fix)" }
        return s
    }

    private func pdfSummary(_ pc: PDFCheck) -> String {
        var parts = [pc.ok == false ? t("PDF check: %@ warnings", pc.issues?.count ?? 0) : t("PDF check: clean")]
        if let p = pc.cv?.pages { parts.append(t("CV %@ pages", p)) }
        if let p = pc.letter?.pages { parts.append(t("letter %@ pages", p)) }
        if let k = pc.keywords {
            parts.append(t("%@ of %@ requirements appear in the CV", k.covered.count, k.covered.count + k.missing.count))
        }
        return parts.joined(separator: " · ")
    }
}

// MARK: Before / after

struct DiffTarget: Identifiable {
    let id: Int
}

struct DiffRow: View {
    let text: String
    let changed: Bool
    let sources: [DiffSource]

    init(item: DiffItem) {
        text = item.text
        changed = item.changed
        sources = item.sources
    }

    init(text: String, changed: Bool, sources: [DiffSource]) {
        self.text = text
        self.changed = changed
        self.sources = sources
    }

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(text.isEmpty ? "–" : text)
                if changed {
                    Chip(text: t("rewritten"), color: .blue)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            VStack(alignment: .leading, spacing: 4) {
                if sources.isEmpty {
                    Text(t("no source")).font(.caption).foregroundStyle(.orange)
                } else {
                    ForEach(Array(sources.enumerated()), id: \.offset) { _, s in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(s.id).font(.caption.monospaced().bold())
                            Text(s.text).font(.caption)
                        }
                        .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 4)
        Divider()
    }
}

struct DiffSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let docID: Int
    @State private var diff: DocumentDiff? = nil
    @State private var loadError = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(diff.map { t("Version %@: what was taken from your profile and how it was written", $0.version) }
                     ?? t("Changes"))
                    .font(.headline)
                Spacer()
                Button(t("Close")) { dismiss() }.keyboardShortcut(.cancelAction)
            }
            .padding(10)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let d = diff {
                        content(d)
                    } else if !loadError.isEmpty {
                        Text(loadError).foregroundStyle(.red)
                    } else {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                }
                .padding(16)
                .textSelection(.enabled)
            }
        }
        .frame(minWidth: 780, minHeight: 640)
        .task { await load() }
    }

    @ViewBuilder
    private func content(_ d: DocumentDiff) -> some View {
        Text(t("On the left the text in the document, on the right the profile facts it rests on. Where a line is marked \"rewritten\", check that the meaning stayed the same."))
            .font(.callout)
            .foregroundStyle(.secondary)
        SectionBox(title: t("Headline and summary"), systemImage: "person.text.rectangle") {
            DiffRow(text: d.headline.text, changed: d.headline.text != d.headline.original,
                    sources: [DiffSource(id: t("profile"), text: d.headline.original)])
            DiffRow(item: d.summary)
        }
        SectionBox(title: t("Experience"), systemImage: "briefcase") {
            ForEach(d.experience) { e in
                Text(e.organization.isEmpty ? e.title : "\(e.title) · \(e.organization)")
                    .font(.subheadline.bold())
                    .padding(.top, 4)
                ForEach(Array(e.bullets.enumerated()), id: \.offset) { _, b in
                    DiffRow(item: b)
                }
                if !e.leftOut.isEmpty {
                    DisclosureGroup(t("%@ facts of this entry were not used", e.leftOut.count)) {
                        BulletList(items: e.leftOut.map { "\($0.id): \($0.text)" }, color: .secondary)
                    }
                    .font(.caption)
                }
            }
            if !d.omittedEntries.isEmpty {
                Text(t("Entries left out of the CV: %@", d.omittedEntries.map(omittedText).joined(separator: ", ")))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        SectionBox(title: t("Skills"), systemImage: "wrench.and.screwdriver") {
            ChipGrid(items: d.skills.chosen.map { (text: $0, color: ThemeStore.shared.accentText) })
            if !d.skills.notChosen.isEmpty {
                Text(t("In your profile but not chosen for this CV")).font(.caption).foregroundStyle(.secondary)
                ChipGrid(items: d.skills.notChosen.map { (text: $0, color: Color.secondary) })
            }
        }
        SectionBox(title: d.letter.subject.isEmpty ? t("Cover letter") : t("Cover letter: %@", d.letter.subject),
                   systemImage: "envelope") {
            if d.letter.paragraphs.isEmpty {
                Text(t("There is no cover letter.")).foregroundStyle(.secondary)
            }
            ForEach(Array(d.letter.paragraphs.enumerated()), id: \.offset) { _, p in
                DiffRow(item: p)
            }
        }
        if !d.answers.isEmpty {
            SectionBox(title: t("Form answers"), systemImage: "list.clipboard") {
                ForEach(Array(d.answers.enumerated()), id: \.offset) { _, a in
                    if let q = a.question {
                        Text(q).font(.caption.bold())
                    }
                    DiffRow(item: a)
                }
            }
        }
    }

    private func omittedText(_ o: DiffOmitted) -> String {
        o.organization.isEmpty ? o.title : "\(o.title) (\(o.organization))"
    }

    private func load() async {
        do {
            diff = try await model.api.diff(docID: docID)
        } catch {
            loadError = error.localizedDescription
        }
    }
}

// MARK: Replies for one job

struct JobRepliesView: View {
    let signals: [MailSignal]

    var body: some View {
        if !signals.isEmpty {
            SectionBox(title: t("E-mail replies"), systemImage: "envelope.badge") {
                ForEach(signals) { signal in
                    MailSignalCard(signal: signal, showJob: false)
                }
            }
        }
    }
}
