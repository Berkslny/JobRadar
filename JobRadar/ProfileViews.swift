import AppKit
import Observation
import SwiftUI
import UniformTypeIdentifiers

/// The profile being edited. It lives outside the views, so unsaved changes survive a visit to another page.
@MainActor
@Observable
final class ProfileEditor {
    var draft = ProfileData()
    var saved = ProfileData()
    var exists = false
    var missing: [String] = []
    var loaded = false
    var loading = false
    var saving = false
    var importing = false
    var note = ""
    var error = ""

    var dirty: Bool { loaded && draft != saved }

    /// Loads the saved profile. Unsaved edits are kept unless `force` is set.
    func load(_ model: AppModel, force: Bool = false) async {
        guard model.connectionReady, !loading else { return }
        if loaded && !force { return }
        loading = true
        defer { loading = false }
        do {
            apply(try await model.api.profile())
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func apply(_ envelope: ProfileEnvelope) {
        saved = envelope.profile
        draft = envelope.profile
        exists = envelope.exists
        missing = envelope.missing
        loaded = true
    }

    func save(_ model: AppModel) async -> Bool {
        guard !saving else { return false }
        saving = true
        defer { saving = false }
        do {
            apply(try await model.api.saveProfile(draft))
            error = ""
            note = t("Saved.")
            await model.loadSetup()
            await model.refreshSummary()
            return true
        } catch {
            self.error = error.localizedDescription
            note = ""
            return false
        }
    }

    /// Lets the AI model read a CV file and puts the result into the draft. Nothing is saved yet.
    func importCV(_ file: URL, model: AppModel) async -> Bool {
        guard !importing else { return false }
        importing = true
        defer { importing = false }
        error = ""
        note = ""
        do {
            let task = try await model.wait(try await model.api.importCV(file: file))
            guard task.status != "error", let profile = task.result?.profile else {
                error = task.message.isEmpty ? t("The CV could not be read.") : task.message
                return false
            }
            draft = profile
            loaded = true
            note = t("Filled in from your CV. Check the details, then save.")
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func revert() {
        draft = saved
        note = ""
        error = ""
    }

    /// Words for what `missing` lists.
    static func explain(_ key: String) -> String {
        switch key {
        case "name": return t("your name")
        case "entries": return t("at least one job, degree or project")
        case "facts": return t("a few lines about what you did")
        case "skills": return t("your skills")
        default: return key
        }
    }
}

/// A binding to the row with this identity. It stays valid when rows are removed or reordered
/// while a text field still holds it.
@MainActor
func rowBinding<Row: LocallyIdentified>(_ list: Binding<[Row]>, _ id: UUID, fallback: Row) -> Binding<Row> {
    Binding(
        get: { list.wrappedValue.first { $0.localID == id } ?? fallback },
        set: { value in
            if let index = list.wrappedValue.firstIndex(where: { $0.localID == id }) {
                list.wrappedValue[index] = value
            }
        }
    )
}

// MARK: Side column

struct ProfileSideView: View {
    @Environment(AppModel.self) private var model
    @Environment(ProfileEditor.self) private var editor
    @State private var showAnswers = false

    var body: some View {
        CardPage(maxWidth: 560) {
            statusCard
            CVImportBox()
            SectionBox(title: t("Form answers"), systemImage: "list.clipboard") {
                Text(t("Notice period, relocation, salary: answer the standard questions of application forms once, then copy them for every job."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Button(t("Edit form answers…")) { showAnswers = true }
                    .buttonStyle(.glass).plainGlass()
            }
            SectionBox(title: t("Why this matters"), systemImage: "checkmark.shield", tint: .green) {
                Text(t("Every line of your profile is a fact with its own code. Evaluations point to these facts, and tailored CVs and letters may only use them, so nothing about you is ever made up."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle(t("Profile"))
        .task { await editor.load(model) }
        .sheet(isPresented: $showAnswers) { FormAnswersSheet() }
        .toolbar {
            ToolbarItem {
                Button {
                    Task { _ = await editor.save(model) }
                } label: {
                    Label(t("Save profile"), systemImage: "checkmark.circle")
                }
                .buttonStyle(.glassProminent).accentFill()
                .keyboardShortcut("s", modifiers: .command)
                .disabled(!editor.dirty || editor.saving)
                .help(t("Save the profile (⌘S)"))
            }
        }
    }

    private var statusCard: some View {
        SectionBox(title: t("Your profile"), systemImage: "person.text.rectangle") {
            if !editor.loaded {
                ProgressView().controlSize(.small)
            } else if editor.exists && editor.missing.isEmpty {
                Label(t("Your profile is ready."), systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            } else {
                Text(t("Still missing: %@.", editor.missing.map { ProfileEditor.explain($0) }.joined(separator: ", ")))
                    .foregroundStyle(.orange)
            }
            Text(t("%@ facts · %@ skills", editor.draft.factCount, editor.draft.skillCount))
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(t("Edit the page on the right like a CV: click any text to change it."))
                .font(.callout)
                .foregroundStyle(.secondary)
            HStack(spacing: 8) {
                Button(t("Save profile")) { Task { _ = await editor.save(model) } }
                    .buttonStyle(.glassProminent).accentFill()
                    .disabled(!editor.dirty || editor.saving)
                Button(t("Undo changes")) { editor.revert() }
                    .buttonStyle(.glass).plainGlass()
                    .disabled(!editor.dirty || editor.saving)
                if editor.saving { ProgressView().controlSize(.small) }
            }
            if editor.dirty {
                Text(t("You have unsaved changes.")).font(.caption).foregroundStyle(.orange)
            }
            if !editor.note.isEmpty { Banner(kind: .success, text: editor.note) }
            if !editor.error.isEmpty { Banner(kind: .error, text: editor.error) }
        }
    }
}

/// Drop a CV (PDF, Word, text) and the AI model turns it into the profile draft.
struct CVImportBox: View {
    @Environment(AppModel.self) private var model
    @Environment(ProfileEditor.self) private var editor
    @Environment(\.openSettings) private var openSettings
    @State private var targeted = false
    @State private var pending: URL? = nil
    @State private var confirmReplace = false

    private var aiReady: Bool {
        model.setup?.ai.ready ?? (model.summary?.llmReady ?? false)
    }

    var body: some View {
        SectionBox(title: t("Start from your CV"), systemImage: "doc.text.viewfinder") {
            Text(t("Drop your CV here (PDF, Word or text). The AI model reads it and fills in the profile. You check the result before anything is saved."))
                .font(.callout)
                .foregroundStyle(.secondary)
            dropZone
            if editor.importing {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(t("Reading your CV. This takes about a minute…")).font(.callout)
                }
            }
            if !aiReady {
                Banner(kind: .warning, text: t("Connect an AI model first. It is needed to read the CV."))
                Button(t("Connect an AI model…")) { openSettings() }
                    .buttonStyle(.glass).plainGlass()
            }
        }
        .confirmationDialog(t("Replace the current profile with the CV?"), isPresented: $confirmReplace) {
            Button(t("Replace"), role: .destructive) {
                if let file = pending { start(file) }
            }
            Button(t("Cancel"), role: .cancel) { pending = nil }
        } message: {
            Text(t("Your work permit, availability and preferences are kept. Nothing is saved until you press Save."))
        }
    }

    private var dropZone: some View {
        let accent = ThemeStore.shared.accent
        return RoundedRectangle(cornerRadius: 12, style: .continuous)
            .strokeBorder(targeted ? accent : Color.secondary.opacity(0.45),
                          style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
            .background(targeted ? accent.opacity(0.10) : Color.clear,
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .frame(height: 96)
            .overlay {
                VStack(spacing: 6) {
                    Image(systemName: "arrow.down.doc").font(.title2).foregroundStyle(.secondary)
                    Button(t("Choose a file…")) { choose() }
                        .buttonStyle(.glass).plainGlass()
                        .disabled(editor.importing || !aiReady)
                }
            }
            .dropDestination(for: URL.self) { urls, _ in
                guard let file = urls.first, aiReady, !editor.importing else { return false }
                offer(file)
                return true
            } isTargeted: { inside in
                targeted = inside
            }
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        var types: [UTType] = [.pdf, .plainText]
        for ext in ["docx", "md", "rtf"] {
            if let type = UTType(filenameExtension: ext) { types.append(type) }
        }
        panel.allowedContentTypes = types
        panel.message = t("Choose your CV (PDF, Word or text)")
        panel.prompt = t("Read")
        if panel.runModal() == .OK, let file = panel.url {
            offer(file)
        }
    }

    /// Asks before an existing profile is replaced.
    private func offer(_ file: URL) {
        let hasContent = !editor.draft.name.isEmpty || editor.draft.factCount > 0
        if hasContent {
            pending = file
            confirmReplace = true
        } else {
            start(file)
        }
    }

    private func start(_ file: URL) {
        pending = nil
        Task { _ = await editor.importCV(file, model: model) }
    }
}

// MARK: The CV page

/// The profile laid out like a CV; every text on it can be edited in place.
struct ProfilePaperView: View {
    @Environment(AppModel.self) private var model
    @Environment(ProfileEditor.self) private var editor

    var body: some View {
        ScrollView {
            ProfilePaper()
                .padding(22)
                .frame(maxWidth: .infinity)
        }
        .overlay {
            if !editor.loaded {
                ProgressView()
            }
        }
        .task { await editor.load(model) }
    }
}

/// The sheet of paper itself, without scrolling (the first-run assistant shows it inside its own page).
struct ProfilePaper: View {
    @Environment(ProfileEditor.self) private var editor

    var body: some View {
        @Bindable var editor = editor
        VStack(alignment: .leading, spacing: 26) {
            PaperHeader(profile: $editor.draft)
            PaperSection(title: t("Summary")) {
                FactList(facts: $editor.draft.summaryFacts,
                         placeholder: t("Who you are professionally, in a line or two"))
            }
            EntriesSection(title: t("Experience"), kind: "work", entries: $editor.draft.experience)
            EntriesSection(title: t("Education"), kind: "education", entries: $editor.draft.education)
            EntriesSection(title: t("Projects"), kind: "project", entries: $editor.draft.projects)
            SkillsSection(groups: $editor.draft.skillGroups)
            LanguagesSection(languages: $editor.draft.languages)
            PermitSection(profile: $editor.draft)
            PreferencesSection(preferences: $editor.draft.preferences)
        }
        .padding(38)
        .frame(maxWidth: 820, alignment: .leading)
        .background(PaperBackground())
    }
}

/// A sheet of paper: nearly opaque so text stays easy to read, with a little of the window showing through.
struct PaperBackground: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(Color(nsColor: .textBackgroundColor).opacity(0.84))
            .shadow(color: Color.black.opacity(0.18), radius: 14, y: 6)
    }
}

/// A CV section: small coloured heading, a rule, and an optional add button.
struct PaperSection<Content: View>: View {
    let title: String
    var addTitle: String = ""
    var onAdd: (() -> Void)? = nil
    @ViewBuilder var content: Content

    var body: some View {
        let accent = ThemeStore.shared.accentText
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Text(title.uppercased(with: L10n.locale))
                    .font(.caption.weight(.bold))
                    .kerning(1.3)
                    .foregroundStyle(accent)
                Rectangle()
                    .fill(accent.opacity(0.35))
                    .frame(height: 1)
                if let onAdd {
                    Button(action: onAdd) {
                        Label(addTitle, systemImage: "plus")
                    }
                    .buttonStyle(.borderless)
                    .font(.caption)
                }
            }
            content
        }
    }
}

/// A caption on the left, a field on the right.
struct PaperRow<Content: View>: View {
    let label: String
    @ViewBuilder var content: Content

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(label)
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(width: 150, alignment: .leading)
            content
        }
    }
}

struct PaperHeader: View {
    @Binding var profile: ProfileData

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            TextField(t("Your name"), text: $profile.name)
                .textFieldStyle(.plain)
                .font(.system(size: 30, weight: .bold))
            TextField(t("Headline, for example: Embedded Software Engineer"), text: $profile.headline)
                .textFieldStyle(.plain)
                .font(.title3)
                .foregroundStyle(.secondary)
            FlowLayout(spacing: 14) {
                contact("envelope", t("E-mail"), $profile.email, 230)
                contact("phone", t("Phone"), $profile.phone, 150)
                contact("mappin.and.ellipse", t("City"), $profile.city, 150)
                contact("house", t("Address (optional)"), $profile.address, 250)
            }
            LinksEditor(links: $profile.linkList)
        }
    }

    private func contact(_ icon: String, _ placeholder: String, _ text: Binding<String>, _ width: CGFloat) -> some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField(placeholder, text: text)
                .textFieldStyle(.plain)
                .font(.callout)
                .frame(width: width)
        }
    }
}

struct LinksEditor: View {
    @Binding var links: [ProfileLink]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(links) { link in
                LinkRow(link: rowBinding($links, link.localID, fallback: ProfileLink())) {
                    links.removeAll { $0.localID == link.localID }
                }
            }
            Button {
                links.append(ProfileLink())
            } label: {
                Label(t("Add a link (LinkedIn, GitHub, portfolio)"), systemImage: "plus")
            }
            .buttonStyle(.borderless)
            .font(.caption)
        }
    }
}

