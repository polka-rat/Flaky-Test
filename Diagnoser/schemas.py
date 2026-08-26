"""Shared data models passed between Flaky Test Diagnoser components.

runner -> analyzer -> diagnoser -> patcher -> agent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


DiagnosisType = Literal[
    "race_condition",
    "shared_state",
    "timing_assumption",
    "test_order_dependency",
    "external_dependency",
    "random_seed",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class RunResult:
    """Evidence captured from one clean pytest process."""

    run_number: int
    passed: bool
    return_code: int
    duration_seconds: float
    stdout: str
    stderr: str
    command: tuple[str, ...]

    @property
    def output(self) -> str:
        """Combined pytest output, preserving stderr when it is present."""
        return f"{self.stdout}\n{self.stderr}".strip()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """A reproducible summary of patterns found across repeated test runs."""

    total_runs: int
    passed_runs: int
    failed_runs: int
    pass_rate: float
    failure_signatures: dict[str, int]
    exception_types: dict[str, int]
    signals: tuple[str, ...]
    evidence_markers: tuple[str, ...]

    @property
    def is_flaky(self) -> bool:
        """Whether this batch contains both passing and failing executions."""
        return self.passed_runs > 0 and self.failed_runs > 0


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """A machine-readable root-cause and fix recommendation."""

    diagnosis_type: DiagnosisType
    confidence: float
    target_file: str | None
    line_number: int | None
    rationale: str
    proposed_fix: str
    original_text: str | None = None
    replacement_text: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation for reporting or APIs."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PatchResult:
    """The copied file and reviewable diff produced by one patch attempt."""

    source_file: Path
    patched_file: Path
    diff: str


@dataclass(frozen=True, slots=True)
class PatchInstruction:
    """An exact replacement that can be applied safely by the patcher."""

    relative_file: str
    original_text: str
    replacement_text: str


@dataclass(frozen=True, slots=True)
class AgentAttempt:
    """One diagnose, patch, and post-fix verification cycle."""

    number: int
    diagnosis: Diagnosis
    patch_result: PatchResult
    post_fix_analysis: AnalysisResult


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Final evidence from the closed-loop agent run."""

    pre_fix_analysis: AnalysisResult
    attempts: tuple[AgentAttempt, ...]
    verified_fixed: bool
    work_root: Path
    workspace_mode: Literal["git_worktree", "copy"]


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One repository and pytest target included in a batch evaluation."""

    name: str
    repo_path: Path
    test_id: str


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Resume-friendly outcome for one evaluated flaky-test case."""

    case_name: str
    diagnosis_type: str | None
    confidence: float | None
    pre_fix_pass_rate: float
    post_fix_pass_rate: float | None
    verified_fixed: bool
