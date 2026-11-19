import React, { useEffect, useState } from "react";
import { useStore, AppSettings, BACKEND_URL } from "../store/useStore";
import { Settings, Shield, Cpu, Sliders, Save, Check, RefreshCw, Zap, AlertTriangle } from "lucide-react";

interface ProviderModelOption {
  id: string;
  label: string;
  tier?: string;
  recommended?: boolean;
}

interface ModelTestResult {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  error?: string | null;
  suggested_model?: string | null;
}

const FALLBACK_MODEL_OPTIONS: Record<string, ProviderModelOption[]> = {
  gemini: [
    { id: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite (Önerilen • ~1 sn & Ücretsiz Kota)", recommended: true },
    { id: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite (Ultra Hızlı ~0.8 sn)", recommended: true },
    { id: "gemini-flash-lite-latest", label: "Gemini Flash-Lite Latest (Otomatik En Güncel Lite)", recommended: true },
    { id: "gemini-3-flash-preview", label: "Gemini 3 Flash Preview (~1.6 sn)" },
    { id: "gemini-3.5-flash", label: "Gemini 3.5 Flash (Detaylı ~7 sn)" },
  ],
  openai: [
    { id: "gpt-4o-mini", label: "GPT-4o mini (Hızlı & Ekonomik)", recommended: true },
    { id: "gpt-4o", label: "GPT-4o (Yüksek Yaratıcılık)" },
    { id: "gpt-4.1-mini", label: "GPT-4.1 mini" },
    { id: "gpt-4.1", label: "GPT-4.1" },
  ],
  anthropic: [
    { id: "claude-sonnet-4-20250514", label: "Claude Sonnet 4", recommended: true },
    { id: "claude-3-5-haiku-latest", label: "Claude 3.5 Haiku (Hızlı)" },
  ],
  local: [
    { id: "llama3", label: "Llama 3 (Ollama)", recommended: true },
    { id: "qwen2.5:14b", label: "Qwen 2.5 14B (JSON Güçlü)" },
    { id: "mistral", label: "Mistral" },
  ],
};

function getActiveModel(data: AppSettings): string {
  if (data.llm_provider === "openai") return data.openai_model;
  if (data.llm_provider === "gemini") return data.gemini_model || "gemini-3.5-flash-lite";
  if (data.llm_provider === "anthropic") return data.anthropic_model;
  return data.local_model_name;
}

function withActiveModel(data: AppSettings, model: string): AppSettings {
  if (data.llm_provider === "openai") return { ...data, openai_model: model };
  if (data.llm_provider === "gemini") return { ...data, gemini_model: model };
  if (data.llm_provider === "anthropic") return { ...data, anthropic_model: model };
  return { ...data, local_model_name: model };
}

export const SettingsPanel: React.FC = () => {
  const { settings, fetchSettings, updateSettings } = useStore();
  const [formData, setFormData] = useState<AppSettings>(settings);
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [modelOptions, setModelOptions] = useState<ProviderModelOption[]>(
    FALLBACK_MODEL_OPTIONS[settings.llm_provider] || FALLBACK_MODEL_OPTIONS.gemini
  );
  const [customMode, setCustomMode] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchNote, setFetchNote] = useState<string | null>(null);
  const [testingModel, setTestingModel] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestResult | null>(null);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  useEffect(() => {
    setFormData(settings);
  }, [settings]);

  const loadModelsForProvider = async (provider: string, live: boolean) => {
    setFetchingModels(true);
    setFetchNote(null);
    const localDefaults = FALLBACK_MODEL_OPTIONS[provider] || [];
    if (localDefaults.length > 0 && !live) {
      setModelOptions(localDefaults);
    }
    try {
      const res = await fetch(`${BACKEND_URL}/api/providers/models?provider=${encodeURIComponent(provider)}&live=${live}`);
      if (res.ok) {
        const data = await res.json();
        const items: ProviderModelOption[] = Array.isArray(data.models) && data.models.length > 0 ? data.models : localDefaults;
        setModelOptions(items);
        if (live) {
          if (data.live_fetched) {
            setFetchNote(`API'den ${items.length} model listelendi.`);
          } else if (data.live_error) {
            setFetchNote(`Canlı liste alınamadı (${data.live_error}); önerilen modeller gösteriliyor.`);
          } else if (!data.api_key_configured) {
            setFetchNote(`.env dosyasında ${provider.toUpperCase()} API anahtarı tanımlı değil.`);
          }
        }
      }
    } catch {
      setModelOptions(localDefaults);
      if (live) setFetchNote("Backend'e bağlanılamadı; önerilen modeller gösteriliyor.");
    } finally {
      setFetchingModels(false);
    }
  };

  useEffect(() => {
    loadModelsForProvider(formData.llm_provider, false);
    setTestResult(null);
  }, [formData.llm_provider]);

  const currentModel = getActiveModel(formData);
  const inDropdown = modelOptions.some((m) => m.id === currentModel);

  const handleTestModel = async () => {
    setTestingModel(true);
    setTestResult(null);
    try {
      const res = await fetch(`${BACKEND_URL}/api/providers/test-model`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: formData.llm_provider,
          model: currentModel,
          base_url:
            formData.llm_provider === "openai"
              ? formData.openai_base_url
              : formData.llm_provider === "local"
              ? formData.local_model_url
              : undefined,
        }),
      });
      if (res.ok) {
        const result: ModelTestResult = await res.json();
        setTestResult(result);
      }
    } catch (e) {
      setTestResult({
        ok: false,
        provider: formData.llm_provider,
        model: currentModel,
        latency_ms: 0,
        error: String(e),
      });
    } finally {
      setTestingModel(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await updateSettings(formData);
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 2000);
  };

  return (
    <div className="flex flex-col h-full bg-fl-panel rounded-lg border border-fl-border overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-fl-border bg-slate-900/60 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Settings className="w-4 h-4 text-slate-300" />
          <h2 className="text-xs font-semibold text-slate-200">Asistan Yapılandırması (Settings)</h2>
        </div>
        {savedSuccess && (
          <span className="flex items-center space-x-1 text-emerald-400 text-xs font-medium">
            <Check className="w-3.5 h-3.5" />
            <span>Ayarlar Kaydedildi</span>
          </span>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex-1 p-4 overflow-y-auto space-y-5 text-xs">
        {/* Model Provider Section */}
        <div className="p-3 rounded-lg bg-fl-card border border-fl-border space-y-3">
          <div className="flex items-center justify-between border-b border-slate-700/80 pb-2">
            <div className="flex items-center space-x-2 text-slate-200 font-semibold">
              <Cpu className="w-4 h-4 text-fl-orange" />
              <span>Yapay Zeka Modeli Sağlayıcısı</span>
            </div>
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={() => loadModelsForProvider(formData.llm_provider, true)}
                disabled={fetchingModels}
                className="flex items-center space-x-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-600 text-[11px] text-slate-200 disabled:opacity-50"
              >
                <RefreshCw className={`w-3 h-3 ${fetchingModels ? "animate-spin" : ""}`} />
                <span>API&apos;den Modelleri Getir</span>
              </button>
              <button
                type="button"
                onClick={handleTestModel}
                disabled={testingModel || !currentModel}
                className="flex items-center space-x-1 px-2 py-1 rounded bg-emerald-900/40 hover:bg-emerald-800/50 border border-emerald-700/60 text-[11px] text-emerald-300 disabled:opacity-50"
              >
                <Zap className="w-3 h-3" />
                <span>{testingModel ? "Test Ediliyor..." : "Modeli Test Et"}</span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">Sağlayıcı (Provider)</label>
              <select
                value={formData.llm_provider}
                onChange={(e) => {
                  setCustomMode(false);
                  setFormData({ ...formData, llm_provider: e.target.value });
                }}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-fl-orange"
              >
                <option value="gemini">Google Gemini (3.5 Flash-Lite / Flash)</option>
                <option value="openai">OpenAI (GPT-4o-mini / GPT-4o)</option>
                <option value="anthropic">Anthropic (Claude Sonnet 4 / Haiku)</option>
                <option value="local">Yerel Model (Ollama / LM Studio)</option>
              </select>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-slate-400 text-[11px]">Model Seçimi</label>
                <button
                  type="button"
                  onClick={() => setCustomMode((v) => !v)}
                  className="text-[10px] text-cyan-400 hover:underline"
                >
                  {customMode ? "Listeden Seç" : "Özel Ad Gir"}
                </button>
              </div>
              {customMode ? (
                <input
                  type="text"
                  value={currentModel}
                  onChange={(e) => setFormData(withActiveModel(formData, e.target.value))}
                  placeholder="Örn: gemini-3.5-flash-lite"
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-fl-orange font-mono text-[11px]"
                />
              ) : (
                <select
                  value={inDropdown ? currentModel : "__custom__"}
                  onChange={(e) => {
                    if (e.target.value === "__custom__") {
                      setCustomMode(true);
                    } else {
                      setFormData(withActiveModel(formData, e.target.value));
                      setTestResult(null);
                    }
                  }}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-fl-orange font-mono text-[11px]"
                >
                  {!inDropdown && currentModel && (
                    <option value="__custom__">{currentModel} (Mevcut / Özel)</option>
                  )}
                  {modelOptions.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                  <option value="__custom__">+ Özel model adı yaz...</option>
                </select>
              )}
            </div>
          </div>

          {fetchNote && (
            <div className="text-[11px] text-slate-300 bg-slate-900/60 border border-slate-700/70 rounded px-2.5 py-1.5">
              {fetchNote}
            </div>
          )}

          {testResult && (
            <div
              className={`flex items-center justify-between gap-2 text-[11px] rounded px-2.5 py-1.5 border ${
                testResult.ok
                  ? "bg-emerald-950/50 border-emerald-700/60 text-emerald-300"
                  : "bg-amber-950/50 border-amber-700/60 text-amber-200"
              }`}
            >
              <div className="flex items-center space-x-1.5 min-w-0">
                {testResult.ok ? (
                  <Check className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
                ) : (
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-amber-400" />
                )}
                <span className="truncate">
                  {testResult.ok
                    ? `Model hazır: ${testResult.model} (${testResult.latency_ms} ms)`
                    : `${testResult.model} yanıt vermedi: ${testResult.error}`}
                </span>
              </div>
              {!testResult.ok && testResult.suggested_model && testResult.suggested_model !== currentModel && (
                <button
                  type="button"
                  onClick={() => {
                    const updated = withActiveModel(formData, testResult.suggested_model!);
                    setFormData(updated);
                    setCustomMode(false);
                    setTestResult(null);
                  }}
                  className="shrink-0 px-2 py-0.5 rounded bg-fl-orange text-black font-semibold hover:bg-orange-400"
                >
                  Önerilene Geç ({testResult.suggested_model})
                </button>
              )}
            </div>
          )}
        </div>

        {/* FL Studio Entegrasyon Ayarları */}
        <div className="p-3 rounded-lg bg-fl-card border border-fl-border space-y-3">
          <div className="flex items-center space-x-2 text-slate-200 font-semibold border-b border-slate-700/80 pb-2">
            <Sliders className="w-4 h-4 text-cyan-400" />
            <span>FL Studio MCP Bağlantı Parametreleri</span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">Daemon Host</label>
              <input
                type="text"
                value={formData.fl_mcp_host}
                onChange={(e) => setFormData({ ...formData, fl_mcp_host: e.target.value })}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-fl-orange font-mono"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">Daemon TCP Port</label>
              <input
                type="number"
                value={formData.fl_mcp_port}
                onChange={(e) => setFormData({ ...formData, fl_mcp_port: parseInt(e.target.value, 10) || 9787 })}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-fl-orange font-mono"
              />
            </div>
          </div>
        </div>

        {/* Güvenlik & İzinler */}
        <div className="p-3 rounded-lg bg-fl-card border border-fl-border space-y-3">
          <div className="flex items-center space-x-2 text-slate-200 font-semibold border-b border-slate-700/80 pb-2">
            <Shield className="w-4 h-4 text-emerald-400" />
            <span>Güvenlik, Doğrulama & Dil</span>
          </div>

          <div className="space-y-2">
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.hcu_enabled}
                onChange={(e) => setFormData({ ...formData, hcu_enabled: e.target.checked })}
                className="rounded bg-slate-900 border-slate-700 text-fl-orange focus:ring-0"
              />
              <span className="text-slate-300">Microsoft HCU GUI Otomasyonunu Etkinleştir</span>
            </label>

            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.auto_verify}
                onChange={(e) => setFormData({ ...formData, auto_verify: e.target.checked })}
                className="rounded bg-slate-900 border-slate-700 text-fl-orange focus:ring-0"
              />
              <span className="text-slate-300">Tüm Eylemleri Otomatik Olarak Oku ve Doğrula (Strict Verification)</span>
            </label>

            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.safe_mode}
                onChange={(e) => setFormData({ ...formData, safe_mode: e.target.checked })}
                className="rounded bg-slate-900 border-slate-700 text-fl-orange focus:ring-0"
              />
              <span className="text-slate-300">Güvenli Mod (Yıkıcı işlemler öncesi onay zorunlu)</span>
            </label>
          </div>

          <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
            <label className="text-slate-400">Arayüz Dili</label>
            <select
              value={formData.language}
              onChange={(e) => setFormData({ ...formData, language: e.target.value })}
              className="bg-slate-900 border border-slate-700 rounded px-2.5 py-1 text-white focus:outline-none"
            >
              <option value="tr">Türkçe (Varsayılan)</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>

        {/* Save Button */}
        <div className="flex justify-end pt-2">
          <button
            type="submit"
            className="flex items-center space-x-1.5 px-4 py-2 bg-fl-orange hover:bg-orange-400 text-black font-semibold rounded-lg text-xs transition shadow-md shadow-orange-500/10"
          >
            <Save className="w-3.5 h-3.5" />
            <span>Ayarları Kaydet</span>
          </button>
        </div>
      </form>
    </div>
  );
};

