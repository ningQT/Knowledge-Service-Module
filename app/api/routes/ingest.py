"""API routes for document ingestion (sync + async with SSE)."""

import asyncio
import json
import logging
import random
import string
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import (
    ensure_instance_access,
    get_ingest_service,
    get_ingest_service_for_background,
    require_read_context,
    require_write_context,
)
from app.api.models import (
    AsyncIngestResponse,
    CancelJobResponse,
    IngestJobResponse,
    IngestResponse,
    SseTokenResponse,
)
from app.config import get_settings
from app.exceptions import PipelineCancelledException
from app.observability import log_event
from app.security.sse_tokens import sse_token_store
from app.storage.path_utils import UnsafePathError, validate_upload_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/instances", tags=["ingest"])
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024

# --- In-memory job state tracking ---

_STEP_NAMES = {
    1: "结构感知分类",
    2: "路径决策",
    3: "Source Note 生成",
    4: "知识定位 / 卡片过滤",
    5: "知识提取",
    6: "知识地图生成",
    7: "关系描述",
    8: "归档索引",
}


@dataclass
class IngestJobState:
    job_id: str
    instance_id: str
    status: str = "pending"
    cancelled: bool = False
    steps: list[dict] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    generated_cards: list[str] = field(default_factory=list)
    generated_maps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    sse_subscribers: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        self.steps = [
            {"step": i, "name": _STEP_NAMES.get(i, f"Step {i}"), "status": "pending", "summary": None}
            for i in range(1, 9)
        ]


# Module-level active jobs dict
_active_jobs: dict[str, IngestJobState] = {}

# Lock for thread-safe job creation
_jobs_lock = threading.Lock()


def _generate_job_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"job_{ts}_{suffix}"


def _push_event(job: IngestJobState, event: dict):
    """Push SSE event to all subscribers."""
    with _jobs_lock:
        subscribers = list(job.sse_subscribers)
    for q in subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _cleanup_old_jobs():
    """Remove completed jobs older than 1 hour."""
    now = time.time()
    to_remove = []
    for jid, job in _active_jobs.items():
        if job.status in ("success", "partial_failed", "failed", "cancelled"):
            # Parse started_at to check age
            try:
                job_time = datetime.fromisoformat(job.started_at).timestamp() if job.started_at else 0
                if now - job_time > 3600:
                    to_remove.append(jid)
            except (ValueError, TypeError):
                pass
    for jid in to_remove:
        _active_jobs.pop(jid, None)


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _safe_upload_name(filename: str | None) -> str:
    try:
        return validate_upload_filename(filename)
    except UnsafePathError as e:
        detail = str(e) if str(e) == "Only .md files are supported" else "Invalid upload filename"
        raise HTTPException(status_code=400, detail=detail) from e


async def _read_markdown_upload(file: UploadFile) -> bytes:
    max_bytes = max(0, int(get_settings().max_upload_bytes))
    content = bytearray()
    while True:
        read_size = min(UPLOAD_READ_CHUNK_BYTES, max(1, max_bytes + 1 - len(content)))
        chunk = await file.read(read_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="Uploaded file is too large")
    return bytes(content)


# --- Sync ingest (existing) ---

