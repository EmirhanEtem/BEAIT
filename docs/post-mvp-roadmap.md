# FL Studio AI Assistant — MVP Sonrası Yol Haritası (Post-MVP Roadmap)

**Mevcut Durum:** MVP Release Candidate (Phase 0 – Phase 9) **%100 tamamlandı** (`109 passed, 0 failed`).  
Bu belge, kararlı Windows MVP temelinin üzerine inşa edilecek **v1.1 – v2.0** geliştirmelerini tanımlar.

---

## 1. Doğrudan Çok Kanallı Piano Roll MIDI Enjeksiyonu (v1.1)

- **Mevcut MVP Durumu:** Çok kanallı polifonik akor, bas ve melodi kalıpları deterministik olarak doğrulanmakta ve `.mid` dosyaları olarak dışa aktarılmaktadır.
- **v1.1 Hedefi:** `device_FLStudioMCP.py` içerisine kanal indeksli Piano Roll nota yazma ve geri okuma (`CMD_PIANO_ROLL_SET_NOTES_VERIFIED`) komutu eklenerek harici `.mid` sürükle-bırak adımına gerek kalmadan seçili enstrüman kanalına doğrudan polifonik nota yazılması.

---

## 2. VST / Üçüncü Parti Eklenti Parametre Haritalaması (v1.2)

- **Mevcut MVP Durumu:** Eklenti pencereleri `SafeGUIExecutor` ile güvenli şekilde açılabilmekte ve mikser ses/pan/mute parametreleri MCP üzerinden doğrulanarak ayarlanabilmektedir.
- **v1.2 Hedefi:** FL Studio'nun `plugins.getParamCount` / `plugins.getParamName` / `plugins.setParamValue` API'lerini `FLStudioAdapter` içine bağlayarak Serum, Vital, Harmor ve Flex gibi yaygın synthesizer'ların filtre kesim frekansı (`Cutoff`), rezonans (`Resonance`) ve zarf (`ADSR`) parametrelerinin semantik isimlerle kontrol edilmesi ve geri okunarak doğrulanması.

---

## 3. Masaüstü Arayüzünde Etkileşimli Piano Roll & Spektrum Önizleyicisi (v1.3)

- **Mevcut MVP Durumu:** Masaüstü uygulaması canlı eylem akışını, ekran önizlemesini, imleç doğrulamasını ve proje bağlamını göstermektedir (`GET /api/presets`, `POST /api/production/plan`, `POST /api/audio/analyze`, `POST /api/samples/scan`).
- **v1.3 Hedefi:**
  - `Dry-Run` (Plan Önizleme) aşamasında üretilen akor, bas ve melodi notalarını uygulama içinde mini bir Piano Roll tuvalinde (canvas) görselleştirme.
  - `AudioAnalyzer` ve `CriticAgent` tarafından üretilen 3-bant spektral enerji ve RMS/Peak ölçümlerini grafiksel miksaj kartları olarak gösterme.

---

## 4. Çoklu Model / Yerel Ollama Canlı Akış Entegrasyonu (v1.4)

- **Mevcut MVP Durumu:** `ModelProviderAdapter` gizlilik kontrollerini (`redact_secrets`, `PromptDisclosureEnvelope`, `allow_audio_upload=False`) ve deterministik kural tabanlı planlamayı desteklemektedir.
- **v1.4 Hedefi:** Yerel **Ollama** (`llama3.3`, `qwen2.5-coder`) ve bulut sağlayıcıları için JSON-Schema zorlamalı (`structured outputs`) canlı akış bağdaştırıcılarının eklenmesi; tüm LLM çıktılarının yine mevcut `ActionType` izin listesinden ve `VerificationEngine` doğrulamasından geçirilmesi.

