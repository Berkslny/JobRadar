import SwiftUI

/// Names and colours of the user's own verdict on a posting.
enum Verdict {
    static func title(_ label: String) -> String {
        switch label {
        case "good": return t("Fits")
        case "maybe": return t("Maybe")
        case "bad": return t("Does not fit")
        case "skip": return t("Cannot tell")
        default: return label
        }
    }

    static func color(_ label: String) -> Color {
        switch label {
        case "good": return .green
        case "maybe": return .orange
        case "bad": return .red
        default: return .secondary
        }
    }
}

// MARK: Settings

/// Smart matching: an embedding model compares postings with the tracks and the profile by meaning.
struct MatchingSettings: View {
    @Environment(AppModel.self) private var model
    @State private var state: MatchingState? = nil
    @State private var provider = "fastembed"
    @State private var modelName = ""
    @State private var baseURL = ""
    @State private var busy = false
    @State private var busyText = ""
    @State private var message = ""
    @State private var messageOK = true
    @State private var error = ""

    var body: some View {
        Form {
            Section {
                Text(t("Smart matching compares every posting with your search tracks and your profile by meaning, not only by keywords. Evaluations then go first to the postings that keywords and meaning agree on, and a posting your keywords would miss can still reach you. Rules you set yourself (title words, seniority, kind of job) always hold."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            // a problem is said first: what follows may be missing because of it
            if !error.isEmpty {
                Section {
                    Banner(kind: .error, text: error)
                }
            }
            if let state {
                Section(t("Smart matching")) {
                    Toggle(t("Use smart matching"), isOn: enabledBinding(state))
                        .disabled(busy)
                    Toggle(t("Let strong matches pass the keyword rules"), isOn: promoteBinding(state))
                        .disabled(busy || !state.enabled)
                    Text(t("Such postings carry the \"Semantic match\" badge. At most %@ are let through per scan.", state.promoteMaxPerRun))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section(t("Model")) {
                    Picker(t("Runs with"), selection: providerBinding(state)) {
                        Text(t("Built into JobRadar")).tag("fastembed")
                        Text(t("Ollama on this Mac")).tag("ollama")
                        Text(t("OpenAI-compatible service")).tag("openai")
                    }
                    if provider == "fastembed" {
                        Picker(t("Model"), selection: $modelName) {
                            ForEach(state.models) { option in
                                Text(Self.title(option)).tag(option.id)
                            }
                            if !modelName.isEmpty && !state.models.contains(where: { $0.id == modelName }) {
                                Text(modelName).tag(modelName)
                            }
                        }
                        Text(t("The model is downloaded once from Hugging Face and then runs on this Mac. Your profile and the postings are not sent anywhere for it."))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        TextField(t("Model"), text: $modelName,
                                  prompt: Text(verbatim: state.defaultModels[provider] ?? ""))
                        TextField(t("Address"), text: $baseURL, prompt: Text(t("The address in the AI model settings")))
                        Text(provider == "ollama"
                             ? t("An embedding model of Ollama, for example bge-m3. Download it in Ollama first.")
                             : t("Any service with an OpenAI-compatible embeddings endpoint. A paid service is only used when a paid AI model is allowed."))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                // the buttons and what they report come before the numbers, so they stay on screen without scrolling
                Section {
                    HStack(spacing: 10) {
                        Button(t("Save")) { Task { await save() } }
                            .buttonStyle(.glassProminent).accentFill()
                            .disabled(busy || !changed(state))
                        Button(t("Test the model")) { Task { await test() } }
                            .disabled(busy || !state.enabled)
                        Button(t("Compare my jobs now")) { Task { await run() } }
                            .disabled(busy || !state.enabled || model.cycleRunning)
                        if busy { ProgressView().controlSize(.small) }
                    }
                    if busy && !busyText.isEmpty {
                        Text(busyText).font(.caption).foregroundStyle(.secondary)
                    }
                    if !message.isEmpty { Banner(kind: messageOK ? .success : .warning, text: message) }
                }
                Section(t("State")) {
                    packageState(state)
                    LabeledContent(t("Jobs with a semantic score")) { Text(verbatim: "\(state.scored)") }
                    LabeledContent(t("Let through by smart matching")) { Text(verbatim: "\(state.promoted)") }
                    if !state.lastRun.isEmpty {
                        LabeledContent(t("Last run")) { Text(Dates.relative(state.lastRun)) }
                    }
                    if let waiting = state.lastWaiting, waiting > 0 {
                        Text(t("%@ jobs are compared in the next scan.", waiting))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if let hint = Self.barHint(state) {
                        Text(hint)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if !state.lastError.isEmpty {
                        Banner(kind: .warning, text: state.lastError)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .task { await load() }
    }

    @ViewBuilder
    private func packageState(_ state: MatchingState) -> some View {
        if model.matchingInstalling {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(t("Adding smart matching to the engine…")).font(.caption)
            }
        } else if !model.matchingError.isEmpty {
            Banner(kind: .warning, text: t("Smart matching could not be added to the engine: %@", model.matchingError))
            Button(t("Try again")) { Task { await retryInstall() } }
                .disabled(busy)
        } else if state.enabled && state.provider == "fastembed" && !state.installed {
            Banner(kind: .warning, text: model.config.mode == .local
                   ? t("The engine does not have the matching package yet.")
                   : t("The server has no matching package installed (pip install 'jobradar[match]')."))
        }
    }

    /// Why nothing can be let through yet; nil when a bar exists or promotion is off.
    static func barHint(_ state: MatchingState) -> String? {
        guard state.enabled, state.promote, !state.lastRun.isEmpty, state.threshold == nil,
              let reference = state.lastReference, let background = state.lastBackground else { return nil }
        let referenceNeeded = state.referenceNeeded ?? 20
        let backgroundNeeded = state.backgroundNeeded ?? 10
        if reference < referenceNeeded || background < backgroundNeeded {
            return t("No job can be let through yet: JobRadar first needs more jobs to measure against. With a semantic score so far: %@ jobs that match your keywords (%@ needed) and %@ that do not (%@ needed).",
                     reference, referenceNeeded, background, backgroundNeeded)
        }
        return t("No job is let through: by meaning, the jobs your keywords turn away look like the ones they accept.")
    }

    private static func title(_ option: MatchingModelOption) -> String {
        let short = option.id.split(separator: "/").last.map(String.init) ?? option.id
        return "\(short) · \(option.sizeMb) MB · \(option.note)"
    }

    // MARK: Work

    private func show(_ fresh: MatchingState) {
        state = fresh
        provider = fresh.provider
        modelName = fresh.provider == "fastembed" ? fresh.modelEffective : fresh.model
        baseURL = fresh.baseUrl
    }

    /// What the engine in use says. When it cannot say, nothing of another engine or an earlier moment stays on screen.
    private func load() async {
        guard model.connectionReady else {
            state = nil
            error = t("The engine is not running yet.")
            return
        }
        do {
            show(try await model.api.matching())
            error = ""
        } catch let problem as APIError where problem.status == 404 {
            state = nil
            error = t("This engine is older than the app and has no smart matching yet.")
        } catch {
            state = nil
            self.error = error.localizedDescription
        }
    }

    /// True when the model fields differ from what the engine has.
    private func changed(_ current: MatchingState) -> Bool {
        let saved = current.provider == "fastembed" ? current.modelEffective : current.model
        return provider != current.provider
            || modelName.trimmingCharacters(in: .whitespaces) != saved
            || baseURL.trimmingCharacters(in: .whitespaces) != current.baseUrl
    }

    private func enabledBinding(_ current: MatchingState) -> Binding<Bool> {
        Binding(get: { current.enabled }, set: { on in switchMatching(on) })
    }

    private func promoteBinding(_ current: MatchingState) -> Binding<Bool> {
        Binding(get: { current.promote }, set: { on in switchPromotion(on) })
    }

    private func switchMatching(_ on: Bool) {
        Task { await setEnabled(on) }
    }

    private func switchPromotion(_ on: Bool) {
        Task { _ = await apply(MatchingBody(promote: on)) }
    }

    /// Another provider starts with that provider's standard model.
    private func providerBinding(_ current: MatchingState) -> Binding<String> {
        Binding(get: { provider }, set: { id in
            guard id != provider else { return }
            provider = id
            if id == current.provider {
                modelName = id == "fastembed" ? current.modelEffective : current.model
                baseURL = current.baseUrl
            } else {
                modelName = id == "fastembed" ? (current.defaultModels[id] ?? "") : ""
                baseURL = ""
            }
        })
    }

    private func apply(_ body: MatchingBody) async -> Bool {
        do {
            show(try await model.api.saveMatching(body))
            error = ""
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    private func refresh() async {
        if let fresh = try? await model.api.matching() { show(fresh) }
    }

    private func setEnabled(_ on: Bool) async {
        busy = true
        defer { busy = false }
        busyText = ""
        message = ""
        guard await apply(MatchingBody(enabled: on)), on else { return }
        await prepare()
    }

    private func save() async {
        busy = true
        defer { busy = false }
        busyText = ""
        message = ""
        let body = MatchingBody(provider: provider, model: modelName.trimmingCharacters(in: .whitespaces),
                                baseUrl: baseURL.trimmingCharacters(in: .whitespaces))
        guard await apply(body), state?.enabled == true else { return }
        await prepare()
    }

    /// After turning it on or choosing another model: add the package when it is missing, then load the model once.
    private func prepare() async {
        if model.config.mode == .local, state?.provider == "fastembed", state?.installed == false {
            busyText = t("Adding smart matching to the engine…")
            await model.installMatchingIfNeeded(force: true)
            await refresh()
            guard state?.installed == true else { return }
        }
        await runTest()
    }

    private func retryInstall() async {
        busy = true
        defer { busy = false }
        busyText = t("Adding smart matching to the engine…")
        message = ""
        await model.installMatchingIfNeeded(force: true)
        await refresh()
    }

    private func test() async {
        busy = true
        defer { busy = false }
        message = ""
        await runTest()
    }

    private func runTest() async {
        busyText = state?.provider == "fastembed"
            ? t("Loading the model. The first time it is downloaded, which can take a few minutes.")
            : t("Asking the model…")
        do {
            let task = try await model.wait(try await model.api.testMatching(), every: 2)
            if task.status == "error" || task.result?.ok != true {
                messageOK = false
                message = task.message.isEmpty ? t("The test did not work.") : task.message
            } else {
                messageOK = true
                let seconds = String(format: "%.1f", task.result?.seconds ?? 0)
                message = t("The model works: %@ answered in %@ seconds.", task.result?.model ?? "", seconds)
            }
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
        await refresh()
    }

    private func run() async {
        busy = true
        defer { busy = false }
        message = ""
        busyText = t("Comparing your jobs. With many jobs this takes a few minutes.")
        do {
            let task = try await model.wait(try await model.api.runMatching(), every: 2)
            if task.status == "error" {
                messageOK = false
                message = task.message.isEmpty ? t("That did not work.") : task.message
            } else {
                messageOK = true
                message = t("%@ jobs compared, %@ let through.", task.result?.embedded ?? 0, task.result?.promoted ?? 0)
            }
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
        await refresh()
        await model.refreshSummary()
    }
}

// MARK: Measurements

/// What the user's own verdicts say about the rankings, the keyword rules and the AI model.
/// It fills the wide column beside the status page, where the tables have room.
struct MeasurementPane: View {
    @Environment(AppModel.self) private var model
    let report: BenchReport
    @State private var showLabeling = false

    var body: some View {
        CardPage(maxWidth: 760) {
            SectionBox(title: t("How well JobRadar finds your jobs"), systemImage: "ruler", tint: .teal) {
                Text(t("Measured on your own verdicts: the jobs you shortlisted, applied to or skipped, and the ones you judged here. The more verdicts, the steadier the numbers."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(alignment: .center, spacing: 10) {
                    Text(t("%@ verdicts: %@ fit, %@ maybe, %@ do not fit", report.labels.total, report.labels.good,
                           report.labels.maybe, report.labels.bad))
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    Button {
                        showLabeling = true
                    } label: {
                        Label(t("Judge jobs…"), systemImage: "hand.thumbsup")
                    }
                    .buttonStyle(.glass).plainGlass()
                    .fixedSize()
                    .disabled(model.sampleData)
                }
                if report.rankings.n < Self.minForRankings {
                    Text(t("The orders are compared here once you have %@ verdicts. From about %@ on, the numbers hold still.",
                           Self.minForRankings, report.labels.needed))
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                } else if !report.labels.enough {
                    Text(t("With fewer than %@ verdicts, or only a few of one kind, the numbers below still move a lot.", report.labels.needed))
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if !report.rankings.rows.isEmpty && report.rankings.n >= Self.minForRankings {
                SectionBox(title: t("Which order puts the jobs you want first?"), systemImage: "list.number", tint: .indigo) {
                    rankings
                }
            }
            SectionBox(title: t("What reaches the AI model, and what never does"),
                       systemImage: "line.3.horizontal.decrease.circle", tint: .orange) {
                gate
            }
            if report.judge.n >= Self.minForJudge {
                SectionBox(title: t("Does the AI model judge like you?"), systemImage: "checkmark.seal", tint: .green) {
                    judge
                }
            }
            if report.usage.calls > 0 {
                SectionBox(title: t("Use of the AI model in the last %@ days", report.usage.days),
                           systemImage: "speedometer", tint: .gray) {
                    usage
                }
            }
        }
        .sheet(isPresented: $showLabeling) {
            LabelingSheet()
        }
        .onChange(of: showLabeling) {
            if !showLabeling { Task { await model.loadBench() } }
        }
    }

    /// With fewer verdicts than this a comparison is noise and is not shown.
    static let minForRankings = 10
    static let minForJudge = 5

    /// A number or short heading of a table: never broken in the middle.
    private func cell(_ text: String) -> some View {
        Text(verbatim: text).fixedSize()
    }

    /// The first column of a table: takes the room that is left and wraps at word ends.
    private func name(_ text: String) -> some View {
        Text(verbatim: text)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var rankings: some View {
        let budget = report.rankings.rows.first?.budget ?? 20
        return VStack(alignment: .leading, spacing: 8) {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 7) {
                GridRow {
                    name(t("Order")).bold()
                    cell(t("First 10")).bold()
                    cell(t("First %@", budget)).bold()
                    cell("NDCG@10").bold()
                    cell("AUC").bold()
                }
                .font(.caption)
                Divider()
                ForEach(report.rankings.rows) { row in
                    GridRow {
                        name(row.id == "llm" && row.n != report.rankings.n ? t("%@ (%@ jobs)", row.name, row.n) : row.name)
                        cell(Self.percent(row.precisionAt10))
                        cell(Self.percent(row.budgetHitRate))
                        cell(Self.number(row.ndcgAt10))
                        cell(Self.number(row.auc))
                    }
                    .font(.callout.monospacedDigit())
                }
            }
            Text(t("Measured on the %@ jobs that have a verdict of yours. First 10 and first %@: the share of the jobs at the top of an order that you want. NDCG@10 and AUC: how well the whole order follows your verdicts; 1.0 is perfect, and an AUC of 0.5 is chance.", report.rankings.n, budget)
                 + " "
                 + (report.rankings.semantic
                    ? t("The first rows are measured on the same jobs, so they can be compared.")
                    : t("Turn on smart matching in Settings to compare it with the keyword order here.")))
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var gate: some View {
        VStack(alignment: .leading, spacing: 8) {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 7) {
                GridRow {
                    name(t("Group")).bold()
                    cell(t("Jobs")).bold()
                    cell(t("Judged")).bold()
                    cell(t("You want")).bold()
                    cell(t("Estimate")).bold()
                }
                .font(.caption)
                Divider()
                ForEach(report.gate.groups) { group in
                    GridRow {
                        name(Self.groupTitle(group.id))
                        cell("\(group.postings)")
                        cell("\(group.judged)")
                        cell(Self.wantedText(group))
                        cell(Self.estimateText(group))
                    }
                    .font(.callout.monospacedDigit())
                }
            }
            if let missed = report.gate.estimatedMissed {
                Text(t("About %@ jobs you would want never reach the AI model.", Self.count(missed)))
                    .font(.callout)
                    .foregroundStyle(missed >= 1 ? Color.orange : Color.green)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(t("Estimate: the share you wanted among the jobs you judged, applied to the whole group. It appears once you judged at least 5 jobs of a group."))
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var judge: some View {
        let j = report.judge
        return VStack(alignment: .leading, spacing: 5) {
            Text(t("On the %@ jobs that both of you judged: the same verdict on %@. Only the AI model said yes: %@. Only you said yes: %@.",
                   j.n, Self.percent(j.agreement), j.onlyAiYes, j.onlyYouYes))
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)
            if let kappa = j.kappa {
                Text(t("Agreement beyond chance (kappa): %@. From 0.6 on it is good.", Self.number(kappa)))
                    .font(.callout)
                    .foregroundStyle(kappa >= 0.6 ? Color.green : Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(t("%@ of the evaluated jobs were jobs you want.", Self.percent(j.hitRate)))
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var usage: some View {
        let u = report.usage
        return VStack(alignment: .leading, spacing: 4) {
            Text(Self.usageLine(u))
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(u.byPurpose) { row in
                Text(Self.purposeLine(row))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // MARK: Text

    static func percent(_ value: Double?) -> String {
        guard let value else { return "·" }
        let n = Int((value * 100).rounded())
        return L10n.isTurkish ? "%\(n)" : "\(n)%"
    }

    static func number(_ value: Double?) -> String {
        guard let value else { return "·" }
        return String(format: "%.2f", value)
    }

    static func count(_ value: Double) -> String {
        value == value.rounded() ? String(Int(value)) : String(format: "%.1f", value)
    }

    static func thousands(_ value: Int) -> String {
        value.formatted(.number.locale(L10n.locale))
    }

    /// "3" while too few jobs of the group are judged, "3 (20%)" after that.
    static func wantedText(_ group: BenchGroup) -> String {
        guard let rate = group.rate else { return String(group.wanted) }
        return String(group.wanted) + " (" + percent(rate) + ")"
    }

    static func estimateText(_ group: BenchGroup) -> String {
        guard let estimate = group.estimatedWanted else { return "·" }
        return "~" + count(estimate)
    }

    static func groupTitle(_ id: String) -> String {
        switch id {
        case "evaluated": return t("Evaluated by the AI model")
        case "queue": return t("Waiting for the AI model")
        case "low_score": return t("Quick score too low")
        case "track_filtered": return t("Matches none of your tracks")
        default: return id
        }
    }

    static func purposeTitle(_ id: String) -> String {
        switch id {
        case "evaluate": return t("Evaluating jobs")
        case "tailor": return t("Writing CV and letter")
        case "review": return t("Second reading of the documents")
        case "profile_import": return t("Reading a CV")
        case "search_setup": return t("Setting up the search")
        case "test": return t("Connection tests")
        default: return t("Other")
        }
    }

    static func usageLine(_ u: BenchUsage) -> String {
        var text = t("%@ calls, %@ tokens in, %@ tokens out", u.calls, thousands(u.inputTokens), thousands(u.outputTokens))
        if u.failed > 0 {
            text += " · " + t("%@ failed", u.failed)
        }
        if let cost = u.costUsd {
            text += " · " + t("%@ USD at API prices (a subscription is not charged this)", String(format: "%.2f", cost))
        }
        return text
    }

    static func purposeLine(_ row: BenchUsagePurpose) -> String {
        var text = purposeTitle(row.purpose) + ": " + t("%@ calls", row.calls)
        if let input = row.avgInputTokens, let output = row.avgOutputTokens {
            text += ", " + t("on average %@ tokens in and %@ out", thousands(input), thousands(output))
        }
        text += ", " + t("%@ seconds each", String(format: "%.0f", row.avgSeconds))
        return text
    }
}

/// One posting at a time: does it fit? The answers are the reference for the measurements.
struct LabelingSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var queue: [LabelCandidate] = []
    @State private var remaining = 0
    @State private var judged = 0
    @State private var loading = true
    @State private var saving = false
    @State private var error = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label(t("Does this job fit you?"), systemImage: "hand.thumbsup").font(.headline)
                Spacer()
                Text(t("%@ judged · %@ to go", judged, remaining))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(t("Judge the posting as if you had just found it yourself. Scores are hidden on purpose. The jobs are drawn from everything JobRadar collected, including what its rules filtered out, so the numbers show what the rules miss."))
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let job = queue.first {
                card(job)
                buttons(job)
            } else if loading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableView(t("Nothing left to judge"), systemImage: "checkmark.circle",
                                       description: Text(t("More jobs appear here after the next scan.")))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if !error.isEmpty {
                Banner(kind: .error, text: error)
            }
            HStack {
                if !queue.isEmpty {
                    Text(t("Keys 1, 2 and 3 choose Fits, Maybe and Does not fit."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(t("Done")) { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(20)
        .frame(width: 660, height: 640)
        .task { await load() }
    }

    private func card(_ job: LabelCandidate) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(job.title).font(.title3.bold())
            Text([job.company, job.location].filter { !$0.isEmpty }.joined(separator: " · "))
                .foregroundStyle(.secondary)
            ChipGrid(items: chips(job))
            ScrollView {
                Text(job.description.isEmpty
                     ? t("This posting came without a description. Judge it by its title, or open it.")
                     : job.description)
                    .font(.callout)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: .infinity)
        }
        .card()
        .id(job.id)
    }

    private func chips(_ job: LabelCandidate) -> [(text: String, color: Color)] {
        var items: [(text: String, color: Color)] = []
        if !job.employmentLabel.isEmpty { items.append((job.employmentLabel, .blue)) }
        if !job.remoteLabel.isEmpty { items.append((job.remoteLabel, .blue)) }
        if !job.salaryText.isEmpty { items.append((job.salaryText, .green)) }
        for badge in job.badges { items.append((badge.label, Palette.badge(badge.kind))) }
        if let posted = job.postedAt, !posted.isEmpty {
            items.append((t("Posted %@", Dates.short(posted)), .secondary))
        }
        // the same word can come from two places (the kind of job and a note of the posting): show it once
        var seen = Set<String>()
        return items.filter { seen.insert($0.text).inserted }
    }

    private func buttons(_ job: LabelCandidate) -> some View {
        HStack(spacing: 10) {
            verdictButton(job, "good", icon: "hand.thumbsup", key: "1")
            verdictButton(job, "maybe", icon: "questionmark.circle", key: "2")
            verdictButton(job, "bad", icon: "hand.thumbsdown", key: "3")
            Spacer()
            Button(Verdict.title("skip")) { Task { await choose(job, "skip") } }
                .disabled(saving)
            if let url = job.postingURL {
                Button {
                    openURL(url)
                } label: {
                    Label(t("Open posting"), systemImage: "safari")
                }
            }
        }
        .buttonStyle(.glass).plainGlass()
    }

    private func verdictButton(_ job: LabelCandidate, _ label: String, icon: String, key: KeyEquivalent) -> some View {
        Button {
            Task { await choose(job, label) }
        } label: {
            Label(Verdict.title(label), systemImage: icon)
        }
        .keyboardShortcut(key, modifiers: [])
        .disabled(saving)
        .help(t("Key %@", String(key.character)))
    }

    private func choose(_ job: LabelCandidate, _ label: String) async {
        guard !saving else { return }
        saving = true
        defer { saving = false }
        do {
            try await model.api.setLabel(job.id, label: label)
            error = ""
            queue.removeAll { $0.id == job.id }
            remaining = max(0, remaining - 1)
            if label != "skip" { judged += 1 }
            if queue.isEmpty { await load() }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let fresh = try await model.api.labelQueue(limit: 10)
            queue = fresh.jobs
            remaining = fresh.remaining
            judged = fresh.judged
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
    }
}
