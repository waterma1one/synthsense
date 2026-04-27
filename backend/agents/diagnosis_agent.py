from __future__ import annotations
"""
Diagnosis agent for SynthSense.
Performs hybrid retrieval (similar past incidents + runbook chunks)
and feeds the retrieved context into Groq to produce a root-cause analysis.
All retrievals are traced to LangSmith for observability.
"""
import json
import logging
from typing import Any

from groq import AsyncGroq
from langsmith import traceable
from sentence_transformers import SentenceTransformer
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from config import settings
from memory.vector_store import search_similar_incidents, search_runbook_chunks

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None
_embedding_model: SentenceTransformer | None = None

_DIAGNOSIS_SYSTEM = """You are an expert SRE performing root-cause analysis.
Use the retrieved context from past incidents and runbooks to diagnose the current issue.
Be specific, technical, and evidence-based. Respond with valid JSON only."""

_DIAGNOSIS_USER_TMPL = """
## Current Incident
{incident_context}

## Similar Past Incidents
{similar_incidents}

## Relevant Runbook Sections
{runbook_chunks}

Diagnose the root cause and respond with JSON:
{{
  "root_cause": "<detailed root cause explanation>",
  "confidence": <float 0.0-1.0>,
  "evidence_from_runbooks": ["<specific runbook evidence points>"],
  "similar_past_incidents": [
    {{"id": "<uuid>", "similarity": <float>, "relevance": "<why this past incident is relevant>"}}
  ],
  "contributing_factors": ["<factor 1>", "<factor 2>"]
}}
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


@traceable(name="retrieve_context")
async def _retrieve_context(query: str) -> tuple[list, list]:
    """Embed the query and perform dual retrieval from incidents + runbooks."""
    model = _get_embedding_model()
    embedding = model.encode(query, normalize_embeddings=True).tolist()

    similar_incidents, runbook_chunks = await _parallel_retrieve(embedding)
    return similar_incidents, runbook_chunks


async def _parallel_retrieve(embedding: list[float]) -> tuple[list, list]:
    import asyncio
    incidents_task = asyncio.create_task(search_similar_incidents(embedding))
    runbooks_task = asyncio.create_task(search_runbook_chunks(embedding))
    incidents = await incidents_task
    runbooks = await runbooks_task
    return incidents, runbooks


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def run_diagnosis(state: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieve context and generate a root-cause diagnosis.

    Reads:   raw_input, image_description, log_entities, severity
    Writes:  diagnosis, similar_incidents, relevant_runbooks
    """
    incident_context = (
        f"Raw Input: {state.get('raw_input', '')[:2000]}\n"
        f"Image Analysis: {state.get('image_description', '')}\n"
        f"Log Entities: {json.dumps(state.get('log_entities', {}))}\n"
        f"Severity: {state.get('severity', 'unknown')}"
    )

    logger.info("Retrieving context for incident %s", state.get("incident_id"))
    similar_incidents, runbook_chunks = await _retrieve_context(incident_context)

    similar_str = json.dumps(
        [
            {
                "id": str(inc.get("id", "")),
                "severity": inc.get("severity", ""),
                "diagnosis": inc.get("diagnosis", "")[:500],
                "similarity": round(inc.get("similarity", 0), 3),
            }
            for inc in similar_incidents
        ],
        indent=2,
    )

    runbooks_str = "\n\n---\n\n".join(
        f"[Source: {chunk.get('source', 'unknown')}]\n{chunk.get('content', '')}"
        for chunk in runbook_chunks
    )

    prompt = _DIAGNOSIS_USER_TMPL.format(
        incident_context=incident_context,
        similar_incidents=similar_str or "No similar incidents found",
        runbook_chunks=runbooks_str or "No runbook sections retrieved",
    )

    client = _get_groq()
    completion = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _DIAGNOSIS_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=settings.groq_temperature,
        max_tokens=768,
    )

    content = completion.choices[0].message.content
    logger.debug("Diagnosis raw response: %s", content[:300])

    try:
        diagnosis_result = json.loads(content)
    except json.JSONDecodeError:
        diagnosis_result = {
            "root_cause": content,
            "confidence": 0.5,
            "evidence_from_runbooks": [],
            "similar_past_incidents": [],
            "contributing_factors": [],
        }

    logger.info(
        "Diagnosis complete: confidence=%.2f",
        diagnosis_result.get("confidence", 0),
    )

    return {
        "diagnosis": diagnosis_result.get("root_cause", ""),
        "diagnosis_result": diagnosis_result,
        "similar_incidents": similar_incidents,
        "relevant_runbooks": runbook_chunks,
    }
