import AppKit
import ServiceManagement
import SwiftUI

struct SettingsView: View {
    @AppStorage("settingsTab") private var tab = "general"

    var body: some View {
        TabView(selection: $tab) {
            GeneralSettings()
                .tabItem { Label(t("General"), systemImage: "gearshape") }
                .tag("general")
            SettingsPage {
                AIModelForm()
            }
            .tabItem { Label(t("AI model"), systemImage: "sparkles") }
            .tag("ai")
            MatchingSettings()
                .tabItem { Label(t("Matching"), systemImage: "wand.and.stars") }
                .tag("matching")
            MailSettingsView()
                .tabItem { Label(t("E-mail"), systemImage: "envelope") }
                .tag("mail")
            EngineSettings()
                .tabItem { Label(t("Engine and data"), systemImage: "shippingbox") }
                .tag("engine")
            AdvancedSettings()
                .tabItem { Label(t("Advanced"), systemImage: "wrench.and.screwdriver") }
                .tag("advanced")
        }
        .frame(width: 700, height: 640)
    }
}

/// A scrolling settings page whose content is not a form.
struct SettingsPage<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            content
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: General

struct GeneralSettings: View {
    @Environment(AppModel.self) private var model
    @State private var settings: AppSettings? = nil
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @State private var loginError = ""

