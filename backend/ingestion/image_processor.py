from __future__ import annotations
"""
Multimodal image analysis for SynthSense.
Sends dashboard screenshots or error images to a vision model on the Hugging Face router
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


def _parse_vision_response(raw_text: str) -> dict[str, Any]:
    """Extract structured JSON from the model's free-form text output."""
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


def _image_mime(image_b64: str) -> str:
    head = base64.b64decode(image_b64[:32] + "=" * (-len(image_b64[:32]) % 4))
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _call_vision_api(image_b64: str) -> str:
    """Send image to a vision model through the Hugging Face router (OpenAI-style chat API)."""
    url = f"{settings.hf_api_base}/chat/completions"
    payload = {
        "model": settings.hf_vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _SRE_VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{_image_mime(image_b64)};base64,{image_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.huggingface_api_key}"},
        )
        response.raise_for_status()
        result = response.json()

    return result["choices"][0]["message"]["content"] or ""


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
        raw_text = await _call_vision_api(image_b64)
        logger.debug("Vision model raw response: %s", raw_text[:200])
        result = _parse_vision_response(raw_text)
    except Exception as exc:
        logger.error("Image analysis failed after retries: %s", exc)
        # Do not cache a failure: it would be served for the whole cache TTL.
        return {**_FALLBACK_RESULT, "error": str(exc)}

    await cache_set(cache_key, result, ttl_seconds=settings.image_cache_ttl)
    return result
