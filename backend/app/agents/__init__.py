"""Specialist Agent Roles (Section 5.2 & Phase 6)."""

from .composer import ComposerAgent, CompositionBundle
from .rhythm import RhythmAgent, RhythmBundle, DEFAULT_FL_DRUM_CHANNEL_MAP
from .sound_designer import (
    SoundDesignerAgent,
    SoundDesignPlan,
    LayeringRecommendation,
    MixerRecommendation,
)
from .arranger import ArrangerAgent, ArrangementPlan, ArrangementSection
from .critic import CriticAgent, CriticFeedbackReport, CriticFinding

__all__ = [
    "ComposerAgent",
    "CompositionBundle",
    "RhythmAgent",
    "RhythmBundle",
    "DEFAULT_FL_DRUM_CHANNEL_MAP",
    "SoundDesignerAgent",
    "SoundDesignPlan",
    "LayeringRecommendation",
    "MixerRecommendation",
    "ArrangerAgent",
    "ArrangementPlan",
    "ArrangementSection",
    "CriticAgent",
    "CriticFeedbackReport",
    "CriticFinding",
]

