import SwiftUI

/// The assistant for new users, or the main window.
struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if model.showOnboarding {
                OnboardingView()
            } else {
                MainView()
            }
        }
        .animation(.easeInOut(duration: 0.3), value: model.showOnboarding)
        .alert("JobRadar", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button(t("OK"), role: .cancel) { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
        }
    }
}

struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 200, ideal: 232, max: 300)
        } content: {
            contentColumn
                .safeAreaInset(edge: .top, spacing: 0) {
                    VStack(spacing: 8) {
                        if model.cycleRunning || model.cycleResult != nil {
                            ScanProgressView()
                                .transition(.opacity)
                        }
                        if model.sampleData {
                            SampleDataBanner()
                        } else if showSetupBanner {
                            SetupBanner()
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.top, (model.cycleRunning || model.cycleResult != nil || showSetupBanner || model.sampleData) ? 6 : 0)
                    .animation(.easeInOut(duration: 0.25), value: model.cycleRunning)
                    .animation(.easeInOut(duration: 0.25), value: model.cycleResult)
                }
                .navigationSplitViewColumnWidth(min: 360, ideal: 440)
        } detail: {
            detailColumn
        }
        .task { await model.refreshAll() }
        .onChange(of: model.sidebar) {
            if model.keepSelectionOnSidebarChange {
                model.keepSelectionOnSidebarChange = false
                return
            }
            model.selectedJobID = nil
            model.detail = nil
            Task { await model.refreshAll() }
        }
        .sheet(isPresented: $model.showImport) { ImportSheet() }
    }

    /// The setup hint is shown above the job lists while something is missing.
    private var showSetupBanner: Bool {
        guard model.connectionReady, let setup = model.setup, !setup.ready else { return false }
        if case .jobs = model.sidebar { return true }
        return false
    }

    @ViewBuilder
    private var contentColumn: some View {
        if model.config.mode == .local && model.localState != .running {
            EngineStatusView()
        } else if !model.config.isComplete {
            ContentUnavailableView {
                Label(t("No server set up"), systemImage: "server.rack")
            } description: {
                Text(t("Enter the server address and its API key in Settings."))
            } actions: {
                Button(t("Open Settings")) { openSettings() }
            }
        } else {
            switch model.sidebar {
            case .stats: StatsView()
            case .replies: MailSignalsView()
            case .profile: ProfileSideView()
            case .search: SearchSideView()
            default: JobListView()
            }
        }
    }

    @ViewBuilder
    private var detailColumn: some View {
        if !model.connectionReady {
            ContentUnavailableView("JobRadar", systemImage: "scope",
                                   description: Text(t("Your job matches appear here once the engine is running.")))
        } else {
            switch model.sidebar {
            case .stats:
                if let report = model.bench {
                    MeasurementPane(report: report)
                } else {
                    ContentUnavailableView(t("Engine status"), systemImage: "chart.bar.xaxis",
                                           description: Text(t("Sources, runs and skill gaps are summarised on the left.")))
                }
            case .profile:
                ProfilePaperView()
            case .search:
                SearchDetailView()
            default:
                if let id = model.selectedJobID {
                    JobDetailView(jobID: id)
                } else if model.sidebar == .replies {
                    ContentUnavailableView(t("Choose a reply"), systemImage: "envelope.open",
                                           description: Text(t("Click \"Show job\" on a reply to open its posting here.")))
                } else {
                    ContentUnavailableView(t("Choose a job"), systemImage: "doc.text.magnifyingglass",
                                           description: Text(t("Pick a posting from the list to see its evaluation.")))
                }
            }
        }
    }
}

struct SidebarView: View {
    @Environment(AppModel.self) private var model
    @Environment(ProfileEditor.self) private var profileEditor
    @Environment(SearchEditor.self) private var searchEditor

