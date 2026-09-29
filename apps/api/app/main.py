"""FastAPI application exposing the decision pipeline.

Endpoints follow the specification:

    POST /webhooks/github
    GET  /api/pull-requests
    GET  /api/pull-requests/{id}
    GET  /api/pull-requests/{id}/decisions
    GET  /api/decisions
    GET  /api/health
    POST /internal/decisions/evaluate

The webhook endpoint verifies the signature before doing anything else.

The health endpoint reports only whether the decision layer is *configured*, never
whether it is reachable. A health check that called the model on every request
would be slow, would leak credential validity through response timing, and would
turn a provider outage into a monitoring storm.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from actions.pipeline import DecisionPipeline
from audit import AuditStore, create_engine, create_schema, session_scope
from config import Settings
from context import build_context
from decisions.jev import JevDecisionProvider
from decisions.registry import load_registry
from github import DeliveryDeduplicator, parse_pull_request_event

from .schemas import (
    DecisionView,
    EvaluateRequest,
    HealthView,
    PullRequestSummary,
    RunView,
    WebhookAccepted,
)
from .service import GatewiseService

__all__ = ["create_app", "app"]

#: Dashboard assets, served from the same origin as the API.
STATIC_DIR = Path(__file__).resolve().parent / "static"



class AppState:
    """Process-wide dependencies, built once at startup."""

    def __init__(self) -> None:
        self.settings = Settings()
        self.engine = create_engine(self.settings.database_url)
        self.registry = load_registry()
        self.dedup = DeliveryDeduplicator()
        self._provider: JevDecisionProvider | None = None

    @property
    def provider(self) -> JevDecisionProvider | None:
        """The provider, or ``None`` when no credential is configured.

        Returning ``None`` rather than raising lets the API start and report its
        own unconfigured state through ``/api/health``, instead of crash-looping
        in an orchestrator that has not injected secrets yet.
        """
        if not self.settings.has_jev_key:
            return None
        if self._provider is None:
            api_key, base_url = self.settings.jev_credentials()
            self._provider = JevDecisionProvider(
                api_key,
                self.settings.jev_model,
                base_url=base_url,
                transport_name=self.settings.jev_transport,
            )
        return self._provider

    def service(self, session: AsyncSession) -> GatewiseService:
        provider = self.provider
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail="decision provider is not configured; set TYPESAFE_API_KEY or OPENROUTER_API_KEY",
            )
        return GatewiseService(
            DecisionPipeline(
                provider, self.registry, is_official_jev=provider.is_official_jev
            ),
            AuditStore(session),
            self.dedup,
        )



def create_app() -> FastAPI:
    """Build the application. Tests call this with overridden settings."""
    state = AppState()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await create_schema(state.engine)
        yield
        provider = state._provider
        if provider is not None:
            await provider.close()
        await state.engine.dispose()

    app = FastAPI(
        title="Gatewise",
        version="0.1.0",
        summary="Typed decision infrastructure for software engineering.",
        lifespan=lifespan,
    )
    app.state.gatewise = state

    async def get_session() -> AsyncIterator[AsyncSession]:
        async with session_scope(state.engine) as session:
            yield session

    @app.get("/api/health", response_model=HealthView, tags=["system"])
    async def health() -> HealthView:
        """Report configuration state only. Never calls the model."""
        return HealthView(
            status="ok",
            decision_provider="jev",
            model=state.settings.jev_model,
            transport=state.settings.jev_transport,
            credentials_configured=state.settings.has_jev_key,
            webhook_configured=bool(state.settings.github_webhook_secret),
        )

    @app.post("/webhooks/github", response_model=WebhookAccepted, tags=["webhooks"])
    async def github_webhook(
        request: Request,
        session: AsyncSession = Depends(get_session),
        x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
        x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
        x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    ) -> WebhookAccepted:
        """Receive a pull request event.

        The signature is checked first, before the body is parsed. An unsigned or
        invalid delivery is rejected with 401 and never reaches the model.
        """
        body = await request.body()
        outcome = await state.service(session).handle_delivery(
            body,
            signature=x_hub_signature_256,
            delivery_id=x_github_delivery,
            event=x_github_event,
            secret=state.settings.github_webhook_secret or "",
        )
        if outcome.status == "unauthorized":
            return JSONResponse(
                status_code=401,
                content={"status": outcome.status, "detail": outcome.detail},
            )
        # Mirror the outcome's own status code so a duplicate or ignored event is
        # distinguishable from a fresh evaluation by the caller alone.
        return JSONResponse(
            status_code=outcome.http_status,
            content={
                "status": outcome.status,
                "detail": outcome.detail,
                "injection_flags": outcome.injection_flags or [],
                "actions": outcome.actions or [],
            },
        )


    @app.get("/api/pull-requests", response_model=list[PullRequestSummary], tags=["data"])
    async def list_pull_requests(
        repository: str | None = None,
        limit: int = 50,
        session: AsyncSession = Depends(get_session),
    ) -> list[PullRequestSummary]:
        """List evaluated pull requests, newest first. Empty when none exist."""
        store = AuditStore(session)
        records = await store.list_pull_requests(repository=repository, limit=limit)
        summaries = []
        for record, repo in records:
            summaries.append(
                PullRequestSummary(
                    id=record.id,
                    repository_id=record.repository_id,
                    repository=f"{repo.owner}/{repo.name}",
                    number=record.number,
                    title=record.title,
                    author=record.author,
                    status=record.status,
                    head_sha=record.head_sha,
                )
            )
        return summaries

    @app.get("/api/pull-requests/{pull_request_id}", tags=["data"])
    async def get_pull_request(
        pull_request_id: int, session: AsyncSession = Depends(get_session)
    ) -> dict:
        """Return one pull request with its runs."""
        store = AuditStore(session)
        record = await store.get_pull_request(pull_request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="pull request not found")
        runs = await store.get_runs(pull_request_id)
        return {
            "id": record.id,
            "number": record.number,
            "title": record.title,
            "author": record.author,
            "head_sha": record.head_sha,
            "runs": [RunView(**_run_fields(run)).model_dump() for run in runs],
        }

    @app.get(
        "/api/pull-requests/{pull_request_id}/decisions",
        response_model=list[DecisionView],
        tags=["data"],
    )
    async def get_pull_request_decisions(
        pull_request_id: int, session: AsyncSession = Depends(get_session)
    ) -> list[DecisionView]:
        """Decisions for the most recent run on this pull request."""
        store = AuditStore(session)
        runs = await store.get_runs(pull_request_id)
        if not runs:
            raise HTTPException(
                status_code=404, detail="no evaluation run for this pull request"
            )
        decisions = await store.get_decisions(runs[0].id)
        return [_decision_view(decision) for decision in decisions]

    @app.get("/api/pull-requests/{pull_request_id}/graph", tags=["data"])
    async def get_pull_request_graph(
        pull_request_id: int, session: AsyncSession = Depends(get_session)
    ) -> dict:
        """The decision path for the most recent run, in inspectable form.

        Returns the context summary, every decision with its question version, and
        the actions the run justified. This is the machine-readable form of the
        decision graph the specification asks to be reconstructable.
        """
        store = AuditStore(session)
        runs = await store.get_runs(pull_request_id)
        if not runs:
            raise HTTPException(
                status_code=404, detail="no evaluation run for this pull request"
            )
        run = runs[0]
        recorded = {a.fingerprint: a for a in await store.get_actions(run.id)}
        # The run records what it justified; the actions table records what is
        # still outstanding. A re-evaluated pull request dedupes to the same
        # fingerprint, so an empty actions list here does not mean "no actions
        # were justified" -- it means they were already recorded earlier.
        planned = []
        for entry in run.planned_actions or []:
            fingerprint = entry.get("fingerprint")
            existing = recorded.get(fingerprint)
            planned.append(
                {
                    "action_type": entry.get("action_type"),
                    "target": entry.get("target"),
                    "fingerprint": fingerprint,
                    "status": existing.status if existing is not None else "already_recorded",
                }
            )
        return {
            "pull_request_id": pull_request_id,
            "run": _run_fields(run),
            "context": {
                "injection_flags": list(run.injection_flags or []),
                "state_hash": run.state_hash,
            },
            "decisions": [
                _decision_view(d).model_dump()
                for d in await store.get_decisions(run.id)
            ],
            "actions": planned,
        }

    @app.get("/api/decisions", response_model=list[DecisionView], tags=["data"])
    async def get_all_decisions(
        limit: int = 100, session: AsyncSession = Depends(get_session)
    ) -> list[DecisionView]:
        """Most recent decisions across all pull requests."""
        store = AuditStore(session)
        records = await store.list_recent_decisions(limit=limit)
        return [_decision_view(record) for record in records]

    @app.post("/internal/decisions/evaluate", tags=["internal"])
    async def evaluate_now(
        payload: EvaluateRequest, session: AsyncSession = Depends(get_session)
    ) -> dict:
        """Evaluate an ad-hoc context without going through a webhook.

        Useful for testing a rubric change against sample text. Returns the
        decisions and the action plan; nothing is executed against GitHub.
        """
        service = state.service(session)
        provider = service._pipeline._provider  # noqa: SLF001 - internal route
        context = build_context(
            number=payload.number,
            title=payload.title,
            description=payload.description,
            author=payload.author,
            base_branch=payload.base_branch,
            head_branch=payload.head_branch,
            labels=payload.labels,
            changed_files=payload.changed_files,
        )
        run = await service._pipeline.evaluate(  # noqa: SLF001 - internal route
            _SyntheticEvent(payload), context
        )
        if not run.succeeded:
            return {
                "status": run.status.value,
                "error": run.error,
                "decisions": [],
                "actions": [],
            }
        return {
            "status": run.status.value,
            "state_hash": run.state_hash,
            "latency_ms": run.latency_ms,
            "question_versions": run.question_versions,
            "injection_flags": run.injection_flags,
            "decisions": _decisions_to_dicts(run.answers),
            "actions": service._pipeline.plan_actions(run),  # noqa: SLF001
        }

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        """Serve the decision index.

        The dashboard reads only what the API actually recorded. An empty
        database renders "No evaluations yet" rather than placeholder metrics.
        """
        return FileResponse(STATIC_DIR / "index.html")

    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    return app


class _SyntheticEvent:
    """Adapter so an ad-hoc context can reuse the pipeline's event interface."""

    def __init__(self, payload: EvaluateRequest) -> None:
        self.repository = "internal/adhoc"
        self.number = payload.number
        self.action = "opened"
        self.title = payload.title


