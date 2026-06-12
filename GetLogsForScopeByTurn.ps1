<#
.SYNOPSIS
    Extracts all log entries for a named scope (e.g. "TileIsland update") from bot test output,
    grouped by turn, and appends any AssertionError / Traceback that follows each scope block.

.DESCRIPTION
    Bot test output is structured with "~~~ Turn N (timing) ~~~" markers, and scopes delimited by
    "Beginning: <ScopeName> (...)" / "Complete: (...) <ScopeName>" lines.  This script finds every
    occurrence of the requested scope across all turns and prints just that slice, making it easy to
    trace per-turn state through a long run without wading through unrelated log lines.

    Accepts input either piped directly from a pytest run (most useful during debugging sessions)
    or from a saved log file via -LogFilePath.

.PARAMETER ScopeName
    The exact scope name to extract, e.g. "TileIsland update".
    Matched as a substring of the Beginning/Complete lines.

.PARAMETER LogFilePath
    Path to a saved log file.  Mutually exclusive with piped input.

.EXAMPLE
    # Pipe a live pytest run and filter to TileIsland update scope only:
    .\.venv\Scripts\python.exe -m pytest Tests/test_Expansion.py::ExpansionTests::test_should_perform_early_gather_to_tendrils__cramped --tb=no -q -s 2>&1 | .\GetLogsForScopeByTurn.ps1 -ScopeName "TileIsland update"

.EXAMPLE
    # Same but save to file for repeated analysis:
    .\.venv\Scripts\python.exe -m pytest Tests/test_Expansion.py::ExpansionTests::test_should_perform_early_gather_to_tendrils__cramped --tb=no -q -s 2>&1 | .\GetLogsForScopeByTurn.ps1 -ScopeName "TileIsland update" | Out-File -Encoding utf8 debug_output.txt

.EXAMPLE
    # Grep the extracted output for specific log keywords across all turns:
    .\.venv\Scripts\python.exe -m pytest ... 2>&1 | .\GetLogsForScopeByTurn.ps1 -ScopeName "TileIsland update" | Select-String "BACKREF|BUILD_BORDERS|REGISTER_LOOKUP|AssertionError"

.EXAMPLE
    # Read from a saved log file instead:
    .\GetLogsForScopeByTurn.ps1 -LogFilePath .\debug_output.txt -ScopeName "TileIsland update"

.NOTES
    - The script always appends any AssertionError or Traceback block that appears after the scope's
      Complete line within the same turn block, labelled "--- STACK TRACE ---".
    - Island unique IDs shift between test runs unless MapBase.DO_NOT_RANDOMIZE = True is set in the
      test BEFORE map loading.  Always set this when diagnosing island-related bugs so log IDs are
      stable across runs.
    - Diagnostic logging in TileIslandBuilder uses tile-position-based guards (e.g. _DIAG_TILES)
      rather than unique_id guards, so they remain valid across runs regardless of randomization.
#>
param(
    [Parameter(Mandatory=$false)]
    [string]$LogFilePath,

    [Parameter(Mandatory=$false)]
    [Alias("Scope")]
    [string]$ScopeName,

    [Parameter(Mandatory=$false)]
    [Alias("IncludeTurnTimingsSummary")]
    [switch]$IncludeTurnTimings,

    [Parameter(ValueFromPipeline=$true)]
    [string[]]$PipedInput
)

begin {
    $pipedLines = @()
}

process {
    if ($PipedInput) {
        $pipedLines += $PipedInput
    }
}