    var body: some View {
        @Bindable var model = model
        List(selection: $model.sidebar) {
            Section(t("Jobs")) {
                ForEach(jobListKinds) { kind in
                    sidebarLabel(kind.title, kind.icon, color(for: kind.id))
                        .badge(model.summary?.views[kind.id] ?? 0)
                        .tag(SidebarItem.jobs(kind.id))
                }
            }
            Section(t("Follow-up")) {
                sidebarLabel(t("E-mail replies"), "envelope.badge", .pink)
                    .badge(model.pendingReplies)
                    .tag(SidebarItem.replies)
            }
            Section(t("You")) {
                sidebarLabel(t("Profile"), "person.text.rectangle", .teal)
                    .badge(profileEditor.dirty ? Text(verbatim: "●") : nil)
                    .tag(SidebarItem.profile)
                sidebarLabel(t("Search"), "scope", .orange)
                    .badge(searchEditor.dirty ? Text(verbatim: "●") : nil)
                    .tag(SidebarItem.search)
            }
            Section(t("Engine")) {
                sidebarLabel(t("Status and sources"), "chart.bar", .gray)
                    .tag(SidebarItem.stats)
            }
            if let s = model.summary {
                Section(t("Summary")) {
                    VStack(alignment: .leading, spacing: 6) {
                        summaryLine("star.fill", .orange,
                                    t("%@ strong matches (≥ %@)", s.strongOpen, String(format: "%.1f", s.strongThreshold)))
                        summaryLine("hourglass", .secondary, t("%@ waiting for evaluation", s.pendingEvaluation))
                        if s.followUpsDue > 0 {
                            summaryLine("bell", .blue, t("%@ applications due for a follow-up", s.followUpsDue))
                        }
                        if (s.mailSignalsPending ?? 0) > 0 {
                            summaryLine("envelope.badge", .red, t("%@ e-mail replies to review", s.mailSignalsPending ?? 0))
                        }
                        if s.todoFacts > 0 {
                            summaryLine("exclamationmark.triangle", .orange, t("%@ TODO notes in the profile", s.todoFacts))
                        }
                        if model.cycleRunning {
                            summaryLine("antenna.radiowaves.left.and.right", ThemeStore.shared.accentText,
                                        t("Scan running") + (ScanProgressView.percent(model.cycleProgress).map { " · \($0)" } ?? ""))
                        } else if !s.lastCycle.isEmpty {
                            summaryLine("clock", .secondary, t("Last scan %@", Dates.relative(s.lastCycle)))
                        } else {
                            summaryLine("clock", .secondary, t("No scan yet"))
                        }
                    }
                    .font(.caption)
                    .padding(.vertical, 2)
                }
            }
        }
        .listStyle(.sidebar)
    }

    private func color(for view: String) -> Color {
        switch view {
        case "inbox": return .blue
        case "active": return .purple
        case "done": return .green
        case "filtered": return .gray
        default: return .indigo
        }
    }

    private func sidebarLabel(_ title: String, _ icon: String, _ color: Color) -> some View {
        Label {
            Text(title)
        } icon: {
            Image(systemName: icon).foregroundStyle(color)
        }
    }

    private func summaryLine(_ icon: String, _ color: Color, _ text: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon).foregroundStyle(color).frame(width: 14)
            Text(text).foregroundStyle(.secondary)
        }
    }
}

/// Shown while the app runs on made-up data, with the way back.
struct SampleDataBanner: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "eyes").foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 1) {
                Text(t("Sample data")).font(.callout.weight(.semibold))
                Text(t("These jobs and this profile are made up. Nothing is scanned or sent."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Button(t("Leave the sample data")) { Task { await model.showSampleData(false) } }
                .buttonStyle(.glassProminent).accentFill()
                .controlSize(.small)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .cardBackground(cornerRadius: 14, tint: .orange)
    }
}

/// What is still missing before JobRadar can find and judge jobs, with a way to fix it.
struct SetupBanner: View {
    @Environment(AppModel.self) private var model

