


$Script:RunConfig = $null
$Script:CheapBotCpuAffinityMask = [IntPtr]0x10000
$Script:HumanPcoreAffinityMasks = @(
    [IntPtr]0x1,
    [IntPtr]0x4,
    [IntPtr]0x10,
    [IntPtr]0x40,
    [IntPtr]0x100,
    [IntPtr]0x400,
    [IntPtr]0x1000,
    [IntPtr]0x4000
)


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


function Get-RequiredRunConfigValue {
    Param(
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    $value = Get-RunConfigValue -Key $Key
    if ([string]::IsNullOrWhiteSpace($value)) {
        $configFile = Get-RunConfigFilePath
        throw "run_config.txt file at $configFile is required to have a $Key=<path> entry."
    }

    return $value
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


function Get-ConfiguredLogFolder {
    return Get-RequiredRunConfigValue -Key 'log_folder'
}


function Get-ConfiguredGroupedFolder {
    return Get-RequiredRunConfigValue -Key 'grouped_folder'
}


function Get-SoraBotPath {
    return Get-RequiredRunConfigValue -Key 'sora_bot_path'
}


function Get-BlobBotPath {
    return Get-RequiredRunConfigValue -Key 'blob_bot_path'
}


function Get-PathBotPath {
    return Get-RequiredRunConfigValue -Key 'path_bot_path'
}


function Get-HistoricalBotsRoot {
    return Get-RequiredRunConfigValue -Key 'historical_bots_root'
}


function Get-CurrentGenPythonPath {
    return Get-RequiredRunConfigValue -Key 'current_gen_python_path'
}


function Get-LegacyPythonPath {
    return Get-RequiredRunConfigValue -Key 'legacy_python_path'
}


function Get-CheckpointMirrorRoot {
    return Get-RequiredRunConfigValue -Key 'checkpoint_mirror_root'
}


function Get-CheckpointBackupRoot {
    return Get-RequiredRunConfigValue -Key 'checkpoint_backup_root'
}


function Get-HistoricalBotPath {
    Param(
        [Parameter(Mandatory = $true)]
        [string]$VersionFolder,
        [Parameter(Mandatory = $true)]
        [string]$BotFile
    )

    return (Join-Path (Join-Path (Get-HistoricalBotsRoot) $VersionFolder) $BotFile)
}


function Start-RunBotWindowsTerminalTab {
    Param(
        [Parameter(Mandatory = $true)]
        [string]$WindowName,
        [string]$Command,
        [switch]$LoadGameResultUtils
    )

    $repoRoot = Get-ConfiguredRepoRoot
    $runBotPath = Join-Path $repoRoot 'run-bot.ps1'
    $analysisUtilsPath = Join-Path $repoRoot 'game-result-analysis-utils.ps1'
    $commandLines = @(
        "Set-Location '$($repoRoot.Replace("'", "''"))'",
        ". '$($runBotPath.Replace("'", "''"))'"
    )
    if ($LoadGameResultUtils) {
        $commandLines += ". '$($analysisUtilsPath.Replace("'", "''"))'"
    }
    if (-not [string]::IsNullOrWhiteSpace($Command)) {
        $escapedCommand = $Command.Replace("'", "''")
        $commandLines += "`$command = '$escapedCommand'"
        $commandLines += 'try {'
        $commandLines += '    Invoke-Expression $command'
        $commandLines += '} finally {'
        $commandLines += '    Write-Host $command'
        $commandLines += '    Start-Sleep -Seconds 1'
        $commandLines += '}'
    }

    $scriptText = '& { ' + ([string]::Join('; ', $commandLines)) + ' }'
    $encodedScriptText = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($scriptText))
    Write-Output $encodedScriptText
    $wtArguments = @(
        '-w',
        $WindowName,
        'new-tab',
        'pwsh',
        '-NoExit',
        '-EncodedCommand',
        $encodedScriptText
    )
    & wt @wtArguments
}


$null = Initialize-RunConfig


function Resolve-CpuAffinityMask {
    Param(
        $cpuAffinityMask
    )

    if ($null -eq $cpuAffinityMask) {
        return [IntPtr]::Zero
    }

    if ($cpuAffinityMask -is [IntPtr]) {
        return $cpuAffinityMask
    }

    $cpuAffinityString = "$cpuAffinityMask".Trim()
    if ([string]::IsNullOrWhiteSpace($cpuAffinityString)) {
        return [IntPtr]::Zero
    }

    if ($cpuAffinityString -eq 'P') {
        return [IntPtr]0x5555
    }

    if ($cpuAffinityString -eq 'E') {
        return [IntPtr]0xFF0000
    }

    $cpuIndex = 0
    if (-not [int]::TryParse($cpuAffinityString, [ref]$cpuIndex)) {
        throw "Invalid cpuAffinityMask '$cpuAffinityMask'. Use a CPU number, P for all p-cores, or E for all e-cores."
    }

    if ($cpuIndex -lt 0 -or $cpuIndex -ge [IntPtr]::Size * 8) {
        throw "Invalid cpuAffinityMask CPU number '$cpuAffinityMask'. CPU number must be between 0 and $([IntPtr]::Size * 8 - 1)."
    }

    if ($cpuIndex -eq 0) {
        return [IntPtr]1
    }

    return [IntPtr]([int64]1 -shl $cpuIndex)
}


function Run-BotOnce {
    Param(
        $name,
        $game,
        [switch]$public,
        [switch]$right,
        [switch]$privateGame,
        $roomID = $null,
        [switch]$noui,
        $path = $(Join-Path (Get-ConfiguredRepoRoot) 'BotHost.py'),
        $userID = $null,
        [switch]$nolog,
        [switch]$noTextLog,
        [switch]$publicLobby,
        $cpuAffinityMask = [IntPtr]::Zero
    )

    $ErrorActionPreference = 'Stop'
    $cpuAffinityMask = Resolve-CpuAffinityMask $cpuAffinityMask

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

    $logFolder = Get-ConfiguredLogFolder
    $groupedFolder = Get-ConfiguredGroupedFolder

    $null = New-Item -ItemType Directory -Force -Path $logFolder
    $null = New-Item -ItemType Directory -Force -Path $groupedFolder

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
    if ($noTextLog) { [void] $arguments.Add("--no-text-log") }
    if ($public) {
        [void] $arguments.Add("--public")
    }

    $arguments = $arguments.ToArray()
    $argString = $([string]::Join(" ", $arguments))
    Write-Verbose $argString -Verbose
    $host.ui.RawUI.WindowTitle = "$game - $($name.Replace('[Bot]', '').Trim())"
    $pythonVer = "python"
    $pythonVer = Get-CurrentGenPythonPath
    if ($path -notlike '*[/\]generals-bot[\/]*') {
        $pythonVer = Get-LegacyPythonPath
    }

    Write-Host "Python ver $pythonVer for path $path"

    $randNums = 1..10 | Get-Random -Count 10
    $randName = $randNums -join ''
    $ps1File = "$PSScriptRoot/../temp/$randName.ps1"
    $playedGameFile = "$PSScriptRoot/../temp/$randName.played"

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
    `$cpuAffinityMask = [IntPtr]::new($($cpuAffinityMask.ToInt64()))
    `$arguments = @('$([string]::Join("', '", $arguments))')
    Write-Output "arguments $([string]::Join(', ', $arguments))"
    `$cleanName = '$name'.Replace('[', '').Replace(']', '')
    `$logName = "`$cleanName-$game-$df$roomName"
    `$logFile = "`$logName.txt"
    `$logPath = "$logFolder/`$logFile"
    `$stdoutLogPath = "`$logPath.stdout"
    `$stderrLogPath = "`$logPath.stderr"
    `$processExitCode = `$null
    `$playedGameFile = '$playedGameFile'

    `$startProcSplat = @{}
    if (-not `$$($nolog.ToString()))
    {
        `$startProcSplat['RedirectStandardOutput'] = "`$stdoutLogPath"
        `$startProcSplat['RedirectStandardError'] = "`$stderrLogPath"
    }

    try
    {
        #Write-Verbose `"$pythonVer $path -name $name -g $game $argString`" -verbose
        #$pythonVer "$path" -name '$name' -g '$game' @arguments

        `$procArguments = @("`$path", '-name', '$name', '-g', '$game')
        `$procArguments += `$arguments
        `$escapedProcArguments = foreach (`$procArgument in `$procArguments) {
            if (`$procArgument -match '[\s"]') {
                '"' + (`$procArgument -replace '"', '\"') + '"'
            }
            else {
                `$procArgument
            }
        }
        `$joinedArguments = [string]::Join(' ', `$escapedProcArguments)
        `$Process = Start-Process -FilePath '$pythonVer' -ArgumentList `$joinedArguments -PassThru -NoNewWindow @startProcSplat
        if (`$null -ne `$Process -and `$cpuAffinityMask -ne [IntPtr]::Zero) {
            try {
                `$Process.ProcessorAffinity = `$cpuAffinityMask
            }
            catch {
                Write-Warning `$_
            }
        }
        if (`$null -ne `$Process) {
            try {
                `$Process.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::High
            }
            catch {
                Write-Warning `$_
            }
            `$Process | Wait-Process 2>&1
            `$Process.Refresh()
            `$processExitCode = `$Process.ExitCode
        }
    }
    catch
    {
        Write-Error `$_
    }
    finally
    {
        if (-not `$$($nolog.ToString()))
        {
            #stop-transcript
            `$mergedContent = @()
            if (Test-Path `$stdoutLogPath) {
                `$mergedContent += Get-Content `$stdoutLogPath
            }
            if (Test-Path `$stderrLogPath) {
                `$mergedContent += Get-Content `$stderrLogPath
            }
            if (`$mergedContent.Count -gt 0) {
                `$mergedContent | Set-Content -Path `$logPath -Force
            }
            if (-not (Test-Path `$logPath)) {
                Write-Warning "No crash/output log file found at `$logPath"
            }
            else {
                if (`$processExitCode -ne `$null -and `$processExitCode -ne 0) {
                    Write-Warning "Bot process exited with code `$processExitCode. Captured output from `${logPath}:"
                    Get-Content `$logPath | ForEach-Object { Write-Host `$_ }
                }
                `$copiedToReplayLog = `$false
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
                            Set-Content -Path `$playedGameFile -Value `$repId -Force
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
                    `$copiedToReplayLog = `$true
                    Write-Warning "`$newName"
                    Write-Warning "`$newName"
                    Write-Warning "`$newName"
                }

                if (`$copiedToReplayLog) {
                    Remove-Item `$logPath -Force
                }
            }
            if (Test-Path `$stdoutLogPath) {
                Remove-Item `$stdoutLogPath -Force
            }
            if (Test-Path `$stderrLogPath) {
                Remove-Item `$stderrLogPath -Force
            }
        }
    }

    Start-Sleep -Seconds 1

    `$rand = Get-Random -Maximum 100
    if (`$rand -eq 0) {
        `$groupedFolderFullPath = [System.IO.Path]::GetFullPath("$groupedFolder").TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
        Get-ChildItem "$logFolder" |
            ? { `$_.FullName -notlike '*_chat*' } |
            ? { [System.IO.Path]::GetFullPath(`$_.FullName).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) -ne `$groupedFolderFullPath } |
            ? { `$_.LastWriteTime -lt (get-date).AddHours(-4) } |
            Remove-Item -Force -Recurse -ErrorAction Ignore

        Get-ChildItem "$groupedFolder" -Directory |
            ? { `$_.FullName -notlike '*_chat*' } |
            ? { `$_.LastWriteTime -lt (get-date).AddHours(-4) } |
            Remove-Item -Force -Recurse -ErrorAction Ignore
    }
"@

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

    $playedGame = Test-Path $playedGameFile
    if ($playedGame) {
        Remove-Item $playedGameFile -Force
    }
    return $playedGame
}



function Run-SoraAI {
    Param(
        $game = @('1v1', '1v1', 'ffa', 'ffa'),
        [switch]$public,
        [switch]$nolog,
        [switch]$noTextLog,
        [int]$sleepMax = 3,
        $cpuAffinityMask = $Script:CheapBotCpuAffinityMask
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
            $playedGame = run-botonce -game $g -name "Sora AI" -userID $userId -path (Get-SoraBotPath) -public:$public -nolog:$nolog -noTextLog:$noTextLog -cpuAffinityMask $cpuAffinityMask
            if ($playedGame) {
                SleepLeastOfTwo -sleepMax $sleepMax
            }
        }
    }
}



function Run-SoraAlt {
    Param(
        $game = @('1v1', '1v1'),
        [switch]$public,
        [switch]$nolog,
        [switch]$noTextLog,
        [int]$sleepMax = 3,
        $cpuAffinityMask = $Script:CheapBotCpuAffinityMask
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
            $playedGame = run-botonce -game $g -name $name -userID $userId -path (Get-SoraBotPath) -public:$public -nolog:$nolog -noTextLog:$noTextLog -cpuAffinityMask $cpuAffinityMask
            if ($playedGame) {
                SleepLeastOfTwo -sleepMax $sleepMax
            }
        }
    }
}


function Run-SoraAITeammate {
    Param(
        $cpuAffinityMask = $Script:CheapBotCpuAffinityMask
    )
    while ($true)
    {
        run-botonce -game 'team' -name "Sora_ai_2" -userID "EKSORA2" -path (Get-SoraBotPath) -nolog -public:$public -cpuAffinityMask $cpuAffinityMask
    }
}


function Start-WindowsTerminalAltBots {
    Param(
    )

    $windowName = 'AltBots'

    # starts a windows terminal that runs the FFA bots and a second instance of Sora AI that joins 1v1s
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Blob -game ffa'
    # time for the terminal window to open
    start-sleep -seconds 3
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Path -game ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Path -game 1v1, ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Blob -game 1v1, ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-SoraAI -game ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-SoraAI -game 1v1,ffa,1v1'
}



# starts a windows terminal that runs many historical versions of EklipZ_ai
function Start-WindowsTerminalHistoricalBots {
    Param(
    )

    $windowName = 'HistBots'

    <#
    original timings and bugs from 2019, with connection code fixed
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, 1v1, 1v1, 1v1 -name 'EklipZ_ai_14' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-24' -BotFile 'bot_ek0x45.py')"

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
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, 1v1, 1v1, ffa -name 'EklipZ_ai_13' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-29' -BotFile 'bot_ek0x45.py')"
    <#
    Hopefully defense off-by-one threat detection fixed
    Additional panic gather defense added, defense now negatives all tiles in shortest path on attack path
    undiscovered priority improvements
    AGGRESSIVELY take cities while cramped. Cramped detection takes into account the distance to enemy territory
    gather to enemy tiles inside territory more aggressively
    play turns 25-50 more aggressively (too aggressively?)
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, 1v1, ffa, 1v1 -name 'EklipZ_ai_12' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-31' -BotFile 'bot_ek0x45.py')"
    <#
    improved 'vision tile' kill gathers to only gather for the quickexpand turns, and are included in the main gather phase with a 2
        tile exclusion radius around them to prioritize killing them over gather path gather movement if adequate tile counts are near them.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, 1v1, ffa, 1v1 -name 'EklipZ_ai_11' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-04' -BotFile 'BotHost.py')"
    <#
    semi-optimal first 25, unit tests
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, 1v1, ffa -name 'EklipZ_ai_10' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-07' -BotFile 'BotHost.py')"
    <#
    tweaked gathers taking neutral / enemy tiles to include extra gather moves.
    tweaked initial expansion.
    tweaked optimal_expansion to include move-half when appropriate and draw the boundaries for when move-half is limited to closer-only moves and when it is limited to flankpath-or-closer-only moves.
    reduced neutral city aggressiveness right before launch timings.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, 1v1, ffa -name 'EklipZ_ai_09' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-08' -BotFile 'BotHost.py')"

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
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, ffa, 1v1, ffa -name 'EklipZ_ai_08' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-26' -BotFile 'BotHost.py')"
    <#
    loads of fog / engine bugfixes but still not MCTS working.
    Tweaked attack timings.
    Better defense.
    Brute force army engine time cutoff.
    Dropped file logging.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, ffa, 1v1, ffa, 1v1 -name 'EklipZ_ai_07' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-09-15' -BotFile 'BotHost.py')"
    <#
    MCTS based army engine.
    2v2
    fog / movement detection rework
    way too much stuff to list
    broken 1v1 in some ways due to 2v2 changes
    defense gather forward instead of back
    found-no-move mcts (need to tune back for historical bots I think)
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa, ffa, 1v1, ffa, 1v1 -name 'EklipZ_ai_06' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-10-23' -BotFile 'BotHost.py')"
}



# starts a windows terminal that runs many historical versions of EklipZ_ai
function Start-WindowsTerminalBigFfaBots {
    Param(
    )

    $windowName = 'BigFFA'

    <#
    original timings and bugs from 2019, with connection code fixed
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_14' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-24' -BotFile 'bot_ek0x45.py')"

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
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_13' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-29' -BotFile 'bot_ek0x45.py')"
    <#
    Hopefully defense off-by-one threat detection fixed
    Additional panic gather defense added, defense now negatives all tiles in shortest path on attack path
    undiscovered priority improvements
    AGGRESSIVELY take cities while cramped. Cramped detection takes into account the distance to enemy territory
    gather to enemy tiles inside territory more aggressively
    play turns 25-50 more aggressively (too aggressively?)
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_12' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-31' -BotFile 'bot_ek0x45.py')"
    <#
    improved 'vision tile' kill gathers to only gather for the quickexpand turns, and are included in the main gather phase with a 2
        tile exclusion radius around them to prioritize killing them over gather path gather movement if adequate tile counts are near them.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_11' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-04' -BotFile 'BotHost.py')"
    <#
    semi-optimal first 25, unit tests
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_10' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-07' -BotFile 'BotHost.py')"
    <#
    tweaked gathers taking neutral / enemy tiles to include extra gather moves.
    tweaked initial expansion.
    tweaked optimal_expansion to include move-half when appropriate and draw the boundaries for when move-half is limited to closer-only moves and when it is limited to flankpath-or-closer-only moves.
    reduced neutral city aggressiveness right before launch timings.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_09' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-08' -BotFile 'BotHost.py')"

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
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_08' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-26' -BotFile 'BotHost.py')"
    <#
    loads of fog / engine bugfixes but still not MCTS working.
    Tweaked attack timings.
    Better defense.
    Brute force army engine time cutoff.
    Dropped file logging.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_07' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-09-15' -BotFile 'BotHost.py')"
    <#
    MCTS based army engine.
    2v2
    fog / movement detection rework
    way too much stuff to list
    broken 1v1 in some ways due to 2v2 changes
    defense gather forward instead of back
    found-no-move mcts (need to tune back for historical bots I think)
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game ffa -name 'EklipZ_ai_06' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-10-23' -BotFile 'BotHost.py')"

    <#
    ffa only 2
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai_i2" -right -noui -nolog'

    <#
    ffa only 3
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai_i3" -right -noui -nolog'

    <#
    ffa only 4
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai_i4" -right -noui -nolog'

    <#
    ffa only 2
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai_i2" -right -noui -nolog'

    <#
    ffa only 3
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai_i3" -right -noui -nolog'

    <#
    ffa only 4
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai_i4" -right -noui -nolog'

    <#
    ffa only
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai" -right -nolog'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Blob -game ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Blob -game ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Path -game ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Path -game ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-SoraAI -game ffa'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-SoraAI -game ffa'
}



# starts a windows terminal that runs many bots in the big team queue
function Start-WindowsTerminalBigTeamBots {
    Param(
    )

    $windowName = 'BigTeam'


    <#
    original timings and bugs from 2019, with connection code fixed
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_14' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-24' -BotFile 'bot_ek0x45.py')"

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
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_13' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-29' -BotFile 'bot_ek0x45.py')"
    <#
    Hopefully defense off-by-one threat detection fixed
    Additional panic gather defense added, defense now negatives all tiles in shortest path on attack path
    undiscovered priority improvements
    AGGRESSIVELY take cities while cramped. Cramped detection takes into account the distance to enemy territory
    gather to enemy tiles inside territory more aggressively
    play turns 25-50 more aggressively (too aggressively?)
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_12' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-31' -BotFile 'bot_ek0x45.py')"
    <#
    improved 'vision tile' kill gathers to only gather for the quickexpand turns, and are included in the main gather phase with a 2
        tile exclusion radius around them to prioritize killing them over gather path gather movement if adequate tile counts are near them.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_11' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-04' -BotFile 'BotHost.py')"
    <#
    semi-optimal first 25, unit tests
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_10' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-07' -BotFile 'BotHost.py')"
    <#
    tweaked gathers taking neutral / enemy tiles to include extra gather moves.
    tweaked initial expansion.
    tweaked optimal_expansion to include move-half when appropriate and draw the boundaries for when move-half is limited to closer-only moves and when it is limited to flankpath-or-closer-only moves.
    reduced neutral city aggressiveness right before launch timings.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_09' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-08' -BotFile 'BotHost.py')"

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
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_08' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-26' -BotFile 'BotHost.py')"

    <#
    loads of fog / engine bugfixes but still not MCTS working.
    Tweaked attack timings.
    Better defense.
    Brute force army engine time cutoff.
    Dropped file logging.
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_07' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-09-15' -BotFile 'BotHost.py')"

    <#
    MCTS based army engine.
    2v2
    fog / movement detection rework
    way too much stuff to list
    broken 1v1 in some ways due to 2v2 changes
    defense gather forward instead of back
    found-no-move mcts (need to tune back for historical bots I think)
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game bigteam -name 'EklipZ_ai_06' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-10-23' -BotFile 'BotHost.py')"

    <#
    bigteam only 2
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game bigteam -name "EklipZ_ai_i2" -right -noui -nolog'

    <#
    bigteam only 3
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game bigteam -name "EklipZ_ai_i3" -right -noui -nolog'

    <#
    bigteam only 4
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game bigteam -name "EklipZ_ai_i4" -right -noui -nolog'

    <#
    bigteam only 2
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game bigteam -name "EklipZ_ai_i2" -right -noui -nolog'

    <#
    bigteam only 3
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game bigteam -name "EklipZ_ai_i3" -right -noui -nolog'

    <#
    bigteam only 4
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game bigteam -name "EklipZ_ai_i4" -right -noui -nolog'

    <#
    bigteam only
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game bigteam -name "EklipZ_ai" -right -nolog'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Blob -game bigteam'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Blob -game bigteam'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Path -game bigteam'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Path -game bigteam'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-SoraAI -game bigteam'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-SoraAI -game bigteam'
}



# starts a windows terminal that runs the standard live bots and opens dev tabs
function Start-WindowsTerminalLiveBots {
    Param(
    )

    $windowName = 'LiveBots'

    <#
    dev tab
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -LoadGameResultUtils

    # time for the terminal window to open
    start-sleep -seconds 3

    <#
    Human 1v1
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Human -left -game 1v1 -sleepMax 600 -cpuAffinityMask P'

    <#
    Human ffa
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Human -right -game ffa -sleepMax 120 -cpuAffinityMask P'

    <#
    Human 2v2 partners
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Human -game team -right -sleepMax 5 -nolog -botServer -cpuAffinityMask 4'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-HumanTeammate -game team -right -sleepMax 60 -nolog -noui -cpuAffinityMask 6'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Teammate -sleepMax 90 -left -nolog -cpuAffinityMask 8'
    # SECOND teammate for local testing:
    # run-teammate -sleepMax 1 -left -name Teammate2.exe

    <# Teammate in team lobby #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Teammate -sleepMax 1 -left -roomID teammate -nolog -cpuAffinityMask 10'

    # weak bots
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-blob -game 1v1 -sleepMax 120 -name "QueueT" -public -noui'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-path -game 1v1 -sleepMax 120 -name "a98i40pwpfah" -public -noui'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-SoraAlt -public -sleepMax 120'

    # <#
    # Human in custom lobby with custom maps
    # #>
    # wt -w $windowName new-tab pwsh -NoExit -c {
    #     cd "D:/2019_reformat_Backup/generals-bot/";
    #     . ./run-bot.ps1;
    #     $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeCustMap1 -nolog'
    #     try {
    #         Invoke-Expression $command
    #     } finally {
    #         Write-Host $command
    #         Start-Sleep -Seconds 1
    #     }
    # }

    # <#
    # Human in custom lobby with custom maps
    # #>
    # wt -w $windowName new-tab pwsh -NoExit -c {
    #     cd "D:/2019_reformat_Backup/generals-bot/";
    #     . ./run-bot.ps1;
    #     $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeCustMap2 -nolog'
    #     try {
    #         Invoke-Expression $command
    #     } finally {
    #         Write-Host $command
    #         Start-Sleep -Seconds 1
    #     }
    # }

    # # <#
    # # Human in custom lobby with alt tiles
    # # #>
    # # wt -w $windowName new-tab pwsh -NoExit -c {
    # #     cd "D:/2019_reformat_Backup/generals-bot/";
    # #     . ./run-bot.ps1;
    # #     $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeAltTiles1 -nolog'
    # #     try {
    # #         Invoke-Expression $command
    # #     } finally {
    # #         Write-Host $command
    # #         Start-Sleep -Seconds 1
    # #     }
    # # }

    # <#
    # Human in custom lobby with normal setup
    # #>
    # wt -w $windowName new-tab pwsh -NoExit -c {
    #     cd "D:/2019_reformat_Backup/generals-bot/";
    #     . ./run-bot.ps1;
    #     $command = 'Run-Human -left -game custom -sleepMax 1 -roomID Human.exeNormal1 -nolog'
    #     try {
    #         Invoke-Expression $command
    #     } finally {
    #         Write-Host $command
    #         Start-Sleep -Seconds 1
    #     }
    # }

    # ALT TESTING
    # Run-Human -name 'HaltWhoGoesThere' -game custom -private -sleepMax 1 -roomID Human.exeNormal1 -cpuAffinityMask 0
}




# starts a windows terminal that runs the standard live bots and opens dev tabs
function Start-WindowsTerminalBotServer2v2Bots {
    Param(
    )

    $windowName = 'Bot2v2Bots'

    <#
    Human 2v2 partners
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Human -game team -right -sleepMax 5 -nolog -botServer -cpuAffinityMask 0'


    # time for the terminal window to open
    start-sleep -seconds 3

    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-HumanTeammate -game team -right -sleepMax 10 -nolog -noui -botServer -cpuAffinityMask 2'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Teammate -sleepMax 10 -left -nolog -botServer -cpuAffinityMask 4'
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'Run-Teammate -sleepMax 10 -left -nolog -name Teammate2.exe -botServer -cpuAffinityMask 6'
}




# starts a windows terminal that runs the standard live bots and opens dev tabs
function Start-WindowsTerminalBotServerLiveBots {
    Param(
    )

    $windowName = 'BotServerLiveBots'
    <#
    FFA
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game ffa -name "EklipZ_ai" -right'

    # time for the terminal window to open
    start-sleep -seconds 3

    <#
    1v1 only
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game 1v1 -name "EklipZ_ai" -right'

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
    Start-RunBotWindowsTerminalTab -WindowName $windowName -LoadGameResultUtils

    <#
    private ek 14
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command "run-bot -game 1v1 -name 'EklipZ_ai_14' -noui -nolog -path $(Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-07-24' -BotFile 'bot_ek0x45.py') -privateGame testing"

    <#
    private live
    #>
    Start-RunBotWindowsTerminalTab -WindowName $windowName -Command 'run-bot -game 1v1 -name "EklipZ_ai" -left -privateGame testing'
}



function Run-Path {
    Param(
        $game = @('ffa'),
        $name = "PurdPath",
        [switch]$public,
        [switch]$nolog,
        [switch]$noTextLog,
        [switch]$noui,
        [int]$sleepMax = 3,
        $cpuAffinityMask = $Script:CheapBotCpuAffinityMask
    )
    while ($true)
    {
        foreach ($g in $game)
        {
            $playedGame = run-botonce -game $g -name $name -path (Get-PathBotPath) -nolog:$nolog -noTextLog:$noTextLog -noui:$noui -public:$public -cpuAffinityMask $cpuAffinityMask
            if ($playedGame) {
                SleepLeastOfTwo -sleepMax $sleepMax
            }
        }
    }
}



function Run-Blob {
    Param(
        $game = @('ffa'),
        $name = "PurdBlob",
        [switch]$public,
        [switch]$nolog,
        [switch]$noTextLog,
        [switch]$noui,
        [int]$sleepMax = 3,
        $cpuAffinityMask = $Script:CheapBotCpuAffinityMask
    )
    while ($true)
    {
        foreach ($g in $game)
        {
            $playedGame = run-botonce -game $g -name $name -path (Get-BlobBotPath) -nolog:$nolog -noTextLog:$noTextLog -noui:$noui -public:$public -cpuAffinityMask $cpuAffinityMask
            if ($playedGame) {
                SleepLeastOfTwo -sleepMax $sleepMax
            }
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
        $path = $(Join-Path (Get-ConfiguredRepoRoot) 'BotHost.py'),
        [switch]$nolog,
        [switch]$noTextLog,
        [switch]$publicLobby,
        $sleepMax = 30,
        $cpuAffinityMask = [IntPtr]::Zero
    )
    if ($privateGame -is [string]) {
        if (-not $roomID) {
            $roomID = $privateGame
            $PSBoundParameters['roomID'] = $roomID
        }
        $privateGame = $true
        $PSBoundParameters['privateGame'] = $true
    }
    $games = $game
    while($true)
    {
        foreach ($g in $games)
        {
            write-verbose $g -verbose
            $psboundparameters['game'] = $g
            $playedGame = Run-BotOnce @psboundparameters
            if ($playedGame) {
                SleepLeastOfTwo -sleepMax $sleepMax
            }
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
        [switch]$noTextLog,
        [switch]$publicLobby
    )
    if ($privateGame -is [string]) {
        if (-not $roomID) {
            $roomID = $privateGame
            $PSBoundParameters['roomID'] = $roomID
        }
        $privateGame = $true
        $PSBoundParameters['privateGame'] = $true
    }
    $games = $game
    $date = Get-Date -Format 'yyyy-MM-dd'
    $checkpointLoc = Join-Path (Get-CheckpointBackupRoot) "generals-bot-$date"
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
        $source = $(Get-ConfiguredRepoRoot),
        $dest = $(Get-CheckpointMirrorRoot),
        $backup = $(Join-Path (Get-CheckpointBackupRoot) "generals-bot-$(Get-Date -Format 'yyyy-MM-dd')")
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
        [switch] $noTextLog,
        $name = 'Human.exe',
        [switch] $botServer,
        $cpuAffinityMask = 0
    )
    $splat = @{
        noui = $noui
        right = -not $left
        nolog = $nolog
        noTextLog = $noTextLog
        public = -not $botServer
        cpuAffinityMask = $cpuAffinityMask
    }
    while ($true)
    {
        foreach ($g in $game)
        {
            $playedGame = run-botonce -game $g -name $name -roomID $roomID @splat -privateGame:$private
            if ($playedGame) {
                SleepLeastOfTwo -sleepMax $sleepMax
            }
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
        [switch] $noTextLog,
        [switch] $botServer,
        $cpuAffinityMask = 2
    )

    $splat = @{
        noui = $noui
        right = -not $left
        userID = 'efgHuman.py'
        nolog = $nolog
        noTextLog = $noTextLog
        public = -not $botServer
        cpuAffinityMask = $cpuAffinityMask
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
        [switch] $noTextLog,
        $name = "Teammate.exe",
        [switch] $botServer,
        $cpuAffinityMask = 4
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
        noTextLog = $noTextLog
        public = -not $botServer
        cpuAffinityMask = $cpuAffinityMask
    }

    while ($true)
    {
        $playedGame = Run-BotOnce -game "team" -name $name @splat
        if (-not $playedGame) {
            continue
        }

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

