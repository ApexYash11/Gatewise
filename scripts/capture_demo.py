"""Capture the dashboard for a demo, driving the real UI in a real browser.

Every frame is a genuine screenshot of the running application: the review form is
filled and submitted, the resulting panel is whatever the live model returned, and
the decision graph is expanded by an actual click. Nothing here is mocked or
composed, so if a frame looks right the product looks right.

Run with the server already listening:

    .venv\\Scripts\\python scripts\\capture_demo.py

Screenshots land in ``demo/``. Any console error or failed request is collected and
printed at the end, because a frame that renders "Could not reach the API" is
still a valid screenshot of a broken page and would otherwise be filed as a good
one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo"
BASE = "http://127.0.0.1:8000"

#: The pull request used for the demo. A bug fix in a real repository reads better
#: than a synthetic one, and a real answer is the only honest thing to show.
DEMO_REPOSITORY = "jaredpalmer/kev"
DEMO_NUMBER = "174"

VIEWPORT = {"width": 1440, "height": 900}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    problems: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

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

        def shoot(name: str, *, scroll_to: str | None = None) -> None:
            """Capture one frame at a fixed viewport size.

            Every frame is the same dimensions on purpose. Full-page screenshots
            vary in height with the length of the list, and the video encoder needs
            a constant canvas -- mixed sizes collapse the timeline and letterbox
            badly. Scrolling the subject into view keeps each frame readable at
            16:10 instead of shrinking a 5000px page to fit.
            """
            if scroll_to:
                page.locator(scroll_to).first.scroll_into_view_if_needed()
                page.wait_for_timeout(350)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
            print(f"  wrote {name}.png")

        print("capturing index")
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".card", timeout=15_000)
        shoot("01-index")

        print("capturing a filtered view")
        page.click('.chip[data-filter="attention"]')
        page.wait_for_timeout(400)
        shoot("02-filtered", scroll_to="#filters")
        page.click('.chip[data-filter="all"]')
        page.wait_for_timeout(300)

        print("capturing the expanded decision graph")
        page.click(".card")
        page.wait_for_selector(".card[aria-expanded='true'] .graph", timeout=10_000)
        page.wait_for_timeout(500)
        shoot("03-decision-graph", scroll_to=".card[aria-expanded='true'] .graph")

        print(f"submitting a live review of {DEMO_REPOSITORY}#{DEMO_NUMBER}")
        page.fill("#repo", DEMO_REPOSITORY)
        page.fill("#prnum", DEMO_NUMBER)
        page.click("#review-go")
        # A real model call takes seconds. Wait for the panel to leave its pending
        # state rather than sleeping a guessed interval, so the frame captures the
        # finished result and not a spinner.
        page.wait_for_selector(".review-out.is-ok, .review-out.is-bad", timeout=180_000)
        page.wait_for_timeout(800)
        shoot("04-review-result", scroll_to=".review-out")

        status = page.inner_text(".review-out .rv-head")
        print(f"  review panel says: {status.strip()}")

        browser.close()

    if problems:
        print("\nbrowser problems:")
        for problem in problems:
            print(f"  {problem}")
    else:
        print("\nno console errors or failed requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
