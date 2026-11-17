<#
.SYNOPSIS
Scans recent game log folders for fog ArmyTracking desyncs: turns where the bot
tracks more large armies of a given value in the fog than actually exist on the
true (replay-simulated) board.

.DESCRIPTION
For every <turn>.txtmap in each scanned game folder the bot's serialized
ArmyTracker state (the `Armies=` footer written by TextMapLoader.dump_armies)
is reconstructed and collapsed into entanglement groups: a split army's fog
hypotheses mutually list each other's tiles and count as ONE army (matching the
bot's own model, where army.entangledArmies defines the group). Independent
trackers that merely sit on a tile another group claims as a hypothesis are NOT
merged - that asymmetry is itself part of the multiplication signature.

A turn is suspicious for a player when they have any large fog army group
(a lone phantom stack is already a desync candidate), when the anticipated
sum over their fog groups approaches their true standing army ({c}Score minus
{c}Tiles in the footer is server truth), or when one claimed army is huge
relative to standing. Suspicious turns get a .truemap.txtmap dumped into the
shared replay-dump cache via ReplayTools\ReplayTxtmapDump.js (same replay
parser Create-TestContinuingGameFrom uses; cached truemaps are reused on
later runs, and truemaps previously left inside the game folder by older
runs are still reused read-only - new dumps never write there).
If the dumper's orientation verify fails (rotated FFA views), it retries with
--no-verify and cross-checks the dumped {c}Score/{c}Tiles against the bot
footer's server scoreboard before trusting the map; those findings are marked
UnverifiedOrientation=True. Each claimed fog army value is greedily matched
against the player's real tiles on the true map (ValueTolerance window, and a
lone claim needs a much wider LooseShrinkTolerance window to be explained by
an unseen fog fight); leftover claims mean the bot multiplied a large army
out into the fog.

Output is a list of candidate .txtmap paths plus, per flagged player: the army
names + coordinates of the suspected duplicate trackers, their claimed size,
the bot's anticipated sum over all entanglement groups, and the player's real
large-tile army on the true map.

.PARAMETER LogRoot
Folder containing per-game log folders (each named '<desc>---<replayId>').
Defaults to the grouped_folder key in ..\run_config.txt.

.PARAMETER MaxGames
How many of the most recently written game folders to scan.

.PARAMETER MinTurn / TurnStride
Skip txtmaps below MinTurn and only evaluate every TurnStride-th turn.
Cheap txtmap parsing still runs per stride; truemap dumps only happen for
suspicious turns.

.PARAMETER MinLargeArmy
Claimed army value at or above which a fog group counts as "large".

.PARAMETER ValueTolerance
A true tile can explain a claimed army when its army is within this fraction of
the claim (default 0.35 absorbs income drift between last-seen and now).

.PARAMETER BoundFraction / SingleClaimFraction
Prefilter dump triggers: anticipatedAll > standing * BoundFraction, or one
claimed large army >= standing * SingleClaimFraction.

.PARAMETER SumRatio / SumExcess
Finding trigger: anticipatedLargeSum - trueLargeSum >= SumExcess AND
anticipatedLargeSum >= trueLargeSum * SumRatio.

.PARAMETER LooseShrinkTolerance
A single unmatched fog claim is only flagged when no true tile could be the
same army after shrinking by up to this fraction in unseen fog fights.

.PARAMETER MaxDumpsPerGame / MaxFindingsPerGame
Caps on truemap dumps and reported findings per game folder.

.PARAMETER RedumpInterval
Re-verify a recurring suspicion signature after this many turns even when the
claims themselves are unchanged (the truth may have moved underneath them).

.PARAMETER ForceRedump
Delete cached .truemap.txtmap files and regenerate them.

.PARAMETER PrefilterOnly
Only run the cheap txtmap suspicion pass; no replay dumps, no findings.

.PARAMETER FolderFilter / SinceHours
Game folder name filter and recency cutoff for selecting folders.

.PARAMETER ReportPath
Where to write the human-readable report; defaults to a timestamped file
under C:\cascade-debug-output\generals-bot\fog-desync-scan.

.PARAMETER AllFlaggedTurns
Report every flagged turn instead of deduping repeats of the same signature
inside a game.

.EXAMPLE
.\ScanRecentGamesForFogDesyncs.ps1 -MaxGames 10

