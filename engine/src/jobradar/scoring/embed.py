"""Embedding models for semantic matching.

Three ways to get vectors, all free to run: a model inside JobRadar (fastembed, ONNX on the CPU), an embedding
model of a local Ollama, or any OpenAI-compatible /embeddings endpoint. Every backend returns plain lists of
floats of length 1, so the dot product of two vectors is their cosine similarity.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import operator
import os
import struct
import sys
import warnings
from array import array
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

import httpx

from jobradar.config import AppConfig
from jobradar.i18n import t
from jobradar.scoring.llm import is_local_url

DEFAULT_MODELS = {
    "fastembed": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "ollama": "bge-m3",
    "openai": "",
}
# What the app offers for the built-in provider. Sizes are the one-time downloads. Any other model that
# fastembed supports can be named in jobradar.yaml (matching.model).
BUILTIN_MODELS: list[dict[str, Any]] = [
    {"id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "size_mb": 220, "dim": 384,
     "note": "küçük ve hızlı, 50+ dil (varsayılan)"},
    {"id": "jinaai/jina-embeddings-v2-base-de", "size_mb": 640, "dim": 768,
     "note": "Almanca ve İngilizce ilanlar için"},
    {"id": "Qwen/Qwen3-Embedding-0.6B-Q", "size_mb": 1120, "dim": 1024,
     "note": "en güçlüsü, 100+ dil; daha yavaş"},
]
BATCH = 32


class EmbedError(Exception):
    """The embedding model is missing, unreachable or failed. Matching is skipped; nothing else depends on it."""


class Embedder(Protocol):
    provider: str
    model: str

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        ...


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------


def unit(values: Any) -> list[float]:
    """A vector as a list of floats with length 1 (a zero vector stays zero)."""
    vec = [float(x) for x in (values.tolist() if hasattr(values, "tolist") else values)]
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


def pack(vectors: Sequence[Sequence[float]]) -> bytes:
    """Vectors of one size as float32, little endian, one after the other."""
    flat = [x for v in vectors for x in v]
    return struct.pack(f"<{len(flat)}f", *flat)


def unpack(blob: bytes, dim: int) -> list[array]:
    arr = array("f")
    arr.frombytes(blob)
    if sys.byteorder == "big":
        arr.byteswap()
    return [arr[i:i + dim] for i in range(0, len(arr), dim)] if dim > 0 else []


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(map(operator.mul, a, b))


# ---------------------------------------------------------------------------
# Instructions some models expect in front of the text
# ---------------------------------------------------------------------------

_QWEN_TASK = "Given what a candidate is looking for and has done, retrieve job postings that fit"


def query_prefix(model: str) -> str:
    m = model.lower()
    if "qwen3-embedding" in m:
        return f"Instruct: {_QWEN_TASK}\nQuery:"
    if "e5" in m and "instruct" not in m:
        return "query: "
    if "nomic-embed" in m:
        return "search_query: "
    if "embeddinggemma" in m:
        return "task: search result | query: "
    return ""


def passage_prefix(model: str) -> str:
    m = model.lower()
    if "e5" in m and "instruct" not in m:
        return "passage: "
    if "nomic-embed" in m:
        return "search_document: "
    if "embeddinggemma" in m:
        return "title: none | text: "
    return ""


def _prefixed(model: str, texts: Sequence[str], query: bool) -> list[str]:
    prefix = query_prefix(model) if query else passage_prefix(model)
    return [prefix + (x or " ") for x in texts]


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def fastembed_installed() -> bool:
    importlib.invalidate_caches()  # the app may have installed the package after this process started
    return importlib.util.find_spec("fastembed") is not None


class FastEmbedBackend:
    """A model that runs inside this process. Its files are downloaded once from Hugging Face."""

    provider = "fastembed"

    def __init__(self, model: str, cache_dir: Path, threads: int = 0):
        self.model = model
        self.cache_dir = cache_dir
        self.threads = threads
        self._engine: Any = None

    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        if not fastembed_installed():
            raise EmbedError(t("Eşleştirme paketi (fastembed) kurulu değil."))
        # quiet, and nothing but the model files is requested
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        try:
            from fastembed import TextEmbedding
        except Exception as exc:  # noqa: BLE001 - a broken install must not break a scan
            raise EmbedError(t("Eşleştirme paketi yüklenemedi: {error}", error=str(exc)[:300])) from exc
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._engine = TextEmbedding(model_name=self.model, cache_dir=str(self.cache_dir),
                                             threads=self.threads or None)
        except ValueError as exc:
            raise EmbedError(t("Bu eşleştirme modeli desteklenmiyor: {model}", model=self.model)) from exc
        except Exception as exc:  # noqa: BLE001 - download, disk or runtime problems
            raise EmbedError(t("Eşleştirme modeli yüklenemedi ({model}): {error}", model=self.model,
                               error=str(exc)[:300])) from exc
        return self._engine

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        engine = self._load()
        try:
            vectors = list(engine.embed(_prefixed(self.model, texts, query), batch_size=BATCH))
        except Exception as exc:  # noqa: BLE001
            raise EmbedError(t("Eşleştirme modeli hata verdi: {error}", error=str(exc)[:300])) from exc
        return [unit(v) for v in vectors]


class OllamaEmbedBackend:
    provider = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 300, client: httpx.Client | None = None):
        root = base_url.rstrip("/")
        self.root = root[:-3] if root.endswith("/v1") else root
        self.model = model
        self.client = client or httpx.Client(timeout=timeout)

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        body = {"model": self.model, "input": _prefixed(self.model, texts, query)}
        try:
            r = self.client.post(f"{self.root}/api/embed", json=body)
        except httpx.HTTPError as exc:
            raise EmbedError(t("Ollama'ya bağlanılamadı ({root}). Ollama uygulaması açık mı? {error}", root=self.root,
                               error=exc)) from exc
        if r.status_code == 404:
            raise EmbedError(t("Ollama modeli bulunamadı: {model}. Önce: ollama pull {model}", model=self.model))
        if r.status_code >= 400:
            raise EmbedError(f"Ollama {r.status_code}: {r.text[:300]}")
        try:
            vectors = r.json()["embeddings"]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbedError(t("{provider}: beklenmeyen yanıt", provider="Ollama")) from exc
        if len(vectors) != len(texts):
            raise EmbedError(t("{provider}: beklenmeyen yanıt", provider="Ollama"))
        return [unit(v) for v in vectors]


class OpenAIEmbedBackend:
    provider = "openai"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120,
                 client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=timeout)

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "input": _prefixed(self.model, texts, query)}
        try:
            r = self.client.post(f"{self.base_url}/embeddings", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise EmbedError(t("bağlantı hatası: {error}", error=str(exc)[:200])) from exc
        if r.status_code >= 400:
            raise EmbedError(f"{self.base_url} {r.status_code}: {r.text[:300]}")
        try:
            items = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
            vectors = [d["embedding"] for d in items]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise EmbedError(t("{provider}: beklenmeyen yanıt", provider=self.base_url)) from exc
        if len(vectors) != len(texts):
            raise EmbedError(t("{provider}: beklenmeyen yanıt", provider=self.base_url))
        return [unit(v) for v in vectors]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def model_name(cfg: AppConfig) -> str:
    return cfg.matching.model.strip() or DEFAULT_MODELS.get(cfg.matching.provider, "")


def model_key(cfg: AppConfig) -> str:
    """Identity of the vectors in the database: vectors of different models are never compared."""
    return f"{cfg.matching.provider}:{model_name(cfg)}"


def base_url(cfg: AppConfig) -> str:
    mc = cfg.matching
    if mc.base_url.strip():
        return mc.base_url.strip().rstrip("/")
    return (cfg.llm.ollama.base_url if mc.provider == "ollama" else cfg.llm.openai.base_url).rstrip("/")


def get_embedder(cfg: AppConfig) -> Embedder:
    """The configured embedding model. Raises EmbedError with a text for the user when it cannot be used."""
    mc = cfg.matching
    model = model_name(cfg)
    if mc.provider == "fastembed":
        return FastEmbedBackend(model, cfg.models_path, mc.threads)
    if mc.provider == "ollama":
        return OllamaEmbedBackend(base_url(cfg), model)
    url = base_url(cfg)
    if not model:
        raise EmbedError(t("Eşleştirme için bir model adı gerekli."))
    if not is_local_url(url) and not cfg.llm.allow_paid_api:
        raise EmbedError(t("Ücretli API kapalı (llm.allow_paid_api: false)."))
    return OpenAIEmbedBackend(url, os.environ.get(cfg.llm.openai.api_key_env, ""), model)


def embed_all(embedder: Embedder, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        out += embedder.embed(texts[i:i + BATCH], query=query)
    return out


def probe(embedder: Embedder) -> Optional[int]:
    """Embed one short text; returns the vector size. The first call of the built-in model downloads it."""
    vectors = embedder.embed(["A job posting"], query=False)
    return len(vectors[0]) if vectors else None
