<#
Runs only the live Sauce Demo headed demo.

The script loads tools\set_live_env.local.ps1 first, then runs
tools\debug_saucedemo_playwright_headed.py.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $toolsDir
$envScript = Join-Path $toolsDir "set_live_env.local.ps1"
$sauceScript = Join-Path $toolsDir "debug_saucedemo_playwright_headed.py"

if (-not (Test-Path -LiteralPath $envScript)) {
    throw "Missing live environment script: $envScript"
}

Set-Location -LiteralPath $rootDir

Write-Host "Loading live environment from $envScript"
. $envScript

Write-Host ""
Write-Host "================================================================"
Write-Host "Sauce Demo Playwright headed"
Write-Host "================================================================"

& python $sauceScript
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "Sauce Demo Playwright headed failed with exit code $exitCode."
}

Write-Host ""
Write-Host "Sauce Demo headed run finished."
