"""VoiceLab engine.

Renders Piper or Kokoro voices with tunable settings and manages a catalog of
presets that any robot can use:

    from voicelab import speak
    speak("stelly", "Hi Skyler!")
"""
from __future__ import annotations

import json
import os
import time
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig

# VoiceLab folder. Set VOICELAB_HOME to point a robot at a different copy.
HOME = Path(os.environ.get("VOICELAB_HOME", Path(__file__).resolve().parent))
VOICES_DIR = HOME / "voices"
CATALOG_PATH = HOME / "catalog.json"
KOKORO_MODEL = VOICES_DIR / "kokoro-v1.0.fp16.onnx"  # int8 version glitches, avoid it
KOKORO_VOICES = VOICES_DIR / "voices-v1.0.bin"
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
ENGINES = ["kokoro", "piper", "beeps"]
BEEP_STYLES = ["chirpy", "whistle", "buzzy"]

DEFAULTS = {
    "engine": "piper",      # "piper" or "kokoro"
    "voice": "",            # Piper .onnx file name, or Kokoro voice name like af_heart
    "blend_voice": "",      # Kokoro only: second voice to mix in
    "blend": 0.0,           # Kokoro only: 0 = all main voice, 1 = all blend voice
    "speaker": 0,           # speaker id (only matters for multi speaker voices)
    "speed": 1.0,           # higher = faster
    "pitch": 0.0,           # semitones, +12 = one octave up
    "expressiveness": 0.667,  # Piper noise_scale
    "rhythm": 0.8,          # Piper noise_w_scale (timing wobble)
    "robot_mix": 0.0,       # 0 = clean, 1 = full ring mod robot
    "robot_freq": 50.0,     # robot carrier tone in Hz
    "beep_pitch": 1200.0,   # Beeps only: base tone in Hz
    "crunch": 0.0,          # 0 = clean, higher = lo-fi, low battery robot
    "metallic": 0.0,        # 0 = clean, higher = tin can shimmer
    "tin_size": 5.0,        # shimmer delay in ms, smaller = brighter and tinier
    "volume": 1.0,
    "pan": 0.0,             # -1 = left speaker, 0 = center, 1 = right speaker
    "width": 0.0,           # 0 = narrow, 1 = wide and roomy
    "sweep": 0.0,           # moves the voice across during a line (minus = right to left)
}

_voices: dict[str, PiperVoice] = {}
_kokoro = None


# ---------- voices ----------

def kokoro_ready() -> bool:
    return KOKORO_MODEL.exists() and KOKORO_VOICES.exists()


def get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
    return _kokoro


def download_kokoro(progress=print) -> None:
    """Grab the Kokoro model (about 200 MB total) into voices/."""
    import urllib.request
    VOICES_DIR.mkdir(exist_ok=True)
    for path in (KOKORO_VOICES, KOKORO_MODEL):
        if not path.exists():
            progress(f"Downloading {path.name}...")
            tmp = path.with_suffix(path.suffix + ".part")
            urllib.request.urlretrieve(KOKORO_URL + path.name, tmp)
            tmp.replace(path)


def list_voices(engine: str = "piper") -> list[str]:
    if engine == "beeps":
        return list(BEEP_STYLES)
    if engine == "kokoro":
        return sorted(get_kokoro().get_voices()) if kokoro_ready() else []
    return sorted(p.name for p in VOICES_DIR.glob("*.onnx")
                  if not p.name.startswith("kokoro"))


def load_voice(name: str) -> PiperVoice:
    """Load once, then reuse. Reloading every line is a big source of lag."""
    if name not in _voices:
        path = VOICES_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"Voice not found: {path}")
        _voices[name] = PiperVoice.load(path)
    return _voices[name]


def speakers(name: str) -> list[tuple[int, str]]:
    """List (id, label) speakers for a voice."""
    cfg = load_voice(name).config
    if cfg.num_speakers <= 1:
        return [(0, "default")]
    if cfg.speaker_id_map:
        return sorted(((i, n) for n, i in cfg.speaker_id_map.items()))
    return [(i, str(i)) for i in range(cfg.num_speakers)]


# ---------- rendering ----------

def _pitch_shift(audio: np.ndarray, factor: float) -> np.ndarray:
    # Squeeze the waveform so it plays higher. Piper already made the
    # speech longer by the same factor, so the final speed stays the same.
    idx = np.arange(0, len(audio) - 1, factor)
    return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def _robotize(audio: np.ndarray, sr: int, mix: float, freq: float) -> np.ndarray:
    t = np.arange(len(audio)) / sr
    carrier = np.sin(2 * np.pi * freq * t).astype(np.float32)
    return audio * (1 - mix) + audio * carrier * mix


