"""Turkish texts of the app. Key: the English text used in t("…"). Checked and turned into Swift by l10n.py."""

TR: dict[str, str] = {}

# --- AIViews.swift
TR.update({
    "Claude Code on this Mac": "Bu Mac'teki Claude Code",
    "Anthropic API key": "Anthropic API anahtarı",
    "OpenAI-compatible service": "OpenAI uyumlu servis",
    "Ollama on this Mac": "Bu Mac'teki Ollama",
    "No AI model": "Yapay zeka modeli yok",
    "Uses your own Claude subscription through the Claude Code program.":
        "Claude Code programı üzerinden kendi Claude aboneliğini kullanır.",
    "Claude models, paid per use with your own key.": "Claude modelleri; kendi anahtarınla, kullandıkça ödersin.",
    "OpenAI, OpenRouter, Groq, Mistral, Gemini, LM Studio and others.":
        "OpenAI, OpenRouter, Groq, Mistral, Gemini, LM Studio ve benzerleri.",
    "Free and private: the model runs on your Mac.": "Ücretsiz ve gizli: model kendi Mac'inde çalışır.",
    "Jobs are still collected and sorted, but not evaluated, and no documents are written.":
        "İlanlar yine toplanır ve sıralanır, ama değerlendirilmez ve belge yazılmaz.",
    "Claude Code": "Claude Code",
    "Found: %@": "Bulundu: %@",
    "JobRadar runs the Claude Code program as it is installed on this Mac. You sign in to Claude Code yourself, with your own account. JobRadar never sees, asks for or stores your Claude login.":
        "JobRadar, Claude Code programını bu Mac'te kurulu olduğu haliyle çalıştırır. Claude Code'a kendi hesabınla kendin giriş yaparsın. JobRadar Claude giriş bilgilerini hiçbir zaman görmez, istemez ve saklamaz.",
    "Open Claude Code in Terminal to sign in…": "Giriş yapmak için Claude Code'u Terminal'de aç…",
    "Usage counts against your own Claude plan under Anthropic's terms.":
        "Kullanım, Anthropic'in koşullarına göre kendi Claude planından düşer.",
    "Claude Code is not installed on this Mac.": "Claude Code bu Mac'te kurulu değil.",
    "Install Claude Code, open it once and sign in with your Claude account. Then come back and press \"Check again\".":
        "Claude Code'u kur, bir kez açıp Claude hesabınla giriş yap. Sonra buraya dönüp \"Yeniden kontrol et\"e bas.",
    "Get Claude Code": "Claude Code'u indir",
    "Check again": "Yeniden kontrol et",
    "Anthropic API": "Anthropic API",
    "Create a key in the Anthropic Console": "Anthropic Console'da anahtar oluştur",
    "This is paid per use and billed by Anthropic to your key.":
        "Kullandıkça ödenir; ücreti Anthropic senin anahtarına yansıtır.",
    "Service": "Servis",
    "Address of the service": "Servisin adresi",
    "model name": "model adı",
    "Hosted services are paid per use and billed to your key. A server on this Mac (LM Studio) is free and needs no key.":
        "İnternetteki servisler kullandıkça ödenir ve ücret senin anahtarına yansır. Bu Mac'te çalışan bir sunucu (LM Studio) ücretsizdir ve anahtar istemez.",
    "Ollama": "Ollama",
    "Ollama runs open models on your own Mac. Install it, download a model (for example in the Ollama app), then load the list here. Larger models judge jobs better but need a Mac with plenty of memory.":
        "Ollama açık modelleri kendi Mac'inde çalıştırır. Kur, bir model indir (örneğin Ollama uygulamasından), sonra listeyi buradan yükle. Büyük modeller ilanları daha iyi değerlendirir ama belleği bol bir Mac ister.",
    "Get Ollama": "Ollama'yı indir",
    "Address of Ollama": "Ollama'nın adresi",
    "API key": "API anahtarı",
    "A key is saved. Type a new one to replace it.": "Bir anahtar kayıtlı. Değiştirmek için yenisini yaz.",
    "Paste your API key": "API anahtarını yapıştır",
    "The key is kept in your Mac's Keychain, never in a file.":
        "Anahtar Mac'inin Anahtar Zinciri'nde tutulur, hiçbir dosyaya yazılmaz.",
    "Forget the key": "Anahtarı sil",
    "Model for judging jobs (fast)": "İlan değerlendirme modeli (hızlı)",
    "Model for writing your CV and letter (best)": "CV ve ön yazı modeli (en iyi)",
    "Load the model list": "Model listesini yükle",
    "%@ models available": "%@ model var",
    "Choose from the list": "Listeden seç",
    "Save": "Kaydet",
    "Save and test": "Kaydet ve dene",
    "Asking the model a test question…": "Modele deneme sorusu soruluyor…",
    "Connected: %@": "Bağlı: %@",
    "Other": "Diğer",
    "The engine is not running yet.": "Motor henüz çalışmıyor.",
    "Ollama did not answer, or it has no model yet. Is Ollama running?":
        "Ollama yanıt vermedi ya da henüz modeli yok. Ollama açık mı?",
    "The service returned no models.": "Servis hiç model döndürmedi.",
    "Saved. JobRadar works without an AI model, but it cannot evaluate jobs or write documents.":
        "Kaydedildi. JobRadar yapay zeka modeli olmadan da çalışır, ama ilanları değerlendiremez ve belge yazamaz.",
    "The model is not ready yet. Check the fields above.": "Model henüz hazır değil. Yukarıdaki alanları kontrol et.",
    "The test did not work.": "Deneme başarısız oldu.",
    "It works. %@ answered in %@ seconds.": "Çalışıyor. %@ %@ saniyede yanıt verdi.",
})

# --- APIClient.swift, AppInstaller.swift
TR.update({
    "The server address and API key are missing. Enter them in Settings (⌘,).":
        "Sunucu adresi ve API anahtarı eksik. Ayarlar'dan gir (⌘,).",
    "The server address is not valid. Example: https://jobradar.example.com":
        "Sunucu adresi geçerli değil. Örnek: https://jobradar.example.com",
    "Not authorized: %@": "Yetki yok: %@",
    "Cloudflare Access stopped the request. Enter the service token in Settings.":
        "Cloudflare Access isteği durdurdu. Ayarlar'dan servis anahtarını gir.",
    "Could not reach JobRadar: %@": "JobRadar'a ulaşılamadı: %@",
    "Could not read the answer: %@": "Yanıt okunamadı: %@",
    "the backup is not a database file": "yedek bir veritabanı dosyası değil",
    "check the API key": "API anahtarını kontrol et",
    "JobRadar shortcut": "JobRadar kısayolu",
    "That did not work: %@": "Olmadı: %@",
    "If macOS asked for access to the Desktop, choose Allow. Later you can change it in System Settings > Privacy & Security > Files and Folders > JobRadar.":
        "macOS Masaüstü için izin sorduysa İzin Ver'i seç. Sonradan Sistem Ayarları > Gizlilik ve Güvenlik > Dosyalar ve Klasörler > JobRadar bölümünden değiştirebilirsin.",
    "Creating the disk image": "Disk görüntüsü oluşturma",
})

# --- AppModel.swift
TR.update({
    "Inbox": "Gelen kutusu",
    "In progress": "Başvuru akışı",
    "Closed": "Sonuçlanan",
    "Filtered out": "Elenen",
    "All": "Tümü",
    "Waiting": "Bekliyor",
    "Off (a remote server is used)": "Kapalı (uzak sunucu kullanılıyor)",
    "Installing: %@": "Kuruluyor: %@",
    "Preparing…": "Hazırlanıyor…",
    "Starting…": "Başlatılıyor…",
    "Running": "Çalışıyor",
    "Error: %@": "Hata: %@",
    "The e-mails could not be read.": "E-postalar okunamadı.",
    "That did not work.": "İşlem başarısız oldu.",
    "Starting": "Başlatılıyor",
    "The scan is finished.": "Tarama bitti.",
    "The scan is finished: %@": "Tarama bitti: %@",
    "The scan ended with an error: %@": "Tarama hata ile bitti: %@",
    "The scan was interrupted.": "Tarama yarıda kaldı.",
    "The scan could not finish: %@": "Tarama tamamlanamadı: %@",
    "Connected. Server %@, %@ jobs in the inbox, AI model: %@.":
        "Bağlantı tamam. Sunucu %@, gelen kutusunda %@ ilan, yapay zeka modeli: %@.",
    "JobRadar: a company replied": "JobRadar: şirketten yanıt",
    "JobRadar: %@ company replies": "JobRadar: %@ şirket yanıtı",
    "JobRadar: a new strong match": "JobRadar: yeni güçlü ilan",
    "JobRadar: %@ new strong matches": "JobRadar: %@ yeni güçlü ilan",
})

