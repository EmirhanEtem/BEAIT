import React from "react";
import { useStore, ActionItem } from "../store/useStore";
import { Activity, CheckCircle2, Clock, XCircle, AlertCircle, ShieldCheck, Zap } from "lucide-react";

export const ActivityPanel: React.FC = () => {
  const { tasks, activeTask } = useStore();

  // Aggregate actions from active task and recent tasks
  const allActions: ActionItem[] = activeTask?.actions || (tasks.length > 0 ? tasks[tasks.length - 1].actions : []);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "SUCCEEDED":
        return (
          <span className="flex items-center space-x-1 text-emerald-400 bg-emerald-950/40 border border-emerald-800 px-2 py-0.5 rounded text-[10px]">
            <CheckCircle2 className="w-3 h-3" />
            <span>Tamamlandı</span>
          </span>
        );
      case "RUNNING":
        return (
          <span className="flex items-center space-x-1 text-fl-orange bg-orange-950/40 border border-orange-800 px-2 py-0.5 rounded text-[10px] animate-pulse">
            <Clock className="w-3 h-3 animate-spin" />
            <span>Yürütülüyor</span>
          </span>
        );
      case "CANCELLED":
        return (
          <span className="flex items-center space-x-1 text-slate-400 bg-slate-900 border border-slate-700 px-2 py-0.5 rounded text-[10px]">
            <XCircle className="w-3 h-3" />
            <span>İptal Edildi</span>
          </span>
        );
      case "FAILED":
        return (
          <span className="flex items-center space-x-1 text-rose-400 bg-rose-950/40 border border-rose-800 px-2 py-0.5 rounded text-[10px]">
            <AlertCircle className="w-3 h-3" />
            <span>Hata</span>
          </span>
        );
      default:
        return (
          <span className="text-slate-500 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded text-[10px]">
            {status}
          </span>
        );
    }
  };

  const getRouteBadge = (route: string) => {
    if (route === "FL_MCP") {
      return (
        <span className="px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800 text-[10px] font-mono">
          CANLI FL MCP
        </span>
      );
    }
    if (route === "GUI_AUTOMATION") {
      return (
        <span className="px-1.5 py-0.5 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-800 text-[10px] font-mono">
          GUI OTOMASYON
        </span>
      );
    }
    return (
      <span className="px-1.5 py-0.5 rounded bg-amber-950/40 text-amber-300 border border-amber-800 text-[10px] font-mono">
        MOCK / SİMÜLE
      </span>
    );
  };

  return (
    <div className="flex flex-col h-full bg-fl-panel rounded-lg border border-fl-border overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-fl-border bg-slate-900/60 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Activity className="w-4 h-4 text-emerald-400" />
          <h2 className="text-xs font-semibold text-slate-200">Canlı Eylem Akışı & Doğrulama (Activity Feed)</h2>
        </div>
        <span className="text-[11px] text-slate-400">
          Toplam Eylem: <span className="text-white font-mono">{allActions.length}</span>
        </span>
      </div>

      {/* Action List */}
      <div className="flex-1 p-3 overflow-y-auto space-y-2.5">
        {allActions.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500">
            <Zap className="w-8 h-8 text-slate-600 mb-2" />
            <p className="text-xs font-medium">Henüz Aktif Eylem Yok</p>
            <p className="text-[11px] max-w-xs mt-1 text-slate-500">
              Sohbet panelinden bir görev başlattığınızda yürütülen tüm müzik üretim adımları burada anlık olarak raporlanır.
            </p>
          </div>
        ) : (
          allActions.map((action, idx) => (
            <div
              key={action.action_id}
              className={`p-3 rounded-lg border transition-all ${
                action.status === "RUNNING"
                  ? "bg-slate-900/90 border-fl-orange shadow-md shadow-orange-500/5"
                  : action.status === "SUCCEEDED"
                  ? "bg-fl-card/90 border-slate-700/80"
                  : "bg-fl-card/50 border-fl-border opacity-70"
              }`}
            >
              {/* Top row: Name, Route, Status */}
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className="font-mono text-xs text-slate-500 font-bold">#{idx + 1}</span>
                  <span className="text-xs font-semibold text-slate-100">{action.name}</span>
                  {getRouteBadge(action.route)}
                </div>
                {getStatusBadge(action.status)}
              </div>

              {/* Description */}
              <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">{action.description}</p>

              {/* Target & Verification Footer */}
              <div className="mt-2.5 pt-2 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-[11px] gap-2">
                <div className="flex items-center space-x-2 text-slate-400">
                  <span>Hedef:</span>
                  <span className="text-slate-200 font-mono bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                    {action.target || "Belirtilmemiş"}
                  </span>
                </div>

                {action.verified != null && (
                  <div className="flex items-center space-x-1.5">
                    <ShieldCheck
                      className={`w-3.5 h-3.5 ${
                        action.verified ? "text-emerald-400" : "text-amber-400"
                      }`}
                    />
                    <span className={action.verified ? "text-emerald-400" : "text-amber-400"}>
                      {action.verification_detail || (action.verified ? "Doğrulandı" : "Do doğrulanamadı")}
                    </span>
                  </div>
                )}
              </div>

              {/* Error box if any */}
              {action.error && (
                <div className="mt-2 p-2 rounded bg-rose-950/50 border border-rose-800/80 text-[11px] text-rose-300">
                  <span className="font-semibold">Hata: </span>
                  {action.error}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

