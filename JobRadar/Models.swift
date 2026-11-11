import Foundation
import SwiftUI

// JSON from the JobRadar engine (/api/v1). Keys arrive in snake_case and are
// converted by the decoder (see KeyStyle), so `llm_score` -> `llmScore`.

struct Badge: Codable, Hashable {
    var label: String
    var kind: String
}

struct JobSummary: Codable, Identifiable, Hashable {
    var id: String
    var title: String
    var company: String
    var location: String
    var track: String?
    var status: String
    var statusLabel: String
    var prescore: Double
    var llmScore: Double?
    var verdict: String?
    var postedAt: String?
    var firstSeen: String?
    var remoteLabel: String
    var employmentLabel: String
    var salaryText: String
    var url: String
    var applyUrl: String
    var sources: [String]
    var badges: [Badge]
    var liveStatus: String?
    var needsLocationCheck: Bool
    var statusChangedAt: String?
    var appliedAt: String?

    var postingURL: URL? { URL(string: applyUrl.isEmpty ? url : applyUrl) }
}

struct JobDetailExtra: Codable {
    var description: String
    var notes: String
    var filteredReason: String?
    var trackName: String?
    var evaluation: EvaluationRecord?
    var facts: [String: String]
    var documents: [DocumentInfo]
    var events: [JobEvent]
    var contacts: [Contact]
    var mailSignals: [MailSignal]?
}

/// Detail = the list row fields plus the extra detail fields (same JSON object, decoded twice).
struct JobDetail: Identifiable {
    var summary: JobSummary
    var extra: JobDetailExtra
    var id: String { summary.id }
}

struct EvaluationRecord: Codable {
    var id: Int
    var createdAt: String
    var provider: String
    var model: String
    var score: Double
    var verdict: String
    var result: EvaluationResult
    var notes: [String]
}

struct Requirement: Codable, Hashable {
    var requirement: String
    var importance: String
    var match: String
    var evidence: [String]
    var note: String

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        requirement = (try? c.decodeIfPresent(String.self, forKey: .requirement)) ?? ""
        importance = (try? c.decodeIfPresent(String.self, forKey: .importance)) ?? "must"
        match = (try? c.decodeIfPresent(String.self, forKey: .match)) ?? "gap"
        evidence = (try? c.decodeIfPresent([String].self, forKey: .evidence)) ?? []
        note = (try? c.decodeIfPresent(String.self, forKey: .note)) ?? ""
    }
}

struct Dimensions: Codable, Hashable {
    var cvMatch: Double?
    var northStar: Double?
    var comp: Double?
    var culture: Double?
    var redFlags: Double?
}

struct EvaluationResult: Codable {
    var track: String?
    var summary: String
    var requirements: [Requirement]
    var dimensions: Dimensions?
    var redFlags: [String]
    var strengths: [String]
    var gaps: [String]
    var globalScore: Double
    var verdict: String
    var legitimacy: String
    var legitimacyNotes: String
    var tailoringHints: [String]
    var interviewTopics: [String]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        track = try? c.decodeIfPresent(String.self, forKey: .track)
        summary = (try? c.decodeIfPresent(String.self, forKey: .summary)) ?? ""
        requirements = (try? c.decodeIfPresent([Requirement].self, forKey: .requirements)) ?? []
        dimensions = try? c.decodeIfPresent(Dimensions.self, forKey: .dimensions)
        redFlags = (try? c.decodeIfPresent([String].self, forKey: .redFlags)) ?? []
        strengths = (try? c.decodeIfPresent([String].self, forKey: .strengths)) ?? []
        gaps = (try? c.decodeIfPresent([String].self, forKey: .gaps)) ?? []
        globalScore = (try? c.decodeIfPresent(Double.self, forKey: .globalScore)) ?? 0
        verdict = (try? c.decodeIfPresent(String.self, forKey: .verdict)) ?? ""
        legitimacy = (try? c.decodeIfPresent(String.self, forKey: .legitimacy)) ?? ""
        legitimacyNotes = (try? c.decodeIfPresent(String.self, forKey: .legitimacyNotes)) ?? ""
        tailoringHints = (try? c.decodeIfPresent([String].self, forKey: .tailoringHints)) ?? []
        interviewTopics = (try? c.decodeIfPresent([String].self, forKey: .interviewTopics)) ?? []
    }
}

