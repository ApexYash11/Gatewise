"""End-to-end test: PR context -> Jev provider -> validated, inspectable decisions.

The HTTP transport is stubbed; everything else is the real code path. This proves
the wiring works, and that a provider failure propagates as ``DecisionUnavailable``
rather than being converted into a safe-looking default.
"""

from __future__ import annotations

import pytest
import typesafe_sdk

from context import build_context
from decisions.jev import JevDecisionProvider
from decisions.provider import DecisionUnavailable, DecisionValidationError
from decisions.registry import load_registry
from decisions.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer

from conftest import RecordingTransport


def build_context_for_demo():
    return build_context(
        number=5215,
        title="Upgrade the ingress controller",
        description=(
            "Bumps the NGINX ingress controller from 4.4.0 to 4.9.0 and adjusts the "
            "default timeouts. Changes behaviour for every route in the cluster."
        ),
        author="octocat",
        base_branch="main",
        head_branch="chore/ingress-upgrade",
        labels=["dependencies", "infrastructure"],
        changed_files=[
            "deploy/helm/values.yaml",
            "deploy/helm/templates/ingress.yaml",
            "test/e2e/ingress_test.py",
        ],
        diff="--- a/values.yaml\n+++ b/values.yaml\n- timeout: 30\n+ timeout: 60\n",
        commit_subjects=["Bump ingress controller to 4.9.0"],
    )


def make_provider(payload, status_code=200):
    transport = RecordingTransport(payload, status_code)
    client = typesafe_sdk.AsyncTypeSafeClient(
        api_key="test-key-not-a-real-credential", transport=transport
    )
    provider = JevDecisionProvider("test-key-not-a-real-credential", client=client)
    provider._transport = transport
    return provider


async def test_end_to_end_evaluation(real_jev_payload):
    ctx = build_context_for_demo()
    registry = load_registry()
    provider = make_provider(real_jev_payload)

    answers = await provider.evaluate(ctx.state, registry.build_request())

    # Six typed decisions came back, one per registered question.
    assert len(answers) == 6
    assert isinstance(answers["pr_category"], ChoiceAnswer)
    assert isinstance(answers["pr_risk"], ScoreAnswer)
    assert answers["pr_category"].choice == "infrastructure"
    assert answers["pr_risk"].score == pytest.approx(4.2)
    assert answers["pr_risk"].resolve_level() == 4
    assert answers["pr_security_review"].noul == pytest.approx(0.18)

    # The exact context we built is what reached the provider.
    sent = provider._transport.requests[0]
    assert b"5215" in sent.content


async def test_context_and_questions_travel_in_one_request(real_jev_payload):
    """Context and all compatible questions are sent together, as the API allows."""
    ctx = build_context_for_demo()
    provider = make_provider(real_jev_payload)

    await provider.evaluate(ctx.state, load_registry().build_request())

    import json

    body = json.loads(provider._transport.requests[0].content)
    assert len(body["questions"]) == 6
    assert body["state"]["untrusted_content"]["title"] == "Upgrade the ingress controller"
    assert body["state"]["pull_request"]["files_changed_count"] == 3


async def test_provider_outage_fails_closed_without_inventing_a_decision():
    """A failed decision must never become risk=0 or safe=true."""
    ctx = build_context_for_demo()
    provider = make_provider({"error": "service unavailable"}, 500)

    with pytest.raises(DecisionUnavailable):
        await provider.evaluate(ctx.state, load_registry().build_request())


async def test_malformed_provider_output_fails_closed():
    ctx = build_context_for_demo()
    provider = make_provider({"model": "jev-1.13.0", "answers": {}})

    with pytest.raises(DecisionValidationError):
        await provider.evaluate(ctx.state, load_registry().build_request())


async def test_authentication_failure_is_reported_clearly():
    ctx = build_context_for_demo()
    provider = make_provider({"error": "invalid api key"}, 401)

    with pytest.raises(DecisionUnavailable, match="TYPESAFE_API_KEY"):
        await provider.evaluate(ctx.state, load_registry().build_request())
