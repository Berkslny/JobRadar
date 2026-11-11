import AppKit
import SwiftUI

/// One way of connecting an AI model.
struct AIProviderOption: Identifiable {
    let id: String
    let icon: String

    var title: String {
        switch id {
        case "claude_cli": return t("Claude Code on this Mac")
        case "anthropic": return t("Anthropic API key")
        case "openai": return t("OpenAI-compatible service")
        case "ollama": return t("Ollama on this Mac")
        default: return t("No AI model")
        }
    }

    var subtitle: String {
        switch id {
        case "claude_cli": return t("Uses your own Claude subscription through the Claude Code program.")
        case "anthropic": return t("Claude models, paid per use with your own key.")
        case "openai": return t("OpenAI, OpenRouter, Groq, Mistral, Gemini, LM Studio and others.")
        case "ollama": return t("Free and private: the model runs on your Mac.")
        default: return t("Jobs are still collected and sorted, but not evaluated, and no documents are written.")
        }
    }

    static let all: [AIProviderOption] = [
        AIProviderOption(id: "claude_cli", icon: "terminal"),
        AIProviderOption(id: "anthropic", icon: "key"),
        AIProviderOption(id: "openai", icon: "network"),
        AIProviderOption(id: "ollama", icon: "desktopcomputer"),
        AIProviderOption(id: "none", icon: "nosign"),
    ]
}

/// A service that speaks the OpenAI protocol.
struct OpenAIPreset: Identifiable {
    let id: String
    let name: String
    let url: String

    static let all: [OpenAIPreset] = [
        OpenAIPreset(id: "openai", name: "OpenAI", url: "https://api.openai.com/v1"),
        OpenAIPreset(id: "openrouter", name: "OpenRouter", url: "https://openrouter.ai/api/v1"),
        OpenAIPreset(id: "groq", name: "Groq", url: "https://api.groq.com/openai/v1"),
        OpenAIPreset(id: "mistral", name: "Mistral", url: "https://api.mistral.ai/v1"),
        OpenAIPreset(id: "gemini", name: "Google Gemini", url: "https://generativelanguage.googleapis.com/v1beta/openai"),
        OpenAIPreset(id: "lmstudio", name: "LM Studio", url: "http://localhost:1234/v1"),
    ]
}

