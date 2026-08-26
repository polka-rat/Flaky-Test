"""Run a pytest target repeatedly in isolated subprocesses."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

from Diagnoser.schemas import RunResult

def run_test_repeatedly(
    repo_path: str | Path,
    test_id: str,
    *,
    runs: int = 20,
    timeout_seconds: float = 60.0,
) -> list[RunResult]:
    """Run ``test_id`` N times, using a new pytest process for every run.

    ``test_id`` is passed directly to pytest (for example,
    ``tests/test_widget.py::test_widget``).  A non-zero exit code is retained as
    test evidence instead of raising, allowing callers to compare every run.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")

    repository = Path(repo_path).expanduser().resolve()
    if not repository.is_dir():
        raise NotADirectoryError(f"Repository path does not exist: {repository}")

    command = (sys.executable, "-m", "pytest", test_id, "--tb=long", "-x")
    results: list[RunResult] = []

    for run_number in range(1, runs + 1):
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=repository,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            return_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            return_code = 124
            stdout = _as_text(error.stdout)
            stderr = _as_text(error.stderr) + (
                f"\nTimed out after {timeout_seconds:g} seconds."
            )

        results.append(
            RunResult(
                run_number=run_number,
                passed=return_code == 0,
                return_code=return_code,
                duration_seconds=time.perf_counter() - started,
                stdout=stdout,
                stderr=stderr,
                command=command,
            )
        )

    return results


def _as_text(value: str | bytes | None) -> str:
    """Normalize timeout output, which varies by Python/subprocess version."""
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