struct Violation: Codable, Hashable {
    var place: String?
    var message: String
    var severity: String?

    enum CodingKeys: String, CodingKey {
        case place = "where"
        case message
        case severity
    }
}

struct ValidationInfo: Codable {
    var ok: Bool?
    var violations: [Violation]?
    var removed: [String]?
    var review: ReviewInfo?
    var pdfCheck: PDFCheck?

    // Each part decodes on its own: a surprise in one never hides the document.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try? c.decodeIfPresent(Bool.self, forKey: .ok)
        violations = try? c.decodeIfPresent([Violation].self, forKey: .violations)
        removed = try? c.decodeIfPresent([String].self, forKey: .removed)
        review = try? c.decodeIfPresent(ReviewInfo.self, forKey: .review)
        pdfCheck = try? c.decodeIfPresent(PDFCheck.self, forKey: .pdfCheck)
    }
}

/// Second LLM reading of the tailored draft.
struct ReviewInfo: Codable {
    var enabled: Bool?
    var applied: Bool?
    var verdict: String?
    var summary: String?
    var issues: [ReviewIssue]?
    var error: String?
    var revisionError: String?
    var rejected: String?

    var statusText: String {
        if let error, !error.isEmpty { return t("could not run") }
        if applied == true { return t("revised with its suggestions") }
        if let rejected, !rejected.isEmpty { return t("revision rejected (unsupported claim)") }
        return verdict == "ok" ? t("found no problems") : t("has suggestions")
    }
}

struct ReviewIssue: Codable, Hashable {
    var place: String?
    var problem: String
    var suggestion: String?

    enum CodingKeys: String, CodingKey {
        case place = "where"
        case problem
        case suggestion
    }
}

struct PDFPages: Codable {
    var pages: Int?
}

struct KeywordCoverage: Codable {
    var covered: [String]
    var missing: [String]
}

/// Page count, text layer, contact details and requirement coverage of the generated PDFs.
struct PDFCheck: Codable {
    var engine: String?
    var ok: Bool?
    var issues: [String]?
    var cv: PDFPages?
    var letter: PDFPages?
    var keywords: KeywordCoverage?
}

struct DocumentInfo: Codable, Identifiable {
    var id: Int
    var version: Int
    var createdAt: String
    var language: String?
    var files: [String]
    var approved: Int?
    var validation: ValidationInfo?

    var isApproved: Bool { (approved ?? 0) == 1 }
}

struct JobEvent: Codable, Identifiable {
    var id: Int
    var ts: String
    var kind: String
    var detail: String?
}

struct Contact: Codable, Hashable {
    var firstName: String?
    var lastName: String?
    var position: String?
    var url: String?

    var name: String { [firstName, lastName].compactMap { $0 }.joined(separator: " ") }
}

struct TaskResult: Codable {
    var score: Double?
    var docId: Int?
    var version: Int?
    var validationOk: Bool?
    var checked: Int?
    var relevant: Int?
    var pending: Int?
    // connection tests (AI model, e-mail)
    var ok: Bool?
    var provider: String?
    var model: String?
    var reply: String?
    var seconds: Double?
    var message: String?
    var smtp: String?
    var imap: String?
    // profile draft from a CV, search setup suggestion
    var profile: ProfileData?
    var chars: Int?
    var tracks: [TrackSetup]?
    var titleExclude: [String]?
    var excludeSenior: Bool?
}

struct TaskInfo: Codable, Identifiable {
    var id: String
    var kind: String
    var jobId: String?
    var status: String
    var startedAt: String
    var finishedAt: String?
    var message: String
    var result: TaskResult?

    var isRunning: Bool { status == "running" }
}

struct TrackInfo: Codable, Hashable, Identifiable {
    var id: String
    var name: String
}

struct StatusInfo: Codable, Hashable, Identifiable {
    var id: String
    var label: String
}

struct ServerSummary: Codable {
    var version: String
    var counts: [String: Int]
    var views: [String: Int]
    var pendingEvaluation: Int
    var strongOpen: Int
    var strongThreshold: Double
    var followUpsDue: Int
    var lastCycle: String
    var lastError: String
    var running: Bool
    var llm: String
    var profileName: String
    var todoFacts: Int
    var tracks: [TrackInfo]
    var statuses: [StatusInfo]
    var lastQuickCycle: String?
    var mailSignalsPending: Int?
    var lastMailSync: String?
    var mailSyncError: String?
    var progress: CycleProgress?
    var llmReady: Bool?
    var profileMissing: [String]?
    var language: String?
}

