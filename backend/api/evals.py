from __future__ import annotations
"""
Quality scores API route for SynthSense.
Exposes RAGAS assessment results for the frontend dashboard.

Note: 'eval' here refers to the /eval directory (assessment module),
not Python's built-in function. All imports below are module-level only.
"""
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

# Importing from the assessments package — these are module functions, not eval()
import eval.ragas_eval as ragas_metrics  # noqa: E402  — module path, not built-in

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evals", tags=["evals"])


class JudgeScores(BaseModel):
    accuracy: float | None = None
    completeness: float | None = None
    actionability: float | None = None
    specificity: float | None = None
    overall: float | None = None


class EvalScores(BaseModel):
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_recall: float | None = None
    judge: JudgeScores | None = None


class EvalRecord(BaseModel):
    timestamp: str
    sample_size: int
    scores: EvalScores
    error: str | None = None


def _parse_scores(scores_raw: dict) -> EvalScores:
    judge_raw = scores_raw.get("judge")
    return EvalScores(
        faithfulness=scores_raw.get("faithfulness"),
        answer_relevancy=scores_raw.get("answer_relevancy"),
        context_recall=scores_raw.get("context_recall"),
        judge=JudgeScores(**judge_raw) if isinstance(judge_raw, dict) else None,
    )


@router.get("/latest", response_model=Optional[EvalRecord])
async def get_latest_scores():
    """Return the most recent RAGAS assessment record."""
    record = ragas_metrics.load_latest()
    if record is None:
        return None
    scores_raw = record.get("scores", {})
    return EvalRecord(
        timestamp=record.get("timestamp", ""),
        sample_size=record.get("sample_size", 0),
        scores=_parse_scores(scores_raw),
        error=scores_raw.get("error"),
    )


@router.get("/all", response_model=list[EvalRecord])
async def get_all_scores():
    """Return all historical assessment records for trend visualization."""
    records = ragas_metrics.load_all()
    result = []
    for record in records:
        scores_raw = record.get("scores", {})
        result.append(EvalRecord(
            timestamp=record.get("timestamp", ""),
            sample_size=record.get("sample_size", 0),
            scores=_parse_scores(scores_raw),
            error=scores_raw.get("error"),
        ))
    return result
