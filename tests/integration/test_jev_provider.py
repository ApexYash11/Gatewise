"""Unit tests for the Jev provider.

These exercise real request construction against the verified Jev contract and
real failure handling. The HTTP transport is stubbed; model intelligence is not
simulated anywhere.
"""

from __future__ import annotations

import json

import pytest
import typesafe_sdk

from decisions.jev import JevDecisionProvider
from decisions.provider import DecisionUnavailable, DecisionValidationError
from decisions.registry import load_registry
from decisions.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer

from conftest import RecordingTransport


def make_provider(payload: dict, status_code: int = 200) -> JevDecisionProvider:
    transport = RecordingTransport(payload, status_code)
    client = typesafe_sdk.AsyncTypeSafeClient(
        api_key="test-key-not-a-real-credential",
        transport=transport,
    )
    provider = JevDecisionProvider("test-key-not-a-real-credential", client=client)
    provider._transport = transport  # type: ignore[attr-defined]
    return provider


async def test_evaluate_returns_validated_typed_answers(real_jev_payload):
    provider = make_provider(real_jev_payload)
    registry = load_registry()

    answers = await provider.evaluate({"pull_request": {"number": 1}}, registry.build_request())

    assert set(answers) == {
        "pr_category",
        "pr_risk",
        "pr_breaking_change",
        "pr_additional_testing",
        "pr_maintainer_review",
        "pr_security_review",
    }
    assert isinstance(answers["pr_category"], ChoiceAnswer)
    assert isinstance(answers["pr_risk"], ScoreAnswer)
    assert isinstance(answers["pr_security_review"], NoulAnswer)


async def test_request_matches_the_verified_jev_contract(real_jev_payload):
    provider = make_provider(real_jev_payload)
    registry = load_registry()
    state = {"pull_request": {"number": 42}, "untrusted_content": {"title": "x"}}

    await provider.evaluate(state, registry.build_request())

    request = provider._transport.requests[0]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert str(request.url).endswith("/v1/systemone")
    assert "Authorization" in request.headers
    assert set(body) == {"state", "questions", "model"}
    assert body["state"] == state
    # All six questions are batched into a single call.
    assert len(body["questions"]) == 6
    assert body["questions"]["pr_category"]["criteria"]["infrastructure"]
    assert isinstance(body["questions"]["pr_risk"]["criteria"], list)
    assert body["questions"]["pr_security_review"]["type"] == "noul"


async def test_score_answer_keeps_expected_value_and_resolves_level(real_jev_payload):
    provider = make_provider(real_jev_payload)
    registry = load_registry()

    answers = await provider.evaluate({}, registry.build_request())
    risk = answers["pr_risk"]

    assert isinstance(risk, ScoreAnswer)
    # The real model returns an interpolated expected score...
    assert risk.score == pytest.approx(4.2)
    # ...and we additionally expose a discrete level for policy routing.
    assert risk.resolve_level() == 4
    assert risk.level_label().startswith("Critical")


async def test_noul_answers_carry_no_invented_confidence(real_jev_payload):
    provider = make_provider(real_jev_payload)
    registry = load_registry()

    answers = await provider.evaluate({}, registry.build_request())
    noul = answers["pr_breaking_change"]

    assert isinstance(noul, NoulAnswer)
    assert noul.noul == pytest.approx(0.07)
    assert not hasattr(noul, "confidence"), "Jev has no confidence field for nouls"


@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (401, {"error": "unauthorized"}, DecisionUnavailable),
        (429, {"error": "rate limited"}, DecisionUnavailable),
        (500, {"error": "boom"}, DecisionUnavailable),
    ],
)
async def test_provider_failures_surface_as_decision_unavailable(
    status_code, payload, expected
):
    """A failed decision must never be converted into a safe-looking default."""
    provider = make_provider(payload, status_code)
    registry = load_registry()

    with pytest.raises(expected):
        await provider.evaluate({}, registry.build_request())


async def test_malformed_response_raises_validation_error():
    provider = make_provider({"model": "jev-1.13.0"})  # no 'answers' at all
    registry = load_registry()

    with pytest.raises(DecisionValidationError):
        await provider.evaluate({}, registry.build_request())


async def test_missing_answer_is_never_defaulted(real_jev_payload):
    del real_jev_payload["answers"]["pr_security_review"]
    provider = make_provider(real_jev_payload)
    registry = load_registry()

    with pytest.raises(DecisionValidationError) as excinfo:
        await provider.evaluate({}, registry.build_request())
    assert "pr_security_review" in str(excinfo.value)


async def test_evaluate_requires_at_least_one_question(real_jev_payload):
    provider = make_provider(real_jev_payload)
    with pytest.raises(DecisionValidationError):
        await provider.evaluate({}, {})


def test_provider_refuses_to_start_without_a_key():
    with pytest.raises(ValueError, match="API key is required"):
        JevDecisionProvider("")
