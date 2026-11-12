# Bağımlılık ve Lisans Envanteri (License Inventory)

Bu belge, **FL Studio AI Assistant** monoreposunda kullanılan tüm dış bileşenlerin, Python paketlerinin, masaüstü arayüz kütüphanelerinin ve otomasyon araçlarının lisans durumunu listeler.

---

## 1. Dış Entegrasyon Depoları (`external/`)

| Bileşen | Sabitlenen Commit | Lisans | Kullanım Amacı |
|---|---|---|---|
| `external/flstudio-mcp` | `30ad112a98ca51c820df93cf7a75b8871c5cfdf7` | MIT | FL Studio MIDI Controller Script (`device_FLStudioMCP.py`) ve SysEx/TCP köprüsü |
| `external/Hybrid-Computer-Use` | `697d3fbad3fd24a4f9d9e0f057dc9277f9897be4` | MIT (Microsoft) | Windows UI Automation (AX) ve ekran görüntüsü/fare/klavye (GUI) MCP sağlayıcısı |

---

## 2. Python Backend Bağımlılıkları (`backend/requirements.txt`)

| Paket | Sürüm | Lisans | Kullanım Amacı |
|---|---|---|---|
| `fastapi` | `0.162.5` | MIT | REST API ve WebSocket sunucusu |
| `uvicorn` | `0.54.0` | BSD-3-Clause | ASGI uygulama sunucusu |
| `websockets` | `17.4` | BSD-3-Clause | Canlı olay akışı (WebSocket) |
| `pydantic` | `2.14.3` | MIT | Tip korumalı eylem ve API şema doğrulaması |
| `structlog` | `26.1.0` | MIT / Apache-2.0 | Yapılandırılmış günlükleme |
| `mido` | `1.3.3` | MIT | Standart MIDI (`.mid`) dosya okuma/yazma ve mesaj işleme |
| `python-rtmidi` | `1.5.8` | MIT | Sanal MIDI port iletişimi (loopMIDI bağlantısı) |
| `pytest` / `pytest-asyncio` | `9.2.0` / `1.4.1` | MIT / Apache-2.0 | Birim, entegrasyon ve uçtan uca test çatısı |
| `httpx` | `0.28+` | BSD-3-Clause | Test istemcisi ve HTTP çağrıları |

---

## 3. Masaüstü Uygulaması Bağımlılıkları (`apps/desktop/`)

| Paket / Çatı | Sürüm | Lisans | Kullanım Amacı |
|---|---|---|---|
| `Tauri` (`tauri`, `tauri-build`) | `2.x` | MIT / Apache-2.0 | Yerel Windows masaüstü kabuğu (`fl-studio-ai-assistant.exe`) |
| `React` / `React DOM` | `19.x` | MIT | Masaüstü kullanıcı arayüzü bileşenleri |
| `Tailwind CSS` | `3.4.x` | MIT | Masaüstü arayüz stil sistemi |
| `Lucide React` | `0.468+` | ISC | Kullanıcı arayüzü ikonları |
| `Vite` / `TypeScript` | `6.x` / `5.x` | MIT / Apache-2.0 | Ön yüz derleme ve tip kontrol sistemi |

---

## 4. Uyumluluk Özeti

- Tüm çalışma zamanı ve derleme bağımlılıkları izinlayıcı açık kaynak lisanslarına (**MIT**, **BSD-3-Clause**, **Apache-2.0**, **ISC**) sahiptir.
- Depoda veya derlenen `fl-studio-ai-assistant.exe` ikili dosyasında hiçbir özel mülkiyetli DAW ses motoru kodu, kırılmış eklenti veya API anahtarı yer almamaktadır.

