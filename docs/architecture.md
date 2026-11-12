# FL Studio AI Assistant — Sistem Mimarisi (Architecture)

**Belge Sürümü:** 0.2.0 (Phase 2 MVP)  
**Hedef Platform:** Windows 10/11 (64-bit)  
**Birincil Uygulama:** FL Studio 2025+  

---

## 1. Genel Bakış ve Temel İlke

FL Studio AI Assistant, kullanıcının bilgisayarında zaten yüklü bulunan FL Studio oturumunu doğal dille kontrol eden bir **Windows Masaüstü Yardımcı Uygulamasıdır (Companion App)**.
- **Bir DAW değildir:** FL Studio'nun ses motoru, mikseri, piano roll'u veya eklenti barındırma yetenekleri yeniden kodlanmaz.
- **Hibrit Kontrol Mimarisi:**
  1. *FL Studio MCP/Scripting Köprüsü:* Mümkün olan tüm operasyonlar (BPM, transport, kanallar, mikser, patternler) yapılandırılmış API/SysEx mesajlarıyla doğrudan yürütülür.
  2. *GUI Otomasyonu (Microsoft HCU):* API'nin desteklemediği arayüz işlemleri (eklenti penceresi açma, render diyalogları vb.) görsel denetimle yapılır.
  3. *Yerel Python Servisleri:* Dosya inceleme, örnek (sample) analizi ve müzik teorisi hesaplamaları DAW'a yük bindirmeden yerel olarak yürütülür.

---

