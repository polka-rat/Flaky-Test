from pathlib import Path
import subprocess

from Diagnoser.agent import run_agent
from Diagnoser.schemas import PatchInstruction


def _create_target_repo(root: Path) -> Path:
    repository = root / "target_repo"
    repository.mkdir()
    (repository / "test_target.py").write_text(
        "TOKEN = 'bad'\n\ndef test_token():\n    assert TOKEN == 'good'\n",
        encoding="utf-8",
    )
    return repository


def _make_git_repository(repository: Path) -> None:
    subprocess.run(("git", "init"), cwd=repository, check=True, capture_output=True)
    subprocess.run(("git", "add", "."), cwd=repository, check=True, capture_output=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ),
        cwd=repository,
        check=True,
        capture_output=True,
    )


def test_agent_patches_only_a_copy_and_verifies_it(tmp_path: Path) -> None:
    repository = _create_target_repo(tmp_path)

    result = run_agent(
        repository,
        "test_target.py::test_token",
        runs=2,
        max_attempts=1,
        work_root=tmp_path / "work",
        patch_provider=lambda *_: PatchInstruction("test_target.py", "'bad'", "'good'"),
        report=lambda _: None,
    )

    assert result.verified_fixed
    assert result.pre_fix_analysis.pass_rate == 0.0
    assert result.attempts[0].post_fix_analysis.pass_rate == 1.0
    assert "TOKEN = 'bad'" in (repository / "test_target.py").read_text(encoding="utf-8")
    assert "TOKEN = 'good'" in result.attempts[0].patch_result.patched_file.read_text(
        encoding="utf-8"
    )
    assert result.workspace_mode == "copy"


def test_agent_stops_after_the_configured_attempt_limit(tmp_path: Path) -> None:
    repository = _create_target_repo(tmp_path)

    result = run_agent(
        repository,
        "test_target.py::test_token",
        runs=1,
        max_attempts=2,
        work_root=tmp_path / "work",
        patch_provider=lambda *_: PatchInstruction("test_target.py", "'bad'", "'still_bad'"),
        report=lambda _: None,
    )

    assert not result.verified_fixed
    assert len(result.attempts) == 2


def test_agent_reuses_one_git_worktree_for_a_clean_repository(tmp_path: Path) -> None:
    repository = _create_target_repo(tmp_path)
    _make_git_repository(repository)

    result = run_agent(
        repository,
        "test_target.py::test_token",
        runs=1,
        max_attempts=1,
        work_root=tmp_path / "work",
        patch_provider=lambda *_: PatchInstruction("test_target.py", "'bad'", "'good'"),
        report=lambda _: None,
    )

    assert result.verified_fixed
    assert result.workspace_mode == "git_worktree"
    assert (result.work_root / "repo" / ".git").is_file()
    assert "TOKEN = 'bad'" in (repository / "test_target.py").read_text(encoding="utf-8")
