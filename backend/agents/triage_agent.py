from __future__ import annotations
"""
Triage agent for SynthSense.
Zero-shot severity classification using Groq in JSON mode.
Combines image analysis, log entities, and raw incident text to
produce a structured triage decision in a single LLM call.
"""
import json
import logging
from typing import Any

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from config import settings, SEVERITY_LEVELS

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None

_TRIAGE_SYSTEM = """You are a senior SRE performing incident triage.
Classify the severity of the incident based on all available context.
Always respond with valid JSON only — no markdown, no explanation outside JSON."""

_TRIAGE_USER_TMPL = """
Analyze this incident and classify its severity.

## Raw Incident Input
{raw_input}

## Image / Dashboard Analysis
{image_description}

## Log Entities Extracted
{log_entities}

Respond with JSON using exactly these keys:
{{
  "severity": "<critical|high|medium|low>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation of severity decision>",
  "affected_services": ["<service names>"]
}}

Severity guidelines:
- critical: service down, data loss risk, security breach, complete outage
- high: significant degradation, >10% error rate, major feature broken
- medium: partial degradation, single non-critical service affected
- low: minor issue, cosmetic, isolated error with low impact
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
async def run_triage(state: dict[str, Any]) -> dict[str, Any]:
    """
    Classify incident severity and identify affected services.

    Reads:   raw_input, image_description, log_entities
    Writes:  severity (+ triage_result for full structured output)
    """
    client = _get_groq()

    log_entities_str = json.dumps(state.get("log_entities", {}), indent=2)
    prompt = _TRIAGE_USER_TMPL.format(
        raw_input=state.get("raw_input", "")[:3000],
        image_description=state.get("image_description", "Not provided"),
        log_entities=log_entities_str,
    )

    logger.info("Running triage for incident %s", state.get("incident_id"))

    completion = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _TRIAGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=256,
    )

    content = completion.choices[0].message.content
    logger.debug("Triage raw response: %s", content)

    try:
        triage = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Triage JSON parse failed, defaulting to high severity")
        triage = {
            "severity": "high",
            "confidence": 0.5,
            "reasoning": "Triage parse error — defaulting to high severity",
            "affected_services": [],
        }

    # Validate severity value
    if triage.get("severity") not in SEVERITY_LEVELS:
        triage["severity"] = "high"

    logger.info(
        "Triage complete: severity=%s confidence=%.2f",
        triage["severity"],
        triage.get("confidence", 0),
    )

    return {
        "severity": triage["severity"],
        "triage_result": triage,
    }
