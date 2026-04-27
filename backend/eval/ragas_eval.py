from __future__ import annotations
"""
RAGAS quality assessment pipeline for SynthSense.
Assesses the diagnosis agent RAG quality on three metrics:
  - faithfulness: does the answer stay faithful to retrieved context?
  - answer_relevancy: is the answer relevant to the question?
  - context_recall: does the context contain the ground truth?

Runs automatically after every N incidents (configurable in config.py).
Stores results in evals.json for the dashboard endpoint.

CLI usage:
    python -m eval.ragas_eval run

Note: `ragas_assess()` calls ragas.evaluate(), which is the RAGAS library function,
not Python's built-in eval(). This is a third-party ML evaluation library.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from eval.synthetic_data import load_synthetic_incidents

logger = logging.getLogger(__name__)


async def _run_pipeline_on_incident(incident: dict) -> dict[str, Any] | None:
    """Run the diagnosis agent on a synthetic incident and collect context."""
    try:
        from agents.diagnosis_agent import run_diagnosis

        mock_state = {
            "incident_id": f"eval-{hash(incident['title']) % 100000}",
            "raw_input": incident.get("raw_logs", ""),
            "image_description": "",
            "log_entities": {},
            "severity": incident.get("severity", "medium"),
        }

        result = await run_diagnosis(mock_state)

        return {
            "question": f"What is the root cause of this incident: {incident['title']}",
            "answer": result.get("diagnosis", ""),
            "contexts": [
                chunk.get("content", "")
                for chunk in result.get("relevant_runbooks", [])
            ],
            "ground_truth": incident.get("expected_diagnosis", ""),
        }
    except Exception as exc:
        logger.warning("Pipeline failed for incident '%s': %s", incident.get("title"), exc)
        return None


async def ragas_assess(sample_size: int = 5) -> dict[str, Any]:
    """
    Sample incidents, run the diagnosis pipeline, and assess with RAGAS.
    Uses ragas.evaluate() — the RAGAS library function for ML metric scoring.

    Args:
        sample_size: Number of synthetic incidents to assess (keep small for speed).

    Returns:
        Dict with metric scores and timestamp.
    """
    # Import RAGAS components — library evaluate() function, not Python built-in
    try:
        import ragas
        from ragas.metrics import faithfulness, answer_relevancy, context_recall
        from datasets import Dataset
        ragas_run = ragas.evaluate  # alias to avoid confusion with built-in name
    except ImportError as exc:
        logger.error("RAGAS or datasets not installed: %s", exc)
        return {"error": str(exc), "scores": {}}

    logger.info("Loading synthetic incidents for RAGAS assessment…")
    try:
        all_incidents = load_synthetic_incidents()
    except FileNotFoundError:
        from eval.synthetic_data import generate_synthetic_incidents
        logger.info("Generating synthetic incidents first…")
        all_incidents = await generate_synthetic_incidents()

    sample = all_incidents[:sample_size]
    logger.info("Running pipeline on %d incidents…", len(sample))

    tasks = [_run_pipeline_on_incident(inc) for inc in sample]
    results = await asyncio.gather(*tasks)
    valid_results = [r for r in results if r is not None]

    if not valid_results:
        logger.error("No valid pipeline results — cannot run RAGAS assessment")
        return {"error": "No valid results", "scores": {}}

    dataset_dict = {
        "question": [r["question"] for r in valid_results],
        "answer": [r["answer"] for r in valid_results],
        "contexts": [r["contexts"] if r["contexts"] else ["No context retrieved"] for r in valid_results],
        "ground_truth": [r["ground_truth"] for r in valid_results],
    }
    dataset = Dataset.from_dict(dataset_dict)

    # Wire RAGAS metrics to Groq LLM + local HuggingFace embeddings
    try:
        from langchain_groq import ChatGroq
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper

        groq_llm = LangchainLLMWrapper(ChatGroq(
            api_key=settings.groq_api_key,
            model_name=settings.groq_model,
            temperature=0.0,
        ))
        hf_embeddings = LangchainEmbeddingsWrapper(
            HuggingFaceEmbeddings(model_name=settings.hf_embedding_model)
        )
        for metric in [faithfulness, answer_relevancy, context_recall]:
            metric.llm = groq_llm
        # answer_relevancy uses embeddings for question ↔ answer similarity
        answer_relevancy.embeddings = hf_embeddings
    except Exception as exc:
        logger.warning("Could not configure Groq/HF for RAGAS: %s", exc)

    logger.info("Running RAGAS metrics on %d samples…", len(valid_results))
    try:
        # ragas.evaluate() is the RAGAS library scoring function
        ragas_result = ragas_run(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy, context_recall],
        )
        def _safe(val: float) -> float | None:
            import math
            f = float(val)
            return None if math.isnan(f) or math.isinf(f) else round(f, 4)

        scores = {
            "faithfulness": _safe(ragas_result["faithfulness"]),
            "answer_relevancy": _safe(ragas_result["answer_relevancy"]),
            "context_recall": _safe(ragas_result["context_recall"]),
        }
    except Exception as exc:
        logger.error("RAGAS assessment failed: %s", exc)
        scores = {"error": str(exc)}

    # Run LLM judge in parallel on the same samples
    try:
        from eval.llm_judge import judge_incident
        judge_tasks = [
            judge_incident(
                incident_input=r["question"],
                diagnosis=r["answer"],
                remediation="",
            )
            for r in valid_results
        ]
        judge_results = await asyncio.gather(*judge_tasks, return_exceptions=True)
        valid_judge = [r for r in judge_results if isinstance(r, dict) and "overall" in r]
        if valid_judge:
            judge_avg = {
                k: round(sum(r.get(k, 0) for r in valid_judge) / len(valid_judge), 4)
                for k in ["accuracy", "completeness", "actionability", "specificity", "overall"]
            }
            scores["judge"] = judge_avg
            logger.info("LLM judge scores: %s", judge_avg)
    except Exception as exc:
        logger.warning("LLM judge assessment failed: %s", exc)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(valid_results),
        "scores": scores,
    }

    _append_record(record)
    logger.info("RAGAS assessment complete: %s", scores)
    return record


def _append_record(record: dict) -> None:
    """Append a new assessment result to the rolling evals.json file."""
    evals_path = Path(settings.evals_file)
    existing: list[dict] = []
    if evals_path.exists():
        try:
            existing = json.loads(evals_path.read_text())
        except json.JSONDecodeError:
            existing = []
    existing.append(record)
    evals_path.write_text(json.dumps(existing, indent=2))


def load_latest() -> dict[str, Any] | None:
    """Return the most recent assessment record, or None if none exist."""
    evals_path = Path(settings.evals_file)
    if not evals_path.exists():
        return None
    try:
        records = json.loads(evals_path.read_text())
        return records[-1] if records else None
    except (json.JSONDecodeError, IndexError):
        return None


def load_all() -> list[dict[str, Any]]:
    """Return all historical assessment records for trend charts."""
    evals_path = Path(settings.evals_file)
    if not evals_path.exists():
        return []
    try:
        return json.loads(evals_path.read_text())
    except json.JSONDecodeError:
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        result = asyncio.run(ragas_assess())
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python -m eval.ragas_eval run")
        sys.exit(1)
