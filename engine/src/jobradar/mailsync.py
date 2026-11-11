"""Replies from companies → proposed status changes (application tracking by e-mail).

Uses Gmail IMAP with the same app password as the digest (SMTP_USER / SMTP_PASSWORD).
Read only: the folder is opened read-only and bodies are fetched with BODY.PEEK, so nothing
is marked as read, moved or deleted. Nothing changes automatically either: each signal waits
until the user applies or dismisses it in the app or the panel."""

from __future__ import annotations

import email
import hashlib
import imaplib
import json
import os
import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Callable, Optional

from jobradar import db
from jobradar.config import AppConfig
from jobradar.i18n import t
from jobradar.processing.normalize import clean_title, normalize_company, normalize_title
from jobradar.textutil import fold_umlauts, html_to_text, now_iso

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TRACKED = ("shortlisted", "tailored", "approved", "applied", "interview", "offer")
ORDER = {s: i for i, s in enumerate(("new", "shortlisted", "tailored", "approved", "applied", "interview", "offer"))}
KIND_TR = {"rejection": "Ret", "interview": "Mülakat daveti", "assessment": "Test / ödev", "offer": "Teklif",
           "received": "Başvuru alındı"}


class MailSyncError(Exception):
    pass


@dataclass
class MailMessage:
    message_id: str
    sender_name: str
    sender_email: str
    subject: str
    received_at: str
    body: str = ""


@dataclass
class SyncResult:
    checked: int = 0
    relevant: int = 0
    new: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def pending(self) -> int:
        return sum(1 for s in self.new if s.get("state") == "pending")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _rx(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(fold_umlauts(p), re.IGNORECASE | re.DOTALL) for p in patterns]


# Checked in this order: a rejection that mentions the interview is still a rejection.
KIND_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("rejection", _rx([
        r"leider (?:müssen|mussten|möchten) wir (?:ihnen|dir|euch) mitteilen",
        r"leider (?:können|konnten) wir (?:ihre|deine) bewerbung (?:\w+ )?nicht",
        r"leider (?:können|konnten) wir (?:ihnen|dir) (?:\w+ )?(?:keine|kein|nicht)",
        r"(?:haben|hat|habe) (?:wir |man )?(?:uns|sich)\b.{0,80}?(?:für (?:eine[nrs]? |den |die )?andere|anders|gegen)"
        r".{0,60}?entschieden",
        r"(?:wahl|entscheidung) (?:ist|fiel) .{0,40}(?:auf (?:eine[nr]? )?andere|nicht auf)",
        r"\babsage\b",
        r"nicht (?:weiter )?berücksichtig",
        r"nicht in die (?:engere|nähere|nächste) (?:auswahl|runde)",
        r"anderweitig (?:besetzt|entschieden|vergeben)",
        r"stelle (?:ist |wurde )?(?:bereits |inzwischen )?(?:besetzt|vergeben)",
        r"\bwe regret to inform\b",
        r"unfortunately,? .{0,160}(?:not (?:been )?(?:selected|successful|shortlisted|moving|proceed|progress)"
        r"|decided|other candidates?)",
        r"(?:not|won't|will not) (?:be )?moving forward with your (?:application|candidacy)",
        r"(?:decided|chosen) to (?:move forward|proceed|continue|go) with (?:other|another|a different)",
        r"decided not to (?:proceed|move forward|pursue|progress)",
        r"position has (?:now )?(?:already )?been filled",
        r"(?:were|was|have not been|has not been) (?:not )?(?:selected|successful) (?:for|in|this time)",
        r"\bmaalesef\b",
    ])),
    ("offer", _rx([
        r"\b(?:vertragsangebot|arbeitsvertrag|angebotsschreiben)\b",
        r"\boffer letter\b",
        r"\b(?:job|employment) offer\b",
        r"\bpleased to offer\b",
        r"(?:freuen uns|möchten (?:ihnen|dir)).{0,80}(?:anzubieten|anbieten|zusage)",
        r"\bzusage\b",
    ])),
    ("interview", _rx([
        r"\b(?:vorstellungsgespräch|bewerbungsgespräch|kennenlerngespräch|telefoninterview|videointerview)",
        r"\beinladung\b.{0,60}\b(?:gespräch|interview|kennenlernen)",
        r"\b(?:zu|zum|zur|für) (?:einem |einen |ein |das |den |unserem |unser )?(?:\w+ )?(?:gespräch|interview"
        r"|kennenlernen|vorstellungsgespräch)\w* (?:ein)?(?:zu)?laden",
        r"\blad(?:en|e) (?:wir )?(?:sie|dich|euch) .{0,40}?(?:gespräch|interview|kennenlernen)\w*.{0,20}?\bein\b",
        r"\b(?:persönlich|gerne|näher) kennen ?(?:zu ?)?lernen\b",
        r"\b(?:invite|invitation|inviting) (?:you )?(?:to|for) (?:an? |the )?(?:\w+ )?(?:interview|call|conversation|chat)",
        r"\b(?:phone|video|first|technical|initial) (?:screen|interview|call)\b",
        r"\bschedule (?:an? )?(?:interview|call|meeting|time)\b",
        r"\b(?:calendly\.com|cal\.com)/",
        r"\bmülakat",
    ])),
    ("assessment", _rx([
        r"\bonline[- ]?(?:test|assessment)\b",
        r"\bassessment[- ]?(?:center|centre)?\b",
        r"\bcoding[- ]?(?:challenge|test|task|exercise)\b",
        r"\b(?:hackerrank|codility|codesignal|testgorilla|coderbyte)\b",
        r"\b(?:take[- ]home|case study|fallstudie|probeaufgabe|eignungstest)\b",
    ])),
    ("received", _rx([
        r"\beingangsbestätigung\b",
        r"bewerbung (?:ist )?(?:bei uns )?(?:gut |erfolgreich )?(?:eingegangen|erhalten|angekommen)",
        r"bewerbung wurde an .{1,80} (?:gesendet|übermittelt|weitergeleitet)",
        r"(?:vielen |herzlichen )?dank für (?:ihre|deine) bewerbung",
        r"thank you for (?:your )?(?:application|applying)",
        r"(?:we have |we've )?received your application",
        r"application (?:has been |was )?(?:received|submitted)",
        r"your application was sent to",
        r"başvurunuz (?:alındı|ulaştı)",
    ])),
]

