

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
        [int]$PlayerIndex
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

    $trueMapPath = Join-Path $Map.Directory.FullName "$($Map.BaseName).truemap.txtmap"
    $giorPath = Join-Path $Map.Directory.FullName "$replayId.gior"
    $server = Get-ReplayServerFromLogFolder -LogFolderPath $Map.Directory.FullName

    # ReplayTxtmapDump walks S3 -> server /api/replay backup (only when
    # /api/serverSettings reports aws_replay_saving_down) -> S3, checks the
    # local replay_data/ outage fallback first, simulates to $Turn, and
    # refuses to write a "true" map that contradicts the bot's visible tiles.
    # A .gior already sitting in the log folder is reused instead of
    # re-downloading.
    $nodeArgs = @($dumper)
    if (Test-Path $giorPath)
    {
        $nodeArgs += @('--replay-file', $giorPath)
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
    Write-Host "dumping true map state for replay $replayId turn $Turn (server=$server)"
    $dumpOutput = & node @nodeArgs 2>&1
    $dumpOutput | ForEach-Object { Write-Host "    $_" }

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $trueMapPath))
    {
        Write-Warning "true-state dump failed for replay $replayId turn $Turn; generating test without a truemap."
        return $null
    }

    return Get-Item $trueMapPath
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

        $DestFolderRoot = $(Join-Path (Get-ConfiguredRepoRoot) 'Tests')
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
    if ($player -ne 'unk')
    {
        $trueMap = Invoke-ReplayTrueMapDump -Map $map -Turn ([int]$turn) -PlayerIndex ([int]$player)
        if ($null -ne $trueMap)
        {
            $trueMapName = $newName -replace '\.txtmap$', '.truemap.txtmap'
            $trueMap | Copy-Item -Destination "$DestFolder/$trueMapName" -ErrorAction Stop
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

    $testFileContent += @"

    def test_$TestName(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/$newName'
$trueMapFileLine
        $mapLoader

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=$turn)

        self.enable_search_time_limits_and_disable_debug_asserts()
        $simHostBuilder
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
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

        $DestFolderRoot = $(Join-Path (Get-ConfiguredRepoRoot) 'UnitTests')
    )

    Create-TestContinuingGameFrom -TestMapFile $TestMapFile -TestCategory $TestCategory -TestName $TestName -DestFolderRoot $DestFolderRoot
}