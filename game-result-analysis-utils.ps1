

#>
function Get-RunConfigFilePath {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\run_config.txt'))
}


function Initialize-RunConfig {
    if ($null -ne $Script:RunConfig) {
        return $Script:RunConfig
    }

    $configFile = Get-RunConfigFilePath
    if (-not (Test-Path $configFile)) {
        throw "Unable to find a run_config.txt file one folder above this script folder at $configFile."
    }

    $config = @{}
    $cfgContent = Get-Content -Path $configFile
    foreach ($line in $cfgContent) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        if ($line.TrimStart().StartsWith('#')) {
            continue
        }

        $separatorIndex = $line.IndexOf('=')
        if ($separatorIndex -lt 0) {
            continue
        }

        $key = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()
        if (-not [string]::IsNullOrWhiteSpace($key)) {
            $config[$key] = $value
        }
    }

    $Script:RunConfig = $config
    return $Script:RunConfig
}


function Get-RunConfigValue {
    Param(
        [Parameter(Mandatory = $true)]
        [string]$Key,
        $Default = $null
    )

    $config = Initialize-RunConfig
    if ($config.ContainsKey($Key)) {
        return $config[$Key]
    }

    return $Default
}


function Get-RunConfigPathValue {
    Param(
        [Parameter(Mandatory = $true)]
        [string]$Key,
        $Default = $null
    )

    $value = Get-RunConfigValue -Key $Key -Default $Default
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $value
    }

    return $value.TrimEnd([char[]]@('/', '\'))
}


function Get-ConfiguredRepoRoot {
    $defaultRepoRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
    return Get-RunConfigPathValue -Key 'repo_root' -Default $defaultRepoRoot
}


function Get-ConfiguredGroupedFolder {
    return Get-RunConfigPathValue -Key 'grouped_folder'
}


function Get-ConfiguredBotLogsRoot {
    $defaultBotLogsRoot = Join-Path ([System.IO.Path]::GetFullPath((Join-Path (Get-ConfiguredRepoRoot) '..'))) 'bot_logs'
    return Get-RunConfigPathValue -Key 'bot_logs_root' -Default $defaultBotLogsRoot
}


$null = Initialize-RunConfig


function Get-GeneralsRepoPath {
    $defaultGeneralsRepo = [System.IO.Path]::GetFullPath((Join-Path (Get-ConfiguredRepoRoot) '..\generals'))
    return Get-RunConfigPathValue -Key 'generals_repo' -Default $defaultGeneralsRepo
}


function Get-GeneralsEventsRepoPath {
    $defaultGeneralsEventsRepo = [System.IO.Path]::GetFullPath((Join-Path (Get-GeneralsRepoPath) 'generals-events'))
    return Get-RunConfigPathValue -Key 'generals_events_repo' -Default $defaultGeneralsEventsRepo
}


function Get-ReplayDumpCacheRoot {
    # Replay-derived analysis artifacts (.gior downloads, .truemap.txtmap dumps)
    # live here instead of inside the game log folders: writing into a grouped
    # log folder bumps its LastWriteTime, which makes long-finished games look
    # freshly modified in Explorer's sort-by-date. Entries auto-expire - see
    # Clear-OldReplayDumpCache.
    return 'C:\cascade-debug-output\generals-bot\replay-dump-cache'
}


function Get-ReplayDumpCacheFolder {
    Param(
        [Parameter(Mandatory = $true)]
        [string]$ReplayId
    )

    $folder = Join-Path (Get-ReplayDumpCacheRoot) $ReplayId
    if (-not (Test-Path $folder)) {
        $null = New-Item -ItemType Directory -Path $folder -Force
    }
    return $folder
}


function Clear-OldReplayDumpCache {
    # Cached dumps are disposable (re-downloaded/re-dumped on demand), so
    # entries older than MaxAgeDays are deleted instead of accumulating.
    Param(
        [int]$MaxAgeDays = 7
    )

    $root = Get-ReplayDumpCacheRoot
    if (-not (Test-Path $root)) {
        return
    }
    $cutoff = (Get-Date).AddDays(-$MaxAgeDays)
    Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    # Drop per-replay folders left empty by the file sweep.
    Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.GetFileSystemInfos().Count -eq 0 } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}


