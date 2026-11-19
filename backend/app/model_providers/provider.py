"""Model provider abstraction, prompt builder, and secret redaction.

Supports OpenAI, Google Gemini, Anthropic Claude, and Local (Ollama / LM Studio).
Priority in live execution is strictly AI-API-first: when an API key / local
model is available, the LLM designs the full creative composition, plugins,
FX chain, and mix/master plan. ``CreativeBeatEngine`` is used only as a fallback
when offline, unconfigured, or when all configured providers fail (with honest
disclosure in the returned metadata and ``ai_response``).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..music_engine.creative_engine import CreativeBeatEngine, NOTE_NAMES, SCALES
from .song_research import (
    SongResearchDossier,
    analyze_song_request,
    format_dossier_for_prompt,
    research_song,
)

logger = logging.getLogger(__name__)

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{12,})"),
    re.compile(r"(AIza[0-9A-Za-z\-_]{20,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9\-._~+/=]+)", re.IGNORECASE),
    re.compile(r"(x-api-key[\"':=\s]+[A-Za-z0-9\-_]{10,})", re.IGNORECASE),
    re.compile(r"([?&]key=[A-Za-z0-9\-_]{10,})", re.IGNORECASE),
    re.compile(
        r"((?:OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|ANTHROPIC_API_KEY|API_KEY)[ \t]*=[ \t]*[A-Za-z0-9\-_]{8,})",
        re.IGNORECASE,
    ),
]
SECRET_PATTERNS = _SECRET_PATTERNS

_DEFAULT_FX_CHAINS: Dict[str, List[str]] = {
    "chords": ["Fruity Parametric EQ 2", "Fruity Reeverb 2", "Fruity Chorus"],
    "bass": ["Fruity Parametric EQ 2", "Fruity Fast Dist", "Fruity Compressor"],
    "lead": ["Fruity Parametric EQ 2", "Fruity Delay 3", "Fruity Reeverb 2"],
    "arp": ["Fruity Parametric EQ 2", "Fruity Delay 3"],
    "pad": ["Fruity Parametric EQ 2", "Fruity Reeverb 2", "Fruity Stereo Enhancer"],
    "drums": ["Fruity Soft Clipper", "Fruity Compressor"],
    "master": ["Fruity Parametric EQ 2", "Fruity Soft Clipper", "Fruity Limiter"],
}

_GENERATOR_FALLBACKS: Dict[str, List[str]] = {
    "FL Keys": ["FLEX", "Sytrus", "3x Osc"],
    "FLEX": ["Sytrus", "FL Keys", "3x Osc"],
    "Sytrus": ["FLEX", "Harmless", "3x Osc"],
    "Harmless": ["Sytrus", "FLEX", "3x Osc"],
    "Harmor": ["Sytrus", "FLEX", "3x Osc"],
    "Sakura": ["FLEX", "Sytrus", "Plucked!"],
    "Plucked!": ["FLEX", "Sytrus", "FL Keys"],
    "3x Osc": ["Sytrus", "FLEX", "BooBass"],
    "BooBass": ["3x Osc", "Transistor Bass", "FLEX"],
    "Transistor Bass": ["3x Osc", "Sytrus", "FLEX"],
    "GMS": ["Sytrus", "FLEX", "3x Osc"],
    "SimSynth": ["Sytrus", "FLEX", "3x Osc"],
    "MiniSynth": ["Sytrus", "FLEX", "3x Osc"],
    "Sawer": ["Sytrus", "FLEX", "3x Osc"],
    "PoiZone": ["Sytrus", "FLEX", "3x Osc"],
}

_SYSTEM_PRODUCER_PROMPT = """You are an elite, deeply original FL Studio 2025 AI Music Producer, Sound Designer, and Mixing/Mastering Engineer.
Your mission is to compose genuinely creative, non-repetitive, expressive multi-track productions executed live inside FL Studio 2025 (loading generators, picking matching presets, sculpting synth knobs, loading Mixer FX chains, tuning FX parameters, Piano Roll, and Playlist arrangement).

Return ONLY a single valid JSON object (no markdown fences, no text outside JSON) following this schema:
{
  "ai_response": "Friendly response in the user's language summarizing your musical concept, harmony, instruments, synth sound design, FX, and mix",
  "intent_type": "full_production" | "edit" | "chat_only",
  "genre": "phonk" | "trap" | "drill" | "melodic_techno" | "house" | "tech_house" | "boom_bap" | "lofi" | "synthwave" | "afrobeat" | "ambient" | "cinematic" | "rnb" | "pop" | "uk_garage" | "dnb" | string,
  "mood": "dark" | "aggressive" | "sad" | "dreamy" | "epic" | "happy" | "chill",
  "tempo_bpm": 124.0,
  "key": "C" | "C#" | "D" | "Eb" | "E" | "F" | "F#" | "G" | "Ab" | "A" | "Bb" | "B",
  "scale": "dorian" | "phrygian" | "harmonic_minor" | "natural_minor" | "lydian" | "mixolydian" | "major",
  "swing": 0.18,
  "chord_progression": ["<Chord 1>", "<Chord 2>", "<Chord 3>", "<Chord 4>"],
  "sections": [
    {"name": "Intro", "bars": 4, "mode": "ambient", "roles": ["chords", "lead"]},
    {"name": "Build", "bars": 4, "mode": "rising", "roles": ["drums", "chords", "bass"]},
    {"name": "Drop", "bars": 8, "mode": "full", "roles": ["drums", "chords", "bass", "lead"]},
    {"name": "Outro", "bars": 4, "mode": "strip", "roles": ["chords", "lead"]}
  ],
  "drum_channels": [
    {"channel": 0, "name": "Kick", "steps": [0, 3, 6, 10], "length": 16, "velocity": 0.94},
    {"channel": 1, "name": "Clap", "steps": [4, 12], "length": 16, "velocity": 0.89},
    {"channel": 2, "name": "HiHat", "steps": [0, 2, 3, 4, 6, 8, 10, 11, 12, 14, 15], "length": 16, "velocity": 0.74},
    {"channel": 3, "name": "Perc", "steps": [7, 13, 15], "length": 16, "velocity": 0.78}
  ],
  "tracks": [
    {
      "role": "chords",
      "instrument_name": "<native FL synth/keys matched to prompt & seed>",
      "fallbacks": ["FLEX", "Sytrus", "FL Keys"],
      "preset_hint": "<2-3 descriptive keywords like Dark Pad, Warm Rhodes, Acoustic Nylon>",
      "generator_params": {"cutoff": 0.52, "resonance": 0.24, "attack": 0.22, "release": 0.58, "detune": 0.36, "reverb": 0.34, "warmth": 0.55},
      "notes": [
        {"pitch": "<midi int in chosen key across 0.0..4.0 bars — write 12 to 28 notes with inversions/syncopation>", "time_bars": 0.0, "length_bars": 0.45, "velocity": 0.76}
      ]
    },
    {
      "role": "bass",
      "instrument_name": "<native FL bass matched to prompt & seed>",
      "fallbacks": ["3x Osc", "Transistor Bass", "FLEX"],
      "preset_hint": "<2-3 descriptive keywords like Sub 808, Reese Bass, Punch Bass>",
      "generator_params": {"cutoff": 0.42, "resonance": 0.30, "attack": 0.06, "release": 0.32, "drive": 0.38, "sub": 0.78},
      "notes": [
        {"pitch": "<low midi int 28..52 locked to chord roots/5ths — write 8 to 18 notes across 0.0..4.0 bars>", "time_bars": 0.0, "length_bars": 0.375, "velocity": 0.94, "porta": false}
      ]
    },
    {
      "role": "lead",
      "instrument_name": "<native FL lead/pluck/bell matched to prompt & seed>",
      "fallbacks": ["Harmless", "Sytrus", "FLEX"],
      "preset_hint": "<2-3 descriptive keywords like Analog Lead, Glass Bell, Plucked Harp>",
      "generator_params": {"cutoff": 0.68, "resonance": 0.32, "attack": 0.10, "release": 0.44, "detune": 0.40, "reverb": 0.28, "delay": 0.26},
      "notes": [
        {"pitch": "<melodic midi int 60..88 across 0.0..4.0 bars — write 14 to 32 notes with motif + answer>", "time_bars": 0.0, "length_bars": 0.25, "velocity": 0.88}
      ]
    }
  ],
  "channel_mix": [
    {"channel": 0, "volume": 0.88, "pan": 0.0},
    {"channel": 2, "volume": 0.65, "pan": 0.16}
  ],
  "fx_plan": {
    "chords": ["Fruity Parametric EQ 2", "Fruity Reeverb 2", "Fruity Chorus"],
    "bass": ["Fruity Parametric EQ 2", "Fruity Fast Dist", "Fruity Compressor"],
    "lead": ["Fruity Parametric EQ 2", "Fruity Delay 3", "Fruity Reeverb 2"],
    "drums": ["Fruity Soft Clipper", "Fruity Multiband Compressor"],
    "master": ["Fruity Parametric EQ 2", "Fruity Soft Clipper", "Fruity Limiter"]
  },
  "fx_params": {
    "chords": {"reverb_wet": 0.32, "low_cut": 0.28, "stereo_width": 0.56},
    "bass": {"drive": 0.40, "sub_boost": 0.62, "comp_ratio": 0.48},
    "lead": {"delay_wet": 0.26, "reverb_wet": 0.24, "air_boost": 0.58},
    "master": {"ceiling": 0.47, "clipper_thresh": 0.82, "eq_air": 0.55}
  },
  "mix": {
    "enabled": true,
    "target_ceiling_db": -1.0,
    "loud": true,
    "wide_stereo": true,
    "punchy_drums": true,
    "style": "aggressive"
  },
  "play_state": "play"
}

