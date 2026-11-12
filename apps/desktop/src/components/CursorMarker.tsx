import React from "react";
import { useStore } from "../store/useStore";
import { MousePointer2, AlertCircle } from "lucide-react";

export const CursorMarkerOverlay: React.FC = () => {
  const { cursorMarker } = useStore();

  if (!cursorMarker.active || cursorMarker.x == null || cursorMarker.y == null) {
    return null;
  }

  return (
    <div
      className="absolute pointer-events-none transition-all duration-300 ease-out z-50 flex items-center space-x-2"
      style={{
        left: `${cursorMarker.x}px`,
        top: `${cursorMarker.y}px`,
        transform: "translate(-50%, -50%)",
      }}
    >
      {/* Reticle / Cursor icon */}
      <div className="relative">
        <MousePointer2 className="w-6 h-6 text-fl-orange fill-fl-orange/30 drop-shadow-md animate-bounce" />
        <span className="absolute -inset-1 rounded-full border border-fl-orange/50 animate-ping" />
      </div>

      {/* Target Description Tag */}
      <div className="bg-slate-900/90 border border-fl-border text-white text-[11px] px-2 py-0.5 rounded shadow-lg backdrop-blur flex items-center space-x-1 whitespace-nowrap">
        <span>{cursorMarker.label || "Hedef Kontrol"}</span>
        {!cursorMarker.is_real_desktop && (
          <span className="text-[9px] bg-slate-800 text-amber-300 px-1 rounded ml-1 font-mono">
            UI Simülasyonu
          </span>
        )}
      </div>
    </div>
  );
};

