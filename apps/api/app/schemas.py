"""Request and response models for the HTTP API.

Deliberately thin: these describe the wire format only. Decision logic lives in
:mod:`apps.api.app.service` and the decision layer, so that the same behaviour is
available whether it is reached over HTTP or from a script.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from actions.pipeline import DecisionPipeline
from audit import AuditStore, create_engine, create_schema, session_scope
from config import Settings
from decisions.jev import JevDecisionProvider
from decisions.registry import QuestionRegistry, load_registry
from github import DeliveryDeduplicator

from .service import GatewiseService, WebhookOutcome

__all__ = ["create_app"]


class PullRequestSummary(BaseModel):
    id: int
    repository_id: int
    #: ``owner/name``, so the dashboard can show which repository a verdict came
    #: from without a second request per entry.
    repository: str = ""
    number: int
    title: str
    author: str
    status: str
    head_sha: str | None = None


class DecisionView(BaseModel):
    """One stored decision, including its question version.

    The version is not decoration: without it a stored answer cannot be compared
    with a later one, because the rubric may have changed in between.
    """

    run_id: int
    question_name: str
    question_version: int
    question_type: str
    answer: str
    confidence: float | None = None
    level: int | None = None


class RunView(BaseModel):
    id: int
    provider: str
    model: str
    is_official_jev: bool
    status: str
    error: str | None = None
    latency_ms: int
    question_versions: list[str] = Field(default_factory=list)
    injection_flags: list[str] = Field(default_factory=list)


class HealthView(BaseModel):
    status: str
    decision_provider: str
    model: str
    transport: str
    credentials_configured: bool
    webhook_configured: bool


class WebhookAccepted(BaseModel):
    status: str
    detail: str
    run_id: int | None = None
    injection_flags: list[str] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)


class EvaluateRequest(BaseModel):
    """Body for the internal evaluation endpoint."""

    title: str
    description: str | None = None
    author: str = "unknown"
    number: int = 0
    base_branch: str = "main"
    head_branch: str = "feature"
    labels: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
