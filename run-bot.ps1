﻿


function Run-BotOnce { 
    Param(
        $name, 
        $game, 
        [switch]$public, 
        [switch]$right, 
        $privateGame, 
        [switch]$noui,
        $path = "C:\generals-bot\bot_ek0x45.py",
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
	`$logPath = "H:\GeneralsLogs\`$logFile"
	if (-not `$$($nolog.ToString()))
	{
		Start-Transcript -path "`$logPath"
	}
    try {
        #Write-Verbose `"C:\Python36-32\python.exe $path -name $name -g $game $argString`" -verbose
        C:\Python36-32\python.exe "$path" -name '$name' -g '$game' @arguments 2>&1 
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
			if (`$repId)
			{
				`$folder = Get-ChildItem "H:\GeneralsLogs" -Filter "*`$repId*" -Directory
				`$newLogPath = Join-Path `$folder.FullName "_`$logFile"
				`$newContent | Set-Content -Path `$newLogPath -Force
				`$null = mkdir H:\GeneralsLogs\GroupedLogs -Force
				`$newFolder = Move-Item `$folder.FullName "H:\GeneralsLogs\GroupedLogs" -PassThru
				`$newName = "`$logName---`$repId"
				Rename-Item `$newFolder.FullName `$newName -PassThru
				Write-Warning "`$newName"
				Write-Warning "`$newName"
				Write-Warning "`$newName"
			}
			Remove-Item `$logPath -Force
		}
    }
    PING 127.0.0.1 -n 1 | out-null
	Get-ChildItem "H:\GeneralsLogs" | ? { `$_.FullName -notlike '*_chat*' } | ? { `$_.LastWriteTime -lt (get-date).AddMinutes(-30) } | Remove-Item -Force -Recurse -ErrorAction Ignore
	Get-ChildItem "H:\GeneralsLogs\GroupedLogs" -Directory | ? { `$_.FullName -notlike '*_chat*' } | ? { `$_.LastWriteTime -lt (get-date).AddMinutes(-30) } | Remove-Item -Force -Recurse -ErrorAction Ignore
"@

	$randNums = 1..10 | Get-Random -Count 10
	$randName = $randNums -join ''
	$ps1File = "C:\temp\$randName.ps1"
	$exeString | Out-File $ps1File
	Write-Verbose $ps1File -Verbose
	start Powershell "-File $ps1File" -Wait -NoNewWindow
	Write-Verbose 'Powershell finished, sleeping' -Verbose
}



function Run-SoraAI {
    Param(
        $name, 
        [string[]]
        $game, 
        [switch]$public, 
        [switch]$right, 
        $privateGame, 
        [switch]$noui,
		[switch]$publicLobby
    )

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
		$path = "C:\generals-bot\bot_ek0x45.py",
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
    if (-not $nocopy)
    {
		$date = Get-Date -Format 'yyyy-MM-dd'
		Create-Checkpoint -backup "C:\generals-bot-historical\generals-bot-$date"
    }
    while($true)
    {
        foreach ($g in $games)
        {
            write-verbose $g -verbose
            $psboundparameters['game'] = $g
            Run-BotOnce @psboundparameters -path "C:\generals-bot-checkpoint\bot_ek0x45.py"
        }
    }
}


function Create-Checkpoint {
	Param(
		$source = 'C:\generals-bot\',
		$dest = 'C:\generals-bot-checkpoint\',
		$backup = "C:\generals-bot-historical\generals-bot-$(Get-Date -Format 'yyyy-MM-dd')"
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