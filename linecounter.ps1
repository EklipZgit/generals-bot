push-location
$files = foreach ($folder in "Sim", "Tests", "base", "base\client") {
    cd $psscriptroot\$folder
    gci *.py
}
cd $psscriptroot
$files += gci *.py
$lines = $files | get-content
$realLines = @($lines |?{$_.trim() -and -not $_.trim().startswith("#") })
$files
$realLines.count
pop-location