CONTEXT = re.compile(fold_umlauts(r"bewerb|application|applied|applying|candida|kandidat|stelle|position|role\b"
                                  r"|interview|gespräch|başvuru|recruit|absage"), re.IGNORECASE)
ALERT_SENDER = re.compile(r"^[^@]*(?:alert|newsletter|jobs-listings|jobagent|digest|marketing|promotion)[^@]*@|^news@",
                          re.IGNORECASE)
ALERT_SUBJECT = re.compile(fold_umlauts(
    r"job ?alert|jobagent|neue jobs|new jobs|jobs for you|stellenangebote für sie|empfohlene jobs|recommended jobs"
    r"|jobs matching|passende jobs|newsletter|webinar"), re.IGNORECASE)
APP_WORDS = re.compile(fold_umlauts(
    r"bewerbung|application|applied|interview|gespräch|absage|einladung|candidate|kandidat|candidacy|"
    r"assessment|online-test|angebot|offer|position|stelle|başvuru|mülakat"), re.IGNORECASE)


# "If your profile fits, we will invite you to an interview" / "Sollten Sie nichts hören, gilt das als Absage":
# a match inside a conditional sentence is not a real invitation or rejection.
CONDITIONAL = re.compile(fold_umlauts(
    r"\b(?:sollte|sollten|sofern|falls|wenn|gegebenenfalls|ggf|im falle|if|should|once|sobald|in case|unless|whether"
    r"|may|might|eventuell|möglicherweise|bevor)\b"), re.IGNORECASE)


def _conditional(text: str, pos: int) -> bool:
    seg = text[max(0, pos - 160):pos]
    cut = max(seg.rfind(". "), seg.rfind("! "), seg.rfind("? "), seg.rfind(": "))
    if cut >= 0:
        seg = seg[cut + 1:]
    return bool(CONDITIONAL.search(seg))


def _hit(patterns: list[re.Pattern], text: str, check_conditional: bool) -> bool:
    for p in patterns:
        for m in p.finditer(text):
            if check_conditional and _conditional(text, m.start()):
                continue
            return True
    return False