.EXAMPLE
.\ScanRecentGamesForFogDesyncs.ps1 -LogRoot C:\KeptGeneralsLogs -MinLargeArmy 30
#>
[CmdletBinding()]
param(
    [string]$LogRoot,
    [string]$FolderFilter = '*---*',
    [int]$MaxGames = 25,
    [int]$SinceHours = 0,
    [int]$MinTurn = 1,
    [int]$TurnStride = 1,
    [int]$MinLargeArmy = 20,
    [double]$ValueTolerance = 0.35,
    [double]$BoundFraction = 0.7,
    [double]$SingleClaimFraction = 0.5,
    [double]$SumRatio = 1.5,
    [double]$SumExcess = 30,
    [double]$LooseShrinkTolerance = 0.6,
    [int]$MaxDumpsPerGame = 40,
    [int]$MaxFindingsPerGame = 10,
    [int]$RedumpInterval = 50,
    [switch]$AllFlaggedTurns,
    [switch]$ForceRedump,
    [switch]$PrefilterOnly,
    [string]$ReportPath
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'game-result-analysis-utils.ps1')

$script:PlayerChars = 'abcdefghijklmnop'

# -----------------------------------------------------------------------------
# txtmap parsing (mirrors ReplayTools/ReplayTxtmapDump.js::parseTxtmap and
# Sim/TextMapLoader.py: ragged rows pad out to the authoritative header width,
# footer starts at the first row beginning with '|').
# -----------------------------------------------------------------------------

function ConvertFrom-TxtmapCell {
    param([string]$Raw)
    $cell = [PSCustomObject]@{
        Owner   = -1
        Army    = 0
        Fog     = $false   # 'D' suffix => discovered but not currently visible
        City    = $false
        General = $false
        Empty   = $false
    }
    $trim = $Raw.Trim()
    if ($trim.Length -eq 0) { $cell.Empty = $true; return $cell }
    if ($trim.EndsWith('D')) {
        $cell.Fog = $true
        $trim = $trim.Substring(0, $trim.Length - 1)
    }
    if ($trim.Length -eq 0) { $cell.Empty = $true; return $cell }
    if ($script:PlayerChars.Contains($trim[0])) {
        $cell.Owner = $script:PlayerChars.IndexOf($trim[0])
        $trim = $trim.Substring(1)
    }
    $flags = ''
    while ($trim.Length -gt 0 -and [char]::IsUpper($trim[0])) {
        $flags += $trim[0]
        $trim = $trim.Substring(1)
    }
    if ($flags.Contains('C')) { $cell.City = $true }
    if ($flags.Contains('G')) { $cell.General = $true }
    if ($trim.Length -gt 0 -and $trim -match '^\d+$') { $cell.Army = [int]$trim }
    return $cell
}

function Read-Txtmap {
    param([Parameter(Mandatory)][string]$Path)
    $lines = [System.IO.File]::ReadAllLines($Path)
    if ($lines.Count -lt 2) { return $null }
    $widthRow = $lines[0]
    $width = ([regex]::Matches($widthRow, '\|')).Count
    if ($width -le 0) { return $null }
    $cellWidth = $widthRow.Split('|')[1].Length + 1
    $grid = New-Object 'System.Collections.Generic.List[object]'
    $footer = @{}
    $inFooter = $false
    for ($r = 1; $r -lt $lines.Count; $r++) {
        $row = $lines[$r]
        if ($row.StartsWith('|')) { $inFooter = $true; continue }
        if (-not $inFooter) {
            $cells = New-Object 'System.Collections.Generic.List[object]'
            $span = [Math]::Max($row.Length, $width * $cellWidth)
            for ($i = 0; $i -lt $span; $i += $cellWidth) {
                $cellText = ''
                if ($i -lt $row.Length) {
                    $cellText = $row.Substring($i, [Math]::Min($cellWidth, $row.Length - $i))
                }
                $cells.Add((ConvertFrom-TxtmapCell $cellText))
            }
            $grid.Add($cells)
        } else {
            $eq = $row.IndexOf('=')
            if ($eq -gt 0) {
                $footer[$row.Substring(0, $eq).Trim()] = $row.Substring($eq + 1).Trim()
            }
        }
    }
    return [PSCustomObject]@{ Grid = $grid; Footer = $footer; Width = $width; Height = $grid.Count }
}

# -----------------------------------------------------------------------------
# Armies= footer parse. Serialization (TextMapLoader.dump_armies):
#   name+value!entangledValue^lastSeen*lastMoved&paths%ownTile|entangled...@reverts
# entries joined by ':'. Only fields needed for desync detection are read.
# -----------------------------------------------------------------------------