@router.post("/{instance_id}/ingest", response_model=IngestResponse)
async def ingest_document(
    instance_id: str,
    file: UploadFile = File(...),
    domain_hint: str | None = Form(None),
    auto_map: bool = Form(True),
    auth=Depends(require_write_context),
):
    """Ingest a markdown document into a knowledge base instance (synchronous)."""
    started = time.perf_counter()
    ensure_instance_access(auth, instance_id, write=True)
    filename = _safe_upload_name(file.filename)
    log_event(
        logger,
        "process.ingest.start",
        mode="sync",
        instance_id=instance_id,
        filename=filename,
        auto_map=auto_map,
        domain_hint_provided=bool(domain_hint),
    )

    content = await _read_markdown_upload(file)
    try:
        markdown = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(markdown)
        tmp_path = tmp.name

    svc = get_ingest_service()
    try:
        result = svc.ingest_document(
            instance_id=instance_id,
            file_path=tmp_path,
            filename=filename,
            auto_map=auto_map,
            domain_hint=domain_hint,
        )
        log_event(
            logger,
            "process.ingest.done",
            mode="sync",
            instance_id=instance_id,
            job_id=result.job_id,
            status=result.status,
            file_bytes=len(content),
            created_count=len(result.created_files),
            card_count=len(result.generated_cards),
            map_count=len(result.generated_maps),
            warning_count=len(result.warnings),
            duration_ms=_duration_ms(started),
        )
        return IngestResponse(
            job_id=result.job_id,
            status=result.status,
            created_files=result.created_files,
            generated_cards=result.generated_cards,
            generated_maps=result.generated_maps,
            warnings=result.warnings,
        )
    except Exception:
        log_event(
            logger,
            "process.ingest.error",
            level=logging.ERROR,
            mode="sync",
            instance_id=instance_id,
            filename=filename,
            duration_ms=_duration_ms(started),
            exc_info=True,
        )
        raise
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# --- Async ingest ---

@router.post("/{instance_id}/ingest/async", response_model=AsyncIngestResponse)
async def ingest_async(
    instance_id: str,
    file: UploadFile = File(...),
    domain_hint: str | None = Form(None),
    auto_map: bool = Form(True),
    auth=Depends(require_write_context),
):
    """Trigger async ingest, returns job_id for SSE progress tracking."""
    ensure_instance_access(auth, instance_id, write=True)
    filename = _safe_upload_name(file.filename)

    # Check if instance already has a running job
    with _jobs_lock:
        for job in _active_jobs.values():
            if job.instance_id == instance_id and job.status in ("pending", "running"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Instance '{instance_id}' already has a running ingest job: {job.job_id}",
                )

    content = await _read_markdown_upload(file)
    try:
        markdown = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    job_id = _generate_job_id()
    now = datetime.now(UTC).isoformat()

    job = IngestJobState(
        job_id=job_id,
        instance_id=instance_id,
        status="pending",
        started_at=now,
    )

    with _jobs_lock:
        _active_jobs[job_id] = job
        # Cleanup old jobs periodically (N-01: 在锁保护范围内调用)
        _cleanup_old_jobs()

    log_event(
        logger,
        "job.start",
        job_type="ingest",
        job_id=job_id,
        instance_id=instance_id,
        filename=filename,
        file_bytes=len(content),
        auto_map=auto_map,
        domain_hint_provided=bool(domain_hint),
    )
    # Start background task
    asyncio.create_task(
        _run_ingest_background(job, markdown, instance_id, filename, auto_map, domain_hint)
    )

    return AsyncIngestResponse(job_id=job_id, status="pending")


