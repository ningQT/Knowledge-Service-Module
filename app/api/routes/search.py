"""API routes for knowledge search and answer synthesis."""

import asyncio
import json
import logging
import random
import string
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import (
    get_answer_service,
    get_answer_service_for_background,
    get_search_service,
    require_read_context,
    restrict_instance_ids,
)
from app.api.models import (
    SearchAnswerJobResponse,
    SearchAnswerJobStatusResponse,
    SearchAnswerRequest,
    SearchRequest,
    SearchResponse,
    SearchStatsResponse,
    SseTokenResponse,
)
from app.config import get_settings
from app.pipeline.answer_models import AnswerResult
from app.pipeline.answer_pipeline import ANSWER_STEP_NAMES
from app.observability import log_event, query_hash
from app.security.sse_tokens import sse_token_store

router = APIRouter(prefix="/api/v1", tags=["search"])
logger = logging.getLogger(__name__)

LLM_THOUGHT_STEP_NAMES = {"batch_summarization", "answer_synthesis"}


@dataclass
class AnswerJobState:
    job_id: str
    query: str
    instance_ids: list[str] | None
    status: str = "pending"
    steps: list[dict] = field(default_factory=list)
    result: dict | None = None
    warnings: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    sse_subscribers: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        self.steps = [
            {"step": step, "name": name, "status": "pending", "summary": None}
            for step, name in ANSWER_STEP_NAMES.items()
        ]


_answer_jobs: dict[str, AnswerJobState] = {}
_answer_jobs_lock = threading.Lock()


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(req: SearchRequest, auth=Depends(require_read_context)):
    """Search knowledge across instances."""
    started = time.perf_counter()
    instance_ids = restrict_instance_ids(auth, req.instance_ids)
    q_hash = query_hash(req.query)
    log_event(
        logger,
        "search.request",
        query_hash=q_hash,
        instance_ids=instance_ids,
        layer_filter=req.layer_filter,
        verification_filter=req.verification_filter,
        include_comprehension=req.include_comprehension,
    )
    if instance_ids == [] and not auth.is_admin:
        log_event(
            logger,
            "search.output",
            query_hash=q_hash,
            intent_type="fallback",
            total=0,
            duration_ms=_duration_ms(started),
            unauthorized_empty_scope=True,
        )
        return SearchResponse(
            query=req.query,
            intent_type="fallback",
            stats=SearchStatsResponse(total=0),
        )

    svc = get_search_service()
    try:
        result = svc.search(
            query=req.query,
            instance_ids=instance_ids,
            layer_filter=req.layer_filter,
            verification_filter=req.verification_filter,
            include_comprehension=req.include_comprehension,
        )
    except Exception:
        log_event(
            logger,
            "search.error",
            level=logging.ERROR,
            query_hash=q_hash,
            instance_ids=instance_ids,
            duration_ms=_duration_ms(started),
            exc_info=True,
        )
        raise

    log_event(
        logger,
        "search.output",
        query_hash=q_hash,
        duration_ms=_duration_ms(started),
        **_search_result_log_fields(result),
    )

    return SearchResponse(
        query=result.query,
        intent_type=result.intent_type,
        query_context=result.query_context,
        core_hits=result.core_hits,
        related_cards=result.related_cards,
        source_notes=result.source_notes,
        maps=result.maps,
        map_priority=result.map_priority,
        key_relations=result.key_relations,
        stats=SearchStatsResponse(
            core_count=result.stats.core_count,
            related_count=result.stats.related_count,
            source_count=result.stats.source_count,
            map_count=result.stats.map_count,
            total=result.stats.total,
            fallback_mode=result.stats.fallback_mode,
            search_path=result.stats.search_path,
            map_sourced_count=result.stats.map_sourced_count,
        ),
        comprehension=result.comprehension.model_dump(mode="json") if result.comprehension else None,
    )


@router.post("/search/answer")
async def search_answer(req: SearchAnswerRequest, auth=Depends(require_read_context)):
    """Generate a map/card based answer with source-note citations."""
    started = time.perf_counter()
    instance_ids = restrict_instance_ids(auth, req.instance_ids)
    q_hash = query_hash(req.query)
    log_event(
        logger,
        "process.answer.start",
        query_hash=q_hash,
        instance_ids=instance_ids,
        include_search_result=req.include_search_result,
        include_comprehension=req.include_comprehension,
    )
    if instance_ids == [] and not auth.is_admin:
        log_event(
            logger,
            "process.answer.done",
            query_hash=q_hash,
            status="empty_unauthorized_scope",
            duration_ms=_duration_ms(started),
        )
        return AnswerResult(
            query=req.query,
            answer="",
            warnings=["No authorized knowledge bases are available."],
        ).model_dump(mode="json")

    svc = get_answer_service()
    try:
        result = svc.synthesize(
            query=req.query,
            instance_ids=instance_ids,
            include_search_result=req.include_search_result,
            include_comprehension=req.include_comprehension,
        )
    except Exception:
        log_event(
            logger,
            "process.answer.error",
            level=logging.ERROR,
            query_hash=q_hash,
            instance_ids=instance_ids,
            duration_ms=_duration_ms(started),
            exc_info=True,
        )
        raise
    log_event(
        logger,
        "process.answer.done",
        query_hash=q_hash,
        warning_count=len(result.warnings),
        citation_count=len(result.citations),
        duration_ms=_duration_ms(started),
    )
    return result.model_dump(mode="json")


