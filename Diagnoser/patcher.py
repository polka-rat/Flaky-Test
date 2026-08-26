"""Apply a precise source replacement to a safe copy and render its diff."""

from __future__ import annotations

import difflib
from pathlib import Path

from Diagnoser.schemas import PatchResult

def apply_replacement_to_copy(
    source_file: str | Path,
    patched_file: str | Path,
    *,
    original_text: str,
    replacement_text: str,
) -> PatchResult:
    """Replace exactly one source fragment in a new copy of a file.

    The original file is never opened for writing. Requiring exactly one match
    prevents a broad LLM suggestion from silently changing several locations.
    """
    source = Path(source_file).expanduser().resolve()
    destination = Path(patched_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source file does not exist: {source}")
    if source == destination:
        raise ValueError("patched_file must be different from source_file")
    if not original_text:
        raise ValueError("original_text must not be empty")

    before = source.read_text(encoding="utf-8")
    occurrences = before.count(original_text)
    if occurrences != 1:
        raise ValueError(
            "replacement target must occur exactly once; "
            f"found {occurrences} occurrences"
        )

    after = before.replace(original_text, replacement_text, 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(after, encoding="utf-8")

    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(source),
            tofile=str(destination),
        )
    )
    return PatchResult(source_file=source, patched_file=destination, diff=diff)
