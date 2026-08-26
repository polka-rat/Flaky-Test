"""Coordinate the run, analyze, diagnose, patch, and verify loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import uuid

from Diagnoser.analyzer import analyze_runs
from Diagnoser.diagnoser import diagnose_mock
from Diagnoser.patcher import apply_replacement_to_copy
from Diagnoser.runner import run_test_repeatedly
from Diagnoser.schemas import (
    AgentAttempt,
    AgentResult,
    AnalysisResult,
    Diagnosis,
    PatchInstruction,
    RunResult,
)


DiagnoseFunction = Callable[[list[RunResult], AnalysisResult], Diagnosis]
PatchProvider = Callable[[Diagnosis, int], PatchInstruction | None]
ProgressReporter = Callable[[str], None]


def run_agent(
    repo_path: str | Path,
    test_id: str,
    *,
    patch_provider: PatchProvider,
    runs: int = 20,
    max_attempts: int = 3,
    timeout_seconds: float = 60.0,
    work_root: str | Path | None = None,
    diagnose: DiagnoseFunction = diagnose_mock,
    report: ProgressReporter = print,
) -> AgentResult:
    """Run the capped diagnose → patch-copy → verify closed loop.

    ``patch_provider`` separates a diagnosis from an executable source edit.
    The future adapter will provide this exact replacement after its
    structured response has been validated. Every verification is performed in
    a newly copied repository, never against ``repo_path``.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    repository = Path(repo_path).expanduser().resolve()
    if not repository.is_dir():
        raise NotADirectoryError(f"Repository path does not exist: {repository}")
    run_workspace = _make_work_root(repository, work_root)

    report(f"RUN: executing {test_id} {runs} times in {repository}")
    current_results = run_test_repeatedly(
        repository, test_id, runs=runs, timeout_seconds=timeout_seconds
    )
    pre_fix_analysis = analyze_runs(current_results)
    report(
        "ANALYZE: "
        f"{pre_fix_analysis.passed_runs}/{pre_fix_analysis.total_runs} passed "
        f"({pre_fix_analysis.pass_rate:.0%}); signals={list(pre_fix_analysis.signals)}"
    )

    attempts: list[AgentAttempt] = []
    for attempt_number in range(1, max_attempts + 1):
        report(f"DIAGNOSE: attempt {attempt_number}/{max_attempts}")
        diagnosis = diagnose(current_results, analyze_runs(current_results))
        instruction = patch_provider(diagnosis, attempt_number)
        if instruction is None:
            report("APPLY: no exact patch was supplied; stopping safely.")
            break

        copied_repo = run_workspace / f"attempt-{attempt_number}" / "repo"
        _copy_repository(repository, copied_repo)
        relative_file = _validated_relative_path(instruction.relative_file)
        report(f"APPLY: writing a patched copy at {copied_repo / relative_file}")
        patch_result = apply_replacement_to_copy(
            repository / relative_file,
            copied_repo / relative_file,
            original_text=instruction.original_text,
            replacement_text=instruction.replacement_text,
        )
        report(f"VERIFY: executing {test_id} {runs} times against the patched copy")
        current_results = run_test_repeatedly(
            copied_repo, test_id, runs=runs, timeout_seconds=timeout_seconds
        )
        post_fix_analysis = analyze_runs(current_results)
        attempts.append(
            AgentAttempt(attempt_number, diagnosis, patch_result, post_fix_analysis)
        )
        report(
            "VERIFY: "
            f"{post_fix_analysis.passed_runs}/{post_fix_analysis.total_runs} passed "
            f"({post_fix_analysis.pass_rate:.0%})"
        )
        if post_fix_analysis.pass_rate == 1.0:
            report("VERIFIED: the copied patch passed every verification run.")
            return AgentResult(
                pre_fix_analysis,
                tuple(attempts),
                verified_fixed=True,
                work_root=run_workspace,
            )

    report("NOT VERIFIED: no attempt achieved a 100% post-fix pass rate.")
    return AgentResult(
        pre_fix_analysis,
        tuple(attempts),
        verified_fixed=False,
        work_root=run_workspace,
    )


def _make_work_root(repository: Path, work_root: str | Path | None) -> Path:
    base = (
        Path(work_root).expanduser().resolve()
        if work_root is not None
        else repository.parent / ".flaky-agent-work"
    )
    if _is_within(base, repository):
        raise ValueError("work_root must not be inside the source repository")
    destination = base / f"run-{uuid.uuid4().hex}"
    destination.mkdir(parents=True)
    return destination


def _copy_repository(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".flaky-agent-work"),
    )


def _validated_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("patch file must be a relative path within the repository")
    return path


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False