def classify(subject: str, body: str) -> Optional[str]:
    text = fold_umlauts(f"{subject}. {body}".lower())
    text = re.sub(r"\s+", " ", text)
    if not CONTEXT.search(text):
        return None
    for kind, patterns in KIND_PATTERNS:
        if _hit(patterns, text, check_conditional=kind != "received"):
            return kind
    return None


def propose(kind: str, current: str) -> Optional[str]:
    """Status change suggested by a reply, given the job's current status (None: nothing to change)."""
    order = ORDER.get(current, -1)
    if kind == "rejection":
        return None if current in ("rejected", "closed") else "rejected"
    if kind == "offer":
        return None if current in ("offer", "rejected", "closed") else "offer"
    if kind in ("interview", "assessment"):
        return "interview" if order < ORDER["interview"] and current not in ("rejected", "closed") else None
    if kind == "received":
        return "applied" if order < ORDER["applied"] and current not in ("rejected", "closed") else None
    return None


# ---------------------------------------------------------------------------
# Matching a message to a tracked job
# ---------------------------------------------------------------------------

GENERIC_COMPANY = {"deutsche", "german", "technik", "technology", "technologies", "systems", "system", "solutions",
                   "services", "service", "international", "europe", "electronic", "electronics", "engineering",
                   "consulting", "software", "digital", "industries", "the", "und", "and", "group"}
TITLE_STOP = {"und", "and", "fur", "fuer", "for", "der", "die", "das", "the", "mit", "with", "im", "in", "als",
              "senior", "junior", "m", "w", "d", "f", "x", "mwd", "all", "genders", "de", "of", "to", "a", "zum", "zur"}
FREEMAIL = {"gmail", "googlemail", "outlook", "hotmail", "gmx", "web", "yahoo", "icloud", "t-online", "posteo",
            "linkedin", "indeed", "xing", "stepstone", "smartrecruiters", "greenhouse", "lever", "personio",
            "workday", "myworkday", "successfactors", "softgarden", "recruitee", "ashbyhq", "join", "bamboohr"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]{2,}", fold_umlauts(text.lower())))


