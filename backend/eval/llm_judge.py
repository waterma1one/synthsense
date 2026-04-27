from __future__ import annotations
"""
LLM-as-judge scoring for SynthSense.
Uses Groq to score diagnosis quality on multiple dimensions:
accuracy, completeness, actionability, and specificity.
Complements RAGAS with dimensions that don't require ground truth labels.
"""
import json
import logging
from typing import Any

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = """You are an expert SRE evaluating an AI-generated incident diagnosis.
Score the diagnosis on four dimensions. Always respond with valid JSON."""

_JUDGE_USER_TMPL = """
## Incident Input
{incident_input}

## AI-Generated Diagnosis
{diagnosis}

## AI-Generated Remediation
{remediation}

Score the diagnosis on each dimension from 0.0 to 1.0:

- accuracy: Does the diagnosis correctly identify the likely root cause?
- completeness: Are all significant contributing factors covered?
- actionability: Does the remediation contain concrete, executable steps?
- specificity: Are service names, error codes, and metrics cited from the evidence?

Respond with JSON:
{{
  "accuracy": <float>,
  "completeness": <float>,
  "actionability": <float>,
  "specificity": <float>,
  "overall": <float — weighted average>,
  "critique": "<one sentence identifying the biggest weakness>"
}}
"""

_groq_client: AsyncGroq | None = None


def _get_groq() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    reraise=True,
)
async def judge_incident(
    incident_input: str,
    diagnosis: str,
    remediation: str,
) -> dict[str, Any]:
    """
    Score an incident diagnosis using Groq as the judge LLM.

    Returns:
        Dict with per-dimension scores and an overall critique.
    """
    client = _get_groq()
    prompt = _JUDGE_USER_TMPL.format(
        incident_input=incident_input[:2000],
        diagnosis=diagnosis[:1500],
        remediation=remediation[:1500],
    )

    completion = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=256,
    )

    content = completion.choices[0].message.content
    try:
        scores = json.loads(content)
        if "overall" not in scores:
            numeric = {k: v for k, v in scores.items() if isinstance(v, (int, float))}
            scores["overall"] = round(sum(numeric.values()) / len(numeric), 4) if numeric else 0.0
        return scores
    except json.JSONDecodeError:
        logger.error("Judge JSON parse failed: %s", content[:200])
        return {
            "accuracy": 0.0,
            "completeness": 0.0,
            "actionability": 0.0,
            "specificity": 0.0,
            "overall": 0.0,
            "critique": "Scoring failed",
        }
