import json
from pathlib import Path

from Diagnoser import evaluate
from Diagnoser.schemas import (
    AgentAttempt,
    AgentResult,
    AnalysisResult,
    Diagnosis,
    EvaluationCase,
    PatchResult,
)


def test_loads_cases_from_a_folder_and_resolves_relative_repositories(tmp_path: Path) -> None:
    config_dir = tmp_path / "cases"
    config_dir.mkdir()
    (config_dir / "case.json").write_text(
        json.dumps({"name": "case-one", "repo_path": "../repo", "test_id": "test.py::test_one"}),
        encoding="utf-8",
    )

    cases = evaluate.load_evaluation_cases(config_dir)

    assert cases[0].name == "case-one"
    assert cases[0].repo_path == (tmp_path / "repo").resolve()


def test_runs_evaluation_and_renders_summary(monkeypatch, tmp_path: Path) -> None:
    analysis = AnalysisResult(2, 2, 0, 1.0, {}, {}, (), ())
    diagnosis = Diagnosis("random_seed", 0.9, "test.py", 1, "random", "seed it")
    patch = PatchResult(tmp_path / "a", tmp_path / "b", "")
    attempt = AgentAttempt(1, diagnosis, patch, analysis)
    agent_result = AgentResult(analysis, (attempt,), True, tmp_path / "work", "copy")
    monkeypatch.setattr(evaluate, "run_agent", lambda *args, **kwargs: agent_result)
    cases = [EvaluationCase("demo", tmp_path, "test.py::test_case")]

    results = evaluate.run_evaluation(cases, mock_llm=True, report=lambda _: None)

    assert results[0].verified_fixed
    assert results[0].diagnosis_type == "random_seed"
    assert "random_seed" in evaluate.render_summary_table(results)
