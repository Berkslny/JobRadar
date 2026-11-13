import Foundation

/// Where the JobRadar engine runs: started by the app on this Mac, or on a remote server.
enum ServerMode: String {
    case local
    case remote
}

struct ServerConfig: Equatable {
    var mode: ServerMode = .local
    /// Workspace folder (jobradar.yaml and data/) for the engine on this Mac.
    var localFolder: String = ""
    var baseURL: String
    var token: String
    var accessClientID: String
    var accessClientSecret: String

    var isComplete: Bool {
        switch mode {
        case .local:
            return !localFolder.trimmingCharacters(in: .whitespaces).isEmpty
        case .remote:
            return !baseURL.trimmingCharacters(in: .whitespaces).isEmpty
                && !token.trimmingCharacters(in: .whitespaces).isEmpty
        }
    }

    var normalizedBaseURL: String {
        var s = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        if !s.isEmpty && !s.contains("://") { s = "https://" + s }
        return s
    }
}

enum APIError: LocalizedError {
    case notConfigured
    case badURL
    case unauthorized(String)
    case accessBlocked
    case server(Int, String)
    case transport(String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured: return t("The server address and API key are missing. Enter them in Settings (⌘,).")
        case .badURL: return t("The server address is not valid. Example: https://jobradar.example.com")
        case .unauthorized(let m): return t("Not authorized: %@", m)
        case .accessBlocked: return t("Cloudflare Access stopped the request. Enter the service token in Settings.")
        case .server(_, let m): return m
        case .transport(let m): return t("Could not reach JobRadar: %@", m)
        case .decoding(let m): return t("Could not read the answer: %@", m)
        }
    }

    /// HTTP status of a server error (409 = something is missing, e.g. the profile).
    var status: Int? {
        if case .server(let code, _) = self { return code }
        return nil
    }
}

/// A coding key made at run time (key conversion between snake_case JSON and camelCase Swift).
nonisolated struct AnyKey: CodingKey {
    var stringValue: String
    var intValue: Int?

    init(_ string: String) {
        stringValue = string
        intValue = nil
    }

    init?(stringValue: String) {
        self.init(stringValue)
    }

    init?(intValue: Int) {
        stringValue = String(intValue)
        self.intValue = intValue
    }
}

/// JSON keys are snake_case, Swift properties camelCase. Keys of dictionaries that hold data
/// (fact IDs, status names) are not field names and must pass through unchanged.
nonisolated enum KeyStyle {
    /// True when the last key of `path` is a key of such a dictionary: a job's `facts`,
    /// the summary's `counts` and `views`.
    static func isData(_ path: [CodingKey]) -> Bool {
        guard path.count >= 2 else { return false }
        switch path[path.count - 2].stringValue {
        case "facts", "counts", "views":
            return true
        default:
            return false
        }
    }

    static func camel(_ s: String) -> String {
        guard s.contains("_") else { return s }
        let parts = s.split(separator: "_", omittingEmptySubsequences: true)
        guard let first = parts.first else { return s }
        return String(first) + parts.dropFirst().map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined()
    }

    static func snake(_ s: String) -> String {
        var out = ""
        for ch in s {
            if ch.isUppercase {
                if !out.isEmpty { out.append("_") }
                out.append(contentsOf: ch.lowercased())
            } else {
                out.append(ch)
            }
        }
        return out
    }

    static func decoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .custom { path in
            guard let key = path.last else { return AnyKey("") }
            return isData(path) ? key : AnyKey(camel(key.stringValue))
        }
        return d
    }

    static func encoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .custom { path in
            guard let key = path.last else { return AnyKey("") }
            return isData(path) ? key : AnyKey(snake(key.stringValue))
        }
        return e
    }
}

/// Talks to the JobRadar engine. Everything runs on the main actor; network waits
/// do not block it, and the payloads are small.
@MainActor
final class APIClient {
    var config: ServerConfig
    private let session: URLSession
    private let decoder = KeyStyle.decoder()
    private let encoder = KeyStyle.encoder()

    init(config: ServerConfig) {
        self.config = config
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 90
        c.httpCookieStorage = nil
        session = URLSession(configuration: c)
    }

    // MARK: Jobs

