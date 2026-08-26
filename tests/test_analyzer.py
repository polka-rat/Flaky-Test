from Diagnoser.analyzer import analyze_runs
from Diagnoser.runner import RunResult


def make_result(number: int, passed: bool, output: str = "") -> RunResult:
    return RunResult(number, passed, 0 if passed else 1, 0.1, output, "", ("pytest",))


def test_detects_intermittent_random_failure() -> None:
    analysis = analyze_runs([
        make_result(1, True),
        make_result(2, False, "E assert secrets.randbelow(2) == 0\nAssertionError"),
        make_result(3, True),
    ])

    assert analysis.is_flaky
    assert analysis.pass_rate == 2 / 3
    assert "intermittent_outcomes" in analysis.signals
    assert "randomness" in analysis.evidence_markers


def test_detects_different_exception_types() -> None:
    analysis = analyze_runs([
        make_result(1, False, "ValueError: bad input"),
        make_result(2, False, "TimeoutError: too slow"),
    ])

    assert "different_exception_types" in analysis.signals
    assert analysis.exception_types == {"ValueError": 1, "TimeoutError": 1}
