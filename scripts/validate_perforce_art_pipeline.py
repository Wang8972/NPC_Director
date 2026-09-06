from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_IGNORE = (
    "/Library/",
    "/Temp/",
    "/Obj/",
    "/Logs/",
    "/UserSettings/",
    "/Builds/",
    ".env",
)

LOCKED_BINARY_EXTENSIONS = (
    "fbx",
    "blend",
    "ma",
    "mb",
    "max",
    "psd",
    "psb",
    "tif",
    "tiff",
    "exr",
    "wav",
    "aiff",
    "mp3",
    "ogg",
    "mp4",
    "mov",
)

LOCKED_UNITY_EXTENSIONS = (
    "unity",
    "prefab",
    "asset",
    "controller",
    "overrideController",
    "anim",
    "mat",
)


def validate_pipeline(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    ignore = (root / "perforce/.p4ignore").read_text(encoding="utf-8")
    for value in REQUIRED_IGNORE:
        if value not in ignore:
            errors.append(f".p4ignore is missing {value}")

    typemap = (root / "perforce/typemap.p4").read_text(encoding="utf-8")
    for extension in LOCKED_BINARY_EXTENSIONS:
        if not re.search(rf"binary\+l\s+//\.\.\.\.{re.escape(extension)}\b", typemap):
            errors.append(f"typemap must lock binary .{extension}")
    for extension in LOCKED_UNITY_EXTENSIONS:
        if not re.search(rf"text\+l\s+//\.\.\.\.{re.escape(extension)}\b", typemap):
            errors.append(f"typemap must text-lock Unity .{extension}")
    if not re.search(r"text\s+//\.\.\.\.meta\b", typemap):
        errors.append("typemap must keep .meta as versioned text")

    ownership = json.loads((root / "perforce/ownership.json").read_text(encoding="utf-8"))
    git_paths = set(ownership["git"]["authoritative_paths"])
    p4_paths = set(ownership["perforce"]["authoritative_paths"])
    if git_paths & p4_paths:
        errors.append("Git and Perforce authoritative paths overlap")
    if "Assets/NPCDirectorClient/**" not in ownership["perforce"]["synced_read_only_paths"]:
        errors.append("Git-owned Unity Runtime must be read-only in Perforce")

    manifest = json.loads(
        (root / "data/vertical_slice/art_asset_manifest.json").read_text(encoding="utf-8")
    )
    categories = {item["category"] for item in manifest["asset_groups"]}
    required_categories = {"environment", "characters", "props", "animation", "audio", "vfx"}
    if categories != required_categories:
        errors.append(
            f"asset categories changed: expected={sorted(required_categories)} "
            f"actual={sorted(categories)}"
        )
    if any(item["license_status"] != "pending" for item in manifest["asset_groups"]):
        errors.append("new asset groups must start with pending license review")

    register_path = root / "data/vertical_slice/art_source_register.csv"
    with register_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        required = set(manifest["source_register_required_fields"])
        if not required <= headers:
            errors.append(f"source register missing fields: {sorted(required - headers)}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the VS2.5 Perforce art pipeline")
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate_pipeline(args.root)
    if errors:
        for error in errors:
            print(f"[VS2_5_P4] FAIL {error}")
        return 1
    print(
        "[VS2_5_P4] PASS ignore=7 binary_locks=17 unity_text_locks=7 "
        "ownership_split=true asset_groups=6"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
