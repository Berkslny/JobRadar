import AppKit
import Foundation
import Observation
import UserNotifications

enum SidebarItem: Hashable {
    case jobs(String)   // inbox, active, done, filtered, all
    case replies        // e-mail replies from companies
    case stats
    case profile
    case search
}

struct JobListKind: Identifiable {
    let id: String
    let icon: String

    var title: String {
        switch id {
        case "inbox": return t("Inbox")
        case "active": return t("In progress")
        case "done": return t("Closed")
        case "filtered": return t("Filtered out")
        default: return t("All")
        }
    }
}

/// State of the JobRadar engine that the app runs on this Mac.
enum LocalState: Equatable {
    case idle
    case installing(EngineStep?)
    case starting
    case running
    case failed(String)
}

/// Result of a scan the app followed, shown under the progress bar for a while.
struct CycleResult: Equatable {
    let id = UUID()
    var ok: Bool
    var text: String
}

let jobListKinds: [JobListKind] = [
    JobListKind(id: "inbox", icon: "tray.full"),
    JobListKind(id: "active", icon: "paperplane"),
    JobListKind(id: "done", icon: "checkmark.seal"),
    JobListKind(id: "filtered", icon: "line.3.horizontal.decrease.circle"),
    JobListKind(id: "all", icon: "square.stack.3d.up"),
]

@MainActor
@Observable
final class AppModel {
    var config: ServerConfig
    var summary: ServerSummary? = nil
    var stats: StatsResponse? = nil
    var jobs: [JobSummary] = []
    /// Size of the current view on the server; the list loads it 1000 at a time.
    var jobsTotal = 0
    var isLoadingMore = false
    static let pageSize = 1000
    var sidebar: SidebarItem? = .jobs("inbox")
    var selectedJobID: String? = nil
    var detail: JobDetail? = nil
    var track = ""
    var search = ""
    var order = "score"
    var isLoading = false
    var isLoadingDetail = false
    var errorMessage: String? = nil
    var runningTasks: [String: TaskInfo] = [:]
    var lastRefresh: Date? = nil
    var lastBackup: Date? = nil
    var lastBackupFile: URL? = nil
    var backupError: String? = nil
    var newStrongJobs: [JobSummary] = []
    var mailSignals: [MailSignal] = []
    var mailLastSync = ""
    var mailError = ""
    var mailSyncRunning = false
    var pickerJobs: [JobSummary] = []
    var gaps: GapsResponse? = nil
    var localState: LocalState = .idle
    /// True while a scan runs on the server; the progress bar is shown.
    var cycleRunning = false
    var cycleProgress: CycleProgress? = nil
    var cycleResult: CycleResult? = nil
    /// What is still missing before the first scan (profile, AI model, search).
    var setup: SetupState? = nil
    /// The first-run assistant is on screen.
    var showOnboarding = false
    /// Page of the assistant (kept here so it survives a change of language).
    var onboardingStep = 0
    /// The job board connectors are being added in the background.
    var jobBoardsInstalling = false
    var jobBoardsError = ""
    /// The runtime of the built-in embedding model (smart matching) is being added.
    var matchingInstalling = false
    var matchingError = ""
    /// Measurements on the user's own verdicts; nil until loaded or when the engine has none.
    var bench: BenchReport? = nil
    /// Sheet for adding a posting by its link; the link may come from the browser button.
    /// The app shows made-up sample data from its own folder; the user's data is not touched.
    var sampleData = false
    /// Why the last connection test of the AI model failed; empty when it worked or was not run.
    var aiTestError = ""
    /// Bringing data over from an earlier JobRadar folder: progress, result, and whether it was done.
    var earlierImportRunning = false
    var earlierImportFailed = false
    var earlierImportMessage = ""
    var earlierImported = UserDefaults.standard.bool(forKey: Prefs.earlierDataImported)
    var showImport = false
    var importDraft = ""
    var notificationsEnabled: Bool {
        didSet { UserDefaults.standard.set(notificationsEnabled, forKey: Prefs.notifications) }
    }
    /// Local mode: run a full scan at these times while the app is open (a missed one runs on wake).
    var autoScan: Bool {
        didSet { UserDefaults.standard.set(autoScan, forKey: Prefs.autoScan) }
    }
    static let autoScanTimes: [(hour: Int, minute: Int)] = [(8, 0), (13, 0), (19, 0)]

