


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