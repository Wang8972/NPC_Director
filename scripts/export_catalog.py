from __future__ import annotations

import json
from pathlib import Path

from npc_director.contracts import BodyAction, FacePreset


def catalog_payload() -> dict[str, object]:
    return {
        "version": "m0-v1",
        "body_actions": [action.value for action in BodyAction],
        "face_presets": [preset.value for preset in FacePreset],
    }


def main() -> None:
    output_path = Path("data/catalogs/performance_catalog.json")
    output_path.write_text(
        json.dumps(catalog_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
