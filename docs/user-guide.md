# FL Studio AI Assistant — Kullanıcı Kılavuzu (User Guide)

## 1. Genel Bakış

**FL Studio AI Assistant**, bilgisayarınızda çalışan mevcut **FL Studio 2025** oturumunuzu güvenli ve doğrulanabilir şekilde kontrol eden masaüstü yardımcı uygulamasıdır. Yeni bir DAW olmaya çalışmaz; müzikal isteklerinizi tiplendirilmiş, geri okunabilir (verified) eylemlere dönüştürür.

---

## 2. Doğal Dil Komut Örnekleri

Sohbet panelinden Türkçe veya İngilizce doğal dil komutları gönderebilirsiniz:

### 2.1 Tam Prodüksiyon Başlangıcı (Uçtan Uca İş Akışı)
> *"FL Studio'da 128 BPM, A minor tonunda melodic techno başlangıcı oluştur. Kick ve percussion düzenini kur, bassline ve ana melodiyi yaz, sonra kısa bir intro ve drop arrangement'ı hazırla."*

Bu komut çalıştırıldığında asistan:
1. Mevcut FL Studio proje durumunu ve Channel Rack kanallarını okur (`READ_PROJECT_STATE`, `READ_CHANNELS`).
2. Proje temposunu `128.0 BPM` olarak ayarlar ve geri okuyarak doğrular (`SET_TEMPO`).
3. `Intro` (8 bar) ve `Drop` (16 bar) bölümleri için yeni pattern'ler (`CREATE_PATTERN`) ve Playlist zaman işaretçileri (`ADD_ARRANGEMENT_MARKER`) oluşturur.
4. `808 Kick`, `808 Clap`, `808 HiHat` ve `808 Snare` kanallarına techno davul dizilimini yazar ve her kanalı geri okuyarak doğrular (`SET_STEP_GRID`).
5. `A natural_minor` tonunda akor yürüyüşü, bas hattı (`bassline`) ve ana melodi (`melody`) notalarını üretir, gam/ölçü doğrulamasından geçirir ve standart `.mid` dosyaları olarak dışa aktarır.
6. Kalan sınırlamaları (örneğin çok kanallı Piano Roll MIDI dosyalarının enstrüman kanallarına sürükle-bırak ile aktarılması gerektiğini) dürüstçe özetler.

### 2.2 Tekil Hızlı Komutlar
- **Tempo Değiştirme:** `"Change tempo to 126 BPM"`
- **Ritim Yazma:** `"Create a four-on-the-floor drum beat"` veya `"Create a trap beat"`
- **Mikser Ayarı:** `"Set track 2 volume to -3.5 dB"`
- **Proje İnceleme:** `"What is in my project right now?"`

---

## 3. Plan Önizleme (Dry-Run) ve Onay Kapıları

- **Plan Önizleme (`dry_run=True`):** FL Studio üzerinde hiçbir değişiklik yapmadan üretilen eylem planını, MIDI dosyalarını ve aranjman bölümlerini incelemenizi sağlar.
- **Onay Kapıları (`AWAITING_APPROVAL`):** Mevcut bir ses dosyasının üzerine yazma, dışa aktarma (`EXPORT_AUDIO`) veya Critic tarafından önerilen önemli mikser revizyonları kullanıcı onayı olmadan yürütülmez.
- **Acil Durdurma (Global STOP):** Üst çubuktaki **STOP** butonu çalışan tüm eylemleri ve GUI otomasyonunu anında güvenli biçimde durdurur.

---

## 4. Ses Dışa Aktarımı (Render) ve Critic Analizi

1. Bir render alındığında `AudioAnalyzer` dosyanın bütünlüğünü, tepe (`peak_dbfs`) ve `RMS` seviyelerini, dijital kırpılma (`clipped_samples`) durumunu ve sessizlik oranını deterministik olarak ölçer.
2. `CriticAgent`, **ölçülen nesnel gerçekler (`MEASURED_FACT`)** ile **öznel/sezgisel miksaj önerilerini (`HEURISTIC_OBSERVATION`)** ayrı başlıklar altında sunar.
3. Kırpılma veya aşırı düşük seviye tespit edilirse somut bir revizyon eylemi (`proposed_revisions`) önerir ve onayınıza sunar.

---

## 5. Gizlilik ve Güvenlik İlkeleri

- API anahtarları günlüklerde ve yapılandırma çıktılarında otomatik olarak maskelenir (`[REDACTED_SECRET]`).
- Model sağlayıcısına hangi proje bağlamı alanlarının gönderildiği (`PromptDisclosureEnvelope.disclosed_fields`) şeffaf biçimde kaydedilir.
- Yerel ses dosyaları, sample klasörleri ve proje dosyaları varsayılan olarak hiçbir bulut sağlayıcısına yüklenmez.
