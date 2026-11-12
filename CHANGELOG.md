# Changelog

## Phase 2 — Masaüstü Yardımcı Temeli (Desktop Companion Foundation) (2026-11-12)

### Oluşturulan
- Tauri 2 + React + TypeScript + Tailwind CSS masaüstü companion uygulaması (`apps/desktop`)
- Derlenmiş Windows çalıştırılabilir dosyası: `fl-studio-ai-assistant.exe` (12.2 MB)
- Uygulama simgeleri paketi (ICO + çoklu çözünürlük PNG)
- `StatusBar.tsx`: Bağlantı göstergeleri ve Global STOP butonu
- `ChatPanel.tsx`: Doğal dil istem paneli, mock/real seçim anahtarı, şablon komutlar
- `ActivityPanel.tsx`: Canlı eylem izleme ve doğrulama akışı (CANLI vs MOCK ayrımı)
- `ScreenView.tsx` & `CursorMarker.tsx`: Ekran ve imleç simülasyonu
- `ProjectContextPanel.tsx`: Proje durumu, BPM, mikser ve kanallar ("Bilinmiyor" etiketleri dahil)
- `SettingsPanel.tsx`: LLM sağlayıcı, MCP, HCU, güvenlik ve dil ayarları
- FastAPI Backend: `/api/health`, `/api/context`, `/api/tasks`, `/api/settings`, `/api/screen/capture`
- `WebSocket /ws`: Canlı olay yayını (`AppEvent`)
- Otomatik testler: 25/25 backend testleri geçti
- `docs/architecture.md`: Kapsamlı sistem mimarisi belgesi
- `docs/phase-reports/phase-2-report.md`: Phase 2 tamamlama raporu

## Phase 1 — Entegrasyon Kanıtı (PoC) (2026-11-12)

### Oluşturulan
- `flstudio-mcp` entegrasyonu ve commit sabitleme (`30ad112`)
- `FLStudioAdapter`: Canlı TCP SysEx köprüsü, doğrulamalı yazma (`set_tempo_verified`), sayfalı liste okuma
- Microsoft HCU entegrasyonu ve commit sabitleme (`697d3fb`)
- `computer-use.exe` ve `computer-use-windows-provider.exe` derlemesi
- `GUIAutomationAdapter`: JSON-RPC stdio MCP istemcisi (AX + GUI kanalları)
- Canlı FL Studio testi: 130 BPM okundu, 130 -> 133 değiştirildi ve doğrulandı, 130'a geri alındı
- HCU zararsız işlem testi: WinForms TextBox'a `set_value` yazıldı ve doğrulandı
- `docs/fl-studio-integration.md` & `docs/gui-automation.md`
- `docs/phase-reports/phase-1-report.md`

## Phase 0 — Ortam Değerlendirmesi ve Depo Yapısı (2026-11-12)

### Oluşturulan
- İlk depo yapısı (monorepo düzeni)
- `.gitignore` — Python, Node.js, Rust, IDE, güvenlik dosyaları için
- `.env.example` — çevresel değişkenler şablonu
- `README.md` — proje açıklaması ve faz durumları
- `docs/setup-windows.md` — Windows kurulum talimatları
- `docs/phase-reports/phase-0-report.md` — ortam raporu

### Tespit Edilen Ortam
- Windows 11 (10.0.26200) — 64-bit
- Python 3.14.0
- Node.js v24.11.1, npm 11.6.2
- Go 1.25.6
- Git 2.52.0
- FL Studio 2025 (v25.1.6.4997)
- Rust/Cargo: **kurulu değil** (Tauri 2 için gerekli)
- pnpm: **kurulu değil** (önerilir)
- loopMIDI: **kurulu değil** (MCP entegrasyonu için gerekebilir)