    let api: APIClient
    @ObservationIgnored private var pollTask: Task<Void, Never>? = nil
    @ObservationIgnored private var cycleWatch: Task<Void, Never>? = nil
    @ObservationIgnored private var cycleWatchToken = 0
    @ObservationIgnored private var probeTask: Task<Void, Never>? = nil
    /// Set when the app itself switches the sidebar and wants to keep the selected job.
    @ObservationIgnored var keepSelectionOnSidebarChange = false

    init() {
        let cfg = ConfigStore.load()
        config = cfg
        api = APIClient(config: AppModel.effectiveConfig(for: cfg))
        lastBackup = UserDefaults.standard.object(forKey: "lastBackup") as? Date
        notificationsEnabled = UserDefaults.standard.object(forKey: Prefs.notifications) as? Bool ?? true
        autoScan = UserDefaults.standard.object(forKey: Prefs.autoScan) as? Bool ?? true
        lastBackupFile = Backups.files().last
        // a new user sees the assistant at once, while the engine installs in the background
        showOnboarding = cfg.mode == .local && !UserDefaults.standard.bool(forKey: Prefs.onboardingDone)
            && !EngineRuntime.isCurrent()
        startPolling()
        LanguageStore.shared.onChange = { [weak self] in
            Task { await self?.languageChanged() }
        }
        guard ProcessInfo.processInfo.environment["XCODE_RUNNING_FOR_PREVIEWS"] != "1" else { return }
        Task {
            // only one copy may run the engine: an older one (Applications or Xcode) closes first
            await AppInstaller.closeOtherInstances()
            if cfg.mode == .local {
                await self.startLocal()
            } else {
                await self.refreshAll()
                await self.loadSetup(offerOnboarding: true)
            }
        }
    }

    /// The configuration the API client uses: in local mode the engine on this Mac.
    static func effectiveConfig(for c: ServerConfig) -> ServerConfig {
        guard c.mode == .local else { return c }
        var e = c
        e.baseURL = LocalServer.shared.baseURL
        e.token = LocalServer.shared.token
        e.accessClientID = ""
        e.accessClientSecret = ""
        return e
    }

    /// True when requests can go out: a complete remote setup, or the local engine is up.
    var connectionReady: Bool {
        config.mode == .remote ? config.isComplete : localState == .running
    }

    var localStatusText: String {
        switch localState {
        case .idle: return config.mode == .local ? t("Waiting") : t("Off (a remote server is used)")
        case .installing(let step): return step.map { t("Installing: %@", $0.title) } ?? t("Preparing…")
        case .starting: return t("Starting…")
        case .running: return t("Running")
        case .failed(let message): return t("Error: %@", message)
        }
    }

    // MARK: Local engine

    /// Secrets the engine reads from its environment; they are kept in the Keychain, never in a file.
    private func engineEnvironment() -> [String: String] {
        let defaults = UserDefaults.standard
        return [
            "ANTHROPIC_API_KEY": Keychain.get(Secret.anthropicKey),
            "OPENAI_API_KEY": Keychain.get(Secret.openAIKey),
            "SMTP_USER": defaults.string(forKey: Prefs.mailUser) ?? "",
            "SMTP_PASSWORD": Keychain.get(Secret.mailPassword),
            "MAIL_TO": defaults.string(forKey: Prefs.mailTo) ?? "",
        ]
    }

    /// Installs the engine if needed (first start, or after an app update), then starts it.
    func startLocal() async {
        guard config.mode == .local else { return }
        if case .installing = localState { return }
        if localState == .starting { return }
        localState = .installing(nil)
        do {
            try await EngineRuntime.ensureInstalled(includeJobBoards: false) { [weak self] step in
                self?.localState = .installing(step)
            }
            localState = .starting
            let server = LocalServer.shared
            server.workspace = sampleData ? EnginePaths.sampleWorkspace : URL(fileURLWithPath: config.localFolder)
            server.sampleData = sampleData
            try await server.start(environment: engineEnvironment())
            api.config = Self.effectiveConfig(for: config)
            localState = .running
            await loadSetup(offerOnboarding: !sampleData)
            await refreshAll()
            Task {
                await self.installJobBoards()
                await self.installMatchingIfNeeded()
            }
            await autoScanIfDue()
        } catch {
            localState = .failed(error.localizedDescription)
        }
    }