def _domain_stem(address: str) -> str:
    domain = address.rpartition("@")[2].lower()
    parts = [p for p in domain.split(".") if p]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def match_jobs(msg: MailMessage, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidate jobs for a message, best first, with a rough confidence score."""
    stem = _domain_stem(msg.sender_email)
    head = fold_umlauts(f"{msg.sender_name} {msg.subject}".lower())
    hay = fold_umlauts(f"{msg.sender_name} {msg.subject} {msg.body[:6000]}".lower())
    hay_words = _words(hay)
    out = []
    for job in jobs:
        cname = normalize_company(job.get("company", ""))
        tokens = [t for t in cname.split() if len(t) >= 3 and t not in GENERIC_COMPANY]
        score = 0.0
        if stem and stem not in FREEMAIL and tokens and any(stem == t or (len(t) >= 4 and t in stem)
                                                              for t in tokens):
            score = 3.0
        elif cname and len(cname) >= 4 and re.search(rf"\b{re.escape(cname)}\b", hay):
            score = 3.0
        elif tokens and len(tokens[0]) >= 4 and re.search(rf"\b{re.escape(tokens[0])}\b", hay):
            score = 2.5 if re.search(rf"\b{re.escape(tokens[0])}\b", head) else 2.0
        if score == 0:
            continue
        title_words = [w for w in normalize_title(job.get("title", "")).split() if len(w) >= 3 and w not in TITLE_STOP]
        if title_words:
            score += 2.0 * sum(1 for w in title_words if w in hay_words) / len(title_words)
        out.append({"job_id": job["id"], "title": clean_title(job.get("title", "")), "company": job.get("company", ""),
                    "status": job.get("status", ""), "score": round(score, 2)})
    return sorted(out, key=lambda c: -c["score"])


def pick(candidates: list[dict[str, Any]]) -> Optional[str]:
    """The job id when one candidate clearly wins; None when nothing or several fit equally."""
    if not candidates or candidates[0]["score"] < 2.0:
        return None
    if len(candidates) > 1 and candidates[0]["score"] - candidates[1]["score"] < 0.5:
        return None
    return candidates[0]["job_id"]


# ---------------------------------------------------------------------------
# IMAP (read only)
# ---------------------------------------------------------------------------

def imap_credentials(cfg: AppConfig) -> Optional[tuple[str, str]]:
    ec = cfg.notify.email
    user = os.environ.get(ec.user_env, "").strip()
    password = os.environ.get(ec.password_env, "").replace(" ", "").strip()
    return (user, password) if user and password else None


def _imap_date(d: datetime) -> str:
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def _mailbox(name: str) -> str:
    name = name.strip() or "INBOX"
    if name.startswith('"') or not re.search(r'[\s()\[\]{}%*"\\]', name):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _uid_payloads(data: list[Any], expected: Optional[list[int]] = None) -> dict[int, bytes]:
    """FETCH response → {uid: literal}. Servers may put "UID n" before or after the literal."""
    out: dict[int, bytes] = {}
    unnamed: list[bytes] = []
    waiting: Optional[bytes] = None
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            if waiting is not None:
                unnamed.append(waiting)
            m = re.search(rb"UID (\d+)", item[0] or b"")
            if m:
                out[int(m.group(1))] = item[1] or b""
                waiting = None
            else:
                waiting = item[1] or b""
        elif isinstance(item, (bytes, bytearray)) and waiting is not None:
            m = re.search(rb"UID (\d+)", bytes(item))
            if m:
                out[int(m.group(1))] = waiting
            else:
                unnamed.append(waiting)
            waiting = None
    if waiting is not None:
        unnamed.append(waiting)
    if expected and len(expected) == 1 and expected[0] not in out and len(unnamed) == 1:
        out[expected[0]] = unnamed[0]
    return out


def _decode(value: Any) -> str:
    return " ".join(str(value or "").split())


def parse_message(raw: bytes) -> Optional[MailMessage]:
    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
    except Exception:  # noqa: BLE001
        return None
    return _to_message(msg)


def _body_text(msg: Message) -> str:
    part = None
    try:
        part = msg.get_body(preferencelist=("plain", "html"))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        part = None
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:  # noqa: BLE001
        payload = part.get_payload(decode=True) or b""
        content = payload.decode(part.get_content_charset() or "utf-8", "replace") if isinstance(payload, bytes) else ""
    if not isinstance(content, str):
        return ""
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return " ".join(content.split())[:20000]


def _to_message(msg: Message) -> Optional[MailMessage]:
    try:
        name, addr = (getaddresses([str(msg.get("From", ""))]) or [("", "")])[0]
        subject = _decode(msg.get("Subject", ""))
        date_raw = str(msg.get("Date", "") or "")
    except Exception:  # noqa: BLE001
        return None
    try:
        received = parsedate_to_datetime(date_raw).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, IndexError):
        received = now_iso()
    mid = _decode(msg.get("Message-ID", "")).strip("<> ")
    if not mid:
        mid = "sha1:" + hashlib.sha1(f"{addr}|{subject}|{date_raw}".encode("utf-8", "ignore")).hexdigest()
    return MailMessage(message_id=mid, sender_name=_decode(name), sender_email=(addr or "").lower(),
                       subject=subject, received_at=received, body=_body_text(msg))


def worth_reading(msg: MailMessage, own_address: str, hints: set[str]) -> bool:
    """Header-only filter before downloading a body: skip our own mails, job alerts and newsletters."""
    if own_address and msg.sender_email == own_address.lower():
        return False
    if msg.subject.lower().startswith("jobradar"):
        return False
    if ALERT_SENDER.search(msg.sender_email) or ALERT_SUBJECT.search(fold_umlauts(msg.subject.lower())):
        return False
    head = fold_umlauts(f"{msg.sender_name} {msg.sender_email} {msg.subject}".lower())
    if APP_WORDS.search(head):
        return True
    stem = _domain_stem(msg.sender_email)
    words = _words(head)
    return any(h in words or (len(h) >= 4 and h == stem) for h in hints)


def fetch_imap(cfg: AppConfig, user: str, password: str, *, state: dict[str, Any], hints: set[str],
               imap_factory: Optional[Callable[[], Any]] = None) -> tuple[list[MailMessage], dict[str, Any], int]:
    """New messages since the last run (UID based). Returns (messages, new_state, headers_checked)."""
    mc = cfg.mail_sync
    factory = imap_factory or (lambda: imaplib.IMAP4_SSL(mc.host, mc.port, ssl_context=ssl.create_default_context(),
                                                          timeout=30))
    try:
        imap = factory()
    except OSError as exc:
        raise MailSyncError(t("{host}:{port} bağlantısı kurulamadı: {error}", host=mc.host, port=mc.port,
                              error=exc)) from exc
    try:
        try:
            imap.login(user, password)
        except imaplib.IMAP4.error as exc:
            raise MailSyncError(t("E-posta sunucusu girişi reddetti. Uygulama şifresi doğru mu, IMAP açık mı?")) from exc
        typ, _ = imap.select(_mailbox(mc.folder), readonly=True)
        if typ != "OK":
            raise MailSyncError(t("Klasör açılamadı: {folder}", folder=mc.folder))
        _, vdata = imap.response("UIDVALIDITY")
        validity = (vdata[0].decode() if vdata and isinstance(vdata[0], bytes) else str((vdata or [""])[0] or ""))
        last = int(state.get("last_uid") or 0) if str(state.get("uidvalidity", "")) == validity else 0
        since = _imap_date(datetime.now(timezone.utc) - timedelta(days=max(1, mc.days)))
        typ, data = imap.uid("SEARCH", None, "SINCE", since)
        uids = sorted(int(x) for x in ((data or [b""])[0] or b"").split()) if typ == "OK" else []
        uids = [u for u in uids if u > last][-max(1, mc.max_messages):]
        messages: list[MailMessage] = []
        for i in range(0, len(uids), 100):
            chunk = uids[i:i + 100]
            typ, data = imap.uid("FETCH", ",".join(map(str, chunk)),
                                 "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            if typ != "OK":
                continue
            for uid, head in sorted(_uid_payloads(data).items()):
                hmsg = parse_message(head)
                if not hmsg or not worth_reading(hmsg, user, hints):
                    continue
                typ, body = imap.uid("FETCH", str(uid), "(BODY.PEEK[]<0.300000>)")
                full = parse_message(_uid_payloads(body, [uid]).get(uid, b"")) if typ == "OK" else None
                messages.append(full or hmsg)
        new_state = {"uidvalidity": validity, "last_uid": max(uids) if uids else last}
        return messages, new_state, len(uids)
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Sync, apply, dismiss
# ---------------------------------------------------------------------------

def tracked_jobs(conn) -> list[dict[str, Any]]:
    marks = ",".join("?" for _ in TRACKED)
    return [db.row_to_job(r) for r in conn.execute(f"SELECT * FROM jobs WHERE status IN ({marks})", TRACKED)]


def company_hints(jobs: list[dict[str, Any]]) -> set[str]:
    hints: set[str] = set()
    for job in jobs:
        for word in normalize_company(job.get("company", "")).split():
            if len(word) >= 4 and word not in GENERIC_COMPANY:
                hints.add(word)
    return hints


def process_messages(conn, messages: list[MailMessage], jobs: Optional[list[dict[str, Any]]] = None,
                     own_address: str = "") -> SyncResult:
    jobs = tracked_jobs(conn) if jobs is None else jobs
    res = SyncResult(checked=len(messages))
    for msg in messages:
        if db.mail_signal_exists(conn, msg.message_id):
            continue
        if own_address and msg.sender_email == own_address.lower():
            continue
        kind = classify(msg.subject, msg.body)
        if not kind:
            continue
        res.relevant += 1
        candidates = match_jobs(msg, jobs)
        job_id = pick(candidates)
        job = next((j for j in jobs if j["id"] == job_id), None) if job_id else None
        proposed = propose(kind, job["status"]) if job else None
        if job is None and kind == "received" and not candidates:
            continue  # a confirmation for something JobRadar does not track
        state = "pending" if (job is None or proposed) else "info"
        sig = {"message_id": msg.message_id, "job_id": job_id, "received_at": msg.received_at,
               "sender": f"{msg.sender_name} <{msg.sender_email}>".strip(), "subject": msg.subject[:300],
               "snippet": msg.body[:400], "kind": kind, "proposed_status": proposed,
               "candidates": candidates[:5], "state": state}
        sid = db.add_mail_signal(conn, sig)
        if sid is None:
            continue
        if state == "info" and job_id:
            db.add_event(conn, job_id, "mail", f"{KIND_TR.get(kind, kind)}: {msg.subject[:140]}")
        sig["id"] = sid
        res.new.append(sig)
    conn.commit()
    return res


def sync_mail(conn, cfg: AppConfig, *, fetch: Optional[Callable[..., Any]] = None,
              imap_factory: Optional[Callable[[], Any]] = None) -> SyncResult:
    """Fetch new mail (read only), classify replies, store proposals. Never raises for mail problems."""
    if not cfg.mail_sync.enabled:
        return SyncResult(error=t("E-posta yanıtlarını okuma kapalı."))
    creds = imap_credentials(cfg)
    if not creds and fetch is None:
        return SyncResult(error=t("E-posta ayarlı değil."))
    user = creds[0] if creds else ""
    jobs = tracked_jobs(conn)
    try:
        if fetch is not None:
            messages, new_state, checked = fetch(), None, None
        else:
            state = json.loads(db.get_meta(conn, "mail_sync_uid", "{}") or "{}")
            messages, new_state, checked = fetch_imap(cfg, creds[0], creds[1], state=state,
                                                      hints=company_hints(jobs), imap_factory=imap_factory)
    except MailSyncError as exc:
        _note(conn, str(exc))
        return SyncResult(error=str(exc))
    except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
        msg = t("IMAP hatası: {error}", error=exc)
        _note(conn, msg)
        return SyncResult(error=msg)
    res = process_messages(conn, messages, jobs, own_address=user)
    if checked is not None:
        res.checked = checked
    if new_state is not None:
        db.set_meta(conn, "mail_sync_uid", json.dumps(new_state))
    _note(conn, "")
    return res


def _note(conn, error: str) -> None:
    db.set_meta(conn, "last_mail_sync", now_iso())
    db.set_meta(conn, "last_mail_sync_error", error)


def apply_signal(conn, signal_id: int, job_id: Optional[str] = None) -> dict[str, Any]:
    sig = db.get_mail_signal(conn, signal_id)
    if not sig:
        raise KeyError(t("yanıt bulunamadı"))
    jid = job_id or sig.get("job_id")
    if not jid:
        raise ValueError(t("Bu yanıt bir ilanla eşleşmedi; önce ilanı seç."))
    job = db.get_job(conn, jid)
    if not job:
        raise ValueError(t("İlan bulunamadı"))
    status = propose(sig["kind"], job["status"])
    if status:
        db.set_status(conn, jid, status, f"e-posta: {sig['subject'][:80]}")
    db.add_event(conn, jid, "mail", f"{KIND_TR.get(sig['kind'], sig['kind'])}: {sig['subject'][:140]}")
    db.set_mail_signal_state(conn, signal_id, "applied", job_id=jid)
    conn.commit()
    return {"job_id": jid, "status": status or job["status"], "changed": bool(status)}


def dismiss_signal(conn, signal_id: int) -> None:
    if not db.get_mail_signal(conn, signal_id):
        raise KeyError(t("yanıt bulunamadı"))
    db.set_mail_signal_state(conn, signal_id, "dismissed")
    conn.commit()


def signal_view(conn, sig: dict[str, Any]) -> dict[str, Any]:
    """A signal plus the matched job's title/company and Turkish labels (API, panel)."""
    from jobradar.models import STATUS_LABELS_TR

    out = dict(sig)
    job = db.get_job(conn, sig["job_id"]) if sig.get("job_id") else None
    out["job_title"] = clean_title(job["title"]) if job else ""
    out["job_company"] = job["company"] if job else ""
    out["job_status"] = job["status"] if job else ""
    out["kind_label"] = t(KIND_TR.get(sig.get("kind", ""), sig.get("kind", "")))
    proposed = propose(sig["kind"], job["status"]) if job else sig.get("proposed_status")
    out["proposed_status"] = proposed
    out["proposed_label"] = t(STATUS_LABELS_TR.get(proposed or "", ""))
    return out
