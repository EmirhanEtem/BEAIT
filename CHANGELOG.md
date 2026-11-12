# Changelog

## Phase 8 — Producer Orchestrator ve Uçtan Uca İş Akışı (End-to-End Workflow) (2026-11-12)

### Oluşturulan
- `backend/app/orchestration/producer.py`: Gelişmiş `ProducerOrchestrator` ve `UserMusicalIntent` — Türkçe ve İngilizce doğal dil niyet ayrıştırıcı (`parse_musical_intent`), uzman ajan koordinasyonu (`ComposerAgent`, `RhythmAgent`, `SoundDesignerAgent`, `ArrangerAgent`, `CriticAgent`), sınırlı yürütme döngüsü (`max_actions_per_plan = 32`) ve dürüst sınırlama raporlaması (`remaining_limitations`).
- `backend/app/model_providers/`: `ModelProviderAdapter`, `ProviderConfig` ve `PromptDisclosureEnvelope` — API anahtarı maskeleme (`redact_secrets`), şeffaf bağlam bildirimi (`disclosed_fields`) ve varsayılan ses/dosya yükleme engeli (`allow_audio_upload=False`).
- `backend/app/project_memory/`: `ProjectMemoryManager`, `UserMusicalPreferences` ve `TaskSummaryRecord` — kalıcı kullanıcı tercihleri ve denetlenebilir görev/oturum özetleri.
- `backend/scripts/demo_phase8_e2e.py`: Gerçek FL Studio 2025 üzerinde 128 BPM A minor Melodic Techno uçtan uca canlı demo scripti (11/11 eylem canlı doğrulandı ve başlangıç durumu %100 geri yüklendi).
- `docs/user-guide.md`: Kapsamlı kullanıcı kılavuzu.
- `backend/tests/test_phase8_e2e.py`: 5 yeni uçtan uca orkestrasyon, gizlilik ve proje belleği testi; toplam 102 test %100 başarıyla geçti.
- `docs/phase-reports/phase-8-report.md`: Phase 8 tamamlama raporu.

## Phase 7 — Ses Dışa Aktarımı ve Analizi (Audio Rendering and Analysis) (2026-11-12)

### Oluşturulan
- `backend/app/integrations/audio/render_workflow.py`: `FLRenderWorkflow`, `RenderSettings` ve `RenderResult` — mevcut dosyanın üzerine yazmadan önce açık onay kapısı (`AWAITING_OVERWRITE_APPROVAL`), dışa aktarım diyaloğu ve ayar doğrulaması (`DIALOG_NOT_FOUND`), WAV bütünlük kontrolü (`VERIFICATION_FAILED` / `SUCCEEDED`).
- `backend/app/integrations/audio/analyzer.py`: `AudioAnalyzer`, `MeasuredAudioFacts`, `HeuristicAudioObservations` ve `AudioAnalysisReport` — tekrarlanabilir deterministik sinyal analizi (`peak_dbfs`, `rms_dbfs`, `crest_factor_db`, dijital kırpılma tespiti, sessizlik oranı, Goertzel 3-bant spektral enerji analizi ve zarf otokorelasyonuyla tempo tahmini).
- `backend/app/agents/critic.py`: `CriticAgent` ve `CriticFeedbackReport` — nesnel ölçümleri (`MEASURED_FACT`) ile öznel miksaj önerilerini (`subjective_recommendations`) ayıran ve tüm önemli revizyonları `requires_approval=True` (`AWAITING_APPROVAL`) ile kapılayan Critic rolü.
- `backend/tests/fixtures/audio/`: Örnek render (`example_render.wav`) ve yapılandırılmış analiz raporu (`example_analysis_report.json`).
- `backend/tests/test_phase7_audio.py`: 11 yeni render, analiz ve Critic testi; toplam 97 test %100 başarıyla geçti.
- `docs/phase-reports/phase-7-report.md`: Phase 7 tamamlama raporu.

## Phase 6 — Müzik Prodüksiyon Motoru (Music Production Engine) (2026-11-12)

