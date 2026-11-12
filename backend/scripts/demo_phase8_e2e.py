"""Phase 8 End-to-End Demo Script.

Executes the specification benchmark prompt:
"FL Studio'da 128 BPM, A minor tonunda melodic techno başlangıcı oluştur.
Kick ve percussion düzenini kur, bassline ve ana melodiyi yaz,
sonra kısa bir intro ve drop arrangement'ı hazırla."

Connects to live FL Studio 2025 if running (with safe TestProjectSession baseline
capture and restore), or falls back transparently to mock mode if FL Studio is closed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from app.action_router.executor import ActionExecutor
from app.database.persistence import DatabaseManager
from app.integrations.audio import RenderSettings
from app.integrations.fl_studio.adapter import FLStudioAdapter
from app.orchestration.producer import ProducerOrchestrator
from app.project_memory import ProjectMemoryManager
from app.sessions.test_project import TestProjectSession


BENCHMARK_PROMPT = (
    "FL Studio'da 128 BPM, A minor tonunda melodic techno başlangıcı oluştur. "
    "Kick ve percussion düzenini kur, bassline ve ana melodiyi yaz, "
    "sonra kısa bir intro ve drop arrangement'ı hazırla."
)


async def run_demo() -> int:
    out_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "e2e_demo"))
    os.makedirs(out_dir, exist_ok=True)

    fl = FLStudioAdapter()
    health = fl.connect()
    live_fl = health.connected and health.fl_studio_alive
    print(f"[1] FL Studio Connection: connected={health.connected}, alive={health.fl_studio_alive} (mode={'LIVE_FL' if live_fl else 'MOCK'})")

    session = TestProjectSession(fl) if live_fl else None
    if session is not None:
        snap = await session.capture_baseline()
        print(f"[2] Captured safe FL Studio baseline snapshot: tempo={snap.tempo} BPM, channels={len(snap.step_grids)}")

    db = DatabaseManager(db_path=os.path.join(out_dir, "demo_e2e.db"))
    executor = ActionExecutor(db=db, fl_adapter=fl if live_fl else None)
    memory = ProjectMemoryManager(storage_path=os.path.join(out_dir, "demo_memory.json"))

    orchestrator = ProducerOrchestrator(
        executor=executor,
        fl_adapter=fl if live_fl else None,
        db=db,
        memory=memory,
    )

    plan = orchestrator.create_plan(
        BENCHMARK_PROMPT,
        midi_export_dir=os.path.join(out_dir, "midi"),
    )
    print(f"[3] Created ActionPlan '{plan.plan_id}' with {len(plan.actions)} typed actions.")
    print(f"    Parsed Intent: genre={plan.parsed_intent.genre}, bpm={plan.parsed_intent.tempo_bpm}, key={plan.parsed_intent.key} {plan.parsed_intent.scale}, sections={plan.parsed_intent.sections}")

    example_render = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "audio", "example_render.wav")
    )
    render_cfg = RenderSettings(output_path=example_render, overwrite_approved=True)

    result = await orchestrator.execute_plan(
        plan,
        prefer_mock=not live_fl,
        render_settings=render_cfg,
    )

    print(f"[4] Execution finished: success={result.success}, succeeded={result.actions_succeeded}/{len(plan.actions)}")
    for d in result.details:
        print(f"    - [{d['status']}] {d['action_type']}: {d['description']} (verified={d['verified']})")

    print(f"[5] Exported MIDI files: {json.dumps(result.exported_midi_files, indent=2)}")
    print(f"[6] Remaining limitations reported honestly: {result.remaining_limitations}")

    if session is not None:
        restored = await session.restore_baseline()
        print(f"[7] Restored original FL Studio baseline state: {restored}")
        fl.disconnect()

    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_demo()))
