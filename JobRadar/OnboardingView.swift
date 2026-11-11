import AppKit
import SwiftUI

/// The first-run assistant: language and look, AI model, profile from a CV, what to search for.
/// The engine installs itself in the background while the first page is shown.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @Environment(ProfileEditor.self) private var profileEditor
    @Environment(SearchEditor.self) private var searchEditor
    @State private var showConnection = false
    @State private var working = false

    private var titles: [String] {
        [t("Welcome"), t("AI model"), t("Your profile"), t("Your search"), t("Ready")]
    }

    private var step: Int { min(max(model.onboardingStep, 0), 4) }

    var body: some View {
        VStack(spacing: 0) {
            OnboardingSteps(titles: titles, current: step)
                .padding(.horizontal, 24)
                .padding(.top, 18)
                .padding(.bottom, 8)
            ScrollView {
                GlassEffectContainer(spacing: 0) {
                    VStack(alignment: .leading, spacing: 16) {
                        page
                    }
                    .padding(24)
                    .frame(maxWidth: 880, alignment: .leading)
                }
                .frame(maxWidth: .infinity)
            }
            .id(step)   // every page starts at its top
            footer
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .sheet(isPresented: $showConnection) { ConnectionSheet() }
    }

    @ViewBuilder
    private var page: some View {
        switch step {
        case 0: WelcomePage(showConnection: $showConnection)
        case 1: AIPage()
        case 2: ProfilePage()
        case 3: SearchPage()
        default: ReadyPage()
        }
    }

    private var footer: some View {
        HStack(spacing: 10) {
            if step > 0 {
                Button(t("Back")) { model.onboardingStep = step - 1 }
                    .buttonStyle(.glass).plainGlass()
                    .disabled(working)
            }
            Button(t("Skip the setup")) { model.finishOnboarding() }
                .buttonStyle(.link)
                .disabled(working)
            Spacer()
            if working { ProgressView().controlSize(.small) }
            if step < 4 {
                Button(continueTitle) { next() }
                    .buttonStyle(.glassProminent).accentFill()
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
                    .disabled(working)
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
    }

    private var continueTitle: String {
        switch step {
        case 0: return t("Get started")
        case 2: return profileEditor.dirty ? t("Save and continue") : t("Continue")
        case 3: return searchEditor.dirty ? t("Save and continue") : t("Continue")
        default: return t("Continue")
        }
    }

    /// Saves what the page edited, then goes on. A failed save keeps the page (its error is shown there).
    private func next() {
        working = true
        Task {
            var ok = true
            if step == 2 && profileEditor.dirty {
                ok = await profileEditor.save(model)
            } else if step == 3 && searchEditor.dirty {
                ok = await searchEditor.save(model)
            }
            if ok { model.onboardingStep = step + 1 }
            working = false
        }
    }
}

/// The row of numbered steps at the top.
struct OnboardingSteps: View {
    let titles: [String]
    let current: Int

    var body: some View {
        let accent = ThemeStore.shared.accent
        HStack(spacing: 8) {
            ForEach(Array(titles.enumerated()), id: \.offset) { index, title in
                HStack(spacing: 6) {
                    Text("\(index + 1)")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(index <= current ? Color.white : Color.secondary)
                        .frame(width: 20, height: 20)
                        .background(index <= current ? accent : Color.secondary.opacity(0.2), in: Circle())
                    Text(title)
                        .font(.callout.weight(index == current ? .semibold : .regular))
                        .foregroundStyle(index == current ? Color.primary : Color.secondary)
                        .lineLimit(1)
                }
                if index < titles.count - 1 {
                    Rectangle()
                        .fill(Color.secondary.opacity(0.25))
                        .frame(height: 1)
                        .frame(maxWidth: 44)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .cardBackground(cornerRadius: 20)
    }
}

/// State of the engine in one or two lines, for the assistant.
struct EngineInlineStatus: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if model.config.mode == .remote {
            Label(model.connectionReady ? t("Using your own server.") : t("Your server is not set up yet."),
                  systemImage: "server.rack")
                .foregroundStyle(.secondary)
        } else {
            switch model.localState {
            case .running:
                Label(t("The engine is installed and running."), systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            case .installing(let step):
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(step.map { t("Setting up the engine: %@ (step %@ of %@)", $0.title, $0.index, $0.total) }
                             ?? t("Preparing the engine…"))
                    }
                    if let step {
                        ProgressView(value: step.fraction)
                            .progressViewStyle(.linear)
                            .frame(maxWidth: 360)
                    }
                    Text(t("This happens once, needs an internet connection and can take a few minutes. You can go on meanwhile."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            case .failed(let message):
                VStack(alignment: .leading, spacing: 8) {
                    Banner(kind: .error, text: message)
                    HStack {
                        Button(t("Try again")) { Task { await model.startLocal() } }
                            .buttonStyle(.glassProminent).accentFill()
                        Button(t("Show the log")) { LocalServer.shared.revealLog() }
                            .buttonStyle(.glass).plainGlass()
                    }
                }
            default:
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(t("Starting the engine…"))
                }
            }
        }
    }
}

struct WelcomePage: View {
    @Environment(AppModel.self) private var model
    @Binding var showConnection: Bool

    var body: some View {
        @Bindable var theme = ThemeStore.shared
        @Bindable var language = LanguageStore.shared
        HStack(alignment: .center, spacing: 18) {
            if let icon = AppInstaller.bundleIcon() {
                Image(nsImage: icon)
                    .resizable()
                    .frame(width: 92, height: 92)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(t("Welcome to JobRadar")).font(.largeTitle.bold())
                Text(t("It finds jobs that fit you, judges each one against your real CV, and writes honest applications for the ones you choose."))
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.bottom, 4)
        VStack(alignment: .leading, spacing: 10) {
            feature("antenna.radiowaves.left.and.right", .blue, t("Scans job boards and company career pages for you"),
                    t("LinkedIn, Indeed, Google Jobs, career pages and more, several times a day."))
            feature("checklist", .green, t("Explains every score"),
                    t("Each requirement of a posting is matched to a line of your profile, so you see why a job fits."))
            feature("doc.badge.plus", .purple, t("Writes your CV and cover letter for a job"),
                    t("Only from facts in your profile. Nothing is invented, and nothing is sent without you."))
            feature("lock.shield", .orange, t("Stays on your Mac"),
                    t("Your data lives in a folder on this Mac. You connect your own AI model."))
        }
        .card()
        SectionBox(title: t("Language and look"), systemImage: "paintpalette") {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 10) {
                GridRow {
                    Text(t("Language")).foregroundStyle(.secondary)
                    Picker(t("Language"), selection: $language.choice) {
                        ForEach(AppLanguage.allCases) { option in
                            Text(language.title(option)).tag(option)
                        }
                    }
                    .pickerStyle(.segmented).accentFill()
                    .labelsHidden()
                    .frame(maxWidth: 380, alignment: .leading)
                }
                GridRow {
                    Text(t("Mode")).foregroundStyle(.secondary)
                    Picker(t("Mode"), selection: $theme.appearance) {
                        ForEach(AppearanceChoice.allCases) { choice in
                            Text(choice.title).tag(choice)
                        }
                    }
                    .pickerStyle(.segmented).accentFill()
                    .labelsHidden()
                    .frame(maxWidth: 380, alignment: .leading)
                }
                GridRow {
                    Text(t("Colours")).foregroundStyle(.secondary)
                    HStack(spacing: 10) {
                        ForEach(ThemePalette.all) { palette in
                            PaletteSwatch(palette: palette, selected: theme.paletteID == palette.id) {
                                theme.paletteID = palette.id
                            }
                        }
                    }
                }
            }
        }
        SectionBox(title: t("Engine"), systemImage: "shippingbox") {
            EngineInlineStatus()
            if model.setup?.ready == true {
                Banner(kind: .success, text: t("This JobRadar folder is already set up."))
                Button(t("Open JobRadar")) { model.finishOnboarding() }
                    .buttonStyle(.glassProminent).accentFill()
            }
            EarlierDataOffer()
            Button(t("I already have JobRadar data, or my own server…")) { showConnection = true }
                .buttonStyle(.link)
        }
        if model.config.mode == .local {
            SectionBox(title: t("Just looking?"), systemImage: "eyes") {
                Text(t("Open JobRadar with made-up jobs and a made-up profile, and see how it works before you set it up."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Button(t("Look around with sample data")) { Task { await model.showSampleData(true) } }
                    .buttonStyle(.glass).plainGlass()
                    .disabled(model.localState != .running)
            }
        }
    }

    private func feature(_ icon: String, _ color: Color, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(color)
                .frame(width: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(text).font(.callout).foregroundStyle(.secondary)
            }
        }
    }
}

/// Where the engine runs and where the data lives, as a sheet of the assistant.
struct ConnectionSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            EngineSettings()
            Divider()
            HStack {
                Spacer()
                Button(t("Done")) { dismiss() }
                    .buttonStyle(.glassProminent).accentFill()
                    .keyboardShortcut(.defaultAction)
            }
            .padding(12)
        }
        .frame(width: 680, height: 620)
    }
}

struct AIPage: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Text(t("Connect an AI model")).font(.title.bold())
        Text(t("JobRadar uses an AI model to read your CV, to judge each posting against it and to write your application documents. Connect one you already have. You can change it at any time in Settings."))
            .font(.title3)
            .foregroundStyle(.secondary)
        if model.connectionReady {
            AIModelForm()
        } else {
            EngineInlineStatus().card()
        }
    }
}