async def _run_ingest_background(
    job: IngestJobState,
    markdown: str,
    instance_id: str,
    filename: str,
    auto_map: bool,
    domain_hint: str | None,
):
    """Execute ingest in a background thread with progress tracking."""
    started = time.perf_counter()
    step_started: dict[int, float] = {}
    job.status = "running"
    _push_event(job, {"event": "job_start", "data": json.dumps({"job_id": job.job_id})})
    log_event(
        logger,
        "process.ingest.start",
        mode="async",
        job_id=job.job_id,
        instance_id=instance_id,
        filename=filename,
        auto_map=auto_map,
        domain_hint_provided=bool(domain_hint),
    )

    def progress_callback(step: int, status: str, summary: dict | None = None):
        step_name = _STEP_NAMES.get(step, f"Step {step}")
        if status == "running":
            step_started[step] = time.perf_counter()
            log_event(
                logger,
                "process.ingest.step.start",
                job_id=job.job_id,
                instance_id=instance_id,
                step=step,
                step_name=step_name,
            )
        elif status in {"completed", "failed"}:
            log_event(
                logger,
                "process.ingest.step.done" if status == "completed" else "process.ingest.step.error",
                level=logging.INFO if status == "completed" else logging.ERROR,
                job_id=job.job_id,
                instance_id=instance_id,
                step=step,
                step_name=step_name,
                status=status,
                duration_ms=_duration_ms(step_started.get(step, time.perf_counter())),
                summary_keys=sorted(summary.keys()) if summary else [],
            )
        step_data = {"step": step, "name": _STEP_NAMES.get(step, f"Step {step}"), "status": status}
        if summary:
            step_data["summary"] = summary

        with job.lock:
            for s in job.steps:
                if s["step"] == step:
                    s["status"] = status
                    if summary:
                        s["summary"] = summary
                    break

        event_type = "step_output" if status == "completed" else "step_update"
        _push_event(job, {"event": event_type, "data": json.dumps(step_data)})

    def _cancel_check() -> bool:
        with job.lock:
            return job.cancelled

    def _execute():
        db = None
        try:
            svc, db = get_ingest_service_for_background()
            # 设计文档 §885: 后台线程创建独立的 SQLiteBackend 实例，不复用缓存的单例
            svc, db = get_ingest_service_for_background()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
                tmp.write(markdown)
                tmp_path = tmp.name

            try:
                result = svc.ingest_document(
                    instance_id=instance_id,
                    file_path=tmp_path,
                    filename=filename,
                    auto_map=auto_map,
                    domain_hint=domain_hint,
                    progress_callback=progress_callback,
                    cancel_check=_cancel_check,
                    job_id=job.job_id,
                )
                with job.lock:
                    job.created_files = result.created_files
                    job.generated_cards = result.generated_cards
                    job.generated_maps = result.generated_maps
                    job.warnings = result.warnings
                    job.status = result.status
                log_event(
                    logger,
                    "process.ingest.done",
                    mode="async",
                    job_id=job.job_id,
                    instance_id=instance_id,
                    status=result.status,
                    created_count=len(result.created_files),
                    card_count=len(result.generated_cards),
                    map_count=len(result.generated_maps),
                    warning_count=len(result.warnings),
                    duration_ms=_duration_ms(started),
                )
                log_event(
                    logger,
                    "job.done",
                    job_type="ingest",
                    job_id=job.job_id,
                    instance_id=instance_id,
                    status=result.status,
                    duration_ms=_duration_ms(started),
                )
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        except PipelineCancelledException:
            logger.info("Ingest job %s was cancelled", job.job_id)
            with job.lock:
                job.status = "cancelled"
            log_event(
                logger,
                "job.cancelled",
                job_type="ingest",
                job_id=job.job_id,
                instance_id=instance_id,
                duration_ms=_duration_ms(started),
            )
            _push_event(job, {"event": "job_cancelled", "data": json.dumps({"job_id": job.job_id})})

        except Exception as e:
            logger.error("Background ingest failed: %s", e)
            failed_step = None
            with job.lock:
                job.status = "failed"
                job.warnings.append(str(e))
                for step in job.steps:
                    if step["status"] == "running":
                        step["status"] = "failed"
                        step["summary"] = {"error": str(e)}
                        failed_step = dict(step)
                        break
            if failed_step:
                _push_event(job, {"event": "step_output", "data": json.dumps(failed_step)})
            log_event(
                logger,
                "process.ingest.error",
                level=logging.ERROR,
                mode="async",
                job_id=job.job_id,
                instance_id=instance_id,
                duration_ms=_duration_ms(started),
                error_type=e.__class__.__name__,
                exc_info=True,
            )
            log_event(
                logger,
                "job.error",
                level=logging.ERROR,
                job_type="ingest",
                job_id=job.job_id,
                instance_id=instance_id,
                status="failed",
                duration_ms=_duration_ms(started),
            )

        finally:
            # 关闭独立的数据库连接
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

            with job.lock:
                job.finished_at = datetime.now(UTC).isoformat()

                complete_data = {
                    "status": job.status,
                    "created_files": job.created_files,
                    "generated_cards": job.generated_cards,
                    "generated_maps": job.generated_maps,
                    "warnings": job.warnings,
                }
            _push_event(job, {"event": "job_complete", "data": json.dumps(complete_data)})

            # Send sentinel to close SSE streams
            with _jobs_lock:
                subscribers = list(job.sse_subscribers)
            for q in subscribers:
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    await asyncio.to_thread(_execute)


# --- Job polling ---

