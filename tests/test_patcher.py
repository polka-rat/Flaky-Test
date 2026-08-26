from pathlib import Path

import pytest

from Diagnoser.patcher import apply_replacement_to_copy


def test_applies_exact_replacement_to_copy_and_keeps_source_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "test_example.py"
    copy = tmp_path / "patched" / "test_example.py"
    source.write_text("def test_value():\n    assert value == random_value\n", encoding="utf-8")

    result = apply_replacement_to_copy(
        source,
        copy,
        original_text="assert value == random_value",
        replacement_text="assert value == expected_value",
    )

    assert "random_value" in source.read_text(encoding="utf-8")
    assert "expected_value" in copy.read_text(encoding="utf-8")
    assert result.source_file == source.resolve()
    assert result.patched_file == copy.resolve()
    assert "-    assert value == random_value" in result.diff
    assert "+    assert value == expected_value" in result.diff


def test_rejects_ambiguous_replacement(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("assert flag\nassert flag\n", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly once"):
        apply_replacement_to_copy(
            source,
            tmp_path / "copy.py",
            original_text="assert flag",
            replacement_text="assert True",
        )


def test_rejects_an_attempt_to_overwrite_the_source(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("assert flag\n", encoding="utf-8")

    with pytest.raises(ValueError, match="different"):
        apply_replacement_to_copy(
            source,
            source,
            original_text="assert flag",
            replacement_text="assert True",
        )