/// Stage and progress of the running scan (progress bar).
struct CycleProgress: Codable, Equatable {
    var stage: String?
    var label: String?
    var detail: String?
    var done: Int?
    var total: Int?
    var fraction: Double?
    var quick: Bool?
    var startedAt: String?
    var updatedAt: String?
    var finishedAt: String?
    var newJobs: Int?
    var evaluated: Int?
    var ok: Bool?
}

struct ProgressResponse: Codable {
    var running: Bool
    var progress: CycleProgress?
}

struct HealthInfo: Codable {
    var ok: Bool
    var version: String
}

struct FunnelItem: Codable, Identifiable {
    var status: String
    var label: String
    var count: Int
    var id: String { status }
}

struct SourceStat: Codable, Identifiable {
    var source: String
    var jobs: Int
    var evaluated: Int
    var strong: Int
    var applied: Int
    var avgScore: Double?
    var id: String { source }
}

struct SourceHealth: Codable, Identifiable {
    var source: String
    var startedAt: String?
    var found: Int?
    var new: Int?
    var error: String?
    var warnings: [String]?
    var consecutiveEmpty: Int?
    var id: String { source }
}

struct StatsResponse: Codable {
    var funnel: [FunnelItem]
    var sources: [SourceStat]
    var health: [SourceHealth]
}

struct JobsResponse: Codable {
    var jobs: [JobSummary]
    /// Size of the whole view (older servers do not send it).
    var total: Int?
}

struct RunResponse: Codable {
    var started: Bool
}

struct ImportResponse: Codable {
    var jobId: String?
    var new: Bool
}

struct OKResponse: Codable {
    var ok: Bool
}

// MARK: E-mail replies (mail sync)

struct MailCandidate: Codable, Hashable {
    var jobId: String
    var title: String
    var company: String
    var score: Double?
}

struct MailSignal: Codable, Identifiable, Hashable {
    var id: Int
    var jobId: String?
    var receivedAt: String
    var sender: String
    var subject: String
    var snippet: String
    var kind: String
    var kindLabel: String
    var proposedStatus: String?
    var proposedLabel: String
    var candidates: [MailCandidate]
    var state: String
    var jobTitle: String
    var jobCompany: String
    var jobStatus: String

    var isPending: Bool { state == "pending" }

    var color: Color {
        switch kind {
        case "rejection": return .red
        case "interview", "assessment", "offer": return .green
        default: return .blue
        }
    }

    var stateLabel: String {
        switch state {
        case "applied": return t("accepted")
        case "dismissed": return t("ignored")
        case "info": return t("info")
        default: return t("waiting for review")
        }
    }
}

struct MailSignalsResponse: Codable {
    var signals: [MailSignal]
    var pending: Int
    var lastSync: String
    var lastError: String
}

struct ApplySignalResponse: Codable {
    var jobId: String
    var status: String
    var changed: Bool
}

// MARK: Application form answers

struct AnswerItem: Codable, Identifiable, Hashable {
    var id: String
    var label: String
    var de: String
    var en: String

    func text(_ language: String) -> String {
        language == "en" ? (en.isEmpty ? de : en) : (de.isEmpty ? en : de)
    }
}

struct AnswerGroup: Codable, Identifiable {
    var id: String
    var title: String
    var items: [AnswerItem]
}

struct AnswersResponse: Codable {
    var language: String
    /// Code of the main application language; the `de` field of every item holds the answer in it.
    var primary: String?
    var groups: [AnswerGroup]
    var missing: [String]
    var answersFile: String?
}

// MARK: Document diff (what was taken from the profile and how it was written)

struct DiffSource: Codable, Hashable {
    var id: String
    var text: String
}

struct DiffItem: Codable, Hashable {
    var text: String
    var sources: [DiffSource]
    var changed: Bool
    var question: String?
}

struct DiffHeadline: Codable {
    var text: String
    var original: String
}

struct DiffFact: Codable, Hashable {
    var id: String
    var text: String
}