    func health() async throws -> HealthInfo {
        try await get("/api/v1/health", authorized: false)
    }

    func summary() async throws -> ServerSummary {
        try await get("/api/v1/summary")
    }

    /// One page of a view; `total` in the answer is the size of the whole view.
    func jobsPage(view: String, track: String, query: String, order: String,
                  limit: Int, offset: Int = 0) async throws -> JobsResponse {
        var q = [URLQueryItem(name: "view", value: view), URLQueryItem(name: "order", value: order),
                 URLQueryItem(name: "limit", value: String(limit)), URLQueryItem(name: "offset", value: String(offset))]
        if !track.isEmpty { q.append(URLQueryItem(name: "track", value: track)) }
        let trimmed = query.trimmingCharacters(in: .whitespaces)
        if !trimmed.isEmpty { q.append(URLQueryItem(name: "q", value: trimmed)) }
        return try await get("/api/v1/jobs", query: q)
    }

    /// The whole view (for small views such as the application pipeline).
    func jobs(view: String, track: String, query: String, order: String) async throws -> [JobSummary] {
        try await jobsPage(view: view, track: track, query: query, order: order, limit: 10000).jobs
    }

    func job(_ id: String) async throws -> JobDetail {
        let data = try await send(try request("GET", "/api/v1/jobs/\(escape(id))"))
        let summary: JobSummary = try decode(data)
        let extra: JobDetailExtra = try decode(data)
        return JobDetail(summary: summary, extra: extra)
    }

    func setStatus(_ id: String, status: String, note: String = "") async throws -> JobSummary {
        try await post("/api/v1/jobs/\(escape(id))/status", json: ["status": status, "note": note])
    }

    func setNotes(_ id: String, notes: String) async throws {
        let _: OKResponse = try await post("/api/v1/jobs/\(escape(id))/notes", json: ["notes": notes])
    }

    func evaluate(_ id: String) async throws -> TaskInfo {
        try await post("/api/v1/jobs/\(escape(id))/evaluate")
    }

    func tailor(_ id: String, language: String) async throws -> TaskInfo {
        try await post("/api/v1/jobs/\(escape(id))/tailor", json: ["language": language])
    }

    func task(_ id: String) async throws -> TaskInfo {
        try await get("/api/v1/tasks/\(escape(id))")
    }

    func approve(docID: Int) async throws {
        let _: OKResponse = try await post("/api/v1/docs/\(docID)/approve")
    }

    func importURL(_ url: String) async throws -> ImportResponse {
        try await post("/api/v1/import/url", json: ["url": url])
    }

    func run() async throws -> RunResponse {
        try await post("/api/v1/run")
    }

    func stats() async throws -> StatsResponse {
        try await get("/api/v1/stats")
    }

    func progress() async throws -> ProgressResponse {
        try await get("/api/v1/progress")
    }

    func answers(jobID: String) async throws -> AnswersResponse {
        try await get("/api/v1/jobs/\(escape(jobID))/answers")
    }

    func diff(docID: Int) async throws -> DocumentDiff {
        try await get("/api/v1/docs/\(docID)/diff")
    }

    func mailSignals(state: String = "all") async throws -> MailSignalsResponse {
        try await get("/api/v1/mail-signals", query: [URLQueryItem(name: "state", value: state),
                                                       URLQueryItem(name: "limit", value: "150")])
    }

    func mailSync() async throws -> TaskInfo {
        try await post("/api/v1/mail-sync")
    }

    func applySignal(_ id: Int, jobID: String?) async throws -> ApplySignalResponse {
        try await post("/api/v1/mail-signals/\(id)/apply", json: ["job_id": jobID ?? ""])
    }

    func dismissSignal(_ id: Int) async throws {
        let _: OKResponse = try await post("/api/v1/mail-signals/\(id)/dismiss")
    }

    func gaps(minScore: Double = 3.0) async throws -> GapsResponse {
        try await get("/api/v1/gaps", query: [URLQueryItem(name: "min_score", value: String(format: "%.1f", minScore))])
    }

    // MARK: Setup

    func setup() async throws -> SetupState {
        try await get("/api/v1/setup")
    }

    func appSettings() async throws -> AppSettings {
        try await get("/api/v1/app-settings")
    }

