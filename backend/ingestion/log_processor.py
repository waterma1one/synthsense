from __future__ import annotations
"""
Structured entity extraction from raw incident logs.
Uses Groq in JSON mode to pull out services, error codes, timestamps,
and other operationally relevant entities from free-form log text.
"""
import json
import logging
from typing import Any

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from config import settings

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None

_EXTRACTION_SYSTEM = (
    "You are an expert SRE log analyzer. "
    "Extract structured entities from the provided log text. "
    "Always respond with valid JSON."
)

_EXTRACTION_USER_TMPL = """
Analyze the following incident logs and extract entities.

LOGS:
{logs}

Return JSON with these exact keys:
{{
  "services": ["list of service/component names mentioned"],
  "error_codes": ["HTTP or application error codes found"],
  "exceptions": ["exception class names or error types"],
  "timestamps": ["ISO timestamps or time references"],
  "hosts": ["hostnames, IPs, or pod names"],
  "metrics": {{"key": "value pairs of numeric metrics found"}},
  "keywords": ["high-signal keywords: timeout, OOM, crash, 5xx, latency, etc."],
  "summary": "one sentence describing what the logs indicate"
}}
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
async def extract_log_entities(raw_logs: str) -> dict[str, Any]:
    """
    Parse raw log text and return structured entities.

    Args:
        raw_logs: Free-form log lines from an incident.

    Returns:
        Structured dict of extracted entities.
    """
    if not raw_logs or not raw_logs.strip():
        return {
            "services": [],
            "error_codes": [],
            "exceptions": [],
            "timestamps": [],
            "hosts": [],
            "metrics": {},
            "keywords": [],
            "summary": "No logs provided",
        }

    client = _get_groq()
    prompt = _EXTRACTION_USER_TMPL.format(logs=raw_logs[:4000])  # cap at 4k chars

    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=512,
        )
        content = completion.choices[0].message.content
        logger.debug("Log entity extraction raw response: %s", content[:200])
        entities = json.loads(content)
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("Log extraction failed: %s", exc)
        entities = {
            "services": [],
            "error_codes": [],
            "exceptions": [],
            "timestamps": [],
            "hosts": [],
            "metrics": {},
            "keywords": [],
            "summary": f"Extraction error: {exc}",
        }

    return entities
