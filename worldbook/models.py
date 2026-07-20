from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

JSON = Any


@dataclass(frozen=True)
class UnfoldRequest:
    """A deterministic request to expose imported skeleton records.

    ``depth`` is an attention/deepening limit, not a travel or stamina rule.
    RFC-0 supports one administrative level per call.
    """

    depth: int = 1
    limit: int = 100


@dataclass(frozen=True)
class Problem:
    id: str
    region_id: str
    title: str
    statement: str
    status: str
    metric: str
    value: float
    unit: str
    source_id: str
    source_url: str
    observed_at: str


@dataclass(frozen=True)
class Observation:
    node_id: str
    metric: str
    value: float
    unit: str
    source_id: str
    observed_at: str
    observer_id: str
    note: str = ""


@dataclass(frozen=True)
class UnfoldResult:
    book: "WorldBook"
    nodes: tuple[Mapping[str, JSON], ...]
    event: Mapping[str, JSON] | None


@dataclass(frozen=True)
class Submission:
    book: "WorldBook"
    event: Mapping[str, JSON]


# Avoid a runtime import cycle while keeping useful annotations.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .book import WorldBook
