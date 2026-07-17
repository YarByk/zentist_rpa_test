<#
Shared helpers for the live headed demo PowerShell wrappers.

The wrappers are meant to be used by an operator from PowerShell or another
launcher. Expected setup problems should therefore produce clear instructions
and normal process exit codes, not PowerShell exception stack traces.
#>

function Write-LiveDemoSection {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Title
    )

    Write-Host ""
    Write-Host "================================================================"
    Write-Host $Title
    Write-Host "================================================================"
}

function Write-LiveDemoProblem {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Title,

        [Parameter(Mandatory = $true)]
        [string] $Message,

        [string[]] $Suggestions = @()
    )

    Write-Host ""
    Write-Host "ERROR: $Title"
    Write-Host $Message

    if ($Suggestions.Count -gt 0) {
        Write-Host ""
        Write-Host "What to check:"
        foreach ($suggestion in $Suggestions) {
            Write-Host "- $suggestion"
        }
    }
}

function Import-LiveDemoEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string] $EnvScript
    )

    if (-not (Test-Path -LiteralPath $EnvScript)) {
        Write-LiveDemoProblem `
            -Title "Live environment file was not found" `
            -Message "Expected file: $EnvScript" `
            -Suggestions @(
                "Create tools\set_live_env.local.ps1 from tools\set_live_env.example.ps1.",
                "Fill ORANGEHRM_PASSWORD and/or SAUCEDEMO_PASSWORD in that local file.",
                "Run the wrapper again from the project root or from the tools folder."
            )
        return $false
    }

    try {
        $item = Get-Item -LiteralPath $EnvScript -ErrorAction Stop
        if ($item.PSIsContainer) {
            Write-LiveDemoProblem `
                -Title "Live environment path is a directory" `
                -Message "Expected a PowerShell file, but found a directory: $EnvScript" `
                -Suggestions @(
                    "Remove or rename that directory.",
                    "Create a real tools\set_live_env.local.ps1 file with the password assignments."
                )
            return $false
        }

        # Force a read before parsing so access/locking problems get a precise diagnosis.
        $content = Get-Content -LiteralPath $EnvScript -Raw -ErrorAction Stop
    }
    catch {
        Write-LiveDemoProblem `
            -Title "Could not read the live environment file" `
            -Message "PowerShell could not read: $EnvScript`nReason: $($_.Exception.Message)" `
            -Suggestions @(
                "Check that the file exists and is not a directory.",
                "Check Windows file permissions for your current user.",
                "Check whether antivirus, backup software, or an editor is blocking the file.",
                "Make sure you are editing the file in this checkout, not another project copy."
            )
        return $false
    }

    try {
        $tokens = $null
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $EnvScript,
            [ref] $tokens,
            [ref] $parseErrors
        ) | Out-Null

        if ($parseErrors.Count -gt 0) {
            $messages = ($parseErrors | ForEach-Object { $_.Message }) -join "`n"
            Write-LiveDemoProblem `
                -Title "Could not parse the live environment file" `
                -Message "PowerShell syntax errors were found in: $EnvScript`n$messages" `
                -Suggestions @(
                    "Check the file for missing quotes, extra brackets, or partially pasted lines.",
                    "Keep password assignments in this form: `$env:ORANGEHRM_PASSWORD = `"your-password`".",
                    "If unsure, recreate the file from tools\set_live_env.example.ps1."
                )
            return $false
        }

        $assignmentPattern = '^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(["''])(.*?)\2\s*(?:#.*)?$'
        $loadedNames = New-Object System.Collections.Generic.List[string]
        foreach ($line in ($content -split "`r?`n")) {
            $match = [regex]::Match($line, $assignmentPattern)
            if (-not $match.Success) {
                continue
            }

            $name = $match.Groups[1].Value
            $value = $match.Groups[3].Value
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
            $loadedNames.Add($name)
        }

        if ($loadedNames.Count -eq 0) {
            Write-LiveDemoProblem `
                -Title "No environment assignments were found" `
                -Message "The file was readable, but no direct `$env:NAME = `"value`" assignments were found in: $EnvScript" `
                -Suggestions @(
                    "Check that the file was not accidentally emptied.",
                    "Use direct assignments such as `$env:ORANGEHRM_PASSWORD = `"your-password`".",
                    "If unsure, recreate the file from tools\set_live_env.example.ps1."
                )
            return $false
        }
    }
    catch {
        Write-LiveDemoProblem `
            -Title "Could not load the live environment file" `
            -Message "PowerShell found a problem while reading settings from: $EnvScript`nReason: $($_.Exception.Message)" `
            -Suggestions @(
                "Check the file for unexpected binary characters or broken encoding.",
                "Keep assignments in this form: `$env:ORANGEHRM_PASSWORD = `"your-password`".",
                "If the file contains extra commands, they are intentionally ignored by the wrapper."
            )
        return $false
    }

    Write-Host "Loaded live environment values from $EnvScript"
    return $true
}

function Test-LiveDemoPassword {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,

        [Parameter(Mandatory = $true)]
        [string] $EnvScript,

        [Parameter(Mandatory = $true)]
        [string] $PortalLabel
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $true
    }

    Write-LiveDemoProblem `
        -Title "$PortalLabel password is empty or not visible" `
        -Message "$Name is empty after loading $EnvScript." `
        -Suggestions @(
            "Open tools\set_live_env.local.ps1 and set: `$env:$Name = `"your-password`".",
            "Make sure the assignment is not commented out and not inside a conditional block that did not run.",
            "Make sure the script did not stop before the password assignment.",
            "Make sure you edited this exact file: $EnvScript.",
            "For these wrappers, restarting the launcher is not required because the file is loaded directly before the run."
        )
    return $false
}

function Invoke-LiveDemoPythonStep {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Title,

        [Parameter(Mandatory = $true)]
        [string] $ScriptPath
    )

    Write-LiveDemoSection -Title $Title

    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        Write-LiveDemoProblem `
            -Title "Python helper script was not found" `
            -Message "Expected helper: $ScriptPath" `
            -Suggestions @(
                "Check that the repository checkout is complete.",
                "Check that you are running the wrapper from the correct project."
            )
        return $false
    }

    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-LiveDemoProblem `
            -Title "Python was not found" `
            -Message "The wrapper could not find python.exe on PATH." `
            -Suggestions @(
                "Activate the project environment before running this script.",
                "Install Python or add it to PATH.",
                "Run the same command from the shell where the project tests pass."
            )
        return $false
    }

    & python $ScriptPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        return $true
    }

    Write-LiveDemoProblem `
        -Title "$Title did not complete successfully" `
        -Message "The Python helper exited with code $exitCode." `
        -Suggestions @(
            "Read the run details printed above; they contain the portal status and item-level errors.",
            "If you see LOGIN_FAILED or invalid credentials, verify the password in tools\set_live_env.local.ps1.",
            "If the portal is unavailable, inspect the screenshot and report paths printed above.",
            "This is reported as a controlled script result, not as a PowerShell exception."
        )
    return $false
}