    var body: some View {
        @Bindable var model = model
        @Bindable var theme = ThemeStore.shared
        @Bindable var language = LanguageStore.shared
        Form {
            Section(t("Language")) {
                Picker(t("Interface language"), selection: $language.choice) {
                    ForEach(AppLanguage.allCases) { option in
                        Text(language.title(option)).tag(option)
                    }
                }
                if let settings {
                    Picker(t("Evaluations are written in"), selection: outputBinding(settings)) {
                        Text(t("The interface language")).tag("auto")
                        ForEach(languageOptions(including: settings.outputLanguage), id: \.self) { code in
                            Text(languageName(code)).tag(code)
                        }
                    }
                    Picker(t("CV and letter, when a posting's language is unclear"), selection: documentBinding(settings)) {
                        Text(t("By country (%@)", languageName(settings.documentLanguageEffective))).tag("")
                        ForEach(languageOptions(including: settings.documentLanguage), id: \.self) { code in
                            Text(languageName(code)).tag(code)
                        }
                    }
                    Text(t("A CV and letter are normally written in the language of the posting."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Section(t("Appearance")) {
                Picker(t("Mode"), selection: $theme.appearance) {
                    ForEach(AppearanceChoice.allCases) { choice in
                        Label(choice.title, systemImage: choice.icon).tag(choice)
                    }
                }
                .pickerStyle(.segmented).accentFill()
                LabeledContent(t("Colours")) {
                    HStack(spacing: 10) {
                        ForEach(ThemePalette.all) { palette in
                            PaletteSwatch(palette: palette, selected: theme.paletteID == palette.id) {
                                theme.paletteID = palette.id
                            }
                        }
                    }
                }
                Picker(t("Content boxes"), selection: $theme.cardStyle) {
                    ForEach(CardStyle.allCases) { style in
                        Text(style.title).tag(style)
                    }
                }
                Toggle(t("Let the desktop shine through the window"), isOn: $theme.seeThrough)
            }
            Section(t("Behaviour")) {
                Toggle(t("Notify me about strong matches and company replies"), isOn: $model.notificationsEnabled)
                    .onChange(of: model.notificationsEnabled) {
                        if model.notificationsEnabled { Task { await Notifier.requestPermission() } }
                    }
                Toggle(t("Scan automatically at 08:00, 13:00 and 19:00"), isOn: $model.autoScan)
                Text(t("Scans run while the app is open (it can stay in the menu bar). A scan missed during sleep runs once after waking."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Toggle(t("Open JobRadar when I log in"), isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { setLaunchAtLogin() }
                if !loginError.isEmpty {
                    Text(loginError).font(.caption).foregroundStyle(.red)
                }
                if let settings {
                    Stepper(t("Remind me to follow up %@ days after applying", settings.followUpDays),
                            value: followUpBinding(settings), in: 1...90)
                }
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .task { await load() }
    }

    private func languageOptions(including code: String) -> [String] {
        let clean = code.lowercased()
        if clean.isEmpty || clean == "auto" || commonLanguageCodes.contains(clean) { return commonLanguageCodes }
        return commonLanguageCodes + [clean]
    }

    private func outputBinding(_ current: AppSettings) -> Binding<String> {
        Binding(get: { current.outputLanguage.isEmpty ? "auto" : current.outputLanguage },
                set: { value in save(AppSettingsBody(outputLanguage: value)) })
    }

    private func documentBinding(_ current: AppSettings) -> Binding<String> {
        Binding(get: { current.documentLanguage },
                set: { value in save(AppSettingsBody(documentLanguage: value)) })
    }

    private func followUpBinding(_ current: AppSettings) -> Binding<Int> {
        Binding(get: { current.followUpDays },
                set: { value in save(AppSettingsBody(followUpDays: value)) })
    }

    private func load() async {
        guard model.connectionReady else { return }
        settings = try? await model.api.appSettings()
    }

    private func save(_ body: AppSettingsBody) {
        Task {
            do {
                settings = try await model.api.saveAppSettings(body)
            } catch {
                model.errorMessage = error.localizedDescription
            }
        }
    }

    private func setLaunchAtLogin() {
        let service = SMAppService.mainApp
        let enabled = service.status == .enabled
        guard launchAtLogin != enabled else { return }
        do {
            if launchAtLogin {
                try service.register()
            } else {
                try service.unregister()
            }
            loginError = ""
        } catch {
            loginError = t("macOS did not accept that: %@", error.localizedDescription)
            launchAtLogin = enabled
        }
    }
}

struct PaletteSwatch: View {
    let palette: ThemePalette
    let selected: Bool
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Circle()
                .fill(AngularGradient(colors: palette.glow + [palette.glow[0]], center: .center))
                .frame(width: 26, height: 26)
                .overlay {
                    Circle().strokeBorder(Color.primary.opacity(selected ? 0.9 : 0.15), lineWidth: selected ? 2.5 : 1)
                }
                .padding(2)
        }
        .buttonStyle(.plain)
        .help(palette.title)
        .accessibilityLabel(palette.title)
    }
}

// MARK: E-mail

struct MailPreset: Identifiable {
    let id: String
    let name: String
    let smtpHost: String
    let smtpPort: Int
    let imapHost: String
    let imapPort: Int
    let passwordPage: String

    static let all: [MailPreset] = [
        MailPreset(id: "gmail", name: "Gmail", smtpHost: "smtp.gmail.com", smtpPort: 587,
                   imapHost: "imap.gmail.com", imapPort: 993, passwordPage: "https://myaccount.google.com/apppasswords"),
        MailPreset(id: "icloud", name: "iCloud Mail", smtpHost: "smtp.mail.me.com", smtpPort: 587,
                   imapHost: "imap.mail.me.com", imapPort: 993, passwordPage: "https://account.apple.com"),
        MailPreset(id: "yahoo", name: "Yahoo Mail", smtpHost: "smtp.mail.yahoo.com", smtpPort: 587,
                   imapHost: "imap.mail.yahoo.com", imapPort: 993,
                   passwordPage: "https://login.yahoo.com/account/security"),
    ]
}

struct MailSettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var loaded = false
    @State private var hasPassword = false
    @State private var user = ""
    @State private var password = ""
    @State private var to = ""
    @State private var smtpHost = "smtp.gmail.com"
    @State private var smtpPort = 587
    @State private var imapHost = "imap.gmail.com"
    @State private var imapPort = 993
    @State private var digest = true
    @State private var instant = true
    @State private var sync = true
    @State private var busy = false
    @State private var message = ""
    @State private var messageOK = true
    @State private var error = ""

    private var preset: MailPreset? {
        MailPreset.all.first { $0.smtpHost == smtpHost && $0.imapHost == imapHost }
    }

    var body: some View {
        Form {
            Section {
                Text(t("With a mailbox connected, JobRadar can send you a daily summary and an alert for strong matches, and it can spot replies from companies in your inbox. Your mailbox is only read, never changed."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Section(t("Mailbox")) {
                Picker(t("Provider"), selection: presetBinding) {
                    ForEach(MailPreset.all) { preset in
                        Text(preset.name).tag(preset.id)
                    }
                    Text(t("Other")).tag("custom")
                }
                TextField(t("E-mail address"), text: $user, prompt: Text(verbatim: "you@example.com"))
                SecureField(t("App password"), text: $password,
                            prompt: Text(hasPassword ? t("Saved. Type a new one to replace it.") : t("Not your normal password")))
                if let preset, let link = URL(string: preset.passwordPage) {
                    Link(t("Create an app password for %@", preset.name), destination: link)
                        .font(.callout)
                }
                Text(t("Gmail, iCloud and Yahoo need an app password, which you create in your account's security settings (two-step verification must be on). It is kept in your Mac's Keychain."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextField(t("Send summaries to"), text: $to, prompt: Text(t("The same address")))
            }
            if preset == nil {
                Section(t("Servers")) {
                    TextField(t("Outgoing server (SMTP)"), text: $smtpHost)
                    TextField(t("SMTP port"), value: $smtpPort, format: .number.grouping(.never))
                    TextField(t("Incoming server (IMAP)"), text: $imapHost)
                    TextField(t("IMAP port"), value: $imapPort, format: .number.grouping(.never))
                }
            }
            Section(t("What JobRadar does with it")) {
                Toggle(t("Send a daily summary of new matches"), isOn: $digest)
                Toggle(t("Send an alert at once for a strong match"), isOn: $instant)
                Toggle(t("Look for replies from companies in the inbox"), isOn: $sync)
            }
            Section {
                HStack(spacing: 10) {
                    Button(t("Save")) { Task { await save() } }
                        .buttonStyle(.glassProminent).accentFill()
                        .disabled(busy || !loaded)
                    Button(t("Save and send a test e-mail")) { Task { await test() } }
                        .disabled(busy || !loaded)
                    if hasPassword {
                        Button(t("Disconnect")) { Task { await disconnect() } }
                            .disabled(busy)
                    }
                    if busy { ProgressView().controlSize(.small) }
                }
                if !message.isEmpty { Banner(kind: messageOK ? .success : .warning, text: message) }
                if !error.isEmpty { Banner(kind: .error, text: error) }
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .task { await load() }
    }

    private var presetBinding: Binding<String> {
        Binding(
            get: { preset?.id ?? "custom" },
            set: { id in
                if let chosen = MailPreset.all.first(where: { $0.id == id }) {
                    smtpHost = chosen.smtpHost
                    smtpPort = chosen.smtpPort
                    imapHost = chosen.imapHost
                    imapPort = chosen.imapPort
                } else {
                    smtpHost = ""
                    imapHost = ""
                }
            }
        )
    }

    private func show(_ settings: MailSettings) {
        hasPassword = settings.hasPassword
        user = settings.user
        to = settings.to == settings.user ? "" : settings.to
        smtpHost = settings.smtpHost
        smtpPort = settings.smtpPort
        imapHost = settings.imapHost
        imapPort = settings.imapPort
        digest = settings.digest
        instant = settings.instant
        sync = settings.sync
        loaded = true
    }

    private func load() async {
        guard model.connectionReady else {
            error = t("The engine is not running yet.")
            return
        }
        do {
            show(try await model.api.mailSettings())
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// Stores the account on this Mac (address in the preferences, password in the Keychain) and
    /// hands it to the running engine, which keeps it in memory only.
    private func push() async throws {
        let address = user.trimmingCharacters(in: .whitespacesAndNewlines)
        let recipient = to.trimmingCharacters(in: .whitespacesAndNewlines)
        let typed = password.replacingOccurrences(of: " ", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
        if model.config.mode == .local {
            UserDefaults.standard.set(address, forKey: Prefs.mailUser)
            UserDefaults.standard.set(recipient, forKey: Prefs.mailTo)
            if !typed.isEmpty { Keychain.set(typed, for: Secret.mailPassword) }
        }
        let body = MailBody(user: address, password: typed.isEmpty ? nil : typed, to: recipient,
                            smtpHost: smtpHost.trimmingCharacters(in: .whitespaces), smtpPort: smtpPort,
                            imapHost: imapHost.trimmingCharacters(in: .whitespaces), imapPort: imapPort,
                            digest: digest, instant: instant, sync: sync)
        show(try await model.api.saveMailSettings(body))
        password = ""
    }

    private func save() async {
        busy = true
        defer { busy = false }
        error = ""
        message = ""
        do {
            try await push()
            messageOK = true
            message = t("Saved.")
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func test() async {
        busy = true
        defer { busy = false }
        error = ""
        message = ""
        do {
            try await push()
            let task = try await model.wait(try await model.api.testMail(), every: 1)
            if task.status == "error" {
                messageOK = false
                message = task.message.isEmpty ? t("The test did not work.") : task.message
                return
            }
            let smtp = task.result?.smtp ?? ""
            let imap = task.result?.imap ?? ""
            if smtp.isEmpty && imap.isEmpty {
                messageOK = true
                message = t("It works: a test e-mail is on its way, and the inbox can be read.")
            } else {
                messageOK = false
                message = [smtp, imap].filter { !$0.isEmpty }.joined(separator: "\n")
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func disconnect() async {
        busy = true
        defer { busy = false }
        if model.config.mode == .local {
            UserDefaults.standard.removeObject(forKey: Prefs.mailUser)
            UserDefaults.standard.removeObject(forKey: Prefs.mailTo)
            Keychain.set("", for: Secret.mailPassword)
        }
        do {
            show(try await model.api.saveMailSettings(MailBody(user: "", password: "", to: "")))
            password = ""
            messageOK = true
            message = t("The mailbox is disconnected.")
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: Engine and data

struct EngineSettings: View {
    @Environment(AppModel.self) private var model
    @State private var mode: ServerMode = .local
    @State private var localFolder = ""
    @State private var baseURL = ""
    @State private var token = ""
    @State private var accessID = ""
    @State private var accessSecret = ""
    @State private var testResult = ""
    @State private var testing = false
    @State private var saved = false
    @State private var confirmRestart = false
    @State private var confirmReinstall = false

    private var draft: ServerConfig {
        ServerConfig(mode: mode, localFolder: localFolder, baseURL: baseURL, token: token,
                     accessClientID: accessID, accessClientSecret: accessSecret)
    }

    private var changed: Bool {
        if mode != model.config.mode { return true }
        if mode == .local { return localFolder != model.config.localFolder }
        return draft != model.config
    }

    var body: some View {
        Form {
            Section(t("Where JobRadar runs")) {
                Picker(t("Engine"), selection: $mode) {
                    Text(t("On this Mac")).tag(ServerMode.local)
                    Text(t("On my own server")).tag(ServerMode.remote)
                }
                .pickerStyle(.segmented).accentFill()
                .labelsHidden()
                Text(mode == .local
                     ? t("The app runs its engine on this Mac while it is open. Nothing leaves your Mac except the requests to the job boards and to your AI model.")
                     : t("For people who run the JobRadar engine on a server of their own: enter its address and API key."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if mode == .local {
                localSections
            } else {
                remoteSections
            }
            Section {
                HStack {
                    if mode == .remote {
                        Button(t("Test the connection")) {
                            testing = true
                            Task {
                                testResult = await model.testConnection(draft)
                                testing = false
                            }
                        }
                        .disabled(!draft.isComplete || testing)
                    }
                    Button(t("Apply changes")) {
                        Task {
                            await model.saveConfig(draft)
                            saved = true
                        }
                    }
                    .buttonStyle(.glassProminent).accentFill()
                    .disabled(!draft.isComplete || !changed)
                    if testing { ProgressView().controlSize(.small) }
                    if saved && !changed { Text(t("Changes applied")).foregroundStyle(.green) }
                }
                if !testResult.isEmpty && mode == .remote {
                    Text(testResult)
                        .font(.callout)
                        .textSelection(.enabled)
                }
            }
            Section(t("Backups")) {
                LabeledContent(t("Last backup")) {
                    Text(model.lastBackup.map { Dates.display($0) } ?? t("none yet"))
                }
                if let e = model.backupError {
                    Text(e).font(.caption).foregroundStyle(.red)
                }
                HStack {
                    Button(t("Back up now")) { Task { await model.backupIfNeeded(force: true) } }
                        .disabled(!model.connectionReady)
                    Button(t("Show backups")) { model.revealBackups() }
                }
                Text(t("While the app is open, a copy of your database is kept every day (the last 14 days)."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .onAppear {
            mode = model.config.mode
            localFolder = model.config.localFolder
            baseURL = model.config.baseURL
            token = model.config.token
            accessID = model.config.accessClientID
            accessSecret = model.config.accessClientSecret
        }
    }

    @ViewBuilder
    private var localSections: some View {
        Section(t("Your data")) {
            LabeledContent(t("Folder")) {
                Text(localFolder)
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
            }
            HStack {
                Button(t("Choose another folder…")) { chooseFolder() }
                Button(t("Use the standard folder")) { localFolder = EnginePaths.defaultWorkspace.path }
                    .disabled(localFolder == EnginePaths.defaultWorkspace.path)
                Button(t("Show in Finder")) {
                    NSWorkspace.shared.open(URL(fileURLWithPath: model.config.localFolder))
                }
            }
            Text(t("Your profile, settings, job database and generated documents live in this folder. A folder from an earlier JobRadar setup can be chosen as it is."))
                .font(.caption)
                .foregroundStyle(.secondary)
            EarlierDataOffer()
        }
        Section(t("Engine")) {
            LabeledContent(t("State")) {
                Text(model.localStatusText)
                    .lineLimit(4)
                    .textSelection(.enabled)
            }
            LabeledContent(t("Version")) {
                Text(EngineRuntime.bundledVersion)
            }
            HStack {
                Button(t("Restart")) {
                    if model.cycleRunning {
                        confirmRestart = true
                    } else {
                        Task { await model.restartLocal() }
                    }
                }
                .disabled(model.config.mode != .local || model.localState == .starting)
                .confirmationDialog(t("A scan is running"), isPresented: $confirmRestart) {
                    Button(t("Restart"), role: .destructive) { Task { await model.restartLocal() } }
                    Button(t("Cancel"), role: .cancel) {}
                } message: {
                    Text(t("Restarting now leaves the scan unfinished."))
                }
                Button(t("Show the log")) { LocalServer.shared.revealLog() }
                Button(t("Install again…")) { confirmReinstall = true }
                    .disabled(model.config.mode != .local)
                    .confirmationDialog(t("Install the engine again?"), isPresented: $confirmReinstall) {
                        Button(t("Install again")) { Task { await model.reinstallEngine() } }
                        Button(t("Cancel"), role: .cancel) {}
                    } message: {
                        Text(t("Python and the engine are downloaded and installed again. Your data is not touched."))
                    }
            }
            if model.jobBoardsInstalling {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(t("Adding the job board connectors…")).font(.caption)
                }
            } else if !model.jobBoardsError.isEmpty {
                Text(t("The job board connectors could not be installed: %@", model.jobBoardsError))
                    .font(.caption)
                    .foregroundStyle(.orange)
                Button(t("Try again")) { Task { await model.installJobBoards(force: true) } }
            }
        }
    }

    @ViewBuilder
    private var remoteSections: some View {
        Section(t("Server")) {
            TextField(t("Address"), text: $baseURL, prompt: Text(verbatim: "https://jobradar.example.com"))
            SecureField(t("API key"), text: $token, prompt: Text(t("The key your server shows for \"jobradar api-token\"")))
        }
        Section(t("Cloudflare Access (optional)")) {
            TextField(t("Service token client ID"), text: $accessID)
            SecureField(t("Service token client secret"), text: $accessSecret)
            Text(t("Only needed when your server's address is protected by Cloudflare Access."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = t("Choose")
        panel.message = t("Choose the folder for your JobRadar data. An existing JobRadar folder (with jobradar.yaml) keeps everything it has.")
        panel.directoryURL = URL(fileURLWithPath: localFolder.isEmpty ? EnginePaths.defaultWorkspace.path : localFolder)
        if panel.runModal() == .OK, let url = panel.url {
            localFolder = url.path
        }
    }
}

// MARK: Advanced

struct AdvancedSettings: View {
    @Environment(AppModel.self) private var model
    @State private var bookmarkletCopied = false
    @State private var shortcutMessage = ""
    @State private var shortcutFailed = false
    @State private var exporting = false
    @State private var exportMessage = ""
    @State private var exportFailed = false

    /// A bookmark that hands the page you are on to the app.
    static let bookmarklet = "javascript:(function(){location.href='jobradar://add?url='+encodeURIComponent(location.href);})();"

    var body: some View {
        Form {
            Section(t("Add jobs from your browser")) {
                Text(t("Copy the code and make it the address of a bookmark. On any job posting, click that bookmark: JobRadar opens and offers to add the posting. Chrome: right-click the bookmarks bar > Add page, and paste the code as the URL. Safari: bookmark any page, then edit the bookmark's address and paste the code."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    Button(t("Copy the bookmark code")) {
                        Clipboard.copy(Self.bookmarklet)
                        bookmarkletCopied = true
                    }
                    if bookmarkletCopied { Text(t("Copied")).foregroundStyle(.green) }
                }
            }
            Section(t("Setup")) {
                Button(t("Run the setup assistant again")) {
                    model.reopenOnboarding()
                    NSApplication.shared.keyWindow?.close()
                }
                .disabled(model.sampleData)
                if model.config.mode == .local {
                    Button(model.sampleData ? t("Leave the sample data") : t("Look around with sample data")) {
                        let on = !model.sampleData
                        Task { await model.showSampleData(on) }
                        NSApplication.shared.keyWindow?.close()
                    }
                }
                HStack {
                    Button(t("Put a shortcut on the Desktop")) { makeShortcut() }
                    if !shortcutMessage.isEmpty {
                        Text(shortcutMessage)
                            .font(.caption)
                            .foregroundStyle(shortcutFailed ? Color.red : Color.green)
                    }
                }
            }
            Section(t("Share the app")) {
                Text(t("Packs this copy of JobRadar into a disk image (.dmg) that other people can open and drag into their Applications folder. It contains the app only, none of your data."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    Button(t("Create a disk image…")) { exportDiskImage() }
                        .disabled(exporting)
                    if exporting { ProgressView().controlSize(.small) }
                }
                if AppInstaller.isDebugBuild {
                    Label(releaseProject != nil
                          ? t("This copy runs from Xcode, so JobRadar first builds the release version from your project (a few minutes) and puts the disk image into the project's dist folder.")
                          : t("This copy was started from Xcode for testing. For a disk image to hand out, double-click scripts/make-dmg.command in the project folder instead: it makes the release build."),
                          systemImage: "hammer")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if !exportMessage.isEmpty {
                    Text(exportMessage)
                        .font(.caption)
                        .foregroundStyle(exporting ? Color.secondary : (exportFailed ? Color.red : Color.green))
                        .textSelection(.enabled)
                }
                Text(t("Macs warn about apps from developers Apple does not know. To avoid that warning for other people, the app must be signed with an Apple Developer ID and notarised by Apple."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Section(t("About")) {
                LabeledContent(t("App version")) {
                    Text(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")
                }
                LabeledContent(t("Engine version")) {
                    Text(model.summary?.version ?? EngineRuntime.bundledVersion)
                }
                Text(t("JobRadar is free software under the MIT licence. It builds on JobSpy and ideas from career-ops, JobNavigator and JobCtrl."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
    }

    private func makeShortcut() {
        Task {
            do {
                try await AppInstaller.makeDesktopShortcut()
                shortcutFailed = false
                shortcutMessage = t("The shortcut is on your Desktop.")
            } catch {
                shortcutFailed = true
                shortcutMessage = AppInstaller.explain(error)
            }
        }
    }

    /// The project to build the release version from, when this copy runs from Xcode.
    private var releaseProject: URL? {
        AppInstaller.isDebugBuild ? AppInstaller.projectFolder() : nil
    }

    private func exportDiskImage() {
        if let project = releaseProject {
            exporting = true
            exportFailed = false
            exportMessage = t("Building the release version…")
            Task {
                do {
                    let image = try await AppInstaller.buildReleaseImage(project: project)
                    exportFailed = false
                    exportMessage = t("Created: %@", image.path)
                    NSWorkspace.shared.activateFileViewerSelecting([image])
                } catch {
                    exportFailed = true
                    exportMessage = error.localizedDescription
                }
                exporting = false
            }
            return
        }
        let panel = NSSavePanel()
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
        panel.nameFieldStringValue = "JobRadar-\(version).dmg"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let target = panel.url else { return }
        exporting = true
        exportMessage = ""
        Task {
            do {
                try await AppInstaller.exportDiskImage(to: target)
                exportFailed = false
                exportMessage = t("Created: %@", target.path)
                NSWorkspace.shared.activateFileViewerSelecting([target])
            } catch {
                exportFailed = true
                exportMessage = error.localizedDescription
            }
            exporting = false
        }
    }
}