# --- ApplicationViews.swift
TR.update({
    "Form answers": "Form cevapları",
    "Copy and paste while you fill in the application form.": "Başvuru formunu doldururken kopyala, yapıştır.",
    "Language": "Dil",
    "Not filled in yet: %@. Add your answers under Profile > Form answers.":
        "Henüz doldurulmamış: %@. Cevaplarını Profil > Form cevapları bölümünden ekle.",
    "Second reading: %@": "İkinci okuma: %@",
    "%@ notes from the second reading": "%@ ikinci okuma notu",
    "%@ requirements your profile supports but the CV does not mention":
        "Profilinin desteklediği ama CV'de geçmeyen %@ şart",
    "PDF check: %@ warnings": "PDF kontrolü: %@ uyarı",
    "PDF check: clean": "PDF kontrolü: temiz",
    "CV %@ pages": "CV %@ sayfa",
    "letter %@ pages": "ön yazı %@ sayfa",
    "%@ of %@ requirements appear in the CV": "şartların %1$@/%2$@ tanesi CV'de",
    "rewritten": "yeniden yazıldı",
    "no source": "kaynak yok",
    "Version %@: what was taken from your profile and how it was written":
        "Sürüm %@: profilden ne alındı, nasıl yazıldı",
    "Changes": "Değişiklikler",
    "Close": "Kapat",
    "On the left the text in the document, on the right the profile facts it rests on. Where a line is marked \"rewritten\", check that the meaning stayed the same.":
        "Solda belgedeki metin, sağda dayandığı profil gerçekleri. \"yeniden yazıldı\" işaretli satırlarda anlamın değişmediğini kontrol et.",
    "Headline and summary": "Başlık ve özet",
    "profile": "profil",
    "Experience": "Deneyim",
    "%@ facts of this entry were not used": "Bu girişten kullanılmayan %@ gerçek",
    "Entries left out of the CV: %@": "CV'ye hiç girmeyen girişler: %@",
    "Skills": "Beceriler",
    "In your profile but not chosen for this CV": "Profilde olup bu CV'de seçilmeyenler",
    "Cover letter": "Ön yazı",
    "Cover letter: %@": "Ön yazı: %@",
    "There is no cover letter.": "Ön yazı yok.",
    "E-mail replies": "E-posta yanıtları",
})

# --- Components.swift, ContentView.swift
TR.update({
    "AI score (0 to 5)": "Yapay zeka puanı (0 ile 5 arası)",
    "Quick score (0 to 100). Not evaluated by the AI model yet.":
        "Ön puan (0 ile 100 arası). Henüz yapay zeka modeliyle değerlendirilmedi.",
    "Remove": "Kaldır",
    "Add…": "Ekle…",
    "Copied": "Kopyalandı",
    "Copy": "Kopyala",
    "OK": "Tamam",
    "No server set up": "Sunucu ayarlanmadı",
    "Enter the server address and its API key in Settings.": "Sunucu adresini ve API anahtarını Ayarlar'a gir.",
    "Open Settings": "Ayarları aç",
    "Your job matches appear here once the engine is running.": "Motor çalışınca sana uyan ilanlar burada görünür.",
    "Engine status": "Motor durumu",
    "Sources, runs and skill gaps are summarised on the left.":
        "Kaynakların, taramaların ve eksik becerilerin özeti solda.",
    "Choose a reply": "Bir yanıt seç",
    "Click \"Show job\" on a reply to open its posting here.":
        "Yanıttaki ilanı burada açmak için \"İlanı göster\"e tıkla.",
    "Choose a job": "Bir ilan seç",
    "Pick a posting from the list to see its evaluation.": "Listeden bir ilan seçince değerlendirmesi burada görünür.",
    "Jobs": "İlanlar",
    "Follow-up": "Takip",
    "You": "Sen",
    "Profile": "Profil",
    "Search": "Arama",
    "Engine": "Motor",
    "Status and sources": "Durum ve kaynaklar",
    "Summary": "Özet",
    "%@ strong matches (≥ %@)": "%@ güçlü ilan (≥ %@)",
    "%@ waiting for evaluation": "%@ ilan değerlendirme bekliyor",
    "%@ applications due for a follow-up": "%@ başvuruda takip zamanı",
    "%@ e-mail replies to review": "%@ e-posta yanıtı onay bekliyor",
    "%@ TODO notes in the profile": "Profilde %@ TODO notu",
    "Scan running": "Tarama sürüyor",
    "Last scan %@": "Son tarama %@",
    "No scan yet": "Henüz tarama yapılmadı",
    "an AI model": "yapay zeka modeli",
    "your profile": "profilin",
    "what to search for": "arama ayarların",
    "Still to set up: %@.": "Kurulumda eksik: %@.",
    "Continue setup": "Kuruluma devam et",
    "%@ of %@ jobs": "%1$@ / %2$@ ilan",
    "%@ jobs": "%@ ilan",
    "Show %@ more": "%@ ilan daha göster",
    "No jobs here": "İlan yok",
    "Title, company, city": "Başlık, şirket, şehir",
    "Track": "Alan",
    "All tracks": "Tüm alanlar",
    "Show one search track only": "Yalnızca bir arama alanını göster",
    "Order": "Sıra",
    "By score": "Puana göre",
    "By date": "Tarihe göre",
    "By company": "Şirkete göre",
    "Sort order": "Sıralama",
    "Add link": "Link ekle",
})

# --- ContentView.swift (rest), Engine.swift
TR.update({
    "Add a posting by its link (⌘L)": "Linkiyle bir ilan ekle (⌘L)",
    "Refresh": "Yenile",
    "Refresh (⌘R)": "Yenile (⌘R)",
    "Scan now": "Şimdi tara",
    "A scan is running": "Tarama sürüyor",
    "Look for new jobs now (⇧⌘R)": "Yeni ilanları şimdi ara (⇧⌘R)",
    "Run a scan to fill your inbox.": "Gelen kutunu doldurmak için bir tarama başlat.",
    "There are no postings in this view.": "Bu görünümde ilan bulunmuyor.",
    "Writing documents": "Belgeler yazılıyor",
    "Evaluating": "Değerlendiriliyor",
    "Add a job by its link": "Linkiyle ilan ekle",
    "Paste the address of a posting: LinkedIn, Indeed, StepStone, a company career page… JobRadar reads the posting and adds it to your inbox.":
        "Bir ilanın adresini yapıştır: LinkedIn, Indeed, StepStone, şirket kariyer sayfası… JobRadar ilanı okuyup gelen kutuna ekler.",
    "Cancel": "Vazgeç",
    "Add": "Ekle",
    "The engine could not start": "Motor başlatılamadı",
    "Try again": "Tekrar dene",
    "Show the log": "Kayıtları göster",
    "Setting up the JobRadar engine": "JobRadar motoru kuruluyor",
    "Step %@ of %@: %@": "Adım %1$@ / %2$@: %3$@",
    "This happens once and needs an internet connection. It can take a few minutes.":
        "Bu yalnızca bir kez yapılır ve internet bağlantısı ister. Birkaç dakika sürebilir.",
    "Starting JobRadar…": "JobRadar başlatılıyor…",
    "The first start takes a few seconds.": "İlk açılış birkaç saniye sürer.",
    "This copy of the app is incomplete: the engine package is missing. Download JobRadar again.":
        "Uygulamanın bu kopyası eksik: motor paketi yok. JobRadar'ı yeniden indir.",
    "The download did not work: %@ Check the internet connection and try again.":
        "İndirme başarısız oldu: %@ İnternet bağlantısını kontrol edip tekrar dene.",
    "A downloaded file did not pass its integrity check. Try again; if this repeats, the network is altering downloads.":
        "İndirilen bir dosya bütünlük kontrolünden geçemedi. Tekrar dene; yine olursa ağ indirmeleri değiştiriyor demektir.",
    "\"%@\" did not finish. Check the internet connection and try again.":
        "\"%@\" adımı tamamlanamadı. İnternet bağlantısını kontrol edip tekrar dene.",
    "\"%@\" did not finish.": "\"%@\" adımı tamamlanamadı.",
    "Downloading the installer": "Kurulum aracı indiriliyor",
    "Installing Python": "Python kuruluyor",
    "Installing the JobRadar engine": "JobRadar motoru kuruluyor",
    "Adding the job boards (LinkedIn, Indeed, Google Jobs)": "İlan siteleri ekleniyor (LinkedIn, Indeed, Google Jobs)",
})

