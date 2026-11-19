"""Real-time Internet Song Research & Music Metadata Grounding.

Resolves real-world song references (BPM, key/scale, chord progressions,
signature melody/riff motifs, bass/drum groove, sections, and instrumentation)
BEFORE LLM composition so song remakes and replicas stay musically faithful
instead of hallucinating tempo or chords.

Combines zero-key public music APIs (iTunes Search + Deezer Track API) with
Gemini Google Search Grounding (``{"tools": [{"google_search": {}}]}``) when
a Gemini API key is available.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_HTTP_HEADERS = {
    "User-Agent": "FLStudioAIAssistant/1.0 (+https://github.com/rosasynthesiz/flstudio-mcp)",
    "Accept": "application/json",
}

# Patterns that strongly signal the user wants a SPECIFIC existing song
_EXPLICIT_SONG_RE = re.compile(
    r"(?:"
    r"\b(?:şarkısı\w*|şarkı\w*|parçası\w*|replikas\w*|replika\w*|birebir|aynısı\w*|orijinal\w*|"
    r"cover|remake|recreate|replicate|reproduce|rendition|interpolation|same\s+bpm)\b"
    r")",
    re.IGNORECASE | re.UNICODE,
)

# Style-only phrases without explicit song words (e.g. "Travis Scott tarzı beat")
_STYLE_BEAT_RE = re.compile(
    r"\b(?:tarz[ıi]nda|tarz[ıi]|type\s+beat|style\s+beat|havas[ıi]nda|benzer(?:i)?|ilhaml[ıi])\b",
    re.IGNORECASE | re.UNICODE,
)

# "Artist - Track" / "Artist – Track"
_ARTIST_TRACK_DASH_RE = re.compile(
    r"(?:^|[:\s])([A-Za-z0-9ÇĞİÖŞÜçğıöşü.$!&' ]{2,40}?)\s[-–—]\s([A-Za-z0-9ÇĞİÖŞÜçğıöşü.$!&'() ]{2,55})",
    re.UNICODE,
)

# Explicit BPM written by the user (must contain digits, e.g. "140 bpm")
_USER_BPM_RE = re.compile(r"\b(\d{2,3}(?:[.,]\d+)?)\s*bpm\b", re.IGNORECASE)

_TR_POSSESSIVE_RE = re.compile(r"['’](?:nin|nın|nun|nün|in|ın|un|ün)\b", re.IGNORECASE | re.UNICODE)

# Noise words stripped when forming music API search queries
_QUERY_STOPWORDS = frozenset({
    "bana", "bir", "tane", "lütfen", "lutfen", "hemen", "şimdi", "simdi",
    "şarkısı", "şarkısını", "şarkısının", "şarkıyı", "şarkı", "sarkisi",
    "sarkisini", "sarkisinin", "sarkiyi", "sarki", "parçasını", "parçası",
    "replikasını", "replikası", "replika", "replikasin", "replikasini",
    "birebir", "aynısı", "aynısını", "aynisini", "aynı", "ayni", "olsun",
    "yap", "yapar", "mısın", "misin", "yaparmısın", "oluştur", "olustur",
    "üret", "uret", "hazırla", "hazirla", "bpm", "falan", "filan", "merak",
    "ediyorum", "istiyorum", "çal", "cal", "tarzında", "tarzı", "gibi",
    "make", "me", "please", "the", "a", "an", "song", "track", "beat",
    "instrumental", "cover", "remake", "recreate", "replicate", "reproduce",
    "replica", "of", "same", "and", "or", "with", "for", "fl", "studio",
    "flstudio", "proje", "projesi", "müzik", "muzik", "melodi", "melodisi",
    "riff", "intro", "drop",
})

_KEY_REDACT_RE = re.compile(r"([?&]key=|AIza)[0-9A-Za-z\-_]+", re.IGNORECASE)


def _redact_url_secret(text: str) -> str:
    return _KEY_REDACT_RE.sub(r"\1[REDACTED]", str(text or ""))


def _norm_tokens(text: str) -> List[str]:
    clean = re.sub(r"[^\w\s]", " ", str(text or "").lower(), flags=re.UNICODE)
    return [tok for tok in clean.split() if len(tok) >= 2]


def _similarity_score(query: str, candidate_artist: str, candidate_title: str) -> float:
    """Score 0..1 similarity between a search query and an API track match."""
    q_tokens = _norm_tokens(query)
    if not q_tokens:
        return 0.0
    cand_full = f"{candidate_artist} {candidate_title}".lower()
    cand_tokens = _norm_tokens(cand_full)
    if not cand_tokens:
        return 0.0

    matched = 0.0
    for qt in q_tokens:
        if qt in cand_tokens:
            matched += 1.0
            continue
        best_fuzzy = max(
            (difflib.SequenceMatcher(None, qt, ct).ratio() for ct in cand_tokens),
            default=0.0,
        )
        if best_fuzzy >= 0.78:
            matched += best_fuzzy * 0.9
    score = matched / float(len(q_tokens))

    # Penalize obvious karaoke / tribute / instrumental-cover knockoffs unless requested
    q_low = query.lower()
    for bad in ("karaoke", "tribute", "lullaby", "ringtone", "8-bit", "8 bit"):
        if bad in cand_full and bad not in q_low:
            score -= 0.45
    return max(0.0, min(1.0, score))


def _strip_json_fences(text: str) -> str:
    s = str(text or "").strip()
    if "```" in s:
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    first = s.find("{")
    last = s.rfind("}")
    if first != -1 and last > first:
        return s[first : last + 1]
    return s


@dataclass
class SongQuery:
    is_song_reference: bool
    raw_prompt: str
    search_query: str
    artist_hint: str = ""
    title_hint: str = ""
    explicit_user_bpm: Optional[float] = None


@dataclass
class SongResearchDossier:
    is_song_reference: bool = False
    raw_query: str = ""
    canonical_artist: str = ""
    canonical_title: str = ""
    bpm: Optional[float] = None
    alt_bpm_note: str = ""
    key: str = ""
    scale: str = ""
    genre: str = ""
    time_signature: str = "4/4"
    chord_progression: List[str] = field(default_factory=list)
    signature_riff_notes: List[Dict[str, Any]] = field(default_factory=list)
    melody_description: str = ""
    bass_pattern: str = ""
    drum_groove: str = ""
    instrument_hints: Dict[str, str] = field(default_factory=dict)
    sections: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    deezer_bpm: Optional[float] = None
    grounded_bpm: Optional[float] = None
    confidence: str = "low"
    explicit_user_bpm: Optional[float] = None

    def resolved_label(self) -> str:
        if self.canonical_artist and self.canonical_title:
            return f"{self.canonical_artist} - {self.canonical_title}"
        return self.canonical_title or self.canonical_artist or self.raw_query


def analyze_song_request(user_prompt: str) -> SongQuery:
    """Detect if the prompt asks for a real song and extract a clean search query."""
    prompt = str(user_prompt or "").strip()
    if not prompt:
        return SongQuery(False, "", "")

    explicit_bpm: Optional[float] = None
    m_bpm = _USER_BPM_RE.search(prompt)
    if m_bpm:
        try:
            val = float(m_bpm.group(1).replace(",", "."))
            if 40.0 <= val <= 240.0:
                explicit_bpm = val
        except ValueError:
            pass

    has_song_word = bool(_EXPLICIT_SONG_RE.search(prompt))
    has_style_word = bool(_STYLE_BEAT_RE.search(prompt))
    dash_match = _ARTIST_TRACK_DASH_RE.search(prompt)

    artist_hint = ""
    title_hint = ""
    if dash_match:
        left = dash_match.group(1).strip()
        right = dash_match.group(2).strip()
        # Reject matches like "140 bpm - dark trap"
        if not _USER_BPM_RE.search(left) and len(left.split()) <= 5:
            cleaned_left_words = [
                w for w in re.split(r"\s+", left)
                if w.lower().strip(",.;:!?") not in {"bana", "bir", "make", "me", "the", "recreate", "remake"}
            ]
            artist_hint = " ".join(cleaned_left_words).strip()
            # Clean trailing stopwords from right side
            right_words = re.split(r"\s+", right)
            kept_right: List[str] = []
            for w in right_words:
                wl = re.sub(r"[^\w!']", "", w.lower())
                if wl in _QUERY_STOPWORDS:
                    break
                kept_right.append(w)
            title_hint = " ".join(kept_right).strip()

    has_artist_title_dash = bool(artist_hint and title_hint)
    has_tr_possessive = bool(
        re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2,}['’]?(?:in|ın|un|ün|nin|nın|nun|nün)\s+[A-Za-z0-9]", prompt)
        and has_song_word
    )

    is_song_ref = bool(
        has_artist_title_dash
        or has_song_word
        or has_tr_possessive
    )
    # "Travis Scott tarzı beat" without "birebir/şarkısı/replika/-" is a style beat, not one track
    if has_style_word and not (has_song_word or has_artist_title_dash):
        is_song_ref = False

    # Build clean search string for APIs
    if has_artist_title_dash:
        search_q = f"{artist_hint} {title_hint}".strip()
    else:
        cleaned = _TR_POSSESSIVE_RE.sub("", prompt)
        cleaned = _USER_BPM_RE.sub(" ", cleaned)
        raw_tokens = re.findall(r"[A-Za-z0-9ÇĞİÖŞÜçğıöşü!$&'+-]+", cleaned, re.UNICODE)
        kept: List[str] = []
        for idx, tok in enumerate(raw_tokens):
            low = tok.lower().strip(",.;:!?")
            if low in _QUERY_STOPWORDS:
                continue
            # Standalone Turkish possessive 'in'/'ın' between capitalized artist and track:
            # e.g. "Kanye West in Runway" -> skip standalone "in" only if surrounded by capitalized words
            if low in ("in", "ın", "un", "ün", "nin", "nın") and 0 < idx < len(raw_tokens) - 1:
                prev_cap = raw_tokens[idx - 1][:1].isupper()
                next_cap = raw_tokens[idx + 1][:1].isupper()
                if prev_cap and next_cap:
                    continue
            kept.append(tok)
        search_q = " ".join(kept[:8]).strip()

    return SongQuery(
        is_song_reference=is_song_ref,
        raw_prompt=prompt,
        search_query=search_q,
        artist_hint=artist_hint,
        title_hint=title_hint,
        explicit_user_bpm=explicit_bpm,
    )


def _fetch_json(url: str, timeout: float = 4.5) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers=_HTTP_HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("Song lookup GET failed (%s): %s", _redact_url_secret(url), _redact_url_secret(str(exc)))
        return None


def lookup_itunes_track(query: str, timeout: float = 4.5) -> Optional[Dict[str, Any]]:
    """Resolve canonical artist/track/genre via iTunes public Search API."""
    q = str(query or "").strip()
    if len(q) < 2:
        return None
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": q, "media": "music", "entity": "song", "limit": 5}
    )
    payload = _fetch_json(url, timeout=timeout)
    results = (payload or {}).get("results") or []
    if not results:
        return None

    best_item: Optional[Dict[str, Any]] = None
    best_score = -1.0
    for item in results:
        if not isinstance(item, dict):
            continue
        artist = str(item.get("artistName") or "").strip()
        title = str(item.get("trackName") or "").strip()
        if not artist or not title:
            continue
        score = _similarity_score(q, artist, title)
        if score > best_score:
            best_score = score
            best_item = item

    if best_item is None or best_score < 0.35:
        return None

    release = str(best_item.get("releaseDate") or "")[:4]
    return {
        "artist": str(best_item.get("artistName") or "").strip(),
        "title": str(best_item.get("trackName") or "").strip(),
        "genre": str(best_item.get("primaryGenreName") or "").strip(),
        "album": str(best_item.get("collectionName") or "").strip(),
        "year": release,
        "duration_ms": int(best_item.get("trackTimeMillis") or 0),
        "score": round(best_score, 3),
        "source": "iTunes Search API",
    }


def lookup_deezer_bpm(
    query: str,
    artist_hint: str = "",
    title_hint: str = "",
    timeout: float = 4.5,
) -> Optional[Dict[str, Any]]:
    """Fetch exact catalog BPM & metadata from Deezer's public Track API."""
    q_parts = [p for p in (artist_hint, title_hint) if p]
    q = " ".join(q_parts).strip() or str(query or "").strip()
    if len(q) < 2:
        return None

    search_url = "https://api.deezer.com/search?" + urllib.parse.urlencode({"q": q, "limit": 5})
    payload = _fetch_json(search_url, timeout=timeout)
    items = (payload or {}).get("data") or []
    if not items:
        return None

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        artist = str(((item.get("artist") or {}).get("name")) or "").strip()
        title = str(item.get("title") or "").strip()
        tid = item.get("id")
        if not tid or not title:
            continue
        score = _similarity_score(q, artist, title)
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored or scored[0][0] < 0.35:
        return None

    # Inspect up to top 2 matching tracks in case the first lacks a BPM tag
    best_fallback: Optional[Dict[str, Any]] = None
    for _, cand in scored[:2]:
        tid = cand["id"]
        detail = _fetch_json(f"https://api.deezer.com/track/{int(tid)}", timeout=timeout)
        if not detail or detail.get("error"):
            continue
        artist = str(((detail.get("artist") or {}).get("name")) or "").strip()
        title = str(detail.get("title") or "").strip()
        raw_bpm = detail.get("bpm")
        bpm_val: Optional[float] = None
        try:
            b = float(raw_bpm or 0)
            if 40.0 <= b <= 240.0:
                bpm_val = round(b, 2)
        except (TypeError, ValueError):
            bpm_val = None
        entry = {
            "artist": artist,
            "title": title,
            "bpm": bpm_val,
            "duration_sec": int(detail.get("duration") or 0),
            "source": f"Deezer Track API (id={tid})",
        }
        if bpm_val is not None:
            return entry
        if best_fallback is None:
            best_fallback = entry
    return best_fallback


