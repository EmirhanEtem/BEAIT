# Güvenlik ve GUI Otomasyon Protokolü (Safety & GUI Automation Protocol)

Bu belge, FL Studio AI Assistant'ın masaüstü GUI otomasyonu (Microsoft Hybrid Computer Use — HCU) ve yerel sistem etkileşimlerinde uyguladığı katı güvenlik sınırlarını tanımlar.

---

## 1. Yedi Adımlı GUI Güvenlik Protokolü (`SafeGUIExecutor`)

Herhangi bir GUI eylemi (`safe_click`, `safe_type`, `safe_hotkey`, `safe_scroll`, `safe_drag`) masaüstüne gerçek girdi göndermeden önce aşağıdaki 7 adımı sırasıyla doğrular:

1. **Manuel Müdahale ve Global STOP Denetimi (`InterventionDetector`):**
   - Kullanıcının yardımcı uygulamadaki **STOP** butonuna basıp basmadığı (`cancel_event`) kontrol edilir.
   - Otomasyon sırasında kullanıcının fiziksel fareyi hareket ettirip ettirmediği (`> 20 piksel` sapma) `user32.GetCursorPos` üzerinden denetlenir. Sapma tespit edilirse `UserInterventionError` fırlatılarak dizi anında durdurulur.
2. **Aktif Pencere ve Odak Doğrulaması (`WindowDetector`):**
   - Hedef pencerenin (`HWND`) ön planda (`GetForegroundWindow`) olup olmadığı kontrol edilir.
   - Ön planda değilse `bring_to_foreground` denenir ve tekrar doğrulanır. Odak alınamazsa yanlış pencereye tıklamamak için işlem güvenli şekilde iptal edilir.
3. **Bayat Hedef (Stale Target) ve Pencere Kayması Tespiti:**
   - Pencerenin kapanıp kapanmadığı (`IsWindow`), görünürlüğü (`IsWindowVisible`), simge durumunda olup olmadığı (`IsIconic`) ve başlığının beklenen uygulama ile eşleşip eşleşmediği kontrol edilir.
   - Pencere koordinatları başlangıç referansından `> 50 piksel` kaymışsa hedef **bayat (stale)** kabul edilir ve tıklama engellenir.
4. **Önce Semantik UI Automation (`AX` Kanalı):**
   - Koordinat tıklaması yerine her zaman önce Windows UI Automation ağacında (`AX.find` ve `AX.act`) semantik kontrol aranır.
5. **Koordinat Yedeği Öncesi Zorunlu Ekran Görüntüsü ve Sınır Doğrulaması:**
   - Özel çizimli (custom-drawn) FL Studio/VST arayüzlerinde semantik hedef bulunamazsa, koordinat yedeğine (`coordinate_fallback`) **yalnızca**:
     - Eylem öncesi güncel ekran görüntüsü (`capture_screenshot`) başarıyla alındığında,
     - Hedef $(x, y)$ koordinatları ekran çözünürlüğü ve hedef pencerenin güncel sınırları (`contains_point`) içinde kaldığında izin verilir.
   - Körlemesine (blind) koordinat tıklaması kesinlikle yasaktır.
6. **Görsel Eylem İşaretçileri (`GUIActionMarker`):**
   - Her tıklama, yazma ve sürükleme öncesinde yardımcı masaüstü uygulamasına canlı imleç konumu, hedef açıklaması ve kullanılan yöntem (`semantic_uia` veya `coordinate_fallback`) WebSocket üzerinden yayınlanır.
7. **Eylem Sonrası Doğrulama:**
   - Girdi gönderildikten hemen sonra tekrar kullanıcı müdahalesi denetlenir ve eylem sonrası ekran görüntüsü alınarak görsel doğrulama kaydedilir.

---

## 2. Yüksek Riskli İşlemler İçin Kullanıcı Onayı

- Dosya üzerine yazma, proje sıfırlama, dışa aktarma veya yıkıcı kısayollar (`requires_confirmation=True`) kullanıcı açıkça onaylamadan (`user_confirmed=True`) çalıştırılamaz.
- Onaylanmamış yüksek riskli GUI eylemleri `method_used="aborted"` durumuyla reddedilir.

