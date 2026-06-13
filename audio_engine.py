"""Core focus-audio generation engine.

Shared by the CLI (main.py) and the GUI control panel (control_panel.py).
Generates a binaural-beat + rhythm-pulse track and (optionally) encodes it
to MP3 with ffmpeg. Designed to be driven from a background thread:
pass a `progress` callback and a `should_cancel` predicate.
"""

import os
import wave
import shutil
import tempfile
import subprocess
from dataclasses import dataclass, asdict, fields

import numpy as np


SAMPLE_RATE = 44100
CHUNK_SECONDS = 300   # render in 5-min chunks to keep RAM low
PULSE_HZ = 80         # bass tone used for the rhythm pulse
PULSE_LEN = 0.08      # 80 ms pulse length


@dataclass
class Params:
    """All user-tunable generation parameters."""
    carrier_freq: float = 216.0    # Hz — base tone sent to both ears
    beat_freq: float = 8.0         # Hz — binaural beat (alpha 8-13, beta 14-30)
    bpm: int = 98                  # rhythm pulse tempo
    binaural_vol: float = 0.45     # 0.0 - 1.0
    rhythm_vol: float = 0.45       # 0.0 - 1.0
    duration_hours: float = 3.0    # total duration in hours
    output_file: str = "focus_adhd.mp3"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})


def _generate_chunk(p, beat_interval, beat_dur, sample_rate, t_start, t_end):
    """Generate one stereo chunk [t_start, t_end) as int16 PCM bytes."""
    n = (t_end - t_start) * sample_rate
    t = np.linspace(t_start, t_end, n, endpoint=False)

    # Binaural: left ear gets the carrier, right ear gets carrier + beat.
    left = np.sin(2 * np.pi * p.carrier_freq * t).astype(np.float32)
    right = np.sin(2 * np.pi * (p.carrier_freq + p.beat_freq) * t).astype(np.float32)

    # Rhythm pulses — soft bass tone shaped by a sine envelope. Only scan the
    # beats that actually fall inside this chunk (cheap even for long tracks).
    rhythm = np.zeros(n, dtype=np.float32)
    start_sample = t_start * sample_rate
    end_sample = t_end * sample_rate
    first_beat = (start_sample // beat_interval) * beat_interval
    for beat_pos in range(first_beat, end_sample, beat_interval):
        local = beat_pos - start_sample
        if 0 <= local < n:
            end = min(local + beat_dur, n)
            length = end - local
            envelope = np.sin(np.linspace(0, np.pi, length))
            tone = np.sin(2 * np.pi * PULSE_HZ * np.linspace(0, length / sample_rate, length))
            rhythm[local:end] += (envelope * tone).astype(np.float32)

    # Mix layers and clip to [-1, 1].
    left = np.clip(left * p.binaural_vol + rhythm * p.rhythm_vol, -1, 1)
    right = np.clip(right * p.binaural_vol + rhythm * p.rhythm_vol, -1, 1)

    # Interleave into stereo and convert to 16-bit PCM.
    stereo = np.empty(n * 2, dtype=np.float32)
    stereo[0::2] = left
    stereo[1::2] = right
    return (stereo * 32767).astype(np.int16).tobytes()


def _render_wav(params, total_seconds, wav_path, sample_rate=SAMPLE_RATE,
                chunk_seconds=CHUNK_SECONDS, progress=None, should_cancel=None):
    """Render `total_seconds` of audio into a stereo WAV file.

    `progress(seconds_done, total_seconds)` is called after each chunk.
    `should_cancel()` is polled between chunks; returns False if cancelled.
    """
    beat_interval = max(1, int(sample_rate * 60 / params.bpm))
    beat_dur = int(sample_rate * PULSE_LEN)

    with wave.open(wav_path, 'w') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        for chunk_start in range(0, total_seconds, chunk_seconds):
            if should_cancel and should_cancel():
                return False
            chunk_end = min(chunk_start + chunk_seconds, total_seconds)
            wf.writeframes(_generate_chunk(
                params, beat_interval, beat_dur, sample_rate, chunk_start, chunk_end))
            if progress:
                progress(chunk_end, total_seconds)
    return True


def _to_mp3(wav_path, output_file, bitrate="128k"):
    """Encode a WAV file to MP3 with ffmpeg. Raises on failure."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path,
         "-codec:a", "libmp3lame", "-b:a", bitrate, output_file],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")


def generate(params, progress=None, should_cancel=None):
    """Render the full track to `params.output_file`.

    Returns the output path on success, or None if cancelled.
    A `.wav` output is written directly; anything else is encoded via ffmpeg.
    """
    total = max(1, int(round(params.duration_hours * 3600)))
    tmp = os.path.join(tempfile.gettempdir(), f"focus_tmp_{os.getpid()}.wav")
    try:
        ok = _render_wav(params, total, tmp,
                         progress=progress, should_cancel=should_cancel)
        if not ok:
            return None

        out = params.output_file
        if out.lower().endswith(".wav"):
            shutil.move(tmp, out)
            tmp = None  # moved; nothing left to clean up
        else:
            _to_mp3(tmp, out)
        return out
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def render_preview(params, seconds=10):
    """Render a short WAV preview of the current settings. Returns its path."""
    wav = os.path.join(tempfile.gettempdir(), f"focus_preview_{os.getpid()}.wav")
    _render_wav(params, max(1, int(seconds)), wav)
    return wav
