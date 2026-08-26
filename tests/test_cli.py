from pathlib import Path

from Diagnoser import cli
from Diagnoser.schemas import AgentResult, AnalysisResult


def _result() -> AgentResult:
    analysis = AnalysisResult(2, 2, 0, 1.0, {}, {}, ("no_failures_observed",), ())
    return AgentResult(analysis, (), True, Path("work"), "copy")


def test_mock_cli_wires_the_offline_diagnoser(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_run_agent(*args, **kwargs):
        captured["kwargs"] = kwargs
        return _result()

    monkeypatch.setattr(cli, "run_agent", fake_run_agent)

    exit_code = cli.main([
        "diagnose", "demo_repo", "test_flaky_random.py::test_random_value_is_not_a_valid_correctness_signal",
        "--mock-llm", "--runs", "5",
    ])

    assert exit_code == 0
    assert captured["kwargs"]["diagnose"] is cli.diagnose_mock
    assert "offline mock" in capsys.readouterr().out


def test_real_cli_wires_the_gemini_patch_provider(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_agent(*args, **kwargs):
        captured["kwargs"] = kwargs
        return _result()

    monkeypatch.setattr(cli, "run_agent", fake_run_agent)

    exit_code = cli.main(["diagnose", "repo", "test.py::test_case", "--model", "chosen-model"])

    assert exit_code == 0
    assert captured["kwargs"]["diagnose"].keywords["model"] == "chosen-model"