@router.get("/{instance_id}/ingest/jobs/{job_id}", response_model=IngestJobResponse)
async def get_job_status(instance_id: str, job_id: str, auth=Depends(require_read_context)):
    """Get ingest job status (polling fallback for SSE)."""
    ensure_instance_access(auth, instance_id)
    job = _active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job.instance_id != instance_id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found in instance '{instance_id}'")

    with job.lock:
        return IngestJobResponse(
            job_id=job.job_id,
            instance_id=job.instance_id,
            status=job.status,
            steps=list(job.steps),
            created_files=list(job.created_files),
            generated_cards=list(job.generated_cards),
            generated_maps=list(job.generated_maps),
            warnings=list(job.warnings),
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


@router.post("/{instance_id}/ingest/jobs/{job_id}/sse-token", response_model=SseTokenResponse)
async def create_job_sse_token(instance_id: str, job_id: str, auth=Depends(require_read_context)):
    """Create a short-lived one-time SSE token for browser EventSource."""
    ensure_instance_access(auth, instance_id)
    job = _active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job.instance_id != instance_id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found in instance '{instance_id}'")

    token, expires_at = sse_token_store.create(
        endpoint="ingest",
        job_id=job_id,
        scope=instance_id,
        ttl_seconds=get_settings().sse_token_ttl_seconds,
    )
    sse_url = f"/api/v1/instances/{instance_id}/ingest/jobs/{job_id}/sse?sse_token={token}"
    return SseTokenResponse(sse_token=token, expires_at=expires_at, sse_url=sse_url)


# --- SSE progress stream ---

@router.get("/{instance_id}/ingest/jobs/{job_id}/sse")
async def job_sse_stream(
    request: Request,
    instance_id: str,
    job_id: str,
    sse_token: str | None = None,
):
    """SSE endpoint for real-time pipeline progress updates."""
    job = _active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job.instance_id != instance_id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found in instance '{instance_id}'")
    await _authorize_ingest_sse(request, instance_id, job_id, sse_token)

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _jobs_lock:
        job.sse_subscribers.append(queue)

    async def event_generator():
        try:
            # Replay already-completed steps
            with job.lock:
                steps_snapshot = list(job.steps)
                job_status = job.status
                complete_snapshot = {
                    "status": job.status,
                    "created_files": list(job.created_files),
                    "generated_cards": list(job.generated_cards),
                    "generated_maps": list(job.generated_maps),
                    "warnings": list(job.warnings),
                }

            for step in steps_snapshot:
                if step["status"] in ("completed", "failed"):
                    yield {"event": "step_output", "data": json.dumps(step)}
                elif step["status"] == "running":
                    yield {"event": "step_update", "data": json.dumps(step)}

            # If job is already done, send completion and close
            if job_status in ("success", "partial_failed", "failed", "cancelled"):
                yield {"event": "job_complete", "data": json.dumps(complete_snapshot)}
                return

            # Stream new events
            while True:
                event = await queue.get()
                if event is None:  # Sentinel: job finished
                    break
                yield event

        finally:
            with _jobs_lock:
                if queue in job.sse_subscribers:
                    job.sse_subscribers.remove(queue)

    return EventSourceResponse(event_generator())


async def _authorize_ingest_sse(
    request: Request,
    instance_id: str,
    job_id: str,
    sse_token: str | None,
) -> None:
    if sse_token_store.consume(
        sse_token,
        endpoint="ingest",
        job_id=job_id,
        scope=instance_id,
    ):
        return
    auth = await require_read_context(request)
    ensure_instance_access(auth, instance_id)


# --- Cancel endpoint ---

@router.post("/{instance_id}/ingest/jobs/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(instance_id: str, job_id: str, auth=Depends(require_write_context)):
    """Cancel a running ingest job."""
    ensure_instance_access(auth, instance_id, write=True)
    job = _active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job.instance_id != instance_id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found in instance '{instance_id}'")

    with job.lock:
        if job.status not in ("pending", "running"):
            raise HTTPException(status_code=409, detail=f"Job '{job_id}' is not running (status: {job.status})")
        job.cancelled = True

    return CancelJobResponse(cancelled=True, message=f"Job {job_id} has been cancelled")
