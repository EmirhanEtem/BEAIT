import React, { useEffect } from "react";
import { useStore } from "../store/useStore";
import { StatusBar } from "../components/StatusBar";
import { ChatPanel } from "../panels/ChatPanel";
import { ActivityPanel } from "../panels/ActivityPanel";
import { ScreenView } from "../panels/ScreenView";
import { ProjectContextPanel } from "../panels/ProjectContextPanel";
import { SettingsPanel } from "../panels/SettingsPanel";
import { MessageSquare, Activity, Monitor, Layers, Settings } from "lucide-react";

export const App: React.FC = () => {
  const { activeTab, setActiveTab, initWebSocket } = useStore();

  useEffect(() => {
    initWebSocket();
  }, []);

  return (
    <div className="flex flex-col h-screen w-screen bg-fl-bg text-slate-100 overflow-hidden font-sans">
      {/* Top Status Bar */}
      <StatusBar />

      {/* Main Workspace (Split View) */}
      <div className="flex-1 flex overflow-hidden p-3 gap-3">
        {/* Left Side: Chat & Commands Panel */}
        <div className="w-[48%] min-w-[440px] max-w-[700px] h-full flex flex-col">
          <ChatPanel />
        </div>

        {/* Right Side: Tabbed Multiview */}
        <div className="flex-1 flex flex-col h-full bg-fl-panel rounded-lg border border-fl-border overflow-hidden">
          {/* Navigation Tab Bar */}
          <div className="h-10 border-b border-fl-border bg-slate-900/80 px-2 flex items-center space-x-1 select-none">
            <button
              onClick={() => setActiveTab("activity")}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "activity" || activeTab === "main"
                  ? "bg-slate-800 text-fl-orange border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              <span>Canlı Eylem Akışı</span>
            </button>

            <button
              onClick={() => setActiveTab("screen")}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "screen"
                  ? "bg-slate-800 text-cyan-400 border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Monitor className="w-3.5 h-3.5" />
              <span>Ekran Görünümü</span>
            </button>

            <button
              onClick={() => setActiveTab("project")}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "project"
                  ? "bg-slate-800 text-purple-400 border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Proje Bağlamı</span>
            </button>

            <button
              onClick={() => setActiveTab("settings")}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "settings"
                  ? "bg-slate-800 text-white border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Settings className="w-3.5 h-3.5" />
              <span>Ayarlar</span>
            </button>
          </div>

          {/* Tab Content Display */}
          <div className="flex-1 overflow-hidden p-2">
            {(activeTab === "activity" || activeTab === "main") && <ActivityPanel />}
            {activeTab === "screen" && <ScreenView />}
            {activeTab === "project" && <ProjectContextPanel />}
            {activeTab === "settings" && <SettingsPanel />}
          </div>
        </div>
      </div>
    </div>
  );
};

