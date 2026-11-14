from pathlib import Path

from sharp_scout.ncaam.runner import _file_has_conflict_markers


def test_detects_standard_and_stash_markers(tmp_path: Path) -> None:
    clean = tmp_path / "clean.json"
    clean.write_text('{"plays": []}\n')
    assert _file_has_conflict_markers(clean) is False

    marked = tmp_path / "conflict.json"
    marked.write_text(
        "{\n<<<<<<< Updated upstream\n  \"a\": 1\n=======\n  \"a\": 2\n>>>>>>> Stashed changes\n}\n"
    )
    assert _file_has_conflict_markers(marked) is True

    missing = tmp_path / "nope.json"
    assert _file_has_conflict_markers(missing) is False
