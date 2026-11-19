"""Creative Beat Engine — genre-aware, mood-aware, never-repeating music generator.

Produces a complete, musically coherent production spec for FL Studio from a natural
language prompt (Turkish or English), without needing a cloud LLM:

* 14 genre profiles (trap, drill, phonk, boom bap, lo-fi, house, techno, afrobeat,
  reggaeton/dembow, UK garage, drum & bass, jersey club, amapiano, experimental)
* Mood detection (dark / sad / happy / aggressive / dreamy / epic) that steers
  scale, chord progression, register, velocity and FX
* Probabilistic drum grooves with genre anchors, ghost notes, hat rolls, mutations
  and Euclidean rhythms (16-step Channel Rack grid)
* Diatonic chord progressions with 7th/9th extensions and voice-leading
* Bass lines that lock to the kick (808 glides via per-note portamento), rolling
  16ths, offbeat house bass, walking bass, amapiano log drums
* Motif-based lead melodies (call / response / variation / cadence) with swing
* Per-role instrument selection with fallbacks (FL Studio stock generators)
* Per-role mixer FX chains + master chain and mix targets for the Mix/Master engine

Every call uses ``random.SystemRandom`` so two prompts never produce the same beat.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALES: Dict[str, List[int]] = {
    "natural_minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
}

SCALE_LABELS_TR = {
    "natural_minor": "doğal minör",
    "harmonic_minor": "armonik minör",
    "dorian": "dorian",
    "phrygian": "frigyen",
    "major": "majör",
    "mixolydian": "miksolidyen",
    "lydian": "lidyen",
}

# Diatonic progressions as 0-based scale degrees (one chord per bar, 4 bars)
PROGRESSIONS: Dict[str, List[List[int]]] = {
    "minor": [
        [0, 5, 2, 6], [0, 3, 5, 4], [0, 6, 5, 6], [0, 5, 3, 4], [0, 3, 0, 4],
        [0, 2, 5, 6], [5, 6, 0, 0], [0, 4, 5, 3], [0, 0, 5, 6], [3, 4, 0, 0],
    ],
    "major": [
        [0, 4, 5, 3], [5, 3, 0, 4], [0, 2, 3, 4], [0, 5, 3, 4], [3, 4, 2, 5], [0, 3, 4, 3],
    ],
    "phrygian": [[0, 1, 0, 6], [0, 1, 2, 1], [0, 6, 1, 0], [0, 0, 1, 1]],
    "dorian": [[0, 3, 0, 3], [0, 1, 3, 0], [0, 6, 3, 0], [0, 3, 6, 3]],
    "lydian": [[0, 1, 0, 1], [0, 1, 4, 0]],
    "mixolydian": [[0, 6, 3, 0], [0, 3, 6, 0]],
}


def _grid(*steps_probs: Tuple[int, float]) -> List[float]:
    g = [0.0] * 16
    for s, p in steps_probs:
        g[s % 16] = p
    return g


def _euclid(k: int, n: int = 16, rotate: int = 0) -> List[int]:
    """Bjorklund-style Euclidean rhythm (k onsets spread over n steps)."""
    k = max(0, min(k, n))
    if k == 0:
        return []
    out = [i for i in range(n) if (i * k) % n < k]
    return sorted(((s + rotate) % n) for s in out)


@dataclass
class GenreProfile:
    key: str
    label: str
    bpm: Tuple[int, int]
    scales: List[str]
    kick: List[float]
    clap: List[float]
    hat: List[float]
    perc: List[float]
    chord_style: str
    bass_style: str
    lead_density: Tuple[int, int]
    swing: Tuple[float, float] = (0.0, 0.0)
    hat_rolls: bool = False
    extensions: bool = False
    instruments: Dict[str, List[str]] = field(default_factory=dict)
    fx: Dict[str, List[str]] = field(default_factory=dict)
    sections: List[Tuple[str, int]] = field(default_factory=lambda: [("Intro", 8), ("Drop", 16)])


_DEF_FX = {
    "chords": ["Fruity Parametric EQ 2", "Fruity Reeverb 2"],
    "lead": ["Fruity Parametric EQ 2", "Fruity Delay 3", "Fruity Reeverb 2"],
    "bass": ["Fruity Parametric EQ 2"],
    "master": ["Fruity Parametric EQ 2", "Fruity Compressor", "Fruity Limiter"],
}

GENRES: Dict[str, GenreProfile] = {
    "trap": GenreProfile(
        key="trap", label="Trap", bpm=(136, 156), scales=["natural_minor", "harmonic_minor", "phrygian"],
        kick=_grid((0, 1), (3, .25), (6, .45), (7, .2), (10, .55), (11, .25), (14, .3)),
        clap=_grid((8, 1)),
        hat=_grid(*[(i, .95) for i in range(0, 16, 2)], *[(i, .35) for i in range(1, 16, 2)]),
        perc=_grid((4, .2), (12, .25), (15, .35), (13, .2)),
        chord_style="pad", bass_style="808_follow", lead_density=(4, 7), hat_rolls=True,
        instruments={"chords": ["FLEX", "Sakura", "Sytrus"], "bass": ["3x Osc", "Transistor Bass", "BooBass"],
                     "lead": ["FL Keys", "Plucked!", "FLEX"]},
        fx={**_DEF_FX, "bass": ["Fruity Parametric EQ 2", "Fruity Soft Clipper"]},
    ),
    "drill": GenreProfile(
        key="drill", label="UK/NY Drill", bpm=(138, 146), scales=["harmonic_minor", "phrygian", "natural_minor"],
        kick=_grid((0, 1), (5, .35), (7, .3), (10, .5), (13, .35)),
        clap=_grid((8, 1), (13, .3)),
        hat=_grid((0, .9), (3, .85), (6, .85), (8, .6), (10, .7), (11, .5), (14, .85)),
        perc=_grid((4, .3), (11, .35), (15, .45)),
        chord_style="pad", bass_style="808_follow", lead_density=(3, 6), hat_rolls=True,
        instruments={"chords": ["Sakura", "FLEX", "Sytrus"], "bass": ["3x Osc", "Transistor Bass", "BooBass"],
                     "lead": ["FLEX", "Sytrus", "FL Keys"]},
        fx={**_DEF_FX, "bass": ["Fruity Parametric EQ 2", "Fruity Fast Dist"]},
    ),
    "phonk": GenreProfile(
        key="phonk", label="Drift Phonk", bpm=(125, 145), scales=["phrygian", "harmonic_minor"],
        kick=_grid((0, 1), (4, .5), (8, 1), (10, .45), (11, .3), (14, .4)),
        clap=_grid((4, 1), (12, 1)),
        hat=_grid(*[(i, .9) for i in range(0, 16, 2)], *[(i, .45) for i in range(1, 16, 2)]),
        perc=_grid((3, .4), (7, .35), (11, .4), (15, .5)),
        chord_style="stab_offbeat", bass_style="808_follow", lead_density=(6, 10), hat_rolls=True,
        instruments={"chords": ["Sytrus", "3x Osc"], "bass": ["3x Osc", "Transistor Bass"],
                     "lead": ["FLEX", "3x Osc", "Sytrus"]},
        fx={**_DEF_FX, "bass": ["Fruity Parametric EQ 2", "Fruity Fast Dist"],
            "lead": ["Fruity Parametric EQ 2", "Fruity Fast Dist", "Fruity Reeverb 2"]},
    ),
    "boom_bap": GenreProfile(
        key="boom_bap", label="Boom Bap", bpm=(84, 96), scales=["dorian", "natural_minor"],
        kick=_grid((0, 1), (7, .35), (10, .8), (13, .2)),
        clap=_grid((4, 1), (12, 1)),
        hat=_grid(*[(i, .9) for i in range(0, 16, 2)], (7, .3), (15, .4)),
        perc=_grid((3, .25), (9, .3), (14, .3)),
        chord_style="piano_comp", bass_style="walking", lead_density=(3, 6), swing=(0.12, 0.22), extensions=True,
        instruments={"chords": ["FL Keys", "Sakura"], "bass": ["BooBass", "Transistor Bass"],
                     "lead": ["FL Keys", "Plucked!", "FLEX"]},
    ),
    "lofi": GenreProfile(
        key="lofi", label="Lo-Fi Hip Hop", bpm=(70, 88), scales=["dorian", "major", "natural_minor"],
        kick=_grid((0, 1), (7, .3), (9, .5), (10, .3)),
        clap=_grid((4, 1), (12, 1)),
        hat=_grid(*[(i, .8) for i in range(0, 16, 2)], (11, .3)),
        perc=_grid((6, .2), (14, .25)),
        chord_style="piano_comp", bass_style="sub_whole", lead_density=(2, 5), swing=(0.18, 0.28), extensions=True,
        instruments={"chords": ["FL Keys", "Sakura"], "bass": ["BooBass", "FLEX"], "lead": ["Plucked!", "FL Keys"]},
        fx={**_DEF_FX, "chords": ["Fruity Parametric EQ 2", "Fruity Chorus", "Fruity Reeverb 2"]},
    ),
    "house": GenreProfile(
        key="house", label="Deep/Tech House", bpm=(120, 126), scales=["natural_minor", "dorian", "major"],
        kick=_grid((0, 1), (4, 1), (8, 1), (12, 1)),
        clap=_grid((4, 1), (12, 1)),
        hat=_grid((2, 1), (6, 1), (10, 1), (14, 1), (15, .25), (7, .2)),
        perc=_grid((3, .35), (7, .3), (11, .4), (13, .3)),
        chord_style="stab_offbeat", bass_style="offbeat", lead_density=(4, 8), swing=(0.04, 0.1), extensions=True,
        instruments={"chords": ["FL Keys", "Sytrus", "FLEX"], "bass": ["Transistor Bass", "3x Osc", "BooBass"],
                     "lead": ["Plucked!", "Sytrus", "FLEX"]},
    ),
    "techno": GenreProfile(
        key="techno", label="Melodic Techno", bpm=(124, 136), scales=["natural_minor", "phrygian", "harmonic_minor"],
        kick=_grid((0, 1), (4, 1), (8, 1), (12, 1)),
        clap=_grid((4, .8), (12, .9)),
        hat=_grid(*[(i, .85) for i in range(2, 16, 4)], *[(i, .45) for i in range(1, 16, 2)]),
        perc=_grid((3, .3), (6, .3), (10, .35), (13, .3)),
        chord_style="arp", bass_style="rolling_16th", lead_density=(6, 12),
        instruments={"chords": ["Sytrus", "3x Osc", "FLEX"], "bass": ["3x Osc", "Transistor Bass"],
                     "lead": ["Sytrus", "FLEX", "3x Osc"]},
    ),
    "afrobeat": GenreProfile(
        key="afrobeat", label="Afrobeats", bpm=(100, 114), scales=["major", "dorian", "mixolydian"],
        kick=_grid((0, 1), (6, .6), (10, .7), (12, .3)),
        clap=_grid((4, .5), (7, .6), (12, .8), (15, .3)),
        hat=_grid(*[(i, .8) for i in range(16)]),
        perc=_grid((3, .6), (6, .4), (10, .5), (11, .4), (14, .5)),
        chord_style="syncopated", bass_style="syncopated", lead_density=(5, 9), swing=(0.06, 0.14), extensions=True,
        instruments={"chords": ["Plucked!", "FL Keys"], "bass": ["BooBass", "Transistor Bass"],
                     "lead": ["FLEX", "Plucked!", "Sytrus"]},
    ),
    "reggaeton": GenreProfile(
        key="reggaeton", label="Reggaeton / Dembow", bpm=(88, 100), scales=["natural_minor", "harmonic_minor", "major"],
        kick=_grid((0, 1), (4, 1), (8, 1), (12, 1)),
        clap=_grid((3, 1), (6, 1), (11, 1), (14, 1)),
        hat=_grid(*[(i, .85) for i in range(0, 16, 2)], (5, .3), (13, .3)),
        perc=_grid((7, .4), (15, .4)),
        chord_style="syncopated", bass_style="808_follow", lead_density=(5, 8),
        instruments={"chords": ["FLEX", "Plucked!", "FL Keys"], "bass": ["3x Osc", "BooBass"],
                     "lead": ["FLEX", "Sytrus", "Plucked!"]},
    ),
    "garage": GenreProfile(
        key="garage", label="UK Garage / 2-Step", bpm=(130, 136), scales=["natural_minor", "dorian"],
        kick=_grid((0, 1), (9, .75), (11, .3), (14, .2)),
        clap=_grid((4, 1), (12, 1)),
        hat=_grid((2, .9), (6, .9), (10, .9), (14, .9), (3, .4), (11, .4), (15, .3)),
        perc=_grid((7, .35), (13, .35)),
        chord_style="stab_offbeat", bass_style="syncopated", lead_density=(4, 8), swing=(0.12, 0.2), extensions=True,
        instruments={"chords": ["FL Keys", "Sytrus"], "bass": ["3x Osc", "Transistor Bass"],
                     "lead": ["FLEX", "Plucked!"]},
    ),
    "dnb": GenreProfile(
        key="dnb", label="Drum & Bass", bpm=(170, 176), scales=["natural_minor", "dorian", "harmonic_minor"],
        kick=_grid((0, 1), (10, .9), (7, .2)),
        clap=_grid((4, 1), (12, 1)),
        hat=_grid(*[(i, .85) for i in range(0, 16, 2)], *[(i, .3) for i in range(1, 16, 2)]),
        perc=_grid((14, .5), (6, .3)),
        chord_style="pad", bass_style="rolling_16th", lead_density=(4, 8),
        instruments={"chords": ["Sytrus", "FLEX"], "bass": ["3x Osc", "Transistor Bass"], "lead": ["FLEX", "Sytrus"]},
    ),
    "jersey": GenreProfile(
        key="jersey", label="Jersey Club", bpm=(138, 145), scales=["natural_minor", "major"],
        kick=_grid((0, 1), (3, .9), (6, .9), (8, 1), (10, .6), (12, .7), (13, .7), (14, .6)),
        clap=_grid((4, 1), (12, 1)),
        hat=_grid(*[(i, .7) for i in range(0, 16, 2)]),
        perc=_grid((2, .4), (11, .4), (15, .5)),
        chord_style="stab_offbeat", bass_style="808_follow", lead_density=(5, 9),
        instruments={"chords": ["FLEX", "Sytrus"], "bass": ["3x Osc"], "lead": ["FLEX", "Plucked!"]},
    ),
    "amapiano": GenreProfile(
        key="amapiano", label="Amapiano", bpm=(110, 115), scales=["natural_minor", "dorian", "major"],
        kick=_grid((0, 1), (4, 1), (8, 1), (12, 1)),
        clap=_grid((7, .6), (12, .8), (15, .3)),
        hat=_grid(*[(i, .85) for i in range(16)]),
        perc=_grid((3, .5), (6, .45), (10, .5), (13, .45)),
        chord_style="piano_comp", bass_style="log_drum", lead_density=(3, 6), swing=(0.08, 0.16), extensions=True,
        instruments={"chords": ["FL Keys", "Sakura"], "bass": ["3x Osc", "Transistor Bass"],
                     "lead": ["FLEX", "Plucked!"]},
    ),
    "experimental": GenreProfile(
        key="experimental", label="Deneysel / IDM", bpm=(92, 160), scales=["phrygian", "lydian", "dorian", "harmonic_minor"],
        kick=[0.0] * 16, clap=[0.0] * 16, hat=[0.0] * 16, perc=[0.0] * 16,
        chord_style="arp", bass_style="syncopated", lead_density=(5, 11),
        instruments={"chords": ["Sytrus", "FLEX", "Harmless"], "bass": ["3x Osc", "Transistor Bass"],
                     "lead": ["Plucked!", "Sytrus", "FLEX"]},
        fx={**_DEF_FX, "lead": ["Fruity Parametric EQ 2", "Fruity Delay 3", "Fruity Reeverb 2"]},
    ),
}

GENRE_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("phonk", ("phonk", "drift", "cowbell")),
    ("drill", ("drill",)),
    ("jersey", ("jersey",)),
    ("amapiano", ("amapiano", "log drum")),
    ("reggaeton", ("reggaeton", "dembow", "latin")),
    ("afrobeat", ("afro", "afrobeat")),
    ("garage", ("garage", "2-step", "2 step", "ukg")),
    ("dnb", ("dnb", "drum and bass", "drum & bass", "jungle")),
    ("lofi", ("lofi", "lo-fi", "lo fi", "chill")),
    ("boom_bap", ("boom bap", "boombap", "old school", "90s", "90'lar")),
    ("house", ("house", "deep house", "tech house", "dance", "edm")),
    ("techno", ("techno", "tekno", "trance", "rave", "melodic techno")),
    ("trap", ("trap", "808", "rap", "hip hop", "hip-hop")),
    ("experimental", ("deneysel", "experimental", "idm", "alışıldık dışı", "alisildik disi", "sıradışı", "siradisi", "farklı", "farkli", "değişik", "degisik")),
]

MOOD_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "dark": ("dark", "karanlık", "karanlik", "korku", "gerilim", "evil", "sinister"),
    "sad": ("sad", "hüzün", "huzun", "üzgün", "uzgun", "duygusal", "melankolik", "ağlat", "aglat", "emotional"),
    "happy": ("happy", "mutlu", "neşeli", "neseli", "yaz", "summer", "pozitif", "eğlenceli", "eglenceli"),
    "aggressive": ("agresif", "aggressive", "sert", "hard", "öfke", "ofke", "yıkıcı", "yikici"),
    "dreamy": ("dreamy", "rüya", "ruya", "atmosferik", "atmospheric", "ambient", "uzay", "space", "huzur"),
    "epic": ("epic", "epik", "sinematik", "cinematic", "büyük", "orkestral"),
}

INSTRUMENT_KEYWORDS: List[Tuple[Tuple[str, ...], str, str]] = [
    (("piyano", "piano", "tuşlu", "rhodes", "keys"), "chords", "FL Keys"),
    (("gitar", "guitar", "telli", "akustik"), "chords", "Plucked!"),
    (("keman", "yaylı", "yayli", "string", "orkestra"), "chords", "FLEX"),
    (("pad", "atmosfer"), "chords", "Sytrus"),
    (("bas gitar", "canlı bas", "bass guitar"), "bass", "BooBass"),
    (("synth", "lead", "sytrus"), "lead", "Sytrus"),
    (("bell", "zil", "çan", "can sesi"), "lead", "FLEX"),
    (("flüt", "flut", "flute", "üflemeli"), "lead", "FLEX"),
    (("arp", "arpej"), "lead", "Sytrus"),
]

UNIVERSAL_FALLBACKS = ["FLEX", "3x Osc", "FL Keys"]

ROLE_LABELS_TR = {"chords": "Akor/Armoni", "bass": "Bas", "lead": "Lead/Melodi"}


class CreativeBeatEngine:
    """Generates a full creative production spec (drums, chords, bass, lead, instruments, FX, mix)."""

    def __init__(self, rng: Optional[random.Random] = None):
        self.rng = rng or random.SystemRandom()

    # ------------------------------------------------------------------ parsing

    @staticmethod
    def detect_genre(lower: str) -> Optional[str]:
        for genre, kws in GENRE_KEYWORDS:
            if any(k in lower for k in kws):
                return genre
        return None

    @staticmethod
    def detect_mood(lower: str) -> str:
        for mood, kws in MOOD_KEYWORDS.items():
            if any(k in lower for k in kws):
                return mood
        return "neutral"

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def deg_to_midi(root_midi: int, scale: List[int], deg: int) -> int:
        octave, idx = divmod(deg, len(scale))
        return root_midi + scale[idx] + 12 * octave

    def _pick_scale(self, profile: GenreProfile, mood: str) -> str:
        mood_scales = {
            "dark": ["phrygian", "harmonic_minor", "natural_minor"],
            "sad": ["natural_minor", "harmonic_minor", "dorian"],
            "happy": ["major", "mixolydian", "lydian"],
            "aggressive": ["phrygian", "harmonic_minor"],
            "dreamy": ["lydian", "dorian", "major"],
            "epic": ["harmonic_minor", "natural_minor"],
        }
        if mood in mood_scales:
            options = [s for s in mood_scales[mood] if s in profile.scales] or mood_scales[mood]
            return self.rng.choice(options)
        return self.rng.choice(profile.scales)

    def _progression(self, scale_name: str) -> List[int]:
        family = scale_name if scale_name in ("phrygian", "dorian", "lydian", "mixolydian") else (
            "major" if scale_name == "major" else "minor"
        )
        return list(self.rng.choice(PROGRESSIONS[family]))

    # ------------------------------------------------------------------ drums

    def _drums(self, profile: GenreProfile, mood: str, energy: float) -> Dict[str, List[int]]:
        rng = self.rng
        if profile.key == "experimental":
            kick = _euclid(rng.choice([3, 5, 7]), 16, rng.randint(0, 3))
            clap = _euclid(rng.choice([2, 3]), 16, rng.choice([4, 6]))
            hat = _euclid(rng.choice([7, 9, 11, 13]), 16, rng.randint(0, 5))
            perc = _euclid(rng.choice([3, 5]), 16, rng.randint(1, 7))
            if 0 not in kick:
                kick = sorted(set(kick + [0]))
            return {"kick": kick, "clap": clap, "hat": hat, "perc": perc}

        def sample(grid: List[float], boost: float) -> List[int]:
            out = []
            for i, p in enumerate(grid):
                if p >= 1.0 or (p > 0 and rng.random() < min(0.98, p * boost)):
                    out.append(i)
            return out

        kick = sample(profile.kick, energy)
        clap = sample(profile.clap, 1.0)
        hat = sample(profile.hat, energy)
        perc = sample(profile.perc, energy)

        # Mutation: nudge a non-anchor kick by one 16th for fresh syncopation
        movable = [s for s in kick if profile.kick[s] < 1.0]
        if movable and rng.random() < 0.45:
            s = rng.choice(movable)
            kick.remove(s)
            kick.append((s + rng.choice([-1, 1])) % 16)

        # Hat rolls (16th bursts) before the backbeat or bar end
        if profile.hat_rolls and rng.random() < 0.85:
            for _ in range(rng.randint(1, 2)):
                start = rng.choice([4, 10, 12, 13])
                hat.extend(range(start, min(16, start + rng.randint(2, 4))))

        # Ghost-note / fill on perc channel near the end of the bar
        if rng.random() < 0.5:
            perc.append(rng.choice([13, 14, 15]))

        # Aggressive = denser kicks, dreamy = sparser hats
        if mood == "aggressive" and rng.random() < 0.6:
            kick.append(rng.choice([2, 6, 11, 14]))
        if mood == "dreamy" and len(hat) > 6:
            hat = [h for h in hat if h % 2 == 0 or rng.random() < 0.3]

        def clean(xs: List[int], minimum: int = 0) -> List[int]:
            res = sorted({x % 16 for x in xs})
            return res

        kick = clean(kick)
        if 0 not in kick:
            kick = [0] + kick
        hat = clean(hat)
        if len(hat) < 3:
            hat = sorted(set(hat + [2, 6, 10, 14]))
        return {"kick": kick, "clap": clean(clap), "hat": hat, "perc": clean(perc)}

    # ------------------------------------------------------------------ harmony

    def _voice_chord(self, root_midi: int, scale: List[int], degree: int, extensions: bool,
                     prev_center: float, low: int = 53, high: int = 76) -> List[int]:
        tones = [degree, degree + 2, degree + 4]
        if extensions:
            tones.append(degree + 6)          # 7th
            if self.rng.random() < 0.45:
                tones.append(degree + 8)      # 9th
        base = sorted(self.deg_to_midi(root_midi - 12, scale, t) for t in tones)
        candidates = []
        for shift in (-12, 0, 12, 24):
            for inv in range(len(base)):
                v = sorted([p + shift + (12 if i < inv else 0) for i, p in enumerate(base)])
                if v[0] >= low and v[-1] <= high:
                    candidates.append(v)
        if not candidates:
            return [max(low, min(high, p)) for p in base]
        return min(candidates, key=lambda v: abs(sum(v) / len(v) - prev_center) + self.rng.random() * 1.5)

    def _chord_notes(self, profile: GenreProfile, root_midi: int, scale: List[int], prog: List[int],
                     mood: str) -> List[Dict[str, Any]]:
        rng = self.rng
        notes: List[Dict[str, Any]] = []
        center = 64.0
        style = profile.chord_style
        base_vel = 0.62 if mood in ("sad", "dreamy") else 0.74
        sync_cell = sorted(rng.sample([0.0, 0.1875, 0.375, 0.5, 0.625, 0.8125], k=rng.randint(3, 5)))
        for bar, deg in enumerate(prog):
            voicing = self._voice_chord(root_midi, scale, deg, profile.extensions, center)
            center = sum(voicing) / len(voicing)
            b = float(bar)
            if style == "pad":
                for p in voicing:
                    notes.append({"pitch": p, "time_bars": b, "length_bars": 0.98, "velocity": base_vel})
            elif style == "stab_offbeat":
                for off in (0.125, 0.375, 0.625, 0.875):
                    if rng.random() < 0.88:
                        for p in voicing[:4]:
                            notes.append({"pitch": p, "time_bars": b + off, "length_bars": 0.09,
                                          "velocity": round(base_vel + rng.uniform(-0.06, 0.08), 2)})
            elif style == "syncopated":
                for off in sync_cell:
                    for p in voicing[:4]:
                        notes.append({"pitch": p, "time_bars": b + off, "length_bars": 0.11,
                                      "velocity": round(base_vel + rng.uniform(-0.08, 0.06), 2)})
            elif style == "piano_comp":
                # strummed downbeat + push into the next bar
                for i, p in enumerate(voicing):
                    notes.append({"pitch": p, "time_bars": round(b + i * 0.008, 4), "length_bars": 0.55,
                                  "velocity": round(base_vel + rng.uniform(-0.05, 0.05), 2)})
                if rng.random() < 0.7:
                    for p in voicing[1:]:
                        notes.append({"pitch": p, "time_bars": b + rng.choice([0.625, 0.75]), "length_bars": 0.2,
                                      "velocity": round(base_vel - 0.1, 2)})
            else:  # arp
                pattern = rng.choice(["up", "down", "updown", "random"])
                seq = list(voicing) + [voicing[0] + 12]
                if pattern == "down":
                    seq = seq[::-1]
                elif pattern == "updown":
                    seq = seq + seq[-2:0:-1]
                for i in range(16):
                    p = rng.choice(seq) if pattern == "random" else seq[i % len(seq)]
                    notes.append({"pitch": p, "time_bars": b + i / 16.0, "length_bars": 0.055,
                                  "velocity": round(0.6 + (0.18 if i % 4 == 0 else rng.uniform(0, 0.1)), 2)})
        return notes

    # ------------------------------------------------------------------ bass

    def _bass_notes(self, profile: GenreProfile, root_midi: int, scale: List[int], prog: List[int],
                    kick: List[int]) -> List[Dict[str, Any]]:
        rng = self.rng
        notes: List[Dict[str, Any]] = []
        bass_root = root_midi - 24
        while bass_root < 33:
            bass_root += 12
        while bass_root > 45:
            bass_root -= 12
        style = profile.bass_style
        for bar, deg in enumerate(prog):
            root = self.deg_to_midi(bass_root, scale, deg)
            fifth = self.deg_to_midi(bass_root, scale, deg + 4)
            b = float(bar)
            if style == "808_follow":
                hits = sorted(set(kick)) or [0]
                for i, s in enumerate(hits):
                    nxt = hits[i + 1] if i + 1 < len(hits) else 16
                    pitch = root
                    porta = False
                    if i > 0 and rng.random() < 0.3:
                        pitch = rng.choice([root + 12, fifth, root - 2 if root - 2 > 28 else root])
                        porta = True
                    notes.append({"pitch": pitch, "time_bars": round(b + s / 16.0, 4),
                                  "length_bars": round(max(0.06, (nxt - s) / 16.0 - 0.01), 4),
                                  "velocity": 0.92, "porta": porta})
            elif style == "rolling_16th":
                for i in range(16):
                    if i % 4 == 0:
                        continue
                    if rng.random() < 0.85:
                        notes.append({"pitch": root if rng.random() < 0.8 else root + 12,
                                      "time_bars": b + i / 16.0, "length_bars": 0.05,
                                      "velocity": round(0.7 + (0.15 if i % 4 == 2 else 0.0), 2)})
            elif style == "offbeat":
                for off in (0.125, 0.375, 0.625, 0.875):
                    notes.append({"pitch": root if rng.random() < 0.8 else fifth, "time_bars": b + off,
                                  "length_bars": 0.1, "velocity": 0.85})
            elif style == "walking":
                tones = [root, self.deg_to_midi(bass_root, scale, deg + 2), fifth,
                         self.deg_to_midi(bass_root, scale, prog[(bar + 1) % len(prog)]) - 1]
                for q in range(4):
                    if q == 0 or rng.random() < 0.8:
                        notes.append({"pitch": tones[q], "time_bars": b + q * 0.25, "length_bars": 0.22,
                                      "velocity": round(0.78 + rng.uniform(-0.05, 0.08), 2)})
            elif style == "sub_whole":
                notes.append({"pitch": root, "time_bars": b, "length_bars": 0.6, "velocity": 0.8})
                notes.append({"pitch": root, "time_bars": b + 0.625, "length_bars": 0.3, "velocity": 0.7})
            elif style == "log_drum":
                cell = sorted(rng.sample([0.125, 0.25, 0.375, 0.5625, 0.6875, 0.8125, 0.9375], k=rng.randint(3, 5)))
                for off in cell:
                    notes.append({"pitch": rng.choice([root, root + 12, fifth]), "time_bars": b + off,
                                  "length_bars": 0.12, "velocity": 0.9, "porta": rng.random() < 0.35})
            else:  # syncopated
                cell = sorted(rng.sample([0.0, 0.1875, 0.375, 0.5, 0.625, 0.75, 0.875], k=rng.randint(3, 5)))
                if 0.0 not in cell:
                    cell = [0.0] + cell
                for off in cell:
                    notes.append({"pitch": root if rng.random() < 0.75 else fifth, "time_bars": b + off,
                                  "length_bars": 0.14, "velocity": round(0.8 + rng.uniform(-0.05, 0.1), 2)})
        if style == "808_follow" and len(notes) >= 2 and not any(n.get("porta") for n in notes):
            notes[-1]["porta"] = True
            notes[-1]["pitch"] = min(56, int(notes[-1]["pitch"]) + 12)
        return notes

    # ------------------------------------------------------------------ lead

    def _lead_notes(self, profile: GenreProfile, root_midi: int, scale: List[int], prog: List[int],
                    mood: str, swing: float) -> List[Dict[str, Any]]:
        rng = self.rng
        density = rng.randint(*profile.lead_density)
        weights = [3, 1, 2, 2, 3, 1, 2, 2, 3, 1, 2, 2, 3, 1, 2, 2]
        if profile.key in ("afrobeat", "reggaeton", "garage", "amapiano", "experimental"):
            weights = [2, 1, 2, 3, 1, 2, 3, 1, 2, 3, 2, 1, 2, 3, 2, 2]  # off-grid accents
        positions: List[int] = []
        pool = list(range(16))
        while len(positions) < min(density, 16):
            p = rng.choices(pool, weights=[weights[i] for i in pool])[0]
            positions.append(p)
            pool.remove(p)
        positions.sort()

        # Melodic contour in scale degrees, starting on a chord tone
        register_offset = 7 if mood not in ("dark", "sad") else 0  # degree offset above root (~octave)
        start_deg = rng.choice([0, 2, 4]) + register_offset
        contour = [start_deg]
        for _ in range(len(positions) - 1):
            step = rng.choices([-2, -1, 1, 2, 3, -3, 0], weights=[2, 4, 4, 2, 1, 1, 1])[0]
            contour.append(max(register_offset - 3, min(register_offset + 9, contour[-1] + step)))

        def emit(bar: int, degs: List[int], poss: List[int], vel_shift: float = 0.0,
                 last_long: bool = False) -> None:
            chord_shift = prog[bar] - prog[0] if rng.random() < 0.6 else 0
            for i, (deg, pos) in enumerate(zip(degs, poss)):
                nxt = poss[i + 1] if i + 1 < len(poss) else 16
                length = max(1, nxt - pos) / 16.0
                if last_long and i == len(poss) - 1:
                    length = max(length, 0.25)
                t = pos / 16.0
                if pos % 2 == 1:
                    t += swing / 16.0
                pitch = self.deg_to_midi(root_midi, scale, deg + chord_shift)
                while pitch > 86:
                    pitch -= 12
                while pitch < 55:
                    pitch += 12
                accent = 0.1 if pos % 4 == 0 else 0.0
                notes.append({
                    "pitch": int(pitch),
                    "time_bars": round(bar + t, 4),
                    "length_bars": round(min(0.95, length * rng.choice([0.6, 0.85, 1.0])), 4),
                    "velocity": round(max(0.45, min(1.0, 0.72 + accent + vel_shift + rng.uniform(-0.05, 0.05))), 2),
                })

        notes: List[Dict[str, Any]] = []
        # Bar 1: call (motif A)
        emit(0, contour, positions)
        # Bar 2: motif A repeated over next chord (sequence)
        emit(1, contour, positions, vel_shift=-0.04)
        # Bar 3: variation — inverted tail / ornament
        var = contour[:]
        if len(var) > 2:
            pivot = var[len(var) // 2]
            var = var[: len(var) // 2] + [pivot - (d - pivot) for d in var[len(var) // 2:]]
        emit(2, var, positions, vel_shift=0.03)
        # Bar 4: response & cadence back to tonic
        half = max(1, len(positions) // 2)
        resp_pos = positions[:half] + [12]
        resp_deg = contour[:half] + [register_offset]
        resp = sorted(set(zip(resp_pos, resp_deg)), key=lambda x: x[0])
        emit(3, [d for _, d in resp], [p for p, _ in resp], last_long=True)
        return notes

    # ------------------------------------------------------------------ instruments & fx

    def _instruments(self, profile: GenreProfile, lower: str) -> Dict[str, Dict[str, Any]]:
        rng = self.rng
        chosen: Dict[str, Dict[str, Any]] = {}
        for role in ("chords", "bass", "lead"):
            cands = list(profile.instruments.get(role) or UNIVERSAL_FALLBACKS)
            primary = rng.choice(cands[:2]) if len(cands) > 1 else cands[0]
            chosen[role] = {"instrument_name": primary, "fallbacks": [c for c in cands + UNIVERSAL_FALLBACKS if c != primary]}
        for kws, role, inst in INSTRUMENT_KEYWORDS:
            if any(k in lower for k in kws):
                fb = [c for c in [chosen[role]["instrument_name"]] + chosen[role]["fallbacks"] if c != inst]
                chosen[role] = {"instrument_name": inst, "fallbacks": fb, "user_requested": True}
        return chosen

    def _fx_plan(self, profile: GenreProfile, mood: str, lower: str) -> Dict[str, List[str]]:
        fx = {k: list(v) for k, v in (profile.fx or _DEF_FX).items()}
        for k, v in _DEF_FX.items():
            fx.setdefault(k, list(v))
        if mood in ("dreamy", "sad") and "Fruity Chorus" not in fx["chords"]:
            fx["chords"].insert(1, "Fruity Chorus")
        if mood == "aggressive" and "Fruity Fast Dist" not in fx["bass"]:
            fx["bass"].append("Fruity Fast Dist")
        if any(k in lower for k in ("geniş", "genis", "wide", "stereo")):
            fx["master"].insert(2, "Fruity Stereo Enhancer")
        if any(k in lower for k in ("mastering yok", "master yapma", "efekt yok", "plugin yok", "pluginsiz")):
            return {}
        return fx

    # ------------------------------------------------------------------ public API

    def generate(self, prompt: str, project_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rng = self.rng
        lower = prompt.lower()
        genre_key = self.detect_genre(lower) or rng.choice(
            ["trap", "house", "techno", "lofi", "afrobeat", "garage", "drill", "amapiano"]
        )
        profile = GENRES[genre_key]
        mood = self.detect_mood(lower)

        bpm_match = re.search(r"(\d{2,3}(?:\.\d+)?)\s*bpm", lower)
        bpm = float(bpm_match.group(1)) if bpm_match else float(rng.randint(*profile.bpm))
        scale_name = self._pick_scale(profile, mood)
        scale = SCALES[scale_name]
        key_idx = rng.randrange(12)
        key = NOTE_NAMES[key_idx]
        root_midi = 60 + key_idx if key_idx <= 6 else 48 + key_idx  # keep tonic around C4..F#4
        prog = self._progression(scale_name)
        energy = 1.25 if mood == "aggressive" else (0.8 if mood in ("dreamy", "sad") else 1.0)
        swing = round(rng.uniform(*profile.swing), 3) if profile.swing != (0.0, 0.0) else 0.0

        drums = self._drums(profile, mood, energy)
        no_808 = "808" in lower and any(w in lower for w in ("olmasın", "olmasin", "yok", "istemiyorum", "kaldır", "kaldir"))
        if no_808:
            drums["kick"] = []

        chords = self._chord_notes(profile, root_midi, scale, prog, mood)
        bass = self._bass_notes(profile, root_midi, scale, prog, drums["kick"] or [0, 8])
        lead = self._lead_notes(profile, root_midi, scale, prog, mood, swing)
        instruments = self._instruments(profile, lower)
        fx_plan = self._fx_plan(profile, mood, lower)

        tracks = [
            {"role": "chords", **instruments["chords"], "notes": chords},
            {"role": "bass", **instruments["bass"], "notes": bass},
            {"role": "lead", **instruments["lead"], "notes": lead},
        ]
        only_drums = any(w in lower for w in ("sadece davul", "sadece ritim", "only drums", "drums only"))
        if only_drums:
            tracks = []

        loud = any(w in lower for w in ("yüksek ses", "yuksek ses", "sesli", "loud", "güçlü", "guclu"))
        quiet = any(w in lower for w in ("kısık", "kisik", "düşük ses", "dusuk ses", "sessiz"))
        wants_master = not any(w in lower for w in ("mix yapma", "master yapma", "mastering yok"))

        chord_names = []
        for d in prog:
            note = NOTE_NAMES[(key_idx + scale[d % 7]) % 12]
            third = (scale[(d + 2) % 7] - scale[d % 7]) % 12
            fifth = (scale[(d + 4) % 7] - scale[d % 7]) % 12
            qual = "m" if third == 3 else ""
            if fifth == 6:
                qual = "dim"
            elif fifth == 8:
                qual = "aug"
            chord_names.append(note + qual + ("7" if profile.extensions else ""))

        def grid_str(steps: List[int]) -> str:
            return "".join("x" if i in steps else "." for i in range(16))

        mood_tr = {"dark": "karanlık", "sad": "hüzünlü", "happy": "neşeli", "aggressive": "agresif",
                   "dreamy": "rüya gibi/atmosferik", "epic": "epik", "neutral": "dengeli"}[mood]
        lines = [
            f"🎛️ **{profile.label}** — {bpm:.0f} BPM, **{key} {SCALE_LABELS_TR[scale_name]}**, ruh hali: *{mood_tr}*"
            + (f", swing %{int(swing * 100)}" if swing else ""),
            f"• **Akor yürüyüşü:** {' → '.join(chord_names)} ({profile.chord_style} tarzı, voice-leading ile)",
            f"• **Davul:** Kick `{grid_str(drums['kick'])}` · Clap `{grid_str(drums['clap'])}` · "
            f"Hat `{grid_str(drums['hat'])}` · Perc `{grid_str(drums['perc'])}`",
        ]
        if tracks:
            lines.append("• **Enstrümanlar:** " + ", ".join(
                f"{ROLE_LABELS_TR[t['role']]} → **{t['instrument_name']}** ({len(t['notes'])} nota)" for t in tracks))
            lines.append(f"• **Bas:** {profile.bass_style.replace('_', ' ')} karakteri"
                         + (" (808 glide/portamento ile)" if any(n.get('porta') for n in bass) else ""))
        if fx_plan:
            lines.append("• **Plugin zinciri:** " + " | ".join(
                f"{r.upper()}: {', '.join(v)}" for r, v in fx_plan.items()))
        if wants_master:
            lines.append("• **Mix & Mastering:** kanal isim/renk, gain staging (canlı peak ölçümü), pan, "
                         "plugin parametre ayarı ve master limiter ile -1 dBFS hedefi.")

        return {
            "ai_response": "\n".join(lines),
            "intent_type": "full_production",
            "genre": profile.key,
            "genre_label": profile.label,
            "mood": mood,
            "tempo_bpm": bpm,
            "key": key,
            "scale": scale_name,
            "swing": swing,
            "chord_progression": chord_names,
            "sections": [{"name": n, "bars": b} for n, b in profile.sections],
            "drum_channels": [
                {"channel": 0, "name": "Kick", "steps": drums["kick"]},
                {"channel": 1, "name": "Clap", "steps": drums["clap"]},
                {"channel": 2, "name": "HiHat", "steps": drums["hat"]},
                {"channel": 3, "name": "Perc/Snare", "steps": drums["perc"]},
            ],
            "tracks": tracks,
            "instrument_name": instruments["lead"]["instrument_name"],
            "melody_notes": lead,
            "fx_plan": fx_plan,
            "mix": {"enabled": wants_master, "loud": loud, "quiet": quiet, "mood": mood, "genre": profile.key},
            "mixer_volume": None,
            "play_state": "play",
        }