def _build_research_prompt(query_text: str, user_prompt: str, canonical_label: str) -> str:
    target = canonical_label or query_text
    return (
        f'Search the web for the real musical production facts of the song "{target}" '
        f'(user request: "{user_prompt[:140]}").\n'
        "Find verified facts from music theory/BPM/tab/chord databases (such as Tunebat, SongBPM, "
        "Musicnotes, Ultimate Guitar, Hooktheory, Genius, Wikipedia) for:\n"
        "1. Exact Artist & Official Song Title\n"
        "2. Exact BPM / Tempo (and mention if commonly felt in half-time or double-time)\n"
        "3. Exact Musical Key & Scale (e.g. F# minor, E major, C natural_minor, etc.)\n"
        "4. Exact 4-bar or 8-bar Chord Progression (chord names bar by bar)\n"
        "5. Exact Iconic Melody / Riff / Arpeggio motif notes with octaves and beat offsets across 4 bars "
        "(use standard scientific pitch notation or MIDI note numbers, e.g. MIDI 76 / E5, and beat times 0.0..4.0)\n"
        "6. Bass / 808 pattern and Drum groove (Kick, Snare/Clap, Hi-Hat subdivisions)\n"
        "7. Primary instruments/timbres (e.g. FL Keys piano, Sakura plucked guitar, muted electric bass, 808 sub)\n\n"
        "Respond ONLY with a single JSON object (no commentary before or after) matching this schema:\n"
        "{\n"
        '  "artist": "Official Artist",\n'
        '  "title": "Official Song Title",\n'
        '  "bpm": 84.0,\n'
        '  "alt_bpm_note": "84 BPM half-time feel (168 BPM double-time)",\n'
        '  "key": "B",\n'
        '  "scale": "natural_minor",\n'
        '  "genre": "emo_rap",\n'
        '  "time_signature": "4/4",\n'
        '  "chord_progression": ["Bm", "A", "G", "Em"],\n'
        '  "signature_riff_notes": [\n'
        '    {"pitch": 71, "note": "B4", "time_bars": 0.0, "length_bars": 0.25, "velocity": 0.85}\n'
        "  ],\n"
        '  "melody_description": "Concise bar-by-bar description of the main hook/riff/piano motif",\n'
        '  "bass_pattern": "Follows chord roots B1-A1-G1-E1 on beats 1 and syncopated 3+",\n'
        '  "drum_groove": "84 BPM trap-emo groove: punchy kick syncopated, snare on 2 & 4 (steps 4,12), steady 8th/16th hi-hats",\n'
        '  "instrument_hints": {"chords": "Plucked Guitar / Grand Piano", "bass": "808 Sub Bass", "lead": "Bell / Guitar Top"},\n'
        '  "sections": [{"name": "Intro", "bars": 4, "roles": ["chords", "lead"]}, {"name": "Verse", "bars": 8, "roles": ["drums", "chords", "bass"]}, {"name": "Chorus", "bars": 8, "roles": ["drums", "chords", "bass", "lead"]}]\n'
        "}"
    )