struct DiffEntry: Codable, Identifiable {
    var entryId: String
    var title: String
    var organization: String
    var bullets: [DiffItem]
    var leftOut: [DiffFact]

    var id: String { entryId }
}

struct DiffOmitted: Codable, Hashable {
    var entryId: String
    var title: String
    var organization: String
}

struct DiffSkills: Codable {
    var chosen: [String]
    var notChosen: [String]
}

struct DiffLetter: Codable {
    var subject: String
    var paragraphs: [DiffItem]
}

struct DocumentDiff: Codable {
    var docId: Int
    var jobId: String
    var version: Int
    var headline: DiffHeadline
    var summary: DiffItem
    var experience: [DiffEntry]
    var omittedEntries: [DiffOmitted]
    var skills: DiffSkills
    var letter: DiffLetter
    var answers: [DiffItem]
}

// MARK: Skill gaps

struct GapExample: Codable, Hashable {
    var jobId: String
    var title: String
    var company: String
    var text: String
}

struct GapTerm: Codable, Identifiable {
    var term: String
    var jobs: Int
    var gap: Int
    var partial: Int
    var must: Int
    var nice: Int
    var avgScore: Double?
    var examples: [GapExample]

    var id: String { term }
}

struct GapOther: Codable, Hashable {
    var text: String
    var jobs: Int
}

struct GapsResponse: Codable {
    var jobsConsidered: Int
    var minScore: Double
    var days: Int
    var terms: [GapTerm]
    var other: [GapOther]
}

// MARK: - Setup: profile, search, AI model, e-mail

/// One statement about the candidate; tailored documents may only use these.
struct ProfileFact: Codable, Hashable {
    var id: String = ""
    var text: String = ""
    var skills: [String] = []
    /// Stable identity for lists while the server has not assigned an ID yet.
    var localID = UUID()

    private enum CodingKeys: String, CodingKey { case id, text, skills }

    init(id: String = "", text: String = "", skills: [String] = []) {
        self.id = id
        self.text = text
        self.skills = skills
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        text = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? ""
        skills = (try? c.decodeIfPresent([String].self, forKey: .skills)) ?? []
    }
}

/// A job, degree or project with its facts.
struct ProfileEntry: Codable, Hashable {
    var id: String = ""
    var kind: String = "work"
    var organization: String = ""
    var title: String = ""
    var location: String = ""
    var start: String = ""
    var end: String = ""
    var facts: [ProfileFact] = []
    var localID = UUID()

    private enum CodingKeys: String, CodingKey { case id, kind, organization, title, location, start, end, facts }

    init(kind: String = "work") {
        self.kind = kind
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "work"
        organization = (try? c.decodeIfPresent(String.self, forKey: .organization)) ?? ""
        title = (try? c.decodeIfPresent(String.self, forKey: .title)) ?? ""
        location = (try? c.decodeIfPresent(String.self, forKey: .location)) ?? ""
        start = (try? c.decodeIfPresent(String.self, forKey: .start)) ?? ""
        end = (try? c.decodeIfPresent(String.self, forKey: .end)) ?? ""
        facts = (try? c.decodeIfPresent([ProfileFact].self, forKey: .facts)) ?? []
    }

    var period: String {
        [start, end].filter { !$0.isEmpty }.joined(separator: " – ")
    }
}

struct ProfileLanguage: Codable, Hashable, Identifiable {
    var name: String = ""
    var level: String = ""
    var localID = UUID()
    var id: UUID { localID }

    private enum CodingKeys: String, CodingKey { case name, level }

    init(name: String = "", level: String = "") {
        self.name = name
        self.level = level
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        level = (try? c.decodeIfPresent(String.self, forKey: .level)) ?? ""
    }
}

/// One line of the skills section: a category and what belongs to it.
struct SkillGroup: Codable, Hashable, Identifiable {
    var name: String = ""
    var items: [String] = []
    var localID = UUID()
    var id: UUID { localID }

    private enum CodingKeys: String, CodingKey { case name, items }

    init(name: String = "", items: [String] = []) {
        self.name = name
        self.items = items
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        items = (try? c.decodeIfPresent([String].self, forKey: .items)) ?? []
    }
}

/// A link in the CV header (LinkedIn, GitHub, a portfolio).
struct ProfileLink: Codable, Hashable, Identifiable {
    var name: String = ""
    var url: String = ""
    var localID = UUID()
    var id: UUID { localID }

