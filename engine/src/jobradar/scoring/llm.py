"""LLM providers: Anthropic API, Claude Code CLI (your subscription),
OpenAI-compatible APIs (OpenAI, OpenRouter, LM Studio) and Ollama."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from jobradar.config import AppConfig
from jobradar.i18n import t

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


_LIMIT = r"usage limit|limit reached|limit will reset|rate.?limit|out of extra usage|\b429\b"
_FATAL = re.compile(
    r"authenticat|oauth|/login|not logged in|log ?in again|invalid.{0,20}api.?key|x-api-key|\b401\b|\b403\b"
    r"|credit balance|insufficient_quota|quota exceeded|billing|bulunamadı|command not found|permission denied"
    r"|was not found|model not found|is missing|ücretli api|paid apis? (?:is|are) turned off|anahtarı yok|"
    + _LIMIT,
    re.IGNORECASE,
)


def is_fatal(message: str) -> bool:
    """Errors that will repeat for every posting (login, key, credits, missing CLI)."""
    return bool(_FATAL.search(message or ""))


def llm_hint(provider: str, message: str) -> str:
    m = (message or "").lower()
    if provider == "claude_cli" and re.search(_LIMIT, m):
        return t("Claude planının kullanım limiti doldu. Kalan ilanlar limit sıfırlanınca bir sonraki çalıştırmada "
                 "değerlendirilir. Ek ücret çıkmaması için claude.ai > Settings > Usage altında extra usage kapalı kalsın.")
    if provider == "claude_cli" and re.search(r"authenticat|oauth|login", m):
        return t("Claude Code oturumu geçersiz. Terminal'de `claude` açıp /login ile yeniden giriş yap.")
    if re.search(r"credit balance|quota|billing", m):
        return t("API kredisi ya da kotası bitmiş görünüyor.")
    if re.search(r"401|api.?key|x-api-key", m):
        return t("API anahtarı geçersiz.")
    if "ollama" not in m and ("bulunamadı" in m or "not found" in m):
        return t("AI komutu bulunamadı. Claude Code kurulu mu?")
    return message


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


class BaseLLM:
    provider = "base"

    def model_for(self, tier: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def complete(self, system: str, user: str, *, tier: str = "fast", max_tokens: int = 4000) -> LLMResult:
        raise NotImplementedError  # pragma: no cover


class AnthropicLLM(BaseLLM):
    provider = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, fast_model: str, smart_model: str, timeout: float = 240,
                 client: httpx.Client | None = None):
        self.api_key = api_key
        self.models = {"fast": fast_model, "smart": smart_model}
        self.client = client or httpx.Client(timeout=timeout)

    def model_for(self, tier: str) -> str:
        return self.models.get(tier) or self.models["fast"]

    def complete(self, system: str, user: str, *, tier: str = "fast", max_tokens: int = 4000) -> LLMResult:
        model = self.model_for(tier)
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        last = ""
        for attempt in range(4):
            try:
                r = self.client.post(self.URL, json=body, headers=headers)
            except httpx.HTTPError as exc:
                last = str(exc)
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 529) and attempt < 3:
                last = r.text[:300]
                time.sleep(min(30, 3 * (2 ** attempt)))
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("error", {}).get("message", r.text[:300])
                except ValueError:
                    msg = r.text[:300]
                raise LLMError(f"Anthropic API {r.status_code}: {msg}")
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return LLMResult(text=text, provider=self.provider, model=model, usage=data.get("usage") or {})
        raise LLMError(t("Anthropic API yanıt vermedi: {last}", last=last))


class OpenAICompatLLM(BaseLLM):
    def __init__(self, base_url: str, api_key: str, fast_model: str, smart_model: str, provider: str = "openai",
                 timeout: float = 240, client: httpx.Client | None = None):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.models = {"fast": fast_model, "smart": smart_model or fast_model}
        self.client = client or httpx.Client(timeout=timeout)

    def model_for(self, tier: str) -> str:
        return self.models.get(tier) or self.models["fast"]

    def complete(self, system: str, user: str, *, tier: str = "fast", max_tokens: int = 4000) -> LLMResult:
        model = self.model_for(tier)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens}
        last = ""
        for attempt in range(3):
            try:
                r = self.client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as exc:
                last = str(exc)
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503) and attempt < 2:
                last = r.text[:300]
                time.sleep(3 * (2 ** attempt))
                continue
            if r.status_code >= 400:
                raise LLMError(f"{self.provider} API {r.status_code}: {r.text[:300]}")
            data = r.json()
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(t("{provider}: beklenmeyen yanıt", provider=self.provider)) from exc
            return LLMResult(text=text, provider=self.provider, model=model, usage=data.get("usage") or {})
        raise LLMError(t("{provider} yanıt vermedi: {last}", provider=self.provider, last=last))


class ClaudeCLILLM(BaseLLM):
    """Runs `claude -p` (Claude Code) so evaluations use your Claude plan."""

    provider = "claude_cli"

    # Env vars that would switch Claude Code from the subscription to pay-per-token billing.
    API_BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                        "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")

    # Lighter, faster calls: no tools, no MCP servers, no skills, no saved sessions in ~/.claude.
    LEAN_FLAGS = ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands", "--tools", "")

    def __init__(self, path: str, fast_model: str, smart_model: str, timeout: float = 240,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None, subscription_only: bool = True,
                 lean: bool = True):
        self.path = path
        self.models = {"fast": fast_model, "smart": smart_model}
        self.timeout = timeout
        self.runner = runner or subprocess.run
        self.subscription_only = subscription_only
        self.lean = lean

    def child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.subscription_only:
            for var in self.API_BILLING_VARS:
                env.pop(var, None)
        return env

    def model_for(self, tier: str) -> str:
        return self.models.get(tier) or self.models["fast"]

    def command(self, model: str, lean: bool) -> list[str]:
        cmd = [self.path, "-p", "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        if lean:
            cmd += list(self.LEAN_FLAGS)
        return cmd

    def _run(self, cmd: list[str], prompt: str, cwd: str) -> subprocess.CompletedProcess:
        try:
            return self.runner(cmd, input=prompt, capture_output=True, text=True, timeout=self.timeout, cwd=cwd,
                               env=self.child_env())
        except FileNotFoundError as exc:
            raise LLMError(t("'{path}' bulunamadı. Claude Code kurulu mu?", path=self.path)) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(t("Claude Code {timeout} sn içinde yanıt vermedi", timeout=self.timeout)) from exc

    def complete(self, system: str, user: str, *, tier: str = "fast", max_tokens: int = 4000) -> LLMResult:
        model = self.model_for(tier)
        prompt = f"{system}\n\n---\n\n{user}"
        # An empty working directory keeps Claude Code from reading project files.
        with tempfile.TemporaryDirectory(prefix="jobradar-") as tmp:
            proc = self._run(self.command(model, self.lean), prompt, tmp)
            if self.lean and proc.returncode != 0 and "unknown option" in f"{proc.stderr}{proc.stdout}".lower():
                self.lean = False  # older Claude Code: fall back to the plain command
                proc = self._run(self.command(model, False), prompt, tmp)
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 and not out:
            raise LLMError(t("Claude Code hata verdi: {error}", error=(proc.stderr or "").strip()[:300]))
        text = out
        usage: dict[str, Any] = {}
        try:
            data = json.loads(out)
            if isinstance(data, list):
                data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {})
            if isinstance(data, dict):
                if data.get("is_error"):
                    raise LLMError(f"Claude CLI: {str(data.get('result'))[:300]}")
                text = str(data.get("result") or "")
                usage = data.get("usage") or {}
                # Claude Code reports what the call would cost on the API; a subscription is not charged.
                if data.get("total_cost_usd") is not None:
                    usage["api_equivalent_usd"] = data["total_cost_usd"]
        except json.JSONDecodeError:
            pass
        return LLMResult(text=text, provider=self.provider, model=model, usage=usage)


class OllamaLLM(BaseLLM):
    """Local models through Ollama's native API: free, offline, slower.

    The native endpoint lets us raise the context window (Ollama's default is
    too small for a posting plus the fact bank) and force JSON output."""

    provider = "ollama"

    def __init__(self, base_url: str, fast_model: str, smart_model: str, num_ctx: int = 16384,
                 timeout: float = 600, client: httpx.Client | None = None):
        root = base_url.rstrip("/")
        self.root = root[:-3] if root.endswith("/v1") else root
        self.models = {"fast": fast_model, "smart": smart_model or fast_model}
        self.num_ctx = num_ctx
        self.client = client or httpx.Client(timeout=timeout)

    def model_for(self, tier: str) -> str:
        return self.models.get(tier) or self.models["fast"]

    def complete(self, system: str, user: str, *, tier: str = "fast", max_tokens: int = 4000) -> LLMResult:
        model = self.model_for(tier)
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"num_ctx": self.num_ctx, "temperature": 0.2, "num_predict": max_tokens},
        }
        try:
            r = self.client.post(f"{self.root}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(t("Ollama'ya bağlanılamadı ({root}). Ollama uygulaması açık mı? {error}", root=self.root,
                             error=exc)) from exc
        if r.status_code == 404:
            raise LLMError(t("Ollama modeli bulunamadı: {model}. Önce: ollama pull {model}", model=model))
        if r.status_code >= 400:
            raise LLMError(f"Ollama {r.status_code}: {r.text[:300]}")
        data = r.json()
        text = ((data.get("message") or {}).get("content")) or ""
        usage = {"prompt_eval_count": data.get("prompt_eval_count"), "eval_count": data.get("eval_count")}
        return LLMResult(text=text, provider=self.provider, model=model, usage=usage)


def is_local_url(url: str) -> bool:
    host = (httpx.URL(url).host or "").lower() if url else ""
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


COST_LABELS = {
    "claude_cli": "Claude planın",
    "ollama": "yerel model, ücretsiz",
    "local": "yerel sunucu, ücretsiz",
    "anthropic": "ücretli API (kendi anahtarın)",
    "openai": "ücretli API (kendi anahtarın)",
    "demo": "örnek veriler için sahte model",
}

PROVIDER_NAMES = {
    "claude_cli": "Claude Code",
    "ollama": "Ollama",
    "local": "Yerel sunucu",
    "anthropic": "Anthropic API",
    "openai": "OpenAI uyumlu servis",
    "demo": "Demo",
}


def cost_label(provider: str) -> str:
    return t(COST_LABELS.get(provider, ""))


def provider_name(provider: str) -> str:
    """What the user calls the provider (not the id in the settings file)."""
    return t(PROVIDER_NAMES.get(provider, provider))


def llm_label(llm: "BaseLLM") -> str:
    cost = cost_label(llm.provider)
    return f"{provider_name(llm.provider)} · {cost}" if cost else provider_name(llm.provider)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _ollama_up(base_url: str) -> bool:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    try:
        r = httpx.get(f"{root}/api/tags", timeout=1.5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def get_llm(cfg: AppConfig) -> Optional[BaseLLM]:
    lc = cfg.llm
    prov = lc.provider
    tmo = lc.timeout_seconds

    def anthropic() -> Optional[BaseLLM]:
        key = os.environ.get(lc.anthropic.api_key_env, "")
        if not key or not lc.allow_paid_api:
            return None
        return AnthropicLLM(key, lc.anthropic.fast_model, lc.anthropic.smart_model, tmo)

    def claude_cli() -> Optional[BaseLLM]:
        path = shutil.which(lc.claude_cli.path) or (lc.claude_cli.path if os.path.isfile(lc.claude_cli.path) else None)
        if not path:
            return None
        return ClaudeCLILLM(path, lc.claude_cli.fast_model, lc.claude_cli.smart_model, tmo,
                            subscription_only=lc.claude_cli.subscription_only, lean=lc.claude_cli.lean)

    def openai() -> Optional[BaseLLM]:
        key = os.environ.get(lc.openai.api_key_env, "")
        local = is_local_url(lc.openai.base_url)
        if not lc.openai.fast_model or not (key or local) or not (local or lc.allow_paid_api):
            return None
        return OpenAICompatLLM(lc.openai.base_url, key, lc.openai.fast_model, lc.openai.smart_model,
                               "local" if local else "openai", tmo)

    def ollama(check: bool = True) -> Optional[BaseLLM]:
        if not lc.ollama.fast_model:
            return None
        if check and not _ollama_up(lc.ollama.base_url):
            return None
        return OllamaLLM(lc.ollama.base_url, lc.ollama.fast_model, lc.ollama.smart_model, lc.ollama.num_ctx,
                         max(tmo, 600))

    if prov == "none":
        return None
    paid_off = t("Ücretli API kapalı (llm.allow_paid_api: false).")
    if prov == "anthropic":
        if not lc.allow_paid_api:
            raise LLMError(paid_off)
        llm = anthropic()
        if not llm:
            raise LLMError(t("API anahtarı yok ({env})", env=lc.anthropic.api_key_env))
        return llm
    if prov == "claude_cli":
        llm = claude_cli()
        if not llm:
            raise LLMError(t("'{path}' komutu bulunamadı", path=lc.claude_cli.path))
        return llm
    if prov == "openai":
        if not lc.allow_paid_api and not is_local_url(lc.openai.base_url):
            raise LLMError(paid_off)
        llm = openai()
        if not llm:
            raise LLMError(t("Model adı gerekli (uzak servis için API anahtarı da)."))
        return llm
    if prov == "ollama":
        llm = ollama(check=False)
        if not llm:
            raise LLMError(t("Önce bir Ollama modeli seç."))
        return llm
    # Free options first: your Claude subscription, then a local model; paid APIs last.
    for factory in (claude_cli, ollama, anthropic, openai):
        llm = factory()
        if llm:
            return llm
    return None


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def extract_json(text: str) -> Any:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    start = s.find("{")
    if start == -1:
        raise ValueError(t("yanıtta JSON nesnesi yok"))
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start:i + 1])
    raise ValueError(t("JSON nesnesi kapanmamış (yanıt kesilmiş olabilir)"))


def complete_json(llm: BaseLLM, system: str, user: str, model_cls: Type[T], *, tier: str = "fast",
                  max_tokens: int = 4000) -> tuple[T, LLMResult]:
    prompt = user
    last_err = ""
    for _ in range(2):
        res = llm.complete(system, prompt, tier=tier, max_tokens=max_tokens)
        try:
            data = extract_json(res.text)
            return model_cls.model_validate(data), res
        except (ValueError, ValidationError) as exc:
            last_err = str(exc)[:800]
            prompt = (
                f"{user}\n\nYOUR PREVIOUS ANSWER WAS INVALID: {last_err}\n"
                "Return ONLY one valid JSON object that matches the schema. No prose, no markdown."
            )
    raise LLMError(t("Model geçerli JSON döndürmedi: {error}", error=last_err))
