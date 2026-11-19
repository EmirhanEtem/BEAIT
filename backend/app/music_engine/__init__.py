"""Music and MIDI generation engine for FL Studio AI Assistant."""

from .models import (
    ChordQuality,
    DrumChannelPattern,
    DrumPattern,
    MidiNote,
    MidiPattern,
    ScaleType,
)
from .scales import (
    get_scale_pitches,
    midi_to_note,
    note_to_midi,
    quantize_pitch_to_scale,
)
from .chords import (
    build_chord,
    progression_to_notes,
)
from .generator import (
    apply_humanization,
    generate_bassline,
    generate_chord_pattern,
    generate_drum_pattern,
    generate_melody,
    steps_to_string,
)
from .presets import (
    GenrePreset,
    GenrePresetRegistry,
)
from .validator import (
    ValidationResult,
    validate_drum_channel,
    validate_midi_notes,
)
from .midi_io import (
    export_midi_file,
    read_midi_file,
)
from .creative_engine import CreativeBeatEngine
from .mix_master import MixMasterEngine

__all__ = [
    "ScaleType",
    "ChordQuality",
    "MidiNote",
    "MidiPattern",
    "DrumChannelPattern",
    "DrumPattern",
    "note_to_midi",
    "midi_to_note",
    "get_scale_pitches",
    "quantize_pitch_to_scale",
    "build_chord",
    "progression_to_notes",
    "generate_drum_pattern",
    "generate_chord_pattern",
    "generate_bassline",
    "generate_melody",
    "apply_humanization",
    "steps_to_string",
    "GenrePreset",
    "GenrePresetRegistry",
    "validate_midi_notes",
    "validate_drum_channel",
    "ValidationResult",
    "export_midi_file",
    "read_midi_file",
    "CreativeBeatEngine",
    "MixMasterEngine",
]
