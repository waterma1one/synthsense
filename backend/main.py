from __future__ import annotations
"""
FastAPI application entry point for SynthSense.
Wires together all API routes, adds middleware, and configures logging.
Start with: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import logging
import os
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings

# ── Configure structured logging ──────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    )
)
logger = logging.getLogger(__name__)

# Propagate LangSmith env vars so LangChain picks them up
os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
os.environ.setdefault("LANGCHAIN_TRACING_V2", str(settings.langchain_tracing_v2).lower())
os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SynthSense %s starting up…", settings.app_version)
    yield
    from memory.redis_cache import close as redis_close
    await redis_close()
    logger.info("SynthSense shutdown complete")


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="Multimodal incident intelligence platform powered by LangGraph + Groq.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

from api.incidents import router as incidents_router
from api.runbooks import router as runbooks_router
from api.evals import router as evals_router

app.include_router(incidents_router)
app.include_router(runbooks_router)
app.include_router(evals_router)


@app.get("/health", tags=["health"])
async def health_check():
    """Liveness probe — returns 200 if the server is running."""
    return {"status": "ok", "version": settings.app_version}
