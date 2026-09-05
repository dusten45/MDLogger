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
    [string]$Record
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

Require-Path $Onedir "PyInstaller onedir payload"
Require-Path $BuildDirectory "PyInstaller build directory"
Require-Path $Installer "Inno Setup installer"

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

try {
    & $Installer /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART "/DIR=$InstallRoot"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup silent installation failed: $LASTEXITCODE"
    }

    & uv run python scripts/release/release_validation.py windows-payload --root $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Windows payload validation failed"
    }
    & uv run python -m mdlogger.secret_scan $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Windows payload secret scan failed"
    }
}
finally {
    if (Test-Path -LiteralPath $InstallRoot) {
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force
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
