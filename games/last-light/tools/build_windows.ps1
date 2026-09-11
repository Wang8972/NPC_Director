param([string]$UnityPath = "C:\Program Files\Unity\Hub\Editor\6000.0.62f1\Editor\Unity.exe", [switch]$SkipSetup)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
if (-not (Test-Path $UnityPath)) { throw "Unity 6000.0.62f1 not found. Pass -UnityPath with the installed Editor executable." }
if (-not $SkipSetup) { & (Join-Path $PSScriptRoot "setup_windows.ps1") }
$GamePython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
if (-not (Test-Path $GamePython)) { throw "Run setup_windows.ps1 first." }
New-Item -ItemType Directory -Force artifacts,Builds/Windows,runtime | Out-Null
& $GamePython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Offline tests failed; no release produced." }
& $GamePython -m PyInstaller --noconfirm --clean --onefile --name last-light-server `
    --paths backend --collect-all last_light --collect-all npc_director --collect-all agents `
    --collect-all tiktoken --collect-all tiktoken_ext --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on `
    --distpath runtime --workpath artifacts/pyinstaller --specpath artifacts tools/server_entry.py
if ($LASTEXITCODE -ne 0) { throw "Backend build failed." }
& $GamePython tools/generate_presentation_fixtures.py
if ($LASTEXITCODE -ne 0) { throw "Presentation fixture generation failed." }
# Two invocations allow an input-system setting change to take effect after Editor restart.
$ImportArgs = "-batchmode -nographics -quit -projectPath `"$ProjectRoot`" -executeMethod LastLight.Editor.BuildTools.ValidateAssets -logFile `"$ProjectRoot/artifacts/unity-import.log`""
$ImportProcess = Start-Process -FilePath $UnityPath -ArgumentList $ImportArgs -Wait -PassThru
if ($ImportProcess.ExitCode -ne 0) { throw "Unity import/asset validation failed. See artifacts/unity-import.log." }
$BuildArgs = "-batchmode -nographics -quit -projectPath `"$ProjectRoot`" -executeMethod LastLight.Editor.BuildTools.BuildWindows -logFile `"$ProjectRoot/artifacts/unity-build.log`""
$BuildProcess = Start-Process -FilePath $UnityPath -ArgumentList $BuildArgs -Wait -PassThru
if ($BuildProcess.ExitCode -ne 0) { throw "Unity build failed. See artifacts/unity-build.log." }
$Release = Join-Path $ProjectRoot "Builds/Windows"
New-Item -ItemType Directory -Force "$Release/runtime","$Release/QA","$Release/Docs" | Out-Null
Copy-Item runtime/last-light-server.exe "$Release/runtime/last-light-server.exe" -Force
Copy-Item .env.example "$Release/.env.example" -Force
Copy-Item Docs/WINDOWS.md "$Release/Docs/WINDOWS.md" -Force
Copy-Item Docs/ASSET_LICENSES.md "$Release/Docs/ASSET_LICENSES.md" -Force
if (Test-Path artifacts/presentation/fixtures) {
    Copy-Item artifacts/presentation/fixtures/*.json "$Release/QA/" -Force
}
Write-Host "Built: $Release/LastLight.exe. Configure .env next to it for real AI; rehearsal needs no model."
