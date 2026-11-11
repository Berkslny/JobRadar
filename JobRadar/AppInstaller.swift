import AppKit

/// Small helpers around the app bundle: the Desktop shortcut, the icon, a second running copy,
/// and packing the app into a disk image for sharing.
enum AppInstaller {
    static let appName = "JobRadar"

    /// True when this copy runs from an Applications folder (not from Xcode, Downloads or the disk image).
    static var runsInstalled: Bool {
        let me = Bundle.main.bundleURL.resolvingSymlinksInPath().path
        let home = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications").path
        return me.hasPrefix("/Applications/") || me.hasPrefix(home + "/")
    }

    /// True for the copy Xcode builds for running and debugging; it is not the one to hand to other people.
    static var isDebugBuild: Bool {
        let folder = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS")
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        return names.contains { $0.hasSuffix(".debug.dylib") }
    }

    /// The Xcode project this copy was built from, when it runs from Xcode's build folder and the project
    /// has the release script. Xcode notes the project's place next to the build folder.
    nonisolated static func projectFolder() -> URL? {
        // …/DerivedData/<name>-<id>/Build/Products/Debug/JobRadar.app
        var derived = Bundle.main.bundleURL
        for _ in 0..<4 { derived = derived.deletingLastPathComponent() }
        guard let data = try? Data(contentsOf: derived.appendingPathComponent("info.plist")),
              let plist = (try? PropertyListSerialization.propertyList(from: data, format: nil)) as? [String: Any],
              let workspace = plist["WorkspacePath"] as? String else { return nil }
        let folder = URL(fileURLWithPath: workspace).deletingLastPathComponent()
        let script = folder.appendingPathComponent("scripts/make-dmg.command")
        return FileManager.default.isExecutableFile(atPath: script.path) ? folder : nil
    }