struct LinkRow: View {
    @Binding var link: ProfileLink
    var onDelete: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "link")
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField(t("Name"), text: $link.name)
                .textFieldStyle(.plain)
                .font(.callout)
                .frame(width: 110)
            TextField("https://…", text: $link.url)
                .textFieldStyle(.plain)
                .font(.callout)
                .frame(maxWidth: 380)
            Button(action: onDelete) {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help(t("Remove"))
        }
    }
}

/// Bullet lines; each one is a fact evaluations and tailored documents can cite.
struct FactList: View {
    @Binding var facts: [ProfileFact]
    var placeholder: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(facts, id: \.localID) { fact in
                FactRow(fact: rowBinding($facts, fact.localID, fallback: ProfileFact()), placeholder: placeholder) {
                    facts.removeAll { $0.localID == fact.localID }
                }
            }
            Button {
                facts.append(ProfileFact())
            } label: {
                Label(t("Add a line"), systemImage: "plus")
            }
            .buttonStyle(.borderless)
            .font(.caption)
        }
    }
}

struct FactRow: View {
    @Binding var fact: ProfileFact
    var placeholder: String
    var onDelete: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Text(verbatim: "•").foregroundStyle(.secondary)
            TextField(placeholder, text: $fact.text, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...6)
            if !fact.id.isEmpty {
                Text(fact.id)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.tertiary)
                    .help(t("The code evaluations use to point at this line"))
            }
            Button(action: onDelete) {
                Image(systemName: "xmark.circle")
            }
            .buttonStyle(.borderless)
            .opacity(hovering ? 1 : 0.25)
            .help(t("Remove this line"))
        }
        .onHover { inside in hovering = inside }
    }
}

