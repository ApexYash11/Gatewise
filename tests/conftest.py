"""Shared test fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the packages importable without an editable install.
ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "packages",):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


class RecordingTransport:
    """A fake HTTP transport that records requests and replays a canned response.

    This stubs the *network boundary* only. No decision intelligence is simulated
    here: the tests assert on how Gatewise builds requests and how it handles the
    provider's real response shape.
    """

    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.requests: list = []

    async def handle_async_request(self, request):  # pragma: no cover - plumbing
        self.requests.append(request)
        import httpx2

        return httpx2.Response(
            status_code=self.status_code,
            json=self.payload,
            request=request,
        )


@pytest.fixture
def real_jev_payload() -> dict:
    """A response shaped exactly like the verified Jev contract."""
    return {
        "model": "jev-1.13.0",
        "answers": {
            "pr_category": {
                "type": "choice",
                "choice": "infrastructure",
                "confidence": 0.82,
                "probabilities": {
                    "bug": 0.01,
                    "feature": 0.05,
                    "refactor": 0.02,
                    "documentation": 0.0,
                    "test": 0.01,
                    "dependency": 0.04,
                    "security": 0.02,
                    "infrastructure": 0.82,
                    "other": 0.03,
                },
            },
            "pr_risk": {
                "type": "score",
                "score": 4.2,
                "confidence": 0.88,
                "legend": {
                    "0": "Trivial. No behavioural change; cosmetic, comment, or documentation only.",
                    "1": "Low. Contained, easily reverted, with an obvious blast radius.",
                    "2": "Moderate. Real behavioural change affecting known consumers.",
                    "3": "High. Changes behaviour across system boundaries with a wide blast radius.",
                    "4": "Critical. Affects data integrity, security, money, or core public API contracts.",
                },
                "probabilities": {"0": 0.0, "1": 0.0, "2": 0.02, "3": 0.1, "4": 0.88},
            },
            "pr_breaking_change": {"type": "noul", "noul": 0.07},
            "pr_additional_testing": {"type": "noul", "noul": 0.93},
            "pr_maintainer_review": {"type": "noul", "noul": 0.88},
            "pr_security_review": {"type": "noul", "noul": 0.18},
        },
        "usage": {"input_tokens": 5120, "output_tokens": 140},
    }
