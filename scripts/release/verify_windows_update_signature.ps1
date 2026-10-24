[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Helper,
    [Parameter(Mandatory = $true)]
    [string]$Assets,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$scratch = Join-Path ([IO.Path]::GetTempPath()) ("MDLogger-signature-" + [Guid]::NewGuid())

function Test-NativeVerification {
    param([int]$Expected)
    $process = Start-Process -FilePath (Join-Path $scratch "MDLoggerUpdate.exe") `
        -ArgumentList "--verify-payload `"$scratch`"" -WorkingDirectory $scratch -Wait -PassThru
    if ($process.ExitCode -ne $Expected) {
        throw "Independent native signature verification returned $($process.ExitCode), expected $Expected"
    }
}

try {
    New-Item -ItemType Directory -Path $scratch | Out-Null
    Copy-Item -LiteralPath $Helper -Destination (Join-Path $scratch "MDLoggerUpdate.exe")
    $manifest = Join-Path $scratch "update.json"
    $signature = Join-Path $scratch "update.json.sig"
    $installer = Join-Path $scratch "MDLoggerSetup-$Version.exe"
    Copy-Item -LiteralPath (Join-Path $Assets "MDLogger-$Version-update.json") -Destination $manifest
    Copy-Item -LiteralPath (Join-Path $Assets "MDLogger-$Version-update.json.sig") -Destination $signature
    Copy-Item -LiteralPath (Join-Path $Assets "MDLoggerSetup-$Version.exe") -Destination $installer
    Test-NativeVerification -Expected 0

    # Whitespace is semantically harmless JSON but changes the authenticated bytes.
    $original = [IO.File]::ReadAllBytes($manifest)
    [IO.File]::WriteAllBytes($manifest, $original + [byte]32)
    Test-NativeVerification -Expected 2
    [IO.File]::WriteAllBytes($manifest, $original)

    $stream = [IO.File]::Open($installer, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite)
    try {
        $first = $stream.ReadByte()
        $stream.Position = 0
        $stream.WriteByte([byte]($first -bxor 1))
    }
    finally { $stream.Dispose() }
    Test-NativeVerification -Expected 2
    Copy-Item -LiteralPath (Join-Path $Assets "MDLoggerSetup-$Version.exe") -Destination $installer -Force
    Remove-Item -LiteralPath $signature
    Test-NativeVerification -Expected 2
}
finally {
    if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
}