def _kokoro_lang(voice: str) -> str:
    return {"a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr", "h": "hi",
            "i": "it", "j": "ja", "p": "pt-br", "z": "cmn"}.get(voice[:1], "en-us")


def _render_kokoro(s: dict, text: str, shift: float) -> tuple[np.ndarray, int]:
    k = get_kokoro()
    style = k.get_voice_style(s["voice"])
    if s["blend_voice"] and float(s["blend"]) > 0:
        b = float(s["blend"])
        style = style * (1 - b) + k.get_voice_style(s["blend_voice"]) * b
    speed = min(max(float(s["speed"]) / shift, 0.5), 2.0)
    audio, sr = k.create(text, voice=style.astype(np.float32), speed=speed,
                         lang=_kokoro_lang(s["voice"]))
    return np.nan_to_num(np.asarray(audio, dtype=np.float32)), sr


def _render_piper(s: dict, text: str, shift: float) -> tuple[np.ndarray, int]:
    voice = load_voice(s["voice"])
    cfg = SynthesisConfig(
        speaker_id=int(s["speaker"]) if voice.config.num_speakers > 1 else None,
        length_scale=shift / float(s["speed"]),
        noise_scale=float(s["expressiveness"]),
        noise_w_scale=float(s["rhythm"]),
    )
    chunks = [c.audio_float_array for c in voice.synthesize(text, syn_config=cfg)]
    audio = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    return audio, voice.config.sample_rate


def _crunch(audio: np.ndarray, amount: float) -> np.ndarray:
    # Hold each sample for a few steps (fewer samples per second) and
    # round it to fewer volume levels (fewer bits). Old hardware sound.
    hold = 1 + int(amount * 7)
    if hold > 1:
        audio = np.repeat(audio[::hold], hold)[:len(audio)]
    levels = 2 ** (16 - amount * 12)
    return np.round(audio * levels) / levels


def _render_beeps(s: dict, text: str) -> tuple[np.ndarray, int]:
    """Turn text into robot chirps. Same text always makes the same beeps."""
    import re
    import zlib
    sr = 22050
    rng = np.random.default_rng(zlib.crc32(text.encode()))
    style = s["voice"] if s["voice"] in BEEP_STYLES else "chirpy"
    base = float(s["beep_pitch"]) * 2 ** (float(s["pitch"]) / 12)
    pace = 1 / max(float(s["speed"]), 0.1)
    parts = []

    def tone(f0, f1, dur, wobble=0.0):
        n = int(sr * dur)
        t = np.arange(n) / sr
        freq = np.linspace(f0, f1, n) * (1 + wobble * np.sin(2 * np.pi * 18 * t))
        phase = 2 * np.pi * np.cumsum(freq) / sr
        if style == "buzzy":
            wave = np.tanh(3 * np.sin(phase)) * 0.6
        elif style == "whistle":
            wave = np.sin(phase)
        else:
            wave = np.sin(phase) + 0.25 * np.sin(2 * phase)
        env = np.minimum(1, np.minimum(t, t[::-1]) / 0.008)  # no clicks
        return (wave * env * 0.5).astype(np.float32)

    def gap(dur):
        return np.zeros(int(sr * dur), dtype=np.float32)

    for word, punct in re.findall(r"([A-Za-z0-9']+)([.!?,]*)", text):
        beats = max(1, len(re.findall(r"[aeiouy]+", word.lower())))
        for b in range(beats):
            f0 = base * rng.uniform(0.6, 1.8)
            kind = rng.choice(["flat", "up", "down", "warble"])
            f1 = {"flat": f0, "up": f0 * 1.6, "down": f0 * 0.6, "warble": f0}[kind]
            if b == beats - 1 and "?" in punct:
                f1 = f0 * 2.0  # questions slide up
            if b == beats - 1 and "!" in punct:
                f0, f1 = f0 * 1.3, f0 * 1.8
            wob = 0.06 if kind == "warble" or style == "whistle" else 0.0
            parts += [tone(f0, f1, rng.uniform(0.06, 0.14) * pace, wob), gap(0.025 * pace)]
        parts.append(gap((0.18 if punct else 0.07) * pace))
    if not parts:
        return np.zeros(0, dtype=np.float32), sr
    return np.concatenate(parts), sr


def _metallize(audio: np.ndarray, sr: int, amount: float, ms: float) -> np.ndarray:
    # A short comb filter: the voice plus a few quick echoes of itself.
    # Very short echoes blur into a hollow, metal box sound.
    d = max(1, int(sr * ms / 1000))
    out = audio.copy()
    gain = 1.0
    for k in range(1, 5):
        gain *= amount
        out[d * k:] += gain * audio[:-d * k] if d * k < len(audio) else 0
    return out