function Get-SerializedArmies {
    param([hashtable]$Footer)
    $entries = New-Object 'System.Collections.Generic.List[object]'
    if (-not $Footer.ContainsKey('Armies')) { return $entries }
    foreach ($armyRaw in $Footer['Armies'].Split(':')) {
        if ($armyRaw.Length -eq 0) { continue }
        $rest = $armyRaw
        $at = $rest.IndexOf('@')
        if ($at -ge 0) { $rest = $rest.Substring(0, $at) }
        $i = $rest.IndexOf('+'); if ($i -lt 0) { continue }
        $name = $rest.Substring(0, $i); $rest = $rest.Substring($i + 1)
        $i = $rest.IndexOf('!'); if ($i -lt 0) { continue }
        $value = [int]$rest.Substring(0, $i); $rest = $rest.Substring($i + 1)
        $i = $rest.IndexOf('^'); if ($i -lt 0) { continue }
        $rest = $rest.Substring($i + 1)  # entangledValue ('None' or int) - value already captures the claim
        $i = $rest.IndexOf('*'); if ($i -lt 0) { continue }
        $lastSeen = [int]$rest.Substring(0, $i); $rest = $rest.Substring($i + 1)
        $i = $rest.IndexOf('&'); if ($i -lt 0) { continue }
        $lastMoved = [int]$rest.Substring(0, $i); $rest = $rest.Substring($i + 1)
        $i = $rest.IndexOf('%'); if ($i -lt 0) { continue }
        $tileStr = $rest.Substring($i + 1)
        $tiles = New-Object 'System.Collections.Generic.List[string]'
        foreach ($ts in $tileStr.Split('|')) {
            $xy = $ts.Split(',')
            if ($xy.Count -ge 2 -and $xy[0] -match '^\d+$' -and $xy[1] -match '^\d+$') {
                $tiles.Add("$([int]$xy[0]),$([int]$xy[1])")
            }
        }
        if ($tiles.Count -eq 0) { continue }
        $ox, $oy = $tiles[0].Split(',')
        $entries.Add([PSCustomObject]@{
            Name      = $name
            Value     = $value
            LastSeen  = $lastSeen
            LastMoved = $lastMoved
            OwnX      = [int]$ox
            OwnY      = [int]$oy
            OwnTile   = $tiles[0]
            Tiles     = $tiles
        })
    }
    # ,-wrap so a lone entry still returns List[object], not a bare PSCustomObject.
    return ,$entries
}

# Groups serialized armies into entanglement groups. Two entries merge only when
# they MUTUALLY claim each other's own tile as an alternative (the symmetric
# entanglement dump_armies writes for split hypotheses). An army that keeps
# another's tile in its entangled list while the other no longer lists back is
# de-entangled for real - merging it would hide exactly the duplicate trackers
# this scan exists to find.
function Group-ArmiesByEntanglement {
    param([System.Collections.Generic.List[object]]$Entries)
    $n = $Entries.Count
    $parent = 0..($n - 1)
    function Find-Root { param([int]$x)
        while ($parent[$x] -ne $x) { $parent[$x] = $parent[$parent[$x]]; $x = $parent[$x] }
        return $x
    }
    $ownTileToEntry = @{}
    for ($i = 0; $i -lt $n; $i++) { $ownTileToEntry[$Entries[$i].OwnTile] = $i }
    for ($i = 0; $i -lt $n; $i++) {
        foreach ($tk in $Entries[$i].Tiles) {
            $j = $ownTileToEntry[$tk]
            if ($null -eq $j -or $j -eq $i) { continue }
            # mutual entanglement: i lists j's tile AND j lists i's tile
            if (-not $Entries[$j].Tiles.Contains($Entries[$i].OwnTile)) { continue }
            $ra = Find-Root $i; $rb = Find-Root $j
            if ($ra -ne $rb) { $parent[$rb] = $ra }
        }
    }
    $groups = @{}
    for ($i = 0; $i -lt $n; $i++) {
        $r = Find-Root $i
        if (-not $groups.ContainsKey($r)) { $groups[$r] = New-Object 'System.Collections.Generic.List[object]' }
        $groups[$r].Add($Entries[$i])
    }
    # ,-wrap so callers always foreach over group lists even for a single
    # group: an unwrapped lone List[object] would iterate its member entries.
    $result = New-Object 'System.Collections.Generic.List[object]'
    foreach ($v in $groups.Values) { $result.Add($v) }
    return ,$result
}