enum EntryKind {
    static let work = ["work", "internship", "werkstudent", "thesis", "volunteer"]

    static func title(_ kind: String) -> String {
        switch kind {
        case "internship": return t("Internship")
        case "werkstudent": return t("Working student")
        case "thesis": return t("Thesis")
        case "volunteer": return t("Volunteering")
        default: return t("Employment")
        }
    }
}

struct EntriesSection: View {
    let title: String
    /// work, education or project
    let kind: String
    @Binding var entries: [ProfileEntry]

    private var addTitle: String {
        switch kind {
        case "education": return t("Add a degree")
        case "project": return t("Add a project")
        default: return t("Add a job")
        }
    }

    var body: some View {
        PaperSection(title: title, addTitle: addTitle, onAdd: { entries.append(ProfileEntry(kind: kind)) }) {
            if entries.isEmpty {
                Text(t("Nothing here yet.")).font(.callout).foregroundStyle(.tertiary)
            }
            ForEach(entries, id: \.localID) { entry in
                EntryEditor(entry: rowBinding($entries, entry.localID, fallback: ProfileEntry(kind: kind)),
                            section: kind,
                            onMove: { offset in move(entry.localID, by: offset) },
                            onDelete: { entries.removeAll { $0.localID == entry.localID } })
            }
        }
    }

