<#
.SYNOPSIS
    Strips volatile timing text from two log files and opens a PyCharm diff for easier comparison.

.PARAMETER PathA
    First log file path.

.PARAMETER PathB
    Second log file path.

.EXAMPLE
    .\CompareLogsWithoutTimes.ps1 -PathA .\working_log.txt -PathB .\failed_log.txt
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$PathA,

    [Parameter(Mandatory = $true)]
    [string]$PathB
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RequiredFilePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.PSIsContainer) {
        throw "Expected a file path, but got a directory: $Path"
    }

    return $item.FullName
}

function Get-SafeTempFileName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $fileName = [System.IO.Path]::GetFileName($SourcePath)
    foreach ($invalidChar in [System.IO.Path]::GetInvalidFileNameChars()) {
        $fileName = $fileName.Replace($invalidChar, '_')
    }

    return "$Label.$fileName.stripped.log"
}

function Remove-VolatileLogTimes {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $strippedContent = $Content -replace '\(\d+\.\d+ in\)', ''
    $strippedContent = $strippedContent -replace '(?m)^\d\d:\d\d\.\d\d\d\d', ''
    $strippedContent = $strippedContent -replace ': \(\d+\.\d+\)', ': '
    return $strippedContent
}

function Write-StrippedLogCopy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    $content = Get-Content -LiteralPath $SourcePath -Raw
    $strippedContent = Remove-VolatileLogTimes -Content $content
    [System.IO.File]::WriteAllText($DestinationPath, $strippedContent, [System.Text.UTF8Encoding]::new($false))
}

function Find-PyCharmExecutable {
    $command = Get-Command pycharm64.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $command = Get-Command pycharm.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $candidatePaths = @(
        'C:\Program Files\JetBrains\PyCharm 2025.1.2\bin\pycharm64.exe',
        'C:\Program Files\JetBrains\PyCharm 2025.1\bin\pycharm64.exe',
        'C:\Program Files\JetBrains\PyCharm Community Edition 2025.1.2\bin\pycharm64.exe',
        'C:\Program Files\JetBrains\PyCharm Community Edition 2025.1\bin\pycharm64.exe'
    )

    foreach ($candidatePath in $candidatePaths) {
        if (Test-Path -LiteralPath $candidatePath) {
            return $candidatePath
        }
    }

    throw 'Unable to find PyCharm. Add pycharm64.exe to PATH or update Find-PyCharmExecutable in this script with your install path.'
}

$resolvedPathA = Resolve-RequiredFilePath -Path $PathA
$resolvedPathB = Resolve-RequiredFilePath -Path $PathB

$tempRoot = 'D:\2019_reformat_Backup\cascade-debug-output\generals-bot\log-diffs'
if (-not (Test-Path -LiteralPath $tempRoot)) {
    New-Item -Path $tempRoot -ItemType Directory -Force | Out-Null
}

$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss_ffff'
$runFolder = Join-Path $tempRoot $runStamp
New-Item -Path $runFolder -ItemType Directory -Force | Out-Null

$strippedPathA = Join-Path $runFolder (Get-SafeTempFileName -SourcePath $resolvedPathA -Label 'A')
$strippedPathB = Join-Path $runFolder (Get-SafeTempFileName -SourcePath $resolvedPathB -Label 'B')

Write-StrippedLogCopy -SourcePath $resolvedPathA -DestinationPath $strippedPathA
Write-StrippedLogCopy -SourcePath $resolvedPathB -DestinationPath $strippedPathB

$pyCharmPath = Find-PyCharmExecutable
Write-Host "Opening PyCharm diff:"
Write-Host "  A: $strippedPathA"
Write-Host "  B: $strippedPathB"

Start-Process -FilePath $pyCharmPath -ArgumentList @('diff', $strippedPathA, $strippedPathB)