/// Choose and connect the AI model. Used in Settings and in the first-run assistant.
struct AIModelForm: View {
    @Environment(AppModel.self) private var model
    @State private var state: AIState? = nil
    @State private var provider = "none"
    @State private var fast = ""
    @State private var smart = ""
    @State private var baseURL = ""
    @State private var apiKey = ""
    @State private var models: [String] = []
    @State private var busy = false
    @State private var loadingModels = false
    @State private var error = ""
    @State private var result = ""
    @State private var resultOK = false
    /// Called after the model was saved and answered a test question.
    var onReady: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if state == nil && error.isEmpty {
                ProgressView().frame(maxWidth: .infinity)
            }
            if state != nil {
                providerList
                details
                actions
            }
            if !error.isEmpty { Banner(kind: .error, text: error) }
            if !result.isEmpty { Banner(kind: resultOK ? .success : .warning, text: result) }
        }
        .task { await load() }
    }

    // MARK: Parts

    private var providerList: some View {
        VStack(spacing: 8) {
            ForEach(AIProviderOption.all) { option in
                ProviderRow(option: option, selected: provider == option.id) {
                    choose(option.id)
                }
            }
        }
    }

    @ViewBuilder
    private var details: some View {
        switch provider {
        case "claude_cli": claudeDetails
        case "anthropic": anthropicDetails
        case "openai": openAIDetails
        case "ollama": ollamaDetails
        default: EmptyView()
        }
    }

    private var claudeDetails: some View {
        SectionBox(title: t("Claude Code"), systemImage: "terminal") {
            if let claude = state?.claude, claude.found {
                Label(t("Found: %@", claude.version.isEmpty ? claude.path : claude.version), systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text(t("JobRadar runs the Claude Code program as it is installed on this Mac. You sign in to Claude Code yourself, with your own account. JobRadar never sees, asks for or stores your Claude login."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Button(t("Open Claude Code in Terminal to sign in…")) { openClaude(claude.path) }
                    .buttonStyle(.glass).plainGlass()
                Text(t("Usage counts against your own Claude plan under Anthropic's terms."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                modelFields(fastHint: "haiku", smartHint: "sonnet")
            } else {
                Label(t("Claude Code is not installed on this Mac."), systemImage: "xmark.circle")
                    .foregroundStyle(.orange)
                Text(t("Install Claude Code, open it once and sign in with your Claude account. Then come back and press \"Check again\"."))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                HStack {
                    if let link = URL(string: "https://claude.com/claude-code") {
                        Link(t("Get Claude Code"), destination: link)
                    }
                    Button(t("Check again")) { Task { await load(keepChoice: true) } }
                        .buttonStyle(.glass).plainGlass()
                }
            }
        }
    }

    private var anthropicDetails: some View {
        SectionBox(title: t("Anthropic API"), systemImage: "key") {
            keyField(saved: state?.keySet.anthropic == true)
            if let link = URL(string: "https://console.anthropic.com/settings/keys") {
                Link(t("Create a key in the Anthropic Console"), destination: link).font(.callout)
            }
            modelFields(fastHint: "claude-haiku-5-5", smartHint: "claude-sonnet-5-5")
            Text(t("This is paid per use and billed by Anthropic to your key."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var openAIDetails: some View {
        SectionBox(title: t("OpenAI-compatible service"), systemImage: "network") {
            HStack {
                Text(t("Service")).foregroundStyle(.secondary)
                Menu(presetName) {
                    ForEach(OpenAIPreset.all) { preset in
                        Button(preset.name) {
                            baseURL = preset.url
                            models = []
                        }
                    }
                }
                .fixedSize()
            }
            TextField(t("Address of the service"), text: $baseURL, prompt: Text(verbatim: "https://api.openai.com/v1"))
                .textFieldStyle(.roundedBorder)
            keyField(saved: state?.keySet.openai == true)
            modelFields(fastHint: t("model name"), smartHint: t("model name"))
            Text(t("Hosted services are paid per use and billed to your key. A server on this Mac (LM Studio) is free and needs no key."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var ollamaDetails: some View {
        SectionBox(title: t("Ollama"), systemImage: "desktopcomputer") {
            Text(t("Ollama runs open models on your own Mac. Install it, download a model (for example in the Ollama app), then load the list here. Larger models judge jobs better but need a Mac with plenty of memory."))
                .font(.callout)
                .foregroundStyle(.secondary)
            if let link = URL(string: "https://ollama.com/download") {
                Link(t("Get Ollama"), destination: link).font(.callout)
            }
            TextField(t("Address of Ollama"), text: $baseURL, prompt: Text(verbatim: "http://localhost:11434"))
                .textFieldStyle(.roundedBorder)
            modelFields(fastHint: t("model name"), smartHint: t("model name"))
        }
    }

    private func keyField(saved: Bool) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            SecureField(t("API key"), text: $apiKey, prompt: Text(saved ? t("A key is saved. Type a new one to replace it.") : t("Paste your API key")))
                .textFieldStyle(.roundedBorder)
            HStack {
                Text(t("The key is kept in your Mac's Keychain, never in a file."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if saved {
                    Button(t("Forget the key")) { Task { await forgetKey() } }
                        .buttonStyle(.link)
                        .font(.caption)
                }
            }
        }
    }

    private func modelFields(fastHint: String, smartHint: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            modelRow(t("Model for judging jobs (fast)"), $fast, hint: fastHint)
            modelRow(t("Model for writing your CV and letter (best)"), $smart, hint: smartHint)
            HStack(spacing: 8) {
                Button(t("Load the model list")) { Task { await loadModels() } }
                    .buttonStyle(.glass).plainGlass()
                    .controlSize(.small)
                    .disabled(loadingModels || busy)
                if loadingModels { ProgressView().controlSize(.small) }
                if !models.isEmpty {
                    Text(t("%@ models available", models.count)).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func modelRow(_ label: String, _ value: Binding<String>, hint: String) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(width: 270, alignment: .leading)
            TextField(label, text: value, prompt: Text(hint))
                .labelsHidden()
                .textFieldStyle(.roundedBorder)
            if !models.isEmpty {
                Menu {
                    ForEach(models, id: \.self) { name in
                        Button(name) { value.wrappedValue = name }
                    }
                } label: {
                    Image(systemName: "chevron.up.chevron.down")
                }
                .menuIndicator(.hidden)
                .fixedSize()
                .help(t("Choose from the list"))
            }
        }
    }

    private var actions: some View {
        HStack(spacing: 10) {
            Button {
                Task { await saveAndTest() }
            } label: {
                Label(provider == "none" ? t("Save") : t("Save and test"), systemImage: "checkmark.seal")
            }
            .buttonStyle(.glassProminent).accentFill()
            .disabled(busy)
            if busy {
                ProgressView().controlSize(.small)
                Text(t("Asking the model a test question…")).font(.caption).foregroundStyle(.secondary)
            } else if let state, state.provider == provider, state.ready, result.isEmpty {
                Label(t("Connected: %@", state.label.isEmpty ? state.active : state.label), systemImage: "checkmark.circle.fill")
                    .font(.callout)
                    .foregroundStyle(.green)
            }
        }
    }

    private var presetName: String {
        let clean = baseURL.trimmingCharacters(in: .whitespaces)
        return OpenAIPreset.all.first { $0.url == clean }?.name ?? t("Other")
    }

    // MARK: Work

    private func load(keepChoice: Bool = false) async {
        guard model.connectionReady else {
            error = t("The engine is not running yet.")
            return
        }
        do {
            let fresh = try await model.api.ai()
            state = fresh
            error = ""
            if !keepChoice {
                provider = AIProviderOption.all.contains { $0.id == fresh.provider } ? fresh.provider : "none"
                fast = fresh.fastModel
                smart = fresh.smartModel
                baseURL = fresh.baseUrl
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// Switching the provider shows that provider's saved values, or sensible starting points.
    private func choose(_ id: String) {
        guard id != provider else { return }
        provider = id
        apiKey = ""
        models = []
        result = ""
        error = ""
        if let state, state.provider == id {
            fast = state.fastModel
            smart = state.smartModel
            baseURL = state.baseUrl
            return
        }
        switch id {
        case "claude_cli":
            fast = "haiku"
            smart = "sonnet"
            baseURL = ""
        case "openai":
            fast = ""
            smart = ""
            baseURL = state?.openaiBaseUrl ?? "https://api.openai.com/v1"
        case "ollama":
            fast = ""
            smart = ""
            baseURL = state?.ollamaBaseUrl ?? "http://localhost:11434"
        default:
            fast = ""
            smart = ""
            baseURL = ""
        }
    }

    private var keyAccount: String? {
        switch provider {
        case "anthropic": return Secret.anthropicKey
        case "openai": return Secret.openAIKey
        default: return nil
        }
    }

    /// Sends the form to the engine. A newly typed key also goes into the Keychain.
    private func push() async throws -> AIState {
        let typed = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        if !typed.isEmpty, let account = keyAccount {
            Keychain.set(typed, for: account)
        }
        let body = AIBody(provider: provider,
                          fastModel: fast.trimmingCharacters(in: .whitespaces),
                          smartModel: smart.trimmingCharacters(in: .whitespaces),
                          baseUrl: baseURL.trimmingCharacters(in: .whitespaces),
                          apiKey: typed.isEmpty ? nil : typed)
        let fresh = try await model.api.saveAI(body)
        state = fresh
        apiKey = ""
        return fresh
    }

    private func loadModels() async {
        loadingModels = true
        defer { loadingModels = false }
        error = ""
        do {
            // the engine needs the key and address before it can ask the service for its models
            if provider == "anthropic" || provider == "openai" {
                _ = try await push()
            }
            models = try await model.api.aiModels(provider: provider, baseURL: baseURL.trimmingCharacters(in: .whitespaces))
            if models.isEmpty {
                error = provider == "ollama" ? t("Ollama did not answer, or it has no model yet. Is Ollama running?")
                                             : t("The service returned no models.")
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func forgetKey() async {
        guard let account = keyAccount else { return }
        Keychain.set("", for: account)
        let body = AIBody(provider: provider, fastModel: fast, smartModel: smart, baseUrl: baseURL, apiKey: "")
        if let fresh = try? await model.api.saveAI(body) { state = fresh }
        await model.loadSetup()
    }

    private func saveAndTest() async {
        busy = true
        defer { busy = false }
        error = ""
        result = ""
        do {
            let fresh = try await push()
            await model.loadSetup()
            await model.refreshSummary()
            model.aiTestError = ""
            if provider == "none" {
                resultOK = true
                result = t("Saved. JobRadar works without an AI model, but it cannot evaluate jobs or write documents.")
                return
            }
            guard fresh.ready else {
                resultOK = false
                result = fresh.error.isEmpty ? t("The model is not ready yet. Check the fields above.") : fresh.error
                return
            }
            let task = try await model.wait(try await model.api.testAI(), every: 1)
            if task.status == "error" || task.result?.ok != true {
                resultOK = false
                result = task.message.isEmpty ? t("The test did not work.") : task.message
                model.aiTestError = result
                return
            }
            resultOK = true
            let seconds = String(format: "%.1f", task.result?.seconds ?? 0)
            result = t("It works. %@ answered in %@ seconds.", task.result?.model ?? fresh.active, seconds)
            onReady()
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// Opens Terminal running the user's own Claude Code, where they sign in themselves.
    private func openClaude(_ path: String) {
        guard !path.isEmpty,
              let terminal = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Terminal") else { return }
        let configuration = NSWorkspace.OpenConfiguration()
        NSWorkspace.shared.open([URL(fileURLWithPath: path)], withApplicationAt: terminal, configuration: configuration)
    }
}

struct ProviderRow: View {
    let option: AIProviderOption
    let selected: Bool
    var action: () -> Void

    var body: some View {
        let accent = ThemeStore.shared.accentText
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: option.icon)
                    .font(.title3)
                    .foregroundStyle(selected ? accent : Color.secondary)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text(option.title).font(.headline)
                    Text(option.subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
                Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                    .foregroundStyle(selected ? accent : Color.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? accent.opacity(0.14) : Color.secondary.opacity(0.07),
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(selected ? accent.opacity(0.7) : Color.clear, lineWidth: 1.5)
            }
            .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
