$ErrorActionPreference = "Stop"

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

function Test-InnoSetup6 {
    if (-not (Test-Path -LiteralPath $iscc -PathType Leaf)) {
        return $false
    }
    return (Get-Item -LiteralPath $iscc).VersionInfo.ProductMajorPart -eq 6
}

if (-not (Test-InnoSetup6)) {
    choco install innosetup --yes --no-progress --limit-output
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup installation failed: $LASTEXITCODE"
    }
    if (-not (Test-InnoSetup6)) {
        throw "Inno Setup 6 compiler is missing or unsupported: $iscc"
    }
}

Write-Host "Using Inno Setup 6 compiler: $iscc"
