[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Onedir,

    [Parameter(Mandatory = $true)]
    [string]$BuildDirectory,

    [Parameter(Mandatory = $true)]
    [string]$Installer,

    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,

    [Parameter(Mandatory = $true)]
    [string]$Record,

    [switch]$VerifyUpdater
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Path {
    param([string]$Path, [string]$Description)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description is missing: $Path"
    }
}

function Require-AnalysisEvidence {
    param([string]$Directory)

    $analysis = Join-Path $Directory "Analysis-00.toc"
    $collect = Join-Path $Directory "COLLECT-00.toc"
    Require-Path $analysis "PyInstaller Analysis TOC"
    Require-Path $collect "PyInstaller COLLECT TOC"
    if ((Get-Content -LiteralPath $analysis -Raw) -notmatch "PySide6") {
        throw "PyInstaller Analysis TOC does not contain PySide6 evidence"
    }
}

function Test-PackagedStartup {
    param([string]$Executable)

    $names = @("MDLOGGER_SUPABASE_URL", "MDLOGGER_SUPABASE_ANON_KEY", "MDLOGGER_DECKS_URL", "HTTPS_PROXY", "QT_QPA_PLATFORM")
    $previous = @{}
    foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
    $application = $null
    try {
        $env:MDLOGGER_SUPABASE_URL = "http://127.0.0.1:9"
        $env:MDLOGGER_SUPABASE_ANON_KEY = "sb_publishable_test_not_a_secret_key_abcdefgh"
        $env:MDLOGGER_DECKS_URL = ""
        $env:HTTPS_PROXY = "http://127.0.0.1:9"
        $env:QT_QPA_PLATFORM = "windows"
        $application = Start-Process -FilePath $Executable -PassThru
        Write-Host "Packaged application started: PID $($application.Id)"
        $application.WaitForInputIdle(5000) | Out-Null
        $startup = [Diagnostics.Stopwatch]::StartNew()
        $application.Refresh()
        while (-not $application.HasExited -and $application.MainWindowHandle -eq [IntPtr]::Zero -and $startup.Elapsed.TotalSeconds -lt 45) {
            Start-Sleep -Milliseconds 100
            $application.Refresh()
        }
        if ($application.HasExited -or $application.MainWindowHandle -eq [IntPtr]::Zero) {
            Get-CimInstance Win32_Process -Filter "Name='MDLogger.exe'" |
                Select-Object ProcessId, ParentProcessId, ExecutablePath | Format-List | Out-Host
            $exit = if ($application.HasExited) { $application.ExitCode } else { "still running" }
            throw "Packaged application did not open its main window: $exit"
        }
        Write-Host "Packaged application window ready: $($application.MainWindowTitle)"
        if (-not $application.CloseMainWindow() -or -not $application.WaitForExit(30000)) {
            throw "Packaged application did not exit gracefully"
        }
        if ($application.ExitCode -ne 0) { throw "Packaged application failed during startup or shutdown" }
    }
    finally {
        foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process") }
        if ($null -ne $application -and -not $application.HasExited) {
            # 실패한 검증 프로세스만 정리하며 배포 프로그램의 종료 정책은 변경하지 않는다.
            $application.Kill()
            $application.WaitForExit(10000) | Out-Null
        }
    }
}

Require-Path $Onedir "PyInstaller onedir payload"
Require-Path $BuildDirectory "PyInstaller build directory"
Require-Path $Installer "Inno Setup installer"
if (Test-Path -LiteralPath $InstallRoot) {
    throw "Release verification requires a fresh installation directory"
}

$expectedInstaller = "MDLoggerSetup-$Version.exe"
if ((Split-Path -Leaf $Installer) -cne $expectedInstaller) {
    throw "Unexpected installer filename: $Installer"
}

& uv run python scripts/release/release_validation.py windows-payload --root $Onedir
if ($LASTEXITCODE -ne 0) {
    throw "Windows onedir payload validation failed"
}
Require-AnalysisEvidence -Directory $BuildDirectory

& uv run python -m mdlogger.secret_scan $Onedir
if ($LASTEXITCODE -ne 0) {
    throw "Windows onedir secret scan failed"
}
& uv run python -m mdlogger.checksum $Onedir
if ($LASTEXITCODE -ne 0) {
    throw "Windows onedir checksum generation failed"
}

$helper = Join-Path $Onedir "MDLoggerUpdate.exe"
$scratch = Join-Path ([IO.Path]::GetTempPath()) ("MDLogger-release-" + [Guid]::NewGuid())
$originalDataDir = $env:MDLOGGER_DATA_DIR
$dataRoot = Join-Path $scratch "user-data"
if ($VerifyUpdater) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Windows release installation verification requires an administrator runner"
    }
    Require-Path $helper "Independent update helper"
}