function Get-ReplayServerFromLogFolder {
    Param(
        [Parameter(Mandatory = $true)]
        [string]$LogFolderPath
    )

    # The bot log records the websocket it connected to; that identifies which
    # region's replay bucket/backup holds the game. Detection only tunes the
    # order the dumper probes sources in - 'auto' always works, just slower.
    $logFile = Get-ChildItem -Path $LogFolderPath -Filter '_*.txt' -ErrorAction Ignore | Select-Object -First 1
    if ($null -eq $logFile)
    {
        return 'auto'
    }

    if (Select-String -Path $logFile.FullName -Pattern 'botws\.generals\.io|bot\.generals\.io' -List -Quiet)
    {
        return 'bot'
    }
    if (Select-String -Path $logFile.FullName -Pattern 'euws\.generals\.io|eu\.generals\.io' -List -Quiet)
    {
        return 'eu'
    }
    if (Select-String -Path $logFile.FullName -Pattern 'ws://localhost|ws://127\.0\.0\.1|localhost:8080|127\.0\.0\.1:8080' -List -Quiet)
    {
        return 'loc'
    }
    if (Select-String -Path $logFile.FullName -Pattern 'ws\.generals\.io|us\.generals\.io' -List -Quiet)
    {
        return 'na'
    }

    return 'auto'
}


function Invoke-ReplayTrueMapDump {
    Param(
        [Parameter(Mandatory = $true)]
        $Map,

        [Parameter(Mandatory = $true)]
        [int]$Turn,

        [Parameter(Mandatory = $true)]
        [int]$PlayerIndex,

        [int]$MovesTurns = 25,

        # ScanRecentGamesForFogDesyncs.ps1 fallback: dumps the sim state without
        # cross-checking the bot's visible tiles (needed when the client viewed
        # the board rotated 90 degrees and every orientation fails the verify -
        # a pre-existing ReplayTxtmapDump gap). The truemap is written in
        # canonical orientation; callers must validate turn alignment via the
        # dumped {c}Score/{c}Tiles footers themselves.
        [switch]$NoVerify
    )

    # Grouped log folders are named "<desc>---<replayId>"; without that suffix
    # there is no replay to pull the true board state from.
    $replayId = ($Map.Directory.BaseName -split '---') | Select-Object -Last 1
    if ([string]::IsNullOrWhiteSpace($replayId) -or $replayId -eq $Map.Directory.BaseName)
    {
        return $null
    }

    $generalsEventsRepo = Get-GeneralsEventsRepoPath
    $dumper = Join-Path (Get-ConfiguredRepoRoot) 'ReplayTools\ReplayTxtmapDump.js'
    if (-not (Test-Path $dumper))
    {
        Write-Warning "ReplayTxtmapDump.js not found at $dumper; skipping true-state dump."
        return $null
    }

    if ($null -eq (Get-Command node -ErrorAction SilentlyContinue))
    {
        Write-Warning "node not on PATH; skipping true-state replay dump for $replayId."
        return $null
    }

    # Cache cleanup is once per session - a fog-desync scan can invoke this
    # dozens of times and the sweep is pure waste on repeat calls.
    if (-not $Script:ReplayDumpCacheCleaned) {
        Clear-OldReplayDumpCache
        $Script:ReplayDumpCacheCleaned = $true
    }

    # Dump artifacts go to the replay cache, never the game log folder (see
    # Get-ReplayDumpCacheRoot). The <turn>.truemap.txtmap naming convention is
    # kept, just under <cache>/<replayId>/.
    $cacheFolder = Get-ReplayDumpCacheFolder -ReplayId $replayId
    $trueMapPath = Join-Path $cacheFolder "$($Map.BaseName).truemap.txtmap"
    $giorPath = Join-Path $cacheFolder "$replayId.gior"
    $legacyGiorPath = Join-Path $Map.Directory.FullName "$replayId.gior"
    $server = Get-ReplayServerFromLogFolder -LogFolderPath $Map.Directory.FullName

    # ReplayTxtmapDump walks S3 -> server /api/replay backup (only when
    # /api/serverSettings reports aws_replay_saving_down) -> S3, checks the
    # local replay_data/ outage fallback first, simulates to $Turn, and
    # refuses to write a "true" map that contradicts the bot's visible tiles.
    # A cached .gior is reused instead of re-downloading; a .gior left in the
    # log folder by older runs is still read (read-only), but new downloads
    # always land in the cache.
    $nodeArgs = @($dumper)
    if (Test-Path $giorPath)
    {
        $nodeArgs += @('--replay-file', $giorPath)
    }
    elseif (Test-Path $legacyGiorPath)
    {
        $nodeArgs += @('--replay-file', $legacyGiorPath)
    }
    else
    {
        $nodeArgs += @(
            '--replay-id', $replayId,
            '--server', $server,
            '--save-replay', $giorPath
        )
    }
    $nodeArgs += @(
        '--turn', "$Turn",
        '--player-index', "$PlayerIndex",
        '--generals-events-repo', $generalsEventsRepo,
        '--out', $trueMapPath,
        '--copy-data-from', $Map.FullName
    )
    if ($NoVerify)
    {
        $nodeArgs += '--no-verify'
    }
    if ($MovesTurns -gt 0)
    {
        $nodeArgs += @('--moves-turns', "$MovesTurns")
    }
    Write-Host "dumping true map state for replay $replayId turn $Turn (server=$server)"
    $dumpOutput = & node @nodeArgs 2>&1

    # MOVES|<playerIndex>|<queue_player_moves_str>|<username> marker lines list
    # the moves each player successfully executed over the next MovesTurns
    # turns, in the same coordinates as the dumped truemap.
    $movesByPlayer = @()
    foreach ($line in $dumpOutput)
    {
        if ("$line".StartsWith('MOVES|'))
        {
            $parts = "$line".Substring(6).Split('|', 3)
            $movesByPlayer += [PSCustomObject]@{
                PlayerIndex = [int]$parts[0]
                Moves = $parts[1]
                Username = $parts[2]
            }
        }
    }
    $dumpOutput | ForEach-Object { Write-Host "    $_" }

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $trueMapPath))
    {
        Write-Warning "true-state dump failed for replay $replayId turn $Turn; generating test without a truemap."
        return $null
    }

    return [PSCustomObject]@{ Map = (Get-Item $trueMapPath); Moves = $movesByPlayer }
}


