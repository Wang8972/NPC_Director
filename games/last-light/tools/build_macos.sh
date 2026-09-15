#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
unity_path="${1:-${UNITY_PATH:-}}"
if [[ -z "$unity_path" ]]; then
    for candidate in /Applications/Unity/Hub/Editor/*/Unity.app/Contents/MacOS/Unity \
        "$HOME"/Applications/Unity/Hub/Editor/*/Unity.app/Contents/MacOS/Unity; do
        if [[ -x "$candidate" ]]; then unity_path="$candidate"; break; fi
    done
fi
cd "$project_root"
if [[ ! -x "$unity_path" ]]; then
    echo "Unity editor not found: $unity_path" >&2
    exit 2
fi
"$project_root/tools/setup_macos.sh"
game_python="$project_root/.venv/bin/python"
mkdir -p artifacts runtime Builds/macOS
"$game_python" -m pytest -q
"$game_python" -m PyInstaller --noconfirm --clean --onefile --name last-light-server \
    --paths backend --collect-all last_light --collect-all npc_director --collect-all agents \
    --add-data "$project_root/backend/last_light/director_data:last_light/director_data" \
    --collect-all tiktoken --collect-all tiktoken_ext --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on \
    --distpath runtime --workpath artifacts/pyinstaller --specpath artifacts tools/server_entry.py
chmod +x runtime/last-light-server
codesign --verify --strict runtime/last-light-server
"$game_python" tools/generate_presentation_fixtures.py
"$unity_path" -batchmode -nographics -quit -projectPath "$project_root" \
    -executeMethod LastLight.Editor.BuildTools.ValidateAssets \
    -logFile "$project_root/artifacts/unity-macos-import.log"
"$unity_path" -batchmode -nographics -quit -projectPath "$project_root" \
    -executeMethod LastLight.Editor.BuildTools.BuildMacOS \
    -logFile "$project_root/artifacts/unity-macos-build.log"
app="$project_root/Builds/macOS/LastLight.app"
resources="$app/Contents/Resources"
mkdir -p "$resources/runtime" "$resources/QA" "$resources/Docs"
cp runtime/last-light-server "$resources/runtime/last-light-server-bin"
cp tools/last-light-server-macos "$resources/runtime/last-light-server"
chmod +x "$resources/runtime/last-light-server" "$resources/runtime/last-light-server-bin"
cp .env.example "$resources/.env.example"
config_dir="$HOME/Library/Application Support/LastLight/余灯 · Last Light"
mkdir -p "$config_dir"
if [[ ! -f "$config_dir/.env" ]]; then cp .env.example "$config_dir/.env"; fi
cp Docs/WINDOWS.md "$resources/Docs/BUILD_AND_TEST.md"
cp Docs/ASSET_LICENSES.md "$resources/Docs/ASSET_LICENSES.md"
cp artifacts/presentation/fixtures/*.json "$resources/QA/"
codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"
echo "Built: $app"