    func saveAppSettings(_ body: AppSettingsBody) async throws -> AppSettings {
        try await send("PUT", "/api/v1/app-settings", body: body)
    }

    func ai() async throws -> AIState {
        try await get("/api/v1/ai")
    }

    func saveAI(_ body: AIBody) async throws -> AIState {
        try await send("PUT", "/api/v1/ai", body: body)
    }

    func aiModels(provider: String, baseURL: String) async throws -> [String] {
        let list: ModelList = try await get("/api/v1/ai/models", query: [
            URLQueryItem(name: "provider", value: provider), URLQueryItem(name: "base_url", value: baseURL)])
        return list.models
    }

    func testAI() async throws -> TaskInfo {
        try await post("/api/v1/ai/test")
    }

    func profile() async throws -> ProfileEnvelope {
        try await get("/api/v1/profile")
    }

    func saveProfile(_ profile: ProfileData) async throws -> ProfileEnvelope {
        try await send("PUT", "/api/v1/profile", body: ProfileBody(profile: profile))
    }

    /// Sends a CV file; the task's result is a profile draft (nothing is saved on the server).
    func importCV(file: URL) async throws -> TaskInfo {
        let data: Data
        do {
            data = try Data(contentsOf: file)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
        var req = try request("POST", "/api/v1/profile/import",
                              query: [URLQueryItem(name: "filename", value: file.lastPathComponent)],
                              body: data, timeout: 120)
        req.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        return try decode(try await send(req))
    }

    func search() async throws -> SearchSetup {
        try await get("/api/v1/search")
    }

    func saveSearch(_ setup: SearchSetup) async throws -> SearchSetup {
        try await send("PUT", "/api/v1/search", body: setup)
    }

    func suggestSearch(roles: String, country: String, where place: String) async throws -> TaskInfo {
        try await send("POST", "/api/v1/search/suggest", body: SuggestBody(roles: roles, country: country, where: place))
    }

    func detectCompany(url: String, name: String) async throws -> [CompanyBoard] {
        let res: DetectResponse = try await send("POST", "/api/v1/companies/detect", body: DetectBody(url: url, name: name))
        return res.companies
    }

    func formAnswers() async throws -> FormAnswers {
        try await get("/api/v1/answers/edit")
    }

    func saveFormAnswers(_ answers: FormAnswers) async throws -> FormAnswers {
        try await send("PUT", "/api/v1/answers/edit", body: answers)
    }

    func mailSettings() async throws -> MailSettings {
        try await get("/api/v1/mail-settings")
    }

    func saveMailSettings(_ body: MailBody) async throws -> MailSettings {
        try await send("PUT", "/api/v1/mail-settings", body: body)
    }

    func testMail() async throws -> TaskInfo {
        try await post("/api/v1/mail-settings/test")
    }

    // MARK: Smart matching and measurements

    func matching() async throws -> MatchingState {
        try await get("/api/v1/matching")
    }

    func saveMatching(_ body: MatchingBody) async throws -> MatchingState {
        try await send("PUT", "/api/v1/matching", body: body)
    }

    /// Loads the embedding model and embeds one text; the first call of the built-in model downloads it.
    func testMatching() async throws -> TaskInfo {
        try await post("/api/v1/matching/test")
    }

    /// Scores the postings that are already stored (a scan does the same for new ones).
    func runMatching() async throws -> TaskInfo {
        try await post("/api/v1/matching/run")
    }

    func bench() async throws -> BenchReport {
        try await get("/api/v1/bench")
    }

    func labelQueue(limit: Int = 10) async throws -> LabelQueueResponse {
        try await get("/api/v1/labels/queue", query: [URLQueryItem(name: "limit", value: String(limit))])
    }

    /// Your verdict on a posting: "good", "maybe", "bad", "skip" (cannot tell) or "" (take it back).
    func setLabel(_ id: String, label: String) async throws {
        let _: LabelResponse = try await send("PUT", "/api/v1/jobs/\(escape(id))/label", body: LabelBody(label: label))
    }

    // MARK: Files

    /// Downloads a generated file into the app's temporary folder and returns its location.
    func downloadFile(docID: Int, name: String) async throws -> URL {
        let data = try await send(try request("GET", "/api/v1/docs/\(docID)/files/\(escape(name))"))
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("JobRadar", isDirectory: true)
            .appendingPathComponent(String(docID), isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let target = folder.appendingPathComponent(name)
        try data.write(to: target, options: .atomic)
        return target
    }

    /// Saves a consistent copy of the database into `folder`.
    func backup(into folder: URL) async throws -> URL {
        let data = try await send(try request("GET", "/api/v1/backup", timeout: 300))
        guard data.starts(with: Data("SQLite format 3".utf8)) else {
            throw APIError.decoding(t("the backup is not a database file"))
        }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        let target = folder.appendingPathComponent("jobradar-\(f.string(from: Date())).db")
        try data.write(to: target, options: .atomic)
        return target
    }

    /// Link to the same job in the web panel (remote server).
    func panelURL(jobID: String) -> URL? {
        URL(string: "\(config.normalizedBaseURL)/jobs/\(jobID)")
    }

    // MARK: Plumbing

    private func escape(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? s
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = [], authorized: Bool = true) async throws -> T {
        let data = try await send(try request("GET", path, query: query, authorized: authorized))
        return try decode(data)
    }

    private func post<T: Decodable>(_ path: String, json: [String: String]? = nil) async throws -> T {
        var body: Data?
        if let json {
            body = try JSONSerialization.data(withJSONObject: json)
        }
        let data = try await send(try request("POST", path, body: body))
        return try decode(data)
    }

    /// Sends an Encodable body (camelCase properties become snake_case keys) and decodes the answer.
    private func send<T: Decodable, B: Encodable>(_ method: String, _ path: String, body: B) async throws -> T {
        let payload: Data
        do {
            payload = try encoder.encode(body)
        } catch {
            throw APIError.decoding(String(String(describing: error).prefix(300)))
        }
        let data = try await send(try request(method, path, body: payload))
        return try decode(data)
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(String(String(describing: error).prefix(300)))
        }
    }

    private func request(_ method: String, _ path: String, query: [URLQueryItem] = [], body: Data? = nil,
                         authorized: Bool = true, timeout: TimeInterval = 90) throws -> URLRequest {
        let base = config.normalizedBaseURL
        guard !base.isEmpty else { throw APIError.notConfigured }
        let token = config.token.trimmingCharacters(in: .whitespaces)
        if authorized && token.isEmpty && config.mode == .remote { throw APIError.notConfigured }
        guard var comps = URLComponents(string: base + path),
              comps.scheme == "https" || comps.scheme == "http", comps.host != nil else { throw APIError.badURL }
        if !query.isEmpty { comps.queryItems = query }
        guard let url = comps.url else { throw APIError.badURL }
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue(LanguageStore.shared.code, forHTTPHeaderField: "X-JobRadar-Lang")
        if authorized && !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let cid = config.accessClientID.trimmingCharacters(in: .whitespaces)
        let secret = config.accessClientSecret.trimmingCharacters(in: .whitespaces)
        if !cid.isEmpty && !secret.isEmpty {
            req.setValue(cid, forHTTPHeaderField: "CF-Access-Client-Id")
            req.setValue(secret, forHTTPHeaderField: "CF-Access-Client-Secret")
        }
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return req
    }

    private func send(_ req: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.transport("no HTTP response") }
        // Cloudflare Access redirects unauthenticated requests to its login page.
        if let finalHost = http.url?.host, let requestHost = req.url?.host, finalHost != requestHost {
            throw APIError.accessBlocked
        }
        let type = http.value(forHTTPHeaderField: "Content-Type") ?? ""
        if http.statusCode == 401 || http.statusCode == 403 {
            if type.contains("text/html") { throw APIError.accessBlocked }
            throw APIError.unauthorized(Self.detail(from: data) ?? t("check the API key"))
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = Self.detail(from: data) ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            throw APIError.server(http.statusCode, message)
        }
        return data
    }

    private static func detail(from data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data),
              let dict = object as? [String: Any] else { return nil }
        if let s = dict["detail"] as? String { return s }
        if let list = dict["detail"] as? [[String: Any]], let first = list.first, let msg = first["msg"] as? String {
            return msg
        }
        return nil
    }
}
