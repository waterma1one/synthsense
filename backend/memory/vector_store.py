from __future__ import annotations
"""
Supabase pgvector integration for SynthSense.

Supabase SQL setup — run this once in the Supabase SQL editor before starting:

    create extension if not exists vector;

    create table incidents (
      id uuid primary key default gen_random_uuid(),
      title text,
      raw_input text,
      image_description text,
      severity text,
      diagnosis text,
      remediation text,
      postmortem text,
      embedding vector(384),
      created_at timestamptz default now()
    );

    create table runbook_chunks (
      id uuid primary key default gen_random_uuid(),
      source text,
      content text,
      embedding vector(384),
      created_at timestamptz default now()
    );

    create index on incidents using ivfflat (embedding vector_cosine_ops) with (lists = 100);
    create index on runbook_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

    -- RPC for incident similarity search
    create or replace function match_incidents(
      query_embedding vector(384),
      match_threshold float,
      match_count int
    )
    returns table (
      id uuid,
      title text,
      diagnosis text,
      remediation text,
      severity text,
      similarity float
    )
    language sql stable
    as $$
      select id, title, diagnosis, remediation, severity,
             1 - (embedding <=> query_embedding) as similarity
      from incidents
      where embedding is not null
        and 1 - (embedding <=> query_embedding) > match_threshold
      order by embedding <=> query_embedding
      limit match_count;
    $$;

    -- RPC for runbook chunk similarity search
    create or replace function match_runbook_chunks(
      query_embedding vector(384),
      match_threshold float,
      match_count int
    )
    returns table (
      id uuid,
      source text,
      content text,
      similarity float
    )
    language sql stable
    as $$
      select id, source, content,
             1 - (embedding <=> query_embedding) as similarity
      from runbook_chunks
      where embedding is not null
        and 1 - (embedding <=> query_embedding) > match_threshold
      order by embedding <=> query_embedding
      limit match_count;
    $$;
"""
import logging
from typing import Any
from uuid import UUID

from supabase import AClient, acreate_client
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings

logger = logging.getLogger(__name__)

_supabase_client: AClient | None = None


async def get_supabase() -> AClient:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = await acreate_client(settings.supabase_url, settings.supabase_key)
    return _supabase_client


# ── Incidents ─────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def upsert_incident(
    *,
    incident_id: str,
    title: str,
    raw_input: str,
    image_description: str,
    severity: str,
    diagnosis: str,
    remediation: str,
    postmortem: str,
    embedding: list[float],
) -> dict[str, Any]:
    """Insert or update an incident record with its embedding."""
    client = await get_supabase()
    payload = {
        "id": incident_id,
        "title": title,
        "raw_input": raw_input,
        "image_description": image_description,
        "severity": severity,
        "diagnosis": diagnosis,
        "remediation": remediation,
        "postmortem": postmortem,
        "embedding": embedding,
    }
    response = await client.table("incidents").upsert(payload).execute()
    logger.info("Upserted incident %s to Supabase", incident_id)
    return response.data[0] if response.data else {}


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    reraise=True,
)
async def search_similar_incidents(
    query_embedding: list[float],
    top_k: int = settings.top_k_incidents,
    threshold: float = settings.similarity_threshold,
) -> list[dict[str, Any]]:
    """Find the most semantically similar past incidents using cosine similarity."""
    client = await get_supabase()
    response = await client.rpc(
        "match_incidents",
        {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": top_k,
        },
    ).execute()
    results = response.data or []
    logger.info("Retrieved %d similar incidents", len(results))
    return results


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    reraise=True,
)
async def get_incident_by_id(incident_id: str) -> dict[str, Any] | None:
    """Fetch a single incident record by its UUID."""
    client = await get_supabase()
    response = (
        await client.table("incidents")
        .select("*")
        .eq("id", incident_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    reraise=True,
)
async def list_incidents(limit: int = 20) -> list[dict[str, Any]]:
    """List the most recent incidents."""
    client = await get_supabase()
    response = (
        await client.table("incidents")
        .select("id, title, severity, created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


# ── Runbook chunks ────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    reraise=True,
)
async def upsert_runbook_chunk(
    *,
    source: str,
    content: str,
    embedding: list[float],
) -> dict[str, Any]:
    """Insert a runbook chunk with its embedding."""
    client = await get_supabase()
    payload = {"source": source, "content": content, "embedding": embedding}
    response = await client.table("runbook_chunks").insert(payload).execute()
    return response.data[0] if response.data else {}


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    reraise=True,
)
async def search_runbook_chunks(
    query_embedding: list[float],
    top_k: int = settings.top_k_runbooks,
    threshold: float = settings.similarity_threshold,
) -> list[dict[str, Any]]:
    """Find the most relevant runbook chunks using cosine similarity."""
    client = await get_supabase()
    response = await client.rpc(
        "match_runbook_chunks",
        {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": top_k,
        },
    ).execute()
    results = response.data or []
    logger.info("Retrieved %d runbook chunks", len(results))
    return results


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=settings.retry_base_delay, min=1, max=30),
    reraise=True,
)
async def runbook_source_exists(source: str) -> bool:
    """Check if chunks from this source file have already been ingested."""
    client = await get_supabase()
    response = (
        await client.table("runbook_chunks")
        .select("id")
        .eq("source", source)
        .limit(1)
        .execute()
    )
    return bool(response.data)
