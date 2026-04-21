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

    [Parameter(Mandatory=$true)]
    [string]$ScopeName,

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

# Regex patterns
$turnPattern = '(?m)^\s*~~~\s*Turn (\d+)\s+\(([\d.]+)\)\s*~~~\s*$'
$beginPattern = '(?m)^\s*Beginning:\s*([^\(]+)\s*\(([^\)]+)\)'
$completePattern = '(?m)^\s*Complete:\s*\(([^\)]+)\)\s*([^\s]+)'
$vvvPattern = '(?m)^\s*vvv--------------vvv\s*$'
$endPattern = '(?m)^\s*\^\^\^--------------\^\^\^\s*$'

# Find all turns
$turnMatches = [regex]::Matches($logContent, $turnPattern)
$turns = @($turnMatches)  # Convert to array for IndexOf method

Write-Host "Extracting logs for scope: $ScopeName"
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

    # Find the target scope within this turn
    $scopeBeginPattern = "Beginning:\s*([^\(]*$([regex]::Escape($ScopeName))[^\(]*)\s*\(([^\)]+)\)"
    $scopeBeginMatch = [regex]::Match($turnContent, $scopeBeginPattern)

    if ($scopeBeginMatch.Success) {
        $scopeStartIndex = $scopeBeginMatch.Index

        # Find the first Complete statement that contains our scope name
        $remainingContent = $turnContent.Substring($scopeStartIndex)
        $lines = $remainingContent -split "`r`n"

        $scopeEndIndex = -1
        $currentPos = 0

        foreach ($line in $lines) {
            if ($line -match "Complete:\s*\([^\)]+\)\s+$([regex]::Escape($ScopeName))") {
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
}

Write-Host "Log extraction complete."

} # end of end{} block