    private func move(_ id: UUID, by offset: Int) {
        guard let index = entries.firstIndex(where: { $0.localID == id }) else { return }
        let target = index + offset
        guard entries.indices.contains(target) else { return }
        entries.swapAt(index, target)
    }
}

struct EntryEditor: View {
    @Binding var entry: ProfileEntry
    let section: String
    var onMove: (Int) -> Void
    var onDelete: () -> Void

    private var titlePlaceholder: String {
        switch section {
        case "education": return t("Degree or programme")
        case "project": return t("Project name")
        default: return t("Job title")
        }
    }

    private var organizationPlaceholder: String {
        switch section {
        case "education": return t("School or university")
        case "project": return t("For whom or where (optional)")
        default: return t("Company")
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                TextField(titlePlaceholder, text: $entry.title)
                    .textFieldStyle(.plain)
                    .font(.headline)
                TextField(t("Start"), text: $entry.start)
                    .textFieldStyle(.plain)
                    .font(.callout)
                    .multilineTextAlignment(.trailing)
                    .frame(width: 78)
                Text(verbatim: "–").foregroundStyle(.secondary)
                TextField(t("End"), text: $entry.end)
                    .textFieldStyle(.plain)
                    .font(.callout)
                    .frame(width: 78)
                entryMenu
            }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                TextField(organizationPlaceholder, text: $entry.organization)
                    .textFieldStyle(.plain)
                    .foregroundStyle(.secondary)
                TextField(t("Place"), text: $entry.location)
                    .textFieldStyle(.plain)
                    .foregroundStyle(.secondary)
                    .frame(width: 190)
                if section == "work" && entry.kind != "work" {
                    Chip(text: EntryKind.title(entry.kind), color: .teal)
                }
            }
            FactList(facts: $entry.facts, placeholder: t("What you did or achieved, one fact per line"))
                .padding(.leading, 4)
        }
        .padding(.vertical, 4)
    }

    private var entryMenu: some View {
        Menu {
            if section == "work" {
                Picker(t("Kind"), selection: $entry.kind) {
                    ForEach(EntryKind.work, id: \.self) { kind in
                        Text(EntryKind.title(kind)).tag(kind)
                    }
                }
            }
            Button(t("Move up")) { onMove(-1) }
            Button(t("Move down")) { onMove(1) }
            Divider()
            Button(t("Delete this entry"), role: .destructive) { onDelete() }
        } label: {
            Image(systemName: "ellipsis.circle")
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
    }
}

