<#
Local live-run environment setup.

This file is intentionally ignored by git. Put real demo credentials here and
dot-source it before running a non-dry-run Playwright configuration:

    . .\tools\set_live_env.local.ps1
#>

$env:HEADLESS = "false"
$env:EMAIL_BACKEND = "dry_run"
$env:PLAYWRIGHT_TRACE_ON_FAILURE = "true"
$env:PLAYWRIGHT_SCREENSHOT_ON_FAILURE = "true"
$env:ORANGEHRM_DEBUG = "true"
$env:ORANGEHRM_DEBUG_LOG = "artifacts/orangehrm_debug.log"

$env:ORANGEHRM_BASE_URL = "https://opensource-demo.orangehrmlive.com"
$env:ORANGEHRM_USERNAME = "Admin"
$env:ORANGEHRM_PASSWORD = "admin123"

$env:SAUCEDEMO_BASE_URL = "https://www.saucedemo.com"
$env:SAUCEDEMO_PASSWORD = "secret_sauce"

$liveEnv = @{
    HEADLESS = $env:HEADLESS
    EMAIL_BACKEND = $env:EMAIL_BACKEND
    PLAYWRIGHT_TRACE_ON_FAILURE = $env:PLAYWRIGHT_TRACE_ON_FAILURE
    PLAYWRIGHT_SCREENSHOT_ON_FAILURE = $env:PLAYWRIGHT_SCREENSHOT_ON_FAILURE
    ORANGEHRM_DEBUG = $env:ORANGEHRM_DEBUG
    ORANGEHRM_DEBUG_LOG = $env:ORANGEHRM_DEBUG_LOG
    ORANGEHRM_BASE_URL = $env:ORANGEHRM_BASE_URL
    ORANGEHRM_USERNAME = $env:ORANGEHRM_USERNAME
    ORANGEHRM_PASSWORD = $env:ORANGEHRM_PASSWORD
    SAUCEDEMO_BASE_URL = $env:SAUCEDEMO_BASE_URL
    SAUCEDEMO_PASSWORD = $env:SAUCEDEMO_PASSWORD
}

foreach ($entry in $liveEnv.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "User")
}

Write-Host "Live Playwright environment variables were set for this PowerShell session."
Write-Host "They were also saved globally for the current Windows user."
Write-Host "Restart Visual Studio and any already-open PowerShell windows so they read the updated User environment."
