$ErrorActionPreference = "Stop"

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

function Test-InnoSetup6 {
    if (-not (Test-Path -LiteralPath $iscc -PathType Leaf)) {
        return $false
    }
    # ISCC 6 has 0.0.0.0 PE metadata and intentionally exits 1 for /?.
    $helpText = (& $iscc /? 2>&1 | Out-String)
    $helpExitCode = $LASTEXITCODE
    if ($helpExitCode -eq 1 -and $helpText -match '(?m)^Inno Setup 6 Command-Line Compiler\r?$') {
        $global:LASTEXITCODE = 0
        return $true
    }
    return $false
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
