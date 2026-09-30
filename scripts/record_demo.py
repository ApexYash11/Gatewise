"""Record a live walkthrough of the Gatewise dashboard.

    Start the server first:

        python scripts/serve.py

    Then record:

        .venv\\Scripts\\python scripts/record_demo.py

The recording drives the real application in a real browser: the filter chips
are clicked, a card is expanded to show its decision graph, and the review form
is submitted, so the panel at the end is whatever the live model returned.
Nothing in the page is scripted for the camera and no frame is composited
afterwards.

Playwright writes a WebM clip into ``demo/_recording/`` and ffmpeg converts it
to ``demo/gatewise-demo.mp4``. Console errors, page errors, and failed requests
are collected and printed at the end, and make the script exit non-zero, so a
broken take is reported rather than silently filed as a good one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ffmpeg import find_ffmpeg, find_ffprobe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
RECORDING = DEMO / "_recording"
BASE = "http://127.0.0.1:8000"
OUTPUT = DEMO / "gatewise-demo.mp4"

#: The pull request used for the review beat. A real repository answered by the
#: real model is the only honest thing to put on screen.
DEMO_REPOSITORY = "jaredpalmer/kev"
DEMO_NUMBER = "174"

#: 16:9, and identical to the recording size, so every encoded frame is a 1:1
#: copy of what the browser rendered rather than a scaled or cropped version.
VIEWPORT = {"width": 1440, "height": 810}


def scroll_to(page: Page, selector: str, *, steps: int = 16, gap: int = 45) -> None:
    """Wheel an element towards the middle of the viewport in small increments.

    ``scroll_into_view`` jumps, and a recording of a page teleporting between
    states is not a recording of the product. Wheeling keeps the movement on
    camera. When the element has no box yet -- it sits inside a collapsed card
    or a hidden panel -- there is nothing to aim at and the jump is the only
    option, so that case is handled rather than left to raise.
    """
    element = page.locator(selector).first
    box = element.bounding_box()
    if box is None:
        element.scroll_into_view_if_needed()
        return
    # The box is viewport-relative, so the scroll needed to centre it does not
    # depend on where the page currently is.
    delta = box["y"] - (VIEWPORT["height"] - box["height"]) / 2
    if abs(delta) < 4:
        return
    for _ in range(steps):
        page.mouse.wheel(0, delta / steps)
        page.wait_for_timeout(gap)


def main() -> int:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        print("ffmpeg was not found on PATH or in the winget package directory.")
        print("Install it with:  winget install --id Gyan.FFmpeg -e")
        return 1

    RECORDING.mkdir(parents=True, exist_ok=True)
    # A previous take would otherwise be picked up as this run's output.
    for stale in RECORDING.glob("*.webm"):
        stale.unlink()

    problems: list[str] = []
    recording: Path | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(RECORDING),
            # Deliberately equal to the viewport: a mismatch scales or crops the
            # frame, and the dashboard should be shown at the size it was laid
            # out for.
            record_video_size=VIEWPORT,
        )
        page = context.new_page()
        if page.video is None:
            print("Playwright did not start a recording.")
            return 1

        page.on(
            "console",
            lambda message: problems.append(f"console {message.type}: {message.text}")
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
        page.on(
            "requestfailed",
            lambda request: problems.append(
                f"requestfailed: {request.url} {request.failure}"
            ),
        )

        print("loading the dashboard")
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".card", timeout=15_000)
        page.mouse.move(VIEWPORT["width"] // 2, VIEWPORT["height"] // 2)
        page.wait_for_timeout(1800)

        print("filtering to needs attention")
        scroll_to(page, "#filters")
        page.wait_for_timeout(700)
        page.click('.chip[data-filter="attention"]')
        page.wait_for_timeout(1700)
        page.click('.chip[data-filter="all"]')
        page.wait_for_timeout(900)

        print("expanding a decision graph")
        page.click(".card")
        page.wait_for_selector(".card[aria-expanded='true'] .graph", timeout=10_000)
        page.wait_for_timeout(500)
        scroll_to(page, ".card[aria-expanded='true'] .graph")
        page.wait_for_timeout(2600)

        print(f"submitting a live review of {DEMO_REPOSITORY}#{DEMO_NUMBER}")
        scroll_to(page, "#review-form")
        page.wait_for_timeout(700)
        # Typed rather than filled so the field visibly receives the value. The
        # model call then takes seconds; the button reads "Reviewing…" for that
        # whole time and the wait is kept at full length on camera.
        page.locator("#repo").press_sequentially(DEMO_REPOSITORY, delay=65)
        page.locator("#prnum").press_sequentially(DEMO_NUMBER, delay=110)
        page.wait_for_timeout(700)
        page.click("#review-go")
        page.wait_for_selector(".review-out.is-ok, .review-out.is-bad", timeout=180_000)
        page.wait_for_timeout(1500)
        scroll_to(page, ".review-out")
        page.wait_for_timeout(2600)

        print("showing the run filed in the index")
        scroll_to(page, "#body")
        page.wait_for_timeout(2600)

        status = page.inner_text(".review-out .rv-head")
        print(f"  review panel says: {status.strip()}")

        # Captured before closing: the path is decided when recording starts,
        # but the file only exists once the context has flushed it.
        recording = Path(page.video.path())
        context.close()
        browser.close()

    if recording is None or not recording.exists():
        print("Playwright produced no recording.")
        return 1

    if problems:
        print("\nbrowser problems:")
        for problem in problems:
            print(f"  {problem}")
        print(f"\nraw clip kept for inspection: {recording}")

    print(f"converting to {OUTPUT.name}")
    result = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(recording),
            "-vf", "fps=30,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "20",
            "-movflags", "+faststart",
            str(OUTPUT),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("ffmpeg failed:")
        print(result.stderr.strip())
        return result.returncode

    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1_048_576:.2f} MiB)")

    ffprobe = find_ffprobe(ffmpeg)
    if ffprobe:
        probe = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-show_entries", "stream=width,height,codec_name",
                "-of", "default=noprint_wrappers=1",
                str(OUTPUT),
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            print("  " + "  ".join(probe.stdout.split()))

    if not problems:
        print("no console errors or failed requests")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
