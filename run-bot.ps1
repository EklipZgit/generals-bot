


function Run-BotOnce { 
    Param(
        $name, 
        $game, 
        [switch]$public, 
        [switch]$right, 
        [switch]$privateGame, 
        $roomID = $null,
        [switch]$noui,
        $path = "$PSScriptRoot/BotHost.py",
        $userID = $null,
        [switch]$nolog,
        [switch]$publicLobby
    )

    $ErrorActionPreference = 'Stop'

    if (-not (Test-Path "$PSScriptRoot/../temp")) {
        mkdir "$PSScriptRoot/../temp"
    }

    $blockBotFile = "$PSScriptRoot/../block_bot.txt"
    if (-not (Test-Path $blockBotFile)) {
        throw "Unable to find a block_bot.txt file one folder above this scripts folder at $blockBotFile. The file should contain either the string False or the string True."
    }

    $content = Get-Content -Path $blockBotFile -Raw
    if ($content.Trim().ToLower() -eq 'true')
    {
        Write-Host "Bot blocked by $blockBotFile"
        Start-Sleep -Seconds 15
        return
    }

    $configFile = "$PSScriptRoot/../run_config.txt"
    if (-not (Test-Path $configFile)) {
        throw "Unable to find a run_config.txt file one folder above this scripts folder at $configFile. The file should contain multiple lines with:
log_folder=D:/GeneralsLogs
grouped_folder=D:/GeneralsLogs/GroupedLogs
left_pos=0
right_pos=1920
top_pos=0
bottom_pos=1080

where window positions are pixels relative to the top left corner of your primary monitor, and correspond to where the game UI will show up when the bot is run with a UI and some combination of the -right / -bottom flags provided (default is top left if no positional flags passed).
This allows you to have different bots running on different monitors, etc.
";
    }

    $logFolder = ""
    $groupedFolder = ""

    $cfgContent = Get-Content -Path $configFile
    foreach ($line in $cfgContent) {
        if ($line -like 'log_folder=*') {
            $logFolder = ($line -split '=')[1].TrimEnd('/', '\')
        }

        if ($line -like 'grouped_folder=*') {
            $groupedFolder = ($line -split '=')[1].TrimEnd('/', '\')
        }
    }

    if ([string]::IsNullOrWhiteSpace($groupedFolder)) {
        throw "run_config.txt file at $configFile is required to have a grouped_folder=<path> entry."
    }
    if ([string]::IsNullOrWhiteSpace($logFolder)) {
        throw "run_config.txt file at $configFile is required to have a log_folder=<path> entry."
    }

    $df = Get-Date -format yyyy-MM-dd_hh-mm-ss 
    $arguments = [System.Collections.ArrayList]::new()
    $roomName = ''
    if ($privateGame) {
        $game = "private"
        if ($publicLobby) {
            $game = "custom"
        }

        $roomName = "_$roomID"
    }
    if ($roomID) {
        [void] $arguments.Add("-roomID")
        [void] $arguments.Add($roomID)
    }
    if ($userID) {
        [void] $arguments.Add("-userID")
        [void] $arguments.Add($userID)
    }
    if ($right) { [void] $arguments.Add("--right") }
    if ($noui) { [void] $arguments.Add("--no-ui") }
    if ($nolog) { [void] $arguments.Add("--no-log") }
    if ($public) { 
        [void] $arguments.Add("--public")
    }

    $arguments = $arguments.ToArray()
    $argString = $([string]::Join(" ", $arguments))
    Write-Verbose $argString -Verbose
    $host.ui.RawUI.WindowTitle = "$game - $($name.Replace('[Bot]', '').Trim())"

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
    `$logName = "`$cleanName-$game-$df$roomName"
    `$logFile = "`$logName.txt"
    `$logPath = "$logFolder/`$logFile"

    if (-not `$$($nolog.ToString()))
    {
        Start-Transcript -path "`$logPath"
    }

    try 
    {
        #Write-Verbose `"python $path -name $name -g $game $argString`" -verbose
        python "$path" -name '$name' -g '$game' @arguments 2>&1
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
            if (-not `$content) {
                Write-Warning "No content found in `$logPath"
            }

            `$newContent = foreach (`$line in `$content)
            {
                if (`$line -ne [string]::Empty)
                {
                    `$prevLine = `$line
                    `$line
                    if (`$repId -eq `$null -and `$line -match 'replay_id:\[([^\]]+)\]')
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
                `$filter = "*`$cleanName*`$repId*"
                Write-Output "filter `$filter"
                `$folder = Get-ChildItem "$logFolder" -Filter `$filter -Directory
                `$newLogPath = Join-Path `$folder.FullName "_`$logFile"
                `$newContent | Set-Content -Path `$newLogPath -Force
                `$null = mkdir "$groupedFolder" -Force
                `$newFolder = Move-Item `$folder.FullName "$groupedFolder" -PassThru
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

    `$rand = Get-Random -Maximum 100
    if (`$rand -eq 0) {
        Get-ChildItem "$logFolder" | 
            ? { `$_.FullName -notlike '*_chat*' } | 
            ? { `$_.LastWriteTime -lt (get-date).AddMinutes(-120) } | 
            Remove-Item -Force -Recurse -ErrorAction Ignore
        
        Get-ChildItem "$groupedFolder" -Directory | 
            ? { `$_.FullName -notlike '*_chat*' } | 
            ? { `$_.LastWriteTime -lt (get-date).AddMinutes(-120) } |
            Remove-Item -Force -Recurse -ErrorAction Ignore
    }
"@

    $randNums = 1..10 | Get-Random -Count 10
    $randName = $randNums -join ''
    $ps1File = "$PSScriptRoot/../temp/$randName.ps1"
    $exeString | Out-File $ps1File
    Write-Verbose $ps1File -Verbose
    if ($IsWindows) {
        Start-Process Powershell "-File $ps1File" -Wait -NoNewWindow
    } elseif ($IsLinux) {
        Start-Process pwsh "-File $ps1File" -Wait -NoNewWindow
    }
    try {
        Remove-Item $ps1File
    }
    catch {
        # no op I guess
    }
}



function Run-SoraAI {
    Param(
        $game = @('1v1', '1v1', 'ffa', 'ffa'),
        [switch]$public,
        [switch]$nolog,
        [int]$sleepMax = 3
    )
    while ($true)
    {
        $userId = 'EKSORA'
        if ($public)
        {
            $userId = 'SmurfySmurfette'
        }

        foreach ($g in $game)
        {
            run-botonce -game $g -name "Sora AI" -userID $userId -path "D:/2019_reformat_Backup/Sora_AI/run_bot.py" -public:$public -nolog:$nolog
            SleepLeastOfTwo -sleepMax $sleepMax
        }
    }
}



function Run-SoraAlt {
    Param(
        $game = @('1v1', '1v1'),
        [switch]$public,
        [switch]$nolog,
        [int]$sleepMax = 3
    )
    while ($true)
    {
        $userId = 'soraAlt1Abc'
        $name = "asdfjk;l :D:D"
        $time = (Get-Date).TimeOfDay;
        if ($time -lt ([timespan]'06:00:00')) {
            $userId = 'soraAlt2Abc'
            $name = "oaisdnvzsxdfg98"
        } elseif ($time -lt ([timespan]'12:00:00')) {
            $userId = 'soraAlt3Abc'
            $name = "ShowerPower"
        } elseif ($time -lt ([timespan]'18:00:00')) {
            $userId = 'soraAlt4Abc'
            $name = "wsedxbvtioun"
        }

        # $userId = 'soraAlt1Abc'
        # $name = "asdfjk;l :D:D"
        # $userId = 'soraAlt2Abc'
        # $name = "oaisdnvzsxdfg98"
        # $userId = 'soraAlt3Abc'
        # $name = "ShowerPower"
        # $userId = 'soraAlt4Abc'
        # $name = "wsedxbvtioun"

        foreach ($g in $game)
        {
            run-botonce -game $g -name $name -userID $userId -path "D:/2019_reformat_Backup/Sora_AI/run_bot.py" -public:$public -nolog:$nolog
            SleepLeastOfTwo -sleepMax $sleepMax
        }
    }
}


function Run-SoraAITeammate {
    Param(
    )
    while ($true)
    {
        run-botonce -game 'team' -name "Sora_ai_2" -userID "EKSORA2" -path "D:/2019_reformat_Backup/Sora_AI/run_bot.py" -nolog -public:$public
    }
}


function Start-WindowsTerminalAltBots {
    Param(
    )

    $windowName = 'AltBots'
    
    # starts a windows terminal that runs the FFA bots and a second instance of Sora AI that joins 1v1s
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Path -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Path -game 1v1, ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Blob -game 1v1, ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-SoraAI -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
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

    $windowName = 'HistBots'

    <#
    original timings and bugs from 2019, with connection code fixed
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, 1v1, 1v1, 1v1 -name "EklipZ_ai_14" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-07-24/bot_ek0x45.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, 1v1, 1v1, ffa -name "EklipZ_ai_13" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-07-29/bot_ek0x45.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, 1v1, ffa, 1v1 -name "EklipZ_ai_12" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-07-31/bot_ek0x45.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, 1v1, ffa, 1v1 -name "EklipZ_ai_11" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-04/BotHost.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, 1v1, ffa -name "EklipZ_ai_10" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-07/BotHost.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, 1v1, ffa -name "EklipZ_ai_09" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-08/BotHost.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, ffa, 1v1, ffa -name "EklipZ_ai_08" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-26/BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    loads of fog / engine bugfixes but still not MCTS working. 
    Tweaked attack timings.
    Better defense.
    Brute force army engine time cutoff.
    Dropped file logging.
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, ffa, 1v1, ffa, 1v1 -name "EklipZ_ai_07" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-09-15/BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    MCTS based army engine.
    2v2
    fog / movement detection rework
    way too much stuff to list
    broken 1v1 in some ways due to 2v2 changes
    defense gather forward instead of back
    found-no-move mcts (need to tune back for historical bots I think)
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa, ffa, 1v1, ffa, 1v1 -name "EklipZ_ai_06" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-10-23/BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    fixing stuff?
    #>
}


# starts a windows terminal that runs many historical versions of EklipZ_ai
function Start-WindowsTerminalBigFfaBots {
    Param(
    )

    $windowName = 'BigFFA'

    <#
    original timings and bugs from 2019, with connection code fixed
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_14" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-07-24/bot_ek0x45.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_13" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-07-29/bot_ek0x45.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_12" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-07-31/bot_ek0x45.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_11" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-04/BotHost.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_10" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-07/BotHost.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_09" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-08/BotHost.py'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_08" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-08-26/BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    loads of fog / engine bugfixes but still not MCTS working. 
    Tweaked attack timings.
    Better defense.
    Brute force army engine time cutoff.
    Dropped file logging.
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_07" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-09-15/BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    MCTS based army engine.
    2v2
    fog / movement detection rework
    way too much stuff to list
    broken 1v1 in some ways due to 2v2 changes
    defense gather forward instead of back
    found-no-move mcts (need to tune back for historical bots I think)
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_06" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-10-23/BotHost.py'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    ffa only 2
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_i2" -right -noui -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    ffa only 3
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_i3" -right -noui -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    ffa only 4
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai_i4" -right -noui -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    ffa only
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai" -right -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Blob -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Blob -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Path -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Path -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-SoraAI -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-SoraAI -game ffa'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
}



# starts a windows terminal that runs the standard live bots and opens dev tabs
function Start-WindowsTerminalLiveBots {
    Param(
    )

    $windowName = 'LiveBots'

    <#
    dev tab
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        . ./game-result-analysis-utils.ps1;
    }

    # time for the terminal window to open
    start-sleep -seconds 3

    <#
    Human 1v1
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -left -game 1v1 -sleepMax 240'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    Human ffa
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -right -game ffa -sleepMax 120 -nolog'
        try {
            # Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    Human 2v2 partners
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -game team -right -sleepMax 5 -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-HumanTeammate -game team -right -sleepMax 60 -nolog -noui'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Teammate -sleepMax 90 -left -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
    # SECOND teammate for local testing:
    # run-teammate -sleepMax 1 -left -name Teammate2.exe

    <# Teammate in team lobby #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Teammate -sleepMax 1 -left -roomID teammate -nolog' 
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    # weak bots
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-blob -game 1v1 -sleepMax 120 -name "QueueT" -public'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/";
        . ./run-bot.ps1;
        $command = 'run-path -game 1v1 -sleepMax 120 -name "a98i40pwpfah" -public'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/";
        . ./run-bot.ps1;
        $command = 'run-SoraAlt -public -sleepMax 180'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    Human in custom lobby with custom maps
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeCustMap1 -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    Human in custom lobby with custom maps
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeCustMap2 -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    Human in custom lobby with alt tiles
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeAltTiles1 -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    <#
    Human in custom lobby with normal setup
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeNormal1 -nolog'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    # ALT TESTING
    # Run-Human -name 'HaltWhoGoesThere' -game custom -private -sleepMax 1 -roomID Human.exeNormal1
}




# starts a windows terminal that runs the standard live bots and opens dev tabs
function Start-WindowsTerminalBotServer2v2Bots {
    Param(
    )

    $windowName = 'Bot2v2Bots'

    <#
    Human 2v2 partners
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Human -game team -right -sleepMax 5 -nolog -botServer'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }


    # time for the terminal window to open
    start-sleep -seconds 3

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-HumanTeammate -game team -right -sleepMax 10 -nolog -noui -botServer'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Teammate -sleepMax 10 -left -nolog -botServer'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }

    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'Run-Teammate -sleepMax 10 -left -nolog -name Teammate2.exe -botServer'
        try {
            Invoke-Expression $command
        } finally {
            Write-Host $command
            Start-Sleep -Seconds 1
        }
    }
}




# starts a windows terminal that runs the standard live bots and opens dev tabs
function Start-WindowsTerminalBotServerLiveBots {
    Param(
    )

    $windowName = 'BotServerLiveBots'
    <#
    FFA
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game ffa -name "EklipZ_ai" -right'
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
    wt -w $windowName new-tab pwsh -NoExit -c {
        cd "D:/2019_reformat_Backup/generals-bot/";
        . ./run-bot.ps1;
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
    # wt -w $windowName new-tab pwsh -NoExit -c { 
    #     cd "D:/2019_reformat_Backup/generals-bot/"; 
    #     . ./run-bot.ps1;
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        . ./game-result-analysis-utils.ps1;
    }

    <#
    private ek 14
    #>
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game 1v1 -name "EklipZ_ai_14" -noui -nolog -path D:/2019_reformat_Backup/generals-bot-historical/generals-bot-2023-07-24/bot_ek0x45.py -privateGame testing'
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
    wt -w $windowName new-tab pwsh -NoExit -c { 
        cd "D:/2019_reformat_Backup/generals-bot/"; 
        . ./run-bot.ps1;
        $command = 'run-bot -game 1v1 -name "EklipZ_ai" -left -privateGame testing'
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
        $game = @('ffa'),
        $name = "PurdPath",
        [switch]$public,
        [int]$sleepMax = 3
    )
    while ($true)
    {
        foreach ($g in $game)
        {
            run-botonce -game $g -name $name -path "D:/2019_reformat_Backup/generals-blob-and-path/bot_path_collect.py" -nolog -noui -public:$public
            SleepLeastOfTwo -sleepMax $sleepMax
        }
    }
}



function Run-Blob {
    Param(
        $game = @('ffa'),
        $name = "PurdBlob",
        [switch]$public,
        [int]$sleepMax = 3
    )
    while ($true)
    {
        foreach ($g in $game)
        {
            run-botonce -game $g -name $name -path "D:/2019_reformat_Backup/generals-blob-and-path/bot_blob.py" -nolog -noui -public:$public
            SleepLeastOfTwo -sleepMax $sleepMax
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
        $roomID, 
        [switch]$noui,
        $path = "D:/2019_reformat_Backup/generals-bot/BotHost.py",
        [switch]$nolog,
        [switch]$publicLobby,
        $sleepMax = 30
    )
    $games = $game
    while($true)
    {
        foreach ($g in $games)
        {
            write-verbose $g -verbose
            $psboundparameters['game'] = $g
            Run-BotOnce @psboundparameters
            
            SleepLeastOfTwo -sleepMax $sleepMax
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
        $roomID, 
        [switch]$noui,
        [switch]$nocopy,
        [switch]$nolog,
        [switch]$publicLobby
    )
    $games = $game
    $date = Get-Date -Format 'yyyy-MM-dd'
    $checkpointLoc = "D:/2019_reformat_Backup/generals-bot-historical/generals-bot-$date"
    Create-Checkpoint -backup $checkpointLoc

    while($true)
    {
        foreach ($g in $games)
        {
            write-verbose $g -verbose
            $psboundparameters['game'] = $g
            $botFile = "bot_ek0x45.py"
            if (Test-Path "$checkpointLoc/BotHost.py")
            {
                $botFile = "BotHost.py"    
            }
            Run-BotOnce @psboundparameters -path "$checkpointLoc/$botFile"
        }
    }
}


function Create-Checkpoint {
    Param(
        $source = 'D:/2019_reformat_Backup/generals-bot/',
        $dest = 'D:/2019_reformat_Backup/generals-bot-checkpoint/',
        $backup = "D:/2019_reformat_Backup/generals-bot-historical/generals-bot-$(Get-Date -Format 'yyyy-MM-dd')"
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
        $sleepMax = 3,
        $roomID = 'getRekt',
        [switch] $left,
        [switch] $private,
        [switch] $noui,
        [switch] $nolog,
        $name = 'Human.exe',
        [switch] $botServer
    )
    $splat = @{
        noui = $noui
        right = -not $left
        nolog = $nolog
        public = -not $botServer
    }
    while ($true)
    {
        foreach ($g in $game)
        {
            Run-BotOnce -game $g -name $name -roomID $roomID @splat -privateGame:$private
            SleepLeastOfTwo -sleepMax $sleepMax
        }
    }
}


function SleepLeastOfTwo {
    Param(
        $sleepMax
    )
    
    $sleepTimeA = (Get-Random -Min 0 -Max $sleepMax)
    $sleepTime = $sleepTimeA

    # use min-of-2 strategy to more often pick lower sleep times but still have high sleep times available.
    $sleepTimeB = (Get-Random -Min 0 -Max $sleepMax)
    if ($sleepTimeB -lt $sleepTime) {
        $sleepTime = $sleepTimeB
    }

    Write-Verbose "Finished, sleeping $sleepTime" -Verbose
    Start-Sleep -Seconds $sleepTime
}


function Run-HumanTeammate {
    Param(
        [switch] $left,
        $roomID = 'getRekt',
        [switch] $noui,
        [switch] $nolog,
        [switch] $botServer
    )

    $splat = @{
        noui = $noui
        right = -not $left
        userID = 'efgHuman.py'
        nolog = $nolog
        public = -not $botServer
    }

    while ($true)
    {
        Run-BotOnce -game "team" -roomID $roomID -name "Exe.human" @splat
    }
}


function Run-Teammate {
    Param(
        [switch] $left,
        $sleepMax = 120,
        $roomID = 'matchmaking',
        [switch] $noui,
        [switch] $nolog,
        $name = "Teammate.exe",
        [switch] $botServer
    )

    $userId = 'efgBuddy.exe'
    if ($name -ne 'Teammate.exe') {
        $userId = "efg$($name)";
    }

    $splat = @{
        noui = $noui
        right = -not $left
        userID = $userId
        roomID = $roomID
        nolog = $nolog
        public = -not $botServer
    }

    while ($true)
    {
        Run-BotOnce -game "team" -name $name @splat

        $sleepTimeA = (Get-Random -Min 0 -Max $sleepMax)
        $sleepTime = $sleepTimeA

        # use min-of-2 strategy to more often pick lower sleep times but still have high sleep times available.
        $sleepTimeB = (Get-Random -Min 0 -Max $sleepMax)
        if ($sleepTimeB -lt $sleepTime) {
            $sleepTime = $sleepTimeB
        }

        Write-Verbose "Powershell finished, sleeping $sleepTime" -Verbose
        Start-Sleep -Seconds $sleepTime
    }
}