Creative & Musical Rules:
1. For "chat_only" (greetings, questions, non-composition chat): omit tracks/drum_channels or leave them empty and answer concisely in "ai_response".
2. For music requests ("full_production" / "edit"):
   - ANTI-CLICHÉ ORIGINALITY: NEVER default repeatedly to A minor (Am-F-G), generic 4-note placeholders, or the same synth trio. Follow the "CREATIVE DIRECTION SEED" if provided (or the verified song dossier for song references) so every beat has a genuinely distinct harmonic color, rhythm, and sound palette.
   - UNIFIED 4-BAR PHASE COHESION: Every track ("chords", "bass", "lead") MUST follow ONE unified 4-bar chord progression spanning bars 0.0..4.0 (Bar 1: 0.0-1.0, Bar 2: 1.0-2.0, Bar 3: 2.0-3.0, Bar 4: 3.0-4.0). Do NOT leave any track under 3.5 bars!
   - NOTE DENSITY & EXPRESSIVE GROOVE:
     * Chords: 12-28+ notes (extended voicings like m9/maj7/sus4/add9, broken arpeggios, syncopated stabs or rhythmic comping — never just 4 static root triads!).
     * Bass/808: 8-18+ notes (~28..52 MIDI) locked to kick hits with ghost notes, octave jumps, 5th/approach tones, and "porta": true glides on slides!
     * Lead/Melody: 14-32+ notes (~60..88 MIDI) with recognizable call-and-response motifs, 16th/triplet ornaments, dynamic velocity, and turnaround variation in Bars 2 & 4.
     * Drums: Customize steps to fit the subgenre (2-step / UKG skippy hats, drill sliding snares, bossa/afro syncopation, four-on-the-floor house, boom-bap swung hats, or sparse trap rolls).
   - ACTIVE PLUGIN & SYNTH SOUND DESIGN:
     * Pick fitting FL Studio 2025 native generators ("FLEX", "Sytrus", "Harmless", "Harmor", "Sawer", "PoiZone", "GMS", "SimSynth", "Sakura", "Plucked!", "FL Keys", "3x Osc", "BooBass", "Transistor Bass").
     * ALWAYS supply a descriptive "preset_hint" and tailored normalized 0.0-1.0 "generator_params" (cutoff, resonance, attack, release, detune, warmth, drive, reverb, delay, sub) on every track — the engine will load matching presets and automate these synth knobs live!
   - SONG REFERENCE / REPLICA RULE: Whenever a "VERIFIED INTERNET SONG RESEARCH DOSSIER" is present, strictly LOCK "tempo_bpm", "key", "scale", "chord_progression", and accurately transcribe its recognizable riff/melody rather than inventing an unrelated loop.
   - MIXER FX & MASTERING: Always populate "fx_plan", "fx_params", and "mix" with native FL plugins ("Fruity Parametric EQ 2", "Fruity Reeverb 2", "Fruity Delay 3", "Fruity Soft Clipper", "Fruity Multiband Compressor", "Fruity Compressor", "Fruity Limiter", "Maximus", "Soundgoodizer", "Fruity Fast Dist", "Fruity Chorus", "Gross Beat"). Keep "master.ceiling" around 0.46-0.50 (-1.2 to 0.0 dB on FL Fruity Limiter; NEVER use 0.0 because 0.0 is -INF dB silence).
   - Every note pitch must be an integer 24..108, time_bars >= 0.0, length_bars >= 0.0625, velocity 0.20..1.0."""


def redact_secrets(text: str) -> str:
    """Replace any API keys or bearer tokens in text with [REDACTED_SECRET]."""
    if not text:
        return ""
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED_SECRET]", out)
    return out


def _load_dotenv_dict() -> Dict[str, str]:
    """Read variables from workspace .env without mutating os.environ."""
    candidates = [
        Path(__file__).resolve().parents[3] / ".env",
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
    ]
    data: Dict[str, str] = {}
    for p in candidates:
        if p.is_file():
            try:
                for raw in p.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in data:
                        data[k] = v
            except OSError:
                pass
            break
    return data


def _resolve_env(dotenv: Dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        val = (dotenv.get(key) or os.environ.get(key) or "").strip()
        if val:
            return val
    return default


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"

_GEMINI_FALLBACK_MODELS: Tuple[str, ...] = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
)

_LEGACY_BROKEN_GEMINI_MODELS = frozenset({
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
})

CURATED_PROVIDER_MODELS: Dict[str, List[Dict[str, Any]]] = {
    "gemini": [
        {
            "id": "gemini-3.5-flash-lite",
            "label": "Gemini 3.5 Flash-Lite (Önerilen • Çok Hızlı & Ücretsiz Kota Uyumlu)",
            "tier": "free_fast",
            "recommended": True,
        },
        {
            "id": "gemini-3.1-flash-lite",
            "label": "Gemini 3.1 Flash-Lite (Ultra Hızlı ~0.8 sn • Ücretsiz Kota Uyumlu)",
            "tier": "free_fast",
            "recommended": True,
        },
        {
            "id": "gemini-flash-lite-latest",
            "label": "Gemini Flash-Lite Latest (Otomatik En Güncel Lite)",
            "tier": "free_fast",
            "recommended": True,
        },
        {
            "id": "gemini-3-flash-preview",
            "label": "Gemini 3 Flash Preview (Yaratıcı & Hızlı ~1.6 sn)",
            "tier": "free_balanced",
            "recommended": False,
        },
        {
            "id": "gemini-3.5-flash",
            "label": "Gemini 3.5 Flash (Detaylı Düşünme • ~7 sn)",
            "tier": "free_slow",
            "recommended": False,
        },
    ],
    "openai": [
        {"id": "gpt-4o-mini", "label": "GPT-4o mini (Hızlı & Ekonomik)", "tier": "balanced", "recommended": True},
        {"id": "gpt-4o", "label": "GPT-4o (Yüksek Yaratıcılık)", "tier": "standard", "recommended": False},
        {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini", "tier": "balanced", "recommended": False},
        {"id": "gpt-4.1", "label": "GPT-4.1", "tier": "standard", "recommended": False},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4 (Yüksek Kalite)", "tier": "standard", "recommended": True},
        {"id": "claude-3-5-haiku-latest", "label": "Claude 3.5 Haiku (Hızlı)", "tier": "fast", "recommended": False},
    ],
    "local": [
        {"id": "llama3", "label": "Llama 3 (Ollama / Yerel)", "tier": "local", "recommended": True},
        {"id": "qwen2.5:14b", "label": "Qwen 2.5 14B (JSON Güçlü)", "tier": "local", "recommended": False},
        {"id": "mistral", "label": "Mistral", "tier": "local", "recommended": False},
    ],
}


@dataclass
class ProviderConfig:
    """Configuration for an LLM model provider."""

    provider_name: str = "openai"  # openai, gemini, anthropic, local
    model_name: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None
    allow_audio_upload: bool = False
    allow_project_file_upload: bool = False
    timeout_seconds: float = 28.0

    def __post_init__(self) -> None:
        prov = (self.provider_name or "openai").lower()
        self.provider_name = prov
        if prov == "gemini":
            if self.base_url in ("", "https://api.openai.com/v1"):
                self.base_url = "https://generativelanguage.googleapis.com/v1beta"
            if self.model_name in ("", "gpt-4o"):
                self.model_name = DEFAULT_GEMINI_MODEL
        elif prov == "anthropic":
            if self.base_url in ("", "https://api.openai.com/v1"):
                self.base_url = "https://api.anthropic.com"
            if self.model_name in ("", "gpt-4o"):
                self.model_name = "claude-sonnet-4-20250514"
        elif prov == "local":
            if self.base_url in ("", "https://api.openai.com/v1"):
                self.base_url = "http://localhost:11434"
            if self.model_name in ("", "gpt-4o"):
                self.model_name = "llama3"

    @classmethod
    def from_env(cls, provider_override: Optional[str] = None) -> "ProviderConfig":
        """Create a ProviderConfig populated from .env and environment variables."""
        dotenv = _load_dotenv_dict()
        provider = (provider_override or _resolve_env(dotenv, "LLM_PROVIDER", default="openai")).lower()

        if provider == "gemini":
            return cls(
                provider_name="gemini",
                model_name=_resolve_env(dotenv, "GEMINI_MODEL", default=DEFAULT_GEMINI_MODEL),
                base_url=_resolve_env(
                    dotenv,
                    "GEMINI_BASE_URL",
                    default="https://generativelanguage.googleapis.com/v1beta",
                ),
                api_key=_resolve_env(dotenv, "GEMINI_API_KEY", "GOOGLE_API_KEY") or None,
            )

        if provider == "anthropic":
            return cls(
                provider_name="anthropic",
                model_name=_resolve_env(dotenv, "ANTHROPIC_MODEL", default="claude-sonnet-4-20250514"),
                base_url=_resolve_env(dotenv, "ANTHROPIC_BASE_URL", default="https://api.anthropic.com"),
                api_key=_resolve_env(dotenv, "ANTHROPIC_API_KEY") or None,
            )

        if provider == "local":
            return cls(
                provider_name="local",
                model_name=_resolve_env(dotenv, "LOCAL_MODEL_NAME", default="llama3"),
                base_url=_resolve_env(dotenv, "LOCAL_MODEL_URL", default="http://localhost:11434"),
                api_key=None,
            )

        return cls(
            provider_name="openai",
            model_name=_resolve_env(dotenv, "OPENAI_MODEL", default="gpt-4o"),
            base_url=_resolve_env(dotenv, "OPENAI_BASE_URL", default="https://api.openai.com/v1"),
            api_key=_resolve_env(dotenv, "OPENAI_API_KEY") or None,
        )

    @classmethod
    def all_configured_from_env(cls, primary_provider: Optional[str] = None) -> List["ProviderConfig"]:
        """Return ordered list of configured/usable providers starting with the primary."""
        dotenv = _load_dotenv_dict()
        primary = (primary_provider or _resolve_env(dotenv, "LLM_PROVIDER", default="openai")).lower()
        order: List[str] = [primary]
        for cand in ("openai", "gemini", "anthropic", "local"):
            if cand not in order:
                order.append(cand)

        configs: List[ProviderConfig] = []
        for name in order:
            cfg = cls.from_env(provider_override=name)
            if name == "local":
                local_model = _resolve_env(dotenv, "LOCAL_MODEL_NAME")
                if local_model:
                    configs.append(cfg)
            elif cfg.api_key:
                configs.append(cfg)
        return configs

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize configuration with secrets masked."""
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
            "api_key_preview": "[REDACTED_SECRET]" if self.api_key else None,
            "allow_audio_upload": self.allow_audio_upload,
            "allow_project_file_upload": self.allow_project_file_upload,
        }


