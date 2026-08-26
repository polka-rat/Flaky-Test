from Diagnoser.analyzer import analyze_runs
from Diagnoser.diagnoser import build_diagnosis_prompt, diagnose_mock
from Diagnoser.runner import RunResult


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