### Oluşturulan
- `configs/genre-presets.json` & `backend/app/music_engine/presets.py`: Düzenlenebilir tür ve mod ön ayarları (`melodic_techno`, `deep_house`, `trap_dark`, `boom_bap_chill`), bölüm şablonları ve açık stilistik sorumluluk reddi (`stylistic_disclaimer`).
- `backend/app/music_engine/generator.py`: Gam kısıtlamalı melodi üreticisi (`generate_melody`) ve ölçü sınırlarını koruyan tuşe/swing insansılaştırma (`apply_humanization`).
- `backend/app/agents/composer.py`: `ComposerAgent` ve `CompositionBundle` — akor yürüyüşü, bas hattı, melodi üretimi, deterministik MIDI doğrulaması ve `.mid` dışa aktarımı (`backend/tests/fixtures/midi/`).
- `backend/app/agents/rhythm.py`: `RhythmAgent` ve `RhythmBundle` — çok kanallı davul kalıpları, enerji varyantları (`full`, `intro`, `breakdown`) ve FL Studio `SET_STEP_GRID` eylem üretimi.
- `backend/app/agents/sound_designer.py`: `SoundDesignerAgent` ve `SoundDesignPlan` — enstrüman katmanlama önerileri ve başlangıç mikser seviye/pan eylemleri.
- `backend/app/agents/arranger.py`: `ArrangerAgent` ve `ArrangementPlan` — kesintisiz çok bölümlü şarkı yapısı (`Intro`, `Build`, `Drop`, `Breakdown`, `Outro`) ve FL Studio `CREATE_PATTERN` + `ADD_ARRANGEMENT_MARKER` eylemleri.
- `backend/app/integrations/filesystem/sample_scanner.py`: `SampleScanner` — yalnızca onaylı dizinleri (`approved_directories`) tarayan, WAV başlık meta verisi (`duration_seconds`, `sample_rate`, `channels`, `bit_depth`), BPM/ton etiketleri ve kategori çıkaran güvenli sample tarayıcısı ve ön dinleme (`prepare_audition`) iş akışı.
- `backend/tests/test_phase6_production.py`: 13 yeni prodüksiyon ve güvenlik testi; toplam 86 test %100 başarıyla geçti.
- `docs/phase-reports/phase-6-report.md`: Phase 6 tamamlama raporu.

## Phase 5 — GUI Otomasyonu ve Görünür Operasyon Deneyimi (2026-11-12)

### Oluşturulan
- `backend/app/integrations/computer_use/window_detector.py`: Windows `user32` / `shcore` tabanlı aktif pencere, DPI ölçeği, odak doğrulama ve bayat hedef (`is_target_stale`) algılayıcısı.
- `backend/app/integrations/computer_use/user_intervention.py`: Fiziksel fare hareketi (`> 20px`), pencere odak kaybı ve global STOP butonunu algılayıp otomasyonu anında kesen `InterventionDetector`.
- `backend/app/integrations/computer_use/safe_gui.py`: 7 adımlı güvenlik protokolü uygulayan `SafeGUIExecutor` (`safe_click`, `safe_type`, `safe_hotkey`, `safe_scroll`, `safe_drag`), semantik UIA önceliği, ekran görüntüsü + pencere sınırı doğrulamalı koordinat yedeği ve canlı `GUIActionMarker` yayını.
- `apps/desktop/src/components/CursorMarker.tsx`: Canlı HCU masaüstü eylemleri (`CANLI MASAÜSTÜ (HCU)`) ile UI simülasyonu ayrımı rozeti.
- `backend/tests/test_gui_phase5.py`: 9 yeni GUI güvenlik ve otomasyon testi; toplam 73 test başarıyla geçti.
- `docs/security.md`: 7 adımlı GUI güvenlik protokolü ve onay mekanizması belgesi.
- `docs/phase-reports/phase-5-report.md`: Phase 5 tamamlama raporu.

## Phase 4 — Gerçek FL Studio Kontrol MVP (Real FL Studio Control MVP) (2026-11-12)

