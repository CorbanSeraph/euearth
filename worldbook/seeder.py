from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .models import Problem

MAX_PROBLEMS_PER_REGION = 10


def _problem(region: Mapping[str, Any], metric: str, title: str, statement: str) -> Problem:
    evidence = region["properties"]["metrics"][metric]
    key = f"{region['id']}|{metric}|{evidence['observed_at']}|{evidence['value']}"
    problem_id = "problem:" + hashlib.sha256(key.encode()).hexdigest()[:24]
    return Problem(
        id=problem_id,
        region_id=region["id"],
        title=title,
        statement=statement,
        status="open",
        metric=metric,
        value=float(evidence["value"]),
        unit=evidence["unit"],
        source_id=evidence["source_id"],
        source_url=evidence["source_url"],
        observed_at=evidence["observed_at"],
    )


def seed_problems(region: Mapping[str, Any]) -> tuple[Problem, ...]:
    """Seed only threshold-backed questions; silence is better than filler."""

    metrics = region.get("properties", {}).get("metrics", {})
    candidates: list[Problem] = []
    density = metrics.get("population_density")
    if density and float(density["value"]) >= 150:
        candidates.append(_problem(
            region, "population_density", "Measure high-density service pressure",
            "Identify which public-service capacity is measurably lagging population density; withdraw if no capacity metric supports the gap.",
        ))
    growth = metrics.get("population_change_annual")
    if growth and float(growth["value"]) <= 0:
        candidates.append(_problem(
            region, "population_change_annual", "Explain stagnant or declining population",
            "Test the leading demographic drivers with newer component data; withdraw if the trend is revised away.",
        ))
    return tuple(sorted(candidates, key=lambda p: p.id)[:MAX_PROBLEMS_PER_REGION])