def _call_gemini_search_grounding(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    prompt_text: str,
    timeout_seconds: float = 14.0,
) -> Optional[Dict[str, Any]]:
    """Run Gemini generateContent with native Google Search Grounding (NO responseMimeType)."""
    if not api_key:
        return None
    base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    url = f"{base}/models/{model_name}:generateContent?key={api_key}"
    # NOTE: Do NOT pass responseMimeType="application/json" alongside google_search tool.
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates") or []
    if not candidates:
        return None
    cand = candidates[0]
    parts = ((cand.get("content") or {}).get("parts") or [])
    raw_text = "".join(str(p.get("text", "")) for p in parts).strip()
    if not raw_text:
        return None

    parsed = json.loads(_strip_json_fences(raw_text))
    if not isinstance(parsed, dict):
        return None

    gm = cand.get("groundingMetadata") or {}
    queries = [str(q) for q in (gm.get("webSearchQueries") or []) if q]
    sources: List[str] = []
    for chunk in (gm.get("groundingChunks") or []):
        web = chunk.get("web") if isinstance(chunk, dict) else None
        if isinstance(web, dict):
            title = str(web.get("title") or "").strip()
            uri = str(web.get("uri") or "").strip()
            if title:
                sources.append(title)
            elif uri:
                sources.append(uri)

    parsed["_grounding_queries"] = queries
    parsed["_grounding_sources"] = sources[:6]
    parsed["_grounding_model"] = model_name
    return parsed


