"""Encode the captured demo frames into a video.

    .venv\\Scripts\\python scripts\\make_demo_video.py

Requires ffmpeg. It is looked up on PATH first and then in the winget package
directory, because a winget install does not always put it on PATH; if it is
genuinely missing the script says so and exits without touching the
screenshots, rather than producing a half-written file.

The frames are still images of a live UI. Each gets a restrained digital push,
with frame order and durations declared in FRAMES below.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ffmpeg import find_ffmpeg  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
OUTPUT = DEMO / "gatewise-demo.mp4"

#: (frame file, seconds on screen). Keep the film under twelve seconds: each scene
#: gets enough time to read, without making people wait through a slideshow.
FRAMES: list[tuple[str, float]] = [
    ("01-index.png", 3.0),
    ("02-filtered.png", 1.8),
    ("03-decision-graph.png", 3.2),
    ("04-review-result.png", 3.4),
]
FPS = 30
WIDTH, HEIGHT = 1440, 810


def main() -> int:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        print("ffmpeg was not found on PATH or in the winget package directory.")
        print("Install it with:  winget install --id Gyan.FFmpeg -e")
        return 1

    missing = [name for name, _ in FRAMES if not (DEMO / name).exists()]
    if missing:
        print(f"missing frames: {', '.join(missing)}")
        print("Run scripts/capture_demo.py first.")
        return 1

    command: list[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    filters: list[str] = []
    labels: list[str] = []
    for index, (name, seconds) in enumerate(FRAMES):
        # A still image contributes one input frame; zoompan turns it into the
        # requested number of output frames at the chosen frame rate.
        command.extend(["-i", str(DEMO / name)])
        label = f"v{index}"
        filters.append(
            f"[{index}:v]scale={WIDTH}:900:flags=lanczos,"
            f"crop={WIDTH}:{HEIGHT}:0:45,"
            f"zoompan=z='min(zoom+0.001,1.12)':"
            f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
            f"d={round(seconds * FPS)}:s={WIDTH}x{HEIGHT}:fps={FPS},"
            f"trim=duration={seconds},setpts=PTS-STARTPTS,format=yuv420p[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(FRAMES)}:v=1:a=0[out]")
    total = sum(seconds for _, seconds in FRAMES)
    command += [
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-movflags", "+faststart",
        str(OUTPUT),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg failed:")
        print(result.stderr.strip())
        return result.returncode

    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1_048_576:.1f} MiB)")
    print(f"duration {sum(d for _, d in FRAMES):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
