import React, { useState } from "react";
import { useStore, AppSettings } from "../store/useStore";
import { Settings, Shield, Cpu, Sliders, FolderOpen, Save, Check } from "lucide-react";

export const SettingsPanel: React.FC = () => {
  const { settings, updateSettings } = useStore();
  const [formData, setFormData] = useState<AppSettings>(settings);
  const [savedSuccess, setSavedSuccess] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateSettings(formData);
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
          <div className="flex items-center space-x-2 text-slate-200 font-semibold border-b border-slate-700/80 pb-2">
            <Cpu className="w-4 h-4 text-fl-orange" />
            <span>Yapay Zeka Modeli Sağlayıcısı</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">Sağlayıcı (Provider)</label>
              <select
                value={formData.llm_provider}
                onChange={(e) => setFormData({ ...formData, llm_provider: e.target.value })}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-fl-orange"
              >
                <option value="openai">OpenAI (GPT-4o / GPT-4o-mini)</option>
                <option value="anthropic">Anthropic (Claude 3.5 Sonnet / Opus)</option>
                <option value="local">Yerel Model (Ollama / LM Studio)</option>
              </select>
            </div>

            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">Model Adı</label>
              <input
                type="text"
                value={
                  formData.llm_provider === "openai"
                    ? formData.openai_model
                    : formData.llm_provider === "anthropic"
                    ? formData.anthropic_model
                    : formData.local_model_name
                }
                onChange={(e) => {
                  if (formData.llm_provider === "openai") setFormData({ ...formData, openai_model: e.target.value });
                  else if (formData.llm_provider === "anthropic") setFormData({ ...formData, anthropic_model: e.target.value });
                  else setFormData({ ...formData, local_model_name: e.target.value });
                }}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-fl-orange font-mono text-[11px]"
              />
            </div>
          </div>
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

