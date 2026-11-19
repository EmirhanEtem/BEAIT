"""Producer Orchestrator — Central coordination of user intent, planning, specialist roles, and execution.

Converts natural-language musical and DAW requests (Turkish & English) into typed,
verifiable ActionPlans, coordinates Composer, Rhythm, SoundDesigner, Arranger, and Critic
specialist modules, enforces bounded execution and approval gating, and records task summaries.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..action_router.executor import ActionExecutor
from ..agents import (
    ArrangementPlan,
    ArrangerAgent,
    ComposerAgent,
    CompositionBundle,
    CriticAgent,
    CriticFeedbackReport,
    RhythmAgent,
    RhythmBundle,
    SoundDesignPlan,
    SoundDesignerAgent,
)
from ..database.persistence import DatabaseManager
from ..integrations.audio import AudioAnalyzer, FLRenderWorkflow, RenderSettings
from ..integrations.fl_studio.adapter import FLStudioAdapter
from ..model_providers import ModelProviderAdapter, PromptDisclosureEnvelope
from ..music_engine.generator import generate_drum_pattern
from ..project_memory import ProjectMemoryManager, TaskSummaryRecord
from ..schemas.actions import (
    ActionDefinition,
    ActionLifecycleState,
    ActionRiskLevel,
    ActionType,
)

logger = logging.getLogger(__name__)

MAX_BOUNDED_PLAN_ACTIONS = 64


@dataclass
class UserMusicalIntent:
    """Structured musical intent schema (Section 6.1)."""
    raw_prompt: str
    genre: Optional[str] = None
    tempo_bpm: Optional[float] = None
    key: Optional[str] = None
    scale: Optional[str] = None
    time_signature: str = "4/4"
    mood: List[str] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)
    requested_elements: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(
        default_factory=lambda: {
            "use_existing_project": True,
            "preserve_existing_tracks": True,
        }
    )

    @property
    def is_full_production_request(self) -> bool:
        """Return True when the prompt asks for a multi-element musical production workflow."""
        return len(self.requested_elements) >= 2 or (
            self.genre is not None and (len(self.requested_elements) >= 1 or len(self.sections) >= 1)
        )


@dataclass
class ActionPlan:
    """An ordered, bounded list of typed actions to achieve a user's musical intent."""
    plan_id: str
    task_id: str
    prompt: str
    actions: List[ActionDefinition] = field(default_factory=list)
    dry_run: bool = False
    requires_approval: bool = False
    parsed_intent: Optional[UserMusicalIntent] = None
    composition: Optional[CompositionBundle] = None
    rhythm: Optional[RhythmBundle] = None
    arrangement: Optional[ArrangementPlan] = None
    sound_design: Optional[SoundDesignPlan] = None
    prompt_disclosure: Optional[PromptDisclosureEnvelope] = None
    llm_explanation: Optional[str] = None
    remaining_limitations: List[str] = field(default_factory=list)
    session_id: Optional[str] = None
    session_history_entry: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PlanExecutionResult:
    """Summary of plan execution outcomes."""
    plan_id: str
    task_id: str
    success: bool
    actions_executed: int
    actions_succeeded: int
    actions_failed: int
    actions_awaiting_approval: int
    details: List[Dict[str, Any]] = field(default_factory=list)
    completed_summary: List[str] = field(default_factory=list)
    remaining_limitations: List[str] = field(default_factory=list)
    exported_midi_files: Dict[str, str] = field(default_factory=dict)
    critic_feedback: Optional[CriticFeedbackReport] = None
    error: Optional[str] = None