function Copy-Turn25StartResultsToUnitTest {
    Param(
        $DestFolder = $(Join-Path (Join-Path (Get-ConfiguredRepoRoot) 'Tests') 'EarlyExpandUtilsTestMaps/SampleTurn25MapsToTryToBeat'),
        $LogFolder = $(Get-ConfiguredGroupedFolder)
    )

    $items = Get-ChildItem -Path $LogFolder -Recurse -Filter '50.txtmap'
    foreach ($item in $items)
    {
        if (-not $item.DirectoryName.Contains('---'))
        {
            Write-Host "skipped - $($item.DirectoryName)"
            continue
        }

        $newName = ($item.DirectoryName -split '---') | Select -Last 1
        if ($newName.Contains('GroupedLogs'))
        {
            # then this is a log folder from an old bot, I think?
            Write-Host "skipped - newName $newName, folder $($folder.BaseName)"
            continue
        }

        $item | Copy-Item -Destination "$DestFolder/$newName.txtmap"
    }
}


function Copy-WinMapsToWonMapsDirectory {
    Param(
        $DestFolder = $(Join-Path (Join-Path (Get-ConfiguredRepoRoot) 'Tests') 'WonFullMapVisionSampleMaps'),
        $LogFolder = $(Get-ConfiguredGroupedFolder)
    )

    if (-not (Test-Path $DestFolder))
    {
        mkdir $DestFolder -Force
    }

    $folders = Get-ChildItem -Path $LogFolder -Directory
    foreach ($folder in $folders)
    {
        $mapFiles = Get-ChildItem -Path $folder.FullName -Filter '*.txtmap'
        $maxFileInt = $mapFiles.BaseName | % { [int] $_ } | Sort -Descending | Select -First 1
        $maxFileName = "$maxFileInt.txtmap"
        $maxFileName
        $maxFilePath = "$($folder.FullName)/$maxFileName"
        $contentLines = Get-Content -Path $maxFilePath | Select -Skip 1
        $countsByPlayer = @{
            ([char]'a') = 0;
            ([char]'b') = 0;
            ([char]'c') = 0;
            ([char]'d') = 0;
            ([char]'e') = 0;
            ([char]'f') = 0;
            ([char]'g') = 0;
            ([char]'h') = 0;
        }

        foreach ($contentLine in $contentLines)
        {
            if ($contentLine.Contains('|'))
            {
                break;
            }

            foreach ($char in $contentLine.ToCharArray())
            {
                if ([char]::IsUpper($char))
                {
                    continue
                }

                if ($countsByPlayer.ContainsKey([char]$char))
                {
                    $count = $countsByPlayer[[char]$char]
                    $countsByPlayer[[char]$char] = $count + 1
                }
            }
        }

        $foundPlayer = $null
        $wasWin = $false
        foreach ($char in $countsByPlayer.Keys)
        {
            $count = $countsByPlayer[$char]
            if ($count -gt 0)
            {
                if ($null -ne $foundPlayer)
                {
                    $wasWin = $false
                    break
                }

                $wasWin = $true

                $foundPlayer = $char
            }
        }

        if (-not $wasWin)
        {
            continue
        }

        if (-not $folder.BaseName.Contains('---'))
        {
            Write-Host "skipped - $($folder.BaseName)"
            continue
        }

        $newName = ($folder.BaseName -split '---') | Select -Last 1
        if ($newName.Contains('GroupedLogs'))
        {
            # then this is a log folder from an old bot, I think?
            Write-Host "skipped - newName $newName, folder $($folder.BaseName)"
            continue
        }

        $newName = "$newName---$foundPlayer--$maxFileInt"
        Copy-Item -Path $maxFilePath -Destination "$DestFolder/$newName.txtmap"
    }
}

