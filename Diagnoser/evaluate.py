"""Evaluate the agent across configured flaky-test cases."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
import json
from pathlib import Path

from Diagnoser.agent import run_agent
from Diagnoser.config import DEFAULT_GEMINI_MODEL
from Diagnoser.diagnoser import (
    build_mock_patch_instruction,
    diagnose_mock,
    diagnose_with_agent,
    patch_instruction_from_diagnosis,
)
from Diagnoser.schemas import EvaluationCase, EvaluationResult


class EvaluationConfigError(ValueError):
    """Raised when an evaluation JSON configuration is malformed."""


def load_evaluation_cases(config_path: str | Path) -> list[EvaluationCase]:
    """Load cases from one JSON file or every JSON file in a directory."""
    path = Path(config_path).expanduser().resolve()
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(path.glob("*.json"))
    else:
        raise FileNotFoundError(f"Evaluation config path does not exist: {path}")
    if not files:
        raise EvaluationConfigError(f"No JSON case files found in: {path}")

    cases: list[EvaluationCase] = []
    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise EvaluationConfigError(f"Invalid JSON in {file}: {error.msg}") from error
        entries = payload.get("cases") if isinstance(payload, dict) and "cases" in payload else [payload]
        if not isinstance(entries, list):
            raise EvaluationConfigError(f"'cases' must be a list in {file}")
        for index, entry in enumerate(entries, start=1):
            required = {"name", "repo_path", "test_id"}
            if not isinstance(entry, dict) or set(entry) != required or not all(
                isinstance(entry[key], str) for key in required
            ):
                raise EvaluationConfigError(
                    f"Case {index} in {file} must contain only string name, repo_path, and test_id"
                )
            cases.append(
                EvaluationCase(
                    name=entry["name"],
                    repo_path=(file.parent / entry["repo_path"]).resolve(),
                    test_id=entry["test_id"],
                )
            )
    return cases


def run_evaluation(
    cases: list[EvaluationCase],
    *,
    runs: int = 20,
    max_attempts: int = 3,
    timeout_seconds: float = 60.0,
    work_root: str | Path | None = None,
    mock_llm: bool = False,
    model: str = DEFAULT_GEMINI_MODEL,
    report: Callable[[str], None] = print,
) -> list[EvaluationResult]:
    """Run the closed loop for every case and return compact outcomes."""
    if not cases:
        raise ValueError("at least one evaluation case is required")

    outcomes: list[EvaluationResult] = []
    for number, case in enumerate(cases, start=1):
        report(f"\nEVALUATE {number}/{len(cases)}: {case.name}")
        if mock_llm:
            diagnosis_function = diagnose_mock
            patch_provider = lambda diagnosis, _: build_mock_patch_instruction(
                case.repo_path, diagnosis
            )
        else:
            diagnosis_function = partial(diagnose_with_agent, model=model)
            patch_provider = lambda diagnosis, _: patch_instruction_from_diagnosis(diagnosis)

        result = run_agent(
            case.repo_path, case.test_id, runs=runs, max_attempts=max_attempts,
            timeout_seconds=timeout_seconds, work_root=work_root,
            diagnose=diagnosis_function, patch_provider=patch_provider, report=report,
        )
        final_attempt = result.attempts[-1] if result.attempts else None
        outcomes.append(
            EvaluationResult(
                case_name=case.name,
                diagnosis_type=(final_attempt.diagnosis.diagnosis_type if final_attempt else None),
                confidence=(final_attempt.diagnosis.confidence if final_attempt else None),
                pre_fix_pass_rate=result.pre_fix_analysis.pass_rate,
                post_fix_pass_rate=(final_attempt.post_fix_analysis.pass_rate if final_attempt else None),
                verified_fixed=result.verified_fixed,
            )
        )
    return outcomes


def render_summary_table(results: list[EvaluationResult]) -> str:
    """Render a dependency-free fixed-width terminal summary table."""
    headers = ["Case", "Diagnosis", "Confidence", "Pre-fix", "Post-fix", "Verified"]
    rows = [
        [
            result.case_name,
            result.diagnosis_type or "n/a",
            f"{result.confidence:.0%}" if result.confidence is not None else "n/a",
            f"{result.pre_fix_pass_rate:.0%}",
            f"{result.post_fix_pass_rate:.0%}" if result.post_fix_pass_rate is not None else "n/a",
            "yes" if result.verified_fixed else "no",
        ]
        for result in results
    ]
    widths = [max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers)]
    divider = "-+-".join("-" * width for width in widths)
    format_row = lambda row: " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
    return "\n".join([format_row(headers), divider, *(format_row(row) for row in rows)])
