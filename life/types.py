"""The types shared by the pipeline, the benchmark and the app. Frozen dataclasses, no logic."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Session:
    idx: int
    time: str  # ISO-8601, "YYYY-MM-DD HH:MM" (STALE's format); facts sort by this string
    turns: list[dict]  # {"role": "user" | "assistant", "content": str}


@dataclass(frozen=True)
class Fact:
    id: str
    subject: str
    attribute: str
    value: str
    time: str
    source_idx: int
    status: Literal["active", "stale"] = "active"
    invalidated_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Decision:
    old_id: str
    verdict: Literal["keep", "stale", "changed"]
    reason: str
    by: str  # id of the new fact that changed it (a stale Fact's invalidated_by)


@dataclass(frozen=True)
class PremiseReport:
    premises: list[str]
    stale: list[dict]  # {"premise", "fact_id", "invalidated_by", "reason"}


@dataclass(frozen=True)
class Answer:
    text: str
    premise_report: PremiseReport
    cost_usd: float


@dataclass(frozen=True)
class Instance:
    """STALE's record, field for field (arXiv 2605.06527; data CC BY 4.0)."""
    uid: str
    type: str
    M_old: str
    M_new: str
    explanation: str
    probing_queries: dict  # dim1_query, dim2_query, dim3_query
    haystack_session: list[list[dict]]
    relevant_session_index: list[int]
    timestamps: list[str]


@dataclass(frozen=True)
class EvalRow:
    uid: str
    type: str
    dim: str
    condition: str
    response: str
    correct: bool
    judge_model: str
    cost_usd: float
