import Observation
import SwiftUI

/// The search settings being edited (what to look for, where, on which sources).
@MainActor
@Observable
final class SearchEditor {
    var draft = SearchSetup()
    var saved = SearchSetup()
    var loaded = false
    var loading = false
    var saving = false
    var suggesting = false
    var note = ""
    var error = ""
    /// What the user is looking for, in their own words; the AI model turns it into search tracks.
    var roles: String = UserDefaults.standard.string(forKey: "searchWish") ?? "" {
        didSet { UserDefaults.standard.set(roles, forKey: "searchWish") }
    }

    var dirty: Bool { loaded && draft != saved }

    func load(_ model: AppModel, force: Bool = false) async {
        guard model.connectionReady, !loading else { return }
        if loaded && !force { return }
        loading = true
        defer { loading = false }
        do {
            apply(try await model.api.search())
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func apply(_ setup: SearchSetup) {
        saved = setup
        draft = setup
        loaded = true
    }

    func save(_ model: AppModel) async -> Bool {
        guard !saving else { return false }
        saving = true
        defer { saving = false }
        do {
            apply(try await model.api.saveSearch(draft))
            error = ""
            note = t("Saved. The next scan uses the new settings.")
            await model.loadSetup()
            await model.refreshSummary()
            return true
        } catch {
            self.error = error.localizedDescription
            note = ""
            return false
        }
    }

    /// Turns `roles` into search tracks (with the AI model when one is connected). Nothing is saved yet.
    func suggest(_ model: AppModel) async -> Bool {
        guard !suggesting else { return false }
        suggesting = true
        defer { suggesting = false }
        error = ""
        note = ""
        let place = draft.locations.map(\.city).filter { !$0.isEmpty }.joined(separator: ", ")
        do {
            let start = try await model.api.suggestSearch(roles: roles, country: draft.country, where: place)
            let task = try await model.wait(start)
            guard task.status != "error", let tracks = task.result?.tracks, !tracks.isEmpty else {
                error = task.message.isEmpty ? t("No search tracks could be made from that. Describe the roles in a few words.")
                                             : task.message
                return false
            }
            draft.tracks = tracks
            for word in task.result?.titleExclude ?? [] where !draft.filters.titleExclude.contains(word) {
                draft.filters.titleExclude.append(word)
            }
            if let senior = task.result?.excludeSenior {
                draft.filters.excludeSenior = senior
            }
            loaded = true
            note = t("Made %@ search tracks. Check them, then save.", tracks.count)
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

    /// Germany has its own public job board; it follows the chosen country.
    func countryChanged(from old: String) {
        if draft.country == "DE" && old != "DE" {
            draft.sources.arbeitsagentur.enabled = true
        } else if draft.country != "DE" {
            draft.sources.arbeitsagentur.enabled = false
        }
    }
}

enum SearchLabels {
    static func site(_ id: String) -> String {
        switch id {
        case "linkedin": return "LinkedIn"
        case "indeed": return "Indeed"
        case "glassdoor": return "Glassdoor"
        case "google": return "Google Jobs"
        case "zip_recruiter": return "ZipRecruiter"
        case "bayt": return "Bayt"
        case "naukri": return "Naukri"
        default: return id
        }
    }

    static func employment(_ id: String) -> String {
        switch id {
        case "fulltime": return t("Full-time")
        case "parttime": return t("Part-time")
        case "werkstudent": return t("Working student")
        case "internship": return t("Internship")
        case "thesis": return t("Thesis")
        case "trainee": return t("Trainee")
        case "apprenticeship": return t("Apprenticeship")
        case "freelance": return t("Freelance")
        case "contract": return t("Contract")
        default: return id
        }
    }

    static func ats(_ id: String) -> String {
        switch id {
        case "greenhouse": return "Greenhouse"
        case "lever": return "Lever"
        case "lever_eu": return "Lever (EU)"
        case "ashby": return "Ashby"
        case "personio": return "Personio"
        case "smartrecruiters": return "SmartRecruiters"
        case "recruitee": return "Recruitee"
        case "workday": return "Workday"
        case "softgarden": return "Softgarden"
        case "rheinmetall": return "Rheinmetall"
        default: return id
        }
    }
}

// MARK: Side column: what and where

struct SearchSideView: View {
    @Environment(AppModel.self) private var model
    @Environment(SearchEditor.self) private var editor

    var body: some View {
        CardPage(maxWidth: 560) {
            SearchWishCard()
            SearchWhereCard()
            saveCard
        }
        .navigationTitle(t("Search"))
        .task { await editor.load(model) }
        .toolbar {
            ToolbarItem {
                Button {
                    Task { _ = await editor.save(model) }
                } label: {
                    Label(t("Save search"), systemImage: "checkmark.circle")
                }
                .buttonStyle(.glassProminent).accentFill()
                .keyboardShortcut("s", modifiers: .command)
                .disabled(!editor.dirty || editor.saving)
                .help(t("Save the search settings (⌘S)"))
            }
        }
    }

    private var saveCard: some View {
        SectionBox(title: t("Save"), systemImage: "tray.and.arrow.down") {
            HStack(spacing: 8) {
                Button(t("Save search")) { Task { _ = await editor.save(model) } }
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

/// "What are you looking for?" plus the button that turns the answer into search tracks.
struct SearchWishCard: View {
    @Environment(AppModel.self) private var model
    @Environment(SearchEditor.self) private var editor
    @State private var confirmReplace = false

    private var aiReady: Bool {
        model.setup?.ai.ready ?? (model.summary?.llmReady ?? false)
    }

    var body: some View {
        @Bindable var editor = editor
        SectionBox(title: t("What are you looking for?"), systemImage: "sparkle.magnifyingglass") {
            Text(t("Describe the jobs you want in your own words. JobRadar turns that into search tracks with the right keywords for the job boards of your country."))
                .font(.callout)
                .foregroundStyle(.secondary)
            TextField(t("For example: junior data analyst, business intelligence, SQL and Python, no sales roles"),
                      text: $editor.roles, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(3...7)
            HStack(spacing: 8) {
                Button {
                    if editor.draft.tracks.isEmpty {
                        Task { _ = await editor.suggest(model) }
                    } else {
                        confirmReplace = true
                    }
                } label: {
                    Label(t("Make search tracks"), systemImage: "wand.and.stars")
                }
                .buttonStyle(.glassProminent).accentFill()
                .disabled(editor.suggesting || editor.roles.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if editor.suggesting {
                    ProgressView().controlSize(.small)
                    Text(t("Thinking… up to a minute.")).font(.caption).foregroundStyle(.secondary)
                }
            }
            if !aiReady {
                Text(t("No AI model is connected, so the tracks are made from your words alone. With a model they get much better keywords."))
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .confirmationDialog(t("Replace the current search tracks?"), isPresented: $confirmReplace) {
            Button(t("Replace"), role: .destructive) { Task { _ = await editor.suggest(model) } }
            Button(t("Cancel"), role: .cancel) {}
        } message: {
            Text(t("The new tracks replace the ones you have now. Nothing is saved until you press Save."))
        }
    }
}

/// Country, cities and remote work.
struct SearchWhereCard: View {
    @Environment(SearchEditor.self) private var editor

    var body: some View {
        @Bindable var editor = editor
        SectionBox(title: t("Where?"), systemImage: "mappin.and.ellipse") {
            // only a choice made here adjusts the sources; loading the saved country must not
            Picker(t("Country"), selection: Binding(
                get: { editor.draft.country },
                set: { code in
                    let old = editor.draft.country
                    editor.draft.country = code
                    editor.countryChanged(from: old)
                })) {
                Text(t("Choose a country")).tag("")
                ForEach(editor.draft.options?.countries ?? []) { country in
                    Text(country.name).tag(country.code)
                }
            }
            Text(t("Cities"))
                .font(.caption)
                .foregroundStyle(.secondary)
            ForEach(editor.draft.locations) { location in
                LocationRow(location: rowBinding($editor.draft.locations, location.localID, fallback: SearchLocation())) {
                    editor.draft.locations.removeAll { $0.localID == location.localID }
                }
            }
            Button {
                editor.draft.locations.append(SearchLocation())
            } label: {
                Label(t("Add a city"), systemImage: "plus")
            }
            .buttonStyle(.borderless)
            .font(.callout)
            if editor.draft.locations.isEmpty {
                Text(t("Without a city, the whole country is searched."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Toggle(t("Include remote jobs"), isOn: $editor.draft.includeRemote)
        }
    }
}

struct LocationRow: View {
    @Binding var location: SearchLocation
    var onDelete: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            TextField(t("City"), text: $location.city)
                .textFieldStyle(.roundedBorder)
            Picker(t("Radius"), selection: $location.radiusKm) {
                ForEach(radiusOptions, id: \.self) { km in
                    Text(t("%@ km", km)).tag(km)
                }
            }
            .labelsHidden()
            .frame(width: 100)
            Button(action: onDelete) {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help(t("Remove"))
        }
    }

    private var radiusOptions: [Int] {
        let base = [10, 25, 50, 80, 100, 150, 200]
        return base.contains(location.radiusKm) ? base : (base + [location.radiusKm]).sorted()
    }
}

// MARK: Detail column: tracks, sources, filters

struct SearchDetailView: View {
    @Environment(AppModel.self) private var model
    @Environment(SearchEditor.self) private var editor

    var body: some View {
        @Bindable var editor = editor
        CardPage(maxWidth: 860) {
            if !editor.loaded {
                ProgressView().frame(maxWidth: .infinity)
            } else {
                tracksHeader
                ForEach(editor.draft.tracks, id: \.localID) { track in
                    TrackCard(track: rowBinding($editor.draft.tracks, track.localID, fallback: TrackSetup()),
                              onMove: { offset in move(track.localID, by: offset) },
                              onDelete: { editor.draft.tracks.removeAll { $0.localID == track.localID } })
                }
                SourcesCard(sources: $editor.draft.sources, country: editor.draft.country,
                            sites: editor.draft.options?.jobspySites ?? [])
                CompaniesCard(companies: $editor.draft.sources.companies,
                              atsTypes: editor.draft.options?.atsTypes ?? [])
                FiltersCard(filters: $editor.draft.filters)
                FineTuningCard(setup: $editor.draft)
            }
        }
        .task { await editor.load(model) }
    }

    private var tracksHeader: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 3) {
                Text(t("Search tracks")).font(.title3.bold())
                Text(t("A track is one direction of your search, with the words that find and recognise its postings."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                editor.draft.tracks.append(TrackSetup())
            } label: {
                Label(t("Add a track"), systemImage: "plus")
            }
            .buttonStyle(.glass).plainGlass()
        }
    }

    private func move(_ id: UUID, by offset: Int) {
        guard let index = editor.draft.tracks.firstIndex(where: { $0.localID == id }) else { return }
        let target = index + offset
        guard editor.draft.tracks.indices.contains(target) else { return }
        editor.draft.tracks.swapAt(index, target)
    }
}

struct TrackCard: View {
    @Binding var track: TrackSetup
    var onMove: (Int) -> Void
    var onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: "scope").foregroundStyle(.orange)
                TextField(t("Name of the track"), text: $track.name)
                    .textFieldStyle(.plain)
                    .font(.headline)
                Toggle(t("Active"), isOn: $track.enabled)
                    .toggleStyle(.switch)
                    .controlSize(.small)
                Menu {
                    Button(t("Move up")) { onMove(-1) }
                    Button(t("Move down")) { onMove(1) }
                    Divider()
                    Button(t("Delete this track"), role: .destructive) { onDelete() }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
            }
            TextField(t("The ideal role in a sentence or two (field, level, kind of employer)"),
                      text: $track.northStar, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)
            TagEditor(title: t("Search terms: typed into the job boards, the most productive first"),
                      tags: $track.searchTerms, placeholder: t("Add a search term…"), color: .orange)
            TagEditor(title: t("Title words: a posting's title must contain one of these (word stems work)"),
                      tags: $track.titleKeywords, placeholder: t("Add a title word…"), color: .blue)
            TagEditor(title: t("Topic words: tools and terms in the description that raise the score"),
                      tags: $track.domainKeywords, placeholder: t("Add a topic word…"), color: .teal)
            Toggle(t("Search the whole country for this track, not only around your cities"), isOn: $track.nationwide)
                .font(.callout)
        }
        .card()
    }
}

struct SourcesCard: View {
    @Environment(AppModel.self) private var model
    @Binding var sources: SearchSources
    let country: String
    let sites: [String]

    var body: some View {
        SectionBox(title: t("Where the jobs come from"), systemImage: "point.3.connected.trianglepath.dotted") {
            Toggle(t("Job boards"), isOn: $sources.jobspy.enabled)
                .toggleStyle(.switch)
            if sources.jobspy.enabled {
                FlowLayout(spacing: 8) {
                    ForEach(sites, id: \.self) { site in
                        Toggle(SearchLabels.site(site), isOn: siteBinding(site))
                            .toggleStyle(.button)
                            .controlSize(.small)
                    }
                }
                jobBoardsStatus
            }
            if country == "DE" {
                Divider()
                Toggle(t("Bundesagentur für Arbeit (Germany's public job board)"), isOn: $sources.arbeitsagentur.enabled)
                    .toggleStyle(.switch)
            }
            Divider()
            Toggle(t("freehire.me (XING, EURES and company pages in Europe)"), isOn: $sources.freehire.enabled)
                .toggleStyle(.switch)
            Text(t("freehire.me allows reading without a key for personal, non-commercial use only."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var jobBoardsStatus: some View {
        if model.config.mode == .local {
            if model.jobBoardsInstalling {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(t("Adding the job board connectors… they are ready in a minute.")).font(.caption)
                }
            } else if !model.jobBoardsError.isEmpty {
                Banner(kind: .warning, text: t("The job board connectors could not be installed: %@", model.jobBoardsError))
                Button(t("Try again")) { Task { await model.installJobBoards(force: true) } }
                    .buttonStyle(.glass).plainGlass()
            }
        } else if sources.jobspy.installed == false {
            Banner(kind: .warning, text: t("The server has no job board connectors (python-jobspy) installed."))
        }
        Text(t("Job boards limit how often they can be read. JobRadar reads them slowly and only for you; please respect their terms."))
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private func siteBinding(_ site: String) -> Binding<Bool> {
        Binding(
            get: { sources.jobspy.sites.contains(site) },
            set: { on in
                if on {
                    if !sources.jobspy.sites.contains(site) { sources.jobspy.sites.append(site) }
                } else {
                    sources.jobspy.sites.removeAll { $0 == site }
                }
            }
        )
    }
}

struct CompaniesCard: View {
    @Environment(AppModel.self) private var model
    @Binding var companies: [CompanyBoard]
    let atsTypes: [String]
    @State private var address = ""
    @State private var busy = false
    @State private var message = ""
    @State private var failed = false

    var body: some View {
        SectionBox(title: t("Company career pages"), systemImage: "building.2") {
            Text(t("Follow the career page of a company directly. Paste its address; JobRadar recognises the common career systems (Greenhouse, Lever, Personio, Workday and others)."))
                .font(.callout)
                .foregroundStyle(.secondary)
            HStack(spacing: 8) {
                TextField(t("Address of the company's job list"), text: $address)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(detect)
                Button(t("Add"), action: detect)
                    .buttonStyle(.glass).plainGlass()
                    .disabled(busy || !address.lowercased().hasPrefix("http"))
                if busy { ProgressView().controlSize(.small) }
            }
            if !message.isEmpty {
                Text(message).font(.caption).foregroundStyle(failed ? Color.red : Color.green)
            }
            ForEach(companies) { company in
                CompanyRow(company: rowBinding($companies, company.localID, fallback: CompanyBoard()), atsTypes: atsTypes) {
                    companies.removeAll { $0.localID == company.localID }
                }
            }
        }
    }

    private func detect() {
        let url = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, url.lowercased().hasPrefix("http") else { return }
        busy = true
        message = ""
        Task {
            do {
                let found = try await model.api.detectCompany(url: url, name: "")
                var added = 0
                for board in found where !companies.contains(where: { $0.ats == board.ats && $0.slug == board.slug && $0.url == board.url }) {
                    companies.append(board)
                    added += 1
                }
                failed = false
                message = added > 0 ? t("Added. Give it the right name, then save.") : t("This page is already in the list.")
                address = ""
            } catch {
                failed = true
                message = error.localizedDescription
            }
            busy = false
        }
    }
}

struct CompanyRow: View {
    @Binding var company: CompanyBoard
    let atsTypes: [String]
    var onDelete: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Toggle(t("Active"), isOn: $company.enabled)
                .labelsHidden()
                .toggleStyle(.switch)
                .controlSize(.mini)
            TextField(t("Company"), text: $company.name)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 220)
            Chip(text: SearchLabels.ats(company.ats), color: .indigo)
            Text(company.slug.isEmpty ? company.url : company.slug)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 0)
            Button(action: onDelete) {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help(t("Remove"))
        }
    }
}

struct FiltersCard: View {
    @Binding var filters: SearchFilters

    var body: some View {
        SectionBox(title: t("What to leave out"), systemImage: "line.3.horizontal.decrease.circle") {
            TagEditor(title: t("Skip postings whose title contains"), tags: $filters.titleExclude,
                      placeholder: t("Add a word…"), color: .red)
            TagEditor(title: t("Skip these companies"), tags: $filters.companyBlacklist,
                      placeholder: t("Add a company…"), color: .red)
            Toggle(t("Skip senior and lead roles"), isOn: $filters.excludeSenior)
            Toggle(t("Skip staffing agencies"), isOn: $filters.excludeAgencies)
            Toggle(t("Keep only postings whose title fits a track"), isOn: $filters.requireTrackMatch)
        }
    }
}

struct FineTuningCard: View {
    @Binding var setup: SearchSetup

    var body: some View {
        SectionBox(title: t("Fine tuning"), systemImage: "slider.horizontal.3") {
            Text(t("Kinds of employment")).font(.caption).foregroundStyle(.secondary)
            FlowLayout(spacing: 8) {
                ForEach(setup.options?.employmentTypes ?? [], id: \.self) { kind in
                    Toggle(SearchLabels.employment(kind), isOn: employmentBinding(kind))
                        .toggleStyle(.button)
                        .controlSize(.small)
                }
            }
            Stepper(t("Ignore postings older than %@ days", setup.maxAgeDays), value: $setup.maxAgeDays, in: 7...365, step: 7)
            Stepper(t("Evaluate up to %@ postings per scan with the AI model", setup.scoring.llmMaxPerRun),
                    value: $setup.scoring.llmMaxPerRun, in: 0...200, step: 5)
            Stepper(t("Only evaluate postings with a quick score of %@ or more", Int(setup.scoring.prescoreMin)),
                    value: $setup.scoring.prescoreMin, in: 0...100, step: 5)
            Stepper(t("A strong match scores %@ or more (out of 5)", String(format: "%.1f", setup.scoring.applyThreshold)),
                    value: $setup.scoring.applyThreshold, in: 2.5...5.0, step: 0.1)
            Text(t("Each evaluation uses your AI model once, so the number per scan decides how much of your plan or credit a scan uses."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func employmentBinding(_ kind: String) -> Binding<Bool> {
        Binding(
            get: { setup.employmentTypes.contains(kind) },
            set: { on in
                if on {
                    if !setup.employmentTypes.contains(kind) { setup.employmentTypes.append(kind) }
                } else if setup.employmentTypes.count > 1 {
                    setup.employmentTypes.removeAll { $0 == kind }
                }
            }
        )
    }
}
