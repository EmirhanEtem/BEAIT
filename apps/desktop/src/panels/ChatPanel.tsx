import React, { useState } from "react";
import { useStore } from "../store/useStore";
import { Send, Sparkles, Terminal, Square, CheckCircle2, Clock, AlertTriangle } from "lucide-react";

export const ChatPanel: React.FC = () => {
  const [prompt, setPrompt] = useState("");
  const [isMock, setIsMock] = useState(false);
  const { messages, activeTask, isExecuting, submitTask, stopActiveTask, projectContext } = useStore();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isExecuting) return;
    submitTask(prompt.trim(), isMock);
    setPrompt("");
  };

  const handlePreset = (text: string) => {
    setPrompt(text);
  };

  return (
    <div className="flex flex-col h-full bg-fl-panel rounded-lg border border-fl-border overflow-hidden">
      {/* Panel Header */}
      <div className="p-3 border-b border-fl-border bg-slate-900/60 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Terminal className="w-4 h-4 text-fl-orange" />
          <span className="text-xs font-semibold text-slate-200">Asistan Sohbeti & Komutlar</span>
        </div>
        <div className="flex items-center space-x-2">
          <label className="flex items-center space-x-1.5 text-xs text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={isMock}
              onChange={(e) => setIsMock(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-fl-orange focus:ring-0 w-3.5 h-3.5"
            />
            <span className={isMock ? "text-amber-400 font-medium" : "text-emerald-400 font-medium"}>
              {isMock ? "Mock / Test Modu" : "Gerçek FL Studio"}
            </span>
          </label>
        </div>
      </div>

      {/* Messages Feed */}
      <div className="flex-1 p-4 overflow-y-auto space-y-3">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500">
            <Sparkles className="w-8 h-8 text-fl-orange/60 mb-2" />
            <p className="text-sm font-medium text-slate-400">FL Studio Asistanı Hazır</p>
            <p className="text-xs max-w-sm mt-1">
              Doğal dil ile müzik üretim talimatı verin. Asistan adımları planlayacak ve görsel olarak yürütecektir.
            </p>
            {/* Quick Suggestions */}
            <div className="mt-4 flex flex-wrap gap-2 justify-center max-w-md">
              <button
                onClick={() =>
                  handlePreset(
                    "FL Studio'da 128 BPM, A minor tonunda melodic techno başlangıcı oluştur. Kick ve percussion düzenini kur, bassline ve ana melodiyi yaz, sonra kısa bir intro ve drop arrangement'ı hazırla."
                  )
                }
                className="text-xs px-2.5 py-1.5 rounded bg-fl-orange/20 hover:bg-fl-orange/30 text-fl-orange border border-fl-orange/40 transition font-medium"
              >
                🚀 Tam Melodic Techno Prodüksiyon Planı (128 BPM A Minor)
              </button>
              <button
                onClick={() => handlePreset("128 BPM, A minor tonunda melodic techno kick ve bas düzeni oluştur.")}
                className="text-xs px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 border border-slate-700 transition"
              >
                🥁 128 BPM Techno Kick & Bass
              </button>
              <button
                onClick={() => handlePreset("Mevcut projeyi oku, BPM ve mikser kanallarını kontrol et.")}
                className="text-xs px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 border border-slate-700 transition"
              >
                🔍 Proje Durumunu Oku
              </button>
              <button
                onClick={() => handlePreset("Lead melodi için 8 barlık bir motif tasarla ve piyanoya aktar.")}
                className="text-xs px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 border border-slate-700 transition"
              >
                🎹 Lead Melodi Motifi
              </button>
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex flex-col ${
                msg.role === "user" ? "items-end" : "items-start"
              }`}
            >
              <div
                className={`max-w-[85%] rounded-lg px-3.5 py-2.5 text-xs ${
                  msg.role === "user"
                    ? "bg-fl-orange text-black font-medium"
                    : msg.role === "system"
                    ? "bg-slate-900 border border-slate-700 text-amber-300"
                    : "bg-fl-card border border-fl-border text-slate-200"
                }`}
              >
                <div className="flex items-center space-x-1 mb-1 opacity-75 text-[10px]">
                  <span>{msg.role === "user" ? "Sen" : msg.role === "system" ? "Sistem" : "AI Asistan"}</span>
                  <span>•</span>
                  <span>{new Date(msg.created_at).toLocaleTimeString()}</span>
                </div>
                <p className="whitespace-pre-wrap leading-relaxed">{msg.text}</p>
              </div>
            </div>
          ))
        )}

        {/* Active Task Progress Banner */}
        {activeTask && (
          <div className="mt-3 p-3 rounded-lg bg-slate-900/90 border border-fl-border text-xs">
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-fl-orange flex items-center space-x-1.5">
                <Clock className="w-3.5 h-3.5 animate-spin" />
                <span>Yürütülen Plan: {activeTask.prompt}</span>
              </span>
              <button
                onClick={stopActiveTask}
                className="text-[11px] px-2 py-0.5 rounded bg-rose-900/80 hover:bg-rose-800 text-rose-200 border border-rose-700 flex items-center space-x-1"
              >
                <Square className="w-2.5 h-2.5 fill-current" />
                <span>İptal Et</span>
              </button>
            </div>

            <div className="space-y-1.5 mt-2">
              {activeTask.actions.map((act, i) => (
                <div
                  key={act.action_id}
                  className={`flex items-center justify-between p-1.5 rounded text-[11px] ${
                    act.status === "RUNNING"
                      ? "bg-slate-800 border border-fl-orange/40 text-fl-orange"
                      : act.status === "SUCCEEDED"
                      ? "bg-slate-800/40 text-emerald-400"
                      : act.status === "CANCELLED"
                      ? "bg-slate-800/20 text-slate-500 line-through"
                      : "text-slate-400"
                  }`}
                >
                  <span className="flex items-center space-x-1.5">
                    <span className="font-mono text-[10px] text-slate-500">{i + 1}.</span>
                    <span>{act.name}</span>
                    <span className="text-[9px] px-1 rounded bg-slate-900 text-slate-400 border border-slate-700">
                      {act.route}
                    </span>
                  </span>
                  <span className="font-mono text-[10px]">{act.status}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Input Form */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-fl-border bg-slate-900/80">
        <div className="flex items-center space-x-2">
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isExecuting}
            placeholder={
              isExecuting
                ? "Bir plan yürütülüyor... Lütfen bekleyin veya Durdur'a basın."
                : "Örn: 128 BPM Techno başlangıç hazırla, kick ve bas yaz..."
            }
            className="flex-1 bg-fl-card border border-fl-border rounded-lg px-3.5 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-fl-orange transition disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!prompt.trim() || isExecuting}
            className="px-4 py-2 bg-fl-orange hover:bg-orange-400 text-black font-semibold rounded-lg text-xs flex items-center space-x-1.5 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-md shadow-orange-500/10"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Gönder</span>
          </button>
        </div>
      </form>
    </div>
  );
};