@router.post("/search/answer-jobs", response_model=SearchAnswerJobResponse)
async def start_search_answer_job(req: SearchAnswerRequest, auth=Depends(require_read_context)):
    """Start answer synthesis in the background and return a job id."""
    instance_ids = restrict_instance_ids(auth, req.instance_ids)
    job_id = _generate_answer_job_id()
    job = AnswerJobState(
        job_id=job_id,
        query=req.query,
        instance_ids=instance_ids,
        started_at=datetime.now(UTC).isoformat(),
    )
    with _answer_jobs_lock:
        _answer_jobs[job_id] = job
        _cleanup_old_answer_jobs()

    log_event(
        logger,
        "job.start",
        job_type="answer",
        job_id=job_id,
        query_hash=query_hash(req.query),
        instance_ids=instance_ids,
    )
    asyncio.create_task(_run_answer_background(job, req))
    return SearchAnswerJobResponse(job_id=job_id, status="pending")


@router.get("/search/answer-jobs/{job_id}", response_model=SearchAnswerJobStatusResponse)
async def get_search_answer_job(job_id: str, auth=Depends(require_read_context)):
    """Get answer synthesis job status."""
    job = _get_answer_job(job_id)
    restrict_instance_ids(auth, job.instance_ids)
    return SearchAnswerJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        query=job.query,
        steps=job.steps,
        result=job.result,
        warnings=job.warnings,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/search/answer-jobs/{job_id}/sse-token", response_model=SseTokenResponse)
async def create_search_answer_sse_token(job_id: str, auth=Depends(require_read_context)):
    """Create a short-lived one-time SSE token for browser EventSource."""
    job = _get_answer_job(job_id)
    restrict_instance_ids(auth, job.instance_ids)
    token, expires_at = sse_token_store.create(
        endpoint="answer",
        job_id=job_id,
        scope=_answer_scope(job.instance_ids),
        ttl_seconds=get_settings().sse_token_ttl_seconds,
    )
    sse_url = f"/api/v1/search/answer-jobs/{job_id}/sse?sse_token={token}"
    return SseTokenResponse(sse_token=token, expires_at=expires_at, sse_url=sse_url)


@router.get("/search/answer-jobs/{job_id}/sse")
async def search_answer_job_sse(
    request: Request,
    job_id: str,
    sse_token: str | None = None,
):
    """Stream answer synthesis progress as server-sent events."""
    job = _get_answer_job(job_id)
    await _authorize_answer_sse(request, job, sse_token)
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _answer_jobs_lock:
        job.sse_subscribers.append(queue)

    async def event_generator():
        try:
            yield {"event": "job_start", "data": json.dumps({"job_id": job.job_id, "status": job.status})}
            with job.lock:
                for step in job.steps:
                    if step["status"] in {"running", "completed", "failed"}:
                        yield {"event": "step_output", "data": json.dumps(step)}
                if job.result:
                    yield {"event": "job_complete", "data": json.dumps(job.result)}
                    return

            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
                if event.get("event") in {"job_complete", "job_failed"}:
                    break
        finally:
            with _answer_jobs_lock:
                if queue in job.sse_subscribers:
                    job.sse_subscribers.remove(queue)

    return EventSourceResponse(event_generator())


async def _authorize_answer_sse(
    request: Request,
    job: AnswerJobState,
    sse_token: str | None,
) -> None:
    if sse_token_store.consume(
        sse_token,
        endpoint="answer",
        job_id=job.job_id,
        scope=_answer_scope(job.instance_ids),
    ):
        return
    auth = await require_read_context(request)
    restrict_instance_ids(auth, job.instance_ids)


def _answer_scope(instance_ids: list[str] | None) -> str:
    return "*" if instance_ids is None else "|".join(sorted(instance_ids))


def _generate_answer_job_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"answer_{ts}_{suffix}"


def _cleanup_old_answer_jobs() -> None:
    now = time.time()
    to_remove = []
    for job_id, job in _answer_jobs.items():
        if job.status in {"success", "failed"}:
            try:
                started = datetime.fromisoformat(job.started_at).timestamp() if job.started_at else 0
            except (TypeError, ValueError):
                started = 0
            if now - started > 3600:
                to_remove.append(job_id)
    for job_id in to_remove:
        _answer_jobs.pop(job_id, None)


def _get_answer_job(job_id: str) -> AnswerJobState:
    job = _answer_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


