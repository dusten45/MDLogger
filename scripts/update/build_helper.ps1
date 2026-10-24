[CmdletBinding()]
param(
    [string]$Output = "build/update/MDLoggerUpdate.exe",
    [string]$TrustedKeys = "src/mdlogger/data/update-trusted-keys.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Windows 기본 .NET Framework 컴파일러만 사용한다. Python 런타임에 연결하지 않는다.
$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw "Windows .NET Framework C# compiler is missing: $compiler"
}
if (-not (Test-Path -LiteralPath $TrustedKeys -PathType Leaf)) {
    throw "Pinned update public keys are missing: $TrustedKeys"
}
$keys = Get-Content -LiteralPath $TrustedKeys -Raw -Encoding UTF8 | ConvertFrom-Json
if ($keys.schema -ne 1 -or @($keys.keys).Count -eq 0) {
    throw "At least one pinned update key is required"
}
$outputPath = [IO.Path]::GetFullPath($Output)
$keysPath = (Resolve-Path -LiteralPath $TrustedKeys).Path
$scriptDirectory = Split-Path -Parent $PSCommandPath
$sourcePath = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory "UpdateHelper.cs")).Path
$manifestPath = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory "update-helper.manifest")).Path
$parent = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Path $parent -Force | Out-Null
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 `
    "/out:$outputPath" `
    /reference:System.Web.Extensions.dll /reference:System.Windows.Forms.dll `
    "/resource:$keysPath,MDLogger.UpdateTrustedKeys.json" `
    "/win32manifest:$manifestPath" `
    $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "Windows update helper compilation failed: $LASTEXITCODE"
}
Write-Host "Built independent Windows update helper: $outputPath"
