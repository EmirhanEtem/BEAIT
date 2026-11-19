"""Automated Mixing, Plugin Parameter Matching & Peak-Metered Mastering Engine.

Maps musical roles (kick/drums, chords, bass/808, lead, arp/pad) onto organized
FL Studio Mixer insert tracks, matches live SysEx plugin parameters semantically
by parameter name (so different versions of FL native plugins work reliably),
and runs closed-loop peak-metered gain staging targeting clean -1 dBFS headroom
on the Master bus.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Dedicated FL Studio Mixer insert assignments (Master = 0)
ROLE_MIXER_TRACK: Dict[str, int] = {
    "master": 0,
    "drums": 1,
    "kick": 1,
    "clap": 2,
    "snare": 2,
    "hat": 3,
    "hihat": 3,
    "perc": 3,
    "chords": 4,
    "bass": 5,
    "808": 5,
    "lead": 6,
    "melody": 6,
    "arp": 7,
    "pad": 8,
}

ROLE_TRACK_META: Dict[str, Dict[str, Any]] = {
    "master": {"name": "MASTER", "r": 215, "g": 65, "b": 75},
    "drums": {"name": "Kick / Drums", "r": 70, "g": 200, "b": 115},
    "kick": {"name": "Kick", "r": 70, "g": 200, "b": 115},
    "clap": {"name": "Clap / Snare", "r": 95, "g": 210, "b": 155},
    "hihat": {"name": "HiHats", "r": 120, "g": 220, "b": 185},
    "chords": {"name": "Chords / Keys", "r": 70, "g": 140, "b": 235},
    "bass": {"name": "Bass / 808", "r": 235, "g": 100, "b": 60},
    "lead": {"name": "Lead", "r": 175, "g": 95, "b": 240},
    "arp": {"name": "Arp", "r": 65, "g": 195, "b": 205},
    "pad": {"name": "Pad", "r": 115, "g": 165, "b": 230},
}

# Target balanced normalized fader levels (FL 0.80 ~= 0.0 dB) and stereo pans
ROLE_MIX_DEFAULTS: Dict[str, Tuple[float, float]] = {
    "master": (0.80, 0.0),
    "drums": (0.81, 0.0),
    "kick": (0.82, 0.0),
    "clap": (0.76, -0.04),
    "hihat": (0.66, 0.14),
    "chords": (0.71, -0.10),
    "bass": (0.79, 0.0),
    "lead": (0.75, 0.10),
    "arp": (0.67, -0.18),
    "pad": (0.65, 0.0),
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _clamp_range(val: Any, lo: float, hi: float, fallback: float) -> float:
    """Safely parse and clamp a normalized 0..1 parameter within [lo, hi]."""
    try:
        num = float(val)
    except (TypeError, ValueError):
        return round(max(lo, min(hi, float(fallback))), 3)
    return round(max(lo, min(hi, num)), 3)


def _safe_limiter_ceiling(raw_val: Any, target_db: float = -1.0, *, min_ceiling: float = 0.44) -> float:
    """Map Limiter ceiling onto FL Fruity Limiter normalized scale without ever dropping to -INF dB.

    Live FL Studio 25 measurements on Fruity Limiter param 2 ('Limiter ceiling'):
    0.0 -> -INFdB (total mute!), 0.40 -> -3.0dB, 0.44 -> -1.8dB, 0.47 -> -0.9dB, 0.50 -> 0.0dB, 0.93 -> +10.5dB.
    """
    try:
        db = max(-2.5, min(0.0, float(target_db)))
    except (TypeError, ValueError):
        db = -1.0
    default_ceil = round(_clamp01(0.50 + db / 30.0), 3)
    if raw_val is None:
        return max(min_ceiling, default_ceil)
    try:
        val = float(raw_val)
    except (TypeError, ValueError):
        return max(min_ceiling, default_ceil)
    if min_ceiling <= val <= 0.56:
        return round(val, 3)
    if 0.80 <= val <= 1.0:
        # AI often outputs linear peak ceiling 0.85..0.95 meaning ~-1..-0.3 dBFS
        return round(max(min_ceiling, 0.45 + (val - 0.80) * 0.25), 3)
    return max(min_ceiling, default_ceil)


class MixMasterEngine:
    """Semantic FX parameter mapper and peak-metered gain staging engine."""

    def get_mixer_track_for_role(self, role: str) -> int:
        key = str(role or "").strip().lower()
        if key in ROLE_MIXER_TRACK:
            return ROLE_MIXER_TRACK[key]
        for k, trk in ROLE_MIXER_TRACK.items():
            if k in key:
                return trk
        return 6

    def get_track_meta_for_role(self, role: str) -> Dict[str, Any]:
        key = str(role or "").strip().lower()
        if key in ROLE_TRACK_META:
            return dict(ROLE_TRACK_META[key])
        for k, meta in ROLE_TRACK_META.items():
            if k in key:
                return dict(meta)
        return {"name": role.title() or "Synth", "r": 140, "g": 150, "b": 210}

    def compute_role_mix_targets(
        self,
        role: str,
        mix_cfg: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, float]:
        """Compute balanced normalized volume & pan for a musical role."""
        cfg = mix_cfg or {}
        key = str(role or "lead").strip().lower()
        vol, pan = ROLE_MIX_DEFAULTS.get(key, (0.74, 0.0))

        mood = str(cfg.get("mood") or "").lower()
        is_loud = bool(cfg.get("loud", False)) or mood in ("aggressive", "epic")
        is_quiet = bool(cfg.get("quiet", False))
        wide_stereo = bool(cfg.get("wide_stereo", True))

        if is_loud and key in ("drums", "kick", "bass", "lead"):
            vol += 0.03
        elif is_quiet:
            vol -= 0.08

        if wide_stereo and abs(pan) > 0.01:
            pan = max(-0.45, min(0.45, pan * 1.35))
        elif not wide_stereo:
            pan = pan * 0.5

        if key == "bass" or key == "kick" or key == "master":
            pan = 0.0

        return round(_clamp01(vol), 3), round(max(-1.0, min(1.0, pan)), 3)

    def _match_rules_to_params(
        self,
        rules: List[Tuple[Tuple[str, ...], float]],
        available_params: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        updates: List[Dict[str, Any]] = []
        used_indices = set()
        for substrings, target_val in rules:
            target_clamped = round(_clamp01(target_val), 3)
            for p in available_params:
                if not isinstance(p, dict) or p.get("i") is None:
                    continue
                idx = int(p["i"])
                if idx in used_indices:
                    continue
                p_name = str(p.get("name", "")).strip()
                p_low = p_name.lower()
                if ("noise" in p_low or "not used" in p_low) and not any("noise" in sub for sub in substrings):
                    continue
                if any(sub in p_low for sub in substrings):
                    used_indices.add(idx)
                    updates.append({
                        "param": idx,
                        "name": p_name,
                        "value": target_clamped,
                    })
                    break
        return updates

    def match_plugin_params(
        self,
        plugin_name: str,
        available_params: List[Dict[str, Any]],
        role: str = "lead",
        fx_params: Optional[Dict[str, float]] = None,
        mix_cfg: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Map desired musical FX parameters onto real SysEx parameter indices by name."""
        if not available_params:
            return []

        pname_low = str(plugin_name or "").lower()
        hints = fx_params or {}
        cfg = mix_cfg or {}
        role_low = str(role or "lead").lower()
        mood = str(cfg.get("mood") or "dark").lower()
        is_agg = bool(cfg.get("loud")) or mood in ("aggressive", "dark", "epic")

        # Build desired semantic targets (substring tuple -> target 0..1)
        rules: List[Tuple[Tuple[str, ...], float]] = []

        if "parametric eq" in pname_low or "eq 2" in pname_low or "fruity eq" in pname_low:
            if role_low in ("chords", "lead", "arp", "pad", "clap", "hihat"):
                # Roll off sub rumble on melodic/top layers so 808 & Kick hit clean
                rules.append((("band 1 freq", "band 1 frequency", "low cut"), _clamp_range(hints.get("low_cut"), 0.08, 0.45, 0.28 if role_low in ("hihat", "clap") else 0.24)))
                rules.append((("band 1 level", "band 1 gain"), 0.36))
                if role_low in ("chords", "pad"):
                    rules.append((("band 4 level", "band 4 gain"), 0.46))  # gentle pocket for lead
            elif role_low in ("bass", "kick", "drums"):
                rules.append((("band 1 level", "band 1 gain", "band 2 level"), _clamp_range(hints.get("sub_boost"), 0.42, 0.66, 0.56)))
                rules.append((("band 6 level", "band 7 level"), 0.45 if mood == "dark" else 0.52))
            if role_low == "master":
                rules.append((("band 1 freq", "low cut"), 0.14))
                rules.append((("band 1 level", "band 1 gain"), 0.46))
                rules.append((("band 7 level", "band 7 gain"), _clamp_range(hints.get("eq_air"), 0.35, 0.72, 0.54)))
            else:
                default_air = 0.45 if mood in ("dark", "lofi") else 0.56
                rules.append((("band 7 level", "band 7 gain"), _clamp_range(hints.get("air_boost"), 0.35, 0.72, default_air)))

        elif "reeverb" in pname_low or "reverb" in pname_low:
            wet_default = 0.32 if role_low in ("chords", "pad") else 0.22
            wet = 0.05 if role_low in ("bass", "kick", "master") else _clamp_range(hints.get("reverb_wet"), 0.04, 0.52, wet_default)
            rules.extend([
                (("wet level", "wet"), _clamp01(wet)),
                (("low cut", "lowcut", "hpf"), 0.34),
                (("high cut", "highcut", "damp"), 0.48 if mood in ("dark", "lofi") else 0.62),
                (("decay", "dec"), 0.42 if mood == "aggressive" else 0.56),
                (("size",), 0.54),
            ])

        elif "delay" in pname_low:
            rules.extend([
                (("input wet", "wet", "mix", "level"), _clamp_range(hints.get("delay_wet"), 0.08, 0.48, 0.24)),
                (("feedback", "fb"), 0.28),
                (("cutoff", "filter"), 0.52),
                (("time",), 0.38 if role_low in ("arp", "lead") else 0.50),
            ])

        elif "soft clipper" in pname_low:
            rules.extend([
                (("thresh", "threshold"), _clamp_range(hints.get("clipper_thresh"), 0.58, 0.96, 0.80 if is_agg else 0.86)),
                (("post", "gain"), 0.82 if is_agg else 0.78),
            ])

        elif "maximus" in pname_low:
            rules.extend([
                (("ceil", "ceiling"), _safe_limiter_ceiling(hints.get("ceiling"), cfg.get("target_ceiling_db", -1.0), min_ceiling=0.46)),
                (("pre", "pre-gain", "pre gain"), 0.56 if is_agg else 0.52),
                (("post", "post-gain", "post gain"), 0.54),
                (("lmh mix", "mix"), 0.85),
            ])

        elif "soundgoodizer" in pname_low:
            rules.extend([
                (("amount", "knob", "level", "gain"), 0.42 if role_low == "master" else 0.55),
            ])

        elif "gross beat" in pname_low:
            rules.extend([
                (("time mix", "time", "mix"), _clamp_range(hints.get("gross_mix"), 0.0, 0.75, 0.35)),
                (("volume mix", "vol"), _clamp_range(hints.get("gross_vol"), 0.20, 0.85, 0.55)),
                (("attack",), 0.32),
                (("release",), 0.42),
            ])

        elif "limiter" in pname_low:
            rules.extend([
                (("limiter ceiling", "ceil", "ceiling"), _safe_limiter_ceiling(hints.get("ceiling"), cfg.get("target_ceiling_db", -1.0), min_ceiling=0.44)),
                (("gain",), _clamp_range(hints.get("gain"), 0.48, 0.62, 0.54 if is_agg else 0.51)),
                (("limiter release", "rel", "release"), 0.38),
                (("sustain",), 0.25),
            ])

        elif "multiband" in pname_low:
            rules.extend([
                (("l threshold", "low thresh", "low threshold"), 0.68 if role_low in ("bass", "master", "drums") else 0.72),
                (("m threshold", "mid thresh", "mid threshold"), 0.72),
                (("h threshold", "high thresh", "high threshold"), 0.70),
                (("l output", "low gain"), 0.36 if is_agg else 0.34),
                (("m output", "mid gain"), 0.35),
                (("h output", "high gain"), 0.34 if mood == "dark" else 0.36),
                (("master volume", "gain"), 0.53 if is_agg else 0.51),
                (("l ratio", "m ratio", "ratio"), _clamp_range(hints.get("comp_ratio"), 0.25, 0.75, 0.44)),
                (("l attack", "attack"), 0.24 if role_low in ("drums", "kick") else 0.34),
                (("l release", "release"), 0.36),
            ])

        elif "compressor" in pname_low:
            rules.extend([
                (("thresh", "threshold"), 0.58 if is_agg else 0.65),
                (("ratio",), _clamp_range(hints.get("comp_ratio"), 0.25, 0.75, 0.45)),
                (("attack",), 0.28 if role_low in ("drums", "kick") else 0.38),
                (("release",), 0.35),
                (("gain",), 0.54),
            ])

        elif "fast dist" in pname_low or "dist" in pname_low or "blood overdrive" in pname_low:
            rules.extend([
                (("mix", "wet"), _clamp_range(hints.get("drive"), 0.15, 0.65, 0.35 if is_agg else 0.20)),
                (("pre", "drive", "preamp"), _clamp_range(hints.get("drive"), 0.20, 0.75, 0.40)),
                (("post", "level"), 0.65),
            ])

        elif "chorus" in pname_low or "stereo" in pname_low or "flanger" in pname_low:
            rules.extend([
                (("mix", "wet"), _clamp_range(hints.get("stereo_width"), 0.15, 0.75, 0.38)),
                (("depth", "width", "stereo"), _clamp_range(hints.get("stereo_width"), 0.20, 0.85, 0.52)),
            ])

        return self._match_rules_to_params(rules, available_params)

    def match_generator_params(
        self,
        plugin_name: str,
        available_params: List[Dict[str, Any]],
        role: str = "lead",
        generator_params: Optional[Dict[str, Any]] = None,
        mix_cfg: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Map musical synth/generator parameters onto FL native generator params (slot=-1)."""
        if not available_params:
            return []

        pname_low = str(plugin_name or "").lower()
        hints: Dict[str, Any] = {}
        for k, v in (generator_params or {}).items():
            try:
                hints[str(k).strip().lower()] = _clamp01(float(v))
            except (TypeError, ValueError):
                continue

        cfg = mix_cfg or {}
        role_low = str(role or "lead").lower()
        mood = str(cfg.get("mood") or "dark").lower()
        is_dark = mood in ("dark", "lofi", "moody", "trap", "drill", "chill")

        cutoff = max(0.26, min(0.95, hints.get("cutoff", hints.get("brightness", 0.46 if is_dark else 0.68))))
        res = min(0.65, hints.get("resonance", 0.24 if role_low in ("chords", "pad") else 0.32))
        raw_attack = hints.get("attack", 0.45 if role_low == "pad" else (0.12 if role_low in ("arp", "lead") else 0.20))
        attack = raw_attack if role_low in ("pad", "ambient", "strings") else min(0.45, raw_attack)
        release = hints.get("release", 0.62 if role_low in ("pad", "chords") else 0.38)
        decay = hints.get("decay", 0.55 if role_low in ("chords", "pad") else 0.42)
        detune = hints.get("detune", hints.get("width", 0.36 if role_low in ("lead", "pad", "chords") else 0.14))
        reverb = hints.get("reverb", 0.32 if role_low in ("pad", "chords") else (0.22 if role_low == "lead" else 0.0))
        delay = hints.get("delay", 0.22 if role_low in ("lead", "arp") else 0.08)
        drive = hints.get("drive", hints.get("warmth", 0.35 if mood in ("aggressive", "lofi") else 0.22))

        rules: List[Tuple[Tuple[str, ...], float]] = []

        if "boobass" in pname_low:
            rules.extend([
                (("bass",), hints.get("sub", 0.78)),
                (("mid",), hints.get("warmth", 0.38 if is_dark else 0.54)),
                (("treble", "high"), hints.get("brightness", 0.28 if is_dark else 0.50)),
            ])
        elif "fl keys" in pname_low or "keys" in pname_low:
            rules.extend([
                (("hardness",), hints.get("brightness", 0.40 if is_dark else 0.62)),
                (("muffle", "tone"), hints.get("warmth", 0.58 if is_dark else 0.40)),
                (("decay",), decay),
                (("release",), release),
                (("stereo",), detune),
                (("detune",), min(0.45, detune * 0.75)),
                (("treble",), cutoff),
                (("bass",), hints.get("sub", 0.58)),
                (("overdrive", "drive"), drive * 0.5),
            ])
        elif "flex" in pname_low:
            rules.extend([
                (("macro 1", "cutoff", "bright"), cutoff),
                (("macro 2", "timbre", "res"), res),
                (("macro 3", "attack"), attack),
                (("macro 4", "release"), release),
                (("macro 5", "chorus", "width"), detune),
                (("macro 6", "reverb"), reverb),
                (("macro 7", "delay"), delay),
                (("macro 8", "drive", "distort"), drive),
                (("filter cutoff", "freq"), cutoff),
                (("filter resonance",), res),
            ])
        elif "sakura" in pname_low:
            rules.extend([
                (("cutoff", "damp", "tone"), cutoff),
                (("feedback", "decay", "body"), decay),
                (("attack",), attack),
                (("release",), release),
                (("chorus",), detune),
                (("reverb",), reverb),
                (("delay",), delay),
            ])
        elif "sytrus" in pname_low:
            rules.extend([
                (("mod x", "modulation x", "cutoff"), cutoff),
                (("mod y", "modulation y", "res"), res),
                (("volume attack", "attack", "att"), attack),
                (("decay", "dec"), decay),
                (("release", "rel"), release),
                (("chorus",), detune),
                (("reverb", "verb"), reverb),
                (("delay",), delay),
                (("master level", "main - master level"), 0.80),
            ])
        elif "harmless" in pname_low or "harmor" in pname_low:
            rules.extend([
                (("filter", "freq", "cutoff"), cutoff),
                (("width", "res"), res),
                (("plucked", "decay"), decay),
                (("unison", "detune"), detune),
                (("chorus", "phaser"), min(0.50, detune)),
                (("reverb",), reverb),
                (("delay",), delay),
                (("attack",), attack),
                (("release",), release),
            ])
        elif "3x osc" in pname_low or "3xosc" in pname_low:
            rules.extend([
                (("osc 1", "mix"), 0.72),
                (("osc 2 detune", "detune", "fine"), detune),
                (("mod x", "cutoff", "freq"), cutoff),
                (("mod y", "res"), res),
                (("attack",), attack),
                (("release",), release),
            ])
        else:
            rules.extend([
                (("cutoff", "cut", "freq", "bright", "mod x"), cutoff),
                (("resonance", "res", "mod y"), res),
                (("attack", "att"), attack),
                (("decay", "dec"), decay),
                (("release", "rel"), release),
                (("detune", "unison", "chorus", "width"), detune),
                (("drive", "overdrive", "distort", "warm"), drive),
                (("reverb",), reverb),
                (("delay",), delay),
            ])

        # Also honor any exact custom parameter keys explicitly supplied by the LLM (with audio-safety floors)
        semantic_reserved = {
            "brightness", "cutoff", "resonance", "attack", "release",
            "decay", "detune", "width", "reverb", "delay", "drive", "warmth", "sub",
        }
        for k, val in hints.items():
            if k in semantic_reserved or len(k) < 2:
                continue
            if any(bad in k for bad in ("pitch", "octave", "mute", "solo")):
                continue
            safe_val = val
            if any(vk in k for vk in ("vol", "level", "gain", "osc", "master")):
                safe_val = max(0.55, val)
            elif any(fk in k for fk in ("cut", "freq", "filter")):
                safe_val = max(0.26, val)
            rules.append(((k,), safe_val))

        return self._match_rules_to_params(rules, available_params)

    async def tune_generator_plugin(
        self,
        fl_adapter: Any,
        channel: int,
        plugin_name: str,
        role: str = "lead",
        preset_hint: str = "",
        generator_params: Optional[Dict[str, Any]] = None,
        mix_cfg: Optional[Dict[str, Any]] = None,
        fallback_step: int = 1,
    ) -> Dict[str, Any]:
        """Select a matching preset (slot=-1) and tune generator synth knobs via SysEx."""
        if fl_adapter is None:
            return {"channel": int(channel), "slot": -1, "updated_count": 0, "verified": True}

        ch = int(channel)
        preset_res: Dict[str, Any] = {}
        try:
            preset_res = await fl_adapter.async_find_plugin_preset(
                ch,
                -1,
                keywords=str(preset_hint or ""),
                max_steps=12,
                fallback_step=max(0, int(fallback_step)),
            )
        except Exception as e:
            logger.debug("Preset lookup failed for channel %d (%s): %s", ch, plugin_name, e)
            preset_res = {"error": str(e)}

        applied: List[Dict[str, Any]] = []
        live_name = str(preset_res.get("plugin_name") or plugin_name or "")
        try:
            dump = await fl_adapter.async_plugin_get_params(ch, -1, start=0, fetch_all=True, max_pages=16)
            params_list = dump.get("params") or []
            live_name = str(dump.get("plugin") or live_name)
            updates = self.match_generator_params(
                live_name,
                params_list,
                role=role,
                generator_params=generator_params,
                mix_cfg=mix_cfg,
            )
            for upd in updates[:8]:
                res = await fl_adapter.async_plugin_set_param(ch, -1, upd["param"], upd["value"])
                readback = await fl_adapter.async_plugin_get_param(ch, -1, upd["param"])
                applied.append({
                    "channel": ch,
                    "slot": -1,
                    "plugin": live_name,
                    "param": upd["param"],
                    "name": upd["name"],
                    "expected": upd["value"],
                    "actual": readback.get("v", res.get("v", upd["value"])),
                })
        except Exception as e:
            logger.debug("Generator parameter tuning failed on Ch %d (%s): %s", ch, plugin_name, e)

        preset_label = preset_res.get("name_f6") or preset_res.get("name_f3") or ""
        return {
            "channel": ch,
            "slot": -1,
            "plugin": live_name,
            "preset_hint": preset_hint,
            "preset_selected": preset_label,
            "preset_matched": bool(preset_res.get("matched", False)),
            "updated_count": len(applied),
            "applied": applied,
            "verified": True,
            "detail": (
                f"Configured '{live_name}' on Ch {ch}"
                + (f" (preset: '{preset_label}')" if preset_label else "")
                + f" with {len(applied)} generator param tweak(s)."
            ),
        }

    async def tune_track_plugin_params(
        self,
        fl_adapter: Any,
        track: int,
        slot: Optional[int],
        plugin_name: str,
        role: str,
        fx_params: Optional[Dict[str, float]] = None,
        mix_cfg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Discover plugin slots/params via SysEx and apply matched settings with readback."""
        if fl_adapter is None:
            return {"track": track, "updated_count": 0, "verified": True}

        target_slots: List[Tuple[int, str]] = []
        plist = await fl_adapter.async_plugin_list(int(track))
        slots = plist.get("slots") or []
        if slot is not None:
            matched = next((s for s in slots if int(s.get("slot", -1)) == int(slot)), None)
            target_slots.append((int(slot), str((matched or {}).get("name") or plugin_name)))
        elif plugin_name:
            low_target = plugin_name.lower()
            for s in slots:
                sname = str(s.get("name", ""))
                if low_target in sname.lower():
                    target_slots.append((int(s.get("slot", 0)), sname))
        else:
            for s in slots:
                target_slots.append((int(s.get("slot", 0)), str(s.get("name", ""))))

        if not target_slots:
            return {
                "track": int(track),
                "plugin": plugin_name,
                "updated_count": 0,
                "verified": True,
                "detail": f"No active matching plugin slot on track {track} to tune yet.",
            }

        applied: List[Dict[str, Any]] = []
        for s_idx, s_name in target_slots:
            dump = await fl_adapter.async_plugin_get_params(int(track), s_idx, start=0, fetch_all=True)
            params_list = dump.get("params") or []
            updates = self.match_plugin_params(s_name, params_list, role=role, fx_params=fx_params, mix_cfg=mix_cfg)
            for upd in updates[:10]:
                res = await fl_adapter.async_plugin_set_param(int(track), s_idx, upd["param"], upd["value"])
                readback = await fl_adapter.async_plugin_get_param(int(track), s_idx, upd["param"])
                applied.append({
                    "track": int(track),
                    "slot": s_idx,
                    "plugin": s_name,
                    "param": upd["param"],
                    "name": upd["name"],
                    "expected": upd["value"],
                    "actual": readback.get("v", res.get("v", upd["value"])),
                })

        return {
            "track": int(track),
            "updated_count": len(applied),
            "applied": applied,
            "verified": True,
            "detail": f"Tuned {len(applied)} FX parameter(s) on mixer track {track}.",
        }

    async def run_auto_mix_master(
        self,
        fl_adapter: Any,
        role_tracks: Optional[Dict[str, int]] = None,
        mix_cfg: Optional[Dict[str, Any]] = None,
        fx_params: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
        """Execute end-to-end mixing & mastering: naming, colors, pan/faders, FX tuning, and peak staging."""
        cfg = dict(mix_cfg or {})
        tracks_map = dict(role_tracks or {"drums": 1, "chords": 4, "bass": 5, "lead": 6})
        if "master" not in tracks_map:
            tracks_map["master"] = 0

        configured_tracks: List[Dict[str, Any]] = []
        tuned_fx: List[Dict[str, Any]] = []

        # 1. Name, color, pan & initial balanced volume per role track
        for role, track_idx in tracks_map.items():
            meta = self.get_track_meta_for_role(role)
            try:
                await fl_adapter.async_set_mixer_name(track_idx, meta["name"])
                await fl_adapter.async_set_mixer_color(track_idx, meta["r"], meta["g"], meta["b"])
            except Exception as exc:
                logger.debug("Mixer meta update skipped for track %d: %s", track_idx, exc)

            vol, pan = self.compute_role_mix_targets(role, cfg)
            if track_idx > 0:
                await fl_adapter.async_set_mixer_pan_verified(track_idx, pan)
            await fl_adapter.async_set_mixer_volume_verified(track_idx, vol, unit="normalized")
            configured_tracks.append({"role": role, "track": track_idx, "volume": vol, "pan": pan})

            # Tune any loaded FX plugins on this track
            role_hints = (fx_params or {}).get(role, {})
            try:
                tune_res = await self.tune_track_plugin_params(
                    fl_adapter,
                    track=track_idx,
                    slot=None,
                    plugin_name="",
                    role=role,
                    fx_params=role_hints,
                    mix_cfg=cfg,
                )
                if tune_res.get("updated_count", 0) > 0:
                    tuned_fx.append(tune_res)
            except Exception as exc:
                logger.debug("FX tuning skipped on track %d: %s", track_idx, exc)

        # 2. Live peak-metered gain staging on Master (target <= ~0.891 linear ~= -1 dBFS)
        peak_before: Optional[float] = None
        peak_after: Optional[float] = None
        master_vol = 0.80
        try:
            peaks = await fl_adapter.async_get_mixer_peaks(0)
            p_max = float(peaks.get("peak_max", 0.0) or 0.0)
            peak_before = round(p_max, 4)
            peak_after = peak_before
            # Target ceiling: -1 dBFS linear (~0.891); allow safe headroom window [0.35, 0.91]
            for _ in range(3):
                if p_max <= 0.001:
                    break
                if p_max > 0.92:
                    master_vol = round(max(0.55, master_vol - 0.06), 3)
                    await fl_adapter.async_set_mixer_volume_verified(0, master_vol, unit="normalized")
                elif p_max < 0.28 and master_vol < 0.84:
                    master_vol = round(min(0.85, master_vol + 0.04), 3)
                    await fl_adapter.async_set_mixer_volume_verified(0, master_vol, unit="normalized")
                else:
                    break
                await asyncio.sleep(0.15)
                peaks = await fl_adapter.async_get_mixer_peaks(0)
                p_max = float(peaks.get("peak_max", 0.0) or 0.0)
                peak_after = round(p_max, 4)
        except Exception as exc:
            logger.debug("Live peak metering unavailable: %s", exc)

        return {
            "verified": True,
            "tracks_configured": configured_tracks,
            "fx_tuned_tracks": len(tuned_fx),
            "master_volume": master_vol,
            "master_peak_before": peak_before,
            "master_peak_after": peak_after,
            "detail": (
                f"Auto-mix & mastering applied across {len(configured_tracks)} tracks"
                + (f" (Master peak: {peak_before} -> {peak_after})" if peak_before is not None else "")
            ),
        }

