#!/usr/bin/env python3
"""Launch the game service with a local installed or adjacent NPC Director."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
for adjacent in (ROOT.parents[1] / "src", ROOT.parent / "npc-director" / "src"):
    if (adjacent / "npc_director").is_dir():
        sys.path.insert(0, str(adjacent))
        break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    # Configuration is plain data; never shell-source a settings file.
    config = ROOT / ".env"
    if config.is_file():
        for line in config.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key.replace("_", "").isalnum() and key.startswith(("NPC_DIRECTOR_", "LAST_LIGHT_", "OPENAI_")):
                os.environ.setdefault(key, value)
    if args.data_dir:
        os.environ["LAST_LIGHT_DATA_DIR"] = args.data_dir
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("缺少后端依赖，请先运行 tools/setup_windows.ps1 或用已安装 npc-director 的 Python 启动。")
    uvicorn.run("last_light.api:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
