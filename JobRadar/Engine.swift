import CryptoKit
import Foundation

/// Where the app keeps the engine and, by default, the user's data.
nonisolated enum EnginePaths {
    static var support: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support", isDirectory: true)
        return base.appendingPathComponent("JobRadar", isDirectory: true)
    }

    /// Python, the engine and the installer tool. Safe to delete: the app builds it again.
    static var runtime: URL { support.appendingPathComponent("runtime", isDirectory: true) }
    static var bin: URL { runtime.appendingPathComponent("bin", isDirectory: true) }
    static var uv: URL { bin.appendingPathComponent("uv") }
    static var venv: URL { runtime.appendingPathComponent("venv", isDirectory: true) }
    static var python: URL { venv.appendingPathComponent("bin/python") }
    static var marker: URL { runtime.appendingPathComponent("installed.json") }
    static var logs: URL { support.appendingPathComponent("logs", isDirectory: true) }

    /// The user's data (profile, settings, database, generated documents) unless another folder is chosen.
    static var defaultWorkspace: URL { support.appendingPathComponent("workspace", isDirectory: true) }
    /// Made-up jobs and a made-up profile for looking around; the engine builds it on first use.
    static var sampleWorkspace: URL { support.appendingPathComponent("sample-data", isDirectory: true) }
}

/// Data of an earlier JobRadar on this Mac: the command line version kept everything in ~/projects/jobradar.
nonisolated enum EarlierData {
    static var folder: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("projects/jobradar", isDirectory: true)
    }

    /// True when that folder holds a JobRadar setup.
    static var found: Bool {
        FileManager.default.fileExists(atPath: folder.appendingPathComponent("jobradar.yaml").path)
    }

    static var timerFile: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/com.jobradar.daily.plist")
    }

    /// Copies settings, profile, jobs and documents from `source` into `target`, which must not exist yet.
    /// Logs and lock files stay behind. When something cannot be copied, `target` is removed again.
    static func copy(from source: URL, to target: URL) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: target, withIntermediateDirectories: true)
        do {
            for name in ["jobradar.yaml", ".env", "data"] {
                let from = source.appendingPathComponent(name)
                guard fm.fileExists(atPath: from.path) else { continue }
                try fm.copyItem(at: from, to: target.appendingPathComponent(name))
            }
            for leftover in ["data/logs", "data/.cycle.lock"] {
                try? fm.removeItem(at: target.appendingPathComponent(leftover))
            }
        } catch {
            try? fm.removeItem(at: target)
            throw error
        }
    }

    /// The command line version could install a daily timer (launchd). The app scans by itself, so that
    /// timer is stopped and removed. Returns true when there was one.
    static func removeTimer() -> Bool {
        let fm = FileManager.default
        guard fm.fileExists(atPath: timerFile.path) else { return false }
        _ = Shell.run(URL(fileURLWithPath: "/bin/launchctl"), ["bootout", "gui/\(getuid())/com.jobradar.daily"],
                      timeout: 20)
        try? fm.removeItem(at: timerFile)
        return true
    }
}

/// Output and exit code of a command line tool.
nonisolated struct ShellResult: Sendable {
    var status: Int32
    var output: String

    var ok: Bool { status == 0 }

    /// The last lines of the output, for an error message.
    func tail(_ lines: Int = 12) -> String {
        output.split(whereSeparator: \.isNewline).suffix(lines).joined(separator: "\n")
    }
}

