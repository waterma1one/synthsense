from __future__ import annotations
"""
Synthetic incident generator for SynthSense.
Produces 20 realistic incident scenarios across 5 categories using Groq.
These scenarios are used to seed the vector store and run eval pipelines
without needing real production incidents.

CLI usage:
    python -m eval.synthetic_data generate
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, INCIDENT_CATEGORIES

logger = logging.getLogger(__name__)

_SYNTHETIC_SYSTEM = """You are a senior SRE creating realistic test data.
Generate authentic-looking incident reports that match real production scenarios.
Always respond with valid JSON."""

_SYNTHETIC_USER_TMPL = """
Generate {count} realistic incident scenarios for the category: "{category}".

Each incident must include:
- title: short incident title
- raw_logs: 8-15 lines of realistic log output (with timestamps, levels, service names)
- severity: one of critical/high/medium/low
- expected_diagnosis: what an expert SRE would conclude is the root cause

Respond with a JSON array of {count} incident objects with exactly these keys:
title, raw_logs, severity, expected_diagnosis, category
"""


def _get_groq() -> AsyncGroq:
    return AsyncGroq(api_key=settings.groq_api_key)


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=2, max=30),
    reraise=True,
)
async def _generate_for_category(category: str, count: int = 4) -> list[dict]:
    client = _get_groq()
    prompt = _SYNTHETIC_USER_TMPL.format(category=category, count=count)

    completion = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _SYNTHETIC_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.8,   # Higher temperature for variety in synthetic data
        max_tokens=2048,
    )

    content = completion.choices[0].message.content
    parsed = json.loads(content)

    # Handle both {"incidents": [...]} and [...] response shapes
    if isinstance(parsed, list):
        return parsed
    for key in ("incidents", "data", "scenarios", "results"):
        if key in parsed and isinstance(parsed[key], list):
            return parsed[key]
    return list(parsed.values())[0] if parsed else []


async def generate_synthetic_incidents(output_path: str | None = None) -> list[dict]:
    """
    Generate 20 synthetic incidents (4 per category) and save to JSON.

    Returns the full list of generated incidents.
    """
    all_incidents: list[dict] = []
    counts_per_category = 4  # 5 categories × 4 = 20 total

    for category in INCIDENT_CATEGORIES:
        logger.info("Generating %d incidents for category: %s", counts_per_category, category)
        try:
            incidents = await _generate_for_category(category, counts_per_category)
            for inc in incidents:
                inc.setdefault("category", category)
            all_incidents.extend(incidents)
            logger.info("  → %d incidents generated", len(incidents))
        except Exception as exc:
            logger.error("Failed to generate incidents for %s: %s", category, exc)

    out = output_path or settings.synthetic_incidents_file
    Path(out).write_text(json.dumps(all_incidents, indent=2))
    logger.info("Saved %d synthetic incidents to %s", len(all_incidents), out)
    return all_incidents


def load_synthetic_incidents(path: str | None = None) -> list[dict]:
    """Load synthetic incidents from disk."""
    file_path = Path(path or settings.synthetic_incidents_file)
    if not file_path.exists():
        raise FileNotFoundError(
            f"Synthetic incidents file not found: {file_path}. "
            "Run: python -m eval.synthetic_data generate"
        )
    return json.loads(file_path.read_text())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        asyncio.run(generate_synthetic_incidents())
    else:
        print("Usage: python -m eval.synthetic_data generate")
        sys.exit(1)
