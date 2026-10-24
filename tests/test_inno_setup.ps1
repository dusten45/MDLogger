param([string]$Helper = (Join-Path $PSScriptRoot "../scripts/ensure_inno_setup.ps1"))

$ErrorActionPreference = "Stop"
$global:innoMock = @{ Compiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" }

function Test-Path {
    param([string]$LiteralPath, [string]$PathType)
    if ($LiteralPath -cne $global:innoMock.Compiler -or $PathType -cne "Leaf") {
        throw "Unexpected compiler path: $LiteralPath"
    }
    return $global:innoMock.Exists
}

function Get-Item {
    # ISCC 6.7.1's actual PE resource has zero file and product versions.
    return [pscustomobject]@{
        VersionInfo = [pscustomobject]@{ ProductMajorPart = 0; FileMajorPart = 0 }
    }
}

function Invoke-FakeCompiler {
    if ($args.Count -ne 1 -or $args[0] -cne "/?") {
        throw "Unexpected compiler arguments: $args"
    }
    "Inno Setup $($global:innoMock.Major) Command-Line Compiler"
    "Usage: iscc [options] scriptfile.iss"
    $global:LASTEXITCODE = $global:innoMock.HelpExitCode
}

Set-Alias -Name $global:innoMock.Compiler -Value Invoke-FakeCompiler

function choco {
    if (($args -join " ") -cne "install innosetup --yes --no-progress --limit-output") {
        throw "Unexpected Chocolatey arguments: $args"
    }
    $global:innoMock.Calls++
    $global:innoMock.Exists = $global:innoMock.Case.AfterExists
    $global:innoMock.Major = $global:innoMock.Case.AfterMajor
    $global:LASTEXITCODE = $global:innoMock.Case.InstallExitCode
}

$cases = @(
    @{
        Name = "existing compiler with zero PE metadata skips installation"
        Exists = $true; Major = 6; HelpExitCode = 1
        AfterExists = $false; AfterMajor = 0; InstallExitCode = 99
        Calls = 0; Error = $null
    },
    @{
        Name = "missing compiler installs and validates"
        Exists = $false; Major = 0; HelpExitCode = 1
        AfterExists = $true; AfterMajor = 6; InstallExitCode = 0
        Calls = 1; Error = $null
    },
    @{
        Name = "wrong major triggers installation"
        Exists = $true; Major = 7; HelpExitCode = 1
        AfterExists = $true; AfterMajor = 6; InstallExitCode = 0
        Calls = 1; Error = $null
    },
    @{
        Name = "unsupported compiler remains rejected after installation"
        Exists = $true; Major = 5; HelpExitCode = 1
        AfterExists = $true; AfterMajor = 7; InstallExitCode = 0
        Calls = 1; Error = "Inno Setup 6 compiler is missing or unsupported:*"
    },
    @{
        Name = "failed installation is not masked by a compiler appearing"
        Exists = $false; Major = 0; HelpExitCode = 1
        AfterExists = $true; AfterMajor = 6; InstallExitCode = 42
        Calls = 1; Error = "Inno Setup installation failed: 42"
    },
    @{
        Name = "successful installation must produce a compiler"
        Exists = $false; Major = 0; HelpExitCode = 1
        AfterExists = $false; AfterMajor = 0; InstallExitCode = 0
        Calls = 1; Error = "Inno Setup 6 compiler is missing or unsupported:*"
    },
    @{
        Name = "unexpected compiler failure is not accepted as help"
        Exists = $true; Major = 6; HelpExitCode = 2
        AfterExists = $true; AfterMajor = 6; InstallExitCode = 0
        Calls = 1; Error = "Inno Setup 6 compiler is missing or unsupported:*"
    }
)

foreach ($case in $cases) {
    $global:innoMock.Case = $case
    $global:innoMock.Exists = $case.Exists
    $global:innoMock.Major = $case.Major
    $global:innoMock.HelpExitCode = $case.HelpExitCode
    $global:innoMock.Calls = 0
    $global:LASTEXITCODE = 0
    $failure = $null
    try { & $Helper } catch { $failure = $_.Exception.Message }
    if ($global:innoMock.Calls -ne $case.Calls) {
        throw "$($case.Name): unexpected installation count $($global:innoMock.Calls)"
    }
    if ($case.Error) {
        if (-not $failure -or $failure -notlike $case.Error) {
            throw "$($case.Name): unexpected error: $failure"
        }
    } elseif ($failure -or $global:LASTEXITCODE -ne 0) {
        throw "$($case.Name): failure or leaked native help exit code: $failure / $global:LASTEXITCODE"
    }
    Write-Host "PASS: $($case.Name)"
}

Write-Host "All $($cases.Count) Inno Setup helper cases passed."
exit 0
