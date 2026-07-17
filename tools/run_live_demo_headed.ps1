<#
Runs the live headed demo sequence.

The script loads tools\set_live_env.local.ps1 first, then runs:
1. OrangeHRM demo Playwright headed.
2. Sauce Demo Playwright headed.

The Python helper scripts keep handled portal report failures VS-friendly, so
this script only stops when a helper exits with a real script/environment error.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $toolsDir
$envScript = Join-Path $toolsDir "set_live_env.local.ps1"
$orangeScript = Join-Path $toolsDir "debug_orangehrm_demo_playwright_headed.py"
$sauceScript = Join-Path $toolsDir "debug_saucedemo_playwright_headed.py"

function Invoke-DemoStep {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Title,

        [Parameter(Mandatory = $true)]
        [string] $ScriptPath
    )

    Write-Host ""
    Write-Host "================================================================"
    Write-Host $Title
    Write-Host "================================================================"

    & python $ScriptPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Title failed with exit code $exitCode."
    }
}

if (-not (Test-Path -LiteralPath $envScript)) {
    throw "Missing live environment script: $envScript"
}

Set-Location -LiteralPath $rootDir

Write-Host "Loading live environment from $envScript"
. $envScript

Invoke-DemoStep `
    -Title "OrangeHRM demo Playwright headed" `
    -ScriptPath $orangeScript

Invoke-DemoStep `
    -Title "Sauce Demo Playwright headed" `
    -ScriptPath $sauceScript

Write-Host ""
Write-Host "Live headed demo sequence finished."
