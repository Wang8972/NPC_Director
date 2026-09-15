#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"
python_bin="${1:-$(command -v python3)}"
if [[ -z "$python_bin" ]]; then
    echo "Python 3.11 or newer is required." >&2
    exit 2
fi
"$python_bin" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if [[ ! -x .venv/bin/python ]]; then
    "$python_bin" -m venv .venv
fi
game_python="$project_root/.venv/bin/python"
if ! "$game_python" -c 'import npc_director' 2>/dev/null; then
    if compgen -G 'vendor/wheels/npc_director-*.whl' >/dev/null; then
        "$game_python" -m pip install --find-links vendor/wheels 'npc-director==0.3.0'
    else
        echo "Missing vendored NPC Director wheel." >&2
        exit 2
    fi
fi
if ! "$game_python" -c 'import pytest, pytest_asyncio' 2>/dev/null; then
    "$game_python" -m pip install 'pytest>=8.3,<10' 'pytest-asyncio>=0.25,<2'
fi
if ! "$game_python" -c 'import PyInstaller' 2>/dev/null; then
    "$game_python" -m pip install 'pyinstaller>=6.12,<7'
fi
if [[ ! -f .env ]]; then
    cp .env.example .env
fi
echo "macOS backend environment is ready."