function Create-ManyTestsByTurnFromFolders {
    Param(
        $TestNamePrefix = "",
        $TestCategory = "",
        $Turn = 1,
        $LogFolderRoot = $(Get-ConfiguredBotLogsRoot),
        $DestFolderRoot = $(Join-Path (Get-ConfiguredRepoRoot) 'Tests')
    )

    $folders = foreach ($f in Get-ChildItem $LogFolderRoot -Directory)
    {
        $f.FullName
    }

    foreach ($folder in $folders) {
        $safeNameEnd = $folder.split('---')[1].replace('-', '_')
        $testName = "$($TestNamePrefix)__$($Turn)__$($safeNameEnd)"

        "$folder/$turn.txtmap" | Create-TestContinuingGameFrom -TestName $testName -TestCategory $TestCategory
    }
}

function Create-TestContinuingGameFrom {
    [Alias("ctc")]
    Param(
        [Parameter(ValueFromPipeline = $true)]
        $TestMapFile = "path to test map file or log screenshot file",

        [Parameter(Position=0)]
        $TestCategory = "BotBehavior",

        [Parameter(Position=1)]
        $TestName = "shouldnt_die_in_some_scenario",

        $DestFolderRoot = $(Join-Path (Get-ConfiguredRepoRoot) 'Tests'),

        [int]$MovesTurns = 25
    )

    $TestName = $TestName.Replace(' ', '_')

    $destFolderRootPath = [System.IO.Path]::GetFullPath($DestFolderRoot)
    if ([System.IO.Path]::GetFileName($destFolderRootPath) -ieq 'UnitTests') {
        $destFolderRootPath = Join-Path ([System.IO.Path]::GetDirectoryName($destFolderRootPath)) 'Tests'
    }
    $destFolder = Join-Path $destFolderRootPath 'GameContinuationEntries'
    if (-not (Test-Path $destFolder))
    {
        mkdir $destFolder -Force
    }

    if ($TestMapFile.EndsWith('png'))
    {
        $TestMapFile = $TestMapFile.Replace(".png", ".txtmap")
    }
    elseif ($TestMapFile.EndsWith('.txtmap'))
    {
        # no op
    }
    else
    {
        $TestMapFile = "$($TestMapFile).txtmap"
    }

    $map = Get-Item $TestMapFile -ErrorAction Ignore
    if ($null -eq $map)
    {
        Write-Warning "Unable to load $TestMapFile"
        return
    }

    $turn = $map.BaseName


    $is2v2 = $false
    $player = 'unk'
    $content = $map | Get-Content
    foreach ($line in $content)
    {
        if ($line -like '*player_index*')
        {
            $player = $line.Split('=')[1].Trim()
        }

        if ($line -like '*mode=team*')
        {
            $is2v2 = $true
        }
    }

    if ($player -eq 'unk')
    {
        Write-Warning "Unable to load $testFile player"
    }

    $newName = ($map.Directory.BaseName -split '---') | Select -Last 1
    $newName = "$newName---$player--$turn"
    $newName = "$($TestName)___$newName.txtmap"
    $map | Copy-Item -Destination "$DestFolder/$newName" -ErrorAction Stop

    # Pull the replay for this game and dump the TRUE board state at this turn
    # as a sibling .truemap.txtmap. The generated test keeps the bot's exported
    # map for vision + resume state but runs the simulator against real state,
    # so wrong fog guesses get corrected by actually-discovered tiles instead
    # of being baked into the sim's ground truth.
    $trueMapName = $null
    $replayMoves = $null
    if ($player -ne 'unk')
    {
        $dumpResult = Invoke-ReplayTrueMapDump -Map $map -Turn ([int]$turn) -PlayerIndex ([int]$player) -MovesTurns $MovesTurns
        if ($null -ne $dumpResult)
        {
            $trueMapName = $newName -replace '\.txtmap$', '.truemap.txtmap'
            $dumpResult.Map | Copy-Item -Destination "$DestFolder/$trueMapName" -ErrorAction Stop
            $replayMoves = $dumpResult.Moves
        }
    }

    $testFile = "$DestFolderRoot/test_$TestCategory.py"
    $testFileContent = Get-Content $testFile -Raw -ErrorAction Stop

    $countsByPlayer = @{
        ([char]'a') = 0;
        ([char]'b') = 0;
        ([char]'c') = 0;
        ([char]'d') = 0;
        ([char]'e') = 0;
        ([char]'f') = 0;
        ([char]'g') = 0;
        ([char]'h') = 0;
    }

    # The simulator's ground-truth map comes from the replay-dumped truemap
    # when we have one; the bot's exported mapFile still supplies the fogged
    # vision map and the serialized bot state the bot resumes from.
    $simMapFileVar = 'mapFile'
    $trueMapFileLine = ''
    if ($null -ne $trueMapName)
    {
        $simMapFileVar = 'trueMapFile'
        $trueMapFileLine = "        trueMapFile = 'GameContinuationEntries/$trueMapName'"
    }

    $mapLoader = "map, general, enemyGeneral = self.load_map_and_generals($simMapFileVar, $turn, fill_out_tiles=True)"
    $baseAssert = "self.assertNoFriendliesKilled(map, general)"
    $simHostBuilder = 'simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)'


    if ($is2v2) {
        $mapLoader = "map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2($simMapFileVar, $turn, fill_out_tiles=True)"
        $baseAssert = "self.assertNoFriendliesKilled(map, general, allyGen)"
        $simHostBuilder = "simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True, teammateNotAfk=False)"
    }

    # Replay-recorded moves for the MovesTurns turns after the imported turn are
    # queued per player so the sim replays what every opponent actually did
    # (queued moves still execute for forced-AFK players). The bot's own real
    # line is emitted commented out - uncommenting it reproduces history.
    $queueMoveLines = "        simHost.queue_player_moves_str(enemyGeneral.player, 'None')"
    if ($null -ne $replayMoves -and $replayMoves.Count -gt 0)
    {
        $queueMoveLines = "        # replay moves for the $MovesTurns turns after turn $turn`n"
        foreach ($entry in $replayMoves)
        {
            if ($entry.PlayerIndex -eq [int]$player)
            {
                $queueMoveLines += "        # simHost.queue_player_moves_str(general.player, '$($entry.Moves)')  # replay line for $($entry.Username)`n"
            }
            else
            {
                $queueMoveLines += "        simHost.queue_player_moves_str($($entry.PlayerIndex), '$($entry.Moves)')  # replay moves: $($entry.Username)`n"
            }
        }
        $queueMoveLines = $queueMoveLines.TrimEnd("`n")
    }

    $testFileContent += @"

    def test_$TestName(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/$newName'
$trueMapFileLine
        $mapLoader

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=$turn)

        self.enable_search_time_limits_and_disable_debug_asserts()
        $simHostBuilder
$queueMoveLines
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)
        $baseAssert

        self.skipTest("TODO add asserts for $TestName")
"@

    $testFileContent | Set-Content $testFile -Encoding utf8
}


function Create-UnitTestContinuingGameFrom {
    [Alias("cuc")]
    Param(
        [Parameter(ValueFromPipeline = $true)]
        $TestMapFile = "path to test map file or log screenshot file",

        [Parameter(Position=0)]
        $TestCategory = "BotBehavior",

        [Parameter(Position=1)]
        $TestName = "shouldnt_die_in_some_scenario",

        $DestFolderRoot = $(Join-Path (Get-ConfiguredRepoRoot) 'UnitTests'),

        [int]$MovesTurns = 25
    )

    Create-TestContinuingGameFrom -TestMapFile $TestMapFile -TestCategory $TestCategory -TestName $TestName -DestFolderRoot $DestFolderRoot -MovesTurns $MovesTurns
}