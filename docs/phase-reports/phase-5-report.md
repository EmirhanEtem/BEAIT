# Phase 5 — GUI Otomasyonu ve Görünür Operasyon Deneyimi Raporu

**Tarih:** 2026-11-12  
**Durum:** ✅ Tamamlandı  
**Hedef:** Yalnızca GUI ile yapılabilen işlemleri güvenilir, gözlemlenebilir, kullanıcı müdahalesine duyarlı ve güvenli hale getirmek.

---

## 1. Uygulanan Bileşenler

### 1.1 Aktif Pencere, DPI Ölçekleme ve Bayat Hedef (Stale Target) Tespiti (`app/integrations/computer_use/window_detector.py`)

- `WindowDetector`: Windows `user32` / `shcore` API'leri üzerinden dış bağımlılık gerektirmeden pencere durumunu denetler:
  - `get_foreground_window()` & `get_window_info(hwnd)`: Pencere başlığı, `PID`, sınır koordinatları (`left`, `top`, `right`, `bottom`, `width`, `height`), odak durumu (`is_foreground`), simge durumu (`is_minimized`) ve ekran DPI ölçeğini (`dpi_scale`) okur.
  - `is_target_stale(...)`: Hedef pencerenin kapanması, gizlenmesi, başlığının değişmesi veya başlangıç referansından `> 50 piksel` kayması durumunda hedefi **bayat (stale)** olarak işaretler ve kör tıklamayı engeller.
  - `bring_to_foreground(hwnd)`: Pencere simge durumundaysa geri yükler ve ön plana taşır.

### 1.2 Manuel Kullanıcı Müdahalesi ve Durdurma Algılayıcısı (`app/integrations/computer_use/user_intervention.py`)

- `InterventionDetector`:
  - Fiziksel fare imleci konumunu (`GetCursorPos`) izler; otomasyon sırasında kullanıcı fareyi `> 20 piksel` hareket ettirirse anında `UserInterventionError` fırlatarak otomasyonu güvenli şekilde durdurur.
  - Hedef pencere odağını kaybederse (kullanıcı `Alt+Tab` yaparsa veya başka pencereye tıklarsa) işlemi keser.
  - Yardımcı masaüstü uygulamasındaki global **STOP** butonunu (`cancel_event`) her adımdan önce ve sonra kontrol eder.

### 1.3 Güvenli GUI Yürütücüsü (`app/integrations/computer_use/safe_gui.py`)

- `SafeGUIExecutor`: Tüm tıklama (`safe_click`), metin yazma (`safe_type`), kısayol (`safe_hotkey`), kaydırma (`safe_scroll`) ve sürükleme (`safe_drag`) işlemlerini 7 adımlı güvenlik protokolünden geçirir:
  1. **Semantik UIA Önceliği:** Önce HCU `AX.find` ve `AX.act` ile semantik kontrol aranır.
  2. **Doğrulanmış Koordinat Yedeği:** Yalnızca semantik hedef bulunamazsa, eylem öncesi ekran görüntüsü (`capture_screenshot`) başarılıysa ve koordinatlar hedef pencere sınırları (`contains_point`) içindeyse koordinat tıklamasına izin verilir.
  3. **Riskli İşlem Onayı:** `requires_confirmation=True` olan işlemler kullanıcı onayı (`user_confirmed=True`) olmadan yürütülemez.
  4. **Canlı İşaretçi Yayını (`GUIActionMarker`):** Her işlem öncesi ve sonrasında masaüstü uygulamasına koordinat, hedef açıklaması ve yöntem bilgisi yayınlanır.

### 1.4 Masaüstü Uygulaması Görselleştirmesi (`apps/desktop/src/components/CursorMarker.tsx`)

- İmleç katmanında işlemin **CANLI MASAÜSTÜ (HCU)** mu yoksa **UI Simülasyonu** mu olduğu rozetle açıkça gösterilir.

---

## 2. Test Sonuçları

`backend/tests/test_gui_phase5.py` altındaki 9 yeni güvenlik ve otomasyon testi dahil tüm test paketi %100 başarıyla geçti:

```text
backend\tests\test_gui_phase5.py::test_window_info_contains_point PASSED
backend\tests\test_gui_phase5.py::test_stale_target_detection_title_and_drift PASSED
backend\tests\test_gui_phase5.py::test_safe_click_blocks_stale_or_unfocused_window PASSED
backend\tests\test_gui_phase5.py::test_semantic_uia_click_preferred_and_emits_markers PASSED
backend\tests\test_gui_phase5.py::test_coordinate_fallback_requires_valid_screenshot_and_bounds PASSED
backend\tests\test_gui_phase5.py::test_manual_user_mouse_intervention_aborts_sequence PASSED
backend\tests\test_gui_phase5.py::test_global_stop_button_cancels_gui_action PASSED
backend\tests\test_gui_phase5.py::test_explicit_user_confirmation_for_risky_ui_ops PASSED
backend\tests\test_gui_phase5.py::test_safe_type_hotkey_and_drag PASSED

Toplam Phase 5 GUI Testleri: 9 passed in 0.12s
Tüm Depo Testleri (Phase 1..5): 73 passed, 9 deselected in 3.60s (%100 Başarı)
```

---

## 3. Kabul Kriterleri Doğrulama Matrisi

| Kabul Kriteri | Durum | Doğrulama Detayı |
|---|---|---|
| Hedefi tespit eder veya güvenli şekilde başarısız olur | ✅ | Semantik UIA veya doğrulanmış pencere içi koordinat bulunamazsa tıklama yapmadan güvenli hata döner |
| Bayat (stale) koordinatlara körlemesine tıklamaz | ✅ | Pencere kapanmışsa, başlığı değişmişse, kaymışsa veya ekran görüntüsü alınamamışsa tıklama reddedilir |
| Kullanıcı otomasyon dizisini durdurabilir | ✅ | Global STOP (`cancel_event`) ile çalışan işlem anında `aborted` durumuna geçer |
| Yardımcı arayüz ne yapıldığını doğru gösterir | ✅ | `GUIActionMarker` ve `CursorMarkerOverlay` ile hedef adı ve CANLI/Simülasyon durumu gösterilir |
| Manuel kullanıcı müdahalesi yanlış yönlendirilmiş tıklamalara yol açmaz | ✅ | Kullanıcı fareyi hareket ettirdiğinde veya pencere odağını değiştirdiğinde dizi anında kesilir |