def research_song_with_gemini_search(
    *,
    api_key: str,
    base_url: str,
    preferred_models: List[str],
    query_text: str,
    user_prompt: str,
    canonical_label: str = "",
    timeout_seconds: float = 14.0,
) -> Optional[Dict[str, Any]]:
    """Try Google Search Grounding across preferred Gemini models cleanly."""
    if not api_key:
        return None
    prompt = _build_research_prompt(query_text, user_prompt, canonical_label)
    seen: set[str] = set()
    for model in preferred_models:
        m = str(model or "").strip()
        if not m or m in seen:
            continue
        seen.add(m)
        try:
            res = _call_gemini_search_grounding(
                api_key=api_key,
                base_url=base_url,
                model_name=m,
                prompt_text=prompt,
                timeout_seconds=timeout_seconds,
            )
            if res:
                return res
        except urllib.error.HTTPError as exc:
            err_detail = ""
            try:
                err_detail = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            logger.info(
                "Gemini Search Grounding (%s) HTTP %s: %s",
                m,
                exc.code,
                _redact_url_secret(err_detail),
            )
            continue
        except Exception as exc:
            logger.info("Gemini Search Grounding (%s) failed: %s", m, _redact_url_secret(str(exc)))
            continue
    return None


def _normalize_scale_token(scale_raw: str) -> str:
    s = str(scale_raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "minor": "natural_minor",
        "min": "natural_minor",
        "aeolian": "natural_minor",
        "natural_minor": "natural_minor",
        "harmonic_minor": "harmonic_minor",
        "melodic_minor": "natural_minor",
        "major": "major",
        "maj": "major",
        "ionian": "major",
        "phrygian": "phrygian",
        "dorian": "dorian",
        "minor_pentatonic": "minor_pentatonic",
        "pentatonic_minor": "minor_pentatonic",
    }
    return mapping.get(s, s or "natural_minor")


