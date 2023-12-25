from __future__ import annotations

import typing
from collections import deque

import logbook

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from DangerAnalyzer import ThreatObj
from MapMatrix import MapMatrix
from Path import Path
from base.client.map import MapBase, Tile

# TODO remove me once things fixed
DEBUG_BYPASS_BAD_INTERCEPTIONS = True


class ArmyInterception(object):
    def __init__(
        self,
        threats: typing.List[ThreatObj]
    ):
        self.threats: typing.List[ThreatObj] = threats
        self.base_threat_army: int = 0
        self.common_intercept_chokes: typing.Dict[Tile, int] = {}
        self.furthest_common_intercept_distances: MapMatrix[int] = None
        self.target_tile: Tile = threats[0].path.start.tile

        # self.best_board_state: ArmySimState

        self.best_enemy_threat: ThreatObj | None = None
        self.best_threat_econ_value: int = 0

        self.intercept_options: typing.Dict[int, typing.Tuple[int, Path]] = {}


class ArmyInterceptor(object):
    def __init__(
        self,
        map: MapBase,
        boardAnalysis: BoardAnalyzer,
        useDebugLogging: bool = False
    ):
        self.map: MapBase = map
        self.board_analysis: BoardAnalyzer = boardAnalysis
        self.log_debug: bool = useDebugLogging

    def get_interception_plan(
        self,
        threats: typing.List[ThreatObj],
        turnsLeftInCycle: int
    ) -> ArmyInterception:
        self._validate_threats(threats)

        interception = ArmyInterception(threats)

        interception.common_intercept_chokes = self.get_shared_chokes(threats)

        self.determine_best_threat_value(interception, threats, turnsLeftInCycle)

        interception.base_threat_army = self._get_threats_army_amount(threats)
        # potentialRecaptureArmyInterceptTable = self._get_potential_intercept_table(turnsLeftInCycle, interception.base_threat_army)
        interception.intercept_options = self._get_intercept_plan(interception, turnsLeftInCycle)

        return interception

    def get_shared_chokes(self, threats: typing.List[ThreatObj]):
        commonChokesCounts = {}
        for threat in threats:
            for tile, interceptMoves in threat.armyAnalysis.interceptChokes.items():
                curCount = commonChokesCounts.get(tile, 0)
                commonChokesCounts[tile] = curCount + 1
        maxShared = 0
        for tile, num in commonChokesCounts.items():
            if num > maxShared:
                maxShared = num

        potentialSharedChokes = {}
        for tile, num in commonChokesCounts.items():
            if num != maxShared:
                continue

            maxWidth = -1
            for threat in threats:
                interceptMoves = threat.armyAnalysis.interceptChokes.get(tile, -1)
                if interceptMoves == -1:
                    continue

                if interceptMoves > maxWidth:
                    maxWidth = interceptMoves
            if maxWidth >= 0:
                potentialSharedChokes[tile] = maxWidth

        furthestPotentialCommon = max(potentialSharedChokes.keys(), key=lambda t: threats[0].armyAnalysis.bMap[t.x][t.y])
        furthestDist = threats[0].armyAnalysis.bMap[furthestPotentialCommon.x][furthestPotentialCommon.y]
        dists = SearchUtils.build_distance_map_matrix(self.map, [furthestPotentialCommon])

        # bestClassVal = 0
        sharedChokes = {}
        distLookups = {}
        for i in range(40):
            distLookups[i] = []

        queue = deque()
        queue.append((0, threats[0].path.start.tile, None))

        fromSets = {}
        toSets = {}
        lastDepth = -1
        lastVisited = set()
        visited = set()
        while len(queue) > 0:
            depth, tile, fromTile = queue.popleft()
            if tile in lastVisited:
                continue

            fSet = fromSets.get(tile, None)
            if fSet is None:
                fSet = set()
                fromSets[tile] = fSet
            fSet.add(fromTile)

            tSet = toSets.get(fromTile, None)
            if tSet is None:
                tSet = set()
                toSets[fromTile] = tSet
            tSet.add(tile)

            if depth > lastDepth:
                lastDepth = depth
                lastVisited.update(visited)
                visited.clear()
            if dists[tile] > furthestDist:
                logbook.info(f'skipping {str(tile)} because dists[tile] {dists[tile]} > furthestDist {furthestDist}')
                continue
            tilesAtDist = distLookups[depth]
            tilesAtDist.append(tile)
            if tile in visited:
                continue
            visited.add(tile)

            # INCLUDE mountains, we need to treat them as fucked stuff. Dont path THROUGH them though.
            if tile.isObstacle:
                continue

            for adj in tile.movable:
                if adj in potentialSharedChokes:
                    queue.append((depth + 1, adj, tile))

        common = {}
        fromCommon = set()
        prevTiles = []
        for i in range(40):
            tiles = distLookups[i]
            if len(tiles) == 0:
                continue
            # find the middle tile...?
            common.clear()
            fromCommon.clear()

            for tile in tiles:
                tile2 = tile
                fromTiles = fromSets[tile]
                fromCommon.update(fromTiles)
                toTiles = toSets.get(tile, None)

            for tile in tiles:
                allCommon = True
                fromTiles = fromSets[tile]
                for t in fromCommon:
                    if t not in fromTiles:
                        allCommon = False
                        break
                if allCommon:
                    # sharedChokes[tile] = i + len(fromTiles) + len(toTiles)
                    sharedChokes[tile] = potentialSharedChokes[tile]

        if len(sharedChokes) == 1 and len(threats) > 1 and threats[0].path.start.tile in sharedChokes:
            logbook.info(f'No shared chokes found against {threats}, falling back to just first threat intercept...')
            return self.get_shared_chokes(threats[0:1])

        return sharedChokes

    def _get_threats_army_amount(self, threats: typing.List[ThreatObj]) -> int:
        maxAmount = 0
        for threat in threats:
            curAmount = 0
            curTurn = self.map.turn + 1
            curOffset = 1
            for tile in threat.path.tileList:
                if self.map.is_tile_on_team_with(tile, threat.threatPlayer):
                    curAmount += tile.army - curOffset
                else:
                    if tile.army < threat.threatValue // 5:
                        curAmount -= tile.army + curOffset

                if curTurn % 50 == 0:
                    curOffset += 1

                curTurn += 1

            if curAmount > maxAmount:
                maxAmount = curAmount

        return maxAmount

    def _get_potential_intercept_table(self, turnsLeftInCycle: int, baseThreatArmy: int) -> typing.List[int]:
        """
        Returns a turn-offset lookup table of how much army we would want to intercept with at any given turn for a max recapture.
        We never need MORE army than this, but gathering 1 extra turn to move one up the intercept table is good ish.
        """

        potentialRecaptureArmyInterceptTable = [
            baseThreatArmy + 2 * i for i in range(turnsLeftInCycle)
        ]

        if turnsLeftInCycle < 15:
            for i in range(10):
                potentialRecaptureArmyInterceptTable.append(baseThreatArmy + 3 * i)

        if self.log_debug:
            for i, val in enumerate(potentialRecaptureArmyInterceptTable):
                logbook.info(f'intercept value turn {self.map.turn + i} = {val}')

        return potentialRecaptureArmyInterceptTable

    def _validate_threats(self, threats: typing.List[ThreatObj]):
        if len(threats) == 0:
            raise AssertionError(f'Threat list was empty.')
        threatTile = threats[0].path.start.tile
        for threat in threats:
            self.ensure_threat_army_analysis(threat)
            if threat.path.start.tile != threatTile:
                raise AssertionError(f'Can only get an interception plan for threats from one tile at a time.')

    def ensure_threat_army_analysis(self, threat):
        if threat.armyAnalysis is None:
            dists = SearchUtils.build_distance_map_matrix(self.map, [threat.path.start.tile])
            furthestPoint = max(threat.path.tileList, key=lambda t: dists[t] if self.map.is_tile_friendly(t) else 0)
            logbook.info(f'backfilling threat army analysis from {str(threat.path.start.tile)}->{str(furthestPoint)}')
            threat.armyAnalysis = ArmyAnalyzer(self.map, armyA=furthestPoint, armyB=threat.path.start.tile)

    def determine_best_threat_value(self, interception: ArmyInterception, threats: typing.List[ThreatObj], turnsLeftInCycle: int):
        maxThreat = None
        maxValPerTurn = -100000
        maxVal = -1000000

        for threat in threats:
            enPlayer = threat.threatPlayer
            frPlayer = self.map.player_index
            val, threatLen = self._get_path_value(threat.path, enPlayer, frPlayer, turnsLeftInCycle)

            valPerTurn = val / max(1, threatLen)
            if valPerTurn == maxValPerTurn and threat.path.length > maxThreat.path.length:
                maxValPerTurn -= 1

            if valPerTurn > maxValPerTurn:
                maxValPerTurn = valPerTurn
                maxVal = val
                maxThreat = threat

        logbook.info(f'best_enemy_threat was val {str(maxVal)} v/t {maxValPerTurn:.2f} - {str(maxThreat)}')
        interception.best_threat_econ_value = maxVal
        interception.best_enemy_threat = maxThreat

    def _get_path_value(
            self,
            path: Path,
            searchingPlayer: int,
            targetPlayer: int,
            turnsLeftInCycle: int,
            interceptingArmy: int = 0,
            includeRecaptureEffectiveStartDist: int = -1
    ) -> typing.Tuple[int, int]:
        """Returns (value, turnsUsed). turnsUsed is always the path length unless includeRecaptureEffectiveStartDist >= 0"""
        val = 0
        cityCaps = 0
        genCaps = 0
        curTurn = self.map.turn
        cycleEnd = self.map.turn + turnsLeftInCycle
        armyLeft = 0
        for tile in path.tileList:
            if armyLeft <= 0 and curTurn > self.map.turn:
                curTurn += 1
                break

            if not self.map.is_tile_on_team_with(tile, searchingPlayer):
                armyLeft -= tile.army

                if armyLeft > 0:
                    if tile.isGeneral:
                        genCaps += 1
                    if tile.isCity:
                        cityCaps += 1
                    if self.map.is_tile_on_team_with(tile, targetPlayer):
                        val += 2
                    else:
                        val += 1
            else:
                armyLeft += tile.army

            armyLeft -= 1

            curTurn += 1

            if (curTurn & 1) == 0:
                val += cityCaps

        # account for we considered the first tile in the list a move, when it is just the start tile
        curTurn -= 1
        armyLeft -= interceptingArmy

        if cycleEnd > curTurn and armyLeft > 0:
            left = cycleEnd - curTurn
            val += cityCaps * (left // 2)

            if includeRecaptureEffectiveStartDist >= 0:
                left -= includeRecaptureEffectiveStartDist
                curTurn += includeRecaptureEffectiveStartDist
                recaps = max(0, min(left, armyLeft // 2))
                curTurn += recaps
                val += recaps * 2

        return val, curTurn - self.map.turn

    def _get_intercept_plan(self, interception: ArmyInterception, turnsLeftInCycle: int) -> typing.Dict[int, typing.Tuple[int, Path]]:
        """turnsToIntercept -> econValueOfIntercept, interceptPath"""

        if len(interception.common_intercept_chokes) == 0:
            return {}

        furthestBackCommonIntercept = max(interception.common_intercept_chokes.keys(), key=lambda t: interception.threats[0].armyAnalysis.bMap[t.x][t.y])
        interception.furthest_common_intercept_distances = SearchUtils.build_distance_map_matrix(self.map, [furthestBackCommonIntercept])
        threatDistFromCommon = interception.furthest_common_intercept_distances[interception.target_tile]
        longestThreat = max(interception.threats, key=lambda t: t.turns)
        maxDepth = longestThreat.turns + 1

        threatValueOffset = interception.best_threat_econ_value

        bestInterceptTable: typing.Dict[int, typing.Tuple[int, Path]] = {}
        logbook.info(f'getting intercept paths at maxDepth {maxDepth}, threatDistFromCommon {threatDistFromCommon}')
        # TODO sort by earliest intercept + chokeWidth?
        for tile, interceptDist in interception.common_intercept_chokes.items():
            # TODO for final tile in the path, if tile is recapturable (city, normal tile) then increase maxDepth to turnsLeftInCycle
            turnsToIntercept = interception.best_enemy_threat.armyAnalysis.bMap[tile.x][tile.y] + 1 #- interceptDist

            interceptPaths = self._get_intercept_paths(
                tile,
                interception,
                maxDepth=min(maxDepth, turnsToIntercept),
                turnsLeftInCycle=turnsLeftInCycle,
                threatDistFromCommon=threatDistFromCommon,
                searchingPlayer=self.map.player_index)

            debugBadCutoff = max(1, interception.base_threat_army // 10)

            for dist, path in interceptPaths.items():
                interceptPointDist = interception.threats[0].armyAnalysis.bMap[path.tail.tile.x][path.tail.tile.y]

                if DEBUG_BYPASS_BAD_INTERCEPTIONS and path.start.tile.army <= debugBadCutoff:
                    logbook.error(f'bypassed bad intercept plan {str(path)}')
                    continue

                addlTurns = interceptPointDist
                if not interception.target_tile.isCity:
                    interceptRemaining = max(0, interceptPointDist - path.length)
                    addlTurns = max(0, interceptRemaining - interceptRemaining // 2)
                    # addlTurns = max(0, interceptRemaining // 2)

                effectiveDist = path.length + addlTurns + interceptDist

                interceptArmy = interception.base_threat_army
                if interception.target_tile in path.tileSet:
                    interceptArmy -= interception.target_tile.army - 1

                newValue, turnsUsed = self._get_path_value(
                    path,
                    searchingPlayer=self.map.player_index,
                    targetPlayer=interception.threats[0].threatPlayer,
                    turnsLeftInCycle=turnsLeftInCycle,
                    interceptingArmy=interceptArmy,
                    includeRecaptureEffectiveStartDist=addlTurns)
                newValue += self._get_value_of_threat_blocked(path, interception.best_enemy_threat, turnsLeftInCycle)

                if self.log_debug:
                    logbook.info(f'interceptPointDist:{interceptPointDist}, addlTurns:{addlTurns}, effectiveDist:{effectiveDist}, turnsUsed:{turnsUsed}')

                for curDist in range(path.length, turnsUsed + 1):
                    diff = turnsUsed - curDist
                    thisValue = newValue - diff * 2

                    existing = bestInterceptTable.get(curDist, None)
                    if existing is None:
                        if self.log_debug:
                            logbook.info(f'setting {curDist}.\n  new  {thisValue} {str(path)}')
                        bestInterceptTable[curDist] = thisValue, path
                        continue

                    existingValue, existingPath = existing
                    if thisValue > existingValue:
                        if self.log_debug:
                            logbook.info(f'replacing prev best for {curDist}.\n  prev {existingValue} {str(existingPath)}\n  new  {thisValue} {str(path)}')
                        bestInterceptTable[curDist] = thisValue, path

        # if self.log_debug:
        for i in range(interception.threats[0].armyAnalysis.shortestPathWay.distance):
            vals = bestInterceptTable.get(i, None)
            if vals:
                logbook.info(f'best turns {i} = {str(vals)}')
            else:
                logbook.info(f'best turns {i} = NONE')

        return bestInterceptTable

    def _get_intercept_paths(self, tile: Tile, interception: ArmyInterception, maxDepth: int, turnsLeftInCycle: int, threatDistFromCommon: int, searchingPlayer: int) -> typing.Dict[int, Path]:
        # negs = set()
        # if not self.map.is_tile_friendly(tile):
        #     negs.add(tile)

        startArmy = 0
        if self.map.is_tile_on_team_with(tile, searchingPlayer):
            startArmy = 0 - tile.army

        def valueFunc(curTile: Tile, prioObj):
            (
                dist,
                negTileCapPoints,
                negArmy
            ) = prioObj

            if curTile.player != self.map.player_index:
                return None

            # if negArmy > 0:
            #     return None

            recapVal = 0 - (negTileCapPoints + negArmy)

            return (
                recapVal,
                0 - negTileCapPoints,
                0 - negArmy
            )

        def prioFunc(nextTile: Tile, prioObj):
            (
                dist,
                negTileCapPoints,
                negArmy
            ) = prioObj

            if interception.furthest_common_intercept_distances[nextTile] > threatDistFromCommon + 1:
                return None

            if self.map.is_tile_on_team_with(nextTile, searchingPlayer):
                negArmy -= nextTile.army
            else:
                negArmy += nextTile.army
                negTileCapPoints += 1
                if not nextTile.isNeutral:
                    negTileCapPoints += 1

            negArmy += 1

            return (
                dist + 1,
                negTileCapPoints,
                negArmy
            )

        startTiles = {tile: ((0, 0, startArmy), 0)}
        results = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(
            self.map,
            startTiles=startTiles,
            valueFunc=valueFunc,
            maxDepth=maxDepth,
            noNeutralCities=True,
            priorityFunc=prioFunc,
            logResultValues=self.log_debug
        )

        paths = results.get(tile, [])

        byDist = {}
        if self.log_debug:
            logbook.info(f'@{str(tile)} returned {len(paths)} paths.')
        for path in paths:
            revPath = path.get_reversed()
            if self.log_debug:
                logbook.info(f'  path len {revPath.length} -- {str(revPath)}')
            byDist[revPath.length] = revPath

        return byDist

    def _get_value_of_threat_blocked(self, path: Path, best_enemy_threat: ThreatObj, turnsLeftInCycle: int) -> int:
        amountBlocked = 0
        turnsLeft = turnsLeftInCycle

        for tile in path.tileList:
            if turnsLeft == 0:
                break

            turnsLeft -= 1
            if tile not in best_enemy_threat.path.tileSet:
                if self.map.is_tile_friendly(tile):
                    amountBlocked += tile.army - 1
                else:
                    amountBlocked -= tile.army + 1

        node = best_enemy_threat.path.tail
        enArmy = best_enemy_threat.path.value
        frDist = best_enemy_threat.armyAnalysis.bMap[path.start.tile.x][path.start.tile.y]
        interceptDist = frDist - path.length
        enLen = best_enemy_threat.path.length

        while node is not None and enArmy < 0 and enLen > interceptDist:
            if self.map.is_tile_on_team_with(node.tile, best_enemy_threat.threatPlayer):
                enArmy -= node.tile.army
            else:
                enArmy += node.tile.army

            enArmy += 1
            node = node.prev
            enLen -= 1

        enArmy -= amountBlocked
        econValueBlocked = 0

        while node is not None and enArmy < 0 and enLen > interceptDist:
            if self.map.is_tile_on_team_with(node.tile, best_enemy_threat.threatPlayer):
                enArmy -= node.tile.army
            else:
                enArmy += node.tile.army
                if self.map.is_tile_friendly(node.tile):
                    econValueBlocked += 2
                else:
                    econValueBlocked += 1

            enArmy += 1
            node = node.prev
            enLen -= 1

        if self.log_debug:
            logbook.info(f'blocked {amountBlocked} at interceptDist {interceptDist} which prevented {econValueBlocked} econ damage with {str(path)}')

        return econValueBlocked