# --- JobDetailView.swift
TR.update({
    "Evaluation": "Değerlendirme",
    "No AI model is connected yet, so jobs cannot be evaluated.":
        "Henüz bir yapay zeka modeli bağlı değil, bu yüzden ilanlar değerlendirilemiyor.",
    "Connect an AI model…": "Yapay zeka modeli bağla…",
    "This posting has not been evaluated yet. Start with \"Evaluate\".":
        "Bu ilan henüz değerlendirilmedi. \"Değerlendir\" ile başlat.",
    "Your contacts at this company": "Bu şirketteki bağlantıların",
    "Loading…": "Yükleniyor…",
    "The posting may be closed": "İlan kapanmış olabilir",
    "Filtered out: %@": "Elenme nedeni: %@",
    "Quick score %@": "Ön puan %@",
    "Posted %@": "Yayın: %@",
    "Evaluate": "Değerlendir",
    "Evaluate again": "Yeniden değerlendir",
    "Automatic language": "Otomatik dil",
    "Write CV and cover letter": "CV ve ön yazı yaz",
    "Open posting": "İlana git",
    "Open in the web panel": "Web panelinde aç",
    "Writing your CV and cover letter. This can take a few minutes.":
        "CV ve ön yazın yazılıyor. Birkaç dakika sürebilir.",
    "Evaluating the posting. This takes a minute or two.": "İlan değerlendiriliyor. Bir iki dakika sürer.",
    "Requirements and evidence": "Şartlar ve kanıtlar",
    "must": "şart",
    "plus": "artı",
    "Evidence in your profile": "Profilindeki kanıt",
    "Hover over an evidence code to see the matching line of your profile.":
        "Kanıt kodunun üstüne gelince profilindeki ilgili satır görünür.",
    "Strengths": "Güçlü yönler",
    "Gaps": "Eksikler",
    "Risks": "Riskler",
    "Application notes": "Başvuru notları",
    "How genuine the posting looks: %@. %@": "İlanın güvenilirliği: %1$@. %2$@",
    "Tips for the CV": "CV için ipuçları",
    "Interview topics": "Mülakat konuları",
    "CV match": "CV uyumu",
    "Fit with your goal": "Hedefe uygunluk",
    "Pay": "Ücret",
    "Culture": "Kültür",
    "Risk (high = low risk)": "Risk (yüksek = az risk)",
    "Posting text": "İlan metni",
    "The posting has no text.": "İlan metni yok.",
    "Show less": "Daha az göster",
    "Show all": "Tamamını göster",
    "History": "Geçmiş",
    "%@ entries": "%@ kayıt",
    "Notes": "Notlar",
    "Documents": "Belgeler",
    "Version %@": "Sürüm %@",
    "Check the notes": "Notlara bak",
    "Verified": "Doğrulandı",
    "Approved": "Onaylandı",
    "Approve": "Onayla",
    "See what changed": "Değişiklikleri gör",
    "The profile fact behind every bullet and paragraph": "Her madde ve paragrafın dayandığı profil gerçeği",
    "%@ verification notes": "%@ doğrulama notu",
    "Open in Preview": "Önizleme'de aç",
    "Save…": "Kaydet…",
})

# --- JobRadarApp.swift, L10n.swift, LocalServer.swift
TR.update({
    "If you quit now, JobRadar stops and the scan is left unfinished. Quit anyway?":
        "Şimdi çıkarsan JobRadar durur ve tarama yarıda kalır. Yine de çıkılsın mı?",
    "Quit": "Çık",
    "About JobRadar": "JobRadar Hakkında",
    "Add a job link…": "İlan linki ekle…",
    "System language": "Sistem dili",
    "The app runs inside the App Sandbox and cannot start its engine. Build it with the App Sandbox turned off.":
        "Uygulama App Sandbox içinde çalıştığı için motorunu başlatamıyor. App Sandbox kapalı olarak derlenmeli.",
    "The engine could not be started: %@": "Motor başlatılamadı: %@",
    "The engine stopped while starting.": "Motor açılırken kapandı.",
    "The engine did not answer within a minute.": "Motor bir dakika içinde yanıt vermedi.",
    "No free local port was found between 8790 and 8799. Close the program that uses them and try again.":
        "8790 ile 8799 arasında boş bir yerel port bulunamadı. Bu portları kullanan programı kapatıp tekrar dene.",
})

# --- MailSignalsView.swift, MenuBarView.swift, Models.swift
TR.update({
    "Replies from companies": "Şirket yanıtları",
    "Rejections, interview invitations, tests and offers in your inbox are matched to your applications. Nothing changes by itself: you apply every suggestion. The mailbox is opened read-only and no mail is marked as read.":
        "Gelen kutundaki ret, mülakat daveti, test ve teklif e-postaları başvurularınla eşleştirilir. Hiçbir şey kendiliğinden değişmez: her öneriyi sen uygularsın. Posta kutusu salt okunur açılır ve hiçbir e-posta okundu olarak işaretlenmez.",
    "Not checked yet": "Henüz kontrol edilmedi",
    "Last checked %@": "Son kontrol %@",
    "Check now": "Şimdi kontrol et",
    "E-mail settings…": "E-posta ayarları…",
    "No reply is waiting": "Bekleyen yanıt yok",
    "When a company answers, the reply shows up here with a suggestion.":
        "Bir şirket yanıt verince, yanıt burada bir öneriyle birlikte görünür.",
    "Waiting for you (%@)": "Onayını bekleyenler (%@)",
    "Recently handled": "Son işlenenler",
    "Show job": "İlanı göster",
    "Job": "İlan",
    "No match: choose the job…": "Eşleşmedi: ilanı seç…",
    "Apply to the chosen job": "Seçilen ilana uygula",
    "Add to the history": "Geçmişe ekle",
    "Apply: %@": "Uygula: %@",
    "Ignore": "Yok say",
    "No server is set up. Open the app and go to Settings.": "Sunucu ayarlanmadı. Uygulamayı açıp Ayarlar'a gir.",
    "inbox": "gelen kutusu",
    "strong": "güçlü",
    "waiting": "bekleyen",
    "applied": "başvuru",
    "%@ company replies to review": "%@ şirket yanıtı onay bekliyor",
    "Strong matches": "Güçlü ilanlar",
    "Open JobRadar": "JobRadar'ı aç",
    "could not run": "çalıştırılamadı",
    "revised with its suggestions": "önerileriyle düzeltildi",
    "revision rejected (unsupported claim)": "düzeltme reddedildi (dayanaksız ifade)",
    "found no problems": "sorun bulmadı",
    "has suggestions": "önerileri var",
    "accepted": "uygulandı",
    "ignored": "yok sayıldı",
    "info": "bilgi",
    "waiting for review": "onay bekliyor",
})

