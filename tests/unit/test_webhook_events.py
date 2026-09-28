"""Tests for webhook payload parsing."""

from __future__ import annotations

import json

import pytest

from github.events import SUPPORTED_ACTIONS, WebhookParseError, parse_pull_request_event


def make_payload(**overrides) -> bytes:
    pull_request = {
        "number": 5215,
        "title": "Upgrade the ingress controller",
        "body": "Bumps NGINX ingress to 4.9.0",
        "user": {"login": "octocat"},
        "base": {"ref": "main"},
        "head": {"ref": "chore/ingress", "sha": "abc123"},
        "labels": [{"name": "dependencies"}, {"name": "infrastructure"}],
        "draft": False,
        "changed_files_list": [
            {"filename": "deploy/helm/values.yaml"},
            {"filename": "test/e2e/ingress_test.py"},
        ],
    }
    pull_request.update(overrides.pop("pull_request", {}))
    payload = {
        "action": overrides.pop("action", "opened"),
        "repository": {"full_name": "octo/repo"},
        "pull_request": pull_request,
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_parses_a_valid_pull_request_event():
    event = parse_pull_request_event(make_payload(), event="pull_request")

    assert event.action == "opened"
    assert event.repository == "octo/repo"
    assert event.number == 5215
    assert event.title == "Upgrade the ingress controller"
    assert event.description == "Bumps NGINX ingress to 4.9.0"
    assert event.author == "octocat"
    assert event.base_branch == "main"
    assert event.head_branch == "chore/ingress"
    assert event.head_sha == "abc123"
    assert event.labels == ("dependencies", "infrastructure")
    assert event.changed_files == ("deploy/helm/values.yaml", "test/e2e/ingress_test.py")
    assert event.draft is False


@pytest.mark.parametrize("action", sorted(SUPPORTED_ACTIONS))
def test_all_supported_actions_are_accepted(action):
    event = parse_pull_request_event(
        make_payload(action=action), event="pull_request"
    )
    assert event.action == action


def test_unsupported_pr_action_is_skipped_not_accepted():
    with pytest.raises(WebhookParseError, match="unsupported pull_request action"):
        parse_pull_request_event(make_payload(action="closed"), event="pull_request")


def test_other_event_types_are_skipped():
    """GitHub sends many event types; only pull_request is handled."""
    for event_type in ("push", "issues", "ping"):
        with pytest.raises(WebhookParseError, match="unsupported event type"):
            parse_pull_request_event(make_payload(), event=event_type)


def test_invalid_json_is_rejected():
    with pytest.raises(WebhookParseError, match="not valid JSON"):
        parse_pull_request_event(b"{not json", event="pull_request")


def test_non_object_payload_is_rejected():
    with pytest.raises(WebhookParseError, match="must be a JSON object"):
        parse_pull_request_event(b"[1,2,3]", event="pull_request")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (json.dumps({"action": "opened"}).encode(), "no pull_request"),
        (
            json.dumps(
                {"action": "opened", "pull_request": {"number": 1}}
            ).encode(),
            "no repository",
        ),
        (
            json.dumps(
                {
                    "action": "opened",
                    "pull_request": {"title": "x"},
                    "repository": {"full_name": "o/r"},
                }
            ).encode(),
            "numeric number",
        ),
        (
            json.dumps(
                {
                    "action": "opened",
                    "pull_request": {"number": 1},
                    "repository": {},
                }
            ).encode(),
            "full_name",
        ),
    ],
)
def test_missing_required_fields_are_rejected(payload, message):
    with pytest.raises(WebhookParseError, match=message):
        parse_pull_request_event(payload, event="pull_request")


def test_oversized_payload_is_rejected():
    from github.events import MAX_PAYLOAD_BYTES

    with pytest.raises(WebhookParseError, match="too large"):
        parse_pull_request_event(b"x" * (MAX_PAYLOAD_BYTES + 1), event="pull_request")


def test_missing_optional_fields_degrade_gracefully():
    """A minimal payload must still parse rather than crash the pipeline."""
    payload = json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "octo/repo"},
            "pull_request": {"number": 1, "title": "Minimal"},
        }
    ).encode("utf-8")

    event = parse_pull_request_event(payload, event="pull_request")
    assert event.title == "Minimal"
    assert event.description is None
    assert event.author == "unknown"
    assert event.labels == ()
    assert event.changed_files == ()
    assert event.draft is False


def test_empty_description_is_none_not_empty_string():
    payload = json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "octo/repo"},
            "pull_request": {"number": 1, "title": "T", "body": ""},
        }
    ).encode("utf-8")
    assert parse_pull_request_event(payload, event="pull_request").description is None
