# FL Studio AI Assistant — Windows Kurulum Rehberi

Bu belge, geliştirme ortamının nasıl kurulacağını adım adım açıklar.

## Gerekli Yazılımlar

### 1. Python 3.12+
- **Mevcut durum:** ✅ Python 3.14.0 kurulu
- İndirme: https://www.python.org/downloads/
- `pip` dahil olmalıdır

### 2. Node.js 20+
- **Mevcut durum:** ✅ Node.js v24.11.1, npm 11.6.2 kurulu
- İndirme: https://nodejs.org/
- pnpm önerilir: `npm install -g pnpm`

### 3. Rust & Cargo (Tauri 2 için)
- **Mevcut durum:** ❌ Kurulu değil
- İndirme: https://rustup.rs/
- Kurulum:
  ```powershell
  winget install Rustlang.Rustup
  ```
  veya https://rustup.rs/ adresinden `rustup-init.exe` indirip çalıştırın.
- Kurulumdan sonra yeni bir terminal açıp doğrulayın:
  ```powershell
  rustc --version
  cargo --version
  ```

### 4. Tauri 2 Gereksinimleri
- Rust/Cargo (yukarıda)
- Microsoft Visual Studio C++ Build Tools:
  - https://visualstudio.microsoft.com/visual-cpp-build-tools/
  - "Desktop development with C++" iş yükünü seçin
- WebView2 (Windows 11'de genellikle önceden yüklü):
  - https://developer.microsoft.com/en-us/microsoft-edge/webview2/

### 5. Go 1.22+ (HCU için)
- **Mevcut durum:** ✅ Go 1.25.6 kurulu
- İndirme: https://go.dev/dl/

### 6. Git
- **Mevcut durum:** ✅ Git 2.52.0 kurulu

### 7. FL Studio
- **Mevcut durum:** ✅ FL Studio 2025 (v25.1.6.4997)
- Konum: `C:\Program Files\Image-Line\FL Studio 2025\`

## İsteğe Bağlı Yazılımlar

### loopMIDI (Sanal MIDI Portu)
- **Mevcut durum:** ❌ Kurulu değil
- FL Studio MCP entegrasyonu sanal MIDI portu gerektirebilir
- İndirme: https://www.tobias-erichsen.de/software/loopmidi.html
- Kurulumdan sonra bir sanal MIDI portu oluşturun (örn. "FL Studio AI Bridge")

### pnpm (Node.js Paket Yöneticisi)
- **Mevcut durum:** ❌ Kurulu değil
- npm'ye göre daha hızlı ve disk-verimli
- Kurulum: `npm install -g pnpm`

## Depo Yapısı

```
fl-studio-ai-assistant/    (= c:\Users\emoca\Desktop\FlMcp)
├── apps/desktop/          — Tauri 2 + React masaüstü uygulaması
├── backend/               — Python FastAPI backend
├── external/              — Harici bağımlılıklar (flstudio-mcp vb.)
├── docs/                  — Belgeleme
├── scripts/               — Yardımcı betikler
├── configs/               — Yapılandırma dosyaları
├── .env.example           — Çevresel değişkenler şablonu
├── .gitignore             — Git hariç tutma kuralları
├── CHANGELOG.md           — Değişiklik günlüğü
└── README.md              — Proje açıklaması
```

## İlk Kurulum Adımları

### 1. Depoyu klonlayın/açın
```powershell
cd c:\Users\emoca\Desktop\FlMcp
```

### 2. Python sanal ortamını oluşturun
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
```

### 3. Ortam değişkenlerini yapılandırın
```powershell
cd c:\Users\emoca\Desktop\FlMcp
copy .env.example .env
# .env dosyasını düzenleyin, API anahtarlarınızı girin
```

### 4. Rust/Cargo kurun (henüz kurulu değilse)
```powershell
winget install Rustlang.Rustup
# Yeni terminal açın
rustc --version
```

### 5. pnpm kurun (isteğe bağlı ama önerilir)
```powershell
npm install -g pnpm
```

## Doğrulama Kontrolleri

Tüm gereksinimlerin karşılandığını doğrulamak için:

```powershell
python --version          # 3.12+
node --version            # 20+
npm --version             # 10+
rustc --version           # 1.70+
cargo --version           # 1.70+
go version                # 1.22+
git --version             # 2.40+
```

## Bilinen Kısıtlamalar

1. **Rust/Cargo kurulu değil** — Tauri 2 masaüstü uygulaması için Phase 2'de gerekecek.
2. **pnpm kurulu değil** — npm ile de çalışılabilir, ama pnpm önerilir.
3. **loopMIDI kurulu değil** — FL Studio MCP entegrasyonu için Phase 1'de test edilecek, gerekip gerekmediği belirlenecek.
4. **FL Studio kullanıcı verileri dizinine sandbox'tan erişilemiyor** — `Documents\Image-Line` dizini sandbox ortamından okunamadı; Phase 1'de doğrudan terminal ile kontrol edilecek.

## Güvenlik Notları

- `.env` dosyası **asla** git'e commit edilmemelidir
- API anahtarları mümkünse Windows Credential Manager'da saklanmalıdır
- Ekran görüntüleri ve loglar kişisel veri içerebilir, paylaşırken dikkatli olun