struct ProfilePage: View {
    @Environment(AppModel.self) private var model
    @Environment(ProfileEditor.self) private var editor

    var body: some View {
        Text(t("Tell JobRadar who you are")).font(.title.bold())
        Text(t("Start from your CV and correct what the AI model read, or type directly into the page below. This profile is what every job is compared with."))
            .font(.title3)
            .foregroundStyle(.secondary)
        if model.connectionReady {
            CVImportBox()
            if !editor.note.isEmpty { Banner(kind: .success, text: editor.note) }
            if !editor.error.isEmpty { Banner(kind: .error, text: editor.error) }
            ProfilePaper()
                .frame(maxWidth: .infinity)
                .task { await editor.load(model) }
        } else {
            EngineInlineStatus().card()
        }
    }
}

struct SearchPage: View {
    @Environment(AppModel.self) private var model
    @Environment(SearchEditor.self) private var editor

    var body: some View {
        Text(t("What should JobRadar look for?")).font(.title.bold())
        Text(t("Say what you want and where. You can fine-tune the keywords, sources and filters later under Search."))
            .font(.title3)
            .foregroundStyle(.secondary)
        if model.connectionReady {
            SearchWhereCard()
            SearchWishCard()
            if !editor.note.isEmpty { Banner(kind: .success, text: editor.note) }
            if !editor.error.isEmpty { Banner(kind: .error, text: editor.error) }
            ForEach(editor.draft.tracks, id: \.localID) { track in
                VStack(alignment: .leading, spacing: 6) {
                    Label(track.name, systemImage: "scope").font(.headline)
                    if !track.northStar.isEmpty {
                        Text(track.northStar).font(.callout).foregroundStyle(.secondary)
                    }
                    ChipGrid(items: track.searchTerms.map { (text: $0, color: Color.orange) })
                }
                .card()
            }
            Color.clear
                .frame(height: 1)
                .task { await editor.load(model) }
        } else {
            EngineInlineStatus().card()
        }
    }
}