    private enum CodingKeys: String, CodingKey { case name, url }

    init(name: String = "", url: String = "") {
        self.name = name
        self.url = url
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        url = (try? c.decodeIfPresent(String.self, forKey: .url)) ?? ""
    }
}

struct ProfilePreferences: Codable, Hashable {
    var dealbreakers: [String] = []
    var niceToHave: [String] = []
    var salaryExpectation: String = ""
    var notes: String = ""

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        dealbreakers = (try? c.decodeIfPresent([String].self, forKey: .dealbreakers)) ?? []
        niceToHave = (try? c.decodeIfPresent([String].self, forKey: .niceToHave)) ?? []
        salaryExpectation = (try? c.decodeIfPresent(String.self, forKey: .salaryExpectation)) ?? ""
        notes = (try? c.decodeIfPresent(String.self, forKey: .notes)) ?? ""
    }
}

/// Rows of an editable list keep an identity of their own, so a field stays attached to its row
/// while rows are added, removed or reordered.
protocol LocallyIdentified {
    var localID: UUID { get }
}

extension ProfileFact: LocallyIdentified {}
extension ProfileEntry: LocallyIdentified {}
extension ProfileLanguage: LocallyIdentified {}
extension SkillGroup: LocallyIdentified {}
extension ProfileLink: LocallyIdentified {}
extension TrackSetup: LocallyIdentified {}
extension SearchLocation: LocallyIdentified {}
extension CompanyBoard: LocallyIdentified {}
extension FormAnswer: LocallyIdentified {}

/// The candidate's fact bank (data/profile.yaml on the server).
struct ProfileData: Codable, Hashable {
    var name: String = ""
    var headline: String = ""
    var email: String = ""
    var phone: String = ""
    var city: String = ""
    var address: String = ""
    /// Links and skills as lists, so their order survives the trip through JSON.
    var linkList: [ProfileLink] = []
    var summaryFacts: [ProfileFact] = []
    var experience: [ProfileEntry] = []
    var education: [ProfileEntry] = []
    var projects: [ProfileEntry] = []
    var skillGroups: [SkillGroup] = []
    var languages: [ProfileLanguage] = []
    var germanLevel: String = ""
    var citizenships: [String] = []
    var workPermit: String = ""
    var earliestStart: String = ""
    var preferences = ProfilePreferences()

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        headline = (try? c.decodeIfPresent(String.self, forKey: .headline)) ?? ""
        email = (try? c.decodeIfPresent(String.self, forKey: .email)) ?? ""
        phone = (try? c.decodeIfPresent(String.self, forKey: .phone)) ?? ""
        city = (try? c.decodeIfPresent(String.self, forKey: .city)) ?? ""
        address = (try? c.decodeIfPresent(String.self, forKey: .address)) ?? ""
        linkList = (try? c.decodeIfPresent([ProfileLink].self, forKey: .linkList)) ?? []
        summaryFacts = (try? c.decodeIfPresent([ProfileFact].self, forKey: .summaryFacts)) ?? []
        experience = (try? c.decodeIfPresent([ProfileEntry].self, forKey: .experience)) ?? []
        education = (try? c.decodeIfPresent([ProfileEntry].self, forKey: .education)) ?? []
        projects = (try? c.decodeIfPresent([ProfileEntry].self, forKey: .projects)) ?? []
        skillGroups = (try? c.decodeIfPresent([SkillGroup].self, forKey: .skillGroups)) ?? []
        languages = (try? c.decodeIfPresent([ProfileLanguage].self, forKey: .languages)) ?? []
        germanLevel = (try? c.decodeIfPresent(String.self, forKey: .germanLevel)) ?? ""
        citizenships = (try? c.decodeIfPresent([String].self, forKey: .citizenships)) ?? []
        workPermit = (try? c.decodeIfPresent(String.self, forKey: .workPermit)) ?? ""
        earliestStart = (try? c.decodeIfPresent(String.self, forKey: .earliestStart)) ?? ""
        preferences = (try? c.decodeIfPresent(ProfilePreferences.self, forKey: .preferences)) ?? ProfilePreferences()
    }

    var factCount: Int {
        summaryFacts.count + (experience + education + projects).reduce(0) { $0 + $1.facts.count }
    }

    var skillCount: Int { skillGroups.reduce(0) { $0 + $1.items.count } }
}