# --- OnboardingView.swift
TR.update({
    "Welcome": "Hoş geldin",
    "AI model": "Yapay zeka modeli",
    "Your profile": "Profilin",
    "Your search": "Araman",
    "Ready": "Hazır",
    "Back": "Geri",
    "Skip the setup": "Kurulumu atla",
    "Get started": "Başla",
    "Save and continue": "Kaydet ve devam et",
    "Continue": "Devam",
    "Using your own server.": "Kendi sunucun kullanılıyor.",
    "Your server is not set up yet.": "Sunucun henüz ayarlanmadı.",
    "The engine is installed and running.": "Motor kuruldu ve çalışıyor.",
    "Setting up the engine: %@ (step %@ of %@)": "Motor kuruluyor: %1$@ (adım %2$@ / %3$@)",
    "Preparing the engine…": "Motor hazırlanıyor…",
    "This happens once, needs an internet connection and can take a few minutes. You can go on meanwhile.":
        "Bu yalnızca bir kez yapılır, internet bağlantısı ister ve birkaç dakika sürebilir. Bu sırada devam edebilirsin.",
    "Starting the engine…": "Motor başlatılıyor…",
    "Welcome to JobRadar": "JobRadar'a hoş geldin",
    "It finds jobs that fit you, judges each one against your real CV, and writes honest applications for the ones you choose.":
        "Sana uyan ilanları bulur, her birini gerçek CV'nle karşılaştırıp değerlendirir ve seçtiklerin için dürüst başvuru belgeleri yazar.",
    "Scans job boards and company career pages for you": "İlan sitelerini ve şirket kariyer sayfalarını senin için tarar",
    "LinkedIn, Indeed, Google Jobs, career pages and more, several times a day.":
        "LinkedIn, Indeed, Google Jobs, kariyer sayfaları ve daha fazlası; günde birkaç kez.",
    "Explains every score": "Her puanı açıklar",
    "Each requirement of a posting is matched to a line of your profile, so you see why a job fits.":
        "İlandaki her şart profilindeki bir satırla eşleştirilir; ilanın neden uyduğunu görürsün.",
    "Writes your CV and cover letter for a job": "İlana özel CV ve ön yazı yazar",
    "Only from facts in your profile. Nothing is invented, and nothing is sent without you.":
        "Yalnızca profilindeki gerçeklerden. Hiçbir şey uydurulmaz, hiçbir şey senden habersiz gönderilmez.",
    "Stays on your Mac": "Mac'inde kalır",
    "Your data lives in a folder on this Mac. You connect your own AI model.":
        "Verilerin bu Mac'teki bir klasörde durur. Kendi yapay zeka modelini bağlarsın.",
    "Language and look": "Dil ve görünüm",
    "Mode": "Mod",
    "Colours": "Renkler",
    "This JobRadar folder is already set up.": "Bu JobRadar klasörü zaten kurulmuş.",
    "I already have JobRadar data, or my own server…": "JobRadar verilerim ya da kendi sunucum var…",
    "Done": "Bitti",
    "Connect an AI model": "Bir yapay zeka modeli bağla",
    "JobRadar uses an AI model to read your CV, to judge each posting against it and to write your application documents. Connect one you already have. You can change it at any time in Settings.":
        "JobRadar CV'ni okumak, her ilanı CV'nle karşılaştırıp değerlendirmek ve başvuru belgelerini yazmak için bir yapay zeka modeli kullanır. Elindeki bir modeli bağla. İstediğin zaman Ayarlar'dan değiştirebilirsin.",
    "Tell JobRadar who you are": "JobRadar'a kendini tanıt",
    "Start from your CV and correct what the AI model read, or type directly into the page below. This profile is what every job is compared with.":
        "CV'nden başla ve yapay zeka modelinin okuduklarını düzelt ya da doğrudan aşağıdaki sayfaya yaz. Her ilan bu profille karşılaştırılır.",
    "What should JobRadar look for?": "JobRadar ne arasın?",
    "Say what you want and where. You can fine-tune the keywords, sources and filters later under Search.":
        "Ne istediğini ve nerede istediğini söyle. Anahtar kelimeleri, kaynakları ve filtreleri sonra Arama bölümünden inceltebilirsin.",
    "You are all set": "Her şey hazır",
    "Almost there": "Az kaldı",
    "JobRadar can now look for jobs. The first scan takes a few minutes; matches appear in your inbox as they are found and evaluated.":
        "JobRadar artık ilan arayabilir. İlk tarama birkaç dakika sürer; ilanlar bulunup değerlendirildikçe gelen kutunda görünür.",
    "Something is still missing. You can go back and finish it, or open JobRadar and complete the setup later.":
        "Hâlâ eksik bir şey var. Geri dönüp tamamlayabilir ya da JobRadar'ı açıp kurulumu sonra bitirebilirsin.",
    "Not connected: jobs are collected but not evaluated.": "Bağlı değil: ilanlar toplanır ama değerlendirilmez.",
    "%@ search tracks": "%@ arama alanı",
    "Job boards": "İlan siteleri",
    "Optional: connect your mailbox": "İsteğe bağlı: posta kutunu bağla",
    "Get a daily summary and alerts by e-mail, and let JobRadar notice replies from companies.":
        "Günlük özeti ve uyarıları e-postayla al, JobRadar şirketlerden gelen yanıtları fark etsin.",
    "Open the e-mail settings…": "E-posta ayarlarını aç…",
    "Start the first scan": "İlk taramayı başlat",
    "Open JobRadar without scanning": "Tarama yapmadan JobRadar'ı aç",
    "Not created yet.": "Henüz oluşturulmadı.",
    "Still missing: %@.": "Eksikler: %@.",
})

# --- OnboardingView.swift (rest), ProfileViews.swift
TR.update({
    "Being added in the background…": "Arka planda ekleniyor…",
    "Could not be installed. You can try again under Search.": "Kurulamadı. Arama bölümünden tekrar deneyebilirsin.",
    "LinkedIn, Indeed and others are ready.": "LinkedIn, Indeed ve diğerleri hazır.",
    "Saved.": "Kaydedildi.",
    "The CV could not be read.": "CV okunamadı.",
    "Filled in from your CV. Check the details, then save.": "CV'nden dolduruldu. Ayrıntıları kontrol et, sonra kaydet.",
    "your name": "adın",
    "at least one job, degree or project": "en az bir iş, eğitim ya da proje",
    "a few lines about what you did": "neler yaptığını anlatan birkaç satır",
    "your skills": "becerilerin",
    "Notice period, relocation, salary: answer the standard questions of application forms once, then copy them for every job.":
        "İhbar süresi, taşınma, maaş: başvuru formlarının standart sorularını bir kez cevapla, sonra her ilan için kopyala.",
    "Edit form answers…": "Form cevaplarını düzenle…",
    "Why this matters": "Neden önemli",
    "Every line of your profile is a fact with its own code. Evaluations point to these facts, and tailored CVs and letters may only use them, so nothing about you is ever made up.":
        "Profilindeki her satır, kendi kodu olan bir gerçektir. Değerlendirmeler bu gerçeklere dayanır; ilana özel CV ve ön yazılar yalnızca bunları kullanabilir. Böylece hakkında hiçbir şey uydurulmaz.",
    "Save profile": "Profili kaydet",
    "Save the profile (⌘S)": "Profili kaydet (⌘S)",
    "Your profile is ready.": "Profilin hazır.",
    "%@ facts · %@ skills": "%@ gerçek · %@ beceri",
    "Edit the page on the right like a CV: click any text to change it.":
        "Sağdaki sayfayı bir CV gibi düzenle: değiştirmek istediğin metne tıkla.",
    "Undo changes": "Değişiklikleri geri al",
    "You have unsaved changes.": "Kaydedilmemiş değişikliklerin var.",
    "Start from your CV": "CV'nden başla",
    "Drop your CV here (PDF, Word or text). The AI model reads it and fills in the profile. You check the result before anything is saved.":
        "CV'ni buraya bırak (PDF, Word ya da metin). Yapay zeka modeli okuyup profili doldurur. Hiçbir şey kaydedilmeden önce sonucu sen kontrol edersin.",
    "Reading your CV. This takes about a minute…": "CV'n okunuyor. Yaklaşık bir dakika sürer…",
    "Connect an AI model first. It is needed to read the CV.":
        "Önce bir yapay zeka modeli bağla. CV'yi okumak için gerekli.",
    "Replace the current profile with the CV?": "Şimdiki profil CV ile değiştirilsin mi?",
    "Replace": "Değiştir",
    "Your work permit, availability and preferences are kept. Nothing is saved until you press Save.":
        "Çalışma izni, uygunluk ve tercih bilgilerin korunur. Kaydet'e basana kadar hiçbir şey kaydedilmez.",
    "Choose a file…": "Dosya seç…",
    "Choose your CV (PDF, Word or text)": "CV'ni seç (PDF, Word ya da metin)",
    "Read": "Oku",
    "Who you are professionally, in a line or two": "Mesleki olarak kim olduğun, bir iki satırda",
    "Education": "Eğitim",
    "Projects": "Projeler",
    "Your name": "Adın soyadın",
    "Headline, for example: Embedded Software Engineer": "Başlık, örneğin: Gömülü Yazılım Mühendisi",
    "E-mail": "E-posta",
    "Phone": "Telefon",
    "City": "Şehir",
    "Address (optional)": "Adres (isteğe bağlı)",
    "Add a link (LinkedIn, GitHub, portfolio)": "Link ekle (LinkedIn, GitHub, portfolyo)",
    "Name": "Ad",
    "Add a line": "Satır ekle",
    "The code evaluations use to point at this line": "Değerlendirmelerin bu satırı göstermek için kullandığı kod",
    "Remove this line": "Bu satırı kaldır",
    "Internship": "Staj",
    "Working student": "Çalışan öğrenci",
    "Thesis": "Tez",
    "Volunteering": "Gönüllü çalışma",
    "Employment": "İş",
    "Add a degree": "Eğitim ekle",
    "Add a project": "Proje ekle",
    "Add a job": "İş ekle",
    "Nothing here yet.": "Henüz bir şey yok.",
    "Degree or programme": "Bölüm ya da program",
    "Project name": "Proje adı",
    "Job title": "Pozisyon",
    "School or university": "Okul ya da üniversite",
    "For whom or where (optional)": "Kimin için ya da nerede (isteğe bağlı)",
    "Company": "Şirket",
    "Start": "Başlangıç",
    "End": "Bitiş",
    "Place": "Yer",
    "What you did or achieved, one fact per line": "Ne yaptığın ya da ne başardığın; her satıra bir gerçek",
    "Kind": "Tür",
    "Move up": "Yukarı taşı",
    "Move down": "Aşağı taşı",
    "Delete this entry": "Bu girişi sil",
    "Add a group": "Grup ekle",
    "Group your skills, for example: Programming, Tools, Methods.":
        "Becerilerini grupla, örneğin: Programlama, Araçlar, Yöntemler.",
    "Group": "Grup",
    "Add a skill…": "Beceri ekle…",
    "Remove this group": "Bu grubu kaldır",
    "Languages": "Diller",
    "Add a language": "Dil ekle",
    "Level": "Seviye",
    "Native": "Ana dil",
    "Right to work and availability": "Çalışma izni ve uygunluk",
    "Citizenship": "Vatandaşlık",
    "Country code, e.g. DE": "Ülke kodu, örn. TR",
    "Work permit": "Çalışma izni",
    "For example: EU citizen, Blue Card, needs sponsorship": "Örneğin: AB vatandaşı, Mavi Kart, sponsorluk gerekli",
    "Earliest start": "En erken başlangıç",
    "For example: immediately, 3 months' notice": "Örneğin: hemen, 3 ay ihbar süresi",
    "What you want": "Ne istiyorsun",
    "These lines never appear in a CV. They guide how each job is judged.":
        "Bu satırlar hiçbir CV'de görünmez. Her ilanın nasıl değerlendirileceğine yön verir.",
    "Deal-breakers": "Olmazsa olmazlar",
    "e.g. shift work": "örn. vardiyalı çalışma",
    "Nice to have": "Olsa iyi olur",
    "e.g. remote work": "örn. uzaktan çalışma",
    "Salary expectation": "Maaş beklentisi",
    "For example: 60,000 € a year": "Örneğin: yıllık 60.000 €",
    "Anything else the evaluation should know": "Değerlendirmenin bilmesi gereken başka her şey",
    "Answer each question once. On every job page you can copy the answers into the application form. Rows you leave empty are not shown.":
        "Her soruyu bir kez cevapla. Her ilan sayfasında cevapları başvuru formuna kopyalayabilirsin. Boş bıraktığın satırlar gösterilmez.",
    "Add a question": "Soru ekle",
    "Question": "Soru",
    "Remove this question": "Bu soruyu kaldır",
    "Your answer": "Cevabın",
    "Your answer in %@": "Cevabın (%@)",
    "Your answer in English": "Cevabın (İngilizce)",
})