function Get-CellAt {
    param($Grid, [int]$X, [int]$Y)
    if ($Y -lt 0 -or $Y -ge $Grid.Count) { return $null }
    $row = $Grid[$Y]
    if ($X -lt 0 -or $X -ge $row.Count) { return $null }
    return $row[$X]
}

# Builds the per-player fog-group picture for one bot txtmap.
# A member army is "fog" when its own tile is not currently visible: the grid
# cell carries the 'D' discovered-not-visible suffix, or the army's
# last_seen_turn is older than this turn (inferred tiles lose the 'D' marker
# entirely, so lastSeen is the reliable visibility signal).
function Get-FogPlayerState {
    param($Txtmap, [int]$Turn)
    $entries = Get-SerializedArmies -Footer $Txtmap.Footer
    $groups = Group-ArmiesByEntanglement -Entries $entries
    $byPlayer = @{}   # playerIndex -> List[psobject]
    foreach ($members in $groups) {
        $allFog = $true
        $claimed = 0
        $owner = -1
        $footprint = New-Object 'System.Collections.Generic.List[string]'
        $names = New-Object 'System.Collections.Generic.List[string]'
        $tilesDesc = New-Object 'System.Collections.Generic.List[string]'
        foreach ($m in $members) {
            $cell = Get-CellAt -Grid $Txtmap.Grid -X $m.OwnX -Y $m.OwnY
            $cellFog = $true
            if ($null -ne $cell -and -not $cell.Fog -and $m.LastSeen -ge $Turn) { $cellFog = $false }
            if (-not $cellFog) { $allFog = $false }
            if ($null -ne $cell -and $cell.Owner -ge 0 -and $owner -lt 0) { $owner = $cell.Owner }
            if ($m.Value -gt $claimed) { $claimed = $m.Value }
            $names.Add($m.Name)
            foreach ($tk in $m.Tiles) { if (-not $footprint.Contains($tk)) { $footprint.Add($tk) } }
            # own tile first, then the other hypothesis tiles this member still claims
            $others = @($m.Tiles | Where-Object { $_ -ne $m.OwnTile })
            $desc = "$($m.Name)@$($m.OwnTile) v$($m.Value) ls$($m.LastSeen)"
            if ($others.Count -gt 0) { $desc += " (alt: $($others -join '|'))" }
            $tilesDesc.Add($desc)
        }
        if ($owner -lt 0) { continue }  # no attributed owner - nothing to compare against
        if (-not $byPlayer.ContainsKey($owner)) { $byPlayer[$owner] = New-Object 'System.Collections.Generic.List[object]' }
        # NOTE: @($list) around a generic List inside a [PSCustomObject] literal
        # throws 'Argument types do not match' on PS7 - assign the list directly.
        $byPlayer[$owner].Add([PSCustomObject]@{
            Claimed   = $claimed
            Fog       = $allFog
            Members   = $members
            Names     = $names
            Footprint = $footprint
            Tiles     = $tilesDesc
        })
    }
    return $byPlayer
}

function Get-FooterInt {
    param([hashtable]$Footer, [string]$Key, [int]$Default = -1)
    if ($Footer.ContainsKey($Key) -and $Footer[$Key] -match '^-?\d+$') { return [int]$Footer[$Key] }
    return $Default
}

# -----------------------------------------------------------------------------
# Suspicion prefilter (cheap, no replay needed) and truemap verification.
# -----------------------------------------------------------------------------

