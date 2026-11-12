import React from "react";
import { useStore } from "../store/useStore";
import { Activity, Circle, RefreshCw, Square, Terminal, ShieldAlert } from "lucide-react";

export const StatusBar: React.FC = () => {
  const { connection, isExecuting, stopActiveTask, refreshHealth, refreshContext } = useStore();

  const handleRefresh = async () => {
    await refreshHealth();
    await refreshContext();
  };

  return (
    <header className="h-14 border-b border-fl-border bg-fl-panel px-4 flex items-center justify-between select-none shrink-0">
      {/* Brand & Title */}
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded-lg bg-fl-orange flex items-center justify-center font-bold text-black shadow-lg shadow-orange-500/20">
          FL
        </div>
        <div>
          <h1 className="text-sm font-semibold tracking-wide text-white">FL Studio AI Assistant</h1>
          <span className="text-xs text-slate-400">Windows Desktop Companion (Phase 2 MVP)</span>
        </div>
      </div>

      {/* Connection Status Pills */}
      <div className="flex items-center space-x-3 text-xs">
        {/* Backend Online */}
        <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-slate-900 border border-slate-700">
          <Circle
            className={`w-2 h-2 fill-current ${
              connection.backend_online ? "text-emerald-400" : "text-rose-500 animate-pulse"
            }`}
          />
          <span className="text-slate-300">Backend:</span>
          <span className={connection.backend_online ? "text-emerald-400 font-medium" : "text-rose-400 font-medium"}>
            {connection.backend_online ? "Online" : "Offline"}
          </span>
        </div>

        {/* FL Studio MCP */}
        <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-slate-900 border border-slate-700">
          <Circle
            className={`w-2 h-2 fill-current ${
              connection.fl_studio_alive ? "text-emerald-400" : "text-amber-400"
            }`}
          />
          <span className="text-slate-300">FL Studio:</span>
          <span
            className={
              connection.fl_studio_alive
                ? "text-emerald-400 font-medium"
                : "text-amber-400 font-medium"
            }
          >
            {connection.fl_studio_alive ? "Bağlı (Canlı)" : "Bekleniyor"}
          </span>
        </div>

        {/* GUI Automation (HCU) */}
        <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-slate-900 border border-slate-700">
          <Circle
            className={`w-2 h-2 fill-current ${
              connection.hcu_available ? "text-cyan-400" : "text-slate-500"
            }`}
          />
          <span className="text-slate-300">GUI Auto (HCU):</span>
          <span className={connection.hcu_available ? "text-cyan-400 font-medium" : "text-slate-400 font-medium"}>
            {connection.hcu_available ? "Aktif" : "Devre Dışı"}
          </span>
        </div>

        {/* Refresh Button */}
        <button
          onClick={handleRefresh}
          title="Bağlantıları Yenile"
          className="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-white transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Global STOP Button */}
      <div className="flex items-center space-x-2">
        <button
          onClick={stopActiveTask}
          disabled={!isExecuting}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md font-medium text-xs transition shadow-sm ${
            isExecuting
              ? "bg-rose-600 hover:bg-rose-500 text-white animate-pulse"
              : "bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700"
          }`}
          title="Çalışan görevi acil durdur"
        >
          <Square className="w-3.5 h-3.5 fill-current" />
          <span>STOP (Durdur)</span>
        </button>
      </div>
    </header>
  );
};