# --- ScanProgressView.swift, SearchViews.swift
TR.update({
    "Starting the quick scan": "Hızlı tarama başlatılıyor",
    "Starting the scan": "Tarama başlatılıyor",
    "Quick scan running": "Hızlı tarama sürüyor",
    "Quick scan: %@": "Hızlı tarama: %@",
    "Scan: %@": "Tarama: %@",
    "JobRadar is preparing the scan…": "JobRadar taramayı hazırlıyor…",
    "Working…": "Çalışıyor…",
    "%@ s": "%@ sn",
    "%@ min %@ s": "%@ dk %@ sn",
    "%@ h %@ min": "%@ sa %@ dk",
    "Saved. The next scan uses the new settings.": "Kaydedildi. Sonraki tarama yeni ayarları kullanır.",
    "No search tracks could be made from that. Describe the roles in a few words.":
        "Bundan arama alanı çıkarılamadı. Aradığın işleri birkaç kelimeyle anlat.",
    "Made %@ search tracks. Check them, then save.": "%@ arama alanı oluşturuldu. Kontrol et, sonra kaydet.",
    "Full-time": "Tam zamanlı",
    "Part-time": "Yarı zamanlı",
    "Trainee": "Trainee",
    "Apprenticeship": "Çıraklık",
    "Freelance": "Serbest",
    "Contract": "Sözleşmeli",
    "Save search": "Aramayı kaydet",
    "Save the search settings (⌘S)": "Arama ayarlarını kaydet (⌘S)",
    "What are you looking for?": "Ne arıyorsun?",
    "Describe the jobs you want in your own words. JobRadar turns that into search tracks with the right keywords for the job boards of your country.":
        "İstediğin işleri kendi cümlelerinle anlat. JobRadar bunu, ülkendeki ilan sitelerine uygun anahtar kelimeleri olan arama alanlarına çevirir.",
    "For example: junior data analyst, business intelligence, SQL and Python, no sales roles":
        "Örneğin: junior veri analisti, iş zekası, SQL ve Python, satış rolleri olmasın",
    "Make search tracks": "Arama alanlarını oluştur",
    "Thinking… up to a minute.": "Düşünüyor… bir dakikaya kadar sürebilir.",
    "No AI model is connected, so the tracks are made from your words alone. With a model they get much better keywords.":
        "Yapay zeka modeli bağlı değil; alanlar yalnızca senin kelimelerinden oluşturulur. Bir modelle çok daha iyi anahtar kelimeler çıkar.",
    "Replace the current search tracks?": "Şimdiki arama alanları değiştirilsin mi?",
    "The new tracks replace the ones you have now. Nothing is saved until you press Save.":
        "Yeni alanlar şimdikilerin yerini alır. Kaydet'e basana kadar hiçbir şey kaydedilmez.",
    "Where?": "Nerede?",
    "Country": "Ülke",
    "Choose a country": "Ülke seç",
    "Cities": "Şehirler",
    "Add a city": "Şehir ekle",
    "Without a city, the whole country is searched.": "Şehir eklemezsen bütün ülke aranır.",
    "Include remote jobs": "Uzaktan çalışma ilanlarını da ara",
    "Radius": "Yarıçap",
    "%@ km": "%@ km",
    "Search tracks": "Arama alanları",
    "A track is one direction of your search, with the words that find and recognise its postings.":
        "Bir alan, aramanın bir yönüdür; ilanlarını bulan ve tanıyan kelimelerle birlikte.",
    "Add a track": "Alan ekle",
    "Name of the track": "Alanın adı",
    "Active": "Etkin",
    "Delete this track": "Bu alanı sil",
    "The ideal role in a sentence or two (field, level, kind of employer)":
        "İdeal rol, bir iki cümleyle (alan, seviye, işveren türü)",
    "Search terms: typed into the job boards, the most productive first":
        "Arama terimleri: ilan sitelerine yazılır, en verimlisi en başta",
    "Add a search term…": "Arama terimi ekle…",
    "Title words: a posting's title must contain one of these (word stems work)":
        "Başlık kelimeleri: ilan başlığında bunlardan biri geçmeli (kelime kökleri de olur)",
    "Add a title word…": "Başlık kelimesi ekle…",
    "Topic words: tools and terms in the description that raise the score":
        "Konu kelimeleri: ilan metninde geçince puanı yükselten araçlar ve terimler",
    "Add a topic word…": "Konu kelimesi ekle…",
    "Search the whole country for this track, not only around your cities":
        "Bu alan için yalnızca şehirlerinin çevresini değil, bütün ülkeyi ara",
    "Where the jobs come from": "İlanlar nereden geliyor",
    "Bundesagentur für Arbeit (Germany's public job board)": "Bundesagentur für Arbeit (Almanya'nın resmi ilan sitesi)",
    "freehire.me (XING, EURES and company pages in Europe)": "freehire.me (XING, EURES ve Avrupa'daki şirket sayfaları)",
    "freehire.me allows reading without a key for personal, non-commercial use only.":
        "freehire.me anahtarsız okumaya yalnızca kişisel, ticari olmayan kullanım için izin verir.",
    "Adding the job board connectors… they are ready in a minute.":
        "İlan sitesi bağlantıları ekleniyor… bir dakika içinde hazır olur.",
    "The job board connectors could not be installed: %@": "İlan sitesi bağlantıları kurulamadı: %@",
    "The server has no job board connectors (python-jobspy) installed.":
        "Sunucuda ilan sitesi bağlantıları (python-jobspy) kurulu değil.",
    "Job boards limit how often they can be read. JobRadar reads them slowly and only for you; please respect their terms.":
        "İlan siteleri ne sıklıkta okunabileceklerini sınırlar. JobRadar onları yavaşça ve yalnızca senin için okur; lütfen kullanım koşullarına uy.",
    "Company career pages": "Şirket kariyer sayfaları",
    "Follow the career page of a company directly. Paste its address; JobRadar recognises the common career systems (Greenhouse, Lever, Personio, Workday and others).":
        "Bir şirketin kariyer sayfasını doğrudan takip et. Adresini yapıştır; JobRadar yaygın kariyer sistemlerini tanır (Greenhouse, Lever, Personio, Workday ve diğerleri).",
    "Address of the company's job list": "Şirketin ilan listesinin adresi",
    "Added. Give it the right name, then save.": "Eklendi. Doğru adı ver, sonra kaydet.",
    "This page is already in the list.": "Bu sayfa zaten listede.",
    "What to leave out": "Neler elensin",
    "Skip postings whose title contains": "Başlığında şunlar geçen ilanları atla",
    "Add a word…": "Kelime ekle…",
    "Skip these companies": "Bu şirketleri atla",
    "Add a company…": "Şirket ekle…",
    "Skip senior and lead roles": "Kıdemli ve yönetici rollerini atla",
    "Skip staffing agencies": "Aracı firmaları atla",
    "Keep only postings whose title fits a track": "Yalnızca başlığı bir alana uyan ilanları tut",
    "Fine tuning": "İnce ayar",
    "Kinds of employment": "Çalışma türleri",
    "Ignore postings older than %@ days": "%@ günden eski ilanları yok say",
    "Evaluate up to %@ postings per scan with the AI model":
        "Her taramada en çok %@ ilanı yapay zeka modeliyle değerlendir",
    "Only evaluate postings with a quick score of %@ or more":
        "Yalnızca ön puanı %@ ve üstü olan ilanları değerlendir",
    "A strong match scores %@ or more (out of 5)": "Güçlü ilan: puanı %@ ve üstü (5 üzerinden)",
    "Each evaluation uses your AI model once, so the number per scan decides how much of your plan or credit a scan uses.":
        "Her değerlendirme yapay zeka modelini bir kez kullanır; bu yüzden tarama başına sayı, bir taramanın planından ya da kredinden ne kadar harcayacağını belirler.",
})

