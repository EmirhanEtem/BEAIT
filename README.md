# FL Studio AI Assistant

Windows masaüstü yapay zeka asistanı — FL Studio'yu doğal dil ile kontrol edin.

## Proje Durumu

🔧 **Phase 0** — Ortam değerlendirmesi ve depo yapısı oluşturma (tamamlandı)

## Genel Bakış

FL Studio AI Assistant, kullanıcının mevcut FL Studio kurulumunu doğal dilde verilen talimatlarla kontrol eden bir Windows masaüstü yardımcısıdır. Bir DAW değildir — FL Studio ile entegre çalışan bir asistan uygulamadır.

### Temel Özellikler (MVP Hedefi)

- 💬 Doğal dil ile müzik üretim talimatları
- 🎹 FL Studio MCP/API entegrasyonu ile proje kontrolü
- 🖱️ GUI otomasyonu ile API dışı işlemler
- 📊 Gerçek zamanlı eylem takibi ve doğrulama
- 🔒 Güvenli yürütme, onay mekanizmaları ve geri alma
- 🎵 MIDI pattern üretimi ve düzenleme
- 🔊 Audio analizi ve geri bildirim

## Teknik Yığın

| Katman | Teknoloji |
|--------|-----------|
| Masaüstü | Tauri 2 + React + TypeScript + Tailwind CSS |
| Backend | Python 3.14 + FastAPI + WebSocket |
| FL Studio Entegrasyonu | flstudio-mcp (MCP protokolü) |
| GUI Otomasyonu | Microsoft Hybrid Computer Use (HCU) |
| Müzik Motoru | pretty_midi, mido, music21 |
| Audio Analizi | librosa, soundfile, numpy |
| Veritabanı | SQLite |

## Kurulum

Detaylı kurulum talimatları için: [docs/setup-windows.md](docs/setup-windows.md)

## Geliştirme Fazları

| Faz | Açıklama | Durum |
|-----|----------|-------|
| 0 | Ortam değerlendirmesi ve depo yapısı | ✅ Tamamlandı |
| 1 | Entegrasyon kanıtı (PoC) | ⏳ Bekliyor |
| 2 | Masaüstü yardımcı temeli | ⏳ Bekliyor |
| 3 | Eylem sistemi, izinler ve doğrulama | ⏳ Bekliyor |
| 4 | Gerçek FL Studio kontrol MVP'si | ⏳ Bekliyor |
| 5 | GUI otomasyonu ve görsel deneyim | ⏳ Bekliyor |
| 6 | Müzik üretim motoru | ⏳ Bekliyor |
| 7 | Audio render ve analiz | ⏳ Bekliyor |
| 8 | Prodüktör orkestratör ve uçtan uca iş akışı | ⏳ Bekliyor |
| 9 | Sağlamlaştırma, paketleme ve sürüm adayı | ⏳ Bekliyor |

## Lisans

Bu proje özel kullanım içindir. Harici bağımlılıkların lisansları `docs/` altında belgelenecektir.