def _reconcile_bpm(
    explicit_user_bpm: Optional[float],
    grounded_bpm: Optional[float],
    deezer_bpm: Optional[float],
) -> Tuple[Optional[float], str]:
    """Choose the most reliable production BPM and note half/double-time context."""
    if explicit_user_bpm is not None:
        return round(explicit_user_bpm, 2), f"User requested explicit {explicit_user_bpm} BPM"

    if grounded_bpm and deezer_bpm:
        if abs(grounded_bpm - deezer_bpm) <= 2.5:
            # Grounded music database + Deezer agree directly
            return round(grounded_bpm, 2), ""
        # Check half-time / double-time match (e.g. 84 vs 168)
        ratio = max(grounded_bpm, deezer_bpm) / max(1.0, min(grounded_bpm, deezer_bpm))
        if 1.92 <= ratio <= 2.08:
            lo = round(min(grounded_bpm, deezer_bpm), 2)
            hi = round(max(grounded_bpm, deezer_bpm), 2)
            # In FL Studio trap/hip-hop/pop workflows, if grounded_bpm is in [62, 165], prefer it
            chosen = grounded_bpm if 62.0 <= grounded_bpm <= 165.0 else lo
            return round(chosen, 2), f"Researched half/double-time pair: {lo} BPM vs {hi} BPM (using {round(chosen, 2)} BPM)"
        # Otherwise prefer grounded theory BPM over catalog DSP estimate
        return round(grounded_bpm, 2), f"Search-grounded BPM {grounded_bpm} (catalog estimate: {deezer_bpm})"

    if grounded_bpm:
        return round(grounded_bpm, 2), ""
    if deezer_bpm:
        return round(deezer_bpm, 2), ""
    return None, ""