## 2. Mimari Katman Şeması

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   Windows Masaüstü Yardımcısı (Tauri 2)                 │
│                                                                        │
│   Sohbet Paneli  │  Canlı Eylem Akışı  │  Ekran & Eylem Önizleme       │
│   Proje Bağlamı  │  Genel STOP Butonu  │  Bağlantı Göstergeleri        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / WebSocket (ws://127.0.0.1:8765/ws)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Python FastAPI Backend                          │
│                                                                        │
│  API & Olay Katmanı                                                    │
│  ├── Session & Task Execution Manager (Asyncio)                        │
│  ├── WebSocket Event Broadcaster                                       │
│  └── REST Uç Noktaları (/health, /context, /tasks, /settings)          │
│                                                                        │
│  Entegrasyon Adaptörleri                                               │
│  ├── FL Studio Adapter (TCPBridge -> fl-studio-mcp daemon)             │
│  ├── GUI Automation Adapter (JSON-RPC stdio -> Microsoft HCU)          │
│  └── Filesystem / Audio Engine (pretty_midi, librosa, soundfile)       │
│                                                                        │
│  Doğrulama & Güvenlik                                                  │
│  ├── Strict Action Schemas (Pydantic)                                  │
│  ├── Write Verification (set_tempo_verified, read-back)                │
│  └── Safe Mode & Approval Manager                                      │
└───────────────────────┬─────────────────────────┬──────────────────────┘
                        │ TCP :9787               │ stdio MCP
                        ▼                         ▼
             ┌─────────────────────┐    ┌─────────────────────┐
             │ fl-studio-mcp       │    │ Microsoft HCU       │
             │ Background Daemon   │    │ (AX + GUI Kanalları)│
             └──────────┬──────────┘    └─────────────────────┘
                        │ SysEx (loopMIDI)
                        ▼
             ┌─────────────────────┐
             │ FL Studio 2025      │
             │ MIDI Controller     │
             └─────────────────────┘
```

---

## 3. Katman Detayları

### 3.1 Masaüstü Kullanıcı Arayüzü (Desktop Companion)

- **Kabuk:** Tauri 2 (Rust tabanlı, hafif, yerel Windows WebView2 kullanarak minimum RAM harcar).
- **Arayüz Kütüphanesi:** React 18, TypeScript, Tailwind CSS.
- **Durum Yönetimi:** Zustand (`useStore.ts`) — WebSocket üzerinden gelen yayınları anında bileşenlere dağıtır.
- **Bileşenler:**
  - *StatusBar:* Backend, FL Studio canlı bağlantısı ve GUI otomasyonunun durumunu anlık gösterir. Acil durum için global STOP butonu barındırır.
  - *ChatPanel:* Kullanıcıdan doğal dille komut alır; test modunu ve eylem aşamalarını gösterir.
  - *ActivityPanel:* Yürütülen eylemlerin adını, rotasını (CANLI FL MCP, GUI OTOMASYON, MOCK), hedefini, doğrulama sonucunu ve hata ayrıntılarını listeler.
  - *ScreenView & CursorMarker:* Otomasyon hedeflerini görselleştirir; arka plan girişlerinin sahte imleç olarak gösterilmesini engeller.
  - *ProjectContextPanel:* FL Studio'dan canlı okunan tempo, çalma/kayıt durumu, kanal listesi ve mikser kanallarını gösterir; API'nin sağlamadığı alanları açıkça "Bilinmiyor" olarak işaretler.
  - *SettingsPanel:* Model sağlayıcısı (OpenAI, Anthropic, Yerel), portlar, dil ve güvenlik seçeneklerini yönetir.

### 3.2 Python Backend (FastAPI)

- **Sunucu:** Python 3.14 + Uvicorn + FastAPI + WebSockets.
- **Port:** `127.0.0.1:8765`.
- **Eşzamanlılık:** Asyncio tabanlı görev kuyruğu ve `asyncio.Event` ile donatılmış anında iptal mekanizması.
- **WebSocket Protokolü:** `AppEvent` zarfı içerisinde tip güvenli olaylar:
  - `connection_status`: Sistem bağlantı sağlığı güncellemeleri
  - `project_context`: Proje meta verileri
  - `task_update`: Görev durumu (QUEUED, RUNNING, COMPLETED, CANCELLED, FAILED)
  - `action_update`: Eylem yaşam döngüsü (PLANNED -> RUNNING -> VERIFYING -> SUCCEEDED)
  - `cursor_marker`: Eylem hedefi koordinat ve açıklama işareti

### 3.3 FL Studio Entegrasyonu

- **Köprü:** `external/flstudio-mcp` (Commit `30ad1121fb511c7524d3b38261506a2e72a96595`).
- **İletişim:** `TCPBridge` üzerinden yerel daemon'a (`127.0.0.1:9787`) bağlanır. Daemon, loopMIDI üzerinden FL Studio içerisindeki `device_FLStudioMCP.py` betiğine SysEx mesajları gönderir.
- **Karakteristik:** SysEx paketleri 1.5 KB ile sınırlı olduğundan, kanal ve mikser listeleri `fetch_all_pages` ile sayfalı olarak çekilir.
- **Doğrulama:** Yapılan değişiklikler (`set_tempo_verified`), komutun gönderilmesiyle başarılı sayılmaz; hemen ardından değer geri okunarak karşılaştırılır.

### 3.4 GUI Otomasyonu (Microsoft HCU)

- **Sunucu:** `external/Hybrid-Computer-Use/artifacts/windows/computer-use.exe` (Commit `697d3fbda04cb322915866bab1aad79c726a61e3`).
- **Kanallar:**
  1. *AX (Erişilebilirlik):* Windows UI Automation ağacı üzerinden pencere diyaloglarını ve butonları yönetir.
  2. *GUI (Görsel):* Masaüstü ekran görüntüsü alır ve koordinat bazlı girdi sağlar.
- **Güvenlik:** Eylemler yalnızca izin verilen pencerelerde çalıştırılır; sahte tıklamalardan kaçınmak için ekran tazeliği denetlenir.

---

## 4. Olay ve Eylem Yaşam Döngüsü

```text
[Kullanıcı İstemi]
       │
       ▼
[Task Submission] ────► Durum: QUEUED
       │
       ▼
[Planlama & Eylem Listesi] ────► Eylemler: PLANNED
       │
       ▼
[Yürütme Döngüsü] ◄───► [İptal Kontrolü (Global STOP)]
       │
       ├──► Durum: RUNNING ──► WebSocket Eylem Bildirimi
       │
       ├──► [Doğrulama (Verification)]
       │         │
       │         ├──► Başarılı ──► Durum: SUCCEEDED
       │         └──► Başarısız ──► Durum: FAILED / NEEDS_RECOVERY
       │
       ▼
[Görev Tamamlandı] ────► Durum: COMPLETED (veya CANCELLED)
```

