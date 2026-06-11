
import numpy as np
from scipy.io import wavfile
import subprocess
import wave
import os


CARRIER_FREQ   = 216.0    # Hz — base tone sent to both ears
BEAT_FREQ      = 8.0      # Hz — binaural beat (alpha = 8–13 Hz, beta = 14–30 Hz)
BPM            = 98       # rhythm pulse tempo
BINAURAL_VOL   = 0.45     # 0.0 – 1.0
RHYTHM_VOL     = 0.45     # 0.0 – 1.0
DURATION_HOURS = 3        # total duration in hours
OUTPUT_FILE    = "focus_adhd.mp3"

SAMPLE_RATE    = 44100
CHUNK_SECONDS  = 300      # process in 5-min chunks to keep RAM low
DURATION       = DURATION_HOURS * 3600
BEAT_INTERVAL  = int(SAMPLE_RATE * 60 / BPM)
BEAT_DUR       = int(SAMPLE_RATE * 0.08)   # 80 ms pulse length
TMP_WAV        = "focus_tmp.wav"


def generate_chunk(t_start, t_end):
    """Generate one stereo chunk as int16 PCM bytes."""
    n = (t_end - t_start) * SAMPLE_RATE
    t = np.linspace(t_start, t_end, n, endpoint=False)

    # Binaural: left ear gets CARRIER, right ear gets CARRIER + BEAT_FREQ
    left  = np.sin(2 * np.pi * CARRIER_FREQ * t).astype(np.float32)
    right = np.sin(2 * np.pi * (CARRIER_FREQ + BEAT_FREQ) * t).astype(np.float32)

    # Rhythm pulses — soft 80 Hz bass tone shaped by a sine envelope
    rhythm = np.zeros(n, dtype=np.float32)
    for beat_pos in range(0, DURATION * SAMPLE_RATE, BEAT_INTERVAL):
        local = beat_pos - t_start * SAMPLE_RATE
        if 0 <= local < n:
            end = min(local + BEAT_DUR, n)
            length = end - local
            envelope = np.sin(np.linspace(0, np.pi, length))
            tone     = np.sin(2 * np.pi * 80 * np.linspace(0, length / SAMPLE_RATE, length))
            rhythm[local:end] += (envelope * tone).astype(np.float32)

    # Mix layers and clip
    left  = np.clip(left  * BINAURAL_VOL + rhythm * RHYTHM_VOL, -1, 1)
    right = np.clip(right * BINAURAL_VOL + rhythm * RHYTHM_VOL, -1, 1)

    # Interleave into stereo and convert to 16-bit PCM
    stereo = np.empty(n * 2, dtype=np.float32)
    stereo[0::2] = left
    stereo[1::2] = right
    return (stereo * 32767).astype(np.int16).tobytes()


def main():
    print(f"Generating {DURATION_HOURS}h focus audio  "
          f"({BEAT_FREQ} Hz binaural · {BPM} BPM · {CARRIER_FREQ} Hz carrier)")

    # Write to a temporary WAV in chunks
    with wave.open(TMP_WAV, 'w') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)

        for chunk_idx in range(0, DURATION, CHUNK_SECONDS):
            t_start = chunk_idx
            t_end   = min(t_start + CHUNK_SECONDS, DURATION)
            wf.writeframes(generate_chunk(t_start, t_end))
            pct = int(t_end / DURATION * 100)
            print(f"  {pct}%  ({t_end // 60} / {DURATION // 60} min)", end='\r')

    print("\nConverting WAV → MP3 with ffmpeg...")
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i",        TMP_WAV,
        "-codec:a",  "libmp3lame",
        "-b:a",      "128k",
        OUTPUT_FILE
    ], capture_output=True, text=True)

    os.remove(TMP_WAV)

    if result.returncode != 0:
        print("ffmpeg error:\n", result.stderr)
    else:
        size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
        print(f"Done!  →  {OUTPUT_FILE}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()