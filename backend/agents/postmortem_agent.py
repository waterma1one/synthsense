from __future__ import annotations
"""
Postmortem agent for SynthSense.
Summarizes the full incident into a three-section postmortem, generates an
embedding of the postmortem text, and persists everything to Supabase so
future incidents can learn from this one via vector similarity search.
"""
import logging
from typing import Any

from groq import AsyncGroq
from sentence_transformers import SentenceTransformer
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from config import settings
from memory.vector_store import upsert_incident

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None
_embedding_model: SentenceTransformer | None = None

_POSTMORTEM_SYSTEM = """You are writing an incident postmortem for an engineering team.
Structure your response in exactly three Markdown sections.
Be factual, blameless, and specific."""

_POSTMORTEM_USER_TMPL = """
Write a blameless postmortem for the following incident.

## Incident Summary
- ID: {incident_id}
- Severity: {severity}
- Raw Input: {raw_input}
- Image Analysis: {image_description}
- Diagnosis: {diagnosis}
- Remediation Applied: {remediation}

Format your response as Markdown with EXACTLY these three sections:

## What Happened
<factual timeline of events>

## Why It Happened
<root causes and contributing factors>

## How to Prevent It
<concrete prevention measures, monitoring improvements, process changes>
"""


def _get_groq() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(settings.hf_embedding_model)
    return _embedding_model


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def run_postmortem(state: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a blameless postmortem and persist the incident to Supabase.

    Reads:   incident_id, severity, raw_input, image_description, diagnosis, remediation
    Writes:  postmortem
    Side effect: upserts the full incident record to the incidents table
    """
    client = _get_groq()
    prompt = _POSTMORTEM_USER_TMPL.format(
        incident_id=state.get("incident_id", "unknown"),
        severity=state.get("severity", "unknown"),
        raw_input=state.get("raw_input", "")[:2000],
        image_description=state.get("image_description", "Not provided"),
        diagnosis=(state.get("diagnosis") or "No diagnosis")[:1500],
        remediation=(state.get("remediation") or "No remediation")[:1500],
    )

    logger.info("Generating postmortem for incident %s", state.get("incident_id"))

    completion = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _POSTMORTEM_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1024,
    )

    postmortem_text = completion.choices[0].message.content
    logger.info("Postmortem generated (%d chars)", len(postmortem_text))

    # Generate embedding from combined incident context for similarity search
    embed_text = (
        f"{state.get('raw_input', '')} {state.get('diagnosis', '')} {postmortem_text}"
    )
    model = _get_embedding_model()
    embedding = model.encode(embed_text, normalize_embeddings=True).tolist()

    # Persist to Supabase
    triage = state.get("triage_result") or {}
    title = (
        (triage.get("affected_services") or ["Unknown"])[:1][0]
        + f" — {state.get('severity', 'unknown')} incident"
    )

    await upsert_incident(
        incident_id=state["incident_id"],
        title=title,
        raw_input=state.get("raw_input") or "",
        image_description=state.get("image_description") or "",
        severity=state.get("severity") or "unknown",
        diagnosis=state.get("diagnosis") or "",
        remediation=state.get("remediation") or "",
        postmortem=postmortem_text,
        embedding=embedding,
    )

    logger.info("Incident %s persisted to Supabase", state["incident_id"])
    return {"postmortem": postmortem_text}


async def store_incident_without_postmortem(state: dict[str, Any]) -> dict[str, Any]:
    """
    Persist a critical incident to Supabase without generating a postmortem.
    Used on the fast path where postmortem is skipped for speed.
    """
    embed_text = f"{state.get('raw_input', '')} {state.get('diagnosis', '')} {state.get('remediation', '')}"
    model = _get_embedding_model()
    embedding = model.encode(embed_text, normalize_embeddings=True).tolist()

    triage = state.get("triage_result") or {}
    title = (
        (triage.get("affected_services") or ["Unknown"])[:1][0]
        + " — CRITICAL incident"
    )

    await upsert_incident(
        incident_id=state["incident_id"],
        title=title,
        raw_input=state.get("raw_input") or "",
        image_description=state.get("image_description") or "",
        severity="critical",
        diagnosis=state.get("diagnosis") or "",
        remediation=state.get("remediation") or "",
        postmortem="Postmortem skipped — critical fast path",
        embedding=embedding,
    )

    logger.info("Critical incident %s stored (no postmortem)", state["incident_id"])
    return {"postmortem": "Postmortem deferred for critical incident — prioritize remediation."}
