from typing import Any

from app.analyzers.rules import ANALYZERS
from app.domain.analysis import AnalyzerResult


def run_analyzers(
    incident: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[AnalyzerResult]:
    results = [
        analyzer(incident, evidence)
        for _, analyzer in ANALYZERS
    ]
    return sorted(
        results,
        key=lambda item: (
            not item.matched,
            -item.confidence,
            item.analyzer,
        ),
    )


def primary_result(
    results: list[AnalyzerResult],
) -> AnalyzerResult | None:
    return next((item for item in results if item.matched), None)