class ProducerOrchestrator:
    """Coordinates natural intent parsing, specialist modules, plan creation, gating, and execution."""

    def __init__(
        self,
        executor: Optional[ActionExecutor] = None,
        fl_adapter: Optional[FLStudioAdapter] = None,
        hcu_adapter: Optional[Any] = None,
        db: Optional[DatabaseManager] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        memory: Optional[ProjectMemoryManager] = None,
        model_provider: Optional[ModelProviderAdapter] = None,
        max_actions_per_plan: int = MAX_BOUNDED_PLAN_ACTIONS,
    ):
        self.db = db or DatabaseManager()
        self.fl_adapter = fl_adapter
        self.hcu_adapter = hcu_adapter
        self.executor = executor or ActionExecutor(db=self.db, fl_adapter=fl_adapter, hcu_adapter=hcu_adapter)
        self.event_callback = event_callback
        self.memory = memory or ProjectMemoryManager()
        self.model_provider = model_provider or ModelProviderAdapter()
        self.max_actions_per_plan = max_actions_per_plan

        # Specialist roles (Section 5.2)
        self.composer = ComposerAgent()
        self.rhythm_agent = RhythmAgent()
        self.sound_designer = SoundDesignerAgent()
        self.arranger = ArrangerAgent()
        self.critic = CriticAgent()
        self._last_prompt: Optional[str] = None
        self._recent_history: List[Dict[str, Any]] = []
        self._session_last_prompts: Dict[str, str] = {}
        self._session_histories: Dict[str, List[Dict[str, Any]]] = {}

    def parse_musical_intent(self, prompt: str) -> UserMusicalIntent:
        """Parse English or Turkish natural-language production requests into UserMusicalIntent."""
        clean = prompt.strip()
        lower = clean.lower()

        # 1. Parse BPM
        tempo_bpm: Optional[float] = None
        bpm_match = (
            re.search(r"(\d{2,3}(?:\.\d+)?)\s*bpm", lower)
            or re.search(r"(?:set|change)?\s*(?:tempo|bpm)\s*(?:to|=)?\s*(\d{2,3}(?:\.\d+)?)", lower)
        )
        if bpm_match:
            tempo_bpm = float(bpm_match.group(1))

        # 2. Parse Genre
        genre: Optional[str] = None
        if "melodic techno" in lower or "melodik tekno" in lower:
            genre = "melodic_techno"
        elif any(g in lower for g in ("deep house", "tech house", "house", "edm", "dance")):
            genre = "deep_house"
        elif any(g in lower for g in ("phonk", "drift", "cowbell", "trap", "drill", "808")):
            genre = "trap_dark"
        elif any(g in lower for g in ("boom bap", "boombap", "slow", "chill", "lofi", "lo-fi", "hip hop", "hip-hop", "rap")):
            genre = "boom_bap_chill"
        elif any(g in lower for g in ("techno", "tekno", "trance", "rave")):
            genre = "melodic_techno"

        # 3. Parse Key & Scale (e.g. "A minor", "F# harmonic minor", "C dorian", "A minör")
        key_root: Optional[str] = None
        scale_name: Optional[str] = None
        key_match = re.search(
            r"\b([A-G][#b]?)\s*(harmonic\s+minor|natural\s+minor|minor|minör|major|majör|dorian|phrygian)\b",
            clean,
            re.IGNORECASE,
        )
        if key_match:
            key_root = key_match.group(1).upper()
            raw_scale = key_match.group(2).lower()
            if "harmonic" in raw_scale:
                scale_name = "harmonic_minor"
            elif "dorian" in raw_scale:
                scale_name = "dorian"
            elif "phrygian" in raw_scale:
                scale_name = "phrygian"
            elif "maj" in raw_scale:
                scale_name = "major"
            else:
                scale_name = "natural_minor"

        # 4. Parse Requested Elements
        elements: List[str] = []
        if any(w in lower for w in ("kick", "drum", "davul", "ritim", "beat", "four-on-the-floor", "4-on-the-floor")):
            elements.append("kick")
        if any(w in lower for w in ("percussion", "perküsyon", "hihat", "hi-hat", "clap", "snare")):
            elements.append("percussion")
        if any(w in lower for w in ("bassline", "bass", "bas")):
            elements.append("bass")
        if any(w in lower for w in ("melody", "melodi", "lead", "motif")):
            elements.append("lead_melody")
        if any(w in lower for w in ("chord", "akor", "pad", "harmony")):
            elements.append("chords")

        # 5. Parse Sections
        sections: List[str] = []
        for sec_en, keywords in [
            ("Intro", ["intro", "giriş"]),
            ("Build", ["build", "yükseliş"]),
            ("Drop", ["drop", "nakarat"]),
            ("Breakdown", ["breakdown", "ara"]),
            ("Outro", ["outro", "çıkış", "bitiş"]),
        ]:
            if any(re.search(rf"\b{kw}\b", lower) for kw in keywords):
                sections.append(sec_en)

        if ("arrangement" in lower or "aranjman" in lower) and not sections:
            sections = ["Intro", "Build", "Drop", "Breakdown", "Outro"]

        # 5b. Expand general song/beat production prompts in Turkish/English
        is_melody_only = ("motif" in lower or "piyano" in lower) and len(elements) == 1 and "lead_melody" in elements
        is_song_creation = any(
            w in lower for w in ("şarkı", "parça", "müzik", "phonk", "yap", "oluştur", "hazırla", "üret")
        )
        if is_song_creation and not is_melody_only:
            if genre is None:
                genre = "melodic_techno"
            if len(elements) < 2:
                for el in ("kick", "percussion", "bass", "lead_melody"):
                    if el not in elements:
                        elements.append(el)
            if not sections:
                sections = ["Intro", "Drop"]

        # 6. Mood keywords
        moods: List[str] = []
        for m_kw in ("dark", "karanlık", "energetic", "enerjik", "atmospheric", "atmosferik", "chill", "warm"):
            if m_kw in lower:
                moods.append(m_kw)

        return UserMusicalIntent(
            raw_prompt=prompt,
            genre=genre,
            tempo_bpm=tempo_bpm,
            key=key_root,
            scale=scale_name,
            mood=moods,
            sections=sections,
            requested_elements=elements,
        )

    def create_plan(
        self,
        prompt: str,
        task_id: Optional[str] = None,
        dry_run: bool = False,
        project_context: Optional[Dict[str, Any]] = None,
        midi_export_dir: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        session_recent_history: Optional[List[Dict[str, Any]]] = None,
    ) -> ActionPlan:
        """Parse natural language command and produce a bounded, structured ActionPlan."""
        t_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        p_id = f"plan_{uuid.uuid4().hex[:8]}"
        clean = prompt.strip().lower()

        if session_id:
            active_history: List[Dict[str, Any]] = (
                list(session_recent_history)
                if session_recent_history is not None
                else list(self._session_histories.get(session_id, []))
            )
            last_for_scope = self._session_last_prompts.get(session_id)
            if not last_for_scope and conversation_history:
                for turn in reversed(conversation_history):
                    if isinstance(turn, dict) and str(turn.get("role")).lower() == "user":
                        cand = str(turn.get("text") or turn.get("content") or "").strip()
                        if cand and cand.lower() not in ("tekrar yap", "yeniden yap", "aynısını yap", "tekrarla", "tekrar"):
                            last_for_scope = cand
                            break
        else:
            active_history = (
                list(session_recent_history)
                if session_recent_history is not None
                else list(self._recent_history)
            )
            last_for_scope = self._last_prompt

        # Support "tekrar yap" / "yeniden yap" by reusing the last meaningful prompt in THIS session
        if clean in ("tekrar yap", "yeniden yap", "aynısını yap", "tekrarla", "tekrar") and last_for_scope:
            prompt = last_for_scope
            clean = prompt.strip().lower()
        else:
            if session_id:
                self._session_last_prompts[session_id] = prompt
            else:
                self._last_prompt = prompt

        intent = self.parse_musical_intent(prompt)
        disclosure = self.model_provider.build_context_prompt(
            user_prompt=prompt,
            project_context=project_context,
            recent_history=active_history if session_id else None,
            user_preferences=asdict(self.memory.preferences),
            conversation_history=conversation_history,
        )

        actions: List[ActionDefinition] = []
        composition: Optional[CompositionBundle] = None
        rhythm: Optional[RhythmBundle] = None
        arrangement: Optional[ArrangementPlan] = None
        sound_design: Optional[SoundDesignPlan] = None
        limitations: List[str] = []
        llm_explanation: Optional[str] = None
        session_history_entry: Optional[Dict[str, Any]] = None

        # Try OpenAI GPT-4o live producer planning when API key is configured in .env
        llm_spec: Optional[Dict[str, Any]] = None
        if not dry_run and midi_export_dir is None:
            llm_spec = self.model_provider.generate_music_plan(
                user_prompt=prompt,
                project_context=project_context,
                user_preferences=asdict(self.memory.preferences),
                recent_history=active_history,
                conversation_history=conversation_history,
            )

        if llm_spec:
            llm_explanation = str(llm_spec.get("ai_response", "")).strip() or None
            if llm_spec.get("intent_type") == "chat_only":
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.READ_PROJECT_STATE,
                        description="Read current FL Studio project state",
                        parameters={},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )
            else:
                eff_genre = str(llm_spec.get("genre") or intent.genre or self.memory.preferences.preferred_genre)
                eff_mood = str(llm_spec.get("mood") or "dark").strip().lower()
                eff_bpm = float(llm_spec.get("tempo_bpm") or intent.tempo_bpm or self.memory.preferences.preferred_bpm)
                eff_key = str(llm_spec.get("key") or intent.key or self.memory.preferences.preferred_root)
                eff_scale = str(llm_spec.get("scale") or intent.scale or self.memory.preferences.preferred_scale)

                intent.genre = eff_genre
                intent.tempo_bpm = eff_bpm
                intent.key = eff_key
                intent.scale = eff_scale

                # 1. Read project context
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.READ_PROJECT_STATE,
                        description="Read current FL Studio project state",
                        parameters={},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.READ_CHANNELS,
                        description="Read FL Studio Channel Rack channels",
                        parameters={},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )

                # 2. Set Tempo
                if llm_spec.get("tempo_bpm") is not None:
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_TEMPO,
                            description=f"[AI] Set project tempo to {eff_bpm} BPM ({eff_genre})",
                            parameters={"bpm": float(eff_bpm), "tolerance": 0.05},
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

                # 3. Create dedicated Pattern 1 for Drums (when drums are present) + Sound Design
                raw_drums = llm_spec.get("drum_channels") or []
                pat_counter = 1
                if isinstance(raw_drums, list) and raw_drums:
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.CREATE_PATTERN,
                            description=f"[AI] Create Drums pattern '01 · {eff_key}_{eff_scale}_Drums'",
                            parameters={"name": f"01 · {eff_key}_{eff_scale}_Drums", "role": "drums"},
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )
                    pat_counter = 2

                # 3b. Channel Sound / Volume / Pan shaping (Sound Design)
                raw_ch_mix = llm_spec.get("channel_mix") or []
                if isinstance(raw_ch_mix, list) and raw_ch_mix:
                    for cm in raw_ch_mix:
                        if not isinstance(cm, dict):
                            continue
                        ch_idx = int(cm.get("channel", 0))
                        ch_name = str(cm.get("name", f"Channel {ch_idx}"))
                        if "volume" in cm and cm["volume"] is not None:
                            ch_vol = max(0.0, min(1.0, float(cm["volume"])))
                            actions.append(
                                ActionDefinition(
                                    task_id=t_id,
                                    action_type=ActionType.SET_CHANNEL_VOLUME,
                                    description=f"[AI] Set {ch_name} (Ch {ch_idx}) volume to {int(ch_vol * 100)}%",
                                    parameters={"channel": ch_idx, "value": ch_vol, "unit": "normalized"},
                                    risk_level=ActionRiskLevel.MEDIUM,
                                )
                            )
                        if "pan" in cm and cm["pan"] is not None and abs(float(cm["pan"])) > 0.01:
                            ch_pan = max(-1.0, min(1.0, float(cm["pan"])))
                            actions.append(
                                ActionDefinition(
                                    task_id=t_id,
                                    action_type=ActionType.SET_CHANNEL_PAN,
                                    description=f"[AI] Set {ch_name} (Ch {ch_idx}) stereo pan to {ch_pan:+.2f}",
                                    parameters={"channel": ch_idx, "value": ch_pan},
                                    risk_level=ActionRiskLevel.MEDIUM,
                                )
                            )

                # 4. Expand 1-bar Drums cleanly into cohesive 4-bar groove (64 steps + Bar-4 turnaround fill)
                if isinstance(raw_drums, list) and raw_drums:
                    for ch_obj in raw_drums:
                        if not isinstance(ch_obj, dict):
                            continue
                        ch_idx = int(ch_obj.get("channel", 0))
                        ch_name = str(ch_obj.get("name", f"Channel {ch_idx}"))
                        src_len = max(8, min(64, int(ch_obj.get("length", 16) or 16)))
                        raw_steps = ch_obj.get("steps") or []
                        base_steps = sorted({int(s) for s in raw_steps if isinstance(s, (int, float)) and 0 <= int(s) < src_len})
                        if src_len <= 16:
                            steps_4bar = sorted({bar * 16 + s for bar in range(4) for s in base_steps})
                            low_ch = ch_name.lower()
                            if any(w in low_ch for w in ("snare", "perc", "clap")):
                                # Cohesive Bar-4 turnaround fill leading back into Bar 1
                                for fill_s in (60, 62):
                                    if fill_s not in steps_4bar:
                                        steps_4bar.append(fill_s)
                                steps_4bar.sort()
                            target_len = 64
                            steps = steps_4bar
                        else:
                            target_len = src_len
                            steps = base_steps
                        pattern_str = "".join("x" if i in steps else "." for i in range(target_len))
                        actions.append(
                            ActionDefinition(
                                task_id=t_id,
                                action_type=ActionType.SET_STEP_GRID,
                                description=f"[AI] Set {ch_name} (Ch {ch_idx}) 4-bar groove ({target_len} steps)",
                                parameters={
                                    "channel": ch_idx,
                                    "steps": steps,
                                    "pattern": pattern_str,
                                    "length": target_len,
                                },
                                risk_level=ActionRiskLevel.MEDIUM,
                            )
                        )

                from ..music_engine.mix_master import MixMasterEngine
                mix_engine = MixMasterEngine()

                # Record in session history so consecutive AI turns in THIS chat remember context
                session_history_entry = {
                    "prompt": prompt[:140],
                    "genre": eff_genre,
                    "tempo_bpm": eff_bpm,
                    "key": eff_key,
                    "scale": eff_scale,
                    "instrument_name": llm_spec.get("instrument_name"),
                    "chord_progression": list(llm_spec.get("chord_progression") or [])[:6],
                    "instruments": [
                        str(t.get("instrument_name"))
                        for t in (llm_spec.get("tracks") or [])
                        if isinstance(t, dict) and t.get("instrument_name")
                    ],
                }
                if session_id:
                    s_hist = self._session_histories.setdefault(session_id, [])
                    s_hist.append(session_history_entry)
                    if len(s_hist) > 6:
                        self._session_histories[session_id] = s_hist[-6:]
                else:
                    self._recent_history.append(session_history_entry)
                    if len(self._recent_history) > 6:
                        self._recent_history = self._recent_history[-6:]

                # 5. Load Multi-Track Generator Instruments, Write Dedicated Patterns & Route to Mixer Inserts
                role_tracks: Dict[str, int] = {"master": 0}
                if raw_drums:
                    role_tracks["drums"] = mix_engine.get_mixer_track_for_role("drums")

                tracks_spec = list(llm_spec.get("tracks") or [])
                if not tracks_spec:
                    inst_name = str(llm_spec.get("instrument_name") or "FL Keys").strip()
                    raw_notes = llm_spec.get("melody_notes") or []
                    if raw_notes:
                        tracks_spec.append({
                            "role": "lead",
                            "instrument_name": inst_name,
                            "fallbacks": ["FLEX", "Sytrus", "3x Osc"],
                            "notes": raw_notes,
                        })

                # 5a. Load instrument + create dedicated Pattern per melodic role + write MIDI FIRST
                # (keeps Piano Roll retargeting from stealing focus before Mixer routing)
                routable_tracks: List[Tuple[str, str, int]] = []
                for trk in tracks_spec[:4]:
                    if not isinstance(trk, dict):
                        continue
                    role = str(trk.get("role") or "lead").strip().lower()
                    t_inst = str(trk.get("instrument_name") or "FLEX").strip()
                    t_fbs = [str(f) for f in (trk.get("fallbacks") or []) if f]
                    raw_notes = trk.get("notes") or []
                    valid_notes = []
                    for n in raw_notes:
                        if isinstance(n, dict) and "pitch" in n:
                            n_dict: Dict[str, Any] = {
                                "pitch": max(21, min(108, int(n.get("pitch", 60)))),
                                "time_bars": max(0.0, float(n.get("time_bars", 0.0))),
                                "length_bars": max(0.0625, float(n.get("length_bars", 0.25))),
                                "velocity": max(0.1, min(1.0, float(n.get("velocity", 0.85)))),
                            }
                            if n.get("porta") is True:
                                n_dict["porta"] = True
                            valid_notes.append(n_dict)
                    if not valid_notes:
                        continue

                    max_bar_span = max(
                        4,
                        min(8, int(max((n["time_bars"] + n["length_bars"]) for n in valid_notes) + 0.99)),
                    )
                    mixer_track = mix_engine.get_mixer_track_for_role(role)
                    role_tracks[role] = mixer_track
                    routable_tracks.append((role, t_inst, mixer_track))
                    pat_label = f"{pat_counter:02d} · {role.title()} ({t_inst})"
                    pat_counter += 1

                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.LOAD_PLUGIN_PRESET,
                            description=f"[Canlı GUI · {role.upper()}] '{t_inst}' eklentisini yükle ve seç",
                            parameters={
                                "plugin_name": t_inst,
                                "instrument_name": t_inst,
                                "role": role,
                                "fallbacks": t_fbs,
                                "preset_hint": trk.get("preset_hint", "Default"),
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_PLUGIN_PARAM,
                            description=f"[Synth Ayarı · {role.upper()}] '{t_inst}' preset ve synth parametrelerini ayarla",
                            parameters={
                                "slot": -1,
                                "role": role,
                                "plugin_name": t_inst,
                                "preset_hint": trk.get("preset_hint") or f"{eff_mood} {eff_genre} {role}",
                                "generator_params": trk.get("generator_params") or {},
                                "mix_cfg": {
                                    **(llm_spec.get("mix") or {}),
                                    "mood": eff_mood,
                                    "genre": eff_genre,
                                },
                                "fallback_step": ((len(active_history) + pat_counter) % 6) + 1,
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.CREATE_PATTERN,
                            description=f"[Pattern] '{pat_label}' desenini oluştur ve seç",
                            parameters={"name": pat_label, "role": role},
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.CREATE_MIDI_PATTERN,
                            description=f"[AI · {role.upper()}] {eff_key} {eff_scale} ({len(valid_notes)} nota) '{t_inst}' Piano Roll'a yaz",
                            parameters={
                                "notes": valid_notes,
                                "instrument_name": t_inst,
                                "role": role,
                                "fallbacks": t_fbs,
                                "bars": max_bar_span,
                                "mode": "replace",
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

                # 5b. Route each loaded channel to its dedicated Mixer Insert together
                for role, t_inst, mixer_track in routable_tracks:
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_MIXER_ROUTING,
                            description=f"[Mix Routing · {role.upper()}] '{t_inst}' kanalını Mixer Insert {mixer_track}'e yönlendir",
                            parameters={
                                "role": role,
                                "mixer_track": mixer_track,
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

                # 5c. Paint Multi-Section Arrangement onto Main Song Playlist
                raw_sections = llm_spec.get("sections") or [{"name": "Intro", "bars": 4}, {"name": "Drop", "bars": 8}]
                clean_sections: List[Dict[str, Any]] = []
                for s in raw_sections:
                    if not isinstance(s, dict):
                        continue
                    sec_item: Dict[str, Any] = {
                        "name": str(s.get("name", "Section")),
                        "bars": max(1, int(s.get("bars", 4) or 4)),
                    }
                    if s.get("mode"):
                        sec_item["mode"] = str(s["mode"])
                    if isinstance(s.get("roles"), list) and s["roles"]:
                        sec_item["roles"] = [str(r).strip().lower() for r in s["roles"] if str(r).strip()]
                    clean_sections.append(sec_item)
                if not clean_sections:
                    clean_sections = [{"name": f"{eff_key}_{eff_scale}_Song", "bars": 8}]
                clear_pl = str(llm_spec.get("intent_type") or "full_production").lower() != "edit"
                cur_bar = 1
                for s_idx, sec in enumerate(clean_sections[:4]):
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.ADD_ARRANGEMENT_MARKER,
                            description=(
                                f"[Playlist] '{sec['name']}' bölüm işaretini ekle ve desenleri Ana Şarkıya diz"
                                if s_idx == 0
                                else f"[Playlist] '{sec['name']}' bölüm işaretini Bar {cur_bar}'e ekle"
                            ),
                            parameters={
                                "bar": cur_bar,
                                "name": sec["name"],
                                "paint_playlist": (s_idx == 0),
                                "clear_playlist": (clear_pl if s_idx == 0 else False),
                                "sections": clean_sections if s_idx == 0 else None,
                                "bars": sec["bars"],
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )
                    cur_bar += sec["bars"]

                # 6. Mixer Naming, Colors, Real FX Plugin Chains & Parameter Tuning
                fx_plan = llm_spec.get("fx_plan") if isinstance(llm_spec.get("fx_plan"), dict) else {}
                fx_params = llm_spec.get("fx_params") if isinstance(llm_spec.get("fx_params"), dict) else {}
                mix_cfg = llm_spec.get("mix") if isinstance(llm_spec.get("mix"), dict) else {"enabled": True}

                ordered_mix_roles = [r for r in role_tracks.keys() if r != "master"] + ["master"]
                for role in ordered_mix_roles:
                    m_track = role_tracks[role]
                    meta = mix_engine.get_track_meta_for_role(role)
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_MIXER_TRACK_META,
                            description=f"[Mix] Mixer Track {m_track} -> '{meta['name']}' isim & renk ayarla",
                            parameters={
                                "track": m_track,
                                "role": role,
                                "name": meta["name"],
                                "color": [meta["r"], meta["g"], meta["b"]],
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )
                    fx_fallbacks_map = {
                        "fruity reeverb 2": ["Fruity Delay 3", "Fruity Convolver"],
                        "fruity parametric eq 2": ["Fruity 7 Band EQ", "Fruity Parametric EQ"],
                        "fruity compressor": ["Fruity Limiter", "Maximus"],
                        "fruity limiter": ["Fruity Soft Clipper", "Maximus"],
                        "fruity soft clipper": ["Fruity Limiter", "Soundgoodizer"],
                        "fruity delay 3": ["Fruity Delay 2", "Fruity Reeverb 2"],
                        "soundgoodizer": ["Maximus", "Fruity Limiter"],
                        "fruity chorus": ["Fruity Flanger", "Fruity Phaser"],
                    }
                    role_fx = list(fx_plan.get(role) or [])
                    fx_cap = 3 if role == "master" else 2
                    for fx_name in role_fx[:fx_cap]:
                        fx_str = str(fx_name)
                        actions.append(
                            ActionDefinition(
                                task_id=t_id,
                                action_type=ActionType.LOAD_MIXER_EFFECT,
                                description=f"[FX Plugin · T{m_track} {role.upper()}] '{fx_str}' efektini yükle",
                                parameters={
                                    "mixer_track": m_track,
                                    "role": role,
                                    "plugin_name": fx_str,
                                    "fallbacks": fx_fallbacks_map.get(fx_str.strip().lower(), []),
                                },
                                risk_level=ActionRiskLevel.MEDIUM,
                            )
                        )
                    if role_fx:
                        actions.append(
                            ActionDefinition(
                                task_id=t_id,
                                action_type=ActionType.SET_PLUGIN_PARAM,
                                description=f"[FX Tuning · T{m_track} {role.upper()}] Yüklenen FX plugin parametrelerini ayarla",
                                parameters={
                                    "track": m_track,
                                    "mixer_track": m_track,
                                    "role": role,
                                    "fx_params": fx_params.get(role, {}),
                                    "mix_cfg": mix_cfg,
                                },
                                risk_level=ActionRiskLevel.MEDIUM,
                            )
                        )

                # Explicit Master volume if specifically requested outside auto-mix
                mix_vol = llm_spec.get("mixer_volume")
                if isinstance(mix_vol, (int, float)):
                    vol_val = max(0.05, min(1.0, float(mix_vol)))
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_MIXER_VOLUME,
                            description=f"[AI] Set Master Mixer volume to {int(vol_val * 100)}%",
                            parameters={"track": 0, "value": vol_val, "unit": "normalized"},
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

                # 7. Transport Playback + Live Peak-Metered Auto-Mix & Mastering
                play_st = llm_spec.get("play_state")
                if play_st == "play":
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_PLAY_STATE,
                            description="[AI] Canlı peak ölçümü ve Song Mode dinleme için oynatmayı başlat",
                            parameters={"state": "play", "loop_mode": "song", "rewind": True},
                            risk_level=ActionRiskLevel.LOW,
                        )
                    )

                if mix_cfg.get("enabled", True):
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.AUTO_MIX_MASTER,
                            description="[Mix & Master] Pan, seviye dengeleme ve -1 dBFS Master peak kontrolü uygula",
                            parameters={
                                "role_tracks": role_tracks,
                                "mix_cfg": mix_cfg,
                                "fx_params": fx_params,
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

                if play_st == "stop":
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_PLAY_STATE,
                            description="[AI] Set FL Studio transport playback to 'stop'",
                            parameters={"state": "stop"},
                            risk_level=ActionRiskLevel.LOW,
                        )
                    )

        # CASE A: Full multi-step production request (Deterministic fallback & offline tests)
        elif intent.is_full_production_request:
            eff_genre = intent.genre or self.memory.preferences.preferred_genre
            eff_bpm = intent.tempo_bpm or self.memory.preferences.preferred_bpm
            eff_key = intent.key or self.memory.preferences.preferred_root
            eff_scale = intent.scale or self.memory.preferences.preferred_scale

            # 1. Read project context first
            actions.append(
                ActionDefinition(
                    task_id=t_id,
                    action_type=ActionType.READ_PROJECT_STATE,
                    description="Read current FL Studio project state before applying production plan",
                    parameters={},
                    risk_level=ActionRiskLevel.LOW,
                )
            )
            actions.append(
                ActionDefinition(
                    task_id=t_id,
                    action_type=ActionType.READ_CHANNELS,
                    description="Read FL Studio Channel Rack channels",
                    parameters={},
                    risk_level=ActionRiskLevel.LOW,
                )
            )

            # 2. Set Tempo if requested or defined by genre
            if intent.tempo_bpm is not None or eff_bpm:
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_TEMPO,
                        description=f"Set project tempo to {eff_bpm} BPM ({eff_genre})",
                        parameters={"bpm": float(eff_bpm), "tolerance": 0.05},
                        risk_level=ActionRiskLevel.MEDIUM,
                    )
                )

            # 3. Arrangement sections & patterns (Intro, Drop, etc.)
            if intent.sections:
                custom_secs = [
                    {"name": s, "bars": 16 if s.lower() == "drop" else 8}
                    for s in intent.sections
                ]
                arrangement = self.arranger.create_arrangement(
                    task_id=t_id,
                    genre=eff_genre,
                    custom_sections=custom_secs,
                )
                actions.extend(arrangement.planned_actions)

            # 4. Drum & Percussion Rhythm programming
            if any(e in intent.requested_elements for e in ("kick", "percussion")):
                rhythm = self.rhythm_agent.build_rhythm(
                    task_id=t_id,
                    genre=eff_genre,
                    tempo_bpm=eff_bpm,
                    steps=16,
                )
                actions.extend(rhythm.planned_actions)

            # 5. Harmonic & Melodic Composition (Bassline, Lead Melody, Chords)
            if any(e in intent.requested_elements for e in ("bass", "lead_melody", "chords")) or intent.genre:
                composition = self.composer.compose(
                    genre=eff_genre,
                    root=eff_key,
                    scale=eff_scale,
                    tempo_bpm=eff_bpm,
                    bars=4,
                    humanize=True,
                    export_dir=midi_export_dir,
                )
                limitations.append(
                    "Multi-track polyphonic Piano Roll notes (chords, bassline, lead melody) are generated, "
                    "validated for key/scale, and exported as standard .mid files so they can be imported or "
                    "dragged onto target synth instruments without overwriting unrelated channels."
                )
                if not dry_run and midi_export_dir is None:
                    target_notes = [n.model_dump() for n in composition.melody.notes]
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.CREATE_MIDI_PATTERN,
                            description=f"Apply {composition.root} {composition.scale} melody notes ({len(target_notes)} notes) to FL Studio Piano Roll",
                            parameters={
                                "notes": target_notes,
                                "bars": 4,
                                "mode": "replace",
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

            # 6. Sound Design & Mixer balance recommendations
            sound_design = self.sound_designer.create_sound_plan(task_id=t_id, genre=eff_genre)
            if any(w in clean for w in ("yüksek ses", "yuksek ses", "sesini aç", "loud", "boost")):
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_MIXER_VOLUME,
                        description="Boost Master mixer track volume to 92% (high volume requested)",
                        parameters={"track": 0, "value": 0.92, "unit": "normalized"},
                        risk_level=ActionRiskLevel.MEDIUM,
                    )
                )
            elif any(w in clean for w in ("kısık", "kisik", "düşük ses", "sesini kıs", "quiet")):
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_MIXER_VOLUME,
                        description="Lower Master mixer track volume to 55%",
                        parameters={"track": 0, "value": 0.55, "unit": "normalized"},
                        risk_level=ActionRiskLevel.MEDIUM,
                    )
                )

            if not dry_run and midi_export_dir is None:
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_PLAY_STATE,
                        description="Start FL Studio transport playback to audition the generated beat",
                        parameters={"state": "play"},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )

        # CASE B: Single-operation commands (backward compatible with Phase 4 unit tests)
        else:
            bpm_match = (
                re.search(r"(?:set|change)?\s*(?:tempo|bpm)\s*(?:to|=)?\s*(\d+(?:\.\d+)?)", clean)
                or re.search(r"(\d{2,3}(?:\.\d+)?)\s*bpm", clean)
            )
            if bpm_match:
                bpm_val = float(bpm_match.group(1))
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_TEMPO,
                        description=f"Change project tempo to {bpm_val} BPM",
                        parameters={"bpm": bpm_val, "tolerance": 0.05},
                        risk_level=ActionRiskLevel.MEDIUM,
                    )
                )

            elif any(k in clean for k in ("drum", "beat", "kick", "4-on-the-floor", "four on the floor", "house beat", "trap beat")):
                style = "four_on_the_floor"
                if "trap" in clean:
                    style = "trap"
                elif "boom bap" in clean or "boombap" in clean:
                    style = "boom_bap"
                elif "techno" in clean:
                    style = "techno"

                dp = generate_drum_pattern(style=style, length=16)
                for ch in dp.channels:
                    if ch.steps:
                        ch_idx = 0
                        if "kick" in ch.channel_name.lower():
                            ch_idx = 0
                        elif "clap" in ch.channel_name.lower():
                            ch_idx = 1
                        elif "hihat" in ch.channel_name.lower() or "hat" in ch.channel_name.lower():
                            ch_idx = 2
                        elif "snare" in ch.channel_name.lower():
                            ch_idx = 3

                        actions.append(
                            ActionDefinition(
                                task_id=t_id,
                                action_type=ActionType.SET_STEP_GRID,
                                description=f"Set {ch.channel_name} step grid ({style}): {ch.pattern_string}",
                                parameters={
                                    "channel": ch_idx,
                                    "steps": ch.steps,
                                    "pattern": ch.pattern_string,
                                    "length": ch.length,
                                },
                                risk_level=ActionRiskLevel.MEDIUM,
                            )
                        )

            elif "mixer" in clean or "volume" in clean:
                vol_match = re.search(r"(?:track|mixer)\s*(\d+).*?(?:volume|vol).*?(-?\d+(?:\.\d+)?)", clean)
                if vol_match:
                    track_idx = int(vol_match.group(1))
                    val = float(vol_match.group(2))
                    unit = "db" if "db" in clean else "normalized"
                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_MIXER_VOLUME,
                            description=f"Set mixer track {track_idx} volume to {val} ({unit})",
                            parameters={"track": track_idx, "value": val, "unit": unit},
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

            elif "play" in clean:
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_PLAY_STATE,
                        description="Start FL Studio transport playback",
                        parameters={"state": "play"},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )
            elif "stop" in clean:
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_PLAY_STATE,
                        description="Stop FL Studio transport playback",
                        parameters={"state": "stop"},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )

            elif any(k in clean for k in ("melodi", "melody", "lead", "motif", "akor", "chord", "bassline", "piyano", "piano")):
                bar_match = re.search(r"(\d+)\s*bar", clean)
                bars = int(bar_match.group(1)) if bar_match else 4
                eff_genre = intent.genre or self.memory.preferences.preferred_genre
                eff_bpm = intent.tempo_bpm or self.memory.preferences.preferred_bpm
                eff_key = intent.key or self.memory.preferences.preferred_root
                eff_scale = intent.scale or self.memory.preferences.preferred_scale

                composition = self.composer.compose(
                    genre=eff_genre,
                    root=eff_key,
                    scale=eff_scale,
                    tempo_bpm=eff_bpm,
                    bars=bars,
                    humanize=True,
                    export_dir=midi_export_dir,
                )
                target_notes = [n.model_dump() for n in composition.melody.notes]
                motif_steps = sorted({int(round((n.time_bars % 1.0) * 16)) % 16 for n in composition.melody.notes}) or [0, 3, 6, 8, 10, 12, 14]
                pattern_str = "".join("x" if i in motif_steps else "." for i in range(16))
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.READ_PROJECT_STATE,
                        description="Read current FL Studio project state",
                        parameters={},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_STEP_GRID,
                        description=f"Activate rhythmic motif steps on Channel 0: {pattern_str}",
                        parameters={
                            "channel": 0,
                            "steps": motif_steps,
                            "pattern": pattern_str,
                            "length": 16,
                        },
                        risk_level=ActionRiskLevel.MEDIUM,
                    )
                )
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.CREATE_MIDI_PATTERN,
                        description=f"Compose & apply {bars}-bar {composition.root} {composition.scale} melody motif ({len(target_notes)} notes) to Piano Roll",
                        parameters={
                            "notes": target_notes,
                            "bars": bars,
                            "mode": "replace",
                        },
                        risk_level=ActionRiskLevel.MEDIUM,
                    )
                )
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_PLAY_STATE,
                        description="Start FL Studio transport playback to audition motif",
                        parameters={"state": "play"},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )

            if not actions:
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.READ_PROJECT_STATE,
                        description="Read current FL Studio project state",
                        parameters={},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.READ_CHANNELS,
                        description="Read FL Studio channel rack channels",
                        parameters={},
                        risk_level=ActionRiskLevel.LOW,
                    )
                )

        # Enforce bounded action limit
        if len(actions) > self.max_actions_per_plan:
            truncated_count = len(actions) - self.max_actions_per_plan
            actions = actions[: self.max_actions_per_plan]
            limitations.append(
                f"Plan exceeded bounded limit of {self.max_actions_per_plan} actions; "
                f"{truncated_count} trailing actions were deferred."
            )

        requires_approval = any(
            a.risk_level in (ActionRiskLevel.HIGH, ActionRiskLevel.DESTRUCTIVE) or a.requires_approval
            for a in actions
        )

        return ActionPlan(
            plan_id=p_id,
            task_id=t_id,
            prompt=prompt,
            actions=actions,
            dry_run=dry_run,
            requires_approval=requires_approval,
            parsed_intent=intent,
            composition=composition,
            rhythm=rhythm,
            arrangement=arrangement,
            sound_design=sound_design,
            prompt_disclosure=disclosure,
            llm_explanation=llm_explanation,
            remaining_limitations=limitations,
            session_id=session_id,
            session_history_entry=session_history_entry,
        )

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.event_callback is not None:
            try:
                self.event_callback({"type": event_type, **payload})
            except Exception:
                pass

    async def execute_plan(
        self,
        plan: ActionPlan,
        cancel_event: Optional[asyncio.Event] = None,
        prefer_mock: bool = False,
        render_settings: Optional[RenderSettings] = None,
    ) -> PlanExecutionResult:
        """Execute all actions in the plan sequentially with bounded loops, verification, and summary recording."""
        logger.info("Executing plan %s (dry_run=%s, actions=%d)", plan.plan_id, plan.dry_run, len(plan.actions))
        self._emit_event("PLAN_STARTED", {"plan_id": plan.plan_id, "task_id": plan.task_id, "action_count": len(plan.actions)})

        if plan.dry_run:
            logger.info("Dry run requested; plan generated without executing DAW mutations.")
            return PlanExecutionResult(
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                success=True,
                actions_executed=0,
                actions_succeeded=0,
                actions_failed=0,
                actions_awaiting_approval=0,
                details=[
                    {
                        "action_id": a.action_id,
                        "type": a.action_type,
                        "desc": a.description,
                        "status": "DRY_RUN_PREVIEW",
                    }
                    for a in plan.actions
                ],
                remaining_limitations=list(plan.remaining_limitations),
                exported_midi_files=dict(plan.composition.exported_midi_files) if plan.composition else {},
            )

        succeeded = 0
        verified_count = 0
        failed = 0
        awaiting = 0
        details: List[Dict[str, Any]] = []
        completed_summary: List[str] = []

        # Bounded execution loop
        bounded_actions = plan.actions[: self.max_actions_per_plan]
        for idx, action in enumerate(bounded_actions, start=1):
            if cancel_event and cancel_event.is_set():
                logger.info("Plan execution cancelled by user event.")
                action.transition_to(ActionLifecycleState.CANCELLED)
                break

            self._emit_event(
                "ACTION_STARTING",
                {
                    "plan_id": plan.plan_id,
                    "step": idx,
                    "total_steps": len(bounded_actions),
                    "action_id": action.action_id,
                    "action_type": action.action_type.value,
                    "description": action.description,
                },
            )

            executed_action = await self.executor.execute_action(
                action,
                cancel_event=cancel_event,
                prefer_mock=prefer_mock,
            )

            status = executed_action.status
            if executed_action.verified:
                verified_count += 1

            step_detail = {
                "action_id": executed_action.action_id,
                "action_type": executed_action.action_type.value,
                "description": executed_action.description,
                "status": status.value,
                "verified": executed_action.verified,
                "verification_detail": executed_action.verification_detail,
                "error": executed_action.error,
            }
            details.append(step_detail)
            self._emit_event("ACTION_COMPLETED", step_detail)

            if status == ActionLifecycleState.SUCCEEDED:
                succeeded += 1
                completed_summary.append(
                    f"{executed_action.description} -> {executed_action.verification_detail or 'Verified'}"
                )
            elif status == ActionLifecycleState.AWAITING_APPROVAL:
                awaiting += 1
                logger.info("Action %s requires approval; halting subsequent plan steps.", action.action_id)
                break
            else:
                failed += 1
                logger.warning("Action %s failed with status %s; halting plan.", action.action_id, status)
                break

        exported_midi: Dict[str, str] = {}
        if plan.composition:
            exported_midi = dict(plan.composition.exported_midi_files)
            completed_summary.append(
                f"Composed & validated {plan.composition.root} {plan.composition.scale} chords, bassline, and melody ({plan.composition.bars} bars)."
            )

        # Optional Render + Critic evaluation if requested
        critic_report: Optional[CriticFeedbackReport] = None
        if render_settings is not None and failed == 0 and awaiting == 0:
            if os.path.isfile(render_settings.output_path):
                analysis = AudioAnalyzer().analyze_file(render_settings.output_path)
                critic_report = self.critic.evaluate_render(analysis, task_id=plan.task_id)
                completed_summary.append(
                    f"Analyzed render '{os.path.basename(render_settings.output_path)}' -> Critic health: {critic_report.overall_health}"
                )

        overall_success = (failed == 0 and awaiting == 0)

        # Persist task summary in ProjectMemoryManager
        summary_record = TaskSummaryRecord(
            task_id=plan.task_id,
            plan_id=plan.plan_id,
            prompt=plan.prompt,
            parsed_intent=asdict(plan.parsed_intent) if plan.parsed_intent else {},
            actions_planned=len(bounded_actions),
            actions_succeeded=succeeded,
            actions_verified=verified_count,
            actions_failed=failed,
            actions_awaiting_approval=awaiting,
            completed_steps=completed_summary,
            exported_midi_files=exported_midi,
            remaining_limitations=list(plan.remaining_limitations),
            critic_summary=critic_report.overall_health if critic_report else None,
        )
        self.memory.record_task_summary(summary_record)

        return PlanExecutionResult(
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            success=overall_success,
            actions_executed=succeeded + failed + awaiting,
            actions_succeeded=succeeded,
            actions_failed=failed,
            actions_awaiting_approval=awaiting,
            details=details,
            completed_summary=completed_summary,
            remaining_limitations=list(plan.remaining_limitations),
            exported_midi_files=exported_midi,
            critic_feedback=critic_report,
        )