function Get-TurnSuspicion {
    # Returns per-player suspicion info: @{ Player; Groups; Large; AnticipatedAll; AnticipatedLarge; Standing; Reason }
    param($ByPlayer, [hashtable]$Footer)
    $out = @{}
    foreach ($pi in $ByPlayer.Keys) {
        $c = $script:PlayerChars[$pi]
        $fog = @($ByPlayer[$pi] | Where-Object { $_.Fog })
        if ($fog.Count -eq 0) { continue }
        $large = @($fog | Where-Object { $_.Claimed -ge $MinLargeArmy })
        $anticipatedAll = ($fog | Measure-Object -Property Claimed -Sum).Sum
        if ($null -eq $anticipatedAll) { $anticipatedAll = 0 }
        $anticipatedLarge = ($large | Measure-Object -Property Claimed -Sum).Sum
        if ($null -eq $anticipatedLarge) { $anticipatedLarge = 0 }
        $standing = Get-FooterInt -Footer $Footer -Key "${c}StandingArmy"
        if ($standing -lt 0) {
            $score = Get-FooterInt -Footer $Footer -Key "${c}Score"
            $tiles = Get-FooterInt -Footer $Footer -Key "${c}Tiles"
            if ($score -ge 0 -and $tiles -ge 0) { $standing = $score - $tiles }
        }
        $reasons = @()
        if ($large.Count -ge 1) { $reasons += "LARGE_FOG_GROUPS($($large.Count))" }
        if ($standing -ge 0 -and $anticipatedAll -gt $standing * $BoundFraction) {
            $reasons += "ANTICIPATED_GT_BOUND($anticipatedAll>$([int]($standing * $BoundFraction)))"
        }
        if ($standing -ge 0 -and $large.Count -ge 1 -and $anticipatedLarge -ge $standing * $SingleClaimFraction) {
            $reasons += "HUGE_CLAIM($anticipatedLarge>=$([int]($standing * $SingleClaimFraction)))"
        }
        if ($reasons.Count -eq 0) { continue }
        $out[$pi] = [PSCustomObject]@{
            Player           = $pi
            FogGroups        = $fog
            LargeGroups      = $large
            AnticipatedAll   = $anticipatedAll
            AnticipatedLarge = $anticipatedLarge
            Standing         = $standing
            Reasons          = $reasons
        }
    }
    return $out
}

# Greedy one-to-one match of claimed fog armies against the player's real owned
# tiles on the true map. Any claim left over is a multiplied army.
function Compare-PlayerToTruemap {
    param($Suspicion, $TrueTiles)
    $pool = @()
    foreach ($t in $TrueTiles) {
        $pool += [PSCustomObject]@{ X = $t.X; Y = $t.Y; Army = $t.Army; Used = $false }
    }
    $claims = @($Suspicion.LargeGroups | Sort-Object { $_.Claimed } -Descending)
    $unmatched = New-Object 'System.Collections.Generic.List[object]'
    $matched = 0
    foreach ($g in $claims) {
        $lo = $g.Claimed * (1 - $ValueTolerance)
        $hi = $g.Claimed * (1 + $ValueTolerance)
        $best = $null; $bestDiff = [double]::MaxValue
        foreach ($t in $pool) {
            if ($t.Used -or $t.Army -lt $lo -or $t.Army -gt $hi) { continue }
            $d = [Math]::Abs($t.Army - $g.Claimed)
            if ($d -lt $bestDiff) { $best = $t; $bestDiff = $d }
        }
        if ($null -ne $best) { $best.Used = $true; $matched++ }
        else { $unmatched.Add($g) }
    }
    $trueLargeSum = 0
    $trueLargeTiles = @()
    foreach ($t in $pool) {
        if ($t.Army -ge $MinLargeArmy) {
            $trueLargeSum += $t.Army
            $trueLargeTiles += "$($t.X),$($t.Y)=$($t.Army)"
        }
    }
    $reasons = @()
    if ($unmatched.Count -gt 0) {
        $strongExtra = $claims.Count -ge 2
        if (-not $strongExtra) {
            # Lone claim: unmatched inside tolerance means nothing - the army
            # may have shrunk via an unseen fog fight. Only flag when NO true
            # tile of the player could even be a heavily-shrunk version of the
            # claimed army (i.e. the stack simply does not exist).
            $looseFloor = $unmatched[0].Claimed * (1 - $LooseShrinkTolerance)
            $strongExtra = -not (@($pool | Where-Object { $_.Army -ge $looseFloor }).Count -gt 0)
        }
        if ($strongExtra) { $reasons += "EXTRA_FOG_ARMIES($($unmatched.Count) unmatched of $($claims.Count))" }
    }
    $delta = $Suspicion.AnticipatedLarge - $trueLargeSum
    if ($delta -ge $SumExcess -and $Suspicion.AnticipatedLarge -ge $trueLargeSum * $SumRatio) {
        $reasons += "ANTICIPATED_SUM_EXCEEDS($($Suspicion.AnticipatedLarge) vs $trueLargeSum)"
    }
    if ($Suspicion.Standing -ge 0 -and $Suspicion.AnticipatedAll -gt $Suspicion.Standing + 10) {
        $reasons += "ANTICIPATED_GT_STANDING($($Suspicion.AnticipatedAll)>$($Suspicion.Standing))"
    }
    return [PSCustomObject]@{
        Matched      = $matched
        Unmatched    = $unmatched
        TrueLargeSum = $trueLargeSum
        TrueLarge    = $trueLargeTiles
        Reasons      = $reasons
    }
}

