"""Safe test project workflow and session snapshotting.

Ensures that experimental operations, automated tests, and AI generation
never silently overwrite or corrupt an active user project.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from ..integrations.fl_studio.adapter import FLStudioAdapter, ProjectState

logger = logging.getLogger(__name__)


@dataclass
class ProjectBaselineSnapshot:
    """Snapshot of initial project state before mutating actions."""
    tempo: float
    channel_count: int
    mixer_track_count: int
    pattern_number: int
    channels: List[Dict[str, Any]] = field(default_factory=list)
    step_grids: Dict[int, List[int]] = field(default_factory=dict)
    mixer_levels: Dict[int, float] = field(default_factory=dict)


class TestProjectSession:
    """Manages disposable testing and safe rollback for FL Studio sessions."""
    __test__ = False

    def __init__(self, adapter: FLStudioAdapter):
        self.adapter = adapter
        self.baseline: Optional[ProjectBaselineSnapshot] = None

    async def capture_baseline(self) -> ProjectBaselineSnapshot:
        """Capture the baseline state of FL Studio before modifying anything."""
        logger.info("Capturing project baseline snapshot...")
        tempo = await self.adapter.async_get_tempo()
        state = await self.adapter.async_get_project_state()
        channels = await self.adapter.async_get_channels()

        # Capture step grids for loaded channels (up to first 8)
        step_grids: Dict[int, List[int]] = {}
        for ch in channels[:8]:
            idx = ch.get("i", 0)
            try:
                g = await self.adapter.async_get_step_grid(idx, length=16)
                step_grids[idx] = g.get("steps", [])
            except Exception as e:
                logger.warning("Could not read step grid for channel %d: %e", idx, e)

        # Capture mixer master level
        mixer_levels: Dict[int, float] = {}
        try:
            m0 = await self.adapter.async_get_mixer_track(0)
            mixer_levels[0] = float(m0.get("vol_norm", 0.8))
        except Exception as e:
            logger.warning("Could not read mixer master level: %e", e)

        self.baseline = ProjectBaselineSnapshot(
            tempo=tempo,
            channel_count=state.channel_count or len(channels),
            mixer_track_count=state.mixer_track_count or 0,
            pattern_number=state.pattern_number or 1,
            channels=channels,
            step_grids=step_grids,
            mixer_levels=mixer_levels,
        )
        logger.info("Project baseline captured: tempo=%.1f, channels=%d", tempo, len(channels))
        return self.baseline

    async def restore_baseline(self) -> Dict[str, Any]:
        """Restore FL Studio state back to the baseline snapshot."""
        if not self.baseline:
            raise RuntimeError("Cannot restore: No baseline snapshot captured.")

        logger.info("Restoring project to baseline (tempo=%.1f)...", self.baseline.tempo)
        results = {}

        # 1. Restore tempo
        try:
            t_res = await self.adapter.async_set_tempo_verified(self.baseline.tempo)
            results["tempo_restored"] = t_res.verified
        except Exception as e:
            results["tempo_error"] = str(e)

        # 2. Restore step grids
        grid_restores = {}
        for ch_idx, steps in self.baseline.step_grids.items():
            try:
                g_res = await self.adapter.async_set_step_grid_verified(ch_idx, steps=steps, length=16)
                grid_restores[ch_idx] = g_res.verified
            except Exception as e:
                grid_restores[ch_idx] = f"error: {e}"
        results["grid_restores"] = grid_restores

        # 3. Restore mixer volume
        if 0 in self.baseline.mixer_levels:
            try:
                m_res = await self.adapter.async_set_mixer_volume_verified(0, self.baseline.mixer_levels[0])
                results["master_volume_restored"] = m_res.verified
            except Exception as e:
                results["master_volume_error"] = str(e)

        logger.info("Baseline restoration complete: %s", results)
        return results
