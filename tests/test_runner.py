from pathlib import Path

import pytest

from Diagnoser.runner import run_test_repeatedly


def test_runs_target_in_fresh_processes_and_captures_output(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_passes():\n    assert 2 + 2 == 4\n", encoding="utf-8"
    )

    results = run_test_repeatedly(tmp_path, "test_sample.py::test_passes", runs=2)

    assert [result.passed for result in results] == [True, True]
    assert [result.run_number for result in results] == [1, 2]
    assert all("1 passed" in result.stdout for result in results)
    assert all(result.duration_seconds > 0 for result in results)


def test_rejects_zero_runs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        run_test_repeatedly(tmp_path, "test_missing.py", runs=0)