    func restartLocal() async {
        guard config.mode == .local else { return }
        resetCycle()
        LocalServer.shared.stop()
        localState = .idle
        await startLocal()
    }

    /// Shows the sample data, or goes back to the user's own folder. The engine restarts on the other folder.
    func showSampleData(_ on: Bool) async {
        guard config.mode == .local, sampleData != on else { return }
        if case .installing = localState { return }
        sampleData = on
        if on { showOnboarding = false }
        jobs = []
        jobsTotal = 0
        detail = nil
        selectedJobID = nil
        summary = nil
        stats = nil
        bench = nil
        setup = nil
        sidebar = .jobs("inbox")
        await restartLocal()
    }

    /// The offer is shown while the earlier folder exists, is not the folder in use, and was not brought over.
    var offersEarlierData: Bool {
        config.mode == .local && !sampleData && !earlierImported && EarlierData.found
            && config.localFolder != EarlierData.folder.path
    }

    /// Copies the data of an earlier JobRadar into JobRadar's own folder and continues there. The earlier
    /// folder is not changed. What was in JobRadar's own folder is removed when it was still empty, and put
    /// aside otherwise.
    func importEarlierData() async {
        guard config.mode == .local, !sampleData, !earlierImportRunning else { return }
        if case .installing = localState { return }
        earlierImportRunning = true
        earlierImportFailed = false
        earlierImportMessage = t("Bringing your data over…")
        defer { earlierImportRunning = false }
        let source = EarlierData.folder
        let target = EnginePaths.defaultWorkspace
        let usingStandard = config.localFolder == target.path
        let emptyNow = usingStandard && localState == .running && setup?.profile.exists == false
            && (summary?.views["all"] ?? 0) == 0
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let aside = EnginePaths.support.appendingPathComponent("workspace-" + formatter.string(from: Date()),
                                                               isDirectory: true)
        resetCycle()
        LocalServer.shared.stop(waitUpTo: 5)
        localState = .idle
        let result = await Task.detached { () -> (problem: String?, kept: Bool, timer: Bool) in
            let fm = FileManager.default
            var kept = false
            do {
                if fm.fileExists(atPath: target.path) {
                    if emptyNow {
                        try fm.removeItem(at: target)
                    } else {
                        try fm.moveItem(at: target, to: aside)
                        kept = true
                    }
                }
                try EarlierData.copy(from: source, to: target)
            } catch {
                // put back what was there
                if kept, !fm.fileExists(atPath: target.path) { try? fm.moveItem(at: aside, to: target) }
                return (error.localizedDescription, false, false)
            }
            return (nil, kept, EarlierData.removeTimer())
        }.value
        if let problem = result.problem {
            earlierImportFailed = true
            earlierImportMessage = t("The data could not be brought over: %@", problem)
            await startLocal()
            return
        }
        UserDefaults.standard.set(true, forKey: Prefs.earlierDataImported)
        earlierImported = true
        var next = config
        next.localFolder = target.path
        ConfigStore.save(next)
        config = ConfigStore.load()
        jobs = []
        jobsTotal = 0
        detail = nil
        selectedJobID = nil
        summary = nil
        setup = nil
        await startLocal()
        var text = t("Your data was brought over.")
        if result.timer { text += " " + t("The earlier daily timer was removed.") }
        if result.kept { text += " " + t("What was here before is kept in %@.", aside.lastPathComponent) }
        earlierImportMessage = text
        if setup?.ready == true && showOnboarding { finishOnboarding() }
    }

    /// Deletes Python and the engine and installs them again; the user's data is not touched.
    func reinstallEngine() async {
        guard config.mode == .local else { return }
        resetCycle()
        LocalServer.shared.stop(waitUpTo: 3)
        EngineRuntime.removeRuntime()
        localState = .idle
        await startLocal()
    }

