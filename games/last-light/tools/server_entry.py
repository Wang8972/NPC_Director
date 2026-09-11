"""PyInstaller entry: backend only, credentials/config stay beside the release."""
import os
from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    release_root = Path(sys.executable).resolve().parent.parent
else:
    release_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(release_root / "backend"))

config = release_root / ".env"
if config.is_file():
    for line in config.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.replace("_", "").isalnum() and key.startswith(("LAST_LIGHT_", "NPC_DIRECTOR_", "OPENAI_")):
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))

if __name__ == "__main__":
    import argparse
    import uvicorn
    from last_light.api import app
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