@dataclass
class PromptDisclosureEnvelope:
    """Audit record showing exactly what data leaves the machine for a prompt."""

    user_prompt: str
    disclosed_fields: List[str] = field(default_factory=list)
    prompt_text: str = ""
    audio_or_project_files_attached: bool = False


def _strip_json_fences(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return cleaned.strip()


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _normalize_note(note: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(note, dict):
        return None
    try:
        pitch = int(round(float(note.get("pitch", 60))))
        time_bars = float(note.get("time_bars", 0.0))
        length_bars = float(note.get("length_bars", 0.25))
        velocity = float(note.get("velocity", 0.8))
    except (TypeError, ValueError):
        return None
    if pitch < 21 or pitch > 108:
        pitch = max(21, min(108, pitch))
    time_bars = max(0.0, min(32.0, round(time_bars, 4)))
    length_bars = max(0.03125, min(8.0, round(length_bars, 4)))
    velocity = round(_clamp(velocity, 0.1, 1.0), 3)
    out: Dict[str, Any] = {
        "pitch": pitch,
        "time_bars": time_bars,
        "length_bars": length_bars,
        "velocity": velocity,
    }
    if note.get("porta") is True:
        out["porta"] = True
    return out


def normalize_llm_plan(
    raw: Dict[str, Any],
    *,
    plan_source: str = "ai_api",
    provider_name: str = "",
    model_name: str = "",
    api_error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Sanitize and normalize an LLM or CreativeBeatEngine JSON plan into a consistent schema."""
    if not isinstance(raw, dict):
        return None

    intent_type = str(raw.get("intent_type") or "full_production").strip().lower()
    if intent_type not in ("full_production", "edit", "chat_only"):
        intent_type = "full_production"

    plan: Dict[str, Any] = {
        "ai_response": str(raw.get("ai_response") or "").strip(),
        "intent_type": intent_type,
        "plan_source": plan_source,
        "provider": provider_name,
        "model": model_name,
    }
    if api_error:
        plan["api_error"] = redact_secrets(api_error)

    if intent_type == "chat_only":
        return plan

    if raw.get("tempo_bpm") is not None:
        try:
            plan["tempo_bpm"] = round(_clamp(float(raw["tempo_bpm"]), 40.0, 240.0), 2)
        except (TypeError, ValueError):
            pass

    for key in ("genre", "genre_label", "mood", "key", "scale"):
        if raw.get(key):
            plan[key] = str(raw[key]).strip()

    if raw.get("swing") is not None:
        try:
            plan["swing"] = round(_clamp(float(raw["swing"]), 0.0, 0.65), 3)
        except (TypeError, ValueError):
            plan["swing"] = 0.0

    if isinstance(raw.get("chord_progression"), list):
        plan["chord_progression"] = [str(c) for c in raw["chord_progression"] if c][:16]

    sections: List[Dict[str, Any]] = []
    for s in (raw.get("sections") or []):
        if isinstance(s, dict) and s.get("name"):
            bars = max(1, min(64, int(float(s.get("bars", 4) or 4))))
            sec_entry: Dict[str, Any] = {"name": str(s["name"]).strip()[:24], "bars": bars}
            if s.get("mode"):
                sec_entry["mode"] = str(s["mode"]).strip()
            if isinstance(s.get("roles"), list):
                sec_roles = [str(r).strip().lower() for r in s["roles"] if str(r).strip()]
                if sec_roles:
                    sec_entry["roles"] = sec_roles
            sections.append(sec_entry)
    plan["sections"] = sections

    drum_channels: List[Dict[str, Any]] = []
    for dc in (raw.get("drum_channels") or []):
        if not isinstance(dc, dict):
            continue
        try:
            ch = max(0, min(15, int(dc.get("channel", 0))))
            length = max(8, min(64, int(dc.get("length", 16) or 16)))
            steps = sorted({int(st) for st in (dc.get("steps") or []) if 0 <= int(st) < length})
        except (TypeError, ValueError):
            continue
        entry: Dict[str, Any] = {
            "channel": ch,
            "name": str(dc.get("name") or f"Drum {ch}").strip()[:32],
            "steps": steps,
            "length": length,
        }
        if dc.get("velocity") is not None:
            try:
                entry["velocity"] = round(_clamp(float(dc["velocity"]), 0.1, 1.0), 3)
            except (TypeError, ValueError):
                pass
        drum_channels.append(entry)
    plan["drum_channels"] = drum_channels

    normalized_tracks: List[Dict[str, Any]] = []
    for idx, trk in enumerate(raw.get("tracks") or []):
        if not isinstance(trk, dict):
            continue
        role = str(trk.get("role") or ("lead" if idx == 0 else f"track_{idx}")).strip().lower()
        inst = str(trk.get("instrument_name") or raw.get("instrument_name") or "FLEX").strip()
        raw_fbs = [str(fb).strip() for fb in (trk.get("fallbacks") or []) if str(fb).strip()]
        if not raw_fbs:
            raw_fbs = list(_GENERATOR_FALLBACKS.get(inst, ["FLEX", "Sytrus", "3x Osc"]))
        notes = [n for n in (_normalize_note(x) for x in (trk.get("notes") or [])) if n is not None]
        notes.sort(key=lambda n: (n["time_bars"], n["pitch"]))
        if not notes:
            continue
        trk_entry: Dict[str, Any] = {
            "role": role,
            "instrument_name": inst,
            "fallbacks": raw_fbs[:4],
            "notes": notes,
        }
        if trk.get("preset_hint"):
            trk_entry["preset_hint"] = str(trk["preset_hint"]).strip()[:48]
        raw_gp = trk.get("generator_params")
        if isinstance(raw_gp, dict):
            clean_gp: Dict[str, float] = {}
            for gk, gv in raw_gp.items():
                try:
                    clean_gp[str(gk).strip()[:32]] = round(_clamp(float(gv), 0.0, 1.0), 3)
                except (TypeError, ValueError):
                    pass
            if clean_gp:
                trk_entry["generator_params"] = clean_gp
        normalized_tracks.append(trk_entry)

    # Backwards-compatibility if AI omitted `tracks` and only sent `melody_notes`
    raw_melody = [n for n in (_normalize_note(x) for x in (raw.get("melody_notes") or [])) if n is not None]
    raw_melody.sort(key=lambda n: (n["time_bars"], n["pitch"]))
    if not normalized_tracks and raw_melody:
        inst = str(raw.get("instrument_name") or "FL Keys").strip()
        normalized_tracks.append(
            {
                "role": "lead",
                "instrument_name": inst,
                "fallbacks": list(_GENERATOR_FALLBACKS.get(inst, ["FLEX", "Sytrus", "3x Osc"])),
                "notes": raw_melody,
            }
        )

    # Unify loop bar span across tracks so separate FL patterns stay harmonically locked in phase
    if normalized_tracks:
        max_end = max(max(n["time_bars"] + n["length_bars"] for n in t["notes"]) for t in normalized_tracks)
        target_bars = 8 if max_end > 4.25 else 4
        for t in normalized_tracks:
            t_notes = t["notes"]
            t_end = max(n["time_bars"] + n["length_bars"] for n in t_notes)
            if t_end <= 2.05 and target_bars >= 4:
                span = 2.0 if t_end > 1.05 else 1.0
                extended = list(t_notes)
                rep = 1
                while rep * span < target_bars - 0.05:
                    offset = rep * span
                    for n in t_notes:
                        if n["time_bars"] + offset >= target_bars:
                            continue
                        new_n = dict(n)
                        new_n["time_bars"] = round(n["time_bars"] + offset, 4)
                        # Subtle melodic turnaround in second half so loop feels cohesive & alive
                        if t["role"] in ("lead", "melody") and rep % 2 == 1 and n["time_bars"] >= (span * 0.5):
                            new_n["velocity"] = round(_clamp(float(n.get("velocity", 0.85)) * 1.04, 0.2, 1.0), 3)
                        extended.append(new_n)
                    rep += 1
                extended.sort(key=lambda x: (x["time_bars"], x["pitch"]))
                t["notes"] = extended

    plan["tracks"] = normalized_tracks

    # Keep legacy single-track keys populated from primary lead/melody track
    primary_lead = next((t for t in normalized_tracks if t["role"] in ("lead", "melody")), None)
    if primary_lead is None and normalized_tracks:
        primary_lead = normalized_tracks[-1]
    plan["instrument_name"] = str(
        raw.get("instrument_name")
        or (primary_lead["instrument_name"] if primary_lead else "FL Keys")
    ).strip()
    plan["melody_notes"] = raw_melody or (list(primary_lead["notes"]) if primary_lead else [])

    ch_mix: List[Dict[str, Any]] = []
    for cm in (raw.get("channel_mix") or []):
        if not isinstance(cm, dict) or cm.get("channel") is None:
            continue
        try:
            entry_cm: Dict[str, Any] = {"channel": max(0, min(63, int(cm["channel"])))}
        except (TypeError, ValueError):
            continue
        if cm.get("volume") is not None:
            try:
                entry_cm["volume"] = round(_clamp(float(cm["volume"]), 0.0, 1.0), 3)
            except (TypeError, ValueError):
                pass
        if cm.get("pan") is not None:
            try:
                entry_cm["pan"] = round(_clamp(float(cm["pan"]), -1.0, 1.0), 3)
            except (TypeError, ValueError):
                pass
        if len(entry_cm) > 1:
            ch_mix.append(entry_cm)
    plan["channel_mix"] = ch_mix

    # FX plan & params (fill sensible defaults per present role if LLM omitted fx_plan)
    raw_fx = raw.get("fx_plan") if isinstance(raw.get("fx_plan"), dict) else {}
    fx_plan: Dict[str, List[str]] = {}
    needed_roles = {t["role"] for t in normalized_tracks}
    if drum_channels:
        needed_roles.add("drums")
    needed_roles.add("master")
    for role in needed_roles:
        custom = raw_fx.get(role)
        if isinstance(custom, list) and custom:
            fx_plan[role] = [str(p).strip() for p in custom if str(p).strip()][:4]
        elif role in _DEFAULT_FX_CHAINS:
            fx_plan[role] = list(_DEFAULT_FX_CHAINS[role])
    plan["fx_plan"] = fx_plan

    raw_fx_params = raw.get("fx_params") if isinstance(raw.get("fx_params"), dict) else {}
    fx_params: Dict[str, Dict[str, float]] = {}
    for role, pdict in raw_fx_params.items():
        if isinstance(pdict, dict):
            clean_p: Dict[str, float] = {}
            for pname, pval in pdict.items():
                try:
                    k_clean = str(pname).strip()
                    v_clean = round(_clamp(float(pval), 0.0, 1.0), 3)
                    k_low = k_clean.lower()
                    if k_low in ("ceiling", "ceil"):
                        if v_clean < 0.44:
                            v_clean = 0.47
                        elif 0.80 <= v_clean <= 1.0:
                            v_clean = round(0.45 + (v_clean - 0.80) * 0.25, 3)
                        elif v_clean > 0.56:
                            v_clean = 0.48
                    elif k_low == "clipper_thresh" and v_clean < 0.55:
                        v_clean = 0.80
                    clean_p[k_clean] = v_clean
                except (TypeError, ValueError):
                    pass
            if clean_p:
                fx_params[str(role).strip().lower()] = clean_p
    plan["fx_params"] = fx_params

    raw_mix = raw.get("mix") if isinstance(raw.get("mix"), dict) else {}
    mood = str(plan.get("mood") or "dark").lower()
    is_agg = mood in ("dark", "aggressive", "epic") or str(plan.get("genre", "")).lower() in ("phonk", "trap", "drill", "techno", "melodic_techno")
    plan["mix"] = {
        "enabled": bool(raw_mix.get("enabled", True)),
        "target_ceiling_db": float(raw_mix.get("target_ceiling_db", -1.0)),
        "loud": bool(raw_mix.get("loud", is_agg)),
        "quiet": bool(raw_mix.get("quiet", False)),
        "wide_stereo": bool(raw_mix.get("wide_stereo", True)),
        "punchy_drums": bool(raw_mix.get("punchy_drums", True)),
        "style": str(raw_mix.get("style") or ("aggressive" if is_agg else "clean")).strip(),
        "mood": mood,
        "genre": str(plan.get("genre") or "").lower(),
    }

    if raw.get("mixer_volume") is not None:
        try:
            plan["mixer_volume"] = round(_clamp(float(raw["mixer_volume"]), 0.0, 1.0), 3)
        except (TypeError, ValueError):
            pass

    play_state = raw.get("play_state")
    plan["play_state"] = str(play_state).lower() if play_state in ("play", "stop") else None
    return plan


_ENHARMONIC_PC = {
    "db": 1, "c#": 1, "eb": 3, "d#": 3, "gb": 6, "f#": 6, "ab": 8, "g#": 8, "bb": 10, "a#": 10,
}

_CREATIVE_KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "Bb", "B"]
_CREATIVE_SCALES = [
    "dorian", "phrygian", "harmonic_minor", "natural_minor", "lydian", "mixolydian", "major",
]
_CREATIVE_CHORD_FEELS = [
    "syncopated neo-soul m9/maj7 stabs with broken upper-voice arpeggios",
    "cinematic suspended sus2/add9 swells with passing diminished transitions",
    "bouncy minor 11th & secondary-dominant turnarounds every bar 4",
    "hypnotic 8th-note rhythmic chord ostinato with octave voicing shifts",
    "warm jazzy chord inversions moving stepwise in bars 2 and 4",
]
_CREATIVE_BASS_GROOVES = [
    "syncopated 808 bounce with 16th ghost pickups and octave glide slides (porta: true)",
    "rolling Reese/analog bassline locking kick transients with 5th approach notes",
    "pocket sub groove leaving breathing room on beat 2 and snapping into bar 4 turnarounds",
    "driving off-beat octave-jumping bassline with subtle chromatic passing steps",
]
_CREATIVE_LEAD_STYLES = [
    "call-and-response top hook (bars 1 & 3 statement, bars 2 & 4 lyrical reply with 16th ornaments)",
    "counter-melody pluck arpeggios weaving around chord spaces with triplet bursts",
    "expressive syncopated motif climbing into the upper octave on bar 3",
    "sparse haunting bell/lead hook layered with delicate echoes in beat 3-4",
]
_CREATIVE_INSTRUMENT_PALETTES = [
    ("FLEX", "Transistor Bass", "Sytrus"),
    ("Harmless", "3x Osc", "Sawer"),
    ("FL Keys", "BooBass", "Harmor"),
    ("Sakura", "FLEX", "Plucked!"),
    ("PoiZone", "3x Osc", "GMS"),
    ("SimSynth", "BooBass", "Harmless"),
    ("FLEX", "3x Osc", "Sakura"),
    ("GMS", "Transistor Bass", "Harmor"),
]
_CREATIVE_FX_SIGNATURES = [
    "Multiband compressor glue + warm saturation + air EQ shelf",
    "Shimmer hall reverb on chords + ping-pong delay throws on lead + clipper punch",
    "Crisp stereo chorus width on mids + mono sub focus + tight transient limiter",
    "Dark vintage low-pass tilt + tape-style feedback delay + aggressive master clipper",
]


def _resolve_scale_pcs(key_str: Optional[str], scale_str: Optional[str]) -> List[int]:
    k_clean = str(key_str or "C").strip().split()[0]
    k_low = k_clean.lower()
    if k_low in _ENHARMONIC_PC:
        root_pc = _ENHARMONIC_PC[k_low]
    else:
        up = k_clean[:1].upper() + k_clean[1:2]
        root_pc = NOTE_NAMES.index(up) if up in NOTE_NAMES else 0
    s_clean = str(scale_str or "natural_minor").strip().lower().replace(" ", "_")
    intervals = SCALES.get(s_clean)
    if intervals is None:
        if "minor_pent" in s_clean:
            intervals = [0, 3, 5, 7, 10]
        elif "harm" in s_clean:
            intervals = SCALES["harmonic_minor"]
        elif "dor" in s_clean:
            intervals = SCALES["dorian"]
        elif "phry" in s_clean:
            intervals = SCALES["phrygian"]
        elif "maj" in s_clean:
            intervals = SCALES["major"]
        else:
            intervals = SCALES["natural_minor"]
    return [(root_pc + iv) % 12 for iv in intervals]


def _snap_pitch_to_scale(pitch: int, scale_pcs: List[int], lo: int = 24, hi: int = 96) -> int:
    best = max(lo, min(hi, int(pitch)))
    best_dist = 99
    for delta in range(-4, 5):
        cand = pitch + delta
        if lo <= cand <= hi and (cand % 12) in scale_pcs and abs(delta) < best_dist:
            best = cand
            best_dist = abs(delta)
    return best


def _default_generator_params(role: str, mood: str) -> Dict[str, float]:
    is_dark = mood in ("dark", "aggressive", "lofi", "sad", "chill")
    r = role.lower()
    if r in ("bass", "808"):
        return {
            "cutoff": 0.38 if is_dark else 0.48,
            "resonance": 0.28,
            "attack": 0.06,
            "release": 0.32,
            "drive": 0.42 if mood in ("aggressive", "dark") else 0.25,
            "sub": 0.80,
        }
    if r in ("chords", "pad"):
        return {
            "cutoff": 0.48 if is_dark else 0.64,
            "resonance": 0.22,
            "attack": 0.24 if r == "pad" else 0.16,
            "release": 0.60,
            "detune": 0.38,
            "reverb": 0.34,
            "warmth": 0.58 if is_dark else 0.45,
        }
    return {
        "cutoff": 0.62 if is_dark else 0.74,
        "resonance": 0.32,
        "attack": 0.10,
        "release": 0.44,
        "detune": 0.36,
        "reverb": 0.26,
        "delay": 0.24,
    }


def build_creative_variation_brief(
    user_prompt: str,
    recent_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate a non-repeating creative direction seed using SystemRandom."""
    rng = random.SystemRandom()
    hist = list(recent_history or [])[-4:]
    used_keys = {str(h.get("key") or "").strip().upper() for h in hist if h.get("key")}
    used_scales = {str(h.get("scale") or "").strip().lower() for h in hist if h.get("scale")}
    used_insts = set()
    for h in hist:
        if h.get("instrument_name"):
            used_insts.add(str(h["instrument_name"]).strip().lower())
        for ins in (h.get("instruments") or []):
            used_insts.add(str(ins).strip().lower())

    avail_keys = [k for k in _CREATIVE_KEYS if k.upper() not in used_keys] or list(_CREATIVE_KEYS)
    avail_scales = [s for s in _CREATIVE_SCALES if s not in used_scales] or list(_CREATIVE_SCALES)
    avail_palettes = [
        p for p in _CREATIVE_INSTRUMENT_PALETTES
        if sum(1 for x in p if x.lower() in used_insts) <= 1
    ] or list(_CREATIVE_INSTRUMENT_PALETTES)

    key_pick = rng.choice(avail_keys)
    scale_pick = rng.choice(avail_scales)
    palette = list(rng.choice(avail_palettes))

    low_p = user_prompt.lower()
    if any(w in low_p for w in ("piyano", "piano", "tuş", "tuslu")):
        palette[0] = "FL Keys"
    if any(w in low_p for w in ("gitar", "guitar", "akustik", "saz", "koto")):
        palette[2] = "Sakura"

    return (
        "CREATIVE DIRECTION SEED (Apply unless the user explicitly requested a different key/BPM/instrument):\n"
        f"- Suggested Key & Scale: {key_pick} {scale_pick} (AVOID A minor if used recently)\n"
        f"- Instrument Palette (use different presets & generator_params): Chords='{palette[0]}', Bass='{palette[1]}', Lead='{palette[2]}'\n"
        f"- Harmony Feel: {rng.choice(_CREATIVE_CHORD_FEELS)}\n"
        f"- Bass Groove: {rng.choice(_CREATIVE_BASS_GROOVES)}\n"
        f"- Lead Motif: {rng.choice(_CREATIVE_LEAD_STYLES)}\n"
        f"- Mix & FX Character: {rng.choice(_CREATIVE_FX_SIGNATURES)}\n"
        "- IMPORTANT: Include 'preset_hint' and 'generator_params' on every track, and write rich 4-bar rhythms (12-28+ lead/chord notes, 8-16+ bass notes)."
    )


def _has_note_near(notes: List[Dict[str, Any]], time_bars: float, tol: float = 0.06) -> bool:
    return any(abs(float(n.get("time_bars", 0.0)) - time_bars) <= tol for n in notes)


def enrich_sparse_ai_tracks(
    plan: Optional[Dict[str, Any]],
    *,
    is_song_reference: bool = False,
) -> Optional[Dict[str, Any]]:
    """Expand sparse 4-bar LLM drafts (>2 bars long but <=7 notes) into full musical grooves."""
    if not isinstance(plan, dict) or plan.get("intent_type") == "chat_only":
        return plan

    mood = str(plan.get("mood") or "dark").lower()
    genre = str(plan.get("genre") or "").lower()
    tracks = plan.get("tracks") or []
    scale_pcs = _resolve_scale_pcs(plan.get("key"), plan.get("scale"))
    enriched_any = False

    def _next_scale_step(pitch: int, step_dir: int, lo: int, hi: int) -> int:
        cand = pitch + (2 if step_dir >= 0 else -2)
        for delta in (step_dir, step_dir * 2, step_dir * 3, -step_dir):
            probe = pitch + delta
            if lo <= probe <= hi and (probe % 12) in scale_pcs:
                return probe
        return _snap_pitch_to_scale(cand, scale_pcs, lo=lo, hi=hi)

    for trk in tracks:
        if not isinstance(trk, dict):
            continue
        role = str(trk.get("role") or "lead").strip().lower()
        notes = list(trk.get("notes") or [])
        if not notes:
            continue
        if not trk.get("generator_params"):
            trk["generator_params"] = _default_generator_params(role, mood)

        if is_song_reference:
            continue

        max_end = max(float(n["time_bars"]) + float(n["length_bars"]) for n in notes)
        if max_end < 2.0:
            # Preserve compact (<2 bar) unit-test fixtures or single-bar loops untouched
            continue
        bars_count = max(4, min(8, int(round(max(4.0, max_end)))))

        if role in ("bass", "808") and len(notes) <= 6:
            added: List[Dict[str, Any]] = []
            glide_ok = genre in ("trap", "drill", "phonk", "")
            for bar in range(bars_count):
                bar_notes = [n for n in notes if bar <= float(n["time_bars"]) < bar + 1.0]
                anchor = bar_notes[0] if bar_notes else max(
                    (n for n in notes if float(n["time_bars"]) <= bar + 0.01),
                    key=lambda x: float(x["time_bars"]),
                    default=notes[0],
                )
                root_p = max(24, min(48, int(anchor["pitch"])))
                while root_p > 43:
                    root_p -= 12
                fifth_p = _snap_pitch_to_scale(root_p + 7, scale_pcs, lo=28, hi=54)
                oct_p = min(56, root_p + 12)
                groove_offsets = (
                    [(0.375, root_p, 0.20, 0.84, False), (0.625, fifth_p, 0.18, 0.80, False), (0.875, oct_p, 0.125, 0.86, glide_ok)]
                    if bar % 2 == 1
                    else [(0.375, root_p, 0.22, 0.85, False), (0.75, fifth_p if bar == 0 else root_p, 0.20, 0.82, False)]
                )
                for off, p_val, ln, vel, porta in groove_offsets:
                    t_abs = round(bar + off, 4)
                    if not _has_note_near(notes + added, t_abs):
                        entry: Dict[str, Any] = {
                            "pitch": int(p_val),
                            "time_bars": t_abs,
                            "length_bars": ln,
                            "velocity": vel,
                        }
                        if porta:
                            entry["porta"] = True
                        added.append(entry)
            if added:
                notes.extend(added)
                notes.sort(key=lambda x: (x["time_bars"], x["pitch"]))
                trk["notes"] = notes
                enriched_any = True

        elif role in ("lead", "melody", "arp") and len(notes) <= 7:
            added = []
            for bar in range(bars_count):
                bar_notes = [n for n in notes if bar <= float(n["time_bars"]) < bar + 1.0]
                anchor = bar_notes[0] if bar_notes else max(
                    (n for n in notes if float(n["time_bars"]) <= bar + 0.01),
                    key=lambda x: float(x["time_bars"]),
                    default=notes[0],
                )
                base_p = max(58, min(86, int(anchor["pitch"])))
                p_up = _next_scale_step(base_p, 2, 60, 90)
                p_up2 = _next_scale_step(p_up, 2, 60, 92)
                p_dn = _next_scale_step(base_p, -2, 56, 86)
                phrase = (
                    [(0.0, base_p, 0.22, 0.87), (0.25, p_up, 0.20, 0.84), (0.5, p_up2, 0.24, 0.90), (0.75, p_up, 0.22, 0.83)]
                    if bar % 2 == 0
                    else [(0.125, p_up, 0.20, 0.86), (0.375, base_p, 0.22, 0.84), (0.625, p_dn, 0.20, 0.80), (0.875, _next_scale_step(p_up, 1, 60, 90), 0.125, 0.88)]
                )
                for off, p_val, ln, vel in phrase:
                    t_abs = round(bar + off, 4)
                    if not _has_note_near(notes + added, t_abs, tol=0.05):
                        added.append({
                            "pitch": int(p_val),
                            "time_bars": t_abs,
                            "length_bars": ln,
                            "velocity": vel,
                        })
            if added:
                notes.extend(added)
                notes.sort(key=lambda x: (x["time_bars"], x["pitch"]))
                trk["notes"] = notes
                enriched_any = True

        elif role in ("chords", "pad") and len(notes) <= 8:
            added = []
            for bar in range(bars_count):
                bar_notes = [n for n in notes if bar <= float(n["time_bars"]) < bar + 1.0]
                if not bar_notes:
                    anchor = notes[bar % len(notes)]
                    t_base = float(bar)
                    root_p = _snap_pitch_to_scale(int(anchor["pitch"]), scale_pcs, lo=48, hi=72)
                    added.append({"pitch": root_p, "time_bars": t_base, "length_bars": 0.45, "velocity": 0.74})
                else:
                    anchor = min(bar_notes, key=lambda x: x["time_bars"])
                    t_base = float(anchor["time_bars"])
                    root_p = int(anchor["pitch"])
                existing_at_t = {int(n["pitch"]) for n in (notes + added) if abs(float(n["time_bars"]) - t_base) <= 0.05}
                third_p = _next_scale_step(_next_scale_step(root_p, 1, 45, 76), 1, 45, 78)
                fifth_p = _next_scale_step(_next_scale_step(third_p, 1, 48, 82), 1, 48, 84)
                for cp in (third_p, fifth_p):
                    if cp not in existing_at_t:
                        added.append({"pitch": int(cp), "time_bars": t_base, "length_bars": 0.45, "velocity": 0.72})
                echo_t = round(t_base + 0.5, 4)
                if not _has_note_near(notes + added, echo_t, tol=0.06):
                    for cp in (root_p, fifth_p):
                        added.append({"pitch": int(cp), "time_bars": echo_t, "length_bars": 0.42, "velocity": 0.68})
            if added:
                notes.extend(added)
                notes.sort(key=lambda x: (x["time_bars"], x["pitch"]))
                trk["notes"] = notes
                enriched_any = True

    if enriched_any:
        plan["sparse_enriched"] = True
        primary_lead = next((t for t in tracks if t.get("role") in ("lead", "melody")), None)
        if primary_lead and len(primary_lead.get("notes") or []) > len(plan.get("melody_notes") or []):
            plan["melody_notes"] = list(primary_lead["notes"])
    return plan


def _looks_like_simple_greeting_or_question(prompt: str) -> bool:
    clean = prompt.strip().lower()
    if len(clean) <= 32 and any(
        clean == g or clean.startswith(g + " ")
        for g in ("selam", "merhaba", "naber", "slm", "hi", "hello", "hey", "teşekkür", "tesekkur", "sağol", "sagol")
    ):
        return True
    if "?" in clean and not any(
        w in clean for w in ("yap", "oluştur", "olustur", "yaz", "üret", "uret", "create", "make", "generate", "beat")
    ):
        return True
    return False


def _looks_like_creative_production_request(prompt: str) -> bool:
    clean = prompt.lower()
    creative_kw = (
        "beat", "şarkı", "sarki", "parça", "parca", "altyapı", "altyapi",
        "phonk", "trap", "drill", "house", "techno", "lofi", "lo-fi", "boom bap",
        "synthwave", "afrobeat", "ambient", "rnb", "melodi", "melody", "piyano",
        "piano", "gitar", "guitar", "808", "mix", "master", "plugin", "fl keys",
        "flex", "sytrus", "sakura", "üret", "uret", "bestele", "compose",
        "havalı", "havali", "agresif", "üzgün", "uzgun", "karanlık", "karanlik",
    )
    return any(kw in clean for kw in creative_kw)


def _format_api_chat_messages(
    conversation_history: Optional[List[Dict[str, str]]],
    final_user_text: str,
    assistant_role: str = "assistant",
    max_turns: int = 12,
) -> List[Tuple[str, str]]:
    """Normalize per-chat turns into strictly alternating user/assistant pairs ending in user."""
    normalized: List[Tuple[str, str]] = []
    for turn in (conversation_history or [])[-max_turns:]:
        if not isinstance(turn, dict):
            continue
        raw_role = str(turn.get("role") or "").strip().lower()
        text = str(turn.get("text") or turn.get("content") or "").strip()
        if not text or raw_role not in ("user", "assistant", "model"):
            continue
        if text.startswith("Starting plan for:"):
            continue
        mapped_role = "user" if raw_role == "user" else assistant_role
        clipped = text[:1200]
        if normalized and normalized[-1][0] == mapped_role:
            normalized[-1] = (mapped_role, f"{normalized[-1][1]}\n{clipped}")
        else:
            normalized.append((mapped_role, clipped))

    while normalized and normalized[0][0] != "user":
        normalized.pop(0)

    trailing_user = ""
    if normalized and normalized[-1][0] == "user":
        trailing_user = normalized.pop()[1]

    combined_final = (
        f"[Earlier uncompleted turn in this chat]: {trailing_user}\n\n{final_user_text}"
        if trailing_user
        else final_user_text
    )
    normalized.append(("user", combined_final))
    return normalized


class ModelProviderAdapter:
    """Privacy-safe wrapper around AI model APIs (OpenAI, Gemini, Anthropic, Local)."""

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig.from_env()
        self._explicit_config = config is not None
        self._creative_engine = CreativeBeatEngine()

    def is_local_provider(self) -> bool:
        return self.config.provider_name == "local"

    def build_context_prompt(
        self,
        user_prompt: str,
        project_context: Optional[Dict[str, Any]] = None,
        recent_history: Optional[List[Dict[str, Any]]] = None,
        user_preferences: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> PromptDisclosureEnvelope:
        """Build prompt containing ONLY user text + text/numeric FL Studio state + per-chat memory."""
        disclosed: List[str] = ["user_prompt"]
        parts: List[str] = [f"User Request: {user_prompt}"]

        if project_context:
            parts.append("\nLive FL Studio Session State:")
            if "bpm" in project_context:
                parts.append(f"- Current Tempo: {project_context['bpm']} BPM")
                disclosed.append("project_context.bpm")
            if "playing" in project_context:
                parts.append(f"- Transport Playing: {project_context['playing']}")
                disclosed.append("project_context.playing")
            if "channel_count" in project_context:
                parts.append(f"- Channel Count: {project_context['channel_count']}")
                disclosed.append("project_context.channel_count")
            if "channels" in project_context and isinstance(project_context["channels"], list):
                ch_names = [str(c.get("name", "?")) for c in project_context["channels"][:24] if isinstance(c, dict)]
                parts.append(f"- Existing Channels: {', '.join(ch_names) if ch_names else '(none)'}")
                disclosed.append("project_context.channel_names")
            if "mixer_tracks" in project_context and isinstance(project_context["mixer_tracks"], list):
                mx_names = [
                    f"T{m.get('index', m.get('i', '?'))}:{m.get('name', '')}"
                    for m in project_context["mixer_tracks"][:16]
                    if isinstance(m, dict) and m.get("name")
                ]
                if mx_names:
                    parts.append(f"- Named Mixer Tracks: {', '.join(mx_names)}")
                    disclosed.append("project_context.mixer_tracks")
            if "patterns" in project_context and isinstance(project_context["patterns"], list):
                pat_names = [str(p.get("name", "?")) for p in project_context["patterns"][:12] if isinstance(p, dict)]
                if pat_names:
                    parts.append(f"- Existing Patterns: {', '.join(pat_names)}")
                    disclosed.append("project_context.patterns")

        if recent_history:
            parts.append("\nRecent Session History (DO NOT repeat identical BPM/key/chords/instruments unless asked):")
            for item in recent_history[-4:]:
                p_txt = str(item.get("prompt", ""))[:100]
                meta = ", ".join(
                    f"{k}={item[k]}"
                    for k in ("genre", "tempo_bpm", "key", "scale", "instrument_name", "instruments", "chord_progression")
                    if item.get(k)
                )
                parts.append(f"- Prompt: {p_txt!r}" + (f" -> {meta}" if meta else ""))
            disclosed.append("recent_history")

        clean_turns = [
            t for t in (conversation_history or [])[-8:]
            if isinstance(t, dict) and str(t.get("text") or t.get("content") or "").strip()
        ]
        if clean_turns:
            parts.append("\nActive Chat Conversation Memory (recall decisions, requests, and context within THIS chat only):")
            for turn in clean_turns:
                r_label = str(turn.get("role") or "user").strip().lower()
                t_txt = str(turn.get("text") or turn.get("content") or "").strip().replace("\n", " ")[:240]
                parts.append(f"- [{r_label}]: {t_txt}")
            disclosed.append("conversation_history")

        return PromptDisclosureEnvelope(
            user_prompt=user_prompt,
            disclosed_fields=disclosed,
            prompt_text="\n".join(parts),
            audio_or_project_files_attached=False,
        )

    def _call_provider_api(
        self,
        cfg: ProviderConfig,
        system_prompt: str,
        user_text: str,
        *,
        temperature: Optional[float] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Send JSON-mode completion request to OpenAI, Gemini, Anthropic, or Local provider."""
        provider = cfg.provider_name.lower()

        if provider == "gemini":
            if not cfg.api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            base = cfg.base_url.rstrip("/")
            url = f"{base}/models/{cfg.model_name}:generateContent?key={cfg.api_key}"
            temp_val = float(temperature) if temperature is not None else 0.9
            gem_turns = _format_api_chat_messages(conversation_history, user_text, assistant_role="model")
            body = json.dumps(
                {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": role, "parts": [{"text": txt}]} for role, txt in gem_turns],
                    "generationConfig": {
                        "temperature": temp_val,
                        "maxOutputTokens": 8192,
                        "responseMimeType": "application/json",
                    },
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates") or []
            parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
            return "".join(str(p.get("text", "")) for p in parts).strip()

        if provider == "anthropic":
            if not cfg.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not configured")
            url = f"{cfg.base_url.rstrip('/')}/v1/messages"
            temp_val = float(temperature) if temperature is not None else 0.88
            ant_turns = _format_api_chat_messages(conversation_history, user_text, assistant_role="assistant")
            body = json.dumps(
                {
                    "model": cfg.model_name,
                    "max_tokens": 3000,
                    "temperature": temp_val,
                    "system": system_prompt,
                    "messages": [{"role": role, "content": txt} for role, txt in ant_turns],
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "x-api-key": cfg.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            blocks = data.get("content") or []
            return "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text").strip()

        if provider == "local":
            base = cfg.base_url.rstrip("/")
            url = f"{base}/v1/chat/completions"
            temp_val = float(temperature) if temperature is not None else 0.85
            loc_turns = _format_api_chat_messages(conversation_history, user_text, assistant_role="assistant")
            body = json.dumps(
                {
                    "model": cfg.model_name or "llama3",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        *[{"role": role, "content": txt} for role, txt in loc_turns],
                    ],
                    "temperature": temp_val,
                    "response_format": {"type": "json_object"},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return str(data["choices"][0]["message"]["content"]).strip()

        # Default: OpenAI / OpenAI-compatible
        if not cfg.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        url = f"{cfg.base_url.rstrip('/')}/chat/completions"
        temp_val = float(temperature) if temperature is not None else 0.88
        oa_turns = _format_api_chat_messages(conversation_history, user_text, assistant_role="assistant")
        body = json.dumps(
            {
                "model": cfg.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    *[{"role": role, "content": txt} for role, txt in oa_turns],
                ],
                "temperature": temp_val,
                "max_tokens": 3000,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"]).strip()

    def _call_with_retry(
        self,
        cfg: ProviderConfig,
        system_prompt: str,
        user_text: str,
        *,
        temperature: Optional[float] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Invoke a provider API with a single quick retry on transient 429/503."""
        last_err: Optional[str] = None
        for attempt in range(2):
            try:
                raw_text = self._call_provider_api(
                    cfg,
                    system_prompt,
                    user_text,
                    temperature=temperature,
                    conversation_history=conversation_history,
                )
                return raw_text, None
            except urllib.error.HTTPError as exc:
                err_body = ""
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                safe_detail = redact_secrets(f"HTTP {exc.code}: {err_body or exc.reason}")
                last_err = safe_detail
                err_low = err_body.lower()
                is_quota = any(tok in err_low for tok in ("insufficient_quota", "limit: 0", "quota exceeded", "freetier"))
                if exc.code in (429, 502, 503) and not is_quota and attempt == 0:
                    time.sleep(0.6)
                    continue
                break
            except Exception as exc:
                last_err = redact_secrets(str(exc))
                break
        return None, last_err

    def _fallback_plan(
        self,
        user_prompt: str,
        project_context: Optional[Dict[str, Any]],
        error_notes: List[str],
        recent_history: Optional[List[Dict[str, Any]]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """High-creativity procedural fallback ONLY when live AI API is unavailable or fails."""
        if _looks_like_simple_greeting_or_question(user_prompt):
            reason = f" ({'; '.join(error_notes)})" if error_notes else ""
            if recent_history and "?" in user_prompt:
                last_item = recent_history[-1]
                summary_bits = [
                    f"{last_item.get('genre', 'beat')}",
                    f"{last_item.get('tempo_bpm', '')} BPM".strip(),
                    f"{last_item.get('key', '')} {last_item.get('scale', '')}".strip(),
                ]
                reply = (
                    f"Bu sohbetteki son çalışmamız: {' / '.join(b for b in summary_bits if b)} "
                    f"(istek: \"{str(last_item.get('prompt', ''))[:80]}\")."
                )
            else:
                reply = (
                    "Selam! Hazırım, bugün nasıl bir beat veya müzik fikri üretelim? "
                    "Örnek: '130 bpm karanlık phonk beat yap' veya '120 bpm duygusal piyano ve 808 trap beat'.\n"
                    f"(Not: Canlı AI API şu an yanıt veremedi{reason}; müzik istersen gelişmiş yerel üretici motoru devreye girecek.)"
                    if error_notes
                    else "Selam! Hazırım, bugün nasıl bir beat yapalım?"
                )
            return {
                "ai_response": reply,
                "intent_type": "chat_only",
                "plan_source": "creative_fallback",
                "api_error": "; ".join(error_notes) if error_notes else None,
            }

        if not _looks_like_creative_production_request(user_prompt):
            return None

        raw_creative = self._creative_engine.generate(user_prompt, project_context)
        normalized = normalize_llm_plan(
            raw_creative,
            plan_source="creative_fallback",
            provider_name="creative_beat_engine",
            model_name="procedural_v2",
            api_error="; ".join(error_notes) if error_notes else "no_api_key",
        )
        if normalized and error_notes:
            note = f"\n[Bilgi: Canlı AI API bağlantısı başarısız oldu ({'; '.join(error_notes)}), bu nedenle yaratıcı yerel motorla özgün beste + FX + mix üretildi.]"
            normalized["ai_response"] = (normalized.get("ai_response") or "").strip() + note
        elif normalized:
            normalized["ai_response"] = (normalized.get("ai_response") or "").strip() + (
                "\n[Bilgi: API anahtarı tanımlı olmadığı için yaratıcı yerel motorla özgün beste + FX + mix üretildi.]"
            )
        return normalized

    def generate_music_plan(
        self,
        user_prompt: str,
        project_context: Optional[Dict[str, Any]] = None,
        recent_history: Optional[List[Dict[str, Any]]] = None,
        user_preferences: Optional[Dict[str, Any]] = None,
        allow_in_pytest: bool = False,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Ask the configured AI API to creatively design the beat, plugins, FX, and mix.

        Under pytest, returns None immediately unless ``allow_in_pytest=True`` so
        deterministic unit/E2E suites do not stall on external network sockets.
        """
        if "PYTEST_CURRENT_TEST" in os.environ and not allow_in_pytest:
            return None

        envelope = self.build_context_prompt(
            user_prompt=user_prompt,
            project_context=project_context,
            recent_history=recent_history,
            user_preferences=user_preferences,
            conversation_history=conversation_history,
        )

        # Refresh env configuration dynamically while honoring runtime config selection
        if self._explicit_config and (self.config.api_key or self.config.provider_name == "local"):
            candidates = [self.config]
        else:
            candidates = ProviderConfig.all_configured_from_env(primary_provider=self.config.provider_name)
            if candidates and candidates[0].provider_name == self.config.provider_name:
                if self.config.model_name:
                    candidates[0].model_name = self.config.model_name
                if self.config.base_url:
                    candidates[0].base_url = self.config.base_url
            if not candidates and self._explicit_config:
                candidates = [self.config]

        error_notes: List[str] = []
        expanded_candidates: List[ProviderConfig] = []
        seen_pairs: set[Tuple[str, str]] = set()
        for cfg in candidates:
            if cfg.provider_name != "local" and not cfg.api_key:
                continue
            pair = (cfg.provider_name, cfg.model_name)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                expanded_candidates.append(cfg)
            if cfg.provider_name == "gemini":
                for fb_model in _GEMINI_FALLBACK_MODELS:
                    fb_pair = ("gemini", fb_model)
                    if fb_pair not in seen_pairs:
                        seen_pairs.add(fb_pair)
                        expanded_candidates.append(
                            ProviderConfig(
                                provider_name="gemini",
                                model_name=fb_model,
                                base_url=cfg.base_url,
                                api_key=cfg.api_key,
                                allow_audio_upload=cfg.allow_audio_upload,
                                allow_project_file_upload=cfg.allow_project_file_upload,
                                timeout_seconds=min(float(cfg.timeout_seconds), 22.0),
                            )
                        )

        # Stage-1: Real-time internet song research + Google Search Grounding for song requests
        prompt_text = envelope.prompt_text
        composition_temp: Optional[float] = None
        dossier: Optional[SongResearchDossier] = None
        song_query = analyze_song_request(user_prompt)
        if song_query.is_song_reference:
            gem_cfg = next((c for c in expanded_candidates if c.provider_name == "gemini" and c.api_key), None)
            if gem_cfg is None and not self._explicit_config:
                env_gem = ProviderConfig.from_env("gemini")
                if env_gem.api_key:
                    gem_cfg = env_gem
            search_models = ["gemini-3-flash-preview"]
            if gem_cfg and gem_cfg.model_name:
                search_models.append(gem_cfg.model_name)
            search_models.extend(_GEMINI_FALLBACK_MODELS)
            try:
                dossier = research_song(
                    user_prompt,
                    gemini_api_key=(gem_cfg.api_key or "") if gem_cfg else "",
                    gemini_base_url=(gem_cfg.base_url if gem_cfg else "https://generativelanguage.googleapis.com/v1beta"),
                    gemini_models=search_models,
                    allow_in_pytest=allow_in_pytest,
                )
            except Exception as exc:
                logger.warning("Song research step skipped after error: %s", redact_secrets(str(exc)))
                dossier = None

            if dossier and dossier.is_song_reference:
                dossier_block = format_dossier_for_prompt(dossier)
                if dossier_block:
                    prompt_text = f"{prompt_text}\n{dossier_block}"
                if dossier.bpm or dossier.chord_progression or dossier.signature_riff_notes:
                    composition_temp = 0.35
                elif dossier.canonical_title:
                    composition_temp = 0.55
        elif not _looks_like_simple_greeting_or_question(user_prompt):
            creative_brief = build_creative_variation_brief(user_prompt, recent_history)
            prompt_text = f"{prompt_text}\n\n{creative_brief}"

        for cfg in expanded_candidates:
            logger.info("Calling %s model '%s' for user prompt: %s", cfg.provider_name, cfg.model_name, user_prompt[:100])
            raw_text, err = self._call_with_retry(
                cfg,
                _SYSTEM_PRODUCER_PROMPT,
                prompt_text,
                temperature=composition_temp,
                conversation_history=conversation_history,
            )
            if err or not raw_text:
                msg = f"{cfg.provider_name}({cfg.model_name}): {err or 'empty response'}"
                logger.warning("AI API call failed: %s", msg)
                error_notes.append(msg)
                continue

            try:
                parsed = json.loads(_strip_json_fences(raw_text))
            except json.JSONDecodeError as exc:
                msg = f"{cfg.provider_name}({cfg.model_name}): invalid JSON ({exc})"
                logger.warning("AI API returned invalid JSON: %s", msg)
                error_notes.append(msg)
                continue

            normalized = normalize_llm_plan(
                parsed,
                plan_source="ai_api",
                provider_name=cfg.provider_name,
                model_name=cfg.model_name,
            )
            if normalized is not None:
                is_song_ref = bool(dossier and dossier.is_song_reference)
                enrich_sparse_ai_tracks(normalized, is_song_reference=is_song_ref)
                if is_song_ref:
                    normalized["song_research"] = {
                        "label": dossier.resolved_label(),
                        "bpm": dossier.bpm,
                        "key": dossier.key,
                        "scale": dossier.scale,
                        "confidence": dossier.confidence,
                        "sources": dossier.sources[:5],
                    }
                    # Post-normalization BPM guard against Stage-2 hallucination
                    if (
                        normalized.get("intent_type") != "chat_only"
                        and dossier.bpm is not None
                        and dossier.explicit_user_bpm is None
                    ):
                        llm_bpm = normalized.get("tempo_bpm")
                        should_lock = False
                        if llm_bpm is None:
                            should_lock = True
                        elif abs(float(llm_bpm) - dossier.bpm) > 2.5:
                            # Allow exact 2x/0.5x half-time only when Google Search itself didn't pick the BPM
                            half_or_double_ok = (
                                dossier.grounded_bpm is None
                                and (
                                    abs(float(llm_bpm) - dossier.bpm * 2.0) <= 2.5
                                    or abs(float(llm_bpm) * 2.0 - dossier.bpm) <= 2.5
                                )
                            )
                            should_lock = not half_or_double_ok
                        if should_lock:
                            logger.info(
                                "Locking LLM BPM %s -> %s BPM from verified internet song research (%s)",
                                llm_bpm,
                                dossier.bpm,
                                dossier.resolved_label(),
                            )
                            normalized["tempo_bpm"] = dossier.bpm
                return normalized
            error_notes.append(f"{cfg.provider_name}({cfg.model_name}): invalid plan schema")

        return self._fallback_plan(
            user_prompt,
            project_context,
            error_notes,
            recent_history=recent_history,
            conversation_history=conversation_history,
        )


def list_available_models(
    provider_name: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    live: bool = True,
) -> Dict[str, Any]:
    """Return curated fast presets + (optionally) live API-discovered models for a provider."""
    cfg = ProviderConfig.from_env(provider_override=provider_name)
    prov = cfg.provider_name
    if api_key is not None:
        cfg.api_key = api_key
    if base_url:
        cfg.base_url = base_url

    curated = [dict(item) for item in CURATED_PROVIDER_MODELS.get(prov, [])]
    seen = {item["id"] for item in curated}
    live_fetched = False
    live_error: Optional[str] = None

    if live and (prov == "local" or cfg.api_key):
        try:
            if prov == "gemini":
                url = f"{cfg.base_url.rstrip('/')}/models?pageSize=100&key={cfg.api_key}"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                skip_tokens = (
                    "-tts", "-image", "nano-banana", "transcribe", "robotics",
                    "deep-research", "lyria", "embedding", "computer-use", "antigravity", "gemma",
                )
                for m in payload.get("models") or []:
                    methods = m.get("supportedGenerationMethods") or []
                    if "generateContent" not in methods:
                        continue
                    mid = str(m.get("name") or "").replace("models/", "").strip()
                    if not mid or mid in seen or mid in _LEGACY_BROKEN_GEMINI_MODELS:
                        continue
                    mid_low = mid.lower()
                    if any(tok in mid_low for tok in skip_tokens):
                        continue
                    disp = str(m.get("displayName") or mid)
                    if "pro" in mid_low:
                        disp = f"{disp} (Pro • Ücretsiz katmanda kota 0 olabilir)"
                    elif "3.8" in mid_low or "3.7" in mid_low or "3.6" in mid_low or mid_low == "gemini-flash-latest":
                        disp = f"{disp} (Ağır düşünme • yavaş olabilir)"
                    curated.append({
                        "id": mid,
                        "label": disp,
                        "tier": "live_api",
                        "recommended": False,
                    })
                    seen.add(mid)
                live_fetched = True
            elif prov == "openai":
                url = f"{cfg.base_url.rstrip('/')}/models"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {cfg.api_key}"}, method="GET")
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                for m in payload.get("data") or []:
                    mid = str(m.get("id") or "").strip()
                    if not mid or mid in seen:
                        continue
                    if not any(mid.startswith(pfx) for pfx in ("gpt-", "o1", "o3", "o4")):
                        continue
                    curated.append({"id": mid, "label": mid, "tier": "live_api", "recommended": False})
                    seen.add(mid)
                live_fetched = True
            elif prov == "local":
                url = f"{cfg.base_url.rstrip('/')}/api/tags"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                for m in payload.get("models") or []:
                    mid = str(m.get("name") or "").strip()
                    if mid and mid not in seen:
                        curated.append({"id": mid, "label": f"{mid} (Yerel Ollama)", "tier": "local", "recommended": False})
                        seen.add(mid)
                live_fetched = True
        except Exception as exc:
            live_error = redact_secrets(str(exc))

    default_model = curated[0]["id"] if curated else cfg.model_name
    return {
        "provider": prov,
        "default_model": default_model,
        "api_key_configured": bool(cfg.api_key) if prov != "local" else True,
        "live_fetched": live_fetched,
        "live_error": live_error,
        "models": curated,
    }


def test_provider_model(
    provider_name: str,
    model_name: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_seconds: float = 12.0,
) -> Dict[str, Any]:
    """Probe a single provider+model with a minimal JSON request to check availability and latency."""
    cfg = ProviderConfig.from_env(provider_override=provider_name)
    if model_name:
        cfg.model_name = model_name.strip()
    if api_key is not None:
        cfg.api_key = api_key
    if base_url:
        cfg.base_url = base_url
    cfg.timeout_seconds = timeout_seconds

    adapter = ModelProviderAdapter(config=cfg)
    t0 = time.time()
    try:
        raw_text = adapter._call_provider_api(cfg, "Return tiny JSON only.", '{"ping": true}')
        latency_ms = int(round((time.time() - t0) * 1000))
        if not raw_text:
            return {
                "ok": False,
                "provider": cfg.provider_name,
                "model": cfg.model_name,
                "latency_ms": latency_ms,
                "error": "Model boş yanıt döndü (thinking bütçesi çıkış tokenlarını tüketmiş olabilir).",
                "suggested_model": DEFAULT_GEMINI_MODEL if cfg.provider_name == "gemini" else None,
            }
        return {
            "ok": True,
            "provider": cfg.provider_name,
            "model": cfg.model_name,
            "latency_ms": latency_ms,
            "error": None,
            "suggested_model": None,
        }
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return {
            "ok": False,
            "provider": cfg.provider_name,
            "model": cfg.model_name,
            "latency_ms": int(round((time.time() - t0) * 1000)),
            "error": redact_secrets(f"HTTP {exc.code}: {err_body[:260] or exc.reason}"),
            "suggested_model": DEFAULT_GEMINI_MODEL if cfg.provider_name == "gemini" else None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": cfg.provider_name,
            "model": cfg.model_name,
            "latency_ms": int(round((time.time() - t0) * 1000)),
            "error": redact_secrets(str(exc)),
            "suggested_model": DEFAULT_GEMINI_MODEL if cfg.provider_name == "gemini" else None,
        }
