param([string]$UnityPath = "C:\Program Files\Unity\Hub\Editor\6000.0.62f1\Editor\Unity.exe")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$GamePython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
& $GamePython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Offline tests failed" }
if (-not (Test-Path "Builds/Windows/LastLight.exe")) { throw "Run build_windows.ps1 first." }
$Exe = Join-Path $ProjectRoot "Builds/Windows/LastLight.exe"
$Fixtures = Join-Path $ProjectRoot "Builds/Windows/QA"
foreach ($Resolution in @(@(1920,1080),@(1280,720),@(1440,900))) {
    $Output = Join-Path $ProjectRoot ("artifacts/windows-"+$Resolution[0]+"x"+$Resolution[1])
    New-Item -ItemType Directory -Force $Output | Out-Null
    $Arguments = "--qa-capture `"$Fixtures`" --qa-output `"$Output`" -screen-fullscreen 0 -screen-width $($Resolution[0]) -screen-height $($Resolution[1]) -logFile `"$Output/player.log`""
    $Process = Start-Process -FilePath $Exe -ArgumentList $Arguments -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw "Player QA failed: $Output" }
    & $GamePython tools/encode_player_captures.py $Output
    if ($LASTEXITCODE -ne 0) { throw "Player video encoding failed: $Output" }
}
Write-Host "Inspect screenshots/animation frame sequences and qa-report.json under artifacts/windows-*; these are actual Windows Player results."