def render(settings: dict, text: str) -> tuple[np.ndarray, int]:
    """Turn text into audio using a settings dict. Returns (audio, sample_rate)."""
    s = {**DEFAULTS, **settings}
    shift = 2 ** (float(s["pitch"]) / 12)
    if s["engine"] == "beeps":
        audio, sr = _render_beeps(s, text)
        shift = 1.0  # pitch is already baked into the beeps
    elif s["engine"] == "kokoro":
        audio, sr = _render_kokoro(s, text, shift)
    else:
        audio, sr = _render_piper(s, text, shift)
    if not len(audio):
        return audio, sr

    if abs(shift - 1) > 1e-3:
        audio = _pitch_shift(audio, shift)
    if s["crunch"] > 0:
        audio = _crunch(audio, float(s["crunch"]))
    if s["metallic"] > 0:
        audio = _metallize(audio, sr, float(s["metallic"]), float(s["tin_size"]))
    if s["robot_mix"] > 0:
        audio = _robotize(audio, sr, float(s["robot_mix"]), float(s["robot_freq"]))
    audio *= float(s["volume"])
    peak = float(np.abs(audio).max())
    if peak > 0.99:
        audio *= 0.99 / peak
    return audio, sr


# ---------- space (left and right speakers) ----------

def spatialize(audio: np.ndarray, sr: int, pan: float = 0.0,
               width: float = 0.0, sweep: float = 0.0) -> np.ndarray:
    """Mono in, stereo out (n, 2). Places the voice between the speakers."""
    n = len(audio)
    # where the voice sits over time: start at pan - sweep, end at pan + sweep
    pos = np.clip(np.linspace(pan - sweep, pan + sweep, n), -1, 1) if sweep else np.full(n, np.clip(pan, -1, 1))
    angle = (pos + 1) * np.pi / 4          # equal power pan, no volume dip in the middle
    left, right = audio * np.cos(angle), audio * np.sin(angle)
    if width > 0 and n:
        # add a tiny delayed copy, opposite sign per side: feels bigger, stays centered
        d = int(sr * 0.011)
        side = np.zeros_like(audio)
        side[d:] = audio[:-d] if d < n else 0
        left, right = left + width * 0.5 * side, right - width * 0.5 * side
    out = np.stack([left, right], axis=1).astype(np.float32)
    peak = float(np.abs(out).max()) if n else 0
    return out * (0.99 / peak) if peak > 0.99 else out


def render_stereo(settings: dict, text: str, **place) -> tuple[np.ndarray, int]:
    """Like render, but returns stereo placed by the preset (or by pan/width/sweep you pass)."""
    s = {**DEFAULTS, **settings, **place}
    audio, sr = render(s, text)
    return spatialize(audio, sr, float(s["pan"]), float(s["width"]), float(s["sweep"])), sr


# ---------- playback ----------

def play(audio: np.ndarray, sr: int, wait: bool = True) -> None:
    import sounddevice as sd
    sd.play(audio, sr)
    if wait:
        sd.wait()


def stop() -> None:
    import sounddevice as sd
    sd.stop()


def save_wav(audio: np.ndarray, sr: int, path) -> None:
    data = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1 if data.ndim == 1 else data.shape[1])
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(data.tobytes())


# ---------- catalog ----------

def load_catalog() -> dict:
    if CATALOG_PATH.exists():
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {"presets": {}}


def _write_catalog(cat: dict) -> None:
    CATALOG_PATH.write_text(json.dumps(cat, indent=2), encoding="utf-8")


def get_preset(name: str) -> dict:
    presets = load_catalog()["presets"]
    if name not in presets:
        raise KeyError(f"No preset named '{name}'. Have: {', '.join(presets) or 'none'}")
    return {**DEFAULTS, **presets[name]["settings"]}


def save_preset(name: str, settings: dict, notes: str = "", tags=None) -> None:
    cat = load_catalog()
    old = cat["presets"].get(name, {})
    cat["presets"][name] = {
        "settings": {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS},
        "notes": notes,
        "tags": list(tags or []),
        "created": old.get("created", time.strftime("%Y-%m-%d")),
        "updated": time.strftime("%Y-%m-%d"),
    }
    _write_catalog(cat)


def delete_preset(name: str) -> None:
    cat = load_catalog()
    cat["presets"].pop(name, None)
    _write_catalog(cat)


def speak(preset: str, text: str, wait: bool = True, **place) -> None:
    """One line for robots: speak("stelly", "Hello!")

    Override placement per line: speak("stelly", "Over here!", pan=-0.8)
    """
    audio, sr = render_stereo(get_preset(preset), text, **place)
    play(audio, sr, wait=wait)
