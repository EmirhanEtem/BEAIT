"""Phase 8 Tests: Producer Orchestrator, Model Provider Privacy, Project Memory, and End-to-End Workflow."""

from __future__ import annotations

import os
import tempfile
import pytest

from app.action_router.executor import ActionExecutor
from app.database.persistence import DatabaseManager
from app.integrations.audio import RenderSettings
from app.model_providers import ModelProviderAdapter, ProviderConfig, redact_secrets
from app.orchestration.producer import ProducerOrchestrator
from app.project_memory import ProjectMemoryManager
from app.schemas.actions import ActionLifecycleState, ActionType


PHASE8_BENCHMARK_PROMPT = (
    "FL Studio'da 128 BPM, A minor tonunda melodic techno başlangıcı oluştur. "
    "Kick ve percussion düzenini kur, bassline ve ana melodiyi yaz, "
    "sonra kısa bir intro ve drop arrangement'ı hazırla."
)


class TestModelProviderAndPrivacy:
    def test_secret_redaction_and_safe_config(self):
        raw = "Error calling OpenAI with key sk-proj1234567890abcdef and Bearer secret_token_999"
        cleaned = redact_secrets(raw)
        assert "sk-proj1234567890abcdef" not in cleaned
        assert "secret_token_999" not in cleaned
        assert "[REDACTED_SECRET]" in cleaned

        cfg = ProviderConfig(
            provider_name="openai",
            model_name="gpt-4o",
            api_key="sk-live9876543210secret",
        )
        safe_dict = cfg.to_safe_dict()
        assert safe_dict["api_key_configured"] is True
        assert safe_dict["api_key_preview"] == "[REDACTED_SECRET]"
        assert safe_dict["allow_audio_upload"] is False

    def test_context_prompt_disclosure(self):
        adapter = ModelProviderAdapter()
        ctx = {
            "bpm": 130.0,
            "playing": False,
            "channel_count": 4,
            "channels": [{"name": "808 Kick"}, {"name": "808 Clap"}],
        }
        envelope = adapter.build_context_prompt(
            user_prompt="Set tempo to 128 BPM",
            project_context=ctx,
        )
        assert envelope.audio_or_project_files_attached is False
        assert "user_prompt" in envelope.disclosed_fields
        assert "project_context.bpm" in envelope.disclosed_fields
        assert "project_context.channel_names" in envelope.disclosed_fields
        assert "808 Kick" in envelope.prompt_text


class TestProjectMemory:
    def test_project_memory_persistence_roundtrip(self, tmp_path):
        mem_file = str(tmp_path / "project_memory.json")
        mem = ProjectMemoryManager(storage_path=mem_file)
        mem.update_preferences(
            preferred_genre="deep_house",
            preferred_bpm=122.0,
            preferred_root="C",
            preferred_scale="dorian",
        )

        reloaded = ProjectMemoryManager(storage_path=mem_file)
        assert reloaded.preferences.preferred_genre == "deep_house"
        assert reloaded.preferences.preferred_bpm == 122.0
        assert reloaded.preferences.preferred_root == "C"
        assert reloaded.preferences.preferred_scale == "dorian"


