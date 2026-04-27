from __future__ import annotations
"""
LangGraph orchestration graph for SynthSense.

Node execution order:
  Normal path:   preprocess → triage → diagnose → remediate → postmortem → store
  Critical path: preprocess → triage → remediate → store  (skip diagnosis + postmortem)

The `astream()` method yields per-node output dicts, which the SSE endpoint
forwards to the frontend in real-time.
"""
import logging
import uuid
from typing import Any, AsyncIterator, TypedDict

from langgraph.graph import END, StateGraph

from agents.diagnosis_agent import run_diagnosis
from agents.postmortem_agent import run_postmortem, store_incident_without_postmortem
from agents.remediation_agent import run_remediation
from agents.triage_agent import run_triage
from ingestion.image_processor import analyze_image
from ingestion.log_processor import extract_log_entities

logger = logging.getLogger(__name__)


# ── State schema ──────────────────────────────────────────────────────────────

class IncidentState(TypedDict, total=False):
    incident_id: str
    raw_input: str
    image_b64: str           # optional base64 image
    image_description: str
    log_entities: dict
    severity: str
    triage_result: dict
    similar_incidents: list
    relevant_runbooks: list
    diagnosis: str
    diagnosis_result: dict
    remediation: str
    remediation_result: dict
    postmortem: str
    eval_scores: dict


# ── Node functions ────────────────────────────────────────────────────────────

async def _no_image() -> dict:
    return {"description": "No image provided", "detected_services": [], "error_codes": [], "anomalies": []}


async def preprocess_node(state: IncidentState) -> dict[str, Any]:
    """Run image analysis and log entity extraction in parallel."""
    import asyncio

    image_coro = analyze_image(state["image_b64"]) if state.get("image_b64") else _no_image()
    image_result, log_entities = await asyncio.gather(
        image_coro,
        extract_log_entities(state.get("raw_input", "")),
    )

    return {
        "image_description": image_result.get("description", ""),
        "log_entities": log_entities,
    }


async def triage_node(state: IncidentState) -> dict[str, Any]:
    return await run_triage(state)


async def diagnose_node(state: IncidentState) -> dict[str, Any]:
    return await run_diagnosis(state)


async def remediate_node(state: IncidentState) -> dict[str, Any]:
    return await run_remediation(state)


async def postmortem_node(state: IncidentState) -> dict[str, Any]:
    return await run_postmortem(state)


async def store_node(state: IncidentState) -> dict[str, Any]:
    """
    For critical incidents that skipped the postmortem node,
    this node persists the record with a deferred postmortem note.
    """
    return await store_incident_without_postmortem(state)


# ── Routing logic ─────────────────────────────────────────────────────────────

def route_after_triage(state: IncidentState) -> str:
    """Critical incidents skip diagnosis for faster time-to-remediation."""
    if state.get("severity") == "critical":
        logger.info("CRITICAL severity — fast path: skipping diagnosis")
        return "remediate"
    return "diagnose"


def route_after_remediate(state: IncidentState) -> str:
    """Critical incidents also skip postmortem and go straight to store."""
    if state.get("severity") == "critical":
        return "store"
    return "write_postmortem"


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph() -> Any:
    graph = StateGraph(IncidentState)

    graph.add_node("preprocess", preprocess_node)
    graph.add_node("triage", triage_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("remediate", remediate_node)
    graph.add_node("write_postmortem", postmortem_node)  # renamed: 'postmortem' is a state key
    graph.add_node("store", store_node)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "triage")

    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "diagnose": "diagnose",
            "remediate": "remediate",
        },
    )
    graph.add_edge("diagnose", "remediate")
    graph.add_conditional_edges(
        "remediate",
        route_after_remediate,
        {
            "write_postmortem": "write_postmortem",
            "store": "store",
        },
    )
    graph.add_edge("write_postmortem", END)
    graph.add_edge("store", END)

    return graph.compile()


# Module-level compiled graph — import this in other modules
incident_graph = build_graph()


# ── Public API ────────────────────────────────────────────────────────────────

async def stream_incident(initial_state: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """
    Run the incident pipeline and yield per-node progress events.
    Each yielded dict is safe to JSON-serialize and send as an SSE event.
    """
    incident_id = initial_state.get("incident_id") or str(uuid.uuid4())
    state: IncidentState = {**initial_state, "incident_id": incident_id}

    logger.info("Starting incident pipeline for %s", incident_id)

    async for chunk in incident_graph.astream(state):
        for node_name, node_output in chunk.items():
            # Filter out internal keys to keep SSE payloads small
            safe_output = {
                k: v
                for k, v in node_output.items()
                if k not in ("image_b64",) and not isinstance(v, (bytes, bytearray))
            }
            yield {
                "incident_id": incident_id,
                "agent": node_name,
                "status": "completed",
                "output": safe_output,
            }

    yield {"incident_id": incident_id, "agent": "done", "status": "completed", "output": {}}
    logger.info("Incident pipeline completed for %s", incident_id)


async def run_incident(initial_state: dict[str, Any]) -> IncidentState:
    """Run the full pipeline synchronously (collects all output)."""
    incident_id = initial_state.get("incident_id") or str(uuid.uuid4())
    state: IncidentState = {**initial_state, "incident_id": incident_id}
    result = await incident_graph.ainvoke(state)
    return result
