<#
Runs only the live OrangeHRM demo headed flow.

The script loads tools\set_live_env.local.ps1 first, then runs
tools\debug_orangehrm_demo_playwright_headed.py.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $toolsDir
$envScript = Join-Path $toolsDir "set_live_env.local.ps1"
$commonScript = Join-Path $toolsDir "live_demo_common.ps1"
$orangeScript = Join-Path $toolsDir "debug_orangehrm_demo_playwright_headed.py"

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

if (-not (Test-LiveDemoPassword -Name "ORANGEHRM_PASSWORD" -EnvScript $envScript -PortalLabel "OrangeHRM")) {
    exit 1
}

if (-not (Invoke-LiveDemoPythonStep -Title "OrangeHRM demo Playwright headed" -ScriptPath $orangeScript)) {
    exit 1
}

Write-Host ""
Write-Host "OrangeHRM headed demo run finished."
exit 0