class TestPhase8EndToEndWorkflow:
    @pytest.mark.asyncio
    async def test_phase8_acceptance_prompt_end_to_end(self, tmp_path):
        db_path = str(tmp_path / "e2e_phase8.db")
        midi_dir = str(tmp_path / "midi_out")
        mem_path = str(tmp_path / "memory.json")

        db = DatabaseManager(db_path=db_path)
        executor = ActionExecutor(db=db)
        memory = ProjectMemoryManager(storage_path=mem_path)
        emitted_events: list[dict] = []

        orchestrator = ProducerOrchestrator(
            executor=executor,
            db=db,
            memory=memory,
            event_callback=lambda ev: emitted_events.append(ev),
        )

        # 1. Create the full production plan from the Turkish benchmark prompt
        plan = orchestrator.create_plan(
            PHASE8_BENCHMARK_PROMPT,
            project_context={"bpm": 130.0, "channel_count": 4},
            midi_export_dir=midi_dir,
        )

        # Verify parsed intent
        intent = plan.parsed_intent
        assert intent is not None
        assert intent.is_full_production_request is True
        assert intent.genre == "melodic_techno"
        assert intent.tempo_bpm == 128.0
        assert intent.key == "A"
        assert intent.scale == "natural_minor"
        assert "kick" in intent.requested_elements
        assert "percussion" in intent.requested_elements
        assert "bass" in intent.requested_elements
        assert "lead_melody" in intent.requested_elements
        assert intent.sections == ["Intro", "Drop"]

        # Verify specialist outputs attached to plan
        assert plan.composition is not None
        assert plan.composition.is_valid is True
        assert plan.composition.root == "A"
        assert plan.composition.scale == "natural_minor"
        assert set(plan.composition.exported_midi_files.keys()) == {"chords", "bassline", "melody"}
        for mpath in plan.composition.exported_midi_files.values():
            assert os.path.isfile(mpath)

        assert plan.rhythm is not None
        assert plan.rhythm.is_valid is True
        assert plan.arrangement is not None
        assert plan.arrangement.is_contiguous is True
        assert [s.name for s in plan.arrangement.sections] == ["Intro", "Drop"]
        assert plan.arrangement.total_bars == 24  # 8 bars Intro + 16 bars Drop

        # Verify planned action types cover context read, tempo, arrangement patterns/markers, and drum grids
        action_types = [a.action_type for a in plan.actions]
        assert ActionType.READ_PROJECT_STATE in action_types
        assert ActionType.READ_CHANNELS in action_types
        assert ActionType.SET_TEMPO in action_types
        assert ActionType.CREATE_PATTERN in action_types
        assert ActionType.ADD_ARRANGEMENT_MARKER in action_types
        assert ActionType.SET_STEP_GRID in action_types

        # Verify honest limitation reporting
        assert len(plan.remaining_limitations) >= 1
        assert any(".mid" in lim for lim in plan.remaining_limitations)

        # 2. Execute the plan end-to-end (with example render analysis connected)
        example_render = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "fixtures", "audio", "example_render.wav")
        )
        render_cfg = RenderSettings(output_path=example_render, overwrite_approved=True)

        result = await orchestrator.execute_plan(
            plan,
            prefer_mock=True,
            render_settings=render_cfg,
        )

        assert result.success is True
        assert result.actions_failed == 0
        assert result.actions_succeeded == len(plan.actions)
        assert all(d["status"] == ActionLifecycleState.SUCCEEDED.value for d in result.details)
        assert all(d["verified"] is True for d in result.details)

        # Live events were streamed to UI callback
        event_types = [e["type"] for e in emitted_events]
        assert "PLAN_STARTED" in event_types
        assert "ACTION_STARTING" in event_types
        assert "ACTION_COMPLETED" in event_types

        # Critic evaluated the render
        assert result.critic_feedback is not None
        assert result.critic_feedback.overall_health == "HEALTHY"

        # Task summary persisted in ProjectMemoryManager
        summaries = memory.get_recent_summaries()
        assert len(summaries) == 1
        assert summaries[0].task_id == plan.task_id
        assert summaries[0].actions_succeeded == len(plan.actions)
        assert summaries[0].critic_summary == "HEALTHY"
        assert len(summaries[0].remaining_limitations) >= 1

    def test_bounded_execution_loop_truncates_excess_actions(self, tmp_path):
        db = DatabaseManager(db_path=str(tmp_path / "bounded.db"))
        orchestrator = ProducerOrchestrator(
            db=db,
            max_actions_per_plan=4,
        )
        plan = orchestrator.create_plan(PHASE8_BENCHMARK_PROMPT)
        assert len(plan.actions) == 4
        assert any("bounded limit of 4 actions" in lim for lim in plan.remaining_limitations)

