import AppKit
import SwiftUI

/// Entry point. Started with `--html-to-pdf in.html out.pdf` the executable only makes a PDF
/// (the engine uses that for the CV and letter); otherwise the app opens.
@main
enum JobRadarMain {
    static func main() {
        let arguments = CommandLine.arguments
        if let i = arguments.firstIndex(of: "--html-to-pdf"), arguments.count > i + 2 {
            PDFHelper.run(html: arguments[i + 1], pdf: arguments[i + 2])
        }
        JobRadarApp.main()
    }
}

/// Stops the engine the app started when the app quits (after asking if a scan is running).
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        ThemeStore.shared.applyAppearance()
        if let icon = AppInstaller.bundleIcon() {
            NSApplication.shared.applicationIconImage = icon
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false   // the app stays in the menu bar for scans and notifications
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let server = LocalServer.shared
        guard server.isRunning && server.scanInProgress else { return .terminateNow }
        NSApplication.shared.activate()
        let alert = NSAlert()
        alert.messageText = t("A scan is running")
        alert.informativeText = t("If you quit now, JobRadar stops and the scan is left unfinished. Quit anyway?")
        alert.addButton(withTitle: t("Quit"))
        alert.addButton(withTitle: t("Cancel"))
        return alert.runModal() == .alertFirstButtonReturn ? .terminateNow : .terminateCancel
    }

    func applicationWillTerminate(_ notification: Notification) {
        LocalServer.shared.stop(waitUpTo: 3)
    }
}

struct JobRadarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var model = AppModel()
    // the drafts live here, so unsaved edits survive when the windows are rebuilt for another language
    @State private var profileEditor = ProfileEditor()
    @State private var searchEditor = SearchEditor()

    var body: some Scene {
        // reading the language here rebuilds windows and menus when it changes
        let language = LanguageStore.shared.code
        WindowGroup("JobRadar", id: "main") {
            RootView()
                .id(language)
                .environment(model)
                .environment(profileEditor)
                .environment(searchEditor)
                .frame(minWidth: 1080, minHeight: 680)
                .themedWindow()
                .handlesExternalEvents(preferring: ["*"], allowing: ["*"])
                .onOpenURL { url in model.handle(url: url) }
        }
        .commands {
            CommandGroup(replacing: .appInfo) {
                Button(t("About JobRadar")) {
                    var options: [NSApplication.AboutPanelOptionKey: Any] = [.applicationName: "JobRadar"]
                    if let icon = AppInstaller.bundleIcon() { options[.applicationIcon] = icon }
                    NSApplication.shared.orderFrontStandardAboutPanel(options: options)
                }
            }
            CommandGroup(replacing: .newItem) {
                Button(t("Refresh")) { Task { await model.refreshAll() } }
                    .keyboardShortcut("r", modifiers: .command)
                Button(t("Scan now")) { Task { await model.runCycle() } }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
                    .disabled(!model.connectionReady || model.cycleRunning)
                Button(t("Add a job link…")) {
                    model.importDraft = ""
                    model.showImport = true
                }
                .keyboardShortcut("l", modifiers: .command)
                .disabled(!model.connectionReady)
            }
        }

        Settings {
            SettingsView()
                .id(language)
                .environment(model)
                .themedWindow()
        }

        MenuBarExtra {
            MenuBarView()
                .id(language)
                .environment(model)
                .tint(ThemeStore.shared.accentText)
        } label: {
            Image(systemName: model.cycleRunning ? "antenna.radiowaves.left.and.right"
                  : model.pendingReplies > 0 ? "envelope.badge.fill"
                  : (model.newStrongJobs.isEmpty ? "scope" : "star.circle.fill"))
        }
        .menuBarExtraStyle(.window)
    }
}