# Validates an unverified (--no-verify) truemap: the dumped {c}Score/{c}Tiles
# are sim truth, the bot footer's are the server scoreboard - equality for
# every player the bot recorded proves the replay sim reached this exact turn.
# Returns $false on any mismatch (wrong turn / diverged sim -> untrustworthy).
function Test-TruemapScoreboard {
    param([hashtable]$BotFooter, [string]$TruemapPath)
    $trueFooter = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($TruemapPath)) {
        $eq = $line.IndexOf('=')
        if ($eq -gt 0) { $trueFooter[$line.Substring(0, $eq).Trim()] = $line.Substring($eq + 1).Trim() }
    }
    for ($pi = 0; $pi -lt $script:PlayerChars.Length; $pi++) {
        $c = $script:PlayerChars[$pi]
        $botScore = Get-FooterInt -Footer $BotFooter -Key "${c}Score"
        if ($botScore -lt 0) { continue }
        $trueScore = Get-FooterInt -Footer $trueFooter -Key "${c}Score"
        $trueTiles = Get-FooterInt -Footer $trueFooter -Key "${c}Tiles"
        $botTiles = Get-FooterInt -Footer $BotFooter -Key "${c}Tiles"
        if ($trueScore -ne $botScore -or ($botTiles -ge 0 -and $trueTiles -ne $botTiles)) { return $false }
    }
    return $true
}

# -----------------------------------------------------------------------------
# Main scan
# -----------------------------------------------------------------------------

if ([string]::IsNullOrWhiteSpace($LogRoot)) { $LogRoot = Get-ConfiguredGroupedFolder }
if (-not (Test-Path $LogRoot)) { throw "Log root $LogRoot does not exist" }
if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $outDir = 'C:\cascade-debug-output\generals-bot\fog-desync-scan'
    $null = New-Item -ItemType Directory -Path $outDir -Force
    $ReportPath = Join-Path $outDir ("desyncs-{0:yyyyMMdd-HHmmss}.txt" -f (Get-Date))
}

$nodeOk = $null -ne (Get-Command node -ErrorAction SilentlyContinue)
if (-not $nodeOk) { Write-Warning "node not on PATH - truemap verification will be skipped for all games." }

$folders = Get-ChildItem -Path $LogRoot -Directory -Filter $FolderFilter |
    Where-Object { $_.BaseName -match '---' } |
    Sort-Object LastWriteTime -Descending
if ($SinceHours -gt 0) {
    $cutoff = (Get-Date).AddHours(-$SinceHours)
    $folders = $folders | Where-Object { $_.LastWriteTime -ge $cutoff }
}
$folders = @($folders | Select-Object -First $MaxGames)

Write-Host "Scanning $($folders.Count) game folder(s) under $LogRoot (MinLargeArmy=$MinLargeArmy tol=$ValueTolerance)"
$report = New-Object 'System.Collections.Generic.List[string]'
$results = New-Object 'System.Collections.Generic.List[object]'

