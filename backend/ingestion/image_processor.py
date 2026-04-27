from __future__ import annotations
"""
Multimodal image analysis for SynthSense.
Sends dashboard screenshots or error images to HuggingFace's LLaVA model
and returns structured descriptions of anomalies, errors, and metrics.
Results are cached in Upstash Redis by image hash to avoid redundant API calls.
"""
import base64
import hashlib
import json
import logging
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config import settings
from memory.redis_cache import cache_get, cache_set

logger = logging.getLogger(__name__)

_SRE_VISION_PROMPT = (
    "You are an SRE analyzing a system dashboard or error screenshot. "
    "Describe what you see including: any error messages, metric anomalies, "
    "service names, HTTP status codes, and anything that looks abnormal. "
    "Be specific and technical. "
    "Respond in JSON with keys: description, detected_services, error_codes, anomalies."
)

_FALLBACK_RESULT: dict[str, Any] = {
    "description": "Image analysis unavailable",
    "detected_services": [],
    "error_codes": [],
    "anomalies": [],
}


def _hash_image(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_llava_response(raw_text: str) -> dict[str, Any]:
    """Extract structured JSON from LLaVA's free-form text output."""
    try:
        # Try to find a JSON block in the response
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: treat entire response as description
    return {
        "description": raw_text.strip(),
        "detected_services": [],
        "error_codes": re.findall(r"\b[45]\d{2}\b", raw_text),
        "anomalies": [],
    }


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _call_llava_api(image_b64: str) -> str:
    """Send image to HuggingFace LLaVA via Inference API."""
    url = f"{settings.hf_api_base}/{settings.hf_vision_model}"
    payload = {
        "inputs": {
            "prompt": _SRE_VISION_PROMPT,
            "image": image_b64,
        },
        "parameters": {"max_new_tokens": 512, "temperature": 0.1},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.huggingface_api_key}"},
        )
        # 503 means model is loading — tenacity will retry
        if response.status_code == 503:
            logger.warning("HuggingFace model loading, will retry…")
            response.raise_for_status()
        response.raise_for_status()
        result = response.json()

    if isinstance(result, list) and result:
        return result[0].get("generated_text", "")
    if isinstance(result, dict):
        return result.get("generated_text", str(result))
    return str(result)


async def analyze_image(
    image_source: str,
    *,
    is_url: bool = False,
) -> dict[str, Any]:
    """
    Analyze a dashboard screenshot or error image.

    Args:
        image_source: Base64-encoded image bytes or a public URL.
        is_url: Set True when image_source is a URL rather than base64.

    Returns:
        Structured dict with description, detected_services, error_codes, anomalies.
    """
    if is_url:
        # Download image to get consistent cache key
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(image_source)
            resp.raise_for_status()
            image_bytes = resp.content
        image_b64 = base64.b64encode(image_bytes).decode()
    else:
        image_bytes = base64.b64decode(image_source)
        image_b64 = image_source

    cache_key = f"img:{_hash_image(image_bytes)}"
    cached = await cache_get(cache_key)
    if cached:
        logger.info("Image analysis served from cache")
        return cached

    try:
        raw_text = await _call_llava_api(image_b64)
        logger.debug("LLaVA raw response: %s", raw_text[:200])
        result = _parse_llava_response(raw_text)
    except Exception as exc:
        logger.error("Image analysis failed after retries: %s", exc)
        result = {**_FALLBACK_RESULT, "error": str(exc)}

    await cache_set(cache_key, result, ttl_seconds=settings.image_cache_ttl)
    return result
