from __future__ import annotations
"""
Runbook PDF ingestion pipeline for SynthSense.
Uses LlamaIndex to split PDFs into overlapping chunks, generates embeddings
with BAAI/bge-small-en via sentence-transformers, then upserts to Supabase.
Deduplication prevents re-ingesting the same file on restart.
"""
import logging
import tempfile
from pathlib import Path

from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter
from sentence_transformers import SentenceTransformer
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from memory.vector_store import upsert_runbook_chunk, runbook_source_exists

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 50

_embedding_model: SentenceTransformer | None = None


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading embedding model %s…", settings.hf_embedding_model)
        _embedding_model = SentenceTransformer(settings.hf_embedding_model)
    return _embedding_model


async def _embed(text: str) -> list[float]:
    model = _get_embedding_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


async def ingest_pdf(pdf_bytes: bytes, filename: str) -> dict:
    """
    Chunk a runbook PDF and upsert all chunks into Supabase with embeddings.

    Args:
        pdf_bytes: Raw PDF file content.
        filename: Original filename — used as the deduplication key.

    Returns:
        Summary dict with chunk_count and skipped status.
    """
    if await runbook_source_exists(filename):
        logger.info("Runbook '%s' already ingested — skipping", filename)
        return {"filename": filename, "chunk_count": 0, "skipped": True}

    # Write to temp file so LlamaIndex can read it
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / filename
        pdf_path.write_bytes(pdf_bytes)

        reader = SimpleDirectoryReader(input_dir=tmpdir, required_exts=[".pdf"])
        documents = reader.load_data()

    splitter = SentenceSplitter(chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP)
    nodes = splitter.get_nodes_from_documents(documents)

    logger.info("Ingesting %d chunks from '%s'", len(nodes), filename)
    chunk_count = 0

    for node in nodes:
        text = node.get_content()
        if not text.strip():
            continue
        embedding = await _embed(text)
        await upsert_runbook_chunk(source=filename, content=text, embedding=embedding)
        chunk_count += 1

    logger.info("Finished ingesting '%s': %d chunks stored", filename, chunk_count)
    return {"filename": filename, "chunk_count": chunk_count, "skipped": False}