    /// Builds the release version from the project and packs it into a disk image (the project's
    /// scripts/make-dmg.command). Returns the image in the project's dist folder.
    static func buildReleaseImage(project: URL) async throws -> URL {
        let script = project.appendingPathComponent("scripts/make-dmg.command")
        let result: ShellResult = await Task.detached {
            // a plain environment: what Xcode gives a debug run must not reach the release build
            let source = ProcessInfo.processInfo.environment
            var env = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "JOBRADAR_NO_REVEAL": "1"]
            for key in ["HOME", "USER", "LOGNAME", "TMPDIR", "DEVELOPER_DIR", "JOBRADAR_SIGN_IDENTITY",
                        "JOBRADAR_NOTARY_PROFILE"] {
                if let value = source[key] { env[key] = value }
            }
            return Shell.run(URL(fileURLWithPath: "/bin/bash"), [script.path], environment: env, timeout: 2400)
        }.value
        let done = result.output.split(whereSeparator: \.isNewline).last { $0.hasPrefix("Done: ") }
        guard result.ok, let done else {
            throw EngineError.tool(t("Building the release version"), result.tail())
        }
        return URL(fileURLWithPath: String(done.dropFirst("Done: ".count)))
    }

    /// Where the Desktop shortcut goes. Only computing the path does not touch the Desktop.
    static var desktopAlias: URL {
        let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Desktop", isDirectory: true)
        return desktop.appendingPathComponent(appName)
    }

    /// Puts a shortcut to this app on the Desktop. The first Desktop access shows a macOS permission prompt.
    static func makeDesktopShortcut() async throws {
        let app = Bundle.main.bundleURL
        let alias = desktopAlias
        let fallback = t("JobRadar shortcut")
        try await Task.detached {
            try AppInstaller.makeAlias(to: app, at: alias, fallbackName: fallback)
        }.value
    }

    /// The icon inside this bundle. macOS can keep showing a blank icon it cached for an earlier build;
    /// setting it at launch fixes the Dock and the About window.
    static func bundleIcon() -> NSImage? {
        if let icon = NSImage(named: "AppIcon") { return icon }
        guard let url = Bundle.main.url(forResource: "AppIcon", withExtension: "icns") else { return nil }
        return NSImage(contentsOf: url)
    }

    /// Quits other running copies of this app (say the Applications copy when an Xcode build starts),
    /// so only one of them runs the engine. Waits up to 10 seconds for them to close.
    static func closeOtherInstances() async {
        guard let id = Bundle.main.bundleIdentifier else { return }
        let me = ProcessInfo.processInfo.processIdentifier
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: id)
            .filter { $0.processIdentifier != me && $0.activationPolicy == .regular }
        guard !others.isEmpty else { return }
        for app in others {
            _ = app.terminate()
        }
        for _ in 0..<40 {
            if others.allSatisfy({ $0.isTerminated }) { break }
            try? await Task.sleep(for: .milliseconds(250))
        }
    }

    static func explain(_ error: Error) -> String {
        var text = t("That did not work: %@", error.localizedDescription)
        if isPermissionError(error) {
            text += " " + t("If macOS asked for access to the Desktop, choose Allow. Later you can change it in System Settings > Privacy & Security > Files and Folders > JobRadar.")
        }
        return text
    }

    /// Packs this app into a disk image (.dmg) with a shortcut to the Applications folder,
    /// the usual way to hand a Mac app to somebody else.
    static func exportDiskImage(to target: URL) async throws {
        let app = Bundle.main.bundleURL
        let name = appName
        let result: ShellResult = await Task.detached {
            let fm = FileManager.default
            let stage = fm.temporaryDirectory.appendingPathComponent("JobRadar-dmg-\(UUID().uuidString)", isDirectory: true)
            defer { try? fm.removeItem(at: stage) }
            do {
                try fm.createDirectory(at: stage, withIntermediateDirectories: true)
                try fm.createSymbolicLink(at: stage.appendingPathComponent("Applications"),
                                          withDestinationURL: URL(fileURLWithPath: "/Applications"))
            } catch {
                return ShellResult(status: -1, output: error.localizedDescription)
            }
            let copy = Shell.run(URL(fileURLWithPath: "/usr/bin/ditto"),
                                 [app.path, stage.appendingPathComponent("\(name).app").path], timeout: 300)
            guard copy.ok else { return copy }
            try? fm.removeItem(at: target)
            return Shell.run(URL(fileURLWithPath: "/usr/bin/hdiutil"),
                             ["create", "-volname", name, "-srcfolder", stage.path, "-ov", "-format", "UDZO",
                              target.path], timeout: 600)
        }.value
        guard result.ok else {
            throw EngineError.tool(t("Creating the disk image"), result.tail())
        }
    }

    // MARK: File work (off the main thread)

    /// Writes a Finder alias to `target`. An older JobRadar shortcut is replaced; a different file
    /// with that name is left alone and `fallbackName` is used instead.
    nonisolated static func makeAlias(to target: URL, at alias: URL, fallbackName: String) throws {
        let fm = FileManager.default
        var place = alias
        if fm.fileExists(atPath: place.path) {
            let isAlias = (try? place.resourceValues(forKeys: [.isAliasFileKey]).isAliasFile) ?? false
            if !isAlias {
                place = alias.deletingLastPathComponent().appendingPathComponent(fallbackName)
            }
            if fm.fileExists(atPath: place.path) {
                try fm.removeItem(at: place)
            }
        }
        let data = try target.bookmarkData(options: .suitableForBookmarkFile,
                                           includingResourceValuesForKeys: nil, relativeTo: nil)
        try URL.writeBookmarkData(data, to: place)
    }

    nonisolated static func isPermissionError(_ error: Error) -> Bool {
        if let e = error as? CocoaError, e.code == .fileWriteNoPermission || e.code == .fileReadNoPermission {
            return true
        }
        if let e = error as? POSIXError, e.code == .EACCES || e.code == .EPERM {
            return true
        }
        guard let underlying = (error as NSError).userInfo[NSUnderlyingErrorKey] as? NSError else { return false }
        return underlying.domain == NSPOSIXErrorDomain
            && (underlying.code == Int(EACCES) || underlying.code == Int(EPERM))
    }
}
