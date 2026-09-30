"""Locate ffmpeg for the demo tooling.

ffmpeg on this machine was installed by winget, which does not always add its
``bin`` directory to PATH, so ``shutil.which("ffmpeg")`` reports the tool as
missing even though it is installed. Both demo scripts need it, so the search
lives here rather than being copied into each one.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: winget unpacks each package into its own directory under here.
WINGET_PACKAGES = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"


def find_ffmpeg() -> str | None:
    """Absolute path to ffmpeg, or None when it genuinely is not installed."""
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    if not WINGET_PACKAGES.is_dir():
        return None
    candidates = list(WINGET_PACKAGES.glob("*/**/ffmpeg.exe"))
    # The binary lives in <package>/<version>/bin/; prefer it over any copy
    # shipped elsewhere in a package, then fall back to whatever exists.
    in_bin = [c for c in candidates if c.parent.name == "bin"]
    chosen = (in_bin or candidates)[:1]
    return str(chosen[0]) if chosen else None


def find_ffprobe(ffmpeg: str) -> str | None:
    """ffprobe next to ``ffmpeg``, which the winget build ships alongside it."""
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    sibling = Path(ffmpeg).with_name(name)
    return str(sibling) if sibling.is_file() else shutil.which("ffprobe")
