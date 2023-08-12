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