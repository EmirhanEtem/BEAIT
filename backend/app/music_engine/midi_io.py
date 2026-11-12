"""Standard MIDI File (.mid) export and import using mido."""

from __future__ import annotations

import os
from typing import List, Optional
import mido
from .models import MidiNote, MidiPattern


def export_midi_file(
    pattern: MidiPattern,
    output_path: str,
    *,
    ppq: int = 480,
    track_name: Optional[str] = None,
) -> str:
    """Export a MidiPattern to a standard MIDI format 0/1 file.

    Returns the absolute path to the written file.
    """
    mid = mido.MidiFile(ticks_per_beat=ppq)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    # Track name meta message
    name = track_name or pattern.name
    track.append(mido.MetaMessage("track_name", name=name, time=0))

    # Set tempo meta message (microseconds per beat)
    tempo_us = mido.bpm2tempo(pattern.tempo_bpm)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo_us, time=0))

    # Time signature meta message
    num, den = pattern.time_signature
    track.append(mido.MetaMessage("time_signature", numerator=num, denominator=den, time=0))

    # Convert notes to absolute tick events
    # In 4/4 time, 1 bar = numerator beats = 4 beats = 4 * ppq ticks
    ticks_per_bar = num * ppq

    events = []
    for note in pattern.notes:
        start_tick = int(round(note.time_bars * ticks_per_bar))
        end_tick = start_tick + max(1, int(round(note.length_bars * ticks_per_bar)))
        vel = max(1, min(127, int(round(note.velocity * 127))))

        # Note ON event
        events.append((start_tick, 0, "note_on", note.pitch, vel, note.channel))
        # Note OFF event
        events.append((end_tick, 1, "note_off", note.pitch, 0, note.channel))

    # Sort events by tick; if same tick, note_off comes before note_on for clear retrigger
    events.sort(key=lambda e: (e[0], e[1]))

    last_tick = 0
    for tick, _, msg_type, pitch, vel, channel in events:
        delta = tick - last_tick
        track.append(
            mido.Message(
                msg_type,
                note=pitch,
                velocity=vel,
                channel=channel,
                time=delta,
            )
        )
        last_tick = tick

    track.append(mido.MetaMessage("end_of_track", time=0))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    mid.save(output_path)
    return os.path.abspath(output_path)


def read_midi_file(file_path: str) -> MidiPattern:
    """Read a standard MIDI file into a MidiPattern."""
    mid = mido.MidiFile(file_path)
    ppq = mid.ticks_per_beat

    tempo_bpm = 120.0
    notes: List[MidiNote] = []

    for track in mid.tracks:
        abs_tick = 0
        active_notes = {}  # (pitch, channel) -> (start_tick, velocity)

        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                tempo_bpm = mido.tempo2bpm(msg.tempo)
            elif msg.type == "note_on" and msg.velocity > 0:
                active_notes[(msg.note, msg.channel)] = (abs_tick, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.note, msg.channel)
                if key in active_notes:
                    start_tick, vel = active_notes.pop(key)
                    dur_ticks = abs_tick - start_tick
                    # 1 bar = 4 * ppq ticks in 4/4
                    time_bars = start_tick / (4.0 * ppq)
                    length_bars = max(0.001, dur_ticks / (4.0 * ppq))
                    notes.append(
                        MidiNote(
                            pitch=msg.note,
                            time_bars=round(time_bars, 4),
                            length_bars=round(length_bars, 4),
                            velocity=round(vel / 127.0, 3),
                            channel=msg.channel,
                        )
                    )

    return MidiPattern(
        name=os.path.basename(file_path),
        tempo_bpm=round(tempo_bpm, 1),
        notes=sorted(notes, key=lambda n: n.time_bars),
    )

