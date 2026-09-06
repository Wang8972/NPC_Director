from __future__ import annotations

import argparse
import json
from pathlib import Path

from npc_director.prototype.content_catalog import (
    DEFAULT_CATALOG_PATH,
    load_prototype_content_catalog,
)

DEFAULT_OUTPUT = Path(
    "unity/NPCDirectorClient/Resources/VerticalSliceContentCatalog.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the vertical-slice catalog for Unity")
    parser.add_argument("--input", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = load_prototype_content_catalog(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            catalog.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"[VS1_CATALOG_EXPORT] version={catalog.catalog_version} "
        f"npcs={len(catalog.npc_profiles)} objects={len(catalog.object_ids)} "
        f"facts={len(catalog.facts)} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
