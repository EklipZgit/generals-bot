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