struct ReadyPage: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings
    @State private var starting = false

    private var ready: Bool { model.setup?.ready == true }

    private var aiText: String {
        guard model.setup?.ai.ready == true else { return t("Not connected: jobs are collected but not evaluated.") }
        if !model.aiTestError.isEmpty { return t("The connection test failed: %@", model.aiTestError) }
        return model.summary?.llm ?? ""
    }

    var body: some View {
        Text(ready ? t("You are all set") : t("Almost there")).font(.title.bold())
        Text(ready
             ? t("JobRadar can now look for jobs. The first scan takes a few minutes; matches appear in your inbox as they are found and evaluated.")
             : t("Something is still missing. You can go back and finish it, or open JobRadar and complete the setup later."))
            .font(.title3)
            .foregroundStyle(.secondary)
        VStack(alignment: .leading, spacing: 10) {
            check(model.localState == .running || model.config.mode == .remote, t("Engine"),
                  model.localStatusText)
            check(model.setup?.ai.ready == true && model.aiTestError.isEmpty, t("AI model"), aiText)
            check(model.setup?.profile.exists == true && model.setup?.profile.missing.isEmpty == true, t("Profile"),
                  profileText)
            check((model.setup?.search.tracks ?? 0) > 0, t("Search"),
                  t("%@ search tracks", model.setup?.search.tracks ?? 0))
            if model.config.mode == .local {
                check(!model.jobBoardsInstalling && model.jobBoardsError.isEmpty, t("Job boards"), jobBoardsText)
            }
        }
        .card()
        SectionBox(title: t("Optional: connect your mailbox"), systemImage: "envelope") {
            Text(t("Get a daily summary and alerts by e-mail, and let JobRadar notice replies from companies."))
                .font(.callout)
                .foregroundStyle(.secondary)
            Button(t("Open the e-mail settings…")) {
                UserDefaults.standard.set("mail", forKey: "settingsTab")
                openSettings()
            }
            .buttonStyle(.glass).plainGlass()
        }
        HStack(spacing: 10) {
            Button {
                starting = true
                Task {
                    model.finishOnboarding()
                    await model.runCycle()
                    starting = false
                }
            } label: {
                Label(t("Start the first scan"), systemImage: "antenna.radiowaves.left.and.right")
            }
            .buttonStyle(.glassProminent).accentFill()
            .controlSize(.large)
            .disabled(!ready || !model.connectionReady || starting)
            Button(t("Open JobRadar without scanning")) { model.finishOnboarding() }
                .buttonStyle(.glass).plainGlass()
                .controlSize(.large)
        }
        .task { await model.loadSetup() }
    }

    private var profileText: String {
        guard let profile = model.setup?.profile, profile.exists else { return t("Not created yet.") }
        if profile.missing.isEmpty { return profile.name }
        return t("Still missing: %@.", profile.missing.map { ProfileEditor.explain($0) }.joined(separator: ", "))
    }

    private var jobBoardsText: String {
        if model.jobBoardsInstalling { return t("Being added in the background…") }
        if !model.jobBoardsError.isEmpty { return t("Could not be installed. You can try again under Search.") }
        return t("LinkedIn, Indeed and others are ready.")
    }

    private func check(_ ok: Bool, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle")
                .foregroundStyle(ok ? Color.green : Color.orange)
            Text(title).font(.headline).frame(width: 120, alignment: .leading)
            Text(detail)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(3)
        }
    }
}
