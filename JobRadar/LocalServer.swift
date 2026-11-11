import AppKit
import Foundation
import Security

enum LocalServerError: LocalizedError {
    case sandboxed
    case launchFailed(String)
    case exited(String)
    case timeout(String)
    case noPort

    var errorDescription: String? {
        switch self {
        case .sandboxed:
            return t("The app runs inside the App Sandbox and cannot start its engine. Build it with the App Sandbox turned off.")
        case .launchFailed(let message):
            return t("The engine could not be started: %@", message)
        case .exited(let log):
            return t("The engine stopped while starting.") + (log.isEmpty ? "" : "\n\n\(log)")
        case .timeout(let log):
            return t("The engine did not answer within a minute.") + (log.isEmpty ? "" : "\n\n\(log)")
        case .noPort:
            return t("No free local port was found between 8790 and 8799. Close the program that uses them and try again.")
        }
    }
}

/// Runs the JobRadar engine (`python -m jobradar serve`) on this Mac for as long as the app is open.
/// Only this app talks to it: every start gets a fresh random key.
@MainActor
final class LocalServer {
    static let shared = LocalServer()
    static let firstPort = 8790
    static var isSandboxed: Bool { ProcessInfo.processInfo.environment["APP_SANDBOX_CONTAINER_ID"] != nil }
    private static let pidKey = "enginePID"

    private(set) var port = LocalServer.firstPort
    /// The key of the running engine; empty until it was started.
    private(set) var token = ""
    /// Folder with the user's data (jobradar.yaml, data/).
    var workspace = EnginePaths.defaultWorkspace
    /// The engine serves sample data: a stand-in answers instead of a model and nothing is scanned.
    var sampleData = false
    /// Set by the app while a scan runs, so quitting can ask first.
    var scanInProgress = false
    private var process: Process? = nil

    var baseURL: String { "http://127.0.0.1:\(port)" }
    var isRunning: Bool { process?.isRunning == true }
    var logFile: URL { EnginePaths.logs.appendingPathComponent("engine.log") }

    private init() {}

    /// True when our engine answers and accepts our key.
    func healthy() async -> Bool {
        guard !token.isEmpty, let url = URL(string: baseURL + "/api/v1/setup") else { return false }
        var request = URLRequest(url: url, timeoutInterval: 3)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        guard let (_, response) = try? await URLSession.shared.data(for: request) else { return false }
        return (response as? HTTPURLResponse)?.statusCode == 200
    }

    /// Starts the engine and waits until it answers. An engine left over from an earlier run of the
    /// app (crash, stopped from Xcode) is ended first, so the new settings and code are used.
    func start(environment extra: [String: String]) async throws {
        if isRunning, await healthy() { return }
        if Self.isSandboxed { throw LocalServerError.sandboxed }
        stop()
        await endLeftovers()
        guard let free = await freePort() else { throw LocalServerError.noPort }
        port = free
        token = Self.randomToken()
        let venvBin = EnginePaths.venv.appendingPathComponent("bin").path
        let path = await Task.detached { ShellPath.resolve(first: venvBin) }.value
        try launch(path: path, extra: extra)
        for _ in 0..<150 {
            try? await Task.sleep(for: .milliseconds(400))
            if await healthy() { return }
            if let p = process, !p.isRunning {
                process = nil
                throw LocalServerError.exited(logTail())
            }
        }
        throw LocalServerError.timeout(logTail())
    }

