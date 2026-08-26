"""Coordinate the run, analyze, diagnose, patch, and verify loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import subprocess
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
    """Run the capped diagnose → patch-isolation → verify closed loop.

    ``patch_provider`` separates a diagnosis from an executable source edit.
    The future adapter will provide this exact replacement after its
    structured response has been validated. A clean Git repository uses one
    disposable worktree that is reset between attempts. Non-Git or dirty
    repositories use one copied fallback, with the target file restored from
    the original before each attempt.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    repository = Path(repo_path).expanduser().resolve()
    if not repository.is_dir():
        raise NotADirectoryError(f"Repository path does not exist: {repository}")
    run_workspace = _make_work_root(repository, work_root)
    isolated_repo, workspace_mode = _prepare_isolated_repository(
        repository, run_workspace, report
    )

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

        relative_file = _validated_relative_path(instruction.relative_file)
        _reset_isolated_repository(
            workspace_mode, repository, isolated_repo, relative_file
        )
        report(f"APPLY: writing a patched copy at {isolated_repo / relative_file}")
        patch_result = apply_replacement_to_copy(
            repository / relative_file,
            isolated_repo / relative_file,
            original_text=instruction.original_text,
            replacement_text=instruction.replacement_text,
        )
        report(f"VERIFY: executing {test_id} {runs} times against the patched copy")
        current_results = run_test_repeatedly(
            isolated_repo, test_id, runs=runs, timeout_seconds=timeout_seconds
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
                workspace_mode=workspace_mode,
            )

    report("NOT VERIFIED: no attempt achieved a 100% post-fix pass rate.")
    return AgentResult(
        pre_fix_analysis,
        tuple(attempts),
        verified_fixed=False,
        work_root=run_workspace,
        workspace_mode=workspace_mode,
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


def _prepare_isolated_repository(
    source: Path, work_root: Path, report: ProgressReporter
) -> tuple[Path, str]:
    """Create one reusable worktree when safe, otherwise one copied fallback."""
    destination = work_root / "repo"
    if _is_clean_git_repository(source):
        completed = _run_git(source, "worktree", "add", "--detach", str(destination), "HEAD")
        if completed.returncode == 0:
            report(f"ISOLATE: using one disposable Git worktree at {destination}")
            return destination, "git_worktree"
        report("ISOLATE: Git worktree creation failed; using the safe copy fallback.")
    else:
        report("ISOLATE: source is not a clean Git repository; using one safe copy fallback.")
    _copy_repository(source, destination)
    return destination, "copy"


def _reset_isolated_repository(
    mode: str, source: Path, isolated: Path, relative_file: Path
) -> None:
    """Restore the reusable isolation area to a baseline before an attempt."""
    if mode == "git_worktree":
        # This destructive reset is constrained to our disposable worktree,
        # never the user's source repository.
        reset = _run_git(isolated, "reset", "--hard", "HEAD")
        clean = _run_git(isolated, "clean", "-fd")
        if reset.returncode != 0 or clean.returncode != 0:
            raise RuntimeError("could not reset disposable Git worktree to baseline")
        return

    destination_file = isolated / relative_file
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / relative_file, destination_file)


def _is_clean_git_repository(repository: Path) -> bool:
    root = _run_git(repository, "rev-parse", "--show-toplevel")
    if root.returncode != 0 or Path(root.stdout.strip()).resolve() != repository:
        return False
    status = _run_git(repository, "status", "--porcelain")
    return status.returncode == 0 and not status.stdout.strip()


def _run_git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )


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
