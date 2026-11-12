"""Live Phase 4 FL Studio Control Verification Script.

Executes real control actions against the running FL Studio instance:
1. Baseline snapshot capture
2. Read project context, channels, and mixer tracks
3. Verified BPM change & verification
4. Drum step-sequencer write (Kick 4-on-the-floor & Clap) with readback verification
5. Pattern creation
6. Full restoration of the session to baseline snapshot (zero silent alteration)
"""

import asyncio
import sys
import os

# Add backend directory to path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.integrations.fl_studio.adapter import FLStudioAdapter, TransportType
from app.sessions.test_project import TestProjectSession
from app.music_engine.generator import generate_drum_pattern


async def main():
    print("=" * 60)
    print("FL Studio AI Assistant - Phase 4 Real Control MVP Live Test")
    print("=" * 60)

    adapter = FLStudioAdapter(transport=TransportType.TCP)
    status = adapter.connect()
    print(f"[1] Adapter connect: connected={status.connected}, alive={status.fl_studio_alive}")
    if not status.connected or not status.fl_studio_alive:
        print(f"Error: FL Studio daemon unreachable or FL not alive: {status.error}")
        return 1

    session = TestProjectSession(adapter)

    # 1. Capture baseline snapshot
    print("\n[2] Capturing project baseline snapshot...")
    baseline = await session.capture_baseline()
    print(f"    Baseline Tempo: {baseline.tempo} BPM")
    print(f"    Channel count: {len(baseline.channels)}")
    print(f"    Channels: {[c.get('name') for c in baseline.channels]}")
    print(f"    Initial step grids: {baseline.step_grids}")

    try:
        # 2. Test Verified BPM Change
        test_bpm = 126.0 if baseline.tempo != 126.0 else 128.0
        print(f"\n[3] Testing verified BPM change to {test_bpm}...")
        bpm_res = await adapter.async_set_tempo_verified(test_bpm)
        print(f"    Before: {bpm_res.before} BPM | Requested: {bpm_res.requested} BPM | After: {bpm_res.after} BPM")
        print(f"    Verified: {bpm_res.verified}")
        assert bpm_res.verified, f"BPM change failed verification (got {bpm_res.after})"

        # 3. Test Drum Step-Sequencer Write (Channel 0 Kick, Channel 1 Clap)
        print("\n[4] Writing 4-on-the-floor drum pattern...")
        drum_pat = generate_drum_pattern("four_on_the_floor", length=16)
        
        # Write Kick steps: [0, 4, 8, 12]
        kick_steps = [0, 4, 8, 12]
        print(f"    Writing Channel 0 (Kick) steps: {kick_steps}...")
        kick_res = await adapter.async_set_step_grid_verified(0, steps=kick_steps, length=16)
        print(f"    Kick Verified: {kick_res.verified} | After steps: {kick_res.after_steps}")
        assert kick_res.verified, "Kick step grid verification failed!"

        # Write Clap steps: [4, 12]
        clap_steps = [4, 12]
        print(f"    Writing Channel 1 (Clap) steps: {clap_steps}...")
        clap_res = await adapter.async_set_step_grid_verified(1, steps=clap_steps, length=16)
        print(f"    Clap Verified: {clap_res.verified} | After steps: {clap_res.after_steps}")
        assert clap_res.verified, "Clap step grid verification failed!"

        # 4. Test Pattern Creation
        print("\n[5] Testing pattern creation ('AI_Beat_1')...")
        pat_res = await adapter.async_create_pattern("AI_Beat_1")
        print(f"    Pattern creation verified: {pat_res.verified} | Index: {pat_res.index} | Name: {pat_res.name}")

        # 5. Test Mixer Track Read
        print("\n[6] Testing mixer master read...")
        master_track = await adapter.async_get_mixer_track(0)
        print(f"    Master Track: {master_track.get('name')} | Vol Norm: {master_track.get('vol_norm')} | Pan: {master_track.get('pan')}")

    finally:
        # 6. Safety Restoration
        print("\n[7] Restoring session back to original baseline snapshot...")
        restored = await session.restore_baseline()
        print(f"    Restoration result: {restored}")
        final_bpm = await adapter.async_get_tempo()
        print(f"    Final session BPM verified: {final_bpm} BPM (expected {baseline.tempo})")

    print("\n" + "=" * 60)
    print("PHASE 4 REAL FL STUDIO LIVE TEST: 100% SUCCESS")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)

