# FL Studio AI Assistant

Windows masaüstü yapay zeka asistanı — FL Studio'yu doğal dil ile kontrol edin.

## Proje Durumu

🚀 **Release Candidate (Phase 0 – Phase 9 Tamamlandı)** — Tüm 108 birim, entegrasyon ve uçtan uca test %100 başarıyla geçti.

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
| 1 | Entegrasyon kanıtı (PoC) | ✅ Tamamlandı |
| 2 | Masaüstü yardımcı temeli | ✅ Tamamlandı |
| 3 | Eylem sistemi, izinler ve doğrulama | ✅ Tamamlandı |
| 4 | Gerçek FL Studio kontrol MVP'si | ✅ Tamamlandı |
| 5 | GUI otomasyonu ve görsel deneyim | ✅ Tamamlandı |
| 6 | Müzik üretim motoru | ✅ Tamamlandı |
| 7 | Audio render ve analiz | ✅ Tamamlandı |
| 8 | Prodüktör orkestratör ve uçtan uca iş akışı | ✅ Tamamlandı |
| 9 | Sağlamlaştırma, paketleme ve sürüm adayı | ✅ Tamamlandı |

## Lisans

Bu proje özel kullanım içindir. Harici bağımlılıkların lisansları `docs/` altında belgelenecektir.

