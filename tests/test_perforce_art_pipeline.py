from __future__ import annotations

from pathlib import Path

from scripts.validate_perforce_art_pipeline import validate_pipeline


def test_perforce_art_pipeline_templates_are_complete() -> None:
    assert validate_pipeline() == []


def test_validator_rejects_missing_library_ignore(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "perforce").mkdir(parents=True)
    (root / "data/vertical_slice").mkdir(parents=True)
    source = Path("perforce")
    for name in (
        "typemap.p4",
        "ownership.json",
    ):
        (root / "perforce" / name).write_text(
            (source / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    ignore = (source / ".p4ignore").read_text(encoding="utf-8").replace("/Library/\n", "")
    (root / "perforce/.p4ignore").write_text(ignore, encoding="utf-8")
    for name in ("art_asset_manifest.json", "art_source_register.csv"):
        path = Path("data/vertical_slice") / name
        (root / path).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    assert ".p4ignore is missing /Library/" in validate_pipeline(root)