def _decision_view(record) -> DecisionView:
    """Map a stored decision row onto the wire model.

    The ORM column is ``decision_run_id`` while the API field is ``run_id``;
    mapping explicitly keeps that rename in one place instead of relying on
    FastAPI to coerce an ORM object.
    """
    return DecisionView(
        run_id=record.decision_run_id,
        question_name=record.question_name,
        question_version=record.question_version,
        question_type=record.question_type,
        answer=record.answer,
        confidence=record.confidence,
        level=record.level,
    )


def _run_fields(run) -> dict:
    return {
        "id": run.id,
        "provider": run.provider,
        "model": run.model,
        "is_official_jev": run.is_official_jev,
        "status": run.status,
        "error": run.error,
        "latency_ms": run.latency_ms,
        "question_versions": list(run.question_versions or []),
        "injection_flags": list(run.injection_flags or []),
    }


def _decisions_to_dicts(answers: dict) -> list[dict]:
    from decisions.schemas import ChoiceAnswer, ScoreAnswer

    out = []
    for name, answer in answers.items():
        if isinstance(answer, ChoiceAnswer):
            out.append(
                {
                    "question": name,
                    "type": "choice",
                    "answer": answer.choice,
                    "confidence": answer.confidence,
                }
            )
        elif isinstance(answer, ScoreAnswer):
            out.append(
                {
                    "question": name,
                    "type": "score",
                    "answer": round(answer.score, 4),
                    "level": answer.resolve_level(),
                    "label": answer.level_label(),
                    "confidence": answer.confidence,
                }
            )
        else:
            out.append(
                {"question": name, "type": "noul", "answer": answer.noul}
            )
    return out


app = create_app()