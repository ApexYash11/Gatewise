"""Tests for delivery deduplication and deterministic action identity."""

from __future__ import annotations

import pytest

from gatewise.github.dedup import (
    DeliveryDeduplicator,
    _legacy_action_fingerprint,
    action_fingerprint,
)


def test_first_delivery_is_not_a_duplicate():
    dedup = DeliveryDeduplicator()
    assert dedup.is_duplicate("delivery-1") is False


def test_redelivery_is_rejected():
    """GitHub retries deliveries; a repeat must not trigger repeat work."""
    dedup = DeliveryDeduplicator()
    assert dedup.is_duplicate("delivery-1") is False
    assert dedup.is_duplicate("delivery-1") is True
    assert dedup.is_duplicate("delivery-1") is True


def test_different_deliveries_are_independent():
    dedup = DeliveryDeduplicator()
    assert dedup.is_duplicate("delivery-1") is False
    assert dedup.is_duplicate("delivery-2") is False


def test_missing_delivery_id_is_not_treated_as_duplicate():
    """Absence of an ID is the endpoint's problem, not 'already seen'."""
    dedup = DeliveryDeduplicator()
    assert dedup.is_duplicate(None) is False
    assert dedup.is_duplicate("") is False
    assert dedup.is_duplicate(None) is False


def test_dedup_memory_is_bounded():
    """An unbounded set would grow forever in a long-running process."""
    dedup = DeliveryDeduplicator(max_entries=10)
    for index in range(100):
        dedup.is_duplicate(f"delivery-{index}")
    assert dedup.seen_count() <= 10


def test_most_recent_deliveries_survive_eviction():
    dedup = DeliveryDeduplicator(max_entries=5)
    for index in range(50):
        dedup.is_duplicate(f"delivery-{index}")
    # The newest is still remembered, so an immediate retry is caught.
    assert dedup.is_duplicate("delivery-49") is True


def test_clear_resets_state():
    dedup = DeliveryDeduplicator()
    dedup.is_duplicate("delivery-1")
    dedup.clear()
    assert dedup.is_duplicate("delivery-1") is False


def test_invalid_capacity_is_rejected():
    with pytest.raises(ValueError):
        DeliveryDeduplicator(max_entries=0)


def test_action_fingerprint_is_deterministic():
    """Same decision run must always yield the same identity."""
    kwargs = dict(
        repository="octo/repo",
        pull_request_number=42,
        action_type="request_review",
        decision_run_id="run-abc",
    )
    assert action_fingerprint(**kwargs) == action_fingerprint(**kwargs)


def test_legacy_action_fingerprint_preserves_the_pre_12_encoding():
    assert (
        _legacy_action_fingerprint(
            repository="octo/repo",
            pull_request_number=42,
            action_type="add_label",
            decision_run_id="run-state-hash",
        )
        == "929d496cf4b2f2b7832ae186f9e074eb"
    )


def test_action_fingerprint_differs_by_action_type():
    base = dict(repository="octo/repo", pull_request_number=42, decision_run_id="run-abc")
    assert action_fingerprint(**base, action_type="add_label") != action_fingerprint(
        **base, action_type="request_review"
    )


def test_action_fingerprint_differs_by_pull_request():
    base = dict(repository="octo/repo", action_type="add_label", decision_run_id="run-abc")
    assert action_fingerprint(**base, pull_request_number=1) != action_fingerprint(
        **base, pull_request_number=2
    )


def test_action_fingerprint_differs_by_decision_run():
    """A genuinely new decision run is new work, not a duplicate."""
    base = dict(repository="octo/repo", pull_request_number=42, action_type="add_label")
    assert action_fingerprint(**base, decision_run_id="run-1") != action_fingerprint(
        **base, decision_run_id="run-2"
    )


def test_action_fingerprint_differs_by_target():
    """Two labels on the same run are two actions, never one."""
    base = dict(
        repository="octo/repo", pull_request_number=42, decision_run_id="run-abc"
    )
    assert action_fingerprint(**base, action_type="add_label", target="risk:high") != (
        action_fingerprint(**base, action_type="add_label", target="security:review")
    )



def test_action_fingerprint_differs_by_head_commit():
    """New code is new content: identity must move with the head SHA."""
    base = dict(
        repository="octo/repo",
        pull_request_number=42,
        action_type="trigger_workflow",
        target="extended-ci",
        decision_run_id="run-abc",
    )
    assert action_fingerprint(**base, head_sha="sha-1") != action_fingerprint(
        **base, head_sha="sha-2"
    )
    assert action_fingerprint(**base, head_sha="sha-1") == action_fingerprint(
        **base, head_sha="sha-1"
    )