    /// Adds the job board connectors (LinkedIn, Indeed, Google Jobs) after the engine is up.
    func installJobBoards(force: Bool = false) async {
        guard config.mode == .local, !jobBoardsInstalling else { return }
        if EngineRuntime.jobBoardsInstalled {
            jobBoardsError = ""
            return
        }
        let marker = EngineMarker.read()
        if !force && !marker.jobBoardsError.isEmpty {
            // it failed before: show why and wait for the user to try again
            jobBoardsError = marker.jobBoardsError
            return
        }
        jobBoardsInstalling = true
        defer { jobBoardsInstalling = false }
        try? await EngineRuntime.ensureInstalled(includeJobBoards: true) { _ in }
        jobBoardsError = EngineMarker.read().jobBoardsError
    }

    /// Adds the runtime of the built-in embedding model when smart matching is on and the engine misses it
    /// (first use, or after the engine was installed again).
    func installMatchingIfNeeded(force: Bool = false) async {
        guard config.mode == .local, !sampleData, connectionReady, !matchingInstalling else { return }
        guard let state = try? await api.matching(), state.enabled, state.provider == "fastembed",
              !state.installed else {
            matchingError = ""
            return
        }
        var marker = EngineMarker.read()
        if !force && !marker.matchingError.isEmpty {
            // it failed before: show why and wait for the user to try again
            matchingError = marker.matchingError
            return
        }
        matchingInstalling = true
        defer { matchingInstalling = false }
        // one installation at a time in the engine's Python environment
        while jobBoardsInstalling {
            try? await Task.sleep(for: .milliseconds(500))
        }
        // the engine says the package is missing, whatever was noted earlier
        marker.matching = false
        marker.matchingError = ""
        marker.write()
        try? await EngineRuntime.ensureInstalled(includeJobBoards: false, includeMatching: true) { _ in }
        matchingError = EngineMarker.read().matchingError
    }

    /// Starts today's due full scan once (local mode, automatic scans on, setup complete).
    func autoScanIfDue() async {
        guard !sampleData else { return }
        guard config.mode == .local, autoScan, connectionReady, let s = summary, !s.running else { return }
        guard setup?.ready != false, !showOnboarding else { return }
        let now = Date()
        let calendar = Calendar.current
        let slots = Self.autoScanTimes.compactMap {
            calendar.date(bySettingHour: $0.hour, minute: $0.minute, second: 0, of: now)
        }
        guard let due = slots.filter({ $0 <= now }).max() else { return }
        let defaults = UserDefaults.standard
        let last = defaults.object(forKey: "lastAutoScan") as? Date ?? .distantPast
        guard last < due else { return }
        defaults.set(now, forKey: "lastAutoScan")
        if let lastCycle = Dates.parse(s.lastCycle), lastCycle >= due { return }
        await runCycle()
    }

    var currentView: String {
        if case .jobs(let v) = sidebar { return v }
        return "inbox"
    }

    var strongCount: Int { summary?.strongOpen ?? 0 }

    var pendingReplies: Int { summary?.mailSignalsPending ?? 0 }

    // MARK: Setup

    /// Reads what is still missing. `offerOnboarding`: open the assistant when the user never finished it.
    func loadSetup(offerOnboarding: Bool = false) async {
        guard connectionReady else { return }
        guard let state = try? await api.setup() else {
            setup = nil   // an older server without the setup pages
            return
        }
        setup = state
        if offerOnboarding && !state.ready && !UserDefaults.standard.bool(forKey: Prefs.onboardingDone) {
            showOnboarding = true
        }
        // the engine on this Mac writes its own texts (filter reasons, e-mails) in the app's language
        if config.mode == .local && state.language != LanguageStore.shared.code {
            _ = try? await api.saveAppSettings(AppSettingsBody(language: LanguageStore.shared.code))
        }
    }

    func finishOnboarding() {
        UserDefaults.standard.set(true, forKey: Prefs.onboardingDone)
        showOnboarding = false
        Task {
            await loadSetup()
            await refreshAll()
        }
    }

    /// Starts the assistant again. It stays pending (also after a restart) until it is finished or skipped.
    func reopenOnboarding() {
        UserDefaults.standard.set(false, forKey: Prefs.onboardingDone)
        onboardingStep = 0
        showOnboarding = true
    }

    /// Tells the engine the interface language, so its texts (labels, e-mails, new evaluations) follow.
    func languageChanged() async {
        guard connectionReady else { return }
        _ = try? await api.saveAppSettings(AppSettingsBody(language: LanguageStore.shared.code))
        await refreshAll()
    }

