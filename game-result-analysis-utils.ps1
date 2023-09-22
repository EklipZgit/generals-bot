<#

#>
function Copy-Turn25StartResultsToUnitTest {
    Param(
        $DestFolder = "D:\2019_reformat_Backup\generals-bot\Tests\EarlyExpandUtilsTestMaps\SampleTurn25MapsToTryToBeat",
        $LogFolder = "D:\GeneralsLogs\GroupedLogs"
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
        
        $item | Copy-Item -Destination "$DestFolder\$newName.txtmap"
    }
}


function Copy-WinMapsToWonMapsDirectory {
    Param(
        $DestFolder = "D:\2019_reformat_Backup\generals-bot\Tests\WonFullMapVisionSampleMaps",
        $LogFolder = "D:\GeneralsLogs\GroupedLogs"
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
        Copy-Item -Path $maxFilePath -Destination "$DestFolder\$newName.txtmap"
    }
}

function Create-ManyTestsByTurnFromFolders {
    Param(
        $TestNamePrefix = "",
        $TestCategory = "",
        $Turn = 1,
        $LogFolderRoot = "D:\GeneralsLogs\GroupedLogs\",
        $DestFolderRoot = "D:\2019_reformat_Backup\generals-bot\Tests\"
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
    Param(
        [Parameter(ValueFromPipeline = $true)]
        $TestMapFile = "path to test map file",

        $TestName = "shouldnt_die_in_some_scenario",

        $TestCategory = "Defense",

        $DestFolderRoot = "D:\2019_reformat_Backup\generals-bot\Tests\"
    )

    $destFolder = "$DestFolderRoot\GameContinuationEntries"
    if (-not (Test-Path $destFolder))
    {
        mkdir $destFolder -Force
    }

    if ($TestMapFile.EndsWith('png'))
    {
        $TestMapFile = $TestMapFile.Replace(".png", ".txtmap")
    }
    
    $map = Get-Item $TestMapFile -ErrorAction Ignore
    if ($null -eq $map)
    {
        Write-Warning "Unable to load $TestMapFile"
        return        
    }

    $turn = $map.BaseName

    $player = 'unk'
    $content = $map | Get-Content
    foreach ($line in $content)
    {
        if ($line -like '*bot_player_index*')
        {
            $player = $line.Split('=')[1].Trim()
        }
    }

    if ($player -eq 'unk')
    {
        Write-Warning "Unable to load $testFile player"
    }

    $newName = ($map.Directory.BaseName -split '---') | Select -Last 1
    $newName = "$newName---$player--$turn"
    $newName = "$($TestName)___$newName.txtmap"
    $map | Copy-Item -Destination "$DestFolder\$newName" -ErrorAction Stop

    $testFile = "$DestFolderRoot\test_$TestCategory.py"
    $testFileContent = Get-Content $testFile -ErrorAction Stop

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

    $testFileContent += @"
    
    def test_$TestName(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/$newName'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, $turn, fill_out_tiles=True)

        self.enable_search_time_limits_and_disable_debug_asserts()

        rawMap, _ = self.load_map_and_general(mapFile, $turn)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode, turn_time=2.0, turns=15)
        self.assertIsNone(winner)

        # TODO add asserts for $TestName
"@

    $testFileContent | Set-Content $testFile -Encoding utf8
}
