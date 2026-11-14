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


def test_build_ncaam_page_survives_conflict_ledger(tmp_path: Path) -> None:
    from sharp_scout.site.ncaam_page import build_ncaam_page

    ledger = tmp_path / "ncaam_ledger.json"
    ledger.write_text(
        "{\n<<<<<<< Updated upstream\n  \"plays\": []\n=======\n  \"plays\": []\n>>>>>>> Stashed changes\n}\n"
    )
    docs = tmp_path / "docs"
    out = build_ncaam_page(docs_dir=docs, ledger_path=ledger)
    assert out.exists()
    html = out.read_text()
    assert "College Basketball" in html or "ncaam" in html.lower() or "No locked plays" in html
