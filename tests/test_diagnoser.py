from Diagnoser.analyzer import analyze_runs
from Diagnoser.diagnoser import (
    build_diagnosis_prompt,
    build_mock_patch_instruction,
    diagnose_with_agent,
    diagnose_mock,
    patch_instruction_from_diagnosis,
)
from Diagnoser.schemas import Diagnosis, RunResult


def make_result(number: int, passed: bool, output: str = "") -> RunResult:
    return RunResult(number, passed, 0 if passed else 1, 0.1, output, "", ("pytest",))


def test_mock_diagnoses_randomness_and_extracts_location() -> None:
    results = [
        make_result(1, True),
        make_result(
            2, False,
            "src/test_token.py:17: AssertionError\nE assert secrets.randbelow(2) == 0",
        ),
    ]

    diagnosis = diagnose_mock(results, analyze_runs(results))

    assert diagnosis.diagnosis_type == "random_seed"
    assert diagnosis.confidence == 0.95
    assert diagnosis.target_file == "src/test_token.py"
    assert diagnosis.line_number == 17


def test_prompt_contains_all_runs_and_analysis() -> None:
    results = [make_result(1, True, "pass output"), make_result(2, False, "AssertionError")]

    prompt = build_diagnosis_prompt(results, analyze_runs(results))

    assert '"run_number": 1' in prompt
    assert '"run_number": 2' in prompt
    assert '"pass_rate": 0.5' in prompt


def test_mock_patch_instruction_is_limited_to_the_known_demo_assertion(tmp_path) -> None:
    source = tmp_path / "test_flaky_random.py"
    source.write_text(
        "import secrets\nassert secrets.randbelow(2) == 0\n", encoding="utf-8"
    )
    results = [
        make_result(
            1,
            False,
            f"{source.name}:2: AssertionError\nE assert secrets.randbelow(2) == 0",
        )
    ]

    instruction = build_mock_patch_instruction(tmp_path, diagnose_mock(results, analyze_runs(results)))

    assert instruction is not None
    assert instruction.relative_file == source.name
    assert instruction.replacement_text == "assert secrets.randbelow(2) in (0, 1)"


def test_gemini_diagnosis_uses_structured_response_and_returns_exact_patch() -> None:
    class FakeInteractions:
        def create(self, **kwargs):
            self.arguments = kwargs
            return type("Response", (), {"output_text": """{
                \"diagnosis_type\": \"timing_assumption\",
                \"confidence\": 0.8,
                \"target_file\": \"tests/test_wait.py\",
                \"line_number\": 11,
                \"rationale\": \"The run timed out.\",
                \"proposed_fix\": \"Wait for the event.\",
                \"original_text\": \"time.sleep(1)\",
                \"replacement_text\": \"event.wait(timeout=1)\"
            }"""})()

    class FakeClient:
        interactions = FakeInteractions()

    results = [make_result(1, False, "tests/test_wait.py:11: TimeoutError")]
    diagnosis = diagnose_with_agent(results, analyze_runs(results), client=FakeClient())

    assert diagnosis.diagnosis_type == "timing_assumption"
    assert diagnosis.confidence == 0.8
    instruction = patch_instruction_from_diagnosis(diagnosis)
    assert instruction is not None
    assert instruction.original_text == "time.sleep(1)"
    assert FakeClient.interactions.arguments["response_format"]["mime_type"] == "application/json"


def test_patch_instruction_refuses_diagnosis_without_exact_source() -> None:
    diagnosis = Diagnosis("unknown", 0.1, "test.py", 1, "insufficient", "inspect first")

    assert patch_instruction_from_diagnosis(diagnosis) is None