def research_song(
    user_prompt: str,
    *,
    gemini_api_key: str = "",
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    gemini_models: Optional[List[str]] = None,
    allow_in_pytest: bool = False,
) -> SongResearchDossier:
    """Detect whether the prompt references an existing song and gather web-grounded facts."""
    sq = analyze_song_request(user_prompt)
    dossier = SongResearchDossier(
        is_song_reference=sq.is_song_reference,
        raw_query=sq.search_query or user_prompt,
        canonical_artist=sq.artist_hint,
        canonical_title=sq.title_hint,
        explicit_user_bpm=sq.explicit_user_bpm,
    )

    if not sq.is_song_reference:
        return dossier

    if "PYTEST_CURRENT_TEST" in os.environ and not allow_in_pytest:
        return dossier

    search_term = sq.search_query or user_prompt

    # Step 1: Canonicalize Artist & Track via iTunes (super fast & resilient to typos like "Runway")
    itunes_res = lookup_itunes_track(search_term, timeout=4.5)
    if itunes_res:
        dossier.canonical_artist = itunes_res.get("artist") or dossier.canonical_artist
        dossier.canonical_title = itunes_res.get("title") or dossier.canonical_title
        if itunes_res.get("genre"):
            dossier.genre = str(itunes_res["genre"])
        dossier.sources.append(str(itunes_res["source"]))

    canonical_label = (
        f"{dossier.canonical_artist} - {dossier.canonical_title}"
        if dossier.canonical_artist and dossier.canonical_title
        else search_term
    )

    # Step 2: Run Deezer Track BPM lookup & Gemini Google Search Grounding in parallel
    deezer_res: Optional[Dict[str, Any]] = None
    gemini_res: Optional[Dict[str, Any]] = None
    models_to_try = list(gemini_models or [
        "gemini-3-flash-preview",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
    ])

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_deezer = pool.submit(
            lookup_deezer_bpm,
            search_term,
            dossier.canonical_artist,
            dossier.canonical_title,
            4.5,
        )
        fut_gemini = (
            pool.submit(
                research_song_with_gemini_search,
                api_key=gemini_api_key,
                base_url=gemini_base_url,
                preferred_models=models_to_try,
                query_text=search_term,
                user_prompt=user_prompt,
                canonical_label=canonical_label,
                timeout_seconds=14.0,
            )
            if gemini_api_key
            else None
        )
        try:
            deezer_res = fut_deezer.result(timeout=6.0)
        except Exception:
            deezer_res = None
        if fut_gemini is not None:
            try:
                gemini_res = fut_gemini.result(timeout=16.0)
            except Exception:
                gemini_res = None

    if deezer_res:
        if not dossier.canonical_artist and deezer_res.get("artist"):
            dossier.canonical_artist = str(deezer_res["artist"])
        if not dossier.canonical_title and deezer_res.get("title"):
            dossier.canonical_title = str(deezer_res["title"])
        if deezer_res.get("bpm"):
            dossier.deezer_bpm = float(deezer_res["bpm"])
        dossier.sources.append(str(deezer_res.get("source") or "Deezer Track API"))

    if gemini_res:
        if gemini_res.get("artist"):
            dossier.canonical_artist = str(gemini_res["artist"]).strip()
        if gemini_res.get("title"):
            dossier.canonical_title = str(gemini_res["title"]).strip()
        try:
            gbpm = float(gemini_res.get("bpm") or 0)
            if 40.0 <= gbpm <= 240.0:
                dossier.grounded_bpm = round(gbpm, 2)
        except (TypeError, ValueError):
            pass
        if gemini_res.get("alt_bpm_note"):
            dossier.alt_bpm_note = str(gemini_res["alt_bpm_note"]).strip()
        if gemini_res.get("key"):
            dossier.key = str(gemini_res["key"]).strip()
        if gemini_res.get("scale"):
            dossier.scale = _normalize_scale_token(str(gemini_res["scale"]))
        if gemini_res.get("genre"):
            dossier.genre = str(gemini_res["genre"]).strip()
        if gemini_res.get("time_signature"):
            dossier.time_signature = str(gemini_res["time_signature"]).strip()
        if isinstance(gemini_res.get("chord_progression"), list):
            dossier.chord_progression = [str(c) for c in gemini_res["chord_progression"] if c][:12]
        if isinstance(gemini_res.get("signature_riff_notes"), list):
            cleaned_riff: List[Dict[str, Any]] = []
            for n in gemini_res["signature_riff_notes"][:48]:
                if not isinstance(n, dict):
                    continue
                try:
                    pitch = max(24, min(108, int(round(float(n["pitch"])))))
                    t_bars = max(0.0, min(8.0, float(n.get("time_bars", 0.0))))
                    l_bars = max(0.0625, min(4.0, float(n.get("length_bars", 0.25))))
                    vel = max(0.2, min(1.0, float(n.get("velocity", 0.85))))
                    item: Dict[str, Any] = {
                        "pitch": pitch,
                        "time_bars": round(t_bars, 4),
                        "length_bars": round(l_bars, 4),
                        "velocity": round(vel, 3),
                    }
                    if n.get("note"):
                        item["note"] = str(n["note"])
                    cleaned_riff.append(item)
                except (KeyError, TypeError, ValueError):
                    continue
            dossier.signature_riff_notes = cleaned_riff
        if gemini_res.get("melody_description"):
            dossier.melody_description = str(gemini_res["melody_description"]).strip()
        if gemini_res.get("bass_pattern"):
            dossier.bass_pattern = str(gemini_res["bass_pattern"]).strip()
        if gemini_res.get("drum_groove"):
            dossier.drum_groove = str(gemini_res["drum_groove"]).strip()
        if isinstance(gemini_res.get("instrument_hints"), dict):
            dossier.instrument_hints = {
                str(k): str(v) for k, v in gemini_res["instrument_hints"].items() if v
            }
        if isinstance(gemini_res.get("sections"), list):
            dossier.sections = [s for s in gemini_res["sections"] if isinstance(s, dict)][:6]
        for q in (gemini_res.get("_grounding_queries") or []):
            dossier.search_queries.append(str(q))
        for src in (gemini_res.get("_grounding_sources") or []):
            dossier.sources.append(f"Google Search: {src}")
        if gemini_res.get("_grounding_model"):
            dossier.sources.append(f"Grounded via {gemini_res['_grounding_model']}")

    chosen_bpm, bpm_note = _reconcile_bpm(
        sq.explicit_user_bpm, dossier.grounded_bpm, dossier.deezer_bpm
    )
    dossier.bpm = chosen_bpm
    if bpm_note and not dossier.alt_bpm_note:
        dossier.alt_bpm_note = bpm_note

    if dossier.grounded_bpm and (dossier.chord_progression or dossier.key):
        dossier.confidence = "high"
    elif dossier.bpm or dossier.canonical_title:
        dossier.confidence = "medium"
    else:
        dossier.confidence = "low"

    return dossier