struct SkillsSection: View {
    @Binding var groups: [SkillGroup]

    var body: some View {
        PaperSection(title: t("Skills"), addTitle: t("Add a group"), onAdd: { groups.append(SkillGroup()) }) {
            if groups.isEmpty {
                Text(t("Group your skills, for example: Programming, Tools, Methods."))
                    .font(.callout)
                    .foregroundStyle(.tertiary)
            }
            ForEach(groups) { group in
                SkillGroupRow(group: rowBinding($groups, group.localID, fallback: SkillGroup())) {
                    groups.removeAll { $0.localID == group.localID }
                }
            }
        }
    }
}

struct SkillGroupRow: View {
    @Binding var group: SkillGroup
    var onDelete: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            TextField(t("Group"), text: $group.name)
                .textFieldStyle(.plain)
                .font(.callout.weight(.semibold))
                .frame(width: 160)
            TagEditor(tags: $group.items, placeholder: t("Add a skill…"), color: ThemeStore.shared.accentText)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(action: onDelete) {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help(t("Remove this group"))
        }
    }
}

struct LanguagesSection: View {
    @Binding var languages: [ProfileLanguage]
    static let levels = ["A1", "A2", "B1", "B2", "C1", "C2", "Native"]

    var body: some View {
        PaperSection(title: t("Languages"), addTitle: t("Add a language"),
                     onAdd: { languages.append(ProfileLanguage(level: "B2")) }) {
            ForEach(languages) { language in
                LanguageRow(language: rowBinding($languages, language.localID, fallback: ProfileLanguage())) {
                    languages.removeAll { $0.localID == language.localID }
                }
            }
        }
    }
}

struct LanguageRow: View {
    @Binding var language: ProfileLanguage
    var onDelete: () -> Void

    /// The standard levels, plus whatever the profile already says.
    private var options: [String] {
        let base = LanguagesSection.levels
        return base.contains(language.level) ? base : [language.level] + base
    }

    var body: some View {
        HStack(spacing: 10) {
            TextField(t("Language"), text: $language.name)
                .textFieldStyle(.plain)
                .frame(width: 180)
            Picker(t("Level"), selection: $language.level) {
                ForEach(options, id: \.self) { level in
                    Text(level == "Native" ? t("Native") : (level.isEmpty ? "–" : level)).tag(level)
                }
            }
            .labelsHidden()
            .frame(width: 120)
            Button(action: onDelete) {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help(t("Remove"))
            Spacer(minLength: 0)
        }
    }
}

struct PermitSection: View {
    @Binding var profile: ProfileData

