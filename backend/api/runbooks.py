from __future__ import annotations
"""
Runbook upload API route for SynthSense.
Accepts PDF files, runs the ingestion pipeline, and returns chunk stats.
"""
import logging

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from ingestion.pdf_processor import ingest_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runbooks", tags=["runbooks"])

_MAX_PDF_SIZE_MB = 20


class RunbookUploadResponse(BaseModel):
    filename: str
    chunk_count: int
    skipped: bool
    message: str


@router.post("/upload", response_model=RunbookUploadResponse)
async def upload_runbook(file: UploadFile):
    """
    Upload a runbook PDF to be chunked and indexed into the vector store.
    Re-uploading the same filename is a no-op (deduplication by filename).
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()

    size_mb = len(pdf_bytes) / (1024 * 1024)
    if size_mb > _MAX_PDF_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Max allowed: {_MAX_PDF_SIZE_MB} MB",
        )

    logger.info("Ingesting runbook: %s (%.2f MB)", file.filename, size_mb)

    try:
        result = await ingest_pdf(pdf_bytes, file.filename)
    except Exception as exc:
        logger.error("Runbook ingestion failed for %s: %s", file.filename, exc)
        raise HTTPException(status_code=500, detail=f"Ingestion error: {exc}")

    if result["skipped"]:
        message = f"Runbook '{file.filename}' already indexed — skipped."
    else:
        message = f"Successfully indexed {result['chunk_count']} chunks from '{file.filename}'."

    return RunbookUploadResponse(
        filename=result["filename"],
        chunk_count=result["chunk_count"],
        skipped=result["skipped"],
        message=message,
    )
