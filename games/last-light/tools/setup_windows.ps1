param([string]$Python = "")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $Python = (& py -3 -c "import sys; print(sys.executable)").Trim()
    } elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = (Get-Command python).Source }
    else { throw "Install Python 3.11 or newer, then rerun this script." }
}
& $Python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
if ($LASTEXITCODE -ne 0) { throw "Unsupported Python" }
if (-not (Test-Path ".venv/Scripts/python.exe")) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Cannot create Python environment" }
}
$GamePython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
& $GamePython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip update failed" }
$Sibling = Join-Path (Split-Path -Parent $ProjectRoot) "npc-director"
$Monorepo = Split-Path -Parent (Split-Path -Parent $ProjectRoot)
if (Test-Path (Join-Path $Monorepo "src/npc_director")) {
    & $GamePython -m pip install $Monorepo
} elseif (Test-Path (Join-Path $ProjectRoot "vendor/wheels")) {
    & $GamePython -m pip install --find-links vendor/wheels "npc-director==0.3.0"
} elseif (Test-Path (Join-Path $Sibling "pyproject.toml")) {
    & $GamePython -m pip install $Sibling
} else { throw "Missing NPC Director source/wheel. Use the complete Last Light source package." }
if ($LASTEXITCODE -ne 0) { throw "NPC Director installation failed" }
& $GamePython -m pip install -e ".[test,build]"
if ($LASTEXITCODE -ne 0) { throw "Game dependency installation failed" }
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }
Write-Host "Ready. Run .venv/Scripts/python.exe tools/run_server.py, then open the Unity project."