try {
    if ($VerifyUpdater) {
        New-Item -ItemType Directory -Path $scratch, $dataRoot | Out-Null
        $env:MDLOGGER_DATA_DIR = $dataRoot
        Copy-Item -LiteralPath $helper -Destination (Join-Path $scratch "MDLoggerUpdate.exe")
        $probe = Join-Path $scratch "empty-payload"
        New-Item -ItemType Directory -Path $probe | Out-Null
        $helperProcess = Start-Process -FilePath (Join-Path $scratch "MDLoggerUpdate.exe") `
            -ArgumentList "--verify-payload `"$probe`"" -WorkingDirectory $scratch -Wait -PassThru
        if ($helperProcess.ExitCode -ne 2) {
            throw "Standalone helper must reject an unsigned payload without Python or Qt"
        }
        [IO.File]::WriteAllText((Join-Path $dataRoot "sentinel"), "preserve-user-data")
    }
    $installProcess = Start-Process -FilePath $Installer -ArgumentList "/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /RESTARTEXITCODE=3010 /NOCLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /DIR=`"$InstallRoot`"" -Wait -PassThru
    if ($installProcess.ExitCode -ne 0) {
        throw "Inno Setup silent installation failed: $($installProcess.ExitCode)"
    }

    & uv run python scripts/release/release_validation.py windows-payload --root $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Windows payload validation failed"
    }
    & uv run python -m mdlogger.secret_scan $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Windows payload secret scan failed"
    }
    if ($VerifyUpdater) {
        $installedHelper = Join-Path $InstallRoot "MDLoggerUpdate.exe"
        Require-Path $installedHelper "Installed independent update helper"
        if ((Get-FileHash -LiteralPath $installedHelper).Hash -cne (Get-FileHash -LiteralPath $helper).Hash) {
            throw "Installed update helper differs from the verified build"
        }
        $registry = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{F0987F41-0A8B-4B2E-9C61-9CDD4F8E7C00}_is1"
        if ($registry.DisplayVersion -cne $Version -or $registry.InstallLocation.TrimEnd('\') -ine $InstallRoot.TrimEnd('\')) {
            throw "Machine-wide installer registration does not match the tested release"
        }
        $reinstall = Start-Process -FilePath $Installer `
            -ArgumentList "/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /RESTARTEXITCODE=3010 /NOCLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /DIR=`"$InstallRoot`"" -Wait -PassThru
        if ($reinstall.ExitCode -ne 0) { throw "In-place reinstall failed or requires reboot" }
        if ([IO.File]::ReadAllText((Join-Path $dataRoot "sentinel")) -cne "preserve-user-data") {
            throw "Installer modified data outside the installation tree"
        }
        & uv run python scripts/release/release_validation.py windows-payload --root $InstallRoot
        if ($LASTEXITCODE -ne 0) { throw "Reinstalled payload validation failed" }
        Test-PackagedStartup -Executable (Join-Path $InstallRoot "MDLogger.exe")
    }
}
finally {
    $env:MDLOGGER_DATA_DIR = $originalDataDir
    $uninstaller = Join-Path $InstallRoot "unins000.exe"
    if ($VerifyUpdater -and (Test-Path -LiteralPath $uninstaller)) {
        $uninstall = Start-Process -FilePath $uninstaller `
            -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait -PassThru
        if ($uninstall.ExitCode -ne 0) { throw "Verification installation cleanup failed" }
    }
    if (Test-Path -LiteralPath $InstallRoot) {
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $scratch) {
        Remove-Item -LiteralPath $scratch -Recurse -Force
    }
}

& uv run python -m mdlogger.checksum $Installer
if ($LASTEXITCODE -ne 0) {
    throw "Installer checksum generation failed"
}

$innoCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
$innoVersion = (Get-Item -LiteralPath $innoCompiler).VersionInfo.ProductVersion
$pythonVersion = (& uv run python --version).Trim()
$uvVersion = (& uv --version).Trim()
$pyInstallerVersion = (& uv run pyinstaller --version).Trim()
$runnerOs = if ([string]::IsNullOrWhiteSpace($env:RUNNER_OS)) { "unknown" } else { $env:RUNNER_OS }
$runnerImageVersion = if ([string]::IsNullOrWhiteSpace($env:ImageVersion)) { "unknown" } else { $env:ImageVersion }

& uv run python scripts/release/create_release_manifest.py platform-record `
    --platform windows-x64 `
    --asset $Installer `
    --output $Record `
    --check onedir-license-payload `
    --check onedir-secret-scan `
    --check pyinstaller-analysis `
    --check onedir-checksum `
    --check installer-silent-installation `
    --check installed-license-payload `
    --check installed-secret-scan `
    --check installer-checksum `
    --tool "python=$pythonVersion" `
    --tool "uv=$uvVersion" `
    --tool "pyinstaller=$pyInstallerVersion" `
    --tool "inno-setup=$innoVersion" `
    --tool "runner-os=$runnerOs" `
    --tool "runner-image-version=$runnerImageVersion"
if ($LASTEXITCODE -ne 0) {
    throw "Windows verification record creation failed"
}

if ($VerifyUpdater) {
    $updateRecord = Join-Path (Split-Path -Parent $Record) "windows-update-verification.json"
    & uv run python -m scripts.release.windows_release record `
        --installer $Installer --helper $helper --output $updateRecord
    if ($LASTEXITCODE -ne 0) { throw "Windows updater verification record creation failed" }
}
