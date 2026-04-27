from __future__ import annotations
"""
Incident API routes for SynthSense.
Handles incident submission, retrieval, listing, and SSE streaming.
"""
import json
import logging
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.graph import run_incident, stream_incident
from memory.redis_cache import cache_increment
from memory.vector_store import get_incident_by_id, list_incidents
from config import settings


class StreamRequest(BaseModel):
    description: str
    image_b64: str = ""

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["incidents"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class IncidentResponse(BaseModel):
    incident_id: str
    severity: str | None = None
    diagnosis: str | None = None
    remediation: str | None = None
    postmortem: str | None = None
    triage_result: dict | None = None
    remediation_result: dict | None = None
    status: str = "processing"


class IncidentSummary(BaseModel):
    id: str
    title: str | None = None
    severity: str | None = None
    created_at: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=IncidentResponse)
async def submit_incident(
    description: str = Form(..., description="Incident description and/or raw logs"),
    image: UploadFile | None = None,
):
    """
    Submit a new incident for analysis.
    Accepts a text description / raw logs and an optional dashboard screenshot.
    Returns immediately with the incident_id; use the /stream endpoint for live progress.
    """
    incident_id = str(uuid.uuid4())
    image_b64 = ""

    if image and image.content_type and image.content_type.startswith("image/"):
        import base64
        image_bytes = await image.read()
        image_b64 = base64.b64encode(image_bytes).decode()
        logger.info("Received image upload: %s (%d bytes)", image.filename, len(image_bytes))

    initial_state = {
        "incident_id": incident_id,
        "raw_input": description,
        "image_b64": image_b64,
    }

    logger.info("Processing incident %s synchronously…", incident_id)
    try:
        final_state = await run_incident(initial_state)
    except Exception as exc:
        logger.error("Incident pipeline failed for %s: %s", incident_id, exc)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")

    # Fire-and-forget LLM judge scoring
    import asyncio as _asyncio
    from eval.llm_judge import judge_incident as _judge
    async def _run_judge():
        try:
            scores = await _judge(
                incident_input=description[:2000],
                diagnosis=final_state.get("diagnosis", ""),
                remediation=final_state.get("remediation", ""),
            )
            logger.info("LLM judge scores for %s: overall=%.2f", incident_id, scores.get("overall", 0))
        except Exception as exc:
            logger.warning("LLM judge failed for %s: %s", incident_id, exc)
    _asyncio.create_task(_run_judge())

    # Trigger RAGAS assessment every N incidents
    count = await cache_increment("incident_count")
    if count % settings.eval_every_n_incidents == 0:
        from eval.ragas_eval import ragas_assess
        _asyncio.create_task(ragas_assess())
        logger.info("Triggered background RAGAS assessment (incident count: %d)", count)

    return IncidentResponse(
        incident_id=incident_id,
        severity=final_state.get("severity"),
        diagnosis=final_state.get("diagnosis"),
        remediation=final_state.get("remediation"),
        postmortem=final_state.get("postmortem"),
        triage_result=final_state.get("triage_result"),
        remediation_result=final_state.get("remediation_result"),
        status="completed",
    )


def _make_event_generator(incident_id: str, initial_state: dict, trigger_ragas: bool = True):
    async def event_generator() -> AsyncIterator[str]:
        try:
            async for event in stream_incident(initial_state):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            logger.error("SSE stream error for %s: %s", incident_id, exc)
            error_event = {"incident_id": incident_id, "agent": "error", "status": "failed", "error": str(exc)}
            yield f"data: {json.dumps(error_event)}\n\n"
        finally:
            if trigger_ragas:
                import asyncio as _asyncio
                count = await cache_increment("incident_count")
                if count % settings.eval_every_n_incidents == 0:
                    from eval.ragas_eval import ragas_assess
                    _asyncio.create_task(ragas_assess())
                    logger.info("Triggered background RAGAS assessment (stream endpoint, count: %d)", count)
    return event_generator


@router.get("/{incident_id}/stream")
async def stream_incident_progress(incident_id: str, description: str = "", image_b64: str = ""):
    """SSE stream via GET (for curl / EventSource clients)."""
    initial_state = {"incident_id": incident_id, "raw_input": description, "image_b64": image_b64}
    return StreamingResponse(
        _make_event_generator(incident_id, initial_state)(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{incident_id}/stream")
async def stream_incident_progress_post(incident_id: str, body: StreamRequest):
    """
    SSE stream via POST — accepts JSON body so large base64 images can be sent
    without URL length limits. Used by the React frontend.
    """
    initial_state = {"incident_id": incident_id, "raw_input": body.description, "image_b64": body.image_b64}
    return StreamingResponse(
        _make_event_generator(incident_id, initial_state)(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{incident_id}", response_model=dict)
async def get_incident(incident_id: str):
    """Retrieve the full stored record for a completed incident."""
    incident = await get_incident_by_id(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return incident


@router.get("", response_model=list[IncidentSummary])
async def list_recent_incidents(limit: int = 20):
    """List the most recent incidents (title, severity, timestamp)."""
    rows = await list_incidents(limit=min(limit, 100))
    return [
        IncidentSummary(
            id=str(row.get("id", "")),
            title=row.get("title"),
            severity=row.get("severity"),
            created_at=row.get("created_at"),
        )
        for row in rows
    ]
