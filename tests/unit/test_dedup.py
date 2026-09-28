"""Tests for delivery deduplication and deterministic action identity."""

from __future__ import annotations

import pytest

from github.dedup import DeliveryDeduplicator, action_fingerprint


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
