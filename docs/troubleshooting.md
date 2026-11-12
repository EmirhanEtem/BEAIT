# Sorun Giderme ve Kurtarma Kılavuzu (Troubleshooting Guide)

Bu belge, **FL Studio AI Assistant** kurulumu, bağlantısı, GUI otomasyonu ve proje kurtarma süreçlerinde karşılaşılabilecek yaygın sorunları ve çözümlerini açıklar.

---

## 1. FL Studio MCP Bağlantı Sorunları (`DISCONNECTED`)

### Belirti
Üst durum çubuğunda **FL Studio MCP: Bağlı Değil** görünüyor veya tanılamada (`GET /api/diagnostics`) `fl_studio_mcp` durumu `DISCONNECTED` olarak raporlanıyor.

### Çözüm Adımları
1. **loopMIDI Sanal Portlarını Kontrol Edin:**
   - **loopMIDI** uygulamasının açık olduğundan ve aşağıdaki iki portun tam olarak bu isimlerle oluşturulduğundan emin olun:
     - `FLStudioMCP RX`
     - `FLStudioMCP TX`
2. **FL Studio MIDI Ayarlarını (`F10`) Kontrol Edin:**
   - **Input** bölümünde `FLStudioMCP RX` portunu seçin, **Controller type** olarak `FLStudioMCP` (`device_FLStudioMCP.py`) atayın ve **Enable** seçeneğini işaretleyin (Port `10`).
   - **Output** bölümünde `FLStudioMCP TX` portuna da aynı Port numarasını (`10`) verin.
3. **TCP Köprü Daemon'unu Kontrol Edin:**
   - Köprü servisinin `127.0.0.1:9787` portunda dinlediğinden emin olun.
4. **Yeniden Bağlanma (Reconnect):**
   - FL Studio yeniden başlatıldığında yardımcı uygulamadaki **Durumu Yenile (`POST /api/health/refresh`)** butonuna tıklayarak bağlantıyı uygulama yeniden başlatmaya gerek kalmadan kurtarabilirsiniz.

---

## 2. GUI Otomasyonu (HCU) ve Pencere Odak Sorunları

### Belirti
GUI eylemi `Target window is stale, closed, or not focused` veya `UserInterventionError` hatasıyla durduruldu.

### Neden ve Çözüm
- **Güvenlik Tasarımı:** `SafeGUIExecutor`, FL Studio penceresi ön planda değilse, pencere taşınmışsa veya otomasyon sırasında fiziksel fareyi `> 20 piksel` hareket ettirdiyseniz kör tıklamayı önlemek için işlemi bilerek durdurur.
- **Çözüm:**
  1. FL Studio 2025 penceresini simge durumundan çıkarın ve ekranda görünür bırakın.
  2. Otomasyon dizisi çalışırken fareyi hareket ettirmeyin veya `Alt+Tab` yapmayın.
  3. İşlemi bilerek durdurmak istediğinizde üst çubuktaki kırmızı **STOP** butonunu kullanın.

---

## 3. Ses Dışa Aktarma (Render) ve Üzerine Yazma Engeli

### Belirti
Render işlemi `AWAITING_OVERWRITE_APPROVAL` veya `DIALOG_NOT_FOUND` durumuyla durdu.

### Çözüm
- **`AWAITING_OVERWRITE_APPROVAL`:** Hedef `.wav` dosyası diskte zaten mevcuttur. Mevcut çalışmanızın yanlışlıkla silinmemesi için üzerine yazma onayı (`overwrite_approved=True`) vermeniz veya yeni bir dosya adı seçmeniz gerekir.
- **`DIALOG_NOT_FOUND`:** FL Studio dışa aktarma penceresi (`Ctrl+R`) açık değildir. Asistan, diyalog penceresini doğrulamadan körlemesine `Enter` tuşuna basmaz.

---

## 4. Proje Yedekleme ve Kurtarma Rehberi

1. **Yeni Sürüm Kaydetme (`Ctrl+N`):** Önemli bir projede çok adımlı aranjman veya mikser değişiklikleri çalıştırmadan önce FL Studio'da `Ctrl+N` kısayoluyla numaralı yeni bir `.flp` yedeği oluşturun.
2. **Başlangıç Anlık Görüntüsü (`TestProjectSession`):** Asistan, canlı oturumlarda tempo, step-grid ve Master mikser seviyesini değiştirmeden önce anlık görüntü alır ve hata durumunda başlangıç değerlerini geri yükleyebilir.
3. **Gizlilik Korumalı Günlük Dışa Aktarımı (`POST /api/logs/export`):** Bir hata raporu paylaşmanız gerektiğinde `/api/logs/export` uç noktasını kullanın; bu çıktı tüm API anahtarlarını (`[REDACTED_SECRET]`) ve Windows kullanıcı adı yollarını (`C:\Users\[USER]`) otomatik olarak temizler.
