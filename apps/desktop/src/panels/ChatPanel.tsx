import React, { useEffect, useRef, useState } from "react";
import { useStore } from "../store/useStore";
import {
  Send,
  Sparkles,
  Square,
  Clock,
  MessageSquarePlus,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Trash2,
  Pencil,
  Check,
  X,
} from "lucide-react";

function formatShortTime(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  const now = new Date();
  const sameDay =
    dt.getFullYear() === now.getFullYear() &&
    dt.getMonth() === now.getMonth() &&
    dt.getDate() === now.getDate();
  return sameDay
    ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : dt.toLocaleDateString([], { day: "2-digit", month: "short" });
}

export const ChatPanel: React.FC = () => {
  const [prompt, setPrompt] = useState("");
  const [isMock, setIsMock] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const {
    sessions,
    activeSessionId,
    isChatSidebarOpen,
    setChatSidebarOpen,
    messages,
    activeTask,
    isExecuting,
    createNewChat,
    selectChat,
    deleteChat,
    renameChat,
    submitTask,
    stopActiveTask,
  } = useStore();

  const activeSession = sessions.find((s) => s.session_id === activeSessionId) || null;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, activeSessionId]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isExecuting) return;
    submitTask(prompt.trim(), isMock);
    setPrompt("");
  };

  const handlePreset = (text: string) => {
    setPrompt(text);
  };

  const handleNewChat = async () => {
    setEditingId(null);
    setPrompt("");
    await createNewChat();
  };

  const startRename = (e: React.MouseEvent, sessionId: string, currentTitle: string) => {
    e.stopPropagation();
    setEditingId(sessionId);
    setEditingTitle(currentTitle);
  };

  const commitRename = async (e?: React.FormEvent | React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (editingId && editingTitle.trim()) {
      await renameChat(editingId, editingTitle.trim());
    }
    setEditingId(null);
    setEditingTitle("");
  };

  const cancelRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(null);
    setEditingTitle("");
  };

  return (
    <div className="flex flex-col h-full bg-fl-panel rounded-lg border border-fl-border overflow-hidden">
      {/* Panel Header */}
      <div className="p-2.5 border-b border-fl-border bg-slate-900/70 flex items-center justify-between gap-2">
        <div className="flex items-center space-x-2 min-w-0">
          <button
            type="button"
            onClick={() => setChatSidebarOpen(!isChatSidebarOpen)}
            title={isChatSidebarOpen ? "Sohbet Listesini Gizle" : "Sohbet Geçmişini Göster"}
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-100 hover:bg-slate-800 border border-transparent hover:border-slate-700 transition shrink-0"
          >
            {isChatSidebarOpen ? (
              <PanelLeftClose className="w-4 h-4" />
            ) : (
              <PanelLeftOpen className="w-4 h-4" />
            )}
          </button>
          <div className="flex flex-col min-w-0">
            <span className="text-xs font-semibold text-slate-100 truncate">
              {activeSession ? activeSession.title : "Yeni Sohbet"}
            </span>
            <span className="text-[10px] text-slate-500">
              İzole Hafıza • {messages.length} mesaj
            </span>
          </div>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          <button
            type="button"
            onClick={handleNewChat}
            title="Sıfırdan yeni bir sohbet sayfası aç"
            className="flex items-center space-x-1 px-2.5 py-1 rounded-md text-[11px] font-semibold bg-fl-orange/15 hover:bg-fl-orange/25 text-fl-orange border border-fl-orange/40 transition"
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            <span>Yeni Sohbet</span>
          </button>

          <label className="flex items-center space-x-1.5 text-[11px] text-slate-400 cursor-pointer pl-1 border-l border-slate-800">
            <input
              type="checkbox"
              checked={isMock}
              onChange={(e) => setIsMock(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-fl-orange focus:ring-0 w-3.5 h-3.5"
            />
            <span className={isMock ? "text-amber-400 font-medium" : "text-emerald-400 font-medium"}>
              {isMock ? "Mock" : "Canlı FL"}
            </span>
          </label>
        </div>
      </div>

      {/* Main Split: Collapsible Session List + Active Chat Feed */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {isChatSidebarOpen && (
          <aside className="w-44 shrink-0 border-r border-fl-border bg-slate-950/60 flex flex-col">
            <div className="p-2 border-b border-slate-800/80 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Sohbetler ({sessions.length})
              </span>
              <button
                type="button"
                onClick={handleNewChat}
                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
              >
                + Yeni
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-1.5 space-y-1">
              {sessions.map((sess) => {
                const isActive = sess.session_id === activeSessionId;
                const isEditing = editingId === sess.session_id;
                return (
                  <div
                    key={sess.session_id}
                    onClick={() => {
                      if (!isEditing) selectChat(sess.session_id);
                    }}
                    className={`group rounded-md px-2 py-2 cursor-pointer border transition ${
                      isActive
                        ? "bg-fl-orange/15 border-fl-orange/50 text-slate-100"
                        : "bg-transparent border-transparent hover:bg-slate-900/90 hover:border-slate-800 text-slate-400"
                    }`}
                  >
                    {isEditing ? (
                      <div
                        className="flex items-center space-x-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="text"
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commitRename();
                            if (e.key === "Escape") {
                              setEditingId(null);
                              setEditingTitle("");
                            }
                          }}
                          autoFocus
                          className="w-full bg-slate-900 border border-fl-orange rounded px-1.5 py-0.5 text-[11px] text-white focus:outline-none"
                        />
                        <button
                          type="button"
                          onClick={commitRename}
                          className="text-emerald-400 hover:text-emerald-300 p-0.5"
                          title="Kaydet"
                        >
                          <Check className="w-3 h-3" />
                        </button>
                        <button
                          type="button"
                          onClick={cancelRename}
                          className="text-slate-400 hover:text-slate-200 p-0.5"
                          title="İptal"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-center justify-between gap-1">
                          <div className="flex items-center space-x-1.5 min-w-0">
                            <MessageSquare
                              className={`w-3 h-3 shrink-0 ${
                                isActive ? "text-fl-orange" : "text-slate-500"
                              }`}
                            />
                            <span className="text-[11px] font-medium truncate">
                              {sess.title}
                            </span>
                          </div>
                          <div className="hidden group-hover:flex items-center space-x-0.5 shrink-0">
                            <button
                              type="button"
                              onClick={(e) => startRename(e, sess.session_id, sess.title)}
                              className="p-0.5 text-slate-400 hover:text-slate-100 rounded"
                              title="Yeniden Adlandır"
                            >
                              <Pencil className="w-2.5 h-2.5" />
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                deleteChat(sess.session_id);
                              }}
                              className="p-0.5 text-slate-400 hover:text-rose-400 rounded"
                              title="Sohbeti Sil"
                            >
                              <Trash2 className="w-2.5 h-2.5" />
                            </button>
                          </div>
                        </div>

                        <div className="mt-1 flex items-center justify-between text-[9px] text-slate-500">
                          <span className="truncate max-w-[95px]">
                            {sess.last_message_preview || "Boş sohbet"}
                          </span>
                          <span className="shrink-0">
                            {formatShortTime(sess.updated_at)}
                          </span>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </aside>
        )}

        {/* Active Conversation Column */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Messages Feed */}
          <div className="flex-1 p-4 overflow-y-auto space-y-3">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-4 text-slate-500">
                <Sparkles className="w-8 h-8 text-fl-orange/70 mb-2" />
                <div className="mb-2 inline-flex items-center space-x-1.5 px-2.5 py-0.5 rounded-full bg-slate-900 border border-slate-700 text-[10px] text-slate-300">
                  <span>✨ Sıfırdan Temiz Sohbet</span>
                </div>
                <p className="text-sm font-medium text-slate-300">
                  {activeSession ? activeSession.title : "Yeni Sohbet"}
                </p>
                <p className="text-xs max-w-sm mt-1">
                  Bu sayfa yalnızca kendi içindeki konuşma hafızasını hatırlar. Yeni sayfa açtığınızda yapay zeka sıfırdan başlar.
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
            <div ref={messagesEndRef} />
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
      </div>
    </div>
  );
};

