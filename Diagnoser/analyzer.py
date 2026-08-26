"""Derive deterministic flakiness signals from test-run evidence."""

from __future__ import annotations

from collections import Counter
import re

from Diagnoser.schemas import AnalysisResult, RunResult


_EXCEPTION_RE = re.compile(r"\b([A-Za-z_]\w*(?:Error|Exception))(?::|\s|$)")
_ASSERTION_RE = re.compile(r"^E\s+(assert .+)$", re.MULTILINE)


def analyze_runs(results: list[RunResult]) -> AnalysisResult:
    """Analyze repeated run evidence without making an LLM call."""
    if not results:
        raise ValueError("at least one RunResult is required")

    failures = [result for result in results if not result.passed]
    signatures = Counter(_failure_signature(result.output) for result in failures)
    exceptions = Counter(_exception_type(result.output) for result in failures)
    markers = _evidence_markers(failures)

    signals: list[str] = []
    if failures and len(failures) < len(results):
        signals.append("intermittent_outcomes")
    elif failures:
        signals.append("consistent_failure")
    else:
        signals.append("no_failures_observed")

    if len(exceptions) > 1:
        signals.append("different_exception_types")
    if len(signatures) > 1:
        signals.append("different_failure_signatures")
    if len(signatures) == 1 and failures:
        signals.append("repeated_same_failure_signature")
    if _fails_only_after_first_run(results):
        signals.append("fails_after_initial_pass")
    if "randomness" in markers:
        signals.append("randomness_marker_in_failure")

    passed_runs = len(results) - len(failures)
    return AnalysisResult(
        total_runs=len(results),
        passed_runs=passed_runs,
        failed_runs=len(failures),
        pass_rate=passed_runs / len(results),
        failure_signatures=dict(signatures),
        exception_types=dict(exceptions),
        signals=tuple(signals),
        evidence_markers=markers,
    )


def _failure_signature(output: str) -> str:
    """Extract a compact stable signature from a pytest failure transcript."""
    assertion = _ASSERTION_RE.search(output)
    if assertion:
        return re.sub(r"\b\d+\b", "<number>", assertion.group(1))
    exception = _exception_type(output)
    if exception != "UnknownFailure":
        return exception
    return "UnknownFailure"


def _exception_type(output: str) -> str:
    matches = _EXCEPTION_RE.findall(output)
    return matches[-1] if matches else "UnknownFailure"


def _fails_only_after_first_run(results: list[RunResult]) -> bool:
    """Flag a simple sequential pattern useful for order-dependency diagnosis."""
    return (
        len(results) > 1
        and results[0].passed
        and all(not result.passed for result in results[1:])
    )


def _evidence_markers(failures: list[RunResult]) -> tuple[str, ...]:
    corpus = "\n".join(result.output for result in failures).lower()
    markers: list[str] = []
    if any(term in corpus for term in ("random", "secrets.", "randbelow", "uuid")):
        markers.append("randomness")
    if any(term in corpus for term in ("timeout", "sleep(", "deadline")):
        markers.append("timing")
    if any(term in corpus for term in ("connectionerror", "requests.", "http", "socket")):
        markers.append("external_dependency")
    return tuple(markers)
