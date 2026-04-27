from __future__ import annotations
"""
Upstash Redis REST client for short-term caching in SynthSense.
Uses the HTTP REST API rather than TCP sockets, which works in any environment.
"""
import json
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=settings.upstash_redis_rest_url,
            headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
            timeout=10.0,
        )
    return _http_client


def _build_key(key: str) -> str:
    return f"{settings.cache_key_prefix}:{key}"


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=15),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def cache_get(key: str) -> Any | None:
    """Retrieve a cached value by key. Returns None on cache miss."""
    client = _get_http_client()
    full_key = _build_key(key)
    try:
        response = await client.get(f"/get/{full_key}")
        response.raise_for_status()
        data = response.json()
        raw = data.get("result")
        if raw is None:
            logger.debug("Cache miss: %s", full_key)
            return None
        logger.debug("Cache hit: %s", full_key)
        return json.loads(raw)
    except httpx.HTTPStatusError as exc:
        logger.warning("Redis GET failed for %s: %s", full_key, exc)
        return None


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=15),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def cache_set(key: str, value: Any, ttl_seconds: int = settings.image_cache_ttl) -> bool:
    """Store a value with an optional TTL (seconds). Returns True on success."""
    client = _get_http_client()
    full_key = _build_key(key)
    serialized = json.dumps(value)
    try:
        # Upstash REST: /set/<key>/<value>?ex=<ttl>
        response = await client.post(
            f"/set/{full_key}",
            params={"ex": ttl_seconds},
            content=serialized,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        logger.debug("Cached %s (TTL=%ds)", full_key, ttl_seconds)
        return True
    except httpx.HTTPStatusError as exc:
        logger.warning("Redis SET failed for %s: %s", full_key, exc)
        return False


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=15),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def cache_delete(key: str) -> bool:
    """Delete a cached key. Returns True if the key existed."""
    client = _get_http_client()
    full_key = _build_key(key)
    try:
        response = await client.get(f"/del/{full_key}")
        response.raise_for_status()
        deleted = response.json().get("result", 0)
        return deleted > 0
    except httpx.HTTPStatusError as exc:
        logger.warning("Redis DEL failed for %s: %s", full_key, exc)
        return False


async def cache_increment(key: str) -> int:
    """Atomically increment a counter. Used for tracking incident count for eval triggers."""
    client = _get_http_client()
    full_key = _build_key(key)
    response = await client.get(f"/incr/{full_key}")
    response.raise_for_status()
    return response.json().get("result", 0)


async def close() -> None:
    """Gracefully close the HTTP client."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