    /// Stops the engine. `waitUpTo` seconds: wait until it has exited (used on quit).
    func stop(waitUpTo seconds: Double = 0) {
        let deadline = Date().addingTimeInterval(seconds)
        if let p = process, p.isRunning {
            p.terminate()
            while p.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }
        }
        process = nil
    }

    /// Ends engines of this app that still run from an earlier start.
    private func endLeftovers() async {
        let stored = pid_t(truncatingIfNeeded: UserDefaults.standard.integer(forKey: Self.pidKey))
        let first = Self.firstPort
        let marker = EnginePaths.venv.path
        let found: [pid_t] = await Task.detached {
            var candidates: [pid_t] = stored > 0 ? [stored] : []
            for port in first..<(first + 10) {
                candidates += ProcessCommand.listeners(port: port)
            }
            var ours: [pid_t] = []
            for pid in Set(candidates) {
                let line = ProcessCommand.line(of: pid)
                if line.contains(marker) && line.contains("jobradar") && line.contains("serve") {
                    ours.append(pid)
                }
            }
            return ours
        }.value
        guard !found.isEmpty else { return }
        for pid in found { _ = kill(pid, SIGTERM) }
        for _ in 0..<40 {
            if found.allSatisfy({ kill($0, 0) != 0 }) { break }
            try? await Task.sleep(for: .milliseconds(250))
        }
        for pid in found where kill(pid, 0) == 0 { _ = kill(pid, SIGKILL) }
    }

    /// The first port from 8790 on that nothing listens on.
    private func freePort() async -> Int? {
        let first = Self.firstPort
        return await Task.detached {
            (first..<(first + 10)).first { ProcessCommand.listeners(port: $0).isEmpty }
        }.value
    }

    private static func randomToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        if SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) != errSecSuccess {
            bytes = (0..<32).map { _ in UInt8.random(in: 0...255) }
        }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    private func launch(path: String, extra: [String: String]) throws {
        let fm = FileManager.default
        if sampleData {
            // the app's own folder for made-up data: anything unfinished from an earlier try is thrown away
            let marker = workspace.appendingPathComponent(".jobradar-demo")
            let ready = (try? String(contentsOf: marker, encoding: .utf8))?.hasPrefix("ready") == true
            if !ready { try? fm.removeItem(at: workspace) }
        }
        do {
            try fm.createDirectory(at: workspace, withIntermediateDirectories: true)
            try fm.createDirectory(at: EnginePaths.logs, withIntermediateDirectories: true)
        } catch {
            throw LocalServerError.launchFailed(error.localizedDescription)
        }
        fm.createFile(atPath: logFile.path, contents: nil)
        let log: FileHandle
        do {
            log = try FileHandle(forWritingTo: logFile)
        } catch {
            throw LocalServerError.launchFailed(error.localizedDescription)
        }
        let p = Process()
        p.executableURL = EnginePaths.python
        p.arguments = ["-m", "jobradar", "serve", "--no-open", "--host", "127.0.0.1", "--port", String(port),
                       "--workspace", workspace.path] + (sampleData ? ["--demo"] : [])
        p.currentDirectoryURL = workspace
        var env = ProcessInfo.processInfo.environment
        for key in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "JOBRADAR_CONFIG"] {
            env[key] = nil
        }
        env["PATH"] = path
        env["PYTHONUNBUFFERED"] = "1"
        env["_TYPER_STANDARD_TRACEBACK"] = "1"   // short, plain error reports in the log
        env["NO_COLOR"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        if env["LANG"] == nil { env["LANG"] = "en_US.UTF-8" }
        env["JOBRADAR_API_TOKEN"] = token
        env["JOBRADAR_LANG"] = L10n.code
        env["JOBRADAR_APP_LINKS"] = "1"
        env["JOBRADAR_DASHBOARD_URL"] = baseURL
        if let helper = Bundle.main.executablePath { env["JOBRADAR_PDF_HELPER"] = helper }
        for (key, value) in extra where !value.isEmpty {
            env[key] = value
        }
        p.environment = env
        p.standardInput = FileHandle.nullDevice
        p.standardOutput = log
        p.standardError = log
        do {
            try p.run()
        } catch {
            throw LocalServerError.launchFailed(error.localizedDescription)
        }
        process = p
        UserDefaults.standard.set(Int(p.processIdentifier), forKey: Self.pidKey)
    }

    func logTail(lines: Int = 6) -> String {
        guard let text = try? String(contentsOf: logFile, encoding: .utf8) else { return "" }
        return text.split(separator: "\n")
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            .suffix(lines)
            .map { $0.count > 220 ? String($0.prefix(220)) + "…" : String($0) }
            .joined(separator: "\n")
    }

    func revealLog() {
        if FileManager.default.fileExists(atPath: logFile.path) {
            NSWorkspace.shared.activateFileViewerSelecting([logFile])
        } else {
            NSWorkspace.shared.open(EnginePaths.support)
        }
    }
}
