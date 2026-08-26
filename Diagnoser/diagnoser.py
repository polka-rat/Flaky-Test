"""Build structured diagnoses from flaky-test evidence."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
from typing import Any
from Diagnoser.schemas import AnalysisResult, Diagnosis, RunResult
from Diagnoser.schemas import PatchInstruction
from Diagnoser.config import DEFAULT_GEMINI_MODEL 

_LOCATION_RE = re.compile(r"([\w./\\-]+\.py):(\d+):")



class DiagnosisError(RuntimeError):
    """Raised when Gemini cannot provide a valid structured diagnosis."""


_DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis_type": {
            "type": "string",
            "enum": [
                "race_condition", "shared_state", "timing_assumption",
                "test_order_dependency", "external_dependency", "random_seed", "unknown",
            ],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "target_file": {"type": ["string", "null"]},
        "line_number": {"type": ["integer", "null"]},
        "rationale": {"type": "string"},
        "proposed_fix": {"type": "string"},
        "original_text": {"type": ["string", "null"]},
        "replacement_text": {"type": ["string", "null"]},
    },
    "required": [
        "diagnosis_type", "confidence", "target_file", "line_number", "rationale",
        "proposed_fix", "original_text", "replacement_text",
    ],
    "additionalProperties": False,
}


def build_diagnosis_prompt(
    results: list[RunResult], analysis: AnalysisResult
) -> str:
    """Build the complete evidence prompt for a future LLM diagnosis call.

    Every run is included: passing runs establish intermittency, while failures
    supply tracebacks. This avoids drawing a conclusion from one cherry-picked
    error transcript.
    """
    evidence = {
        "analysis": asdict(analysis),
        "runs": [
            {
                "run_number": result.run_number,
                "passed": result.passed,
                "return_code": result.return_code,
                "duration_seconds": round(result.duration_seconds, 4),
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in results
        ],
    }
    schema = {
        "diagnosis_type": "race_condition | shared_state | timing_assumption | test_order_dependency | external_dependency | random_seed | unknown",
        "confidence": "number from 0.0 to 1.0",
        "target_file": "path string or null",
        "line_number": "integer or null",
        "rationale": "evidence-based explanation",
        "proposed_fix": "specific code-change recommendation",
        "original_text": "exact source snippet to replace, or null if unsafe to patch",
        "replacement_text": "replacement source snippet, or null if unsafe to patch",
    }
    return (
        "You are diagnosing a flaky pytest test. Classify the root cause using "
        " the supplied evidence. Return JSON matching this schema exactly:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Evidence from every isolated run:\n"
        f"{json.dumps(evidence, indent=2)}"
    )


def diagnose_with_agent(
    results: list[RunResult],
    analysis: AnalysisResult,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_GEMINI_MODEL,
    client: Any | None = None,
) -> Diagnosis:
    """Request one schema-constrained diagnosis from Gemini.

    The SDK is imported only for a real request, preserving offline mock mode.
    Tests can pass a lightweight fake ``client`` and never require credentials.
    """
    if client is None:
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise DiagnosisError(
                "GEMINI_API_KEY is required for Gemini diagnosis; use mock mode otherwise"
            )
        try:
            from google import genai
        except ImportError as error:
            raise DiagnosisError(
                "google-genai is not installed; install requirements.txt first"
            ) from error
        client = genai.Client(api_key=key)

    try:
        interaction = client.interactions.create(
            model=model,
            input=build_diagnosis_prompt(results, analysis),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _DIAGNOSIS_SCHEMA,
            },
        )
        payload = json.loads(interaction.output_text)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise DiagnosisError("Gemini returned an unreadable diagnosis response") from error
    return _diagnosis_from_payload(payload)


def patch_instruction_from_diagnosis(diagnosis: Diagnosis) -> PatchInstruction | None:
    """Convert a validated model response into an executable exact patch."""
    if (
        not diagnosis.target_file
        or diagnosis.original_text is None
        or diagnosis.replacement_text is None
    ):
        return None
    return PatchInstruction(
        relative_file=diagnosis.target_file,
        original_text=diagnosis.original_text,
        replacement_text=diagnosis.replacement_text,
    )


def diagnose_mock(results: list[RunResult], analysis: AnalysisResult) -> Diagnosis:
    """Produce a deterministic diagnosis for offline development and demos.

    This deliberately uses only analyzer evidence and trace text; it makes no
    network request and is not presented as an LLM result.
    """
    if not results:
        raise ValueError("at least one RunResult is required")

    target_file, line_number = _find_failure_location(results)
    corpus = "\n".join(result.output for result in results if not result.passed).lower()

    if "randomness" in analysis.evidence_markers:
        return Diagnosis(
            diagnosis_type="random_seed",
            confidence=0.95,
            target_file=target_file,
            line_number=line_number,
            rationale=(
                "Passing and failing isolated runs contain randomness markers, "
                "so the assertion depends on an uncontrolled random value."
            ),
            proposed_fix=(
                "Replace the random-dependent assertion with a deterministic "
                "assertion, or inject a seeded random-number generator."
            ),
        )
    if "external_dependency" in analysis.evidence_markers:
        return Diagnosis(
            "external_dependency", 0.85, target_file, line_number,
            "Failure output refers to an external network or service dependency.",
            "Mock the external service or make the test use a controlled local fixture.",
        )
    if "timing" in analysis.evidence_markers or "timeout" in corpus:
        return Diagnosis(
            "timing_assumption", 0.8, target_file, line_number,
            "Failure evidence contains timing or timeout markers.",
            "Synchronize on an observable condition instead of using fixed sleeps or deadlines.",
        )
    if "fails_after_initial_pass" in analysis.signals:
        return Diagnosis(
            "test_order_dependency", 0.7, target_file, line_number,
            "The first isolated run passed while every later run failed.",
            "Reset shared state in setup/teardown and avoid mutable module-level test state.",
        )
    return Diagnosis(
        "unknown", 0.25, target_file, line_number,
        "The collected evidence does not contain a reliable signature for a supported cause.",
        "Collect more runs and inspect the repeated traceback before changing source code.",
    )


def build_mock_patch_instruction(
    repo_path: str | Path, diagnosis: Diagnosis
) -> PatchInstruction | None:
    """Return an exact safe patch for the intentionally small demo fixture.

    This is not a general source-code generator. It recognizes only the demo's
    known invalid random assertion, allowing the offline loop to demonstrate
    diagnosis, safe patching, and verification before a Gemini key is used.
    """
    if diagnosis.diagnosis_type != "random_seed" or not diagnosis.target_file:
        return None

    repository = Path(repo_path).expanduser().resolve()
    relative_file = Path(diagnosis.target_file)
    if relative_file.is_absolute() or ".." in relative_file.parts:
        return None
    source_file = repository / relative_file
    if not source_file.is_file():
        return None

    original = "assert secrets.randbelow(2) == 0"
    if source_file.read_text(encoding="utf-8").count(original) != 1:
        return None
    return PatchInstruction(
        relative_file=relative_file.as_posix(),
        original_text=original,
        replacement_text="assert secrets.randbelow(2) in (0, 1)",
    )


def _find_failure_location(results: list[RunResult]) -> tuple[str | None, int | None]:
    for result in results:
        if result.passed:
            continue
        match = _LOCATION_RE.search(result.output)
        if match:
            return Path(match.group(1)).as_posix(), int(match.group(2))
    return None, None


def _diagnosis_from_payload(payload: object) -> Diagnosis:
    if not isinstance(payload, dict):
        raise DiagnosisError("Gemini diagnosis must be a JSON object")
    required = set(_DIAGNOSIS_SCHEMA["required"])
    if set(payload) != required:
        raise DiagnosisError("Gemini diagnosis has missing or unexpected fields")

    diagnosis_type = payload["diagnosis_type"]
    confidence = payload["confidence"]
    allowed_types = _DIAGNOSIS_SCHEMA["properties"]["diagnosis_type"]["enum"]
    if diagnosis_type not in allowed_types:
        raise DiagnosisError("Gemini returned an unsupported diagnosis type")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise DiagnosisError("Gemini confidence must be a number from 0 to 1")
    for field in ("target_file", "original_text", "replacement_text"):
        if payload[field] is not None and not isinstance(payload[field], str):
            raise DiagnosisError(f"Gemini field {field} must be a string or null")
    if payload["line_number"] is not None and (
        isinstance(payload["line_number"], bool) or not isinstance(payload["line_number"], int)
    ):
        raise DiagnosisError("Gemini line_number must be an integer or null")
    for field in ("rationale", "proposed_fix"):
        if not isinstance(payload[field], str):
            raise DiagnosisError(f"Gemini field {field} must be a string")

    return Diagnosis(
        diagnosis_type=diagnosis_type,
        confidence=float(confidence),
        target_file=payload["target_file"],
        line_number=payload["line_number"],
        rationale=payload["rationale"],
        proposed_fix=payload["proposed_fix"],
        original_text=payload["original_text"],
        replacement_text=payload["replacement_text"],
    )
