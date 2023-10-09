push-location
$testFiles = foreach ($folder in "Tests") {
    cd $psscriptroot\$folder
    gci *.py
}

$files = foreach ($folder in "Sim", "Engine", "base", "base\client") {
    cd $psscriptroot\$folder
    gci *.py
}

cd $psscriptroot
$files += gci *.py
$lines = $files | get-content
$realLines = @($lines |?{$_.trim() -and -not $_.trim().startswith("#") })

$testLines = $testFiles | get-content
$testLines = @($testLines |?{$_.trim() -and -not $_.trim().startswith("#") })

$files
"main lines: $($realLines.count)"
"test lines: $($testLines.count)"
pop-location