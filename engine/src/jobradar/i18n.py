"""Two interface languages for everything the API hands to a client: Turkish (the source strings) and English.

``t("Türkçe metin {x}", x=1)`` returns the text in the current language. The current language is the one
of the request (``Accept-Language`` header, set by the API middleware) or, in background threads and the
CLI, the process default (``JOBRADAR_LANG`` or ``language:`` in jobradar.yaml; Turkish when neither is set).
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

SUPPORTED = ("tr", "en")
_request: ContextVar[str] = ContextVar("jobradar_lang", default="")
_default = {"lang": ""}


def normalize(code: str | None) -> str:
    """'en-US,en;q=0.9' -> 'en'; unknown or empty -> ''."""
    for part in (code or "").replace(";", ",").split(","):
        base = part.strip().lower().split("-")[0].split("_")[0]
        if base in SUPPORTED:
            return base
    return ""


def set_default(code: str | None) -> None:
    _default["lang"] = normalize(code)


def default_lang() -> str:
    return _default["lang"] or normalize(os.environ.get("JOBRADAR_LANG")) or "tr"


def set_lang(code: str | None):
    """Language for the current request or thread; returns a token for ``reset``."""
    return _request.set(normalize(code))


def reset(token) -> None:
    _request.reset(token)


def get_lang() -> str:
    return _request.get() or default_lang()


def t(text: str, /, **params: Any) -> str:
    """Translate a Turkish source string; unknown strings come back unchanged."""
    out = EN.get(text, text) if get_lang() == "en" else text
    if params:
        try:
            return out.format(**params)
        except (KeyError, IndexError, ValueError):
            return out
    return out


def language_name(code: str | None = None) -> str:
    """English name of a language code, for prompts ('tr' -> 'Turkish')."""
    return {"tr": "Turkish", "en": "English", "de": "German"}.get((code or get_lang()).lower(), code or "English")


EN: dict[str, str] = {
    # statuses
    "Yeni": "New",
    "Kısa liste": "Shortlist",
    "Belgeler hazır": "Documents ready",
    "Onaylandı": "Approved",
    "Başvuruldu": "Applied",
    "Mülakat": "Interview",
    "Teklif": "Offer",
    "Ret": "Rejected",
    "Geçildi": "Skipped",
    "Kapandı": "Closed",
    "Elendi": "Filtered out",
    # badges
    "Şüpheli gizli metin / AI talimatı": "Suspicious hidden text / AI instruction",
    "Almanca {lv} (artı)": "German {lv} (a plus)",
    "Almanca {lv} (sen {you})": "German {lv} (you: {you})",
    "Almanca {lv}": "German {lv}",
    "Güvenlik soruşturması": "Security clearance",
    "Güvenlik soruşturması {level}": "Security clearance {level}",
    "Vatandaşlık: {value}": "Citizenship: {value}",
    "Werkstudent": "Working student",
    "Abschlussarbeit": "Thesis",
    "Praktikum": "Internship",
    "Ausbildung": "Apprenticeship",
    "Teilzeit": "Part-time",
    "Befristet/Contract": "Fixed-term / contract",
    "Lead/Leitung": "Lead",
    "{yrs}+ yıl deneyim": "{yrs}+ years of experience",
    "Hibrit": "Hybrid",
    "Aracı firma": "Staffing agency",
    "Eski/tekrar yayınlanmış ilan": "Old or reposted listing",
    # job fields
    "Tam uzaktan": "Fully remote",
    "Ofiste": "On-site",
    "Tam zamanlı": "Full-time",
    "Yarı zamanlı": "Part-time",
    "Sözleşmeli": "Contract",
    "yıl": "year",
    "ay": "month",
    "saat": "hour",
    "hafta": "week",
    "gün": "day",
    # API errors
    "İlan bulunamadı": "Job not found",
    "AI modeli bağlı değil": "No AI model is connected",
    "geçersiz durum": "invalid status",
    "değerlendirilemedi": "could not be evaluated",
    "belgeler v{v} onaylandı": "documents v{v} approved",
    "Belge bulunamadı": "Document not found",
    "Bu sürümde tailored.json yok": "This version has no tailored.json",
    "E-posta ayarlı değil.": "E-mail is not set up.",
    "İlan okunamadı: {error}": "Could not read the posting: {error}",
    "görev bulunamadı": "task not found",
    "yok": "none",
    "hata: {error}": "error: {error}",
    "Profil": "Profile",
    "Genel sorular": "General questions",
    "Profil henüz yok. Önce profilini oluştur.": "There is no profile yet. Create your profile first.",
    "Profil geçersiz: {error}": "The profile is not valid: {error}",
    "Dosya okunamadı: {error}": "Could not read the file: {error}",
    "Dosya boş.": "The file is empty.",
    "Bu dosya türü desteklenmiyor: {name}. PDF, Word (.docx), metin ya da Markdown yükle.":
        "This file type is not supported: {name}. Upload a PDF, Word (.docx), text or Markdown file.",
    "Dosyada okunabilir metin yok. Taranmış (resim) bir PDF olabilir.":
        "The file has no readable text. It may be a scanned (image) PDF.",
    "Dosya çok büyük (en fazla {mb} MB).": "The file is too large ({mb} MB at most).",
    "Geçersiz ayar: {error}": "Invalid setting: {error}",
    "Bilinmeyen sağlayıcı: {name}": "Unknown provider: {name}",
    "Bu adres tanınan bir kariyer sistemine ait değil.": "This address does not belong to a known careers system.",
    "Önce hangi işleri aradığını yaz.": "First describe the jobs you are looking for.",
    # filters
    "şirket kara listede": "company is on the blocklist",
    "başlıkta istenmeyen kelime: {word}": "unwanted word in the title: {word}",
    "çalışma türü istenmiyor: {type}": "employment type not wanted: {type}",
    "kıdem: {level}": "seniority: {level}",
    "ilan {age} günlük": "posting is {age} days old",
    "{country} dışı konum: {loc}": "location outside {country}: {loc}",
    "Almanca şartı ({level}) seviyenin çok üstünde": "German requirement ({level}) is far above your level",
    "vatandaşlık şartı: {value}": "citizenship requirement: {value}",
    "güvenlik soruşturması: {level}": "security clearance: {level}",
    "aracı firma ilanı": "staffing agency posting",
    "hiçbir hedef alana uymuyor": "matches none of your target tracks",
    "profil: '{id}' kimliği iki kez kullanılmış": "profile: the ID '{id}' is used twice",
    # progress
    "Başlatılıyor": "Starting",
    "İlanlar taranıyor": "Scanning job sources",
    "Açıklamalar tamamlanıyor": "Fetching descriptions",
    "LLM değerlendirmesi": "AI evaluation",
    "E-posta yanıtları okunuyor": "Reading e-mail replies",
    "Bildirimler gönderiliyor": "Sending notifications",
    "freehire (XING, EURES, şirketler)": "freehire (XING, EURES, companies)",
    "şirket kariyer sayfaları": "company career pages",
    "LinkedIn ve Indeed": "LinkedIn and Indeed",
    "{i}/{n} ilan": "{i}/{n} postings",
    "değerlendirilecek ilan yok": "nothing to evaluate",
    "kaynaklar bitti": "sources done",
    "{new} yeni ilan, {evaluated} değerlendirme": "{new} new postings, {evaluated} evaluations",
    "Tamamlandı": "Finished",
    "Hata ile bitti": "Finished with an error",
    # mail
    "Mülakat daveti": "Interview invitation",
    "Test / ödev": "Assessment / task",
    "Başvuru alındı": "Application received",
    "{host}:{port} bağlantısı kurulamadı: {error}": "Could not connect to {host}:{port}: {error}",
    "E-posta sunucusu girişi reddetti. Uygulama şifresi doğru mu, IMAP açık mı?":
        "The mail server rejected the sign-in. Is the app password correct and is IMAP enabled?",
    "Klasör açılamadı: {folder}": "Could not open folder: {folder}",
    "E-posta yanıtlarını okuma kapalı.": "Reading e-mail replies is turned off.",
    "IMAP hatası: {error}": "IMAP error: {error}",
    "yanıt bulunamadı": "reply not found",
    "Bu yanıt bir ilanla eşleşmedi; önce ilanı seç.": "This reply is not matched to a posting; choose the posting first.",
    "SMTP girişi başarısız: {error}": "SMTP sign-in failed: {error}",
    "E-posta adresi ve uygulama şifresi gerekli.": "An e-mail address and an app password are required.",
    "JobRadar test e-postası": "JobRadar test e-mail",
    "Bu bir deneme e-postasıdır. E-posta ayarların çalışıyor.": "This is a test message. Your e-mail settings work.",
    "E-posta sunucusu girişi reddetti. Gmail için normal şifre değil, 16 haneli uygulama şifresi gerekir "
    "(myaccount.google.com/apppasswords).":
        "The mail server rejected the sign-in. Gmail needs a 16-character app password, not your normal password "
        "(myaccount.google.com/apppasswords).",
    "E-posta gönderilemedi ({host}:{port}): {error}": "Could not send the e-mail ({host}:{port}): {error}",
    "JobRadar'ı aç": "Open JobRadar",
    "Paneli aç": "Open the panel",
    "başvur": "apply",
    "belki": "maybe",
    "geç": "skip",
    "İlana git": "Go to the posting",
    "JobRadar · {day}: {n} yeni güçlü ilan": "JobRadar · {day}: {n} new strong matches",
    "JobRadar · {day}: yeni güçlü ilan yok": "JobRadar · {day}: no new strong matches",
    "JobRadar günlük özet, {day}": "JobRadar daily digest, {day}",
    "JobRadar günlük özet": "JobRadar daily digest",
    "Son 24 saatte: {new} yeni ilan, {evals} değerlendirme. Değerlendirme bekleyen: {pending}.":
        "Last 24 hours: {new} new postings, {evals} evaluations. Waiting for evaluation: {pending}.",
    "son 24 saatte {new} yeni ilan, {evals} değerlendirme · bekleyen {pending}":
        "last 24 hours: {new} new postings, {evals} evaluations · waiting {pending}",
    "Kısa liste: {a} · Başvurulan: {b} · Mülakat: {c}": "Shortlist: {a} · Applied: {b} · Interview: {c}",
    "Puanı {score} ve üstü yeni ilanlar:": "New postings scoring {score} or higher:",
    "Bugün eşiği geçen yeni ilan yok.": "No new posting passed the threshold today.",
    "Takip zamanı gelen başvurular:": "Applications due for a follow-up:",
    "Takip zamanı gelenler": "Due for a follow-up",
    "Onay bekleyen e-posta yanıtları:": "E-mail replies waiting for your review:",
    "Onay bekleyen e-posta yanıtları": "E-mail replies waiting for your review",
    "Kaynak uyarıları": "Source warnings",
    "JobRadar · Yeni güçlü ilan: {title} @ {company} ({score}/5)":
        "JobRadar · New strong match: {title} @ {company} ({score}/5)",
    "JobRadar · {n} yeni güçlü ilan": "JobRadar · {n} new strong matches",
    "Az önce değerlendirilen ve eşiği geçen ilanlar. Erken başvuru şansını artırır.":
        "Postings that were just evaluated and passed the threshold. Applying early improves your chances.",
    "Yeni güçlü ilan": "New strong match",
    "Az önce değerlendirildi. Erken başvuru şansını artırır.": "Just evaluated. Applying early improves your chances.",
    "ön puan {score}": "keyword score {score}",
    "Yeni güçlü eşleşmeler": "New strong matches",
    "Bugün yeni: {n}": "New today: {n}",
    "En iyi açık ilanlar": "Best open postings",
    "3 çalıştırmadır 0 ilan": "0 postings for 3 runs",
    "⚠️ Kaynak '{source}' çalışmıyor olabilir: {reason}": "⚠️ Source '{source}' may be broken: {reason}",
    # answers
    "Ad soyad": "Full name",
    "E-posta": "E-mail",
    "Telefon": "Phone",
    "Adres / şehir": "Address / city",
    "Vatandaşlık": "Citizenship",
    "Çalışma izni": "Work permit",
    "En erken başlangıç": "Earliest start",
    "Maaş beklentisi": "Salary expectation",
    "Diller": "Languages",
    "İlanı nerede buldun?": "Where did you find the posting?",
    "Pozisyon": "Position",
    "Geçersiz dil kodu: {code}": "Invalid language code: {code}",
    "Takip süresi 1 ile 90 gün arasında olmalı.": "The follow-up time must be between 1 and 90 days.",
    "E-posta konusu": "E-mail subject",
    "Bu ilan": "This posting",
    "Referans numarası": "Reference number",
    "Belgelerle üretilen cevaplar (v{v})": "Answers generated with the documents (v{v})",
    "{name} okunamadı: {error}": "Could not read {name}: {error}",
    "İhbar süresi": "Notice period",
    "Taşınmaya açıklık": "Willingness to relocate",
    "Seyahate açıklık": "Willingness to travel",
    "Ehliyet": "Driving licence",
    "Çalışma şekli (ofis / hibrit / uzaktan)": "Preferred way of working (on site / hybrid / remote)",
    "Mülakat için uygunluk": "Availability for interviews",
    "Soru {n}": "Question {n}",
    # PDF check
    "pypdf hatası: {error}": "pypdf error: {error}",
    "poppler hatası: {error}": "poppler error: {error}",
    "CV PDF okunamadı ({engine}); kontrol atlandı.": "Could not read the CV PDF ({engine}); the check was skipped.",
    "CV {pages} sayfa; en fazla {max} olmalı.": "The CV has {pages} pages; the limit is {max}.",
    "CV'nin metin katmanı boş ya da çok kısa: ATS içeriği okuyamayabilir.":
        "The CV's text layer is empty or very short: an ATS may not be able to read it.",
    "PDF metninde bulunamadı: {items}": "Not found in the PDF text: {items}",
    "Profilinin desteklediği {n} şart CV metninde geçmiyor.":
        "{n} requirements that your profile supports do not appear in the CV text.",
    "Ön yazı {pages} sayfa; en fazla {max} olmalı.": "The cover letter has {pages} pages; the limit is {max}.",
    "ad": "name",
    "e-posta": "e-mail",
    "telefon": "phone",
    # validation
    "bilinmeyen gerçek kimliği: {ids}": "unknown fact ID: {ids}",
    "başka bir girişe ait gerçek: {ids}": "fact belongs to another entry: {ids}",
    "hiçbir gerçeğe dayanmıyor": "not backed by any fact",
    "kaynak gerçeklerde olmayan sayı: {n}": "number not found in the source facts: {n}",
    "kanıtı olmayan terim: '{term}'": "term without evidence: '{term}'",
    "Profil özeti": "Profile summary",
    "Giriş {id}": "Entry {id}",
    "profilde böyle bir giriş yok": "no such entry in the profile",
    "Ön yazı paragraf {n}": "Cover letter paragraph {n}",
    "Başlık": "Headline",
    "giriş {id}": "entry {id}",
    "ön yazı paragraf {n}: {text}": "cover letter paragraph {n}: {text}",
    "[Bu cevabı kendin yaz: taslak doğrulamadan geçemedi]":
        "[Write this answer yourself: the draft did not pass validation]",
    "profil özeti": "profile summary",
    "{id} madde {n}": "{id} bullet {n}",
    "{id} madde {n}: {text}": "{id} bullet {n}: {text}",
    "Beceriler": "Skills",
    "profilde olmayan beceri: '{s}'": "skill not in the profile: '{s}'",
    "Cevap {n}": "Answer {n}",
    # skill gaps
    "Almanca": "German",
    "İngilizce": "English",
    "{name} (akıcı)": "{name} (fluent)",
    "Güvenlik soruşturması (Ü2/Ü3)": "Security clearance (Ü2/Ü3)",
    # evaluation notes
    "Bilinmeyen kanıt kimlikleri silindi: {ids}": "Removed unknown evidence IDs: {ids}",
    "'{req}' için kanıt yok; 'strong' -> 'partial'": "No evidence for '{req}'; 'strong' -> 'partial'",
    "Zorunlu şartların kanıt kapsamı %{pct}; puan {cap} ile sınırlandı":
        "Evidence covers {pct}% of the must-have requirements; score capped at {cap}",
    "Almanca şartı {req} (profil: {mine})": "German requirement {req} (profile: {mine})",
    "Vatandaşlık şartı: {value}": "Citizenship requirement: {value}",
    "Vatandaşlık şartı karşılanmıyor; puan 2.5 ile sınırlandı":
        "The citizenship requirement is not met; score capped at 2.5",
    "Güvenlik soruşturması gerekli ({level})": "Security clearance required ({level})",
    # report
    "Konum": "Location",
    "İlan": "Posting",
    "Başvuru": "Apply",
    "(Değerlendirme yok)": "(No evaluation)",
    "Şartlar ve kanıtlar": "Requirements and evidence",
    "| Şart | Önem | Eşleşme | Kanıt |": "| Requirement | Importance | Match | Evidence |",
    "Güçlü yanlar": "Strengths",
    "Eksikler": "Gaps",
    "Riskler": "Risks",
    "Mülakat hazırlığı": "Interview preparation",
    "Uyarlama ipuçları": "Tailoring hints",
    "İlanın güvenilirliği": "Legitimacy of the posting",
    "Kod tarafı düzeltmeler": "Automatic corrections",
    "Düzeltilmiş taslakta profilde olmayan yeni iddialar vardı; ilk taslak korundu.":
        "The revised draft contained new claims that are not in the profile; the first draft was kept.",
    "ilan bulunamadı: {id}": "job not found: {id}",
    # import and liveness
    "LinkedIn sayfasından ilan okunamadı (giriş duvarı ya da hız sınırı)":
        "Could not read the posting from the LinkedIn page (login wall or rate limit)",
    "sayfa açılamadı: HTTP {status}": "could not open the page: HTTP {status}",
    "sayfada ilan bilgisi bulunamadı": "no job posting data found on the page",
    "açıklama yok": "no description",
    "adres yok": "no address",
    "LinkedIn: başvuru kabul edilmiyor": "LinkedIn: no longer accepting applications",
    "LinkedIn sayfası okunamadı": "could not read the LinkedIn page",
    "bağlantı hatası: {error}": "connection error: {error}",
    "sayfada 'ilan kapandı' ifadesi var": "the page says the posting is closed",
    "Gizli (görünmeyen) metin ya da karakter kaldırıldı": "Hidden (invisible) text or characters were removed",
    # AI model
    "Claude planının kullanım limiti doldu. Kalan ilanlar limit sıfırlanınca bir sonraki çalıştırmada "
    "değerlendirilir. Ek ücret çıkmaması için claude.ai > Settings > Usage altında extra usage kapalı kalsın.":
        "Your Claude plan's usage limit is reached. The remaining postings are evaluated on a later run, after "
        "the limit resets. To avoid extra charges, keep extra usage turned off under claude.ai > Settings > Usage.",
    "Claude Code oturumu geçersiz. Terminal'de `claude` açıp /login ile yeniden giriş yap.":
        "The Claude Code session is not valid. Open `claude` in Terminal and sign in again with /login.",
    "API kredisi ya da kotası bitmiş görünüyor.": "The API credit or quota seems to be used up.",
    "API anahtarı geçersiz.": "The API key is not valid.",
    "AI komutu bulunamadı. Claude Code kurulu mu?": "The AI command was not found. Is Claude Code installed?",
    "Anthropic API yanıt vermedi: {last}": "The Anthropic API did not respond: {last}",
    "{provider}: beklenmeyen yanıt": "{provider}: unexpected response",
    "{provider} yanıt vermedi: {last}": "{provider} did not respond: {last}",
    "'{path}' bulunamadı. Claude Code kurulu mu?": "'{path}' was not found. Is Claude Code installed?",
    "Claude Code {timeout} sn içinde yanıt vermedi": "Claude Code did not answer within {timeout} s",
    "Claude Code hata verdi: {error}": "Claude Code failed: {error}",
    "Ollama'ya bağlanılamadı ({root}). Ollama uygulaması açık mı? {error}":
        "Could not connect to Ollama ({root}). Is the Ollama app running? {error}",
    "Ollama modeli bulunamadı: {model}. Önce: ollama pull {model}":
        "Ollama model not found: {model}. First run: ollama pull {model}",
    "Claude planın": "your Claude plan",
    "örnek veriler için sahte model": "stand-in model for the sample data",
    "Yerel sunucu": "Local server",
    "OpenAI uyumlu servis": "OpenAI-compatible service",
    "Bu klasör örnek veri klasörü değil, dokunulmadı: {path}": "This folder is not a sample-data folder and was left alone: {path}",
    "yerel model, ücretsiz": "local model, free",
    "yerel sunucu, ücretsiz": "local server, free",
    "ücretli API (kendi anahtarın)": "paid API (your own key)",
    "Ücretli API kapalı (llm.allow_paid_api: false).": "Paid APIs are turned off (llm.allow_paid_api: false).",
    "API anahtarı yok ({env})": "The API key is missing ({env})",
    "'{path}' komutu bulunamadı": "The '{path}' command was not found",
    "Model adı gerekli (uzak servis için API anahtarı da).":
        "A model name is required (and an API key for a hosted service).",
    "Önce bir Ollama modeli seç.": "Choose an Ollama model first.",
    "yanıtta JSON nesnesi yok": "no JSON object in the answer",
    "JSON nesnesi kapanmamış (yanıt kesilmiş olabilir)": "the JSON object is not closed (the answer may be cut off)",
    "Model geçerli JSON döndürmedi: {error}": "The model did not return valid JSON: {error}",
    "Model boş yanıt verdi.": "The model returned an empty answer.",
    "Bağlantı çalışıyor.": "The connection works.",
    # semantic matching
    "Anlamsal eşleşme": "Semantic match",
    "İlanlar eşleştiriliyor": "Matching postings",
    "Eşleştirme modeli hazırlanıyor": "Preparing the matching model",
    "Eşleştirilecek hedef alan ya da profil yok.": "There is no track or profile to match against.",
    "Eşleştirme paketi (fastembed) kurulu değil.": "The matching package (fastembed) is not installed.",
    "Eşleştirme paketi yüklenemedi: {error}": "Could not load the matching package: {error}",
    "Bu eşleştirme modeli desteklenmiyor: {model}": "This matching model is not supported: {model}",
    "Eşleştirme modeli yüklenemedi ({model}): {error}": "Could not load the matching model ({model}): {error}",
    "Eşleştirme modeli hata verdi: {error}": "The matching model failed: {error}",
    "Eşleştirme için bir model adı gerekli.": "Matching needs a model name.",
    "Eşleştirme modeli çalışıyor.": "The matching model works.",
    "Akıllı eşleştirme kapalı.": "Smart matching is turned off.",
    "Bir tarama çalışıyor; eşleştirme onun içinde yapılır.": "A scan is running; it does the matching itself.",
    "küçük ve hızlı, 50+ dil (varsayılan)": "small and fast, 50+ languages (default)",
    "Almanca ve İngilizce ilanlar için": "for German and English postings",
    "en güçlüsü, 100+ dil; daha yavaş": "the strongest, 100+ languages; slower",
    # measurements
    "Ön puan (anahtar kelimeler)": "Quick score (keywords)",
    "Anlamsal puan": "Semantic score",
    "İkisi birlikte (yeni sıralama)": "Both fused (the new order)",
    "AI puanı": "AI score",
    "geçersiz etiket: {name}": "invalid label: {name}",
}
