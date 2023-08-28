


function Run-BotOnce { 
    Param(
        $name, 
        $game, 
        [switch]$public, 
        [switch]$right, 
        $privateGame, 
        [switch]$noui,
        $path = "D:\2019_reformat_Backup\generals-bot\BotHost.py",
        $userID = $null,
        [switch]$nolog,
        [switch]$publicLobby
    )
    $df = Get-Date -format yyyy-MM-dd_hh-mm-ss 
    $arguments = [System.Collections.ArrayList]::new()
    if ($privateGame) {
        $game = "private"
        if ($publicLobby)
        {
            $game = "custom"
        }
        [void] $arguments.Add("--roomID")
        [void] $arguments.Add($privateGame)
    }
    if ($userID) {
        [void] $arguments.Add("--userid")
        [void] $arguments.Add($userID)
    }
    if ($right) { [void] $arguments.Add("--right") }
    if ($noui) { [void] $arguments.Add("--no-ui") }
    if ($public) { 
        [void] $arguments.Add("--public")
    }
    $arguments = $arguments.ToArray()
    $argString = $([string]::Join(" ", $arguments))
    Write-Verbose $argString -Verbose
    $host.ui.RawUI.WindowTitle = "$($name.Replace('[Bot]', '').Trim()) - $game"

    # this exeString is a hack due to the powershell memory leak, need to keep opening new PS processes
    # or we fill up memory to 1GB per powershell window overnight :(
    # Maybe fixed in PS 5.2? Wouldn't know because can't install on win8 lul

    $exeString = @"
    `$name = '$name'
    `$game = '$game'
    `$df = '$df'
    `$privateGame = '$privateGame'
    `$argString = '$argString'
    `$path = '$path'
    `$arguments = @('$([string]::Join("', '", $arguments))')
    Write-Output "arguments $([string]::Join(', ', $arguments))"
    `$cleanName = '$name'.Replace('[', '').Replace(']', '')
    `$logName = "`$cleanName-$game-$df$privateGame"
    `$logFile = "`$logName.txt"
    `$logPath = "D:\GeneralsLogs\`$logFile"

    if (-not `$$($nolog.ToString()))
    {
        Start-Transcript -path "`$logPath"
    }

    try 
    {
        #Write-Verbose `"python.exe $path -name $name -g $game $argString`" -verbose
        python.exe "$path" -name '$name' -g '$game' @arguments 2>&1 
    } 
    catch 
    {
        Write-Error `$_
    }
    finally 
    {    
        if (-not `$$($nolog.ToString()))
        {
            stop-transcript
            `$content = Get-Content `$logPath
            `$prevLine = [string]::Empty
            `$repId = `$null
            `$newContent = foreach (`$line in `$content)
            {
                if (`$line -ne [string]::Empty)
                {
                    `$prevLine = `$line
                    `$line
                    if (`$repId -eq `$null -and `$line -match '''replay_id'': ''([^'']+)''')
                    {
                        `$repId = `$Matches[1]
                    }
                }
                elseif (`$prevLine -eq [string]::Empty)
                {
                    `$line
                    `$prevLine = `"h`"
                }
                else 
                {
                    `$prevLine = [string]::Empty
                }
            }

            if (`$repId -and (`$path -notlike '*historical*'))
            {
                `$folder = Get-ChildItem "D:\GeneralsLogs" -Filter "*`$repId*" -Directory
                `$newLogPath = Join-Path `$folder.FullName "_`$logFile"
                `$newContent | Set-Content -Path `$newLogPath -Force
                `$null = mkdir D:\GeneralsLogs\GroupedLogs -Force
                `$newFolder = Move-Item `$folder.FullName "D:\GeneralsLogs\GroupedLogs" -PassThru
                `$newName = "`$logName---`$repId"
                Rename-Item `$newFolder.FullName `$newName -PassThru
                Write-Warning "`$newName"
                Write-Warning "`$newName"
                Write-Warning "`$newName"
            }

            Remove-Item `$logPath -Force
        }
    }

    Start-Sleep -Seconds 1

    Get-ChildItem "D:\GeneralsLogs" | 
        ? { `$_.FullName -notlike '*_chat*' } | 
        ? { `$_.LastWriteTime -lt (get-date).AddMinutes(-120) } | 
        Remove-Item -Force -Recurse -ErrorAction Ignore
    
    Get-ChildItem "D:\GeneralsLogs\GroupedLogs" -Directory | 
        ? { `$_.FullName -notlike '*_chat*' } | 
        ? { `$_.LastWriteTime -lt (get-date).AddMinutes(-120) } |
        Remove-Item -Force -Recurse -ErrorAction Ignore
"@

    $randNums = 1..10 | Get-Random -Count 10
    $randName = $randNums -join ''
    $ps1File = "D:\2019_reformat_Backup\temp\$randName.ps1"
    $exeString | Out-File $ps1File
    Write-Verbose $ps1File -Verbose
    start Powershell "-File $ps1File" -Wait -NoNewWindow
    Write-Verbose 'Powershell finished, sleeping' -Verbose
}



function Run-SoraAI {
    Param(
        $game = @('1v1', '1v1', 'ffa', 'ffa')
    )
    while ($true)
    {
        foreach ($g in $game)
        {
            run-botonce -game $g -name "[Bot] Sora_ai_ek" -userID "EKSORA" -path "D:\2019_reformat_Backup\Sora_AI\run_bot.py" -nolog
        }
    }
}


function Run-Blob {
    Param(
        $game = @('ffa')
    )
    while ($true)
    {
        foreach ($g in $game)
        {
            run-botonce -game $g -name "PurdBlob" -path "D:\2019_reformat_Backup\generals-blob-and-path\bot_blob.py" -nolog -noui
        }
    }
}


function Start-WindowsTerminalAltBots {
    Param(
    )
    # starts a windows terminal that runs the FFA bots and a second instance of Sora AI that joins 1v1s
    wt -w AltBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'Run-Blob -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    # time for the terminal window to open
    start-sleep -seconds 3
    wt -w AltBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'Run-Path -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    wt -w AltBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'Run-SoraAI -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    wt -w AltBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'Run-SoraAI -game 1v1,ffa,1v1'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
}



# starts a windows terminal that runs many historical versions of EklipZ_ai
function Start-WindowsTerminalHistoricalBots {
    Param(
    )

    <#
    original timings and bugs from 2019, with connection code fixed
    #>
    wt -w HistBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1, 1v1, 1v1, ffa -name "EklipZ_ai_14" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-07-24\bot_ek0x45.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    # time for the terminal window to open
    start-sleep -seconds 3

    <#
    more frequent 100 cycle timings, no quick-expand at all
    all in based on enemy took city too aggressively, 
    prioritize enemy tiles in path again, 
    explore undiscovered starting turn 50 instead of 100
    de-prioritize fog undiscovered upon discovering nearby neutrals. 
        Increase army emergence fog distance to 10 from 6, first 3 tiles into undiscovered get same rating
    #>
    wt -w HistBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1, 1v1, ffa -name "EklipZ_ai_13" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-07-29\bot_ek0x45.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    <#
    Hopefully defense off-by-one threat detection fixed
    Additional panic gather defense added, defense now negatives all tiles in shortest path on attack path
    undiscovered priority improvements
    AGGRESSIVELY take cities while cramped. Cramped detection takes into account the distance to enemy territory
    gather to enemy tiles inside territory more aggressively
    play turns 25-50 more aggressively (too aggressively?)
    #>
    wt -w HistBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1, ffa, 1v1 -name "EklipZ_ai_12" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-07-31\bot_ek0x45.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    <#
    improved 'vision tile' kill gathers to only gather for the quickexpand turns, and are included in the main gather phase with a 2 
        tile exclusion radius around them to prioritize killing them over gather path gather movement if adequate tile counts are near them.
    #>
    wt -w HistBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1, ffa, 1v1, 1v1 -name "EklipZ_ai_11" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-08-04\BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    <#
    semi-optimal first 25, unit tests
    #>
    wt -w HistBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1, ffa, 1v1, 1v1, ffa, 1v1, 1v1 -name "EklipZ_ai_10" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-08-07\BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    <#
    tweaked gathers taking neutral / enemy tiles to include extra gather moves.
    tweaked initial expansion.
    tweaked optimal_expansion to include move-half when appropriate and draw the boundaries for when move-half is limited to closer-only moves and when it is limited to flankpath-or-closer-only moves.
    reduced neutral city aggressiveness right before launch timings.
    #>
    wt -w HistBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1, ffa, 1v1, ffa, 1v1, 1v1, 1v1 -name "EklipZ_ai_09" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-08-08\BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    more optimal first 25
    defense gathers...?
    improved economy defense to make sure that it doesn't leave its king undefended while switching to hunt mode
    tons of code refactors
    much better map data in map state log
    map data loader
    first get_optimal_expansion unit test +
        bugfixed early expansion not using 2's
    Army Engine, brute force, all known bugs fixed except repetition being undervalued vs end board state.
    Bugfixed tons of fog army issues
    Bugfixed tile delta issues
    iterative gather pruning (still sometimes gathers stupid small bits at end for some reason...?)
    #>
    wt -w HistBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1, ffa, ffa, 1v1, ffa, 1v1, 1v1 -name "EklipZ_ai_08" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-08-26\BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    MCTS based army engine
    #>
}



# starts a windows terminal that runs the standard live bots and opens dev tabs
function Start-WindowsTerminalLiveBots {
    Param(
    )

    <#
    FFA
    #>
    wt -w LiveBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai"'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    # time for the terminal window to open
    start-sleep -seconds 3

    <#
    1v1 only
    #>
    wt -w LiveBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1 -name "EklipZ_ai" -right'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    # <#
    # 1v1 ffa cycler
    # #>
    # wt -w LiveBots new-tab pwsh -NoExit -c { 
    #     cd "D:\2019_reformat_Backup\generals-bot\"; 
    #     . .\run-bot.ps1;
    #     $command = 'run-bot -game 1v1, 1v1, ffa, 1v1 -name "EklipZ_ai" -right'
    #     try {
    #         Invoke-Expression $command
    #     } finally {
    #         Write-Host $command
    #         Start-Sleep -Seconds 1
    #     }
    # }

    <#
    dev tab
    #>
    wt -w LiveBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
    }

    <#
    private ek 14
    #>
    wt -w LiveBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1 -name "EklipZ_ai_14" -noui -nolog -path D:\2019_reformat_Backup\generals-bot-historical\generals-bot-2023-07-24\bot_ek0x45.py -privateGame testing'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    <#
    private live
    #>
    wt -w LiveBots new-tab pwsh -NoExit -c { 
        cd "D:\2019_reformat_Backup\generals-bot\"; 
        . .\run-bot.ps1;
        $command = 'run-bot -game 1v1 -name "EklipZ_ai" -right -privateGame testing'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
}



function Run-Path {
    Param(
        $game = @('ffa')
    )
    while ($true)
    {
        foreach ($g in $game)
        {
            run-botonce -game $g -name "PurdPath" -path "D:\2019_reformat_Backup\generals-blob-and-path\bot_path_collect.py" -nolog -noui
        }
    }
}




function Run-Bot { 
    Param(
        $name, 
        [string[]]
        $game, 
        [switch]$public, 
        [switch]$right, 
        $privateGame, 
        [switch]$noui,
        $path = "D:\2019_reformat_Backup\generals-bot\BotHost.py",
        [switch]$nolog,
        [switch]$publicLobby
    )
    $games = $game
    while($true)
    {
        foreach ($g in $games)
        {
            write-verbose $g -verbose
            $psboundparameters['game'] = $g
            Run-BotOnce @psboundparameters
        }     
    }
}


function Run-BotCheckpoint { 
    Param(
        $name, 
        [string[]]
        $game, 
        [switch]$public, 
        [switch]$right, 
        $privateGame, 
        [switch]$noui,
        [switch]$nocopy,
        [switch]$nolog,
        [switch]$publicLobby
    )
    $games = $game
    $date = Get-Date -Format 'yyyy-MM-dd'
    $checkpointLoc = "D:\2019_reformat_Backup\generals-bot-historical\generals-bot-$date"
    Create-Checkpoint -backup $checkpointLoc

    while($true)
    {
        foreach ($g in $games)
        {
            write-verbose $g -verbose
            $psboundparameters['game'] = $g
            $botFile = "bot_ek0x45.py"
            if (Test-Path "$checkpointLoc\BotHost.py")
            {
                $botFile = "BotHost.py"    
            }
            Run-BotOnce @psboundparameters -path "$checkpointLoc\$botFile"
        }
    }
}


function Create-Checkpoint {
    Param(
        $source = 'D:\2019_reformat_Backup\generals-bot\',
        $dest = 'D:\2019_reformat_Backup\generals-bot-checkpoint\',
        $backup = "D:\2019_reformat_Backup\generals-bot-historical\generals-bot-$(Get-Date -Format 'yyyy-MM-dd')"
    )
    if ($backup)
    {
        robocopy $source $backup /MIR
    }
    robocopy $source $dest /MIR
}


function Run-Human {
    Param(
        $game = @('1v1', 'ffa', '1v1'),
        $sleepMax = 5
    )
    $splat = @{
        noui = $false
        right = $true
    }
    while ($true)
    {
        foreach ($g in $game)
        {
            Run-BotOnce -game $g -name "Human.exe" -public @splat
            Start-Sleep -Seconds (Get-Random -Min 0 -Max $sleepMax)
        }
    }
}