### Oluşturulan
- `backend/app/music_engine/`: Müzik & MIDI üretim motoru (`models.py`, `scales.py`, `chords.py`, `generator.py`, `validator.py`, `midi_io.py`) — gamlar, akor dizileri, 4-on-the-floor/trap/boom bap ritim kalıpları, deterministik MIDI doğrulayıcı ve `.mid` dışa/içe aktarımı.
- `backend/app/integrations/fl_studio/adapter.py`: Gelişmiş FL Studio MCP bağdaştırıcısı — doğrulamalı adım sıralayıcı (step grid write with readback verification), mikser ses/pan/mute denetimi, pattern oluşturma (`create_pattern`), transport denetimi (`play`, `stop`, `toggle_play`).
- `backend/app/sessions/test_project.py`: `TestProjectSession` ile güvenli başlangıç anlık görüntüsü (`capture_baseline`) ve tam geri yükleme (`restore_baseline`).
- `backend/app/orchestration/producer.py`: `ProducerOrchestrator` — doğal dil niyet ayrıştırma, `ActionPlan` üretimi, dry-run (plan önizleme) modu ve onay kapılı sıralı yürütme.
- `backend/app/sessions/manager.py`: `TaskExecutionManager` ile orkestratör entegrasyonu, canlı eylem yürütme ve WebSocket durum yayını.
- `backend/scripts/poc_fl_phase4.py`: Gerçek FL Studio 2025 üzerinde canlı kontrol doğrulama scripti (%100 başarıyla tamamlandı).
- Testler: Toplam 64 birim & entegrasyon testi (%100 başarıyla geçti).
- `docs/phase-reports/phase-4-report.md`: Phase 4 yetenek matrisi ve doğrulama raporu.

## Phase 3 — Eylem Sistemi, İzinler, Doğrulama ve Kurtarma (2026-11-12)

### Oluşturulan
- `backend/app/schemas/actions.py`: Tip korumalı eylem veri modelleri (`ActionType`, `ActionLifecycleState`, risk seviyeleri, geçiş tablosu). Keyfi kabuk komutları şema seviyesinde engellendi.
- `backend/app/action_router/capabilities.py`: Yetenek kayıt defteri (`CapabilityRegistry`), FL Studio MCP, HCU ve Mock bağdaştırıcıları için eylem haritalaması.
- `backend/app/action_router/permissions.py`: Risk sınıflandırıcısı ve izin yöneticisi (`PermissionManager`), `DESTRUCTIVE` ve `HIGH` riskli eylemler için `AWAITING_APPROVAL` onay kapısı.
- `backend/app/action_router/router.py`: Tercihli, yedek ve mock rotalama motoru (`ActionRouter`).
- `backend/app/action_router/executor.py`: Eylem yürütücüsü (`ActionExecutor`) — zaman aşımı, sınırlı yeniden deneme (bounded retries), iptal (cancellation), doğrulama ve veritabanı kalıcılığı.
- `backend/app/database/persistence.py`: SQLite kalıcılık katmanı (`DatabaseManager`) — Windows dosya kilitlerini önleyen context manager (`_session()`).
- `backend/app/verification/engine.py`: Eylem doğrulama motoru (`VerificationEngine`) — BPM okuma, mikser doğrulaması, pattern kontrolü, dışa aktarım (export) dosya boyutu kontrolü.
- `backend/app/recovery/manager.py`: Kurtarma yöneticisi (`RecoveryManager`) — kontrol noktaları (checkpoint) oluşturma, başarısızlık planı (recovery plan) ve `NEEDS_RECOVERY` durum yönetimi.
- `backend/tests/test_action_system.py`: 15 adet kapsamlı birim testi; toplam 48 test başarıyla geçti.
- `docs/action-protocol.md`: Eylem modeli, izin modeli, rota seçimi, doğrulama ve kurtarma mimarisi belgesi.
- `docs/phase-reports/phase-3-report.md`: Phase 3 tamamlama raporu.

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