    private var missing: [String] {
        guard let s = model.setup else { return [] }
        var out: [String] = []
        if !s.ai.ready { out.append(t("an AI model")) }
        if !s.profile.exists || !s.profile.missing.isEmpty { out.append(t("your profile")) }
        if s.search.tracks == 0 { out.append(t("what to search for")) }
        return out
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "wand.and.stars").foregroundStyle(.tint)
            Text(t("Still to set up: %@.", missing.joined(separator: ", ")))
                .font(.callout)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(t("Continue setup")) { model.reopenOnboarding() }
                .buttonStyle(.glassProminent).accentFill()
                .controlSize(.small)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .cardBackground(cornerRadius: 14)
    }
}

struct JobListView: View {
    @Environment(AppModel.self) private var model

    private var title: String {
        jobListKinds.first { $0.id == model.currentView }?.title ?? t("Jobs")
    }

    /// "598 jobs", or "1,000 of 2,306 jobs" while only part of a big view is loaded.
    private var subtitle: String {
        let shown = model.jobs.count
        let total = max(model.jobsTotal, shown)
        return total > shown ? t("%@ of %@ jobs", shown.formatted(), total.formatted()) : t("%@ jobs", shown.formatted())
    }

    var body: some View {
        @Bindable var model = model
        List(selection: $model.selectedJobID) {
            ForEach(model.jobs) { job in
                JobRowView(job: job, task: model.runningTasks[job.id])
                    .contextMenu { StatusMenuItems(jobID: job.id) }
            }
            if model.jobs.count < model.jobsTotal {
                HStack(spacing: 8) {
                    Spacer()
                    Button(t("Show %@ more", model.jobsTotal - model.jobs.count)) {
                        Task { await model.loadMoreJobs() }
                    }
                    .buttonStyle(.glass).plainGlass()
                    .disabled(model.isLoadingMore)
                    if model.isLoadingMore { ProgressView().controlSize(.small) }
                    Spacer()
                }
                .padding(.vertical, 8)
            }
        }
        .scrollContentBackground(.hidden)
        .overlay {
            if model.jobs.isEmpty && !model.isLoading {
                ContentUnavailableView(t("No jobs here"), systemImage: "tray",
                                       description: Text(emptyHint))
            }
        }
        .searchable(text: $model.search, prompt: t("Title, company, city"))
        .onSubmit(of: .search) { Task { await model.reloadJobs() } }
        .onChange(of: model.search) {
            if model.search.isEmpty { Task { await model.reloadJobs() } }
        }
        .onChange(of: model.order) { Task { await model.reloadJobs() } }
        .onChange(of: model.track) { Task { await model.reloadJobs() } }
        .onChange(of: model.selectedJobID) { Task { await model.loadDetail(model.selectedJobID) } }
        .navigationTitle(title)
        .navigationSubtitle(subtitle)
        .toolbar {
            ToolbarItemGroup {
                Picker(t("Track"), selection: $model.track) {
                    Text(t("All tracks")).tag("")
                    ForEach(model.summary?.tracks ?? []) { track in
                        Text(track.name).tag(track.id)
                    }
                }
                .help(t("Show one search track only"))
                Picker(t("Order"), selection: $model.order) {
                    Text(t("By score")).tag("score")
                    Text(t("By date")).tag("date")
                    Text(t("By company")).tag("company")
                }
                .help(t("Sort order"))
            }
            ToolbarSpacer(.fixed)
            ToolbarItemGroup {
                Button {
                    model.importDraft = ""
                    model.showImport = true
                } label: {
                    Label(t("Add link"), systemImage: "link.badge.plus")
                }
                .help(t("Add a posting by its link (⌘L)"))
                Button {
                    Task { await model.refreshAll() }
                } label: {
                    Label(t("Refresh"), systemImage: "arrow.clockwise")
                }
                .help(t("Refresh (⌘R)"))
            }
            ToolbarSpacer(.fixed)
            ToolbarItem {
                Button {
                    Task { await model.runCycle() }
                } label: {
                    Label(t("Scan now"), systemImage: "antenna.radiowaves.left.and.right")
                }
                .buttonStyle(.glassProminent).accentFill()
                .disabled(model.cycleRunning || model.summary?.running == true || model.sampleData)
                .help(model.cycleRunning ? t("A scan is running") : t("Look for new jobs now (⇧⌘R)"))
            }
        }
    }

