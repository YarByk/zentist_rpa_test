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
$commonScript = Join-Path $toolsDir "live_demo_common.ps1"
$sauceScript = Join-Path $toolsDir "debug_saucedemo_playwright_headed.py"

if (-not (Test-Path -LiteralPath $commonScript)) {
    Write-Host "ERROR: Missing live demo helper script: $commonScript"
    exit 1
}

. $commonScript

try {
    Set-Location -LiteralPath $rootDir
}
catch {
    Write-LiveDemoProblem `
        -Title "Could not enter project root" `
        -Message "PowerShell could not switch to: $rootDir`nReason: $($_.Exception.Message)" `
        -Suggestions @("Check that the project folder still exists and is accessible.")
    exit 1
}

if (-not (Import-LiveDemoEnvironment -EnvScript $envScript)) {
    exit 1
}

if (-not (Test-LiveDemoPassword -Name "SAUCEDEMO_PASSWORD" -EnvScript $envScript -PortalLabel "Sauce Demo")) {
    exit 1
}

if (-not (Invoke-LiveDemoPythonStep -Title "Sauce Demo Playwright headed" -ScriptPath $sauceScript)) {
    exit 1
}

Write-Host ""
Write-Host "Sauce Demo headed run finished."
exit 0
