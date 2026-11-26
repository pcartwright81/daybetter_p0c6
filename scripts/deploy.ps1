[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Destination = "\\homeassistant.local\config\custom_components"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$domain = "daybetter_p0c6"
$sourceDir = Join-Path $repoRoot "custom_components\$domain"
$targetDir = Join-Path $Destination $domain

if (-not (Test-Path -LiteralPath $sourceDir -PathType Container)) {
    throw "Source integration directory not found: $sourceDir"
}

if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    throw "Destination path is not reachable: $Destination. Verify the SMB share is mounted/accessible."
}

if ($PSCmdlet.ShouldProcess($targetDir, "Mirror $sourceDir")) {
    $robocopyArgs = @(
        $sourceDir,
        $targetDir,
        "/MIR",
        "/XD", "__pycache__",
        "/XF", "*.pyc", "*.pyo",
        "/R:2",
        "/W:2",
        "/NFL",
        "/NDL",
        "/NP"
    )

    & robocopy @robocopyArgs
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit code $LASTEXITCODE"
    }

    Write-Host "Deployed $domain to $targetDir" -ForegroundColor Green
    Write-Host "Restart Home Assistant to load the updated integration." -ForegroundColor Yellow
}