# --- SettingsView.swift
TR.update({
    "General": "Genel",
    "Engine and data": "Motor ve veriler",
    "Advanced": "Gelişmiş",
    "Interface language": "Arayüz dili",
    "Evaluations are written in": "Değerlendirmelerin dili",
    "The interface language": "Arayüz dili",
    "CV and letter, when a posting's language is unclear": "İlanın dili belli değilse CV ve ön yazının dili",
    "By country (%@)": "Ülkeye göre (%@)",
    "A CV and letter are normally written in the language of the posting.":
        "CV ve ön yazı normalde ilanın dilinde yazılır.",
    "Appearance": "Görünüm",
    "Content boxes": "İçerik kutuları",
    "Let the desktop shine through the window": "Masaüstü pencereden görünsün",
    "Behaviour": "Davranış",
    "Notify me about strong matches and company replies": "Güçlü ilanlarda ve şirket yanıtlarında bildirim göster",
    "Scan automatically at 08:00, 13:00 and 19:00": "08:00, 13:00 ve 19:00'da otomatik tara",
    "Scans run while the app is open (it can stay in the menu bar). A scan missed during sleep runs once after waking.":
        "Taramalar uygulama açıkken yapılır (menü çubuğunda durabilir). Uyku sırasında kaçan bir tarama, Mac uyanınca bir kez yapılır.",
    "Open JobRadar when I log in": "Oturum açtığımda JobRadar'ı aç",
    "Remind me to follow up %@ days after applying": "Başvurudan %@ gün sonra takip etmemi hatırlat",
    "macOS did not accept that: %@": "macOS bunu kabul etmedi: %@",
    "With a mailbox connected, JobRadar can send you a daily summary and an alert for strong matches, and it can spot replies from companies in your inbox. Your mailbox is only read, never changed.":
        "Bir posta kutusu bağlıyken JobRadar sana günlük özet ve güçlü ilanlar için uyarı gönderebilir, gelen kutundaki şirket yanıtlarını da fark edebilir. Posta kutun yalnızca okunur, hiçbir zaman değiştirilmez.",
    "Mailbox": "Posta kutusu",
    "Provider": "Sağlayıcı",
    "E-mail address": "E-posta adresi",
    "App password": "Uygulama şifresi",
    "Saved. Type a new one to replace it.": "Kayıtlı. Değiştirmek için yenisini yaz.",
    "Not your normal password": "Normal şifren değil",
    "Create an app password for %@": "%@ için uygulama şifresi oluştur",
    "Gmail, iCloud and Yahoo need an app password, which you create in your account's security settings (two-step verification must be on). It is kept in your Mac's Keychain.":
        "Gmail, iCloud ve Yahoo bir uygulama şifresi ister; bunu hesabının güvenlik ayarlarından oluşturursun (iki adımlı doğrulama açık olmalı). Şifre Mac'inin Anahtar Zinciri'nde tutulur.",
    "Send summaries to": "Özetlerin gideceği adres",
    "The same address": "Aynı adres",
    "Servers": "Sunucular",
    "Outgoing server (SMTP)": "Giden sunucu (SMTP)",
    "SMTP port": "SMTP portu",
    "Incoming server (IMAP)": "Gelen sunucu (IMAP)",
    "IMAP port": "IMAP portu",
    "What JobRadar does with it": "JobRadar bununla ne yapar",
    "Send a daily summary of new matches": "Yeni ilanların günlük özetini gönder",
    "Send an alert at once for a strong match": "Güçlü bir ilan çıkınca hemen uyarı gönder",
    "Look for replies from companies in the inbox": "Gelen kutusunda şirket yanıtlarını ara",
    "Save and send a test e-mail": "Kaydet ve deneme e-postası gönder",
    "Disconnect": "Bağlantıyı kes",
    "It works: a test e-mail is on its way, and the inbox can be read.":
        "Çalışıyor: deneme e-postası yola çıktı ve gelen kutusu okunabiliyor.",
    "The mailbox is disconnected.": "Posta kutusunun bağlantısı kesildi.",
    "Where JobRadar runs": "JobRadar nerede çalışsın",
    "On this Mac": "Bu Mac'te",
    "On my own server": "Kendi sunucumda",
    "The app runs its engine on this Mac while it is open. Nothing leaves your Mac except the requests to the job boards and to your AI model.":
        "Uygulama açıkken motorunu bu Mac'te çalıştırır. İlan sitelerine ve yapay zeka modeline giden istekler dışında Mac'inden hiçbir şey çıkmaz.",
    "For people who run the JobRadar engine on a server of their own: enter its address and API key.":
        "JobRadar motorunu kendi sunucusunda çalıştıranlar için: sunucunun adresini ve API anahtarını gir.",
    "Test the connection": "Bağlantıyı dene",
    "Apply changes": "Değişiklikleri uygula",
    "Changes applied": "Uygulandı",
    "Backups": "Yedekler",
    "Last backup": "Son yedek",
    "none yet": "henüz yok",
    "Back up now": "Şimdi yedekle",
    "Show backups": "Yedekleri göster",
    "While the app is open, a copy of your database is kept every day (the last 14 days).":
        "Uygulama açıkken veritabanının bir kopyası her gün ayrıca saklanır (son 14 gün).",
    "Your data": "Verilerin",
    "Folder": "Klasör",
    "Choose another folder…": "Başka klasör seç…",
    "Use the standard folder": "Standart klasörü kullan",
    "Show in Finder": "Finder'da göster",
    "Your profile, settings, job database and generated documents live in this folder. A folder from an earlier JobRadar setup can be chosen as it is.":
        "Profilin, ayarların, ilan veritabanın ve üretilen belgeler bu klasörde durur. Daha önceki bir JobRadar kurulumunun klasörü olduğu gibi seçilebilir.",
    "State": "Durum",
    "Version": "Sürüm",
    "Restart": "Yeniden başlat",
    "Restarting now leaves the scan unfinished.": "Şimdi yeniden başlatırsan tarama yarıda kalır.",
    "Install again…": "Yeniden kur…",
    "Install the engine again?": "Motor yeniden kurulsun mu?",
    "Install again": "Yeniden kur",
    "Python and the engine are downloaded and installed again. Your data is not touched.":
        "Python ve motor yeniden indirilip kurulur. Verilerine dokunulmaz.",
    "Adding the job board connectors…": "İlan sitesi bağlantıları ekleniyor…",
    "Server": "Sunucu",
    "Address": "Adres",
    "The key your server shows for \"jobradar api-token\"": "Sunucunda \"jobradar api-token\" komutunun gösterdiği anahtar",
    "Cloudflare Access (optional)": "Cloudflare Access (isteğe bağlı)",
    "Service token client ID": "Servis anahtarı Client ID",
    "Service token client secret": "Servis anahtarı Client Secret",
    "Only needed when your server's address is protected by Cloudflare Access.":
        "Yalnızca sunucunun adresini Cloudflare Access ile koruduysan gerekir.",
    "Choose": "Seç",
    "Choose the folder for your JobRadar data. An existing JobRadar folder (with jobradar.yaml) keeps everything it has.":
        "JobRadar verilerinin duracağı klasörü seç. Var olan bir JobRadar klasörü (içinde jobradar.yaml olan) her şeyiyle korunur.",
    "Add jobs from your browser": "Tarayıcıdan ilan ekle",
    "Copy the code and make it the address of a bookmark. On any job posting, click that bookmark: JobRadar opens and offers to add the posting. Chrome: right-click the bookmarks bar > Add page, and paste the code as the URL. Safari: bookmark any page, then edit the bookmark's address and paste the code.":
        "Kodu kopyala ve bir yer iminin adresi yap. Herhangi bir ilan sayfasındayken o yer imine tıkla: JobRadar açılır ve ilanı eklemeyi önerir. Chrome: yer imleri çubuğuna sağ tık > Sayfa ekle, kodu URL alanına yapıştır. Safari: herhangi bir sayfayı yer imine ekle, sonra yer iminin adresini düzenleyip kodu yapıştır.",
    "Copy the bookmark code": "Yer imi kodunu kopyala",
    "Setup": "Kurulum",
    "Run the setup assistant again": "Kurulum yardımcısını yeniden çalıştır",
    "Put a shortcut on the Desktop": "Masaüstüne kısayol koy",
    "Share the app": "Uygulamayı paylaş",
    "Packs this copy of JobRadar into a disk image (.dmg) that other people can open and drag into their Applications folder. It contains the app only, none of your data.":
        "JobRadar'ın bu kopyasını, başkalarının açıp Uygulamalar klasörüne sürükleyebileceği bir disk görüntüsüne (.dmg) paketler. İçinde yalnızca uygulama vardır, verilerinden hiçbiri yoktur.",
    "Create a disk image…": "Disk görüntüsü oluştur…",
    "Macs warn about apps from developers Apple does not know. To avoid that warning for other people, the app must be signed with an Apple Developer ID and notarised by Apple.":
        "Mac'ler, Apple'ın tanımadığı geliştiricilerin uygulamaları için uyarı gösterir. Başkalarında bu uyarının çıkmaması için uygulamanın bir Apple Developer ID ile imzalanması ve Apple tarafından onaylanması (notarization) gerekir.",
    "About": "Hakkında",
    "App version": "Uygulama sürümü",
    "Engine version": "Motor sürümü",
    "JobRadar is free software under the MIT licence. It builds on JobSpy and ideas from career-ops, JobNavigator and JobCtrl.":
        "JobRadar, MIT lisanslı özgür bir yazılımdır. JobSpy'ı ve career-ops, JobNavigator ile JobCtrl projelerinin fikirlerini temel alır.",
    "The shortcut is on your Desktop.": "Kısayol masaüstünde.",
    "Created: %@": "Oluşturuldu: %@",
})

