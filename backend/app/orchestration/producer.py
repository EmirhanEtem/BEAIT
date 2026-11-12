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
from typing import Any, Callable, Dict, List, Optional

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

MAX_BOUNDED_PLAN_ACTIONS = 32


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
    remaining_limitations: List[str] = field(default_factory=list)
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
        db: Optional[DatabaseManager] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        memory: Optional[ProjectMemoryManager] = None,
        model_provider: Optional[ModelProviderAdapter] = None,
        max_actions_per_plan: int = MAX_BOUNDED_PLAN_ACTIONS,
    ):
        self.db = db or DatabaseManager()
        self.fl_adapter = fl_adapter
        self.executor = executor or ActionExecutor(db=self.db, fl_adapter=fl_adapter)
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
        elif "deep house" in lower or "house" in lower:
            genre = "deep_house"
        elif "trap" in lower:
            genre = "trap_dark"
        elif "boom bap" in lower or "boombap" in lower:
            genre = "boom_bap_chill"
        elif "techno" in lower or "tekno" in lower:
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
    ) -> ActionPlan:
        """Parse natural language command and produce a bounded, structured ActionPlan."""
        t_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        p_id = f"plan_{uuid.uuid4().hex[:8]}"
        clean = prompt.strip().lower()

        intent = self.parse_musical_intent(prompt)
        disclosure = self.model_provider.build_context_prompt(
            user_prompt=prompt,
            project_context=project_context,
            user_preferences=asdict(self.memory.preferences),
        )

        actions: List[ActionDefinition] = []
        composition: Optional[CompositionBundle] = None
        rhythm: Optional[RhythmBundle] = None
        arrangement: Optional[ArrangementPlan] = None
        sound_design: Optional[SoundDesignPlan] = None
        limitations: List[str] = []

        # CASE A: Full multi-step production request (e.g. Phase 8 benchmark prompt)
        if intent.is_full_production_request:
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

            # 6. Sound Design & Mixer balance recommendations
            sound_design = self.sound_designer.create_sound_plan(task_id=t_id, genre=eff_genre)

        # CASE B: Single-operation commands (backward compatible with Phase 4 unit tests)
        else:
            bpm_match = re.search(r"(?:set|change)?\s*(?:tempo|bpm)\s*(?:to|=)?\s*(\d+(?:\.\d+)?)", clean)
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
            remaining_limitations=limitations,
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