end {

# Read log content from piped input or file
if ($pipedLines.Count -gt 0) {
    $logContent = $pipedLines -join "`r`n"
} elseif ($LogFilePath) {
    if (-not (Test-Path $LogFilePath)) {
        Write-Error "Log file not found: $LogFilePath"
        exit 1
    }
    $logContent = Get-Content $LogFilePath -Raw
} else {
    Write-Error "Provide either -LogFilePath or pipe input into this script."
    exit 1
}

if (-not $ScopeName -and -not $IncludeTurnTimings) {
    Write-Error "Provide -ScopeName, -IncludeTurnTimings, or both."
    exit 1
}

function Get-TurnTimingsSummary {
    param(
        [Parameter(Mandatory=$true)]
        [string]$TurnContent,

        [Parameter(Mandatory=$true)]
        [string]$TurnNumber
    )

    $timingsMatch = [regex]::Match($TurnContent, "(?m)^\s*\d{2}:\d{2}\.\d+:\s*MOVE $([regex]::Escape($TurnNumber)) TIMINGS:\s*$")
    if (-not $timingsMatch.Success) {
        return $null
    }

    $summaryStartIndex = $timingsMatch.Index
    $prefixContent = $TurnContent.Substring(0, $timingsMatch.Index)
    $lastEndMarkerMatch = $null
    foreach ($endMarkerMatch in [regex]::Matches($prefixContent, $endPattern)) {
        $lastEndMarkerMatch = $endMarkerMatch
    }

    if ($lastEndMarkerMatch -ne $null) {
        $summaryStartIndex = $lastEndMarkerMatch.Index
    }

    $afterTimings = $TurnContent.Substring($timingsMatch.Index)
    $mainThreadMatch = [regex]::Match($afterTimings, "(?m)^\s*\d{2}:\d{2}\.\d+:\s*$\r?\n\s*vvv--------------vvv\s*$\r?\n\s*Beginning\s+t$([regex]::Escape($TurnNumber)):\s*Main thread check for pygame exit")
    $moveCompleteMatch = [regex]::Match($afterTimings, "(?m)^\s*(?:\d{2}:\d{2}\.\d+:\s*)?MOVE Complete:\s*$([regex]::Escape($TurnNumber))\b")

    $summaryEndIndex = $TurnContent.Length
    if ($mainThreadMatch.Success) {
        $summaryEndIndex = $timingsMatch.Index + $mainThreadMatch.Index
    }
    if ($moveCompleteMatch.Success) {
        $moveCompleteIndex = $timingsMatch.Index + $moveCompleteMatch.Index
        if ($moveCompleteIndex -lt $summaryEndIndex) {
            $summaryEndIndex = $moveCompleteIndex
        }
    }

    return $TurnContent.Substring($summaryStartIndex, $summaryEndIndex - $summaryStartIndex).Trim()
}

# Regex patterns
$turnPattern = '(?m)^\s*~~~\s*Turn (\d+)\s+\(([\d.]+)\)\s*~~~\s*$'
$beginPattern = '(?m)^\s*Beginning t\d+:\s([^\(]+)\s*\(([^\)]+)\)'
$completePattern = '(?m)^\s*Complete t\d+:\s\(([^\)]+)\)\s*([^\s]+)'
$vvvPattern = '(?m)^\s*vvv--------------vvv\s*$'
$endPattern = '(?m)^\s*\^\^\^--------------\^\^\^\s*$'

# Find all turns
$turnMatches = [regex]::Matches($logContent, $turnPattern)
$turns = @($turnMatches)  # Convert to array for IndexOf method
$scopeRegexPattern = $null
if ($ScopeName) {
    $scopeRegexParts = $ScopeName -split "\|" | ForEach-Object { [regex]::Escape($_) }
    $scopeRegexPattern = $scopeRegexParts -join "|"
}

if ($ScopeName) {
    Write-Host "Extracting logs for scope: $ScopeName"
} else {
    Write-Host "Extracting turn timings summaries"
}
Write-Host "Found $($turns.Count) turns in log file"

for ($turnIndex = 0; $turnIndex -lt $turns.Count; $turnIndex++) {
    $turn = $turns[$turnIndex]
    $turnNumber = $turn.Groups[1].Value
    $turnTiming = $turn.Groups[2].Value
    $turnStartIndex = $turn.Index

    # Find the next turn or end of file
    $nextTurnIndex = -1
    if ($turnIndex + 1 -lt $turns.Count) {
        $nextTurnIndex = $turns[$turnIndex + 1].Index
    }

    if ($nextTurnIndex -eq -1) {
        $turnContent = $logContent.Substring($turnStartIndex)
    } else {
        $turnContent = $logContent.Substring($turnStartIndex, $nextTurnIndex - $turnStartIndex)
    }

    $wroteTurnOutput = $false

    if ($ScopeName) {
        $scopeBeginPattern = "(?m)^\s*(?:\d{2}:\d{2}\.\d+:\s*)?Beginning(?:\s+t\d+)?:\s*([^\(]*(?:$scopeRegexPattern)[^\(]*)\s*\(([^\)]+)\)"
        $scopeBeginMatches = [regex]::Matches($turnContent, $scopeBeginPattern)
    } else {
        $scopeBeginMatches = @()
    }

    foreach ($scopeBeginMatch in $scopeBeginMatches) {
        $matchedScopeName = $scopeBeginMatch.Groups[1].Value.Trim()
        $scopeStartIndex = $scopeBeginMatch.Index

        # Find the first Complete statement that contains our scope name
        $remainingContent = $turnContent.Substring($scopeStartIndex)
        $lines = $remainingContent -split "`r`n"

        $scopeEndIndex = -1
        $currentPos = 0

        foreach ($line in $lines) {
            if ($line -match "^\s*(?:\d{2}:\d{2}\.\d+:\s*)?Complete(?:\s+t\d+)?:\s*\([^\)]+\)\s+$([regex]::Escape($matchedScopeName))\s*$") {
                $scopeEndIndex = $scopeStartIndex + $currentPos + $line.Length
                break
            }
            $currentPos += $line.Length + 2  # +2 for `r`n
        }

        if ($scopeEndIndex -ne -1) {
            $scopeContent = $turnContent.Substring($scopeStartIndex, $scopeEndIndex - $scopeStartIndex)

            Write-Output "       ~~~"
            Write-Output "       Turn $turnNumber   ($turnTiming)"
            Write-Output "       ~~~"
            Write-Output $scopeContent.Trim()
            $wroteTurnOutput = $true

            # Extract any AssertionError / Traceback that follows in the same turn block.
            # In piped pytest output, the full traceback arrives as a single long line with
            # embedded literal \r\n sequences, so we match both multi-line and single-line forms.
            $afterScope = $turnContent.Substring($scopeEndIndex)
            # Multi-line form (log files): grab Traceback block or AssertionError block
            $tracebackMatch = [regex]::Match($afterScope, '(?s)(Traceback \(most recent call last\)(?:\r?\n(?!\s*~~~).*)*|AssertionError[^\r\n]*(?:\r?\n(?!\s*~~~).*)*)')
            # Single-line form (piped): AssertionError: ... with embedded \r\n
            $assertMatch = [regex]::Match($afterScope, 'AssertionError:[^\r\n]+')
            if ($tracebackMatch.Success -or $assertMatch.Success) {
                Write-Output ""
                Write-Output "--- STACK TRACE ---"
                if ($tracebackMatch.Success) {
                    Write-Output $tracebackMatch.Value.Trim()
                } else {
                    # Expand embedded literal \r\n for readability
                    Write-Output ($assertMatch.Value.Trim() -replace '\\r\\n', "`n")
                }
                Write-Output "-------------------"
            }

            Write-Output ""
            Write-Output ""
        } else {
            Write-Host "WARNING: Could not find Complete statement for scope in turn $turnNumber"
            Write-Host $scopeBeginMatch.Value
        }
    }

    if ($IncludeTurnTimings) {
        $turnTimingsSummary = Get-TurnTimingsSummary -TurnContent $turnContent -TurnNumber $turnNumber
        if ($turnTimingsSummary) {
            if (-not $wroteTurnOutput) {
                Write-Output "       ~~~"
                Write-Output "       Turn $turnNumber   ($turnTiming)"
                Write-Output "       ~~~"
            } else {
                Write-Output "--- TURN TIMINGS SUMMARY ---"
            }
            Write-Output $turnTimingsSummary
            Write-Output ""
            Write-Output ""
        }
    }
}

Write-Host "Log extraction complete."

} # end of end{} block