def format_dossier_for_prompt(dossier: SongResearchDossier) -> str:
    """Format verified song research into strict instructions for Stage-2 composition."""
    if not dossier or not dossier.is_song_reference:
        return ""

    lines = [
        "\nVERIFIED INTERNET SONG RESEARCH DOSSIER (FOLLOW FAITHFULLY):"
    ]
    if dossier.resolved_label():
        lines.append(f"- Canonical Reference Song: {dossier.resolved_label()}")
    if dossier.bpm is not None:
        lines.append(
            f"- LOCKED TEMPO_BPM: {dossier.bpm} BPM (MUST set \"tempo_bpm\": {dossier.bpm} — DO NOT invent a different BPM!)"
        )
    if dossier.alt_bpm_note:
        lines.append(f"- Tempo Feel Note: {dossier.alt_bpm_note}")
    if dossier.key:
        lines.append(f"- LOCKED KEY & SCALE: key={dossier.key!r}, scale={dossier.scale or 'natural_minor'!r}")
    if dossier.genre:
        lines.append(f"- Style / Genre: {dossier.genre}")
    if dossier.chord_progression:
        lines.append(f"- Verified Chord Progression: {' -> '.join(dossier.chord_progression)}")
    if dossier.melody_description:
        lines.append(f"- Signature Hook / Riff Breakdown: {dossier.melody_description}")
    if dossier.signature_riff_notes:
        sample_json = json.dumps(dossier.signature_riff_notes[:32], ensure_ascii=False)
        lines.append(
            f"- Verified Signature Riff MIDI Notes (adapt cleanly across bars 0.0..4.0 in lead/keys track): {sample_json}"
        )
    if dossier.bass_pattern:
        lines.append(f"- Bass / 808 Pattern: {dossier.bass_pattern}")
    if dossier.drum_groove:
        lines.append(f"- Drum Groove: {dossier.drum_groove}")
    if dossier.instrument_hints:
        lines.append(f"- Recommended FL Native Sound Palette: {json.dumps(dossier.instrument_hints, ensure_ascii=False)}")
    if dossier.sections:
        lines.append(f"- Suggested Sections with active roles: {json.dumps(dossier.sections[:4], ensure_ascii=False)}")
    if dossier.sources:
        lines.append(f"- Grounding Sources: {', '.join(dossier.sources[:5])}")

    lines.append(
        "- STRICT FIDELITY RULE: Do NOT output sparse placeholder notes (never just 4 notes). "
        "Reproduce the recognizable iconic melody/arpeggio & chord voicings accurately across the full 4.0 bars."
    )
    return "\n".join(lines)