struct ProfileEnvelope: Codable {
    var exists: Bool
    var profile: ProfileData
    var missing: [String]
    var todoFacts: [String]?
}

struct ProfileBody: Encodable {
    var profile: ProfileData
}

/// One search direction with its keywords.
struct TrackSetup: Codable, Hashable {
    var id: String = ""
    var name: String = ""
    var priority: Int = 1
    var enabled: Bool = true
    var titleKeywords: [String] = []
    var domainKeywords: [String] = []
    var searchTerms: [String] = []
    var northStar: String = ""
    var nationwide: Bool = false
    var localID = UUID()

    private enum CodingKeys: String, CodingKey {
        case id, name, priority, enabled, titleKeywords, domainKeywords, searchTerms, northStar, nationwide
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        priority = (try? c.decodeIfPresent(Int.self, forKey: .priority)) ?? 1
        enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? true
        titleKeywords = (try? c.decodeIfPresent([String].self, forKey: .titleKeywords)) ?? []
        domainKeywords = (try? c.decodeIfPresent([String].self, forKey: .domainKeywords)) ?? []
        searchTerms = (try? c.decodeIfPresent([String].self, forKey: .searchTerms)) ?? []
        northStar = (try? c.decodeIfPresent(String.self, forKey: .northStar)) ?? ""
        nationwide = (try? c.decodeIfPresent(Bool.self, forKey: .nationwide)) ?? false
    }
}

struct SearchLocation: Codable, Hashable, Identifiable {
    var city: String = ""
    var radiusKm: Int = 50
    var localID = UUID()
    var id: UUID { localID }

    private enum CodingKeys: String, CodingKey { case city, radiusKm }

    init(city: String = "", radiusKm: Int = 50) {
        self.city = city
        self.radiusKm = radiusKm
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        city = (try? c.decodeIfPresent(String.self, forKey: .city)) ?? ""
        radiusKm = (try? c.decodeIfPresent(Int.self, forKey: .radiusKm)) ?? 50
    }
}

struct CompanyBoard: Codable, Hashable, Identifiable {
    var name: String = ""
    var ats: String = "greenhouse"
    var slug: String = ""
    var url: String = ""
    var search: String = ""
    var maxPages: Int = 20
    var enabled: Bool = true
    var localID = UUID()
    var id: UUID { localID }

    private enum CodingKeys: String, CodingKey { case name, ats, slug, url, search, maxPages, enabled }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        ats = (try? c.decodeIfPresent(String.self, forKey: .ats)) ?? "greenhouse"
        slug = (try? c.decodeIfPresent(String.self, forKey: .slug)) ?? ""
        url = (try? c.decodeIfPresent(String.self, forKey: .url)) ?? ""
        search = (try? c.decodeIfPresent(String.self, forKey: .search)) ?? ""
        maxPages = (try? c.decodeIfPresent(Int.self, forKey: .maxPages)) ?? 20
        enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? true
    }
}

struct JobBoardsSource: Codable, Hashable {
    var enabled: Bool = true
    var sites: [String] = []
    var installed: Bool? = nil
}

struct ToggleSource: Codable, Hashable {
    var enabled: Bool = false
    var available: Bool? = nil
}

struct SearchSources: Codable, Hashable {
    var jobspy = JobBoardsSource()
    var arbeitsagentur = ToggleSource()
    var freehire = ToggleSource()
    var companies: [CompanyBoard] = []
}

struct SearchFilters: Codable, Hashable {
    var titleExclude: [String] = []
    var companyBlacklist: [String] = []
    var excludeSenior: Bool = true
    var excludeAgencies: Bool = false
    var requireTrackMatch: Bool = true
}

struct SearchScoring: Codable, Hashable {
    var llmMaxPerRun: Int = 20
    var prescoreMin: Double = 40
    var applyThreshold: Double = 4.0
}

struct CountryOption: Codable, Hashable, Identifiable {
    var code: String
    var name: String
    var id: String { code }
}

struct SearchOptions: Codable, Hashable {
    var countries: [CountryOption] = []
    var employmentTypes: [String] = []
    var atsTypes: [String] = []
    var jobspySites: [String] = []
}

