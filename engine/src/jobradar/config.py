"""Configuration: one YAML file (jobradar.yaml) plus secrets from .env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, PrivateAttr

EMPLOYMENT_TYPES = [
    "fulltime", "parttime", "werkstudent", "internship", "thesis", "trainee",
    "apprenticeship", "freelance", "contract",
]
ATS_TYPES = [
    "greenhouse", "lever", "lever_eu", "ashby", "personio", "smartrecruiters",
    "recruitee", "workday", "softgarden", "rheinmetall",
]


class LocationPref(BaseModel):
    city: str
    radius_km: int = 50


class TrackConfig(BaseModel):
    """A target career track (career-ops 'north star' + JobNavigator multi-CV)."""

    id: str
    name: str
    priority: int = 1
    enabled: bool = True
    title_keywords: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    north_star: str = ""
    nationwide: bool = False


class SearchConfig(BaseModel):
    country: str = "Germany"
    locations: list[LocationPref] = Field(default_factory=list)   # empty: the whole country
    include_remote: bool = True
    max_age_days: int = 120
    employment_types: list[str] = Field(default_factory=lambda: ["fulltime", "werkstudent", "trainee"])
    preferred_cities: list[str] = Field(default_factory=list)


class JobSpyConfig(BaseModel):
    enabled: bool = True
    sites: list[str] = Field(default_factory=lambda: ["linkedin", "indeed"])
    results_wanted: int = 25
    hours_old: int = 72
    fetch_description: bool = False
    proxies: list[str] = Field(default_factory=list)
    pause_seconds: float = 5.0
    max_queries: int = 12
    linkedin_cooldown_seconds: int = 60
    linkedin_max_blocks: int = 2


class ArbeitsagenturConfig(BaseModel):
    enabled: bool = True
    angebotsart: list[int] = Field(default_factory=lambda: [1, 34])
    days: int = 30
    size: int = 50
    max_pages: int = 3
    include_zeitarbeit: bool = False
    include_private_agencies: bool = False


class FreehireConfig(BaseModel):
    enabled: bool = True
    base_url: str = "https://freehire.me/api/v1"
    countries: list[str] = Field(default_factory=lambda: ["DE"])
    limit: int = 50
    posted_within_days: int = 30
    api_key_env: str = "FREEHIRE_API_KEY"
    max_queries: int = 12
    max_pages: int = 3


class CompanySource(BaseModel):
    name: str
    ats: Literal[
        "greenhouse", "lever", "lever_eu", "ashby", "personio", "smartrecruiters",
        "recruitee", "workday", "softgarden", "rheinmetall",
    ]
    slug: str = ""
    url: str = ""
    search: str = ""
    max_pages: int = 20
    enabled: bool = True


class SourcesConfig(BaseModel):
    jobspy: JobSpyConfig = Field(default_factory=JobSpyConfig)
    arbeitsagentur: ArbeitsagenturConfig = Field(default_factory=ArbeitsagenturConfig)
    freehire: FreehireConfig = Field(default_factory=FreehireConfig)
    companies: list[CompanySource] = Field(default_factory=list)
    inbox_dir: str = "inbox"
    enrich_per_run: int = 40


class FilterConfig(BaseModel):
    title_exclude: list[str] = Field(default_factory=list)
    company_blacklist: list[str] = Field(default_factory=list)
    exclude_senior: bool = True
    exclude_agencies: bool = False
    require_track_match: bool = True
    allow_unspecified_remote: bool = True
    german_gap_policy: Literal["warn", "exclude"] = "warn"
    clearance_policy: Literal["warn", "exclude", "ignore"] = "warn"


class ScoringConfig(BaseModel):
    prescore_min: float = 40
    llm_max_per_run: int = 20
    apply_threshold: float = 4.0
    max_description_chars: int = 12000


class MatchingConfig(BaseModel):
    """Semantic matching: an embedding model compares each posting with your tracks and your profile.

    Off by default. With it, the order in which postings are evaluated follows meaning as well as keywords,
    and postings that the keyword rules would miss can be promoted (see scoring/match.py)."""

    enabled: bool = False
    # fastembed: a model that runs inside JobRadar (pip install 'jobradar[match]'); ollama: an embedding model of
    # a local Ollama; openai: an OpenAI-compatible /embeddings endpoint (a local server, or a paid one when
    # llm.allow_paid_api is true)
    provider: Literal["fastembed", "ollama", "openai"] = "fastembed"
    model: str = ""               # "" = the provider's default (see scoring/embed.py)
    base_url: str = ""            # ollama / openai: "" = the address of llm.ollama / llm.openai
    cache_dir: str = ""           # fastembed: where the model files are kept; "" = <data_dir>/models
    threads: int = 0              # fastembed: CPU threads; 0 = decided by the runtime
    max_chunks: int = Field(4, ge=1, le=8)          # pieces of a posting that are embedded (title + requirements)
    chunk_chars: int = Field(700, ge=200, le=4000)
    profile_weight: float = Field(0.35, ge=0, le=1)  # share of "what you have done" next to "what you look for"
    promote: bool = True          # let a strong semantic match pass the keyword rules
    # the bar for a promotion, between the typical semantic score of the postings the keyword rules turn
    # away (0) and that of the postings they accept (1); lower lets more through
    promote_bar: float = Field(0.5, ge=0.05, le=1.0)
    promote_min_similarity: float = Field(0.0, ge=0, le=1)  # > 0: a fixed bar instead of the measured one
    promote_max_per_run: int = Field(5, ge=0, le=200)
    # time a scan may spend on embedding new postings (a quick scan: a third of it)
    max_seconds_per_run: int = Field(180, ge=10, le=3600)


class AnthropicConfig(BaseModel):
    api_key_env: str = "ANTHROPIC_API_KEY"
    fast_model: str = "claude-haiku-5-5"
    smart_model: str = "claude-sonnet-5-5"


class ClaudeCLIConfig(BaseModel):
    path: str = "claude"
    fast_model: str = "haiku"
    smart_model: str = "sonnet"
    subscription_only: bool = True
    lean: bool = True  # no tools/MCP/skills/session files per call: faster and lighter on plan limits


class OpenAICompatConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    fast_model: str = ""
    smart_model: str = ""


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    fast_model: str = ""
    smart_model: str = ""
    num_ctx: int = 16384


class LLMConfig(BaseModel):
    provider: Literal["auto", "anthropic", "claude_cli", "openai", "ollama", "none"] = "auto"
    # Pay-per-token APIs (Anthropic API, hosted OpenAI-compatible) stay off unless this is true.
    allow_paid_api: bool = False
    output_language: str = "tr"   # language of evaluation texts; "auto" = the interface language
    timeout_seconds: int = 240
    eval_tier: Literal["fast", "smart"] = "fast"
    tailor_tier: Literal["fast", "smart"] = "smart"
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    claude_cli: ClaudeCLIConfig = Field(default_factory=ClaudeCLIConfig)
    openai: OpenAICompatConfig = Field(default_factory=OpenAICompatConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)


class TelegramConfig(BaseModel):
    enabled: bool = False
    token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    min_score: float = 4.0
    min_prescore_without_llm: float = 70
    daily_digest: bool = True
    health_alerts: bool = True


class EmailConfig(BaseModel):
    """Daily digest by e-mail. Active only when SMTP_USER and SMTP_PASSWORD are set in .env."""

    enabled: bool = True
    host: str = "smtp.gmail.com"
    port: int = 587
    user_env: str = "SMTP_USER"
    password_env: str = "SMTP_PASSWORD"
    to_env: str = "MAIL_TO"
    min_score: float = 3.5
    max_jobs: int = 12
    # Instant alert: a separate short mail as soon as a fresh evaluation reaches this score
    instant: bool = True
    instant_min_score: float = 4.0
    instant_max_jobs: int = 5


class NotifyConfig(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    dashboard_url: str = "http://127.0.0.1:8787"


class ServerConfig(BaseModel):
    """Running JobRadar on an always-on server behind Cloudflare Tunnel."""

    public_url: str = ""          # e.g. https://jobradar.example.com (links in e-mails)
    api_token_env: str = "JOBRADAR_API_TOKEN"
    session_days: int = 30
    backups_keep: int = 14


class MailSyncConfig(BaseModel):
    """Read replies from companies (Gmail IMAP, same app password as the digest) and propose status changes.

    Read only: messages are opened with BODY.PEEK, so nothing is marked as read, moved or deleted."""

    enabled: bool = True
    host: str = "imap.gmail.com"
    port: int = 993
    folder: str = "INBOX"
    days: int = 21
    max_messages: int = 150


class QuickConfig(BaseModel):
    """`jobradar run --quick`: the hourly early-capture scan (company career pages only, few evaluations)."""

    sources: list[str] = Field(default_factory=lambda: ["companies"])
    max_evaluations: int = 5
    max_pages: int = 10           # per company: big paginated boards get a partial look hourly, full look in `run`


class TailorConfig(BaseModel):
    pdf_engine: Literal["auto", "chrome", "rendercv", "helper", "none"] = "auto"
    chrome_path: str = ""
    default_language: str = ""    # CV/letter language when the posting's language is unknown ("" = by country)
    sender_city: str = ""
    review: bool = True           # second LLM pass critiques the draft, one revision if it helps
    cv_max_pages: int = 2
    letter_max_pages: int = 1


class AppConfig(BaseModel):
    language: str = ""            # interface language of API texts: tr | en ("" = JOBRADAR_LANG, else tr)
    data_dir: str = "data"
    profile: str = "data/profile.yaml"
    dashboard_port: int = 8787
    follow_up_days: int = 10
    tracks: list[TrackConfig] = Field(default_factory=list)
    search: SearchConfig = Field(default_factory=SearchConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    tailor: TailorConfig = Field(default_factory=TailorConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    mail_sync: MailSyncConfig = Field(default_factory=MailSyncConfig)
    quick: QuickConfig = Field(default_factory=QuickConfig)

    _base_dir: Path = PrivateAttr(default_factory=lambda: Path.cwd())
    _config_path: Optional[Path] = PrivateAttr(default=None)

    # -- paths -----------------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def config_path(self) -> Optional[Path]:
        return self._config_path

    def resolve(self, p: str | Path) -> Path:
        path = Path(p).expanduser()
        return path if path.is_absolute() else (self._base_dir / path)

    @property
    def data_path(self) -> Path:
        return self.resolve(self.data_dir)

    @property
    def profile_path(self) -> Path:
        return self.resolve(self.profile)

    @property
    def db_path(self) -> Path:
        return self.data_path / "jobradar.db"

    @property
    def inbox_path(self) -> Path:
        p = Path(self.sources.inbox_dir).expanduser()
        return p if p.is_absolute() else self.data_path / p

    @property
    def applications_path(self) -> Path:
        return self.data_path / "applications"

    @property
    def logs_path(self) -> Path:
        return self.data_path / "logs"

    @property
    def answers_path(self) -> Path:
        return self.data_path / "answers.yaml"

    @property
    def models_path(self) -> Path:
        """Files of the built-in embedding model (downloaded once, safe to delete)."""
        custom = self.matching.cache_dir.strip()
        return self.resolve(custom) if custom else self.data_path / "models"

    def enabled_tracks(self) -> list[TrackConfig]:
        return sorted([t for t in self.tracks if t.enabled], key=lambda t: t.priority)

    def track(self, track_id: str | None) -> Optional[TrackConfig]:
        for t in self.tracks:
            if t.id == track_id:
                return t
        return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_env_file(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def set_env_value(path: Path, key: str, value: str) -> None:
    """Set KEY=value in a .env file: replace the existing line or append one; keep everything else."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for raw in lines:
        stripped = raw.strip()
        bare = stripped[len("export "):] if stripped.startswith("export ") else stripped
        if not stripped.startswith("#") and bare.partition("=")[0].strip() == key:
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(raw)
    if not done:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def find_config(explicit: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("JOBRADAR_CONFIG")
    if env:
        candidates.append(Path(env).expanduser())
    candidates += [Path.cwd() / "jobradar.yaml", Path.home() / ".jobradar" / "jobradar.yaml"]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def load_config(explicit: str | Path | None = None, *, required: bool = True) -> AppConfig:
    path = find_config(explicit)
    if path is None:
        if required:
            raise FileNotFoundError(
                "jobradar.yaml bulunamadı. Proje klasöründe 'jobradar init' çalıştır "
                "ya da --config ile yolu ver."
            )
        cfg = AppConfig()
        cfg._base_dir = Path.cwd()
        return cfg
    from jobradar import i18n, settings  # late: both import this module

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = AppConfig.model_validate(settings.merged_data(data, path.parent))
    cfg._base_dir = path.parent
    cfg._config_path = path
    load_env_file(path.parent / ".env")
    apply_env_overrides(cfg)
    if cfg.language:
        i18n.set_default(cfg.language)
    return cfg


def apply_env_overrides(cfg: AppConfig) -> None:
    """Machine-specific settings come from .env so jobradar.yaml stays identical on Mac and server."""
    url = os.environ.get("JOBRADAR_PUBLIC_URL", "").strip().rstrip("/")
    if url:
        cfg.server.public_url = url
        cfg.notify.dashboard_url = url
    dashboard = os.environ.get("JOBRADAR_DASHBOARD_URL", "").strip().rstrip("/")
    if dashboard and not url:
        cfg.notify.dashboard_url = dashboard
    chrome = os.environ.get("JOBRADAR_CHROME_PATH", "").strip()
    if chrome:
        cfg.tailor.chrome_path = chrome
    claude = os.environ.get("JOBRADAR_CLAUDE_PATH", "").strip()
    if claude:
        cfg.llm.claude_cli.path = claude


def public_base_url(cfg: AppConfig) -> str:
    return (cfg.server.public_url or cfg.notify.dashboard_url).rstrip("/")


def config_from_dict(data: dict, base_dir: Path) -> AppConfig:
    """Build a config in memory (tests, demo)."""
    cfg = AppConfig.model_validate(data)
    cfg._base_dir = base_dir
    return cfg