nonisolated enum Shell {
    /// Runs a tool and waits for it. Blocking: call it from a detached task.
    static func run(_ tool: URL, _ arguments: [String], environment: [String: String]? = nil,
                    timeout: TimeInterval = 900) -> ShellResult {
        let p = Process()
        p.executableURL = tool
        p.arguments = arguments
        if let environment { p.environment = environment }
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        p.standardInput = FileHandle.nullDevice
        do {
            try p.run()
        } catch {
            return ShellResult(status: -1, output: error.localizedDescription)
        }
        // a tool that hangs is ended, which also ends the read below
        let pid = p.processIdentifier
        let watchdog = DispatchWorkItem { _ = kill(pid, SIGTERM) }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: watchdog)
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        watchdog.cancel()
        return ShellResult(status: p.terminationStatus, output: String(decoding: data, as: UTF8.self))
    }

    /// The same without blocking the caller's thread.
    static func runDetached(_ tool: URL, _ arguments: [String], environment: [String: String]? = nil,
                            timeout: TimeInterval = 900) async -> ShellResult {
        await Task.detached {
            run(tool, arguments, environment: environment, timeout: timeout)
        }.value
    }
}

/// One stage of installing the engine, for the progress display.
struct EngineStep: Equatable {
    var index: Int
    var total: Int
    var title: String

    var fraction: Double { total > 0 ? Double(index - 1) / Double(total) : 0 }
}

enum EngineError: LocalizedError {
    case noWheel
    case download(String)
    case checksum
    case install(String, String)
    case tool(String, String)

    var errorDescription: String? {
        switch self {
        case .noWheel:
            return t("This copy of the app is incomplete: the engine package is missing. Download JobRadar again.")
        case .download(let message):
            return t("The download did not work: %@ Check the internet connection and try again.", message)
        case .checksum:
            return t("A downloaded file did not pass its integrity check. Try again; if this repeats, the network is altering downloads.")
        case .install(let step, let output):
            let head = t("\"%@\" did not finish. Check the internet connection and try again.", step)
            return output.isEmpty ? head : head + "\n\n" + output
        case .tool(let step, let output):
            let head = t("\"%@\" did not finish.", step)
            return output.isEmpty ? head : head + "\n\n" + output
        }
    }
}

/// What is installed in the runtime folder.
nonisolated struct EngineMarker: Sendable {
    var wheel = ""
    var uv = ""
    var jobBoards = false
    var jobBoardsError = ""

    static func read() -> EngineMarker {
        guard let data = try? Data(contentsOf: EnginePaths.marker),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return EngineMarker() }
        var m = EngineMarker()
        m.wheel = object["wheel"] as? String ?? ""
        m.uv = object["uv"] as? String ?? ""
        m.jobBoards = object["job_boards"] as? Bool ?? false
        m.jobBoardsError = object["job_boards_error"] as? String ?? ""
        return m
    }

    func write() {
        let object: [String: Any] = ["wheel": wheel, "uv": uv, "job_boards": jobBoards,
                                     "job_boards_error": jobBoardsError]
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
        else { return }
        try? data.write(to: EnginePaths.marker, options: .atomic)
    }
}

/// Installs the JobRadar engine (Python and its packages) inside Application Support, so nobody
/// needs a terminal. The engine itself ships inside the app as a Python wheel; Python and the
/// libraries are downloaded once with `uv`, whose download is checked against a pinned SHA-256.
@MainActor
enum EngineRuntime {
    static let uvVersion = "0.13.7"
    static let pythonVersion = "3.12"
    static let jobBoardsPackage = "python-jobspy>=1.4"

    private static var uvDownload: (url: String, sha256: String) {
        #if arch(arm64)
        return ("https://files.pythonhosted.org/packages/40/a5/8756c38ace102fa13fd4e653e8bc40e1f65924f1c0a0d23350339dac97e5/uv-0.13.7-py3-none-macosx_11_0_arm64.whl",
                "f91a229093163eefca89ea1b220a221d64c3beade05d03519a6584d1797a5a5f")
        #else
        return ("https://files.pythonhosted.org/packages/3d/5b/e0379e7b172659420b1ec99a8e8229830aa85ea59684847c80b1c959a056/uv-0.13.7-py3-none-macosx_10_12_x86_64.whl",
                "fd04bf01ba5f2829f4f94ca8f0c24a743f21e73d75045613ed6fc2fd66fc7bda")
        #endif
    }

