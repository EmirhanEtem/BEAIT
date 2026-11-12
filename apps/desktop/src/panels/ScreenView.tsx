import React, { useState } from "react";
import { useStore } from "../store/useStore";
import { CursorMarkerOverlay } from "../components/CursorMarker";
import { Eye, Camera, RefreshCw, AlertCircle, Monitor } from "lucide-react";

export const ScreenView: React.FC = () => {
  const { cursorMarker, activeTask, connection } = useStore();
  const [isCapturing, setIsCapturing] = useState(false);
  const [screenshotInfo, setScreenshotInfo] = useState<{ width: number; height: number } | null>(null);

  const handleCaptureScreen = async () => {
    setIsCapturing(true);
    try {
      const res = await fetch("http://127.0.0.1:8765/api/screen/capture", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setScreenshotInfo({ width: data.width, height: data.height });
        }
      }
    } catch (e) {
      console.error("Capture failed:", e);
    } finally {
      setIsCapturing(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-fl-panel rounded-lg border border-fl-border overflow-hidden">
      {/* Panel Header */}
      <div className="p-3 border-b border-fl-border bg-slate-900/60 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Eye className="w-4 h-4 text-cyan-400" />
          <h2 className="text-xs font-semibold text-slate-200">Ekran & Eylem Görselleştirme (Screen / Action View)</h2>
        </div>
        <div className="flex items-center space-x-2">
          <button
            onClick={handleCaptureScreen}
            disabled={isCapturing}
            className="flex items-center space-x-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 border border-slate-700 transition"
          >
            <Camera className="w-3.5 h-3.5 text-cyan-400" />
            <span>{isCapturing ? "Alınıyor..." : "Masaüstü Görüntüsü Al"}</span>
          </button>
        </div>
      </div>

      {/* Info Notice regarding cursor movement */}
      <div className="px-3 py-2 bg-slate-900/40 border-b border-slate-800 text-[11px] text-slate-400 flex items-center justify-between">
        <div className="flex items-center space-x-1.5">
          <Monitor className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span>
            {cursorMarker.active
              ? `Eylem İşareti: "${cursorMarker.label}" (Companion UI Görselleştirmesi)`
              : "Aktif otomasyon hedefi bekleniyor."}
          </span>
        </div>
        <span className="text-[10px] text-slate-500">
          Kural: Arka plan girdileri sahte fare hareketi olarak yansıtılmaz.
        </span>
      </div>

      {/* Canvas View Area */}
      <div className="flex-1 relative bg-slate-950 flex items-center justify-center overflow-hidden p-4">
        {/* Mock DAW Viewport Frame */}
        <div className="relative w-full h-full max-w-4xl max-h-[500px] border border-slate-800 rounded-lg bg-slate-900/80 shadow-2xl overflow-hidden flex flex-col">
          {/* Mock FL Studio Header / Toolbar */}
          <div className="h-8 bg-slate-800 border-b border-slate-700/80 px-3 flex items-center justify-between text-[11px] text-slate-400 select-none">
            <div className="flex items-center space-x-4">
              <span className="font-bold text-fl-orange">FL Studio 2025</span>
              <span className="text-slate-300">Proje Önizleme Alanı</span>
            </div>
            <div className="flex items-center space-x-2 text-[10px] text-slate-500 font-mono">
              <span>CANVAS: 1365x768</span>
              {screenshotInfo && (
                <span className="text-cyan-400">SON YAKALAMA: {screenshotInfo.width}x{screenshotInfo.height}</span>
              )}
            </div>
          </div>

          {/* Canvas Interactive Grid */}
          <div className="flex-1 relative bg-[#181a20] p-4 flex flex-col justify-between">
            {/* Visual Tracks Simulation */}
            <div className="grid grid-cols-4 gap-2 h-28">
              <div className="rounded border border-slate-700/60 bg-slate-800/40 p-2 flex flex-col justify-between">
                <span className="text-[10px] text-slate-400 font-medium">808 Kick</span>
                <div className="h-2 rounded bg-orange-500/30 w-3/4"></div>
              </div>
              <div className="rounded border border-slate-700/60 bg-slate-800/40 p-2 flex flex-col justify-between">
                <span className="text-[10px] text-slate-400 font-medium">808 Clap</span>
                <div className="h-2 rounded bg-cyan-500/30 w-1/2"></div>
              </div>
              <div className="rounded border border-slate-700/60 bg-slate-800/40 p-2 flex flex-col justify-between">
                <span className="text-[10px] text-slate-400 font-medium">808 HiHat</span>
                <div className="h-2 rounded bg-emerald-500/30 w-full"></div>
              </div>
              <div className="rounded border border-slate-700/60 bg-slate-800/40 p-2 flex flex-col justify-between">
                <span className="text-[10px] text-slate-400 font-medium">FLEX Bass</span>
                <div className="h-2 rounded bg-purple-500/30 w-2/3"></div>
              </div>
            </div>

            {/* Piano Roll / Grid Simulation */}
            <div className="h-44 border border-slate-800 rounded bg-slate-900/60 p-3 flex flex-col justify-between">
              <div className="flex items-center justify-between text-[11px] text-slate-400 border-b border-slate-800 pb-1">
                <span>Piano Roll / Step Sequencer View</span>
                <span className="text-fl-orange font-mono">A Minor - 128 BPM</span>
              </div>
              {/* Pattern Blocks */}
              <div className="grid grid-cols-16 gap-1 h-20 items-center">
                {Array.from({ length: 16 }).map((_, i) => (
                  <div
                    key={i}
                    className={`h-12 rounded border ${
                      i % 4 === 0
                        ? "bg-fl-orange/20 border-fl-orange/40"
                        : "bg-slate-800/40 border-slate-800"
                    }`}
                  />
                ))}
              </div>
            </div>

            {/* Synchronized Cursor / Action Marker Overlay */}
            <CursorMarkerOverlay />
          </div>
        </div>
      </div>
    </div>
  );
};

