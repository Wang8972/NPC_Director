#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
app="$project_root/Builds/macOS/LastLight.app"
if [[ ! -d "$app" ]]; then
    echo "Builds/macOS/LastLight.app is missing. Run tools/build_macos.sh first." >&2
    exit 2
fi
executable_name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$app/Contents/Info.plist")"
executable="$app/Contents/MacOS/$executable_name"
fixtures="$app/Contents/Resources/QA"
game_python="$project_root/.venv/bin/python"
if ! "$game_python" -c 'import imageio_ffmpeg' 2>/dev/null; then
    "$game_python" -m pip install 'imageio-ffmpeg==0.6.0'
fi
for size in 1920x1080 1280x720 1440x900; do
    width="${size%x*}"
    height="${size#*x}"
    output="$project_root/artifacts/macos-$size"
    mkdir -p "$output"
    "$executable" --qa-capture "$fixtures" --qa-output "$output" \
        -screen-fullscreen 0 -screen-width "$width" -screen-height "$height" \
        -logFile "$output/player.log"
    "$game_python" tools/encode_player_captures.py "$output"
done
codesign --verify --deep --strict "$app"
echo "macOS Player QA complete under artifacts/macos-*"
