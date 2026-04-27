from __future__ import annotations
"""
Remediation agent for SynthSense.
Generates a structured, actionable remediation plan from the diagnosis.
Uses chain-of-thought prompting at low temperature for deterministic output —
critical for ops scenarios where reproducible runbook steps matter.
"""
import json
import logging
from typing import Any

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from config import settings

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None

_REMEDIATION_SYSTEM = """You are an expert SRE creating an incident remediation playbook.
Generate actionable, specific steps ordered by urgency.
Think step by step before giving your final answer.
Respond with valid JSON only."""

_REMEDIATION_USER_TMPL = """
## Incident Diagnosis
{diagnosis}

## Severity
{severity}

## Affected Services
{affected_services}

## Relevant Runbook References
{runbook_refs}

Think through the remediation approach, then respond with JSON:
{{
  "immediate_steps": [
    "<step 1 — do this right now>",
    "<step 2>",
    "<step 3>"
  ],
  "investigation_steps": [
    "<deeper investigation action 1>",
    "<deeper investigation action 2>"
  ],
  "escalation_threshold": "<when to escalate: e.g., 'escalate if not resolved in 30 minutes'>",
  "estimated_resolution_time": "<realistic estimate, e.g., '15-30 minutes'>",
  "runbook_references": ["<runbook or doc reference>"],
  "prevention_notes": "<brief note on preventing recurrence>"
}}

Immediate steps must be specific shell commands or UI actions where possible.
"""


def _get_groq() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def run_remediation(state: dict[str, Any]) -> dict[str, Any]:
    """
    Build a step-by-step remediation plan from the diagnosis and triage output.

    Reads:   diagnosis, severity, triage_result, relevant_runbooks
    Writes:  remediation, remediation_result
    """
    triage = state.get("triage_result") or {}
    affected_services = triage.get("affected_services") or []
    runbooks = state.get("relevant_runbooks") or []
    runbook_refs = [chunk.get("source", "") for chunk in runbooks if chunk.get("source")]

    prompt = _REMEDIATION_USER_TMPL.format(
        diagnosis=(state.get("diagnosis") or "No diagnosis available")[:3000],
        severity=state.get("severity") or "unknown",
        affected_services=", ".join(affected_services) or "Unknown",
        runbook_refs=", ".join(set(runbook_refs)) or "None available",
    )

    client = _get_groq()
    logger.info("Generating remediation for incident %s", state.get("incident_id"))

    completion = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _REMEDIATION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,  # Low temperature for deterministic ops output
        max_tokens=1024,
    )

    content = completion.choices[0].message.content
    logger.debug("Remediation raw response: %s", content[:300])

    try:
        remediation_result = json.loads(content)
    except json.JSONDecodeError:
        remediation_result = {
            "immediate_steps": [content],
            "investigation_steps": [],
            "escalation_threshold": "Escalate immediately if uncertain",
            "estimated_resolution_time": "Unknown",
            "runbook_references": runbook_refs,
            "prevention_notes": "",
        }

    remediation_text = (
        "## Immediate Steps\n"
        + "\n".join(f"{i+1}. {s}" for i, s in enumerate(remediation_result.get("immediate_steps", [])))
        + "\n\n## Investigation Steps\n"
        + "\n".join(f"- {s}" for s in remediation_result.get("investigation_steps", []))
        + f"\n\n**Escalation:** {remediation_result.get('escalation_threshold', '')}"
        + f"\n**ETA:** {remediation_result.get('estimated_resolution_time', '')}"
    )

    logger.info("Remediation complete for incident %s", state.get("incident_id"))

    return {
        "remediation": remediation_text,
        "remediation_result": remediation_result,
    }