    private var emptyHint: String {
        if model.summary?.lastCycle.isEmpty == true && model.currentView == "inbox" {
            return t("Run a scan to fill your inbox.")
        }
        return t("There are no postings in this view.")
    }
}

struct JobRowView: View {
    let job: JobSummary
    let task: TaskInfo?

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ScoreBadge(llmScore: job.llmScore, prescore: job.prescore)
            VStack(alignment: .leading, spacing: 3) {
                Text(job.title).font(.headline).lineLimit(2)
                Text([job.company, job.location].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                HStack(spacing: 4) {
                    if job.status != "new" {
                        Chip(text: job.statusLabel, color: Palette.status(job.status))
                    }
                    if let v = job.verdict, !v.isEmpty {
                        Chip(text: Palette.verdict(v), color: Palette.score(job.llmScore))
                    }
                    ForEach(Array(job.badges.prefix(2).enumerated()), id: \.offset) { _, b in
                        Chip(text: b.label, color: Palette.badge(b.kind))
                    }
                    if let task {
                        ProgressView().controlSize(.mini)
                        Text(task.kind == "tailor" ? t("Writing documents") : t("Evaluating"))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Spacer(minLength: 0)
            Text(Dates.relative(job.postedAt ?? job.firstSeen))
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 4)
    }
}

struct StatusMenuItems: View {
    @Environment(AppModel.self) private var model
    let jobID: String

    var body: some View {
        ForEach(model.summary?.statuses.filter { $0.id != "filtered" } ?? []) { s in
            Button(s.label) { Task { await model.setStatus(jobID, s.id) } }
        }
    }
}

struct ImportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var url = ""
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(t("Add a job by its link"), systemImage: "link.badge.plus").font(.headline)
            Text(t("Paste the address of a posting: LinkedIn, Indeed, StepStone, a company career page… JobRadar reads the posting and adds it to your inbox."))
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField("https://…", text: $url)
                .textFieldStyle(.roundedBorder)
                .onSubmit(add)
            HStack {
                if busy { ProgressView().controlSize(.small) }
                Spacer()
                Button(t("Cancel"), role: .cancel) { dismiss() }
                Button(t("Add"), action: add)
                    .buttonStyle(.glassProminent).accentFill()
                    .keyboardShortcut(.defaultAction)
                    .disabled(busy || !url.lowercased().hasPrefix("http"))
            }
        }
        .padding(20)
        .frame(width: 480)
        .onAppear { url = model.importDraft }
    }

    private func add() {
        guard !busy else { return }
        busy = true
        Task {
            let ok = await model.importURL(url.trimmingCharacters(in: .whitespacesAndNewlines))
            busy = false
            if ok { dismiss() }
        }
    }
}

/// Shown while the app installs or starts the engine on this Mac, or when that failed.
struct EngineStatusView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        switch model.localState {
        case .failed(let message):
            ContentUnavailableView {
                Label(t("The engine could not start"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
                    .textSelection(.enabled)
            } actions: {
                Button(t("Try again")) { Task { await model.startLocal() } }
                    .buttonStyle(.glassProminent).accentFill()
                Button(t("Show the log")) { LocalServer.shared.revealLog() }
                Button(t("Open Settings")) { openSettings() }
            }
        case .installing(let step):
            VStack(spacing: 14) {
                Image(systemName: "shippingbox")
                    .font(.system(size: 36))
                    .foregroundStyle(.tint)
                Text(t("Setting up the JobRadar engine")).font(.headline)
                if let step {
                    ProgressView(value: step.fraction)
                        .progressViewStyle(.linear)
                        .frame(maxWidth: 280)
                    Text(t("Step %@ of %@: %@", step.index, step.total, step.title))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else {
                    ProgressView()
                }
                Text(t("This happens once and needs an internet connection. It can take a few minutes."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        default:
            VStack(spacing: 12) {
                ProgressView()
                Text(t("Starting JobRadar…"))
                    .font(.headline)
                Text(t("The first start takes a few seconds."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