foreach ($folder in $folders) {
    $replayId = ($folder.BaseName -split '---') | Select-Object -Last 1
    $maps = @(Get-ChildItem -Path $folder.FullName -Filter '*.txtmap' |
        Where-Object { $_.BaseName -match '^\d+$' } |
        Sort-Object { [int]$_.BaseName })
    if ($maps.Count -eq 0) { continue }

    $seenSignatures = @{}
    $findingSignatures = @{}
    $dumpsUsed = 0
    $dumpsFailed = 0
    $suspiciousTurns = 0
    $gameFindings = 0
    $turnsScanned = 0

    foreach ($map in $maps) {
        $turn = [int]$map.BaseName
        if ($turn -lt $MinTurn) { continue }
        if ($TurnStride -gt 1 -and (($turn - $MinTurn) % $TurnStride) -ne 0) { continue }
        $turnsScanned++

        $txtmap = Read-Txtmap -Path $map.FullName
        if ($null -eq $txtmap) { continue }
        $byPlayer = Get-FogPlayerState -Txtmap $txtmap -Turn $turn
        if ($byPlayer.Count -eq 0) { continue }
        $suspicion = Get-TurnSuspicion -ByPlayer $byPlayer -Footer $txtmap.Footer
        if ($suspicion.Count -eq 0) { continue }
        $suspiciousTurns++

        # One dump per distinct claim signature: identical signatures recur over
        # consecutive turns and verifying the earliest covers them.
        $sigParts = @()
        foreach ($pi in ($suspicion.Keys | Sort-Object)) {
            $s = $suspicion[$pi]
            $q = @($s.LargeGroups | ForEach-Object { [int][Math]::Round($_.Claimed / 5.0) * 5 } | Sort-Object)
            $sigParts += "$($script:PlayerChars[$pi])[$($q -join ',')]a$([int][Math]::Round($s.AnticipatedAll / 10.0))"
        }
        $signature = $sigParts -join ';'
        # A previously-seen signature is skipped - unless it has drifted long
        # enough that the army it tracked could have died/moved in reality
        # since the last verification (the claim can stay identical while the
        # truth changes underneath it).
        if ($seenSignatures.ContainsKey($signature) -and $turn - $seenSignatures[$signature] -lt $RedumpInterval) { continue }
        $seenSignatures[$signature] = $turn
        if ($PrefilterOnly) { continue }
        if (-not $nodeOk) { continue }
        if ($dumpsUsed -ge $MaxDumpsPerGame) { continue }

        # Truemap dumps live in the replay cache (Get-ReplayDumpCacheRoot),
        # never in the game folder. A truemap left in the game folder by older
        # runs is still reused read-only (skipped under -ForceRedump so a real
        # redump is forced); nothing is ever written there.
        $trueMapPath = Join-Path (Join-Path (Get-ReplayDumpCacheRoot) $replayId) "$($map.BaseName).truemap.txtmap"
        $legacyTrueMapPath = Join-Path $folder.FullName "$($map.BaseName).truemap.txtmap"
        $unverifiedOrientation = $false
        if ($ForceRedump -and (Test-Path $trueMapPath)) { Remove-Item $trueMapPath -Force }
        $readPath = $null
        if (Test-Path $trueMapPath) { $readPath = $trueMapPath }
        elseif (-not $ForceRedump -and (Test-Path $legacyTrueMapPath)) { $readPath = $legacyTrueMapPath }
        if ($null -eq $readPath) {
            $playerIndex = Get-FooterInt -Footer $txtmap.Footer -Key 'player_index' -Default 0
            $dumpsUsed++
            $dumpResult = Invoke-ReplayTrueMapDump -Map $map -Turn $turn -PlayerIndex $playerIndex -MovesTurns 0
            if ($null -eq $dumpResult -or -not (Test-Path $dumpResult.Map.FullName)) {
                # Verified dump failed - most commonly the rot90 FFA view the
                # dumper's orientation verify can't map. Retry unverified and
                # prove turn alignment by comparing the dumped {c}Score/{c}Tiles
                # (sim truth) against the bot footer's server scoreboard.
                $dumpResult = Invoke-ReplayTrueMapDump -Map $map -Turn $turn -PlayerIndex $playerIndex -MovesTurns 0 -NoVerify
                if ($null -eq $dumpResult -or -not (Test-Path $dumpResult.Map.FullName)) {
                    $dumpsFailed++
                    continue
                }
                if (-not (Test-TruemapScoreboard -BotFooter $txtmap.Footer -TruemapPath $dumpResult.Map.FullName)) {
                    # scoreboard mismatch = wrong turn / diverged sim - delete
                    # so it can never be mistaken for a valid cached truemap.
                    Remove-Item $dumpResult.Map.FullName -Force -ErrorAction SilentlyContinue
                    $dumpsFailed++
                    continue
                }
                $unverifiedOrientation = $true
            }
            $readPath = $dumpResult.Map.FullName
        }
        $truemap = Read-Txtmap -Path $readPath
        if ($null -eq $truemap) { $dumpsFailed++; continue }

        # True owned tiles per player (army > 0).
        $trueByPlayer = @{}
        for ($y = 0; $y -lt $truemap.Grid.Count; $y++) {
            $row = $truemap.Grid[$y]
            for ($x = 0; $x -lt $row.Count; $x++) {
                $cell = $row[$x]
                if ($cell.Owner -lt 0 -or $cell.Army -le 0) { continue }
                if (-not $trueByPlayer.ContainsKey($cell.Owner)) { $trueByPlayer[$cell.Owner] = New-Object 'System.Collections.Generic.List[object]' }
                $trueByPlayer[$cell.Owner].Add([PSCustomObject]@{ X = $x; Y = $y; Army = $cell.Army })
            }
        }

        foreach ($pi in $suspicion.Keys) {
            $s = $suspicion[$pi]
            $trueTiles = @()
            # @($genericList) hits the same 'Argument types do not match'
            # quirk as in [PSCustomObject] literals - unwrap via pipeline.
            if ($trueByPlayer.ContainsKey($pi)) { $trueTiles = @($trueByPlayer[$pi] | ForEach-Object { $_ }) }
            $cmp = Compare-PlayerToTruemap -Suspicion $s -TrueTiles $trueTiles
            if ($cmp.Reasons.Count -eq 0) { continue }

            $c = $script:PlayerChars[$pi]
            $uname = ''
            $uKey = "${c}Username"
            if ($txtmap.Footer.ContainsKey($uKey)) { $uname = $txtmap.Footer[$uKey] }
            # Dedup on (player, reason kinds, suspicious coords): a phantom
            # that persists across turns at the same tiles is one
            # investigation target, not N. Prefer unmatched footprints; sum-
            # only findings (empty unmatched) fall back to all large-group
            # footprints so they still distinguish by claim location.
            $sigGroups = if ($cmp.Unmatched.Count -gt 0) { $cmp.Unmatched } else { $s.LargeGroups }
            $findSig = "$c|" +
                (($sigGroups | ForEach-Object { $_.Footprint -join '|' } | Sort-Object) -join ';') +
                "|" + (($cmp.Reasons | ForEach-Object { ($_ -split '\(')[0] } | Sort-Object) -join '+')
            if (-not $AllFlaggedTurns -and $findingSignatures.ContainsKey($findSig)) { continue }
            $findingSignatures[$findSig] = $turn
            if ($gameFindings -ge $MaxFindingsPerGame) { continue }
            $gameFindings++

            $unmatchedDesc = @($cmp.Unmatched | ForEach-Object { "{ $($_.Tiles -join ' | ') }" })
            $unmatchedCoords = @($cmp.Unmatched | ForEach-Object { $_.Footprint -join '|' })
            $allGroupsDesc = @($s.FogGroups | ForEach-Object { "{ $($_.Tiles -join ' | ') }" })
            $finding = [PSCustomObject]@{
                TxtmapPath        = $map.FullName
                TruemapPath       = $readPath
                GameFolder        = $folder.FullName
                ReplayId          = $replayId
                Turn              = $turn
                UnverifiedOrientation = $unverifiedOrientation
                Player            = "$c (idx $pi) $uname"
                Reasons           = $cmp.Reasons
                Coords            = $unmatchedCoords
                UnmatchedGroups   = $unmatchedDesc
                AllFogGroups      = $allGroupsDesc
                AnticipatedLarge  = $s.AnticipatedLarge
                AnticipatedAll    = $s.AnticipatedAll
                TrueLargeSum      = $cmp.TrueLargeSum
                TrueLargeTiles    = $cmp.TrueLarge
                StandingArmy      = $s.Standing
            }
            $results.Add($finding)

            $report.Add("DESYNC  $($map.FullName)  (turn $turn, replay $replayId$(if ($unverifiedOrientation) { ', UNVERIFIED truemap - coords are canonical-view' }))")
            $report.Add("  player $c idx=$pi $uname  reasons: $($cmp.Reasons -join '; ')")
            $report.Add("  suspected duplicated army coords: $($unmatchedCoords -join '  ')")
            $report.Add("  suspected duplicated trackers: $($unmatchedDesc -join '  ')")
            $report.Add("  all fog groups for player: $($allGroupsDesc -join '  ')")
            $report.Add("  anticipated large sum=$($s.AnticipatedLarge) all-groups sum=$($s.AnticipatedAll) vs TRUE large-army sum=$($cmp.TrueLargeSum) standing=$($s.Standing)")
            $report.Add("  true large tiles: $($cmp.TrueLarge -join '  ')")
            $report.Add("")
            Write-Host "DESYNC  $($map.FullName) (turn $turn) player $c ${uname}: $($cmp.Reasons -join '; ')"
        }
    }

    Write-Host ("{0}: scanned {1} txtmaps, {2} suspicious, {3} truemap dumps ({4} failed), {5} finding(s)" -f $folder.BaseName, $turnsScanned, $suspiciousTurns, $dumpsUsed, $dumpsFailed, $gameFindings)
    $report.Add("GAME $($folder.BaseName): scanned $turnsScanned suspicious $suspiciousTurns dumps $dumpsUsed failed $dumpsFailed findings $gameFindings")
}

$report.Add("")
$report.Add("=== candidate txtmaps ===")
foreach ($r in $results) { $report.Add($r.TxtmapPath) }
$report | Set-Content -Path $ReportPath -Encoding utf8

Write-Host ""
Write-Host "Done. $($results.Count) candidate finding(s). Report written to $ReportPath"
return $results