    /// Waits for a background task of the engine. Throws when the request fails; a failed task is
    /// returned with `status == "error"`.
    func wait(_ start: TaskInfo, every seconds: Double = 1.5) async throws -> TaskInfo {
        var task = start
        while task.isRunning {
            try await Task.sleep(for: .seconds(seconds))
            task = try await api.task(task.id)
        }
        return task
    }

    // MARK: Loading

    func refreshAll() async {
        guard connectionReady else { return }
        await refreshSummary()
        switch sidebar {
        case .stats:
            await loadStats()
            await loadGaps()
            await loadBench()
        case .replies:
            await loadMailSignals()
        case .profile, .search:
            break
        default:
            await reloadJobs()
        }
        if let id = selectedJobID { await loadDetail(id) }
    }

    func refreshSummary() async {
        guard connectionReady else { return }
        do {
            summary = try await api.summary()
            errorMessage = nil
            if summary?.running == true { followRunningCycle(summary?.progress) }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reloadJobs() async {
        guard connectionReady else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let res = try await api.jobsPage(view: currentView, track: track, query: search, order: order,
                                              limit: max(Self.pageSize, jobs.count))
            jobs = res.jobs
            jobsTotal = max(res.total ?? res.jobs.count, res.jobs.count)
            lastRefresh = Date()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Appends the next 1000 postings of the current view.
    func loadMoreJobs() async {
        guard connectionReady, !isLoadingMore, jobs.count < jobsTotal else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let res = try await api.jobsPage(view: currentView, track: track, query: search, order: order,
                                              limit: Self.pageSize, offset: jobs.count)
            let known = Set(jobs.map(\.id))
            let fresh = res.jobs.filter { !known.contains($0.id) }
            jobs += fresh
            // an older server ignores offset and sends the first page again: nothing more to show then
            jobsTotal = fresh.isEmpty ? jobs.count : max(res.total ?? jobsTotal, jobs.count)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadDetail(_ id: String?) async {
        guard let id else {
            detail = nil
            return
        }
        isLoadingDetail = true
        defer { isLoadingDetail = false }
        do {
            let d = try await api.job(id)
            if selectedJobID == id { detail = d }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadStats() async {
        do {
            stats = try await api.stats()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadGaps() async {
        do {
            gaps = try await api.gaps()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Measurements on the user's own verdicts. An older engine has none: the section stays hidden then.
    func loadBench() async {
        guard connectionReady else { return }
        bench = try? await api.bench()
    }

    /// Stores the user's verdict on a posting ("good", "maybe", "bad", "skip"; "" takes it back).
    func setLabel(_ jobID: String, _ label: String) async {
        do {
            try await api.setLabel(jobID, label: label)
            if selectedJobID == jobID { await loadDetail(jobID) }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: E-mail replies

    func loadMailSignals() async {
        guard connectionReady else { return }
        do {
            let res = try await api.mailSignals(state: "all")
            mailSignals = res.signals
            mailLastSync = res.lastSync
            mailError = res.lastError
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Jobs to choose from when a reply could not be matched automatically.
    func loadPickerJobs() async {
        guard connectionReady else { return }
        if let list = try? await api.jobs(view: "active", track: "", query: "", order: "date") {
            pickerJobs = list
        }
    }

    func syncMail() async {
        guard !mailSyncRunning else { return }
        mailSyncRunning = true
        defer { mailSyncRunning = false }
        do {
            let task = try await wait(try await api.mailSync(), every: 2)
            if task.status == "error" {
                errorMessage = task.message.isEmpty ? t("The e-mails could not be read.") : task.message
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        await loadMailSignals()
        await refreshSummary()
    }

    func applySignal(_ signal: MailSignal, jobID: String? = nil) async {
        do {
            let res = try await api.applySignal(signal.id, jobID: jobID)
            await loadMailSignals()
            await refreshSummary()
            if selectedJobID == res.jobId { await loadDetail(res.jobId) }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func dismissSignal(_ signal: MailSignal) async {
        do {
            try await api.dismissSignal(signal.id)
            await loadMailSignals()
            await refreshSummary()
            if let id = selectedJobID, id == signal.jobId { await loadDetail(id) }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Shows a job in the detail column without leaving the replies list.
    func showFromReplies(jobID: String) async {
        selectedJobID = jobID
        await loadDetail(jobID)
    }

    // MARK: Actions

    func setStatus(_ jobID: String, _ status: String) async {
        do {
            let updated = try await api.setStatus(jobID, status: status)
            if let i = jobs.firstIndex(where: { $0.id == jobID }) { jobs[i] = updated }
            if selectedJobID == jobID { await loadDetail(jobID) }
            await refreshSummary()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func saveNotes(_ jobID: String, _ notes: String) async {
        do {
            try await api.setNotes(jobID, notes: notes)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func evaluate(_ jobID: String) async {
        do {
            let task = try await api.evaluate(jobID)
            await follow(task, jobID: jobID)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func tailor(_ jobID: String, language: String) async {
        do {
            let task = try await api.tailor(jobID, language: language)
            await follow(task, jobID: jobID)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Polls a background task on the server until it finishes, then refreshes.
    private func follow(_ start: TaskInfo, jobID: String) async {
        var task = start
        runningTasks[jobID] = task
        defer { runningTasks[jobID] = nil }
        do {
            while task.isRunning {
                try await Task.sleep(for: .seconds(3))
                task = try await api.task(task.id)
                runningTasks[jobID] = task
            }
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        if task.status == "error" {
            errorMessage = task.message.isEmpty ? t("That did not work.") : task.message
        }
        await reloadJobs()
        if selectedJobID == jobID { await loadDetail(jobID) }
        await refreshSummary()
    }

    func approve(docID: Int, jobID: String) async {
        do {
            try await api.approve(docID: docID)
            await loadDetail(jobID)
            await reloadJobs()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Starts a full scan on the server and follows it with the progress bar.
    /// If a scan is already running, the bar follows that one.
    func runCycle() async {
        guard !sampleData else { return }
        do {
            let res = try await api.run()
            cycleResult = nil
            // started == false: a scan was already running; the first poll shows where it is
            cycleProgress = res.started ? CycleProgress(stage: "queued", label: t("Starting"), fraction: 0) : nil
            setCycleRunning(true)
            watchCycle()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Shows the bar for a scan the app did not start itself (web panel, timer, menu).
    private func followRunningCycle(_ progress: CycleProgress?) {
        guard cycleWatch == nil else { return }
        cycleProgress = progress?.stage != nil ? progress : nil
        cycleResult = nil
        setCycleRunning(true)
        watchCycle()
    }

    private func setCycleRunning(_ running: Bool) {
        cycleRunning = running
        LocalServer.shared.scanInProgress = running
    }

    /// Stops following (server changed); the next refresh picks up a running scan again.
    private func resetCycle() {
        cycleWatch?.cancel()
        cycleWatch = nil
        cycleWatchToken += 1
        setCycleRunning(false)
        cycleProgress = nil
        cycleResult = nil
    }

    private func watchCycle() {
        cycleWatch?.cancel()
        cycleWatchToken += 1
        let token = cycleWatchToken
        cycleWatch = Task { [weak self] in
            await self?.followCycle()
            guard let self, self.cycleWatchToken == token else { return }
            self.cycleWatch = nil
        }
    }

    /// Polls the progress every 2 seconds. Badges refresh every ~20 seconds, the list when a stage
    /// ends (new postings after the scan stage) and everything when the scan ends.
    private func followCycle() async {
        var ticks = 0
        var misses = 0
        var stage = cycleProgress?.stage
        while !Task.isCancelled {
            var running = true
            var latest: CycleProgress? = nil
            if let p = try? await api.progress() {
                running = p.running
                latest = p.progress
                misses = 0
            } else if let s = try? await api.summary() {  // server without the progress endpoint
                summary = s
                running = s.running
                latest = s.progress
                misses = 0
            } else {
                misses += 1
                if misses >= 6 {  // about 12 seconds without an answer: stop; the next refresh resumes
                    setCycleRunning(false)
                    return
                }
            }
            if Task.isCancelled { return }
            if let latest, latest.stage != nil { cycleProgress = latest }
            if !running {
                await cycleEnded()
                return
            }
            if cycleProgress?.stage != stage {
                stage = cycleProgress?.stage
                await reloadJobsQuietly()
            }
            ticks += 1
            if ticks % 10 == 0, let s = try? await api.summary() { summary = s }
            try? await Task.sleep(for: .seconds(2))
        }
    }

    private func cycleEnded() async {
        setCycleRunning(false)
        await refreshSummary()
        let p = cycleProgress
        let detail = p?.detail ?? ""
        switch p?.stage ?? "" {
        case "done":
            cycleResult = CycleResult(ok: true, text: detail.isEmpty ? t("The scan is finished.")
                                                                     : t("The scan is finished: %@", detail))
        case "failed":
            cycleResult = CycleResult(ok: false, text: t("The scan ended with an error: %@", detail))
        default:
            let error = summary?.lastError ?? ""
            cycleResult = CycleResult(ok: false, text: error.isEmpty ? t("The scan was interrupted.")
                                                                     : t("The scan could not finish: %@", error))
        }
        await reloadJobs()
        await checkNewStrongJobs()
        let shown = cycleResult
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(90))
            guard let self, self.cycleResult == shown, !self.cycleRunning else { return }
            self.cycleResult = nil
        }
    }

    /// Reloads the list without a spinner or an error alert (used while a scan runs).
    private func reloadJobsQuietly() async {
        guard connectionReady, case .jobs = sidebar else { return }
        if let res = try? await api.jobsPage(view: currentView, track: track, query: search, order: order,
                                              limit: max(Self.pageSize, jobs.count)) {
            jobs = res.jobs
            jobsTotal = max(res.total ?? res.jobs.count, res.jobs.count)
            lastRefresh = Date()
        }
    }

    /// Notices a scan started elsewhere (web panel, server timer) within half a minute.
    private func probeCycle() async {
        guard connectionReady, cycleWatch == nil else { return }
        guard let p = try? await api.progress(), p.running else { return }
        followRunningCycle(p.progress)
    }

    /// Opens a job from outside the list (menu bar, notification, link).
    func show(jobID: String) async {
        if sidebar != .jobs("inbox") {
            keepSelectionOnSidebarChange = true
            sidebar = .jobs("inbox")
            await reloadJobs()
        }
        selectedJobID = jobID
        await loadDetail(jobID)
    }

    func importURL(_ url: String) async -> Bool {
        do {
            let res = try await api.importURL(url)
            if sidebar != .jobs("inbox") {
                keepSelectionOnSidebarChange = true
                sidebar = .jobs("inbox")
            }
            await reloadJobs()
            if let id = res.jobId {
                selectedJobID = id
                await loadDetail(id)
            }
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    /// Links that open the app: jobradar://job/<id>, jobradar://add?url=<posting>, jobradar://open.
    func handle(url: URL) {
        guard url.scheme?.lowercased() == "jobradar" else { return }
        NSApplication.shared.activate()
        switch url.host(percentEncoded: false)?.lowercased() ?? "" {
        case "job":
            let id = url.lastPathComponent
            guard !id.isEmpty, id != "/" else { return }
            Task { await show(jobID: id) }
        case "add":
            let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let link = items.first { $0.name == "url" }?.value ?? ""
            guard link.lowercased().hasPrefix("http") else { return }
            importDraft = link
            showImport = true
        default:
            break
        }
    }

    func saveConfig(_ c: ServerConfig) async {
        let previous = config
        let wasSample = sampleData   // leaving the sample data always restarts the engine
        sampleData = false
        ConfigStore.save(c)
        config = ConfigStore.load()
        resetCycle()
        jobs = []
        detail = nil
        selectedJobID = nil
        summary = nil
        bench = nil       // measurements of the engine used until now
        setup = nil
        if config.mode == .local {
            if !wasSample && previous.mode == .local && previous.localFolder == config.localFolder
                && localState == .running {
                await refreshAll()
                return
            }
            // an installation in progress finishes first and then starts the engine with the new folder
            if case .installing = localState { return }
            while localState == .starting {
                try? await Task.sleep(for: .milliseconds(300))
            }
            LocalServer.shared.stop()
            localState = .idle
            await startLocal()
        } else {
            if previous.mode == .local {
                LocalServer.shared.stop()
            }
            localState = .idle
            api.config = config
            await refreshAll()
            await loadSetup(offerOnboarding: true)
        }
    }

    /// Checks a configuration without saving it.
    func testConnection(_ c: ServerConfig) async -> String {
        let probe = APIClient(config: c)
        do {
            let h = try await probe.health()
            let s = try await probe.summary()
            return t("Connected. Server %@, %@ jobs in the inbox, AI model: %@.", h.version, s.views["inbox"] ?? 0, s.llm)
        } catch {
            return error.localizedDescription
        }
    }

    // MARK: Background: polling, notifications, backups

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(5))
            while !Task.isCancelled {
                guard let self else { return }
                await self.backgroundTick()
                try? await Task.sleep(for: .seconds(15 * 60))
            }
        }
        probeTask?.cancel()
        probeTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                guard let self else { return }
                await self.probeCycle()
            }
        }
    }

    func backgroundTick() async {
        if config.mode == .local, case .failed = localState {
            await startLocal()
        }
        guard connectionReady else { return }
        await refreshSummary()
        guard !sampleData else { return }   // sample data: no scans, notifications or backups
        await autoScanIfDue()
        await checkNewStrongJobs()
        await checkNewReplies()
        await backupIfNeeded()
    }

    /// One Mac notification for company replies that wait for a decision and were not shown before.
    func checkNewReplies() async {
        guard connectionReady, pendingReplies > 0 else { return }
        guard let res = try? await api.mailSignals(state: "pending") else { return }
        let defaults = UserDefaults.standard
        let firstRun = defaults.object(forKey: "seenReplyIDs") == nil
        var seen = Set(defaults.array(forKey: "seenReplyIDs") as? [Int] ?? [])
        let fresh = res.signals.filter { !seen.contains($0.id) }
        if sidebar == .replies { await loadMailSignals() }
        guard !fresh.isEmpty else { return }
        seen.formUnion(fresh.map(\.id))
        defaults.set(Array(seen), forKey: "seenReplyIDs")
        if !firstRun && notificationsEnabled {
            let title = fresh.count == 1 ? t("JobRadar: a company replied")
                                         : t("JobRadar: %@ company replies", fresh.count)
            let body = fresh.prefix(3).map { "\($0.kindLabel): \($0.subject)" }.joined(separator: "\n")
            Notifier.post(title: title, body: body)
        }
    }

    /// Finds strong jobs that this Mac has not seen yet and posts one notification for them.
    func checkNewStrongJobs() async {
        guard connectionReady, let threshold = summary?.strongThreshold else { return }
        let all: [JobSummary]
        do {
            all = try await api.jobs(view: "inbox", track: "", query: "", order: "score")
        } catch {
            return
        }
        let strong = all.filter { ($0.llmScore ?? 0) >= threshold }
        let defaults = UserDefaults.standard
        let firstRun = defaults.object(forKey: "seenStrongIDs") == nil
        var seen = Set(defaults.stringArray(forKey: "seenStrongIDs") ?? [])
        let fresh = strong.filter { !seen.contains($0.id) }
        newStrongJobs = Array(strong.prefix(8))
        guard !fresh.isEmpty else { return }
        seen.formUnion(fresh.map(\.id))
        defaults.set(Array(seen), forKey: "seenStrongIDs")
        if !firstRun && notificationsEnabled {
            let title = fresh.count == 1 ? t("JobRadar: a new strong match")
                                         : t("JobRadar: %@ new strong matches", fresh.count)
            let body = fresh.prefix(3).map { "\($0.title) · \($0.company)" }.joined(separator: "\n")
            Notifier.post(title: title, body: body)
        }
    }

    func backupIfNeeded(force: Bool = false) async {
        guard connectionReady, !sampleData else { return }
        if !force, let last = lastBackup, Calendar.current.isDateInToday(last) { return }
        do {
            let file = try await api.backup(into: Backups.folder)
            Backups.prune(keep: 14)
            lastBackup = Date()
            lastBackupFile = file
            backupError = nil
            UserDefaults.standard.set(lastBackup, forKey: "lastBackup")
        } catch {
            backupError = error.localizedDescription
        }
    }

    func revealBackups() {
        if let file = lastBackupFile {
            NSWorkspace.shared.activateFileViewerSelecting([file])
        } else {
            try? FileManager.default.createDirectory(at: Backups.folder, withIntermediateDirectories: true)
            NSWorkspace.shared.open(Backups.folder)
        }
    }
}

@MainActor
enum Notifier {
    static func requestPermission() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
    }

    static func post(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request, withCompletionHandler: nil)
    }
}