    var body: some View {
        PaperSection(title: t("Right to work and availability")) {
            PaperRow(label: t("Citizenship")) {
                TagEditor(tags: $profile.citizenships, placeholder: t("Country code, e.g. DE"), color: .teal)
            }
            PaperRow(label: t("Work permit")) {
                TextField(t("For example: EU citizen, Blue Card, needs sponsorship"), text: $profile.workPermit)
                    .textFieldStyle(.plain)
            }
            PaperRow(label: t("Earliest start")) {
                TextField(t("For example: immediately, 3 months' notice"), text: $profile.earliestStart)
                    .textFieldStyle(.plain)
            }
        }
    }
}

struct PreferencesSection: View {
    @Binding var preferences: ProfilePreferences

    var body: some View {
        PaperSection(title: t("What you want")) {
            Text(t("These lines never appear in a CV. They guide how each job is judged."))
                .font(.caption)
                .foregroundStyle(.secondary)
            PaperRow(label: t("Deal-breakers")) {
                TagEditor(tags: $preferences.dealbreakers, placeholder: t("e.g. shift work"), color: .red)
            }
            PaperRow(label: t("Nice to have")) {
                TagEditor(tags: $preferences.niceToHave, placeholder: t("e.g. remote work"), color: .green)
            }
            PaperRow(label: t("Salary expectation")) {
                TextField(t("For example: 60,000 € a year"), text: $preferences.salaryExpectation)
                    .textFieldStyle(.plain)
            }
            PaperRow(label: t("Notes")) {
                TextField(t("Anything else the evaluation should know"), text: $preferences.notes, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...5)
            }
        }
    }
}

// MARK: Form answers

/// The standard questions of application forms, answered once.
struct FormAnswersSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var answers = FormAnswers()
    @State private var loaded = false
    @State private var saving = false
    @State private var error = ""

    private var primaryName: String {
        let name = languageName(answers.primary)
        return name.isEmpty ? answers.primary.uppercased() : name
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Label(t("Form answers"), systemImage: "list.clipboard").font(.headline)
                Spacer()
                Button(t("Cancel"), role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button(t("Save")) { save() }
                    .buttonStyle(.glassProminent).accentFill()
                    .disabled(!loaded || saving)
            }
            .padding(12)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(t("Answer each question once. On every job page you can copy the answers into the application form. Rows you leave empty are not shown."))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    if !error.isEmpty { Banner(kind: .error, text: error) }
                    if !loaded && error.isEmpty { ProgressView().frame(maxWidth: .infinity) }
                    ForEach(answers.items, id: \.localID) { item in
                        FormAnswerRow(item: rowBinding($answers.items, item.localID, fallback: FormAnswer()),
                                      primary: answers.primary, primaryName: primaryName) {
                            answers.items.removeAll { $0.localID == item.localID }
                        }
                    }
                    if loaded {
                        Button {
                            answers.items.append(FormAnswer())
                        } label: {
                            Label(t("Add a question"), systemImage: "plus")
                        }
                        .buttonStyle(.glass).plainGlass()
                    }
                }
                .padding(16)
            }
        }
        .frame(minWidth: 760, minHeight: 540)
        .task { await load() }
    }

    private func load() async {
        do {
            answers = try await model.api.formAnswers()
            loaded = true
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func save() {
        saving = true
        error = ""
        Task {
            do {
                answers = try await model.api.saveFormAnswers(answers)
                saving = false
                dismiss()
            } catch {
                self.error = error.localizedDescription
                saving = false
            }
        }
    }
}

struct FormAnswerRow: View {
    @Binding var item: FormAnswer
    let primary: String
    let primaryName: String
    var onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                TextField(t("Question"), text: $item.label)
                    .textFieldStyle(.plain)
                    .font(.callout.weight(.semibold))
                Button(action: onDelete) {
                    Image(systemName: "minus.circle")
                }
                .buttonStyle(.borderless)
                .help(t("Remove this question"))
            }
            TextField(primary == "en" ? t("Your answer") : t("Your answer in %@", primaryName),
                      text: $item.primary, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)
            if primary != "en" {
                TextField(t("Your answer in English"), text: $item.en, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...4)
            }
        }
        .padding(10)
        .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