/// What to look for, where, and on which sources (GET/PUT /api/v1/search).
struct SearchSetup: Codable, Hashable {
    var country: String = ""
    var countryName: String = ""
    var locations: [SearchLocation] = []
    var includeRemote: Bool = true
    var maxAgeDays: Int = 120
    var employmentTypes: [String] = ["fulltime"]
    var tracks: [TrackSetup] = []
    var sources = SearchSources()
    var filters = SearchFilters()
    var scoring = SearchScoring()
    var options: SearchOptions? = nil
}

struct SuggestBody: Encodable {
    var roles: String
    var country: String
    var `where`: String
}

struct ClaudeCodeState: Codable, Hashable {
    var found: Bool = false
    var path: String = ""
    var version: String = ""
}

struct KeyState: Codable, Hashable {
    var anthropic: Bool = false
    var openai: Bool = false
}

/// The AI model connection (GET/PUT /api/v1/ai).
struct AIState: Codable, Hashable {
    var provider: String = "none"
    var active: String = ""
    var ready: Bool = false
    var error: String = ""
    var label: String = ""
    var fastModel: String = ""
    var smartModel: String = ""
    var baseUrl: String = ""
    var keySet = KeyState()
    var openaiBaseUrl: String = ""
    var ollamaBaseUrl: String = ""
    var claude = ClaudeCodeState()
}

struct AIBody: Encodable {
    var provider: String
    var fastModel: String
    var smartModel: String
    var baseUrl: String
    var apiKey: String?
}

struct ModelList: Codable {
    var provider: String
    var models: [String]
}

struct SetupProfileState: Codable, Hashable {
    var exists: Bool = false
    var name: String = ""
    var missing: [String] = []
    var error: String = ""
}

struct SetupAIState: Codable, Hashable {
    var provider: String = "none"
    var ready: Bool = false
    var error: String = ""
}

struct SetupSearchState: Codable, Hashable {
    var tracks: Int = 0
    var country: String = ""
}

/// What a new user still has to do before the first scan (GET /api/v1/setup).
struct SetupState: Codable, Hashable {
    var version: String = ""
    var language: String = ""
    var profile = SetupProfileState()
    var ai = SetupAIState()
    var search = SetupSearchState()
    var ready: Bool = false
}

/// General settings kept by the engine (GET/PUT /api/v1/app-settings).
struct AppSettings: Codable, Hashable {
    var language: String = "en"
    /// Language of the CV and letter when a posting's language is unknown; empty = by country.
    var documentLanguage: String = ""
    var documentLanguageEffective: String = ""
    /// Language of evaluation texts; "auto" = the interface language.
    var outputLanguage: String = "auto"
    var followUpDays: Int = 10
}

struct AppSettingsBody: Encodable {
    var language: String?
    var documentLanguage: String?
    var outputLanguage: String?
    var followUpDays: Int?
}

struct MailSettings: Codable, Hashable {
    var user: String = ""
    var to: String = ""
    var hasPassword: Bool = false
    var smtpHost: String = "smtp.gmail.com"
    var smtpPort: Int = 587
    var imapHost: String = "imap.gmail.com"
    var imapPort: Int = 993
    var digest: Bool = true
    var instant: Bool = true
    var sync: Bool = true
    var lastSync: String = ""
    var lastError: String = ""
}

struct MailBody: Encodable {
    var user: String?
    var password: String?
    var to: String?
    var smtpHost: String?
    var smtpPort: Int?
    var imapHost: String?
    var imapPort: Int?
    var digest: Bool?
    var instant: Bool?
    var sync: Bool?
}

/// One reusable answer for application forms (Profile > Form answers).
struct FormAnswer: Codable, Hashable {
    var id: String = ""
    var label: String = ""
    var primary: String = ""
    var en: String = ""
    var localID = UUID()

    private enum CodingKeys: String, CodingKey { case id, label, primary, en }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        label = (try? c.decodeIfPresent(String.self, forKey: .label)) ?? ""
        primary = (try? c.decodeIfPresent(String.self, forKey: .primary)) ?? ""
        en = (try? c.decodeIfPresent(String.self, forKey: .en)) ?? ""
    }
}

struct FormAnswers: Codable {
    var primary: String = "en"
    var items: [FormAnswer] = []
}

struct DetectBody: Encodable {
    var url: String
    var name: String
}

struct DetectResponse: Codable {
    var companies: [CompanyBoard]
}