    /// The engine package inside this app.
    static var bundledWheel: URL? {
        let wheels = Bundle.main.urls(forResourcesWithExtension: "whl", subdirectory: nil) ?? []
        return wheels.sorted { $0.lastPathComponent < $1.lastPathComponent }.last
    }

    /// Version of the engine inside this app ("1.0.0" from "jobradar-1.0.0-py3-none-any.whl").
    static var bundledVersion: String {
        let parts = bundledWheel?.lastPathComponent.split(separator: "-") ?? []
        return parts.count > 1 ? String(parts[1]) : ""
    }

    nonisolated static func sha256(of file: URL) throws -> String {
        let data = try Data(contentsOf: file)
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// True when the installed engine is the one inside this app.
    static func isCurrent() -> Bool {
        guard let wheel = bundledWheel, let hash = try? sha256(of: wheel) else { return false }
        return EngineMarker.read().wheel == hash && FileManager.default.isExecutableFile(atPath: EnginePaths.python.path)
    }

    static var jobBoardsInstalled: Bool { EngineMarker.read().jobBoards }

    /// Environment for `uv`: everything stays inside the runtime folder, nothing of the user's
    /// own Python setup is read or changed.
    private static var uvEnvironment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        for key in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "UV_PYTHON", "UV_PROJECT_ENVIRONMENT"] {
            env[key] = nil
        }
        env["UV_PYTHON_INSTALL_DIR"] = EnginePaths.runtime.appendingPathComponent("python", isDirectory: true).path
        env["UV_CACHE_DIR"] = EnginePaths.runtime.appendingPathComponent("cache", isDirectory: true).path
        env["UV_NO_CONFIG"] = "1"
        env["UV_NO_PROGRESS"] = "1"
        env["NO_COLOR"] = "1"
        if env["LANG"] == nil { env["LANG"] = "en_US.UTF-8" }
        return env
    }

    private static func uv(_ arguments: [String], step: String) async throws {
        let result = await Shell.runDetached(EnginePaths.uv, arguments, environment: uvEnvironment, timeout: 1200)
        guard result.ok else { throw EngineError.install(step, result.tail()) }
    }

    /// Installs or updates the engine. Does nothing when it is already current.
    static func ensureInstalled(includeJobBoards: Bool, progress: @escaping (EngineStep) -> Void) async throws {
        guard let wheel = bundledWheel, let hash = try? sha256(of: wheel) else { throw EngineError.noWheel }
        let fm = FileManager.default
        var marker = EngineMarker.read()
        let havePython = fm.isExecutableFile(atPath: EnginePaths.python.path)
        let current = marker.wheel == hash && havePython
        let wantJobBoards = includeJobBoards && !marker.jobBoards
        if current && !wantJobBoards { return }

        let total = (current ? 0 : 3) + (wantJobBoards ? 1 : 0)
        var index = 0
        func announce(_ title: String) -> String {
            index += 1
            progress(EngineStep(index: index, total: total, title: title))
            return title
        }
        try fm.createDirectory(at: EnginePaths.bin, withIntermediateDirectories: true)

        if !current {
            var step = announce(t("Downloading the installer"))
            if marker.uv != uvVersion || !fm.isExecutableFile(atPath: EnginePaths.uv.path) {
                try await installUV(step: step)
                marker.uv = uvVersion
                marker.write()
            }
            step = announce(t("Installing Python"))
            if !havePython {
                try await uv(["python", "install", pythonVersion, "--no-bin"], step: step)
                try await uv(["venv", "--python", pythonVersion, "--managed-python", "--clear", EnginePaths.venv.path],
                             step: step)
            }
            step = announce(t("Installing the JobRadar engine"))
            try await uv(["pip", "install", "--python", EnginePaths.python.path, "--reinstall-package", "jobradar",
                          wheel.path], step: step)
            marker.wheel = hash
            marker.write()
        }
        if wantJobBoards {
            let step = announce(t("Adding the job boards (LinkedIn, Indeed, Google Jobs)"))
            do {
                if !fm.isExecutableFile(atPath: EnginePaths.uv.path) { try await installUV(step: step) }
                try await uv(["pip", "install", "--python", EnginePaths.python.path, jobBoardsPackage], step: step)
                marker.jobBoards = true
                marker.jobBoardsError = ""
            } catch {
                // the app works without them (company career pages and manual links still do)
                marker.jobBoards = false
                marker.jobBoardsError = error.localizedDescription
            }
            marker.write()
        }
    }

    /// Downloads `uv` from PyPI, checks it against the pinned SHA-256 and unpacks the one binary.
    private static func installUV(step: String) async throws {
        let source = uvDownload
        guard let url = URL(string: source.url) else { throw EngineError.download(source.url) }
        let file: URL
        do {
            let (location, response) = try await URLSession.shared.download(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                try? FileManager.default.removeItem(at: location)
                throw EngineError.download("HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0).")
            }
            file = location
        } catch let error as EngineError {
            throw error
        } catch {
            throw EngineError.download(error.localizedDescription)
        }
        defer { try? FileManager.default.removeItem(at: file) }
        let digest = try? await Task.detached { try sha256(of: file) }.value
        guard digest == source.sha256 else { throw EngineError.checksum }
        let unzip = await Shell.runDetached(URL(fileURLWithPath: "/usr/bin/unzip"),
                                            ["-o", "-q", "-j", file.path, "uv-\(uvVersion).data/scripts/uv",
                                             "-d", EnginePaths.bin.path], timeout: 120)
        guard unzip.ok else { throw EngineError.install(step, unzip.tail()) }
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: EnginePaths.uv.path)
        guard FileManager.default.isExecutableFile(atPath: EnginePaths.uv.path) else {
            throw EngineError.install(step, "uv")
        }
    }

    /// Removes Python and the engine; the next start installs them again. The user's data stays.
    static func removeRuntime() {
        try? FileManager.default.removeItem(at: EnginePaths.runtime)
    }
}

