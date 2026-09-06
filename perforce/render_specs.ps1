param(
    [Parameter(Mandatory = $true)]
    [string]$P4User,

    [Parameter(Mandatory = $true)]
    [string]$P4Client,

    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,

    [string]$P4Port = "localhost:1666",

    [string]$OutputDirectory = ".\perforce\rendered"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ResolvedWorkspaceRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$ResolvedOutput = [System.IO.Path]::GetFullPath(
    (Join-Path $RepositoryRoot $OutputDirectory)
)

if ($ResolvedWorkspaceRoot -eq [System.IO.Path]::GetPathRoot($ResolvedWorkspaceRoot)) {
    throw "WorkspaceRoot 不能是磁盘根目录。"
}

New-Item -ItemType Directory -Force -Path $ResolvedOutput | Out-Null

$Replacements = @{
    "__P4USER__" = $P4User
    "__P4CLIENT__" = $P4Client
    "__P4HOST__" = $env:COMPUTERNAME
    "__P4ROOT__" = $ResolvedWorkspaceRoot.Replace("\", "/")
}

function Render-Template {
    param(
        [string]$Source,
        [string]$Destination
    )

    $Content = Get-Content -Raw -Encoding UTF8 $Source
    foreach ($Key in $Replacements.Keys) {
        $Content = $Content.Replace($Key, $Replacements[$Key])
    }
    Set-Content -Encoding UTF8 -Path $Destination -Value $Content
}

Render-Template `
    (Join-Path $PSScriptRoot "depot.spec.template") `
    (Join-Path $ResolvedOutput "depot.spec")
Render-Template `
    (Join-Path $PSScriptRoot "main.stream.template") `
    (Join-Path $ResolvedOutput "main.stream")
Render-Template `
    (Join-Path $PSScriptRoot "workspace.spec.template") `
    (Join-Path $ResolvedOutput "workspace.spec")

$Config = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot ".p4config.template")
foreach ($Key in $Replacements.Keys) {
    $Config = $Config.Replace($Key, $Replacements[$Key])
}
$Config = $Config.Replace("ssl:localhost:1666", $P4Port)
Set-Content -Encoding UTF8 -Path (Join-Path $ResolvedOutput ".p4config") -Value $Config
Copy-Item (Join-Path $PSScriptRoot ".p4ignore") (Join-Path $ResolvedOutput ".p4ignore") -Force
Copy-Item (Join-Path $PSScriptRoot "typemap.p4") (Join-Path $ResolvedOutput "typemap.p4") -Force

Write-Host "[VS2_5_P4] Rendered specs only; no server mutation was performed."
Write-Host "Output: $ResolvedOutput"
Write-Host "P4PORT: $P4Port"
Write-Host "P4USER: $P4User"
Write-Host "P4CLIENT: $P4Client"
Write-Host "WorkspaceRoot: $ResolvedWorkspaceRoot"
