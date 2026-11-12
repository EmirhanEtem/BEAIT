import React from "react";
import { useStore } from "../store/useStore";
import { Sliders, RefreshCw, Music2, Layers, Play, Square, Mic, Info } from "lucide-react";

export const ProjectContextPanel: React.FC = () => {
  const { projectContext, refreshContext, connection } = useStore();

  return (
    <div className="flex flex-col h-full bg-fl-panel rounded-lg border border-fl-border overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-fl-border bg-slate-900/60 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Layers className="w-4 h-4 text-purple-400" />
          <h2 className="text-xs font-semibold text-slate-200">FL Studio Proje Bağlamı (Project Context)</h2>
        </div>
        <button
          onClick={refreshContext}
          className="flex items-center space-x-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-[11px] text-slate-300 transition"
        >
          <RefreshCw className="w-3 h-3" />
          <span>Yenile</span>
        </button>
      </div>

      <div className="flex-1 p-4 overflow-y-auto space-y-4 text-xs">
        {/* Core Stats Overview */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {/* Tempo */}
          <div className="p-2.5 rounded-lg bg-fl-card border border-fl-border">
            <span className="text-[10px] text-slate-400 uppercase tracking-wider block">Tempo (BPM)</span>
            <div className="mt-1 flex items-baseline space-x-1">
              <span className="text-lg font-bold font-mono text-fl-orange">
                {projectContext.tempo != null ? projectContext.tempo.toFixed(1) : "—"}
              </span>
              <span className="text-[10px] text-slate-500">BPM</span>
            </div>
          </div>

          {/* Time Signature */}
          <div className="p-2.5 rounded-lg bg-fl-card border border-fl-border">
            <span className="text-[10px] text-slate-400 uppercase tracking-wider block">Ölçü (Time Sig)</span>
            <div className="mt-1">
              {projectContext.time_signature ? (
                <span className="text-base font-bold text-white">{projectContext.time_signature}</span>
              ) : (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700 italic">
                  Bilinmiyor (API Desteksiz)
                </span>
              )}
            </div>
          </div>

          {/* Transport State */}
          <div className="p-2.5 rounded-lg bg-fl-card border border-fl-border">
            <span className="text-[10px] text-slate-400 uppercase tracking-wider block">Transport Durumu</span>
            <div className="mt-1 flex items-center space-x-2">
              <span className={`flex items-center space-x-1 ${projectContext.playing ? "text-emerald-400" : "text-slate-400"}`}>
                {projectContext.playing ? <Play className="w-3.5 h-3.5 fill-current" /> : <Square className="w-3.5 h-3.5" />}
                <span className="text-[11px] font-medium">{projectContext.playing ? "Çalıyor" : "Durduruldu"}</span>
              </span>
            </div>
          </div>

          {/* FL Studio Version */}
          <div className="p-2.5 rounded-lg bg-fl-card border border-fl-border">
            <span className="text-[10px] text-slate-400 uppercase tracking-wider block">DAW Sürümü</span>
            <div className="mt-1 truncate">
              <span className="text-xs font-mono text-slate-200">
                {projectContext.fl_version || "Algılanamadı"}
              </span>
            </div>
          </div>
        </div>

        {/* Project Title / File */}
        <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 flex items-center justify-between">
          <span className="text-slate-400">Proje Adı / Dosya:</span>
          {projectContext.title ? (
            <span className="font-semibold text-white font-mono">{projectContext.title}</span>
          ) : (
            <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-amber-300/80 border border-slate-700 italic">
              Bilinmiyor (FL Studio Script API başlık döndürmüyor)
            </span>
          )}
        </div>

        {/* Channel Rack Section */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-300 flex items-center space-x-1.5">
              <Music2 className="w-3.5 h-3.5 text-fl-orange" />
              <span>Channel Rack Enstrüman & Ses Kanalları ({projectContext.channels.length})</span>
            </span>
          </div>

          {projectContext.channels.length === 0 ? (
            <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800 text-center text-slate-500 text-[11px]">
              Kanal verisi yok veya FL Studio oturumuna bağlanılmadı.
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {projectContext.channels.map((ch, idx) => (
                <div
                  key={idx}
                  className="p-2 rounded bg-fl-card border border-fl-border flex items-center justify-between"
                >
                  <span className="truncate font-medium text-slate-200">{ch.name || `Kanal ${idx + 1}`}</span>
                  <span className="text-[10px] font-mono text-slate-500">#{ch.i != null ? ch.i : idx}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Mixer Tracks Section */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-300 flex items-center space-x-1.5">
              <Sliders className="w-3.5 h-3.5 text-cyan-400" />
              <span>Mikser Kanalları ({projectContext.mixer_tracks.length})</span>
            </span>
          </div>

          {projectContext.mixer_tracks.length === 0 ? (
            <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800 text-center text-slate-500 text-[11px]">
              Mikser verisi yok.
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 max-h-48 overflow-y-auto p-1">
              {projectContext.mixer_tracks.map((track, idx) => (
                <div
                  key={idx}
                  className="p-1.5 rounded bg-fl-card/80 border border-slate-800 text-[11px] flex items-center justify-between"
                >
                  <span className="truncate text-slate-300">{track.name || `Insert ${idx}`}</span>
                  <span className="text-[9px] font-mono text-slate-500">#{track.i != null ? track.i : idx}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

