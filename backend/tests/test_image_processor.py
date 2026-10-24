import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

for key in (
    "GROQ_API_KEY",
    "HUGGINGFACE_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
    "LANGCHAIN_API_KEY",
):
    os.environ.setdefault(key, "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion import image_processor as ip  # noqa: E402

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 24).decode()


def _patch_client(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        ip.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


def test_call_vision_api_uses_router_chat_format(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok text"}}]})

    _patch_client(monkeypatch, handler)
    assert asyncio.run(ip._call_vision_api(PNG_B64)) == "ok text"
    assert seen["url"].endswith("/chat/completions")
    assert seen["body"]["model"] == ip.settings.hf_vision_model
    image_part = seen["body"]["messages"][0]["content"][1]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_failed_analysis_is_not_cached(monkeypatch):
    cached = []

    async def fake_get(key):
        return None

    async def fake_set(key, value, ttl_seconds):
        cached.append(key)

    async def boom(image_b64):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ip, "cache_get", fake_get)
    monkeypatch.setattr(ip, "cache_set", fake_set)
    monkeypatch.setattr(ip, "_call_vision_api", boom)
    result = asyncio.run(ip.analyze_image(PNG_B64))
    assert result["description"] == "Image analysis unavailable"
    assert "provider down" in result["error"]
    assert cached == []


def test_image_mime_detects_jpeg():
    assert ip._image_mime(base64.b64encode(b"\xff\xd8\xff" + b"0" * 30).decode()) == "image/jpeg"