# --- StatsView.swift, Theme.swift
TR.update({
    "Runs on": "Çalıştığı yer",
    "This Mac (started by the app)": "Bu Mac (uygulama çalıştırıyor)",
    "Idle": "Boşta",
    "Last scan": "Son tarama",
    "Last error": "Son hata",
    "Last quick scan": "Son hızlı tarama",
    "E-mail check": "E-posta kontrolü",
    "%@, %@ replies to review": "%@, %@ yanıt onay bekliyor",
    "E-mail error": "E-posta hatası",
    "Waiting for evaluation": "Değerlendirme bekleyen",
    "%@, %@ TODO notes": "%@, %@ TODO notu",
    "Application funnel": "Başvuru hunisi",
    "Sources": "Kaynaklar",
    "Source": "Kaynak",
    "Evaluated": "Değerl.",
    "Strong": "Güçlü",
    "Applied": "Başvuru",
    "Avg.": "Ort.",
    "Source health": "Kaynak sağlığı",
    "Every source delivered results in the last run.": "Bütün kaynaklar son taramada sonuç verdi.",
    "No results in the last %@ runs": "Son %@ taramada sonuç yok",
    "Skill gaps": "Eksik beceriler",
    "The requirements that are most often missing or only partly met in %@ jobs scored %@ or higher (last %@ days). Hover over a skill to see examples.":
        "Puanı %2$@ ve üstü olan %1$@ ilanda (son %3$@ gün) en sık eksik ya da kısmen karşılanan şartlar. Örnekleri görmek için becerinin üstüne gel.",
    "No recurring gap was found.": "Tekrar eden eksik bulunmadı.",
    "Skill": "Beceri",
    "Missing": "Eksik",
    "Partly": "Kısmen",
    "Required": "Zorunlu",
    "Repeated gaps that are not technical terms": "Teknik terim olmayan tekrarlar",
    "%@ (%@ jobs)": "%@ (%@ ilan)",
    "Match the system": "Sisteme uy",
    "Light": "Açık",
    "Dark": "Koyu",
    "Liquid Glass": "Liquid Glass",
    "Frosted": "Buzlu cam",
    "Aurora": "Aurora",
    "Sunset": "Gün batımı",
    "Ocean": "Okyanus",
    "Forest": "Orman",
    "Graphite": "Grafit",
    "Apply": "Başvur",
    "Maybe": "Belki",
    "Skip": "Geç",
})

# --- sample data, AI test
TR.update({
    "Just looking?": "Sadece bakmak mı istiyorsun?",
    "Open JobRadar with made-up jobs and a made-up profile, and see how it works before you set it up.":
        "JobRadar'ı uydurma ilanlar ve uydurma bir profille aç; kurmadan önce nasıl çalıştığını gör.",
    "Look around with sample data": "Örnek verilerle göz at",
    "Sample data": "Örnek veriler",
    "These jobs and this profile are made up. Nothing is scanned or sent.":
        "Bu ilanlar ve profil uydurma. Hiçbir şey taranmaz ya da gönderilmez.",
    "Leave the sample data": "Örnek verilerden çık",
    "The connection test failed: %@": "Bağlantı denemesi başarısız oldu: %@",
    "This copy runs from Xcode, so JobRadar first builds the release version from your project (a few minutes) and puts the disk image into the project's dist folder.":
        "Bu kopya Xcode'dan çalışıyor; JobRadar önce projenden yayın sürümünü derler (birkaç dakika) ve disk görüntüsünü projenin dist klasörüne koyar.",
    "Building the release version…": "Yayın sürümü derleniyor…",
    "Building the release version": "Yayın sürümünün derlenmesi",
    "This copy was started from Xcode for testing. For a disk image to hand out, double-click scripts/make-dmg.command in the project folder instead: it makes the release build.":
        "Bu kopya deneme için Xcode'dan başlatıldı. Dağıtacağın disk görüntüsü için proje klasöründeki scripts/make-dmg.command dosyasına çift tıkla: yayın derlemesini o yapar.",
})

# --- data of an earlier JobRadar
TR.update({
    "Data from an earlier JobRadar was found in %@.": "%@ klasöründe önceki bir JobRadar'ın verileri bulundu.",
    "Bring it over to continue where you left off: your profile, jobs, documents and settings are copied into JobRadar's own folder. The earlier folder is left as it is.":
        "Kaldığın yerden devam etmek için buraya aktar: profilin, ilanların, belgelerin ve ayarların JobRadar'ın kendi klasörüne kopyalanır. Önceki klasör olduğu gibi kalır.",
    "Bring my data over": "Verilerimi aktar",
    "Bringing your data over…": "Verilerin aktarılıyor…",
    "The data could not be brought over: %@": "Veriler aktarılamadı: %@",
    "Your data was brought over.": "Verilerin aktarıldı.",
    "The earlier daily timer was removed.": "Önceki günlük zamanlayıcı kaldırıldı.",
    "What was here before is kept in %@.": "Daha önce burada olanlar %@ klasöründe duruyor.",
})

