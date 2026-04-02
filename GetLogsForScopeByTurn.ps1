param(
    [Parameter(Mandatory=$true)]
    [string]$LogFilePath,

    [Parameter(Mandatory=$true)]
    [string]$ScopeName
)

# Read the log file
if (-not (Test-Path $LogFilePath)) {
    Write-Error "Log file not found: $LogFilePath"
    exit 1
}

$logContent = Get-Content $LogFilePath -Raw

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
Write-Host ""

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

            Write-Host "       ~~~"
            Write-Host "       Turn $turnNumber   ($turnTiming)"
            Write-Host "       ~~~"
            Write-Host $scopeContent.Trim()
            Write-Host ""
            Write-Host ""
        } else {
            Write-Host "WARNING: Could not find Complete statement for scope in turn $turnNumber"
            Write-Host $scopeBeginMatch.Value
        }
    }
}

Write-Host "Log extraction complete."
