Set-StrictMode -Version Latest

Describe "GetLogsForScopeByTurn" {
    BeforeAll {
        $script:scriptPath = Join-Path $PSScriptRoot "GetLogsForScopeByTurn.ps1"
        $groupedLogsRoot = "D:\GeneralsLogs\GroupedLogs"

        if (-not (Test-Path $groupedLogsRoot)) {
            Set-ItResult -Skipped -Because "Grouped logs folder was not found: $groupedLogsRoot"
            return
        }

        $latestLogFolder = Get-ChildItem -Path $groupedLogsRoot -Directory |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($null -eq $latestLogFolder) {
            Set-ItResult -Skipped -Because "No grouped log folders were found in: $groupedLogsRoot"
            return
        }

        $script:logFilePath = Get-ChildItem -Path $latestLogFolder.FullName -File -Filter "*.txt" |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1 -ExpandProperty FullName

        if (-not $script:logFilePath) {
            Set-ItResult -Skipped -Because "No .txt log file was found in latest grouped log folder: $($latestLogFolder.FullName)"
            return
        }
    }

    It "Should load all logs for scope" {
        $output = & $script:scriptPath -LogFilePath $script:logFilePath -Scope "FLOW EXPAND!" | Out-String

        (([regex]::Matches($output, "Beginning t\d+:\s+FLOW EXPAND!")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "OrTools inproc\.solve\(\)")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "Complete t\d+:\s+\([\d\.]+\)\s+FLOW EXPAND!")).Count -gt 10) | Should Be $true
        ($output -notmatch "MOVE \d+ TIMINGS") | Should Be $true
    }

    It "Should load all logs for scope AND output timings" {
        $output = & $script:scriptPath -LogFilePath $script:logFilePath -Scope "FLOW EXPAND!" -IncludeTurnTimings | Out-String

        (([regex]::Matches($output, "Beginning t\d+:\s+FLOW EXPAND!")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "Complete t\d+:\s+\([\d\.]+\)\s+FLOW EXPAND!")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "MOVE \d+ TIMINGS")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "\.\d+ Expansion quick check")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "OVERALL TIME SPENT IN")).Count -gt 10) | Should Be $true
    }

    It "Should load JUST turn timings" {
        $output = & $script:scriptPath -LogFilePath $script:logFilePath -IncludeTurnTimings | Out-String

        ($output -notmatch "Beginning t\d+:\s+FLOW EXPAND!") | Should Be $true
        ($output -notmatch "Complete t\d+:\s+\([\d\.]+\)\s+FLOW EXPAND!") | Should Be $true
        (([regex]::Matches($output, "MOVE \d+ TIMINGS")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "\.\d+ Expansion quick check")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "OVERALL TIME SPENT IN")).Count -gt 10) | Should Be $true
        ($output -notmatch "Beginning t\d+:\s+Main thread check for pygame exit") | Should Be $true
        ($output -notmatch "MOVE Complete:\s+\d+") | Should Be $true
    }

    It "Should load multiple scopes" {
        $output = & $script:scriptPath -LogFilePath $script:logFilePath -Scope "FLOW EXPAND!|recalculating player path" | Out-String

        (([regex]::Matches($output, "Beginning t\d+:\s+FLOW EXPAND!")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "OrTools inproc\.solve\(\)")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "Complete t\d+:\s+\([\d\.]+\)\s+FLOW EXPAND!")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "Beginning t\d+:\s+recalculating player path")).Count -gt 10) | Should Be $true
        (([regex]::Matches($output, "Complete t\d+:\s+\([\d\.]+\)\s+recalculating player path")).Count -gt 10) | Should Be $true
        ($output -notmatch "MOVE \d+ TIMINGS") | Should Be $true
        ($output -notmatch "\.\d+ Expansion quick check") | Should Be $true
        ($output -notmatch "OVERALL TIME SPENT IN") | Should Be $true
    }
}