def _push_answer_event(job: AnswerJobState, event: dict) -> None:
    with _answer_jobs_lock:
        subscribers = list(job.sse_subscribers)
    for queue in subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _search_result_log_fields(result) -> dict:
    stats = result.stats
    return {
        "intent_type": result.intent_type,
        "core_count": stats.core_count,
        "related_count": stats.related_count,
        "source_count": stats.source_count,
        "map_count": stats.map_count,
        "total": stats.total,
        "fallback_mode": stats.fallback_mode,
        "search_path": stats.search_path,
        "map_sourced_count": stats.map_sourced_count,
        "core_paths": _node_paths(result.core_hits),
        "map_paths": _node_paths(result.maps),
    }


def _node_paths(nodes: list[dict], limit: int = 5) -> list[str]:
    paths: list[str] = []
    for node in nodes[:limit]:
        path = node.get("path") or node.get("file_path") or node.get("id")
        if path:
            paths.append(str(path))
    return paths


async def _run_answer_background(job: AnswerJobState, req: SearchAnswerRequest) -> None:
    started = time.perf_counter()
    q_hash = query_hash(req.query)
    step_started: dict[int, float] = {}
    job.status = "running"
    _push_answer_event(job, {"event": "job_start", "data": json.dumps({"job_id": job.job_id})})
    log_event(
        logger,
        "process.answer.start",
        job_id=job.job_id,
        query_hash=q_hash,
        instance_ids=job.instance_ids,
    )

    def progress_callback(step: int, status: str, summary: dict | None = None):
        step_name = ANSWER_STEP_NAMES.get(step, f"step_{step}")
        if status == "thought_summary":
            if step_name not in LLM_THOUGHT_STEP_NAMES or not summary:
                return
            current_status = "running"
            with job.lock:
                for item in job.steps:
                    if item["step"] == step:
                        current_status = item.get("status") or current_status
                        break
            _push_answer_event(
                job,
                {
                    "event": "thought_summary",
                    "data": json.dumps(
                        {
                            "step": step,
                            "name": step_name,
                            "status": current_status,
                            "summary": summary,
                        }
                    ),
                },
            )
            return

        if status == "running":
            step_started[step] = time.perf_counter()
            log_event(
                logger,
                "process.answer.step.start",
                job_id=job.job_id,
                step=step,
                step_name=step_name,
            )
        elif status in {"completed", "failed"}:
            log_event(
                logger,
                "process.answer.step.done" if status == "completed" else "process.answer.step.error",
                level=logging.INFO if status == "completed" else logging.ERROR,
                job_id=job.job_id,
                step=step,
                step_name=step_name,
                status=status,
                duration_ms=_duration_ms(step_started.get(step, time.perf_counter())),
                summary_keys=sorted(summary.keys()) if summary else [],
            )
        step_data = {
            "step": step,
            "name": step_name,
            "status": status,
            "summary": summary,
        }
        with job.lock:
            for item in job.steps:
                if item["step"] == step:
                    item["status"] = status
                    item["summary"] = summary
                    break
        event_type = "step_output" if status == "completed" else "step_update"
        _push_answer_event(job, {"event": event_type, "data": json.dumps(step_data)})

    def _execute():
        db = None
        try:
            svc, db = get_answer_service_for_background()
            result = svc.synthesize(
                query=req.query,
                instance_ids=job.instance_ids,
                include_search_result=req.include_search_result,
                include_comprehension=req.include_comprehension,
                progress_callback=progress_callback,
            )
            payload = result.model_dump(mode="json")
            with job.lock:
                job.result = payload
                job.warnings = result.warnings
                job.status = "success"
                job.finished_at = datetime.now(UTC).isoformat()
            log_event(
                logger,
                "process.answer.done",
                job_id=job.job_id,
                query_hash=q_hash,
                warning_count=len(result.warnings),
                citation_count=len(result.citations),
                duration_ms=_duration_ms(started),
            )
            log_event(
                logger,
                "job.done",
                job_type="answer",
                job_id=job.job_id,
                status="success",
                duration_ms=_duration_ms(started),
            )
            _push_answer_event(job, {"event": "job_complete", "data": json.dumps(payload)})
        except Exception as exc:
            with job.lock:
                job.status = "failed"
                job.finished_at = datetime.now(UTC).isoformat()
                job.warnings.append(str(exc))
                for step in job.steps:
                    if step["status"] == "running":
                        step["status"] = "failed"
            log_event(
                logger,
                "process.answer.error",
                level=logging.ERROR,
                job_id=job.job_id,
                query_hash=q_hash,
                duration_ms=_duration_ms(started),
                error_type=exc.__class__.__name__,
                exc_info=True,
            )
            log_event(
                logger,
                "job.error",
                level=logging.ERROR,
                job_type="answer",
                job_id=job.job_id,
                status="failed",
                duration_ms=_duration_ms(started),
            )
            _push_answer_event(
                job,
                {"event": "job_failed", "data": json.dumps({"job_id": job.job_id, "error": str(exc)})},
            )
        finally:
            if db is not None:
                db.close()
            with _answer_jobs_lock:
                subscribers = list(job.sse_subscribers)
            for queue in subscribers:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    await asyncio.to_thread(_execute)