# --- smart matching and measurements (MatchingViews.swift, and their places in other views)
TR.update({
    "Matching": "Eşleştirme",
    "Adding smart matching": "Akıllı eşleştirme ekleniyor",
    "Semantic score %@": "Anlamsal puan %@",
    "Your verdict: %@": "Senin kararın: %@",
    "Take my verdict back": "Kararımı geri al",
    "My verdict": "Benim kararım",
    "Say whether this job fits you. JobRadar measures its rankings and rules against your verdicts.":
        "Bu ilanın sana uyup uymadığını söyle. JobRadar sıralamalarını ve kurallarını senin kararlarına göre ölçer.",
    "Fits": "Uygun",
    "Does not fit": "Uygun değil",
    "Cannot tell": "Karar veremiyorum",
    "Smart matching compares every posting with your search tracks and your profile by meaning, not only by keywords. Evaluations then go first to the postings that keywords and meaning agree on, and a posting your keywords would miss can still reach you. Rules you set yourself (title words, seniority, kind of job) always hold.":
        "Akıllı eşleştirme her ilanı arama alanların ve profilinle sadece anahtar kelimelere göre değil, anlamına göre de karşılaştırır. Değerlendirmeler önce anahtar kelimelerin ve anlamın birlikte işaret ettiği ilanlara gider; anahtar kelimelerinin kaçıracağı bir ilan da sana ulaşabilir. Kendi koyduğun kurallar (başlık kelimeleri, kıdem, çalışma türü) her zaman geçerlidir.",
    "Smart matching": "Akıllı eşleştirme",
    "Use smart matching": "Akıllı eşleştirmeyi kullan",
    "Let strong matches pass the keyword rules": "Güçlü eşleşmeler anahtar kelime kurallarını aşabilsin",
    "Such postings carry the \"Semantic match\" badge. At most %@ are let through per scan.":
        "Bu ilanlar \"Anlamsal eşleşme\" işaretini taşır. Her taramada en fazla %@ ilan öne çıkarılır.",
    "Model": "Model",
    "Runs with": "Nerede çalışsın",
    "Built into JobRadar": "JobRadar'ın içinde",
    "The model is downloaded once from Hugging Face and then runs on this Mac. Your profile and the postings are not sent anywhere for it.":
        "Model bir kez Hugging Face'ten indirilir, sonra bu Mac'te çalışır. Bunun için profilin ve ilanlar hiçbir yere gönderilmez.",
    "The address in the AI model settings": "Yapay zeka modeli ayarlarındaki adres",
    "An embedding model of Ollama, for example bge-m3. Download it in Ollama first.":
        "Ollama'daki bir embedding modeli, örneğin bge-m3. Önce Ollama'da indir.",
    "Any service with an OpenAI-compatible embeddings endpoint. A paid service is only used when a paid AI model is allowed.":
        "OpenAI uyumlu embedding sunan herhangi bir servis. Ücretli bir servis yalnızca ücretli yapay zeka modeline izin verilmişse kullanılır.",
    "Jobs with a semantic score": "Anlamsal puanı olan ilanlar",
    "Let through by smart matching": "Akıllı eşleştirmenin öne çıkardıkları",
    "Last run": "Son çalışma",
    "%@ jobs are compared in the next scan.": "%@ ilan bir sonraki taramada karşılaştırılacak.",
    "Test the model": "Modeli dene",
    "Compare my jobs now": "İlanlarımı şimdi karşılaştır",
    "Adding smart matching to the engine…": "Akıllı eşleştirme motora ekleniyor…",
    "Smart matching could not be added to the engine: %@": "Akıllı eşleştirme motora eklenemedi: %@",
    "The engine does not have the matching package yet.": "Motorda eşleştirme paketi henüz yok.",
    "The server has no matching package installed (pip install 'jobradar[match]').":
        "Sunucuda eşleştirme paketi kurulu değil (pip install 'jobradar[match]').",
    "This engine is older than the app and has no smart matching yet.":
        "Bu motor uygulamadan eski; akıllı eşleştirme henüz yok.",
    "Loading the model. The first time it is downloaded, which can take a few minutes.":
        "Model yükleniyor. İlk seferde indirilir; bu birkaç dakika sürebilir.",
    "Asking the model…": "Modele soruluyor…",
    "The model works: %@ answered in %@ seconds.": "Model çalışıyor: %@ %@ saniyede yanıt verdi.",
    "Comparing your jobs. With many jobs this takes a few minutes.":
        "İlanların karşılaştırılıyor. İlan çoksa birkaç dakika sürer.",
    "%@ jobs compared, %@ let through.": "%@ ilan karşılaştırıldı, %@ ilan öne çıkarıldı.",
    "How well JobRadar finds your jobs": "JobRadar senin ilanlarını ne kadar iyi buluyor",
    "Measured on your own verdicts: the jobs you shortlisted, applied to or skipped, and the ones you judged here. The more verdicts, the steadier the numbers.":
        "Kendi kararlarınla ölçülür: kısa listeye aldığın, başvurduğun ya da geçtiğin ilanlar ve burada karar verdiklerin. Karar sayısı arttıkça sayılar oturur.",
    "%@ verdicts: %@ fit, %@ maybe, %@ do not fit": "%@ karar: %@ uygun, %@ belki, %@ uygun değil",
    "Judge jobs…": "İlanlara karar ver…",
    "Keys 1, 2 and 3 choose Fits, Maybe and Does not fit.": "1, 2 ve 3 tuşları Uygun, Belki ve Uygun değil kararını verir.",
    "With fewer than %@ verdicts, or only a few of one kind, the numbers below still move a lot.":
        "%@ karardan azsa ya da bir türden çok az karar varsa aşağıdaki sayılar hâlâ çok oynar.",
    "Which order puts the jobs you want first?": "Hangi sıralama istediğin ilanları öne alıyor?",
    "First 10": "İlk 10",
    "First %@": "İlk %@",
    "Measured on the %@ jobs that have a verdict of yours. First 10 and first %@: the share of the jobs at the top of an order that you want. NDCG@10 and AUC: how well the whole order follows your verdicts; 1.0 is perfect, and an AUC of 0.5 is chance.":
        "Karar verdiğin %@ ilan üzerinde ölçülür. İlk 10 ve ilk %@: bir sıralamanın en üstündeki ilanların ne kadarını istediğin. NDCG@10 ve AUC: sıralamanın tamamı kararlarına ne kadar uyuyor; 1.0 kusursuz, AUC için 0.5 rastgele demektir.",
    "The first rows are measured on the same jobs, so they can be compared.":
        "İlk satırlar aynı ilanlar üzerinde ölçülür, bu yüzden birbirleriyle karşılaştırılabilir.",
    "Turn on smart matching in Settings to compare it with the keyword order here.":
        "Akıllı eşleştirmeyi Ayarlar'dan açarsan burada anahtar kelime sıralamasıyla karşılaştırılır.",
    "What reaches the AI model, and what never does": "Yapay zeka modeline neler ulaşıyor, neler hiç ulaşmıyor",
    "Judged": "Karar verilen",
    "You want": "İstediğin",
    "Estimate": "Tahmin",
    "About %@ jobs you would want never reach the AI model.":
        "İsteyeceğin yaklaşık %@ ilan yapay zeka modeline hiç ulaşmıyor.",
    "Estimate: the share you wanted among the jobs you judged, applied to the whole group. It appears once you judged at least 5 jobs of a group.":
        "Tahmin: karar verdiğin ilanlar içinde istediklerinin payı, grubun tamamına uygulanır. Bir gruptan en az 5 ilana karar verince görünür.",
    "Does the AI model judge like you?": "Yapay zeka modeli senin gibi mi karar veriyor?",
    "On the %@ jobs that both of you judged: the same verdict on %@. Only the AI model said yes: %@. Only you said yes: %@.":
        "İkinizin de karar verdiği %@ ilanda: %@ oranında aynı karar. Sadece yapay zeka modeli evet dedi: %@. Sadece sen evet dedin: %@.",
    "Agreement beyond chance (kappa): %@. From 0.6 on it is good.":
        "Şansın ötesinde uyum (kappa): %@. 0.6 ve üstü iyidir.",
    "%@ of the evaluated jobs were jobs you want.": "Değerlendirilen ilanların %@ kadarı istediğin ilanlardı.",
    "Use of the AI model in the last %@ days": "Son %@ günde yapay zeka modeli kullanımı",
    "Evaluated by the AI model": "Yapay zeka modeli değerlendirdi",
    "Waiting for the AI model": "Yapay zeka modelini bekliyor",
    "Quick score too low": "Ön puanı düşük",
    "Matches none of your tracks": "Hiçbir arama alanına uymuyor",
    "Evaluating jobs": "İlan değerlendirme",
    "Writing CV and letter": "CV ve ön yazı yazma",
    "Second reading of the documents": "Belgelerin ikinci okuması",
    "Reading a CV": "CV okuma",
    "Setting up the search": "Aramayı kurma",
    "Connection tests": "Bağlantı denemeleri",
    "%@ calls, %@ tokens in, %@ tokens out": "%@ çağrı, %@ giriş token'ı, %@ çıkış token'ı",
    "%@ failed": "%@ başarısız",
    "%@ USD at API prices (a subscription is not charged this)": "API fiyatlarıyla %@ USD (abonelikte bu ücret alınmaz)",
    "%@ calls": "%@ çağrı",
    "on average %@ tokens in and %@ out": "ortalama %@ giriş ve %@ çıkış token'ı",
    "%@ seconds each": "çağrı başına %@ saniye",
    "Does this job fit you?": "Bu ilan sana uygun mu?",
    "%@ judged · %@ to go": "%@ ilana karar verildi · %@ kaldı",
    "Judge the posting as if you had just found it yourself. Scores are hidden on purpose. The jobs are drawn from everything JobRadar collected, including what its rules filtered out, so the numbers show what the rules miss.":
        "İlana, onu az önce kendin bulmuşsun gibi karar ver. Puanlar bilerek gizlendi. İlanlar JobRadar'ın topladığı her şeyden seçilir, kuralların elediği ilanlar da dahil; böylece sayılar kuralların neyi kaçırdığını gösterir.",
    "Nothing left to judge": "Karar verilecek ilan kalmadı",
    "More jobs appear here after the next scan.": "Bir sonraki taramadan sonra burada yeni ilanlar görünür.",
    "This posting came without a description. Judge it by its title, or open it.":
        "Bu ilan açıklamasız geldi. Başlığına göre karar ver ya da ilanı aç.",
    "Key %@": "%@ tuşu",
})
