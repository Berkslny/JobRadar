# JobRadar

JobRadar senin için iş ilanı arayan, her ilanı gerçek CV'nle karşılaştırıp değerlendiren ve seçtiğin ilanlar
için dürüst başvuru belgeleri yazan bir Mac uygulamasıdır. Kendi Mac'inde, senin bağladığın yapay zeka
modeliyle çalışır.

**İndir:** [JobRadar-1.0.dmg](https://github.com/Berkslny/JobRadar/raw/main/downloads/JobRadar-1.0.dmg) (macOS 26 ya da üstü)

English: [README.md](README.md)

## Ne yapar

- **İlanları bulur:** ilan siteleri (JobSpy üzerinden LinkedIn, Indeed, Google Jobs ve diğerleri), şirket
  kariyer sayfaları (Greenhouse, Lever, Ashby, Personio, Workday, SmartRecruiters, Recruitee, Softgarden),
  Almanya için Bundesagentur für Arbeit ve senin eklediğin linkler.
- **Her ilana 0 ile 5 arası puan verir.** İlandaki her şart profilindeki bir satırla eşleştirilir; ilanın neden
  uyduğunu ya da uymadığını görürsün.
- **İlana özel CV ve ön yazı yazar,** yalnızca profilindeki gerçekleri kullanarak. İkinci bir okuma ve PDF
  kontrolü hataları yakalar. Hiçbir yere bir şey gönderilmez; başvuruyu sen yaparsın.
- **Başvurularını takip eder,** takip zamanını hatırlatır ve posta kutundaki şirket yanıtlarını fark edebilir
  (salt okunur).
- **İstersen anlama göre eşleştirir.** *Akıllı eşleştirme* (Ayarlar > Eşleştirme) her ilanı arama alanların
  ve profilinle, Mac'inde çalışan küçük bir embedding modeliyle karşılaştırır. Yapay zeka modeli önce anahtar
  kelimelerin ve anlamın birlikte işaret ettiği ilanları görür; anahtar kelimelerinin kaçıracağı bir ilan da
  sana ulaşabilir. Kendi koyduğun kurallar her zaman geçerlidir.
- **Kendini senin kararlarınla ölçer.** Durum sayfası, öne sıralanan ilanların kaçının istediğin ilanlar
  olduğunu, istediğin kaç ilanın yapay zeka modeline hiç ulaşmadığını, modelin ne sıklıkla senin gibi karar
  verdiğini ve model çağrılarının toplamını gösterir. *İlanlara karar ver…* bu sayıların dürüst olması için
  sana rastgele bir örneklem sorar.
- **Türkçe ve İngilizce** çalışır, Mac'inin açık ya da koyu görünümüne uyar ve Liquid Glass kullanır.
- **Önce göz atabilirsin.** *Örnek verilerle göz at* uygulamayı uydurma ilanlar ve uydurma bir profille
  açar; yapay zeka modeli ya da tarama gerekmez.

## Gerekenler

- macOS 26 ya da üstü (Apple silicon ya da Intel)
- İnternet bağlantısı. İlk açılışta uygulama Python'u ve kütüphanelerini bir kez indirir (yaklaşık 150 MB):
  `~/Library/Application Support/JobRadar/runtime`
- Kendi yapay zeka modelin. Şunlardan biri yeter:
  - Mac'te kurulu ve giriş yapılmış **Claude Code** (Claude aboneliğini kullanır)
  - **Anthropic API anahtarı**
  - **OpenAI uyumlu** bir servis (OpenAI, OpenRouter, Groq, Mistral, Gemini, LM Studio…)
  - **Ollama** (ücretsiz, Mac'te çalışır)

  Model olmadan JobRadar ilanları yine toplar ve sıralar, ama değerlendiremez ve belge yazamaz.

## Kurulum

1. [JobRadar-1.0.dmg](https://github.com/Berkslny/JobRadar/raw/main/downloads/JobRadar-1.0.dmg) dosyasını indir, aç ve JobRadar'ı Uygulamalar klasörüne sürükle.
2. JobRadar'ı aç. İndirilen sürüm Apple onayından (notarization) geçmediği için macOS ilk seferde
   açmayı reddeder. O mesajı kapat, **Sistem Ayarları > Gizlilik ve Güvenlik** bölümünde aşağı inip
   JobRadar ile ilgili satırda **Yine de Aç**'ı seç ve onayla. Bu yalnızca bir kez gerekir.
3. Kurulum yardımcısı dört adımda ilerler: dil ve görünüm, yapay zeka modeli, profilin (CV'ni bırak,
   okunanları kontrol et) ve ne aranacağı. Sonra ilk taramayı başlat.

Uygulama açıkken menü çubuğunda durur ve 08:00, 13:00, 19:00'da tarama yapar.

## Verilerin nerede

Her şey Mac'indeki tek bir klasörde durur; varsayılan yer
`~/Library/Application Support/JobRadar/workspace`: profilin (`data/profile.yaml`), ayarların, ilan
veritabanın ve üretilen belgeler. **Ayarlar > Motor ve veriler** bölümünden başka bir klasör seçebilirsin.
API anahtarları ve e-posta uygulama şifresi macOS Anahtar Zinciri'nde tutulur, hiçbir dosyaya yazılmaz.
Mac'inden yalnızca ilan sitelerine, bağladığın yapay zeka modeline ve kendi posta kutuna istek gider.
Akıllı eşleştirmeyi açarsan modeli (yaklaşık 220 MB) bir kez Hugging Face'ten indirilir; karşılaştırmanın
kendisi Mac'inde yapılır.

Önceki bir JobRadar (komut satırı sürümü) verilerini `~/projects/jobradar` klasöründe bıraktıysa uygulama
bunları aktarmayı önerir: profil, ilanlar, belgeler ve ayarlar yukarıdaki klasöre kopyalanır, önceki klasör
olduğu gibi kalır.

## Yapay zeka modeli seçenekleri hakkında

- **Claude Code.** JobRadar, Mac'inde kurulu Claude Code programını olduğu gibi çalıştırır (`claude -p`);
  giriş işlemini Claude Code içinde kendin yaparsın. JobRadar Claude giriş bilgilerini hiçbir zaman istemez,
  okumaz ve saklamaz. Bu kullanımın planından nasıl düşeceğini Anthropic belirler:
  <https://code.claude.com/docs/en/legal-and-compliance> ve kendi planının koşulları.
- **API anahtarları** sağlayıcı tarafından kullandıkça ücretlendirilir.
- **Ollama ve LM Studio** Mac'inde çalışır ve ücretsizdir. Küçük yerel modeller ilanları daha zayıf değerlendirir.

Uygulamanın bir sürümünü yayınlayacaksan: Anthropic'in koşulları, üçüncü taraf uygulamaların Claude.ai girişi
sunmasına ya da istekleri kullanıcının Free, Pro veya Max hesabı üzerinden geçirmesine izin vermez. Bu uygulama
ikisini de yapmaz; herkes kendi Claude Code kurulumunu ya da kendi API anahtarını kullanır. Yayınlamadan önce
yukarıdaki sayfayı oku; burada yazanlar uygulamanın nasıl çalıştığının açıklamasıdır, hukuki tavsiye değildir.

## Kendin derlemek için

1. `JobRadar.xcodeproj` dosyasını Xcode 27 ya da üstünde aç.
2. ⌘R'ye bas.

Proje *Sign to Run Locally* olarak ayarlıdır; Apple geliştirici hesabı olmadan derlenir. Derlemelerin kendi
imzanı taşısın istersen hedefin **Signing & Capabilities** bölümünde ekibini seç.

Disk görüntüsü (.dmg) için ya `scripts/make-dmg.command` dosyasına çift tıkla ya da çalışan uygulamada
**Ayarlar > Gelişmiş > Disk görüntüsü oluştur…**'u seç. Uygulama Xcode'dan çalışıyorsa ikisi de yayın
(release) derlemesi yapar ve `JobRadar-<sürüm>.dmg` dosyasını `dist/` klasörüne koyar. Kurulu bir
kopyada menüdeki komut o kopyayı olduğu gibi paketler.

**İmzalama.** *Developer ID Application* sertifikası yoksa disk görüntüsündeki uygulama kimseyi
göstermeyen yerel (ad hoc) bir imza alır ve başka Mac'lerde Kurulum bölümünde anlatılan uyarı çıkar. Bir
Developer ID sertifikası (Apple Developer Program) kuruluysa `make-dmg.command` onunla imzalar. Uyarının
hiç çıkmaması için Apple onayı (notarization) da gerekir; bunun için bir anahtar zinciri profili ver:

```
xcrun notarytool store-credentials jobradar-notary --apple-id sen@example.com --team-id EKIPKODUN
JOBRADAR_NOTARY_PROFILE=jobradar-notary scripts/make-dmg.command
```

## Proje düzeni

| Yol | Ne |
|---|---|
| `JobRadar/` | Mac uygulaması (SwiftUI). `L10nTurkish.swift`, `tools/tr_table.py` dosyasından üretilir. |
| `JobRadar/jobradar-1.0.0-py3-none-any.whl` | Uygulamanın taşıdığı motor paketi. |
| `engine/` | Motorun kaynağı (Python): kaynaklar, puanlama, belge yazımı, yerel API. |
| `scripts/` | `make-dmg.command`, `build-engine.command`. |
| `downloads/` | Güncel sürümün disk görüntüsü. |
| `tools/` | Çeviri tablosu ve kontroller. |
| `.github/workflows/ci.yml` | Her gönderimde kontroller: motor testleri, uygulamanın derlenmesi, gerçek modelle akıllı eşleştirme. |

Motoru değiştirdikten sonra: `scripts/build-engine.command`, ardından uygulamayı yeniden derle
(unutulduğunda `python3 tools/check_wheel.py` söyler).
Motor testleri: `cd engine && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest`.
Arayüz metni değiştirdikten sonra: Türkçesini `tools/tr_table.py` dosyasına ekle ve
`python3 tools/l10n.py write` komutunu çalıştır.

Motor uygulama olmadan da çalışabilir (`jobradar serve`, `jobradar run`); komut satırı ve isteğe bağlı web
paneli şimdilik Türkçedir.

## İlan sitelerinin adil kullanımı

İlan siteleri kullanım koşullarında otomatik okumayı sınırlar. JobRadar onları yavaşça ve tek bir kişinin kendi
iş araması için okur. Bu şekilde kullan; bir sitenin işletmecisi isterse o kaynağı kapat.

## Lisans ve teşekkür

MIT, bkz. [LICENSE](LICENSE). Teşekkürler [NOTICE.md](NOTICE.md) dosyasında.
