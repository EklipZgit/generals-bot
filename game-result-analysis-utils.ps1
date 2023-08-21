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
        $newName = ($item.DirectoryName -split '---') | Select -Last 1
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

        $newName = ($folder.BaseName -split '---') | Select -Last 1
        $newName = "$newName---$foundPlayer--$maxFileInt"
        Copy-Item -Path $maxFilePath -Destination "$DestFolder\$newName.txtmap"
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
    
    $map = Get-Item $TestMapFile
    $turn = $map.BaseName

    $earlyFile = Get-Item "$($map.Directory.FullName)/20.txtmap"
    $earlyContent = $earlyFile | get-content -raw
    $match = $earlyContent -cmatch '[a-h]G'
    $player = $MATCHES[0].Trim('G')

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
        debugMode = True
        mapFile = 'GameContinuationEntries/$newName'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, $turn)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, $turn)
        
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap)

        # simHost.make_player_afk(enemyGeneral.player)

        # alert enemy of the player general
        simHost.sim.reveal_player_general(playerToReveal=general.player, playerToRevealTo=enemyGeneral.player)

        self.begin_capturing_logging()
        simHost.run_sim(run_real_time=debugMode, turn_time=2.0)

        # TODO add asserts for $TestName
"@

    $testFileContent | Set-Content $testFile -Encoding utf8
}
