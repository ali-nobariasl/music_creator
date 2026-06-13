"""Command-line entry point for the focus-audio generator.

Generation logic lives in audio_engine.py (shared with the GUI control panel,
control_panel.py). Edit the defaults below or use the GUI to tweak settings.
"""

import os

from audio_engine import Params, generate


def main():
    p = Params()  # tweak fields here, or run control_panel.py for a GUI

    print(f"Generating {p.duration_hours:g}h focus audio  "
          f"({p.beat_freq} Hz binaural · {p.bpm} BPM · {p.carrier_freq} Hz carrier)")

    def progress(done, total):
        pct = int(done / total * 100)
        print(f"  {pct}%  ({done // 60} / {total // 60} min)", end='\r')

    path = generate(p, progress=progress)

    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"\nDone!  →  {path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
