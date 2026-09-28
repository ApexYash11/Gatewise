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


async def test_insufficient_credits_is_reported_as_a_billing_problem():
    """402 is reachable-but-unfunded; it must not look like a code defect."""
    provider = make_provider(
        {"error": {"code": 402, "message": "Insufficient credits."}}, 402
    )
    with pytest.raises(DecisionUnavailable) as excinfo:
        await provider.evaluate({}, load_registry().build_request())
    message = str(excinfo.value)
    assert "credits" in message.lower()
    assert "openrouter.ai/settings/credits" in message


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


async def test_openrouter_response_shape_normalizes_identically():
    """OpenRouter serves the same model and adds id/provider/usage.cost.

    Those extra fields must not break normalization, and the reported cost must
    be captured rather than discarded.
    """
    openrouter_payload = {
        "id": "gen-dec-1789738314-X5e5eKGQdvR9rblyX250",
        "model": "typesafe/jev-1.13-20260917",
        "provider": "TypeSafe",
        "answers": {
            "pr_category": {
                "type": "choice",
                "choice": "infrastructure",
                "confidence": 0.82,
                "probabilities": {"infrastructure": 0.82, "bug": 0.18},
            },
            "pr_risk": {
                "type": "score",
                "score": 4.2,
                "confidence": 0.88,
                "legend": {"0": "Trivial", "1": "Low", "2": "Moderate", "3": "High", "4": "Critical"},
                "probabilities": {"0": 0, "1": 0, "2": 0.02, "3": 0.1, "4": 0.88},
            },
            "pr_breaking_change": {"type": "noul", "noul": 0.07},
        },
        "usage": {"input_tokens": 5120, "output_tokens": 140, "cost": 0.000215},
    }

    provider = make_provider(openrouter_payload)
    questions = {
        name: load_registry().get(name).question
        for name in ("pr_category", "pr_risk", "pr_breaking_change")
    }
    answers = await provider.evaluate({"pull_request": {"number": 1}}, questions)

    assert answers["pr_category"].choice == "infrastructure"
    assert answers["pr_risk"].score == pytest.approx(4.2)
    assert answers["pr_risk"].resolve_level() == 4
    assert answers["pr_breaking_change"].noul == pytest.approx(0.07)

    # Replay the response to confirm usage/cost extraction, using a stub so this
    # asserts our extraction logic rather than the SDK's own key coercion.
    from types import SimpleNamespace

    stub = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=5120, output_tokens=140, cost=0.000215)
    )
    usage = JevDecisionProvider.extract_usage(stub)
    assert usage.input_tokens == 5120
    assert usage.output_tokens == 140
    assert usage.cost == pytest.approx(0.000215)


def test_cost_is_none_when_provider_does_not_report_it():
    """TypeSafe's own endpoint reports no cost; it must not be invented."""
    from types import SimpleNamespace

    stub = SimpleNamespace(usage=SimpleNamespace(input_tokens=275, output_tokens=20))
    assert JevDecisionProvider.extract_usage(stub).cost is None


def test_usage_extraction_tolerates_a_missing_usage_object():
    from types import SimpleNamespace

    assert JevDecisionProvider.extract_usage(SimpleNamespace()).input_tokens is None


def test_provider_records_its_transport(real_jev_payload):
    provider = make_provider(real_jev_payload)
    assert provider.transport == "typesafe"
    assert provider.model == "jev-latest"


def test_official_jev_flag_distinguishes_local_compatible_servers(real_jev_payload):
    """A local Jev-compatible server must never be recorded as hosted Jev."""
    import typesafe_sdk

    local = JevDecisionProvider(
        "local",
        "kev-4b",
        base_url="http://127.0.0.1:8009",
        transport_name="local",
        client=typesafe_sdk.AsyncTypeSafeClient(
            api_key="local", base_url="http://127.0.0.1:8009"
        ),
    )
    assert local.is_official_jev is False
    assert local.transport == "local"

    # Both hosted paths are genuinely TypeSafe's model.
    assert make_provider(real_jev_payload).is_official_jev is True
    openrouter = JevDecisionProvider(
        "sk-or-test", transport_name="openrouter", client=typesafe_sdk.AsyncTypeSafeClient(
            api_key="sk-or-test", base_url="https://openrouter.ai/api"
        )
    )
    assert openrouter.is_official_jev is True


def test_provider_refuses_to_start_without_a_key():
    with pytest.raises(ValueError, match="API key is required"):
        JevDecisionProvider("")
