"""Critic / Mixing Assistant Specialist Role (Section 5.2, Section 6.5 & Phase 7).

Inspects rendered audio analysis reports and arrangement context to:
1. Report objective, measurable technical findings (clipping, silence, peak/RMS levels, duration).
2. Provide clearly separated subjective/heuristic mixing suggestions.
3. Propose concrete revision actions (ActionDefinition) that strictly require user approval
   (requires_approval=True) before applying substantial changes to the project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..integrations.audio.analyzer import AudioAnalysisReport
from ..schemas.actions import (
    ActionDefinition,
    ActionLifecycleState,
    ActionRiskLevel,
    ActionType,
)


@dataclass
class CriticFinding:
    """A single technical or musical observation produced by CriticAgent."""
    code: str
    severity: str       # "INFO" | "WARNING" | "CRITICAL"
    category: str       # "MEASURED_FACT" | "HEURISTIC_OBSERVATION"
    summary: str
    metric_value: str


@dataclass
class CriticFeedbackReport:
    """Structured Critic evaluation separating measured facts from subjective recommendations."""
    render_valid: bool
    overall_health: str  # "HEALTHY" | "NEEDS_ATTENTION" | "CRITICAL_ISSUES" | "RENDER_FAILED"
    measured_findings: List[CriticFinding] = field(default_factory=list)
    subjective_recommendations: List[str] = field(default_factory=list)
    proposed_revisions: List[ActionDefinition] = field(default_factory=list)
    requires_user_approval_for_revisions: bool = True
    objectivity_disclaimer: str = (
        "Measured findings reflect deterministic signal calculations (peak, RMS, clipping, silence). "
        "Subjective recommendations and spectral observations are heuristic mixing suggestions and "
        "never guarantee objective artistic perfection."
    )


class CriticAgent:
    """Evaluates rendered audio and proposes approval-gated mix/arrangement revisions."""

    def evaluate_render(
        self,
        analysis: AudioAnalysisReport,
        *,
        task_id: str = "task_critic_revision",
        expected_duration_seconds: Optional[float] = None,
        target_bpm: Optional[float] = None,
    ) -> CriticFeedbackReport:
        """Analyze an AudioAnalysisReport and produce structured CriticFeedbackReport."""
        if not analysis.success or analysis.measured_facts is None:
            return CriticFeedbackReport(
                render_valid=False,
                overall_health="RENDER_FAILED",
                measured_findings=[
                    CriticFinding(
                        code="RENDER_INVALID",
                        severity="CRITICAL",
                        category="MEASURED_FACT",
                        summary=analysis.error or "Rendered audio file could not be decoded.",
                        metric_value="N/A",
                    )
                ],
                subjective_recommendations=[
                    "Verify that FL Studio completed the export and that the target WAV file is not locked or empty."
                ],
                proposed_revisions=[],
            )

        facts = analysis.measured_facts
        heuristics = analysis.heuristic_observations

        findings: List[CriticFinding] = []
        recommendations: List[str] = []
        revisions: List[ActionDefinition] = []

        # 1. Clipping check (Objective Measured Fact)
        if facts.is_clipping:
            findings.append(
                CriticFinding(
                    code="DIGITAL_CLIPPING_DETECTED",
                    severity="CRITICAL",
                    category="MEASURED_FACT",
                    summary=(
                        f"Digital clipping detected: {facts.clipped_samples} clipped samples "
                        f"(peak {facts.peak_dbfs:.2f} dBFS, ratio {facts.clipping_ratio * 100:.3f}%)."
                    ),
                    metric_value=f"peak={facts.peak_dbfs:.2f} dBFS, clipped={facts.clipped_samples}",
                )
            )
            recommendations.append(
                "Reduce Master track or loud bus faders by ~3-4 dB (or engage a soft limiter) to eliminate digital clipping."
            )
            revisions.append(
                ActionDefinition(
                    task_id=task_id,
                    action_type=ActionType.SET_MIXER_VOLUME,
                    target="mixer:0:Master",
                    description="Reduce Master Mixer Track (Track 0) volume to 0.68 (-3.0 dB headroom) to prevent clipping",
                    parameters={"track_index": 0, "volume": 0.68},
                    execution_route="FL_MCP",
                    risk_level=ActionRiskLevel.HIGH,
                    requires_approval=True,
                    status=ActionLifecycleState.AWAITING_APPROVAL,
                )
            )
        else:
            findings.append(
                CriticFinding(
                    code="PEAK_HEADROOM_OK",
                    severity="INFO",
                    category="MEASURED_FACT",
                    summary=f"No digital clipping detected (peak level {facts.peak_dbfs:.2f} dBFS).",
                    metric_value=f"{facts.peak_dbfs:.2f} dBFS",
                )
            )

        # 2. Silence check (Objective Measured Fact)
        if facts.is_mostly_silent:
            findings.append(
                CriticFinding(
                    code="EXCESSIVE_SILENCE",
                    severity="CRITICAL",
                    category="MEASURED_FACT",
                    summary=(
                        f"Render is mostly silent: silence ratio is {facts.silence_ratio * 100:.1f}% "
                        f"and RMS level is {facts.rms_dbfs:.2f} dBFS."
                    ),
                    metric_value=f"silence_ratio={facts.silence_ratio:.2f}, rms={facts.rms_dbfs:.2f} dBFS",
                )
            )
            recommendations.append(
                "Check whether pattern/song mode matched your active arrangement and verify that channels/mixer tracks are not muted."
            )
            revisions.append(
                ActionDefinition(
                    task_id=task_id,
                    action_type=ActionType.SET_MIXER_MUTE,
                    target="mixer:0:Master",
                    description="Ensure Master Mixer Track (Track 0) is unmuted",
                    parameters={"track_index": 0, "mute": False},
                    execution_route="FL_MCP",
                    risk_level=ActionRiskLevel.HIGH,
                    requires_approval=True,
                    status=ActionLifecycleState.AWAITING_APPROVAL,
                )
            )
        elif facts.trailing_silence_seconds >= 2.0 and facts.duration_seconds > 4.0:
            findings.append(
                CriticFinding(
                    code="LONG_TRAILING_SILENCE",
                    severity="WARNING",
                    category="MEASURED_FACT",
                    summary=f"Trailing silence of {facts.trailing_silence_seconds:.2f}s detected at end of render.",
                    metric_value=f"{facts.trailing_silence_seconds:.2f}s",
                )
            )
            recommendations.append(
                "Consider setting FL Studio export Tail mode to 'Cut remainder' or trimming the playlist end marker."
            )

        # 3. Low overall level check (Objective Measured Fact)
        if not facts.is_mostly_silent and facts.rms_dbfs < -26.0 and facts.peak_dbfs < -9.0:
            findings.append(
                CriticFinding(
                    code="LOW_OVERALL_LEVEL",
                    severity="WARNING",
                    category="MEASURED_FACT",
                    summary=(
                        f"Render level is relatively quiet (RMS {facts.rms_dbfs:.2f} dBFS, "
                        f"Peak {facts.peak_dbfs:.2f} dBFS)."
                    ),
                    metric_value=f"rms={facts.rms_dbfs:.2f} dBFS, peak={facts.peak_dbfs:.2f} dBFS",
                )
            )
            recommendations.append(
                "Consider raising instrument bus levels or applying gentle bus compression to bring peak levels closer to -3.0 dBFS."
            )
            revisions.append(
                ActionDefinition(
                    task_id=task_id,
                    action_type=ActionType.SET_MIXER_VOLUME,
                    target="mixer:0:Master",
                    description="Raise Master Mixer Track (Track 0) volume to 0.85 to increase overall render level",
                    parameters={"track_index": 0, "volume": 0.85},
                    execution_route="FL_MCP",
                    risk_level=ActionRiskLevel.HIGH,
                    requires_approval=True,
                    status=ActionLifecycleState.AWAITING_APPROVAL,
                )
            )

        # 4. Duration comparison against brief (Objective Measured Fact)
        if expected_duration_seconds is not None and abs(facts.duration_seconds - expected_duration_seconds) > 1.0:
            findings.append(
                CriticFinding(
                    code="DURATION_MISMATCH",
                    severity="WARNING",
                    category="MEASURED_FACT",
                    summary=(
                        f"Rendered duration ({facts.duration_seconds:.2f}s) differs from "
                        f"expected brief duration ({expected_duration_seconds:.2f}s)."
                    ),
                    metric_value=f"actual={facts.duration_seconds:.2f}s vs expected={expected_duration_seconds:.2f}s",
                )
            )

        # 5. Heuristic spectral observations (Explicitly labeled as Heuristic / Subjective)
        if heuristics is not None and not facts.is_mostly_silent:
            findings.append(
                CriticFinding(
                    code="SPECTRAL_BALANCE_ESTIMATE",
                    severity="INFO",
                    category="HEURISTIC_OBSERVATION",
                    summary=heuristics.spectral_balance_summary,
                    metric_value=(
                        f"Low={heuristics.low_band_energy_ratio * 100:.1f}%, "
                        f"Mid={heuristics.mid_band_energy_ratio * 100:.1f}%, "
                        f"High={heuristics.high_band_energy_ratio * 100:.1f}% "
                        f"(centroid ~{heuristics.spectral_centroid_hz_est:.0f} Hz)"
                    ),
                )
            )
            if heuristics.low_band_energy_ratio >= 0.70:
                recommendations.append(
                    "Subjective tip: Low-end energy (<250 Hz) is strongly dominant; consider checking kick/sub balance by ear or high-passing non-bass elements."
                )
            elif heuristics.high_band_energy_ratio >= 0.55:
                recommendations.append(
                    "Subjective tip: High-frequency energy (>4 kHz) is prominent; consider taming harsh hi-hat or synth transients if the mix sounds fatiguing."
                )
            else:
                recommendations.append(
                    "Subjective tip: Spectral energy is reasonably distributed across low, mid, and high bands; fine-tune EQ to taste."
                )

        # Determine overall health
        severities = {f.severity for f in findings}
        if "CRITICAL" in severities:
            health = "CRITICAL_ISSUES"
        elif "WARNING" in severities:
            health = "NEEDS_ATTENTION"
        else:
            health = "HEALTHY"

        return CriticFeedbackReport(
            render_valid=True,
            overall_health=health,
            measured_findings=findings,
            subjective_recommendations=recommendations,
            proposed_revisions=revisions,
            requires_user_approval_for_revisions=True,
        )