/// The PATH of the user's login shell. Apps opened from the Dock get a minimal PATH, but the
/// engine needs the full one to find the `claude` command and a local Ollama.
nonisolated enum ShellPath {
    static func resolve(first: String) -> String {
        let home = NSHomeDirectory()
        var parts = [first]
        if let shell = loginShellPath() {
            parts += shell.split(separator: ":").map(String.init)
        }
        parts += ["\(home)/.local/bin", "\(home)/.claude/local", "/opt/homebrew/bin", "/usr/local/bin",
                  "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        var seen = Set<String>()
        return parts.filter { !$0.isEmpty && seen.insert($0).inserted }.joined(separator: ":")
    }

    private static func loginShellPath() -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = ["-ilc", "printf '__JR__%s__JR__' \"$PATH\""]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        do {
            try p.run()
        } catch {
            return nil
        }
        let deadline = Date().addingTimeInterval(8)
        while p.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if p.isRunning {
            p.terminate()
            return nil
        }
        let text = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        guard let start = text.range(of: "__JR__"),
              let end = text.range(of: "__JR__", range: start.upperBound..<text.endIndex) else { return nil }
        return String(text[start.upperBound..<end.lowerBound])
    }
}

/// `ps` and `lsof` helpers to recognise an engine this app started.
nonisolated enum ProcessCommand {
    /// Command line of a running process; empty when it is gone.
    static func line(of pid: pid_t) -> String {
        Shell.run(URL(fileURLWithPath: "/bin/ps"), ["-o", "command=", "-p", String(pid)], timeout: 10).output
    }

    /// PIDs that listen on a local TCP port.
    static func listeners(port: Int) -> [pid_t] {
        Shell.run(URL(fileURLWithPath: "/usr/sbin/lsof"), ["-nP", "-t", "-iTCP:\(port)", "-sTCP:LISTEN"], timeout: 10)
            .output
            .split(whereSeparator: \.isNewline)
            .compactMap { pid_t($0.trimmingCharacters(in: .whitespaces)) }
    }
}
