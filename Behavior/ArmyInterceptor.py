from __future__ import annotations

import typing

import logbook

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from DangerAnalyzer import ThreatObj, ThreatType
from DataModels import Move
from Interfaces import TilePlanInterface
from MapMatrix import MapMatrix
from Path import Path
from base.client.map import MapBase, Tile

# TODO remove me once things fixed
DEBUG_BYPASS_BAD_INTERCEPTIONS = True


class ThreatValueInfo(object):
    def __init__(self, threat: ThreatObj, value: float, turns: int):
        self.threat: ThreatObj = threat
        self.econ_value: float = value
        self.turns_used_by_enemy: int = turns
        self.econ_value_per_turn: float = value / max(1, turns)

    def __str__(self):
        return f'Threat {self.threat.path.start.tile}->{self.threat.path.tail.tile} (val {self.econ_value:.2f}, turns {self.turns_used_by_enemy}, vt {self.econ_value_per_turn:.2f}) {self.threat}'

    def __repr__(self):
        return str(self)


class ThreatBlockInfo(object):
    def __init__(self, tile: Tile, amount_needed_to_block: int):
        self.tile: Tile = tile
        self.amount_needed_to_block: int = amount_needed_to_block
        # list, not set, because set is slower to check than list for small numbers of entries, and we can never have more than 4
        self.blocked_destinations: typing.List[Tile] = []

    def add_blocked_destination(self, tile: Tile):
        if tile not in self.blocked_destinations:
            self.blocked_destinations.append(tile)

    def __str__(self) -> str:
        return f'{str(self.tile)}:{str(self.amount_needed_to_block)}@{"|".join([str(t) for t in self.blocked_destinations])}'


class InterceptPointTileInfo(object):
    def __init__(self, tile: Tile, minDelayTurns: int, maxExtraMoves: int, maxChokeWidth: int, maxInterceptTurnOffset: int):
        self.tile: Tile = tile

        self.max_delay_turns: int = minDelayTurns
        """The latest turns in the future that this tile must be reached in order to prevent subsequent damage in the worst case scenarios."""

        self.max_extra_moves_to_capture: int = maxExtraMoves
        """The maximum worst case number of moves that will be wasted to complete an intercept capture from this tile if reached by the min_delay_turns turn."""

        self.max_choke_width: int = maxChokeWidth
        """The width of the max choke. Informational only?"""

        self.max_intercept_turn_offset: int = maxInterceptTurnOffset
        """Mostly useless? The max offset based on chokewidths and distances to chokes, used to calculate the min_delay_turns"""

    def __str__(self) -> str:
        return f'{self.tile} - it{self.max_delay_turns}, cw{self.max_choke_width}, ic{self.max_intercept_turn_offset}, im{self.max_extra_moves_to_capture}'

    def __repr__(self) -> str:
        return str(self)


class InterceptionOptionInfo(TilePlanInterface):

    def __init__(self, path: Path, econValue: float, turns: int, damageBlocked: float, interceptingArmyRemaining: int, bestCaseInterceptMoves: int, requiredDelay: int):
        self.path: Path = path
        self._econ_value: float = econValue
        self._turns: int = turns
        self.damage_blocked: float = damageBlocked
        """The economic damage prevented by this intercept."""
        self.intercepting_army_remaining: int = interceptingArmyRemaining
        """The amount of the attacking army that will likely be remaining after the intercept completes."""
        self.best_case_intercept_moves: int = bestCaseInterceptMoves
        """While Turns should be the worst case intercept moves, this should be best case?"""
        self._requiredDelay: int = requiredDelay

        self.intercept: ArmyInterception | None = None

    @property
    def length(self) -> int:
        return self._turns

    @property
    def econValue(self) -> float:
        return self._econ_value

    @econValue.setter
    def econValue(self, value: float):
        self._econ_value = value

    @property
    def tileSet(self) -> typing.Set[Tile]:
        return self.path.tileSet

    @property
    def tileList(self) -> typing.List[Tile]:
        return self.path.tileList

    @property
    def requiredDelay(self) -> int:
        return self._requiredDelay

    def get_move_list(self) -> typing.List[Move]:
        return self.path.get_move_list()

    def get_first_move(self) -> Move:
        return self.path.get_first_move()

    def pop_first_move(self) -> Move:
        return self.path.pop_first_move()

    def __str__(self):
        return f'int {self.econValue:.2f}v/{self._turns}t ({self._econ_value / max(1, self._turns):.2f}vt) dBlk {self.damage_blocked:.2f}, armyLeft {self.intercepting_army_remaining}, bcm {self.best_case_intercept_moves}, del {self.requiredDelay}, path {self.path}'

    def __repr__(self):
        return str(self)

    def clone(self) -> InterceptionOptionInfo:
        clone = InterceptionOptionInfo(
            self.path.clone(),
            self.econValue,
            self._turns,
            self.damage_blocked,
            self.intercepting_army_remaining,
            self.best_case_intercept_moves,
            self._requiredDelay)
        return clone


class ArmyInterception(object):
    def __init__(
        self,
        threats: typing.List[ThreatValueInfo],
        ignoredThreats: typing.List[ThreatObj]
    ):
        self.threat_values: typing.List[ThreatValueInfo] = threats
        self.threats: typing.List[ThreatObj] = [t.threat for t in threats]

        self.ignored_threats: typing.List[ThreatObj] = ignoredThreats

        self.base_threat_army: int = 0
        self.common_intercept_chokes: typing.Dict[Tile, InterceptPointTileInfo] = {}
        self.furthest_common_intercept_distances: MapMatrix[int] = None
        self.target_tile: Tile = threats[0].threat.path.start.tile

        maxValPerTurn = -100000
        maxThreatInfo = None

        for threatInfo in threats:
            val = threatInfo.econ_value
            valPerTurn = threatInfo.econ_value_per_turn
            if valPerTurn == maxValPerTurn and threatInfo.threat.path.length > maxThreatInfo.threat.path.length:
                maxValPerTurn -= 1

            if valPerTurn > maxValPerTurn:
                maxValPerTurn = valPerTurn
                maxVal = val
                maxThreatInfo = threatInfo

        self.best_enemy_threat: ThreatValueInfo = maxThreatInfo

        self.intercept_options: typing.Dict[int, InterceptionOptionInfo] = {}
        """turnsToIntercept -> econValueOfIntercept, interceptPath"""

    def get_intercept_plan_values_by_path(self, path: Path) -> typing.Tuple[int | None, float | None]:
        """returns distance, value"""
        for dist, optionInfo in self.intercept_options.items():
            val = optionInfo.econValue
            p = optionInfo.path
            if p.start.tile == path.start.tile and p.tail.tile == path.tail.tile:
                return dist, val

        return None, None

    def get_intercept_option_by_path(self, path: Path) -> InterceptionOptionInfo | None:
        """returns distance, value"""
        if isinstance(path, InterceptionOptionInfo):
            return path

        for dist, optionInfo in self.intercept_options.items():
            p = optionInfo.path
            if p.start.tile == path.start.tile and p.tail.tile == path.tail.tile:
                return optionInfo

        return None


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
        turnsLeftInCycle: int,
        otherThreatsBlockingTiles: typing.Dict[Tile, ThreatBlockInfo] | None = None
    ) -> ArmyInterception | None:
        threatValues, ignoredThreats = self._prune_threats_to_valuable_threat_info(threats, turnsLeftInCycle)

        if len(threatValues) == 0:
            return None

        interception = ArmyInterception(threatValues, ignoredThreats)

        interception.common_intercept_chokes = self.get_shared_chokes(interception.threat_values, interception)
        threatMovable = [t for t in interception.target_tile.movableNoObstacles]
        if len(interception.common_intercept_chokes) <= len(threatMovable):
            countMightBeMovable = len(threatMovable) - len(interception.common_intercept_chokes)
            for mv in threatMovable:
                if mv in interception.common_intercept_chokes:
                    countMightBeMovable -= 1

            if countMightBeMovable == 0:
                # TODO do something with this info...?
                logbook.warn(f'ALL of the {len(interception.common_intercept_chokes)} common intercept chokes were only one tile adjacent to the threat. Should probably re-evaluate which threats we care about, then...?')

        interception.base_threat_army = self._get_threats_army_amount(threats)
        # potentialRecaptureArmyInterceptTable = self._get_potential_intercept_table(turnsLeftInCycle, interception.base_threat_army)
        interception.intercept_options = self._get_intercept_plan_options(interception, turnsLeftInCycle, otherThreatsBlockingTiles)
        if len(interception.intercept_options) == 0:
            logbook.warn(f'No intercept options found, retrying shared chokes but being more lenient filtering out threats')
            # try again, more friendly
            altThreatValues = [t for t in threatValues if t.threat.path.get_first_move().dest.lastMovedTurn < self.map.turn]
            if len(threatValues) > len(altThreatValues) > 0:
                newIgnored = [t.threat for t in threatValues if t not in altThreatValues]
                newIgnored.extend(ignoredThreats)
                interception = ArmyInterception(altThreatValues, newIgnored)

                interception.common_intercept_chokes = self.get_shared_chokes(interception.threat_values, interception)

                interception.base_threat_army = self._get_threats_army_amount(interception.threats)

                interception.intercept_options = self._get_intercept_plan_options(interception, turnsLeftInCycle, otherThreatsBlockingTiles)

        return interception

    def get_shared_chokes(
            self,
            threats: typing.List[ThreatValueInfo],
            interceptData: ArmyInterception,
    ) -> typing.Dict[Tile, InterceptPointTileInfo]:
        commonChokesCounts: typing.Dict[Tile, int] = {}
        # commonChokesCombinedTurnOffsets: typing.Dict[Tile, int] = {}
        commonMinDelayTurns = {}
        commonMaxExtraMoves = {}

        isThreatNotMoving = threats[0].threat.path.start.tile.lastMovedTurn < self.map.turn - 1
        # additionalOffset = 0
        # if isThreatNotMoving:
        #     additionalOffset = 2

        # withinOneAdditionalChecks = {}
        for threatValueInfo in threats:
            threat = threatValueInfo.threat
            # withinOneAdditionalChecks.clear()
            for tile in self.map.pathableTiles:
                interceptMoves = threat.armyAnalysis.interceptChokes[tile]
                delayTurns = threat.armyAnalysis.interceptTurns[tile]
                worstCaseExtraMoves = threat.armyAnalysis.interceptDistances[tile]

                # if tile == threat.path.start.tile:
                #     # we dont consider the start tile a shared choke...?
                #     continue

                if interceptMoves is None or delayTurns > 800:
                    continue

                curCount = commonChokesCounts.get(tile, 0)
                # curVal = commonChokesCombinedTurnOffsets.get(tile, 0)
                curExtraMoves = commonMaxExtraMoves.get(tile, 0)
                curMinDelayTurns = commonMinDelayTurns.get(tile, 1000)
                commonChokesCounts[tile] = curCount + 1
                # commonChokesCombinedTurnOffsets[tile] = curVal + interceptMoves + 1
                commonMaxExtraMoves[tile] = max(worstCaseExtraMoves, curExtraMoves)
                commonMinDelayTurns[tile] = min(curMinDelayTurns, delayTurns)
            #     for movable in tile.movable:
            #         if movable in threat.armyAnalysis.interceptChokes or movable.isObstacle:
            #             continue
            #         if threat.armyAnalysis.bMap[movable] >= threat.turns + 1 or threat.armyAnalysis.aMap[movable] > threat.turns + 1:
            #             continue
            #         existingMin = withinOneAdditionalChecks.get(movable, 10000)
            #         if existingMin > interceptMoves:
            #             withinOneAdditionalChecks[movable] = interceptMoves
            #
            # for tile, interceptMoves in withinOneAdditionalChecks.items():
            #     curCount = commonChokesCounts.get(tile, 0)
            #     curVal = commonChokesVals.get(tile, 0)
            #     commonChokesCounts[tile] = curCount + 1
            #     commonChokesVals[tile] = curVal + interceptMoves + 1

        maxShared = 0
        for tile, num in commonChokesCounts.items():
            if tile in threats[0].threat.path.start.tile.adjacents:
                # we dont consider the start tile or its immediate neighbors a shared choke from a 'find max shared count' perspective
                # TODO change if we start intercepting agnostic of the maximal shared chokes..?
                continue
            if num > maxShared:
                maxShared = num

        potentialSharedChokes = set()
        for tile, num in commonChokesCounts.items():
            if num < maxShared:
                continue

            potentialSharedChokes.add(tile)
            # maxWidth = -1
            # for threat in threats:
            #     interceptMoves = threat.armyAnalysis.interceptChokes.get(tile, -1)
            #     if interceptMoves == -1:
            #         continue
            #
            #     if interceptMoves > maxWidth:
            #         maxWidth = interceptMoves
            # if maxWidth >= 0:
            #     potentialSharedChokes[tile] = maxWidth

        if self.log_debug:
            # for tile, chokeVal in sorted(commonChokesCombinedTurnOffsets.items()):
            #     logbook.info(f'chokeVals: {str(tile)} = count {commonChokesCounts[tile]} - chokeVal {chokeVal}')

            for tile in potentialSharedChokes:
                dist = commonMinDelayTurns[tile]
                logbook.info(f'potential shared: {str(tile)} = dist {dist}')

        sharedChokes = self._build_shared_chokes(
            potentialSharedChokes,
            commonMaxExtraMoves,
            commonMinDelayTurns,
            threats)

        # if self.log_debug:
        #     for tile, dist in sorted(sharedChokes.items()):
        #         logbook.info(f'potential shared: {str(tile)} = dist {dist}')

        indexesToKeepIfBad = 1
        if len(sharedChokes) == 1 and len(threats) > indexesToKeepIfBad and threats[0].threat.path.start.tile in sharedChokes:
            logbook.info(f'No shared chokes found against {threats}, falling back to just first threat intercept...')
            interceptData.ignored_threats.extend([t.threat for t in threats[indexesToKeepIfBad:]])
            return self.get_shared_chokes(threats[0:indexesToKeepIfBad], interceptData)

        return sharedChokes

    def _build_shared_chokes(
            self,
            potentialSharedChokes: typing.Concatenate[typing.Iterable[Tile], typing.Container[Tile]],
            commonMaxExtraMoves: typing.Dict[Tile, int],
            commonMinDelayTurns: typing.Dict[Tile, int],
            threats: typing.List[ThreatValueInfo]
    ) -> typing.Dict[Tile, InterceptPointTileInfo]:
        sharedChokes = {}
        genBlockTile = None
        threatenedGen = None
        for threatInfo in threats:
            threat = threatInfo.threat
            if threat.path.tail.tile.isGeneral and self.map.is_tile_friendly(threat.path.tail.tile):
                if threat.threatValue < 0:
                    # TODO probably this needs to take into account the true value of the threat path...? PotentialThreat excludes our large blocking tiles, right?
                    continue
                threatenedGen = threat.path.tail.tile
                if threat.saveTile is not None:
                    genBlockTile = threat.saveTile
                    isGenThreatWithMultiPath = False
                    continue
                isGenThreatWithMultiPath = True
                for tile in threat.path.tileList[-2:1]:
                    if tile.isGeneral:
                        continue
                    ito = threat.armyAnalysis.interceptChokes[tile]
                    cw = threat.armyAnalysis.chokeWidths[tile]
                    # dists = threat.armyAnalysis.tileDistancesLookup[tile]
                    dist = threat.armyAnalysis.interceptDistances[tile]
                    if cw == 1:
                        isGenThreatWithMultiPath = False
                        logbook.info(f'genBlockTile is {tile} due')
                        genBlockTile = tile
                        break

        blockDist = 1000
        if threatenedGen:
            blockDist = 0
            if genBlockTile:
                blockDist = self.map.distance_mapper.get_distance_between(threatenedGen, genBlockTile)

        hi = 'hi'

        for tile in potentialSharedChokes:
            minDelayTurns = commonMinDelayTurns[tile]
            maxExtraMoves = commonMaxExtraMoves[tile]
            maxChokeWidth = 0
            maxInterceptTurnOffset = 0
            for threatInfo in threats:
                threat = threatInfo.threat
                ito = threat.armyAnalysis.interceptChokes[tile]
                cw = threat.armyAnalysis.chokeWidths[tile]
                if cw is not None:
                    maxChokeWidth = max(cw, maxChokeWidth)
                if ito is not None:
                    maxInterceptTurnOffset = max(ito, maxInterceptTurnOffset)

            if threatenedGen is not None and blockDist < self.map.distance_mapper.get_distance_between(threatenedGen, tile) and tile != threats[0].threat.path.start.tile:
                logbook.info(f'INCREASED MAX INTERCEPT {tile} DUE PRE CHOKE')
                # maxInterceptTurnOffset += 1
                minDelayTurns -= 1
            if self.log_debug:
                logbook.info(f'common choke {str(tile)} was '
                             f'minDelayTurns {minDelayTurns}, '
                             f'maxExtraMoves {maxExtraMoves}, '
                             f'maxChokeWidth {maxChokeWidth}, '
                             f'maxInterceptTurnOffset {maxInterceptTurnOffset}')
            sharedChokes[tile] = InterceptPointTileInfo(tile, minDelayTurns, maxExtraMoves, maxChokeWidth, maxInterceptTurnOffset)

        return sharedChokes

    # OLD
    # def _build_shared_chokes(
    #         self,
    #         potentialSharedChokes: typing.Concatenate[typing.Iterable[Tile], typing.Container[Tile]],
    #         commonMaxExtraMoves: typing.Dict[Tile, int],
    #         commonMinDelayTurns: typing.Dict[Tile, int],
    #         threats: typing.List[ThreatObj]
    # ) -> typing.Dict[Tile, InterceptPointTileInfo]:
    #     furthestPotentialCommon = max(potentialSharedChokes, key=lambda t: threats[0].armyAnalysis.bMap[t])
    #     furthestDist = threats[0].armyAnalysis.bMap[furthestPotentialCommon]
    #     dists = self.map.distance_mapper.get_tile_dist_matrix(furthestPotentialCommon)
    #
    #     sharedChokes = {}
    #     distLookups = {}
    #     for i in range(40):
    #         distLookups[i] = []
    #
    #     queue = deque()
    #     queue.append((0, threats[0].path.start.tile, None))
    #     fromSets = {}
    #     toSets = {}
    #     lastDepth = -1
    #     lastVisited = set()
    #     visited = set()
    #     while queue:
    #         depth, tile, fromTile = queue.popleft()
    #         if tile in lastVisited:
    #             continue
    #
    #         fSet = fromSets.get(tile, None)
    #         if fSet is None:
    #             fSet = set()
    #             fromSets[tile] = fSet
    #         fSet.add(fromTile)
    #
    #         tSet = toSets.get(fromTile, None)
    #         if tSet is None:
    #             tSet = set()
    #             toSets[fromTile] = tSet
    #         tSet.add(tile)
    #
    #         if depth > lastDepth:
    #             lastDepth = depth
    #             lastVisited.update(visited)
    #             visited.clear()
    #
    #         curDist = dists[tile]
    #         if curDist > furthestDist:
    #             if self.log_debug:
    #                 logbook.info(f'skipping {str(tile)} because dists[tile] {dists[tile]} > furthestDist {furthestDist}')
    #             continue
    #
    #         tilesAtDist = distLookups[depth]
    #         tilesAtDist.append(tile)
    #
    #         if tile in visited:
    #             continue
    #
    #         visited.add(tile)
    #
    #         # INCLUDE mountains, we need to treat them as fucked stuff. Dont path THROUGH them though.
    #         if tile.isObstacle:
    #             continue
    #
    #         for adj in tile.movable:
    #             if adj in potentialSharedChokes:
    #                 queue.append((depth + 1, adj, tile))
    #
    #     common = {}
    #     fromCommon = set()
    #     for i in range(40):
    #         tiles = distLookups[i]
    #         if len(tiles) == 0:
    #             continue
    #
    #         # find the middle tile...?
    #         common.clear()
    #         fromCommon.clear()
    #
    #         for tile in tiles:
    #             fromTiles = fromSets[tile]
    #             fromCommon.update(fromTiles)
    #             # toTiles = toSets.get(tile, None)
    #
    #         for tile in tiles:
    #             allCommon = len(fromCommon) > 0
    #             fromTiles = fromSets[tile]
    #             for t in fromCommon:
    #                 if t not in fromTiles:
    #                     allCommon = False
    #                     break
    #             if allCommon:
    #                 # sharedChokes[tile] = i + len(fromTiles) + len(toTiles)
    #                 if tile not in potentialSharedChokes:
    #                     if self.log_debug:
    #                         logbook.info(f'DEBUG: SHAREDINTERCEPTVAL WAS NONE FOR TILE {tile} IN INTERCEPT {threats[0].path.start.tile}')
    #                 else:
    #                     minDelayTurns = commonMinDelayTurns[tile]
    #                     maxExtraMoves = commonMaxExtraMoves[tile]
    #                     maxChokeWidth = 0
    #                     maxInterceptTurnOffset = 0
    #                     for threat in threats:
    #                         ito = threat.armyAnalysis.interceptChokes[tile]
    #                         cw = threat.armyAnalysis.chokeWidths[tile]
    #                         if cw is not None:
    #                             maxChokeWidth = max(cw, maxChokeWidth)
    #                         if ito is not None:
    #                             maxInterceptTurnOffset = max(ito, maxInterceptTurnOffset)
    #                     if self.log_debug:
    #                         logbook.info(f'common choke {str(tile)} was '
    #                                      f'minDelayTurns {minDelayTurns}, '
    #                                      f'maxExtraMoves {maxExtraMoves}, '
    #                                      f'maxChokeWidth {maxChokeWidth}, '
    #                                      f'maxInterceptTurnOffset {maxInterceptTurnOffset}')
    #                     sharedChokes[tile] = InterceptPointTileInfo(tile, minDelayTurns, maxExtraMoves, maxChokeWidth, maxInterceptTurnOffset)
    #
    #     return sharedChokes

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

    def _get_potential_intercept_table(self, turnsLeftInCycle: int, baseThreatArmy: int) -> typing.List[float]:
        """
        Returns a turn-offset lookup table of how much army we would want to intercept with at any given turn for a max recapture.
        We never need MORE army than this, but gathering 1 extra turn to move one up the intercept table is good ish.
        """

        potentialRecaptureArmyInterceptTable = [
            baseThreatArmy + 1.8 * i for i in range(turnsLeftInCycle)
        ]

        if turnsLeftInCycle < 15:
            for i in range(10):
                potentialRecaptureArmyInterceptTable.append(baseThreatArmy + 3 * i)

        if self.log_debug:
            for i, val in enumerate(potentialRecaptureArmyInterceptTable):
                logbook.info(f'intercept value turn {self.map.turn + i} = {val}')

        return potentialRecaptureArmyInterceptTable

    def _prune_threats_to_valuable_threat_info(self, threats: typing.List[ThreatObj], turnsLeftInCycle: int) -> typing.Tuple[typing.List[ThreatValueInfo], typing.List[ThreatObj]]:
        """
        Returns threatsToConsider, threatsIgnored

        @param threats:
        @param turnsLeftInCycle:
        @return:
        """
        if len(threats) == 0:
            raise AssertionError(f'Threat list was empty.')

        outThreats = []
        ignoredThreats: typing.List[ThreatObj] = []

        threatTile = threats[0].path.start.tile
        countCity = 0
        countGen = 0
        countExpansion = 0
        for threat in threats:
            if threat.path.length <= 0:
                ignoredThreats.append(threat)
                continue
            # Why was this here?
            # if threat.turns > 30:
            #     logbook.info(f'skipping long threat len {threat.turns} from {str(threat.path.start.tile)} to {str(threat.path.tail.tile)}')
            #     continue

            if threat.path.tail.tile.isGeneral:
                countGen += 1
                if countGen > 2:
                    logbook.info(f'bypassing {countGen}+ general threat {threat.path}')
                    ignoredThreats.append(threat)
                    continue
            elif threat.path.tail.tile.isCity:
                countCity += 1
                if countCity > 2:
                    logbook.info(f'bypassing {countCity}+ city threat {threat.path}')
                    ignoredThreats.append(threat)
                    continue
            else:
                countExpansion += 1
                if countExpansion > 3:
                    logbook.info(f'bypassing {countExpansion}+ expansion threat {threat.path}')
                    ignoredThreats.append(threat)
                    continue

            self.ensure_threat_army_analysis(threat)
            if threat.path.start.tile != threatTile:
                raise AssertionError(f'Can only get an interception plan for threats from one tile at a time. {str(threat.path.start.tile)} vs {str(threatTile)}')
            outThreats.append(threat)

        threatValues = self._determine_threat_values(outThreats, turnsLeftInCycle)
        maxLen = 0
        avgLen = 0
        for threat in threatValues:
            maxLen = max(threat.turns_used_by_enemy, maxLen)
            avgLen += threat.turns_used_by_enemy
        avgLen = avgLen / len(threatValues)

        lenCutoffIfNotCompliant = max(maxLen // 4, int(2 * avgLen / 3))
        lenCutoffIfNotCompliant = min(turnsLeftInCycle - 2, lenCutoffIfNotCompliant)
        finalThreats = []
        for threat in threatValues:
            if not threat.threat.path.tail.tile.isGeneral and threat.turns_used_by_enemy <= lenCutoffIfNotCompliant:
                logbook.info(f'bypassing threat due to turns {threat.turns_used_by_enemy} vs cutoff {avgLen}. Cut {threat}')
                ignoredThreats.append(threat.threat)
                continue
            finalThreats.append(threat)

        return finalThreats, ignoredThreats

    def ensure_threat_army_analysis(self, threat: ThreatObj) -> bool:
        """returns True if the army analysis was built"""
        if threat.path.value == 0:
            threat.path.calculate_value(threat.threatPlayer, self.map._teams)
        if threat.armyAnalysis is None:
            threat.armyAnalysis = ArmyAnalyzer.build_from_path(self.map, threat.path)
            return True
        return False

    def _determine_threat_values(self, threats: typing.List[ThreatObj], turnsLeftInCycle: int) -> typing.List[ThreatValueInfo]:
        maxValPerTurn = -100000
        maxVal = -1000000

        maxThreatInfo = None
        maxThreatKills = False

        threatValues = []

        for threat in threats:
            enPlayer = threat.threatPlayer
            frPlayer = self.map.player_index
            val, threatLen = self._get_path_econ_values_for_player(threat.path, enPlayer, frPlayer, turnsLeftInCycle)
            threatInfo = ThreatValueInfo(threat, val, threatLen)
            valPerTurn = threatInfo.econ_value_per_turn
            if valPerTurn == maxValPerTurn and threat.path.length > maxThreatInfo.threat.path.length:
                maxValPerTurn -= 1

            isKillThreat = threat.threatType == ThreatType.Kill and threat.threatValue > 0

            if (maxThreatKills == isKillThreat and valPerTurn > maxValPerTurn) or (maxThreatKills is False and isKillThreat):
                maxValPerTurn = valPerTurn
                maxVal = val
                maxThreatInfo = threatInfo
                maxThreatKills = isKillThreat

            threatValues.append(threatInfo)

        logbook.info(f'best_enemy_threat was val {maxVal:.2f} v/t {maxValPerTurn:.2f} - {str(maxThreatInfo)}')
        return threatValues

    def _get_path_econ_values_for_player(
            self,
            interceptionPath: Path,
            searchingPlayer: int,
            targetPlayer: int,
            turnsLeftInCycle: int,
            interceptingArmy: int = 0,
            includeRecaptureEffectiveStartDist: int = -1
    ) -> typing.Tuple[float, int]:
        """
        Returns (value, turnsUsed).
        turnsUsed is always the path length unless includeRecaptureEffectiveStartDist >= 0.
        value includes the recaptured tile value for the turns used here.
        """
        val = 0
        cityCaps = 0
        genCaps = 0
        curTurn = self.map.turn
        cycleEnd = self.map.turn + turnsLeftInCycle
        armyLeft = 0
        pathNode = interceptionPath.start
        while pathNode is not None:
            tile = pathNode.tile
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
                        val += 2.1
                    else:
                        val += 1
            else:
                armyLeft += tile.army

                if pathNode.move_half:
                    # we still intend to use the rest of the split army to capture the rest of the round, so DONT exclude it from the recaptures.
                    # armyLeft = armyLeft - armyLeft // 2
                    # however DO penalize our turn count, as we use one extra turn to do this.
                    curTurn += 1

            armyLeft -= 1

            curTurn += 1

            if (curTurn & 1) == 0:
                val += cityCaps

            pathNode = pathNode.next

            if curTurn > cycleEnd:
                break

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
                val += recaps * 2.1  # have to keep this same as the factor in expansion algo, or we pick expansion over intercept...

        return val, curTurn - self.map.turn

    def _get_intercept_plan_options(
            self,
            interception: ArmyInterception,
            turnsLeftInCycle: int,
            otherThreatsBlockingTiles: typing.Dict[Tile, ThreatBlockInfo] | None = None
    ) -> typing.Dict[int, InterceptionOptionInfo]:
        """turnsToIntercept -> econValueOfIntercept, interceptPath"""

        if len(interception.common_intercept_chokes) == 0:
            return {}

        furthestBackCommonIntercept = max(interception.common_intercept_chokes.keys(), key=lambda t: interception.threats[0].armyAnalysis.bMap[t])
        interception.furthest_common_intercept_distances = self.map.distance_mapper.get_tile_dist_matrix(furthestBackCommonIntercept)
        threatDistFromCommon = interception.furthest_common_intercept_distances[interception.target_tile]
        longestThreat = max(interception.threats, key=lambda t: t.turns)
        maxDepth = longestThreat.turns + 1

        averageEnemyPositionByTurn: typing.Dict[int, typing.Tuple[float, float]] = {}
        for i in range(0, interception.best_enemy_threat.threat.path.length):
            numThreatsAtThisDist = 0
            allThreatsX = 0
            allThreatsY = 0
            for threat in interception.threat_values:
                distances = threat.threat.armyAnalysis.tileDistancesLookup.get(i, None)
                if not distances:
                    continue

                numThreatsAtThisDist += 1
                xSum = 0
                ySum = 0
                numTilesAtThisDist = 0
                for t in distances:
                    xSum += t.x
                    ySum += t.y
                    numTilesAtThisDist += 1

                xAvg = xSum / numTilesAtThisDist
                yAvg = ySum / numTilesAtThisDist
                allThreatsX += xAvg
                allThreatsY += yAvg

            if numThreatsAtThisDist == 0:
                continue

            avgAllThreatsX = allThreatsX / numThreatsAtThisDist
            avgAllThreatsY = allThreatsY / numThreatsAtThisDist
            averageEnemyPositionByTurn[i] = avgAllThreatsX, avgAllThreatsY
            logbook.info(f'avgPos dist {i} = {avgAllThreatsX:.1f},{avgAllThreatsY:.1f}')

        bestInterceptTable: typing.Dict[int, InterceptionOptionInfo] = {}
        logbook.info(f'getting intercept paths at maxDepth {maxDepth}, threatDistFromCommon {threatDistFromCommon}')
        # TODO sort by earliest intercept + chokeWidth?
        tile: Tile
        interceptInfo: InterceptPointTileInfo
        for tile, interceptInfo in interception.common_intercept_chokes.items():
            if tile.isCity and tile.isNeutral:
                continue
            # # TODO where does this 3 come from...? I think this lets the intercept chase, slightly...?
            # # THE 3 is necessary to chase 1 tile behind. I'm not sure why, though...
            # arbitraryOffset = 3
            # # TODO for final tile in the path, if tile is recapturable (city, normal tile) then increase maxDepth to turnsLeftInCycle
            turnsToIntercept = interceptInfo.max_delay_turns

            depth = min(maxDepth, turnsToIntercept)

            if self.log_debug:
                logbook.info(f'\r\n\r\nChecking tile {str(tile)} with depth {depth} / threatDistFromCommon {threatDistFromCommon} / min(maxDepth={maxDepth}, turnsToIntercept={turnsToIntercept}) ')

            interceptPaths = self._get_intercept_paths(
                tile,
                interception,
                maxDepth=depth,
                turnsLeftInCycle=turnsLeftInCycle,
                threatDistFromCommon=threatDistFromCommon,
                searchingPlayer=self.map.player_index,
                positionsByTurn=averageEnemyPositionByTurn,
                otherThreatsBlockingTiles=otherThreatsBlockingTiles,
            )

            debugBadCutoff = max(1, interception.base_threat_army // 10)

            for dist, path in interceptPaths.items():
                interceptPointDist = interception.threats[0].armyAnalysis.bMap[path.tail.tile]
                """The distance from the threat to the intercept point"""

                if DEBUG_BYPASS_BAD_INTERCEPTIONS and path.start.tile.army <= debugBadCutoff:
                    logbook.error(f'bypassed bad intercept plan {str(path)}')
                    continue

                addlTurns = interceptPointDist
                """The number of additional turns beyond the path length that will need to be travelled to recoup our current tile-differential...? to reach the threat tile."""
                if not interception.target_tile.isCity:
                    # interceptRemaining = max(0, interceptPointDist - path.length)
                    # where the opponents army will ideally have moved to while we are moving to this position
                    # addlTurns = max(0, interceptRemaining - interceptRemaining // 2)
                    addlTurns = max(0, interceptPointDist - path.length)
                    # addlTurns = max(0, interceptRemaining // 2)

                # effectiveDist = path.length + addlTurns + interceptWorstCaseDistance
                effectiveDist = path.length + addlTurns + interceptInfo.max_extra_moves_to_capture
                """The effective distance that we need to travel before recapture starts"""

                interceptArmy = interception.base_threat_army
                if interception.target_tile in path.tileSet:
                    interceptArmy -= interception.target_tile.army - 1

                if otherThreatsBlockingTiles is not None:
                    pathNode = path.start
                    while pathNode is not None:
                        t = pathNode.tile
                        tileHold = otherThreatsBlockingTiles.get(t, None)
                        if tileHold is not None and pathNode.next is not None and pathNode.next.tile in tileHold.blocked_destinations:
                            # TODO
                            # interceptArmy -= max(tileHold, t.army // 2)
                            logbook.info(f'forcing {pathNode.tile} move half due to blocked destinations in {path}')
                            pathNode.move_half = True
                        pathNode = pathNode.next

                shouldDelay, shouldSplit = self._should_delay_or_split(tile, path, interception.threat_values, turnsLeftInCycle)
                if shouldSplit:
                    path.start.move_half = True

                if shouldDelay:
                    logbook.info(f'DETERMINED SHOULD DELAY FOR {tile} {path}')

                # TODO this is returning extra moves, see test_should_full_intercept_all_options
                newValue, turnsUsed = self._get_path_econ_values_for_player(
                    path,
                    searchingPlayer=self.map.player_index,
                    targetPlayer=interception.threats[0].threatPlayer,
                    turnsLeftInCycle=turnsLeftInCycle,
                    interceptingArmy=interceptArmy,
                    includeRecaptureEffectiveStartDist=addlTurns)  #+ (1 if shouldDelay else 0)
                turnsUsed += interceptInfo.max_extra_moves_to_capture
                blockedDamage, enemyArmyLeftAtIntercept, bestCaseInterceptMoves, worstCaseInterceptMoves = self._get_value_of_threat_blocked(path, interception.best_enemy_threat, turnsLeftInCycle)

                newValue += blockedDamage

                if self.log_debug:
                    logbook.info(f'interceptPointDist:{interceptPointDist}, addlTurns:{addlTurns}, effectiveDist:{effectiveDist}, turnsUsed:{turnsUsed}, blockedAmount:{blockedDamage}')

                # for curDist in range(path.length + addlTurns, turnsUsed + 1):
                for curDist in range(path.length, turnsUsed + 1):
                    diff = turnsUsed - curDist
                    thisValue = newValue - diff * 2

                    existing = bestInterceptTable.get(curDist, None)
                    opt = InterceptionOptionInfo(
                        path,
                        thisValue,
                        curDist,
                        damageBlocked=blockedDamage,
                        interceptingArmyRemaining=enemyArmyLeftAtIntercept,
                        bestCaseInterceptMoves=bestCaseInterceptMoves,
                        requiredDelay=1 if shouldDelay else 0)

                    opt.intercept = interception

                    if existing is None:
                        if self.log_debug:
                            logbook.info(f'setting bestInterceptTable[dist {curDist}]:\n  new  {str(opt)}')
                        bestInterceptTable[curDist] = opt
                        continue

                    if thisValue > existing.econValue:
                        if self.log_debug:
                            logbook.info(f'replacing bestInterceptTable[dist {curDist}]:\n  prev {str(existing)}\n  new  {str(opt)}')
                        bestInterceptTable[curDist] = opt

        # if self.log_debug:
        for i in range(interception.threats[0].armyAnalysis.shortestPathWay.distance):
            vals = bestInterceptTable.get(i, None)
            if vals:
                logbook.info(f'best turns {i} = {str(vals)}')
            else:
                logbook.info(f'best turns {i} = NONE')

        return bestInterceptTable

    def _get_intercept_paths(
            self,
            interceptAtTile: Tile,
            interception: ArmyInterception,
            maxDepth: int,
            turnsLeftInCycle: int,
            threatDistFromCommon: int,
            searchingPlayer: int,
            positionsByTurn: typing.Dict[int, typing.Tuple[float, float]],
            otherThreatsBlockingTiles: typing.Dict[Tile, ThreatBlockInfo] | None = None
    ) -> typing.Dict[int, Path]:
        # negs = set()
        # if not self.map.is_tile_friendly(tile):
        #     negs.add(tile)

        startArmy = 0
        if self.map.is_tile_on_team_with(interceptAtTile, searchingPlayer):
            startArmy = 0 - interceptAtTile.army

        threatTile = interception.threats[0].path.start.tile
        bMap = interception.threats[0].armyAnalysis.bMap

        def valueFunc(curTile: Tile, prioObj):
            (
                dist,
                euclidIntDist,
                negTileCapPoints,
                negArmy,
                fromTile
            ) = prioObj

            if curTile.player != searchingPlayer:
                return None

            if curTile.army <= 1:
                return None

            if negArmy > 0:
                return None

            recapVal = 0 - (negTileCapPoints + negArmy)

            return (
                recapVal,
                0 - negTileCapPoints,
                0 - negArmy
            )

        def prioFunc(nextTile: Tile, prioObj):
            (
                dist,
                euclidIntDist,
                negTileCapPoints,
                negArmy,
                fromTile
            ) = prioObj

            if interception.furthest_common_intercept_distances[nextTile] > threatDistFromCommon + 1:
                return None

            if nextTile.isCity and nextTile.isNeutral:
                return None

            if fromTile is not None:
                # TODO needs to switch to negative tiles, and only be supplied when in actual danger and need to intercept with OTHER tiles than the negative tiles, EG last second defense
                threatBlock = otherThreatsBlockingTiles.get(nextTile, None)
                # if threatBlock and threatBlock.amount_needed_to_block > nextTile.army:
                if threatBlock and fromTile in threatBlock.blocked_destinations:
                    return None
                    # if fromTile in threatBlock.blocked_destinations:
                distA = self.map.get_distance_between(threatTile, fromTile)
                distB = self.map.get_distance_between(threatTile, nextTile)
                if distA is None:
                    # if not DebugHelper.IS_DEBUGGING:
                    #     return None
                    raise AssertionError(f'{repr(interceptAtTile)}->{repr(fromTile)}: {distA}')
                if distB is None:
                    # if not DebugHelper.IS_DEBUGGING:
                    #     return None
                    raise AssertionError(f'{repr(interceptAtTile)}->{repr(nextTile)}: {distB}')

                # if
                if distA > distB:
                    return None

            if self.map.is_tile_on_team_with(nextTile, searchingPlayer):
                negArmy -= nextTile.army
            else:
                negArmy += nextTile.army
                negTileCapPoints += 1
                if not nextTile.isNeutral:
                    negTileCapPoints += 1

            negArmy += 1

            # newDist =
            distTuple = positionsByTurn.get(dist, None)
            if distTuple:
                approxPosX, approxPosY = distTuple
                euclidIntDist = (approxPosX - nextTile.x)**2 + (approxPosY - nextTile.y)**2
            else:
                pass

            return (
                dist + 1,
                euclidIntDist,
                negTileCapPoints,
                negArmy,
                nextTile
            )

        startTiles = {interceptAtTile: ((0, 0, 0, startArmy, interceptAtTile), 0)}
        results = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(
            self.map,
            startTiles=startTiles,
            valueFunc=valueFunc,
            maxDepth=maxDepth,
            noNeutralCities=True,
            priorityFunc=prioFunc,
            logResultValues=self.log_debug
        )

        paths = results.get(interceptAtTile, [])

        byDist = {}
        if self.log_debug:
            logbook.info(f'@{str(interceptAtTile)} depth{maxDepth} returned {len(paths)} paths.')
        for path in paths:
            revPath = path.get_reversed()
            if self.log_debug:
                logbook.info(f'  path len {revPath.length} -- {str(revPath)}')
            byDist[revPath.length] = revPath

        return byDist

    def _get_value_of_threat_blocked(self, interceptPath: Path, best_enemy_threat_info: ThreatValueInfo, turnsLeftInCycle: int) -> typing.Tuple[float, int, int, int]:
        """Returns amountBlocked, enemyArmyRemainingAtIntercept, bestCaseInterceptTurns, worstCaseInterceptTurns (if any)"""
        best_enemy_threat = best_enemy_threat_info.threat
        amountBlocked = 0
        blockable = best_enemy_threat_info.econ_value

        bestCaseInterceptTurn = 1000
        worstCaseInterceptTurn = 0

        turnsLeft = turnsLeftInCycle
        for i, tile in enumerate(interceptPath.tileList):
            if turnsLeft == 0:
                break

            turnsLeft -= 1
            if tile not in best_enemy_threat.path.tileSet:
                if self.map.is_tile_friendly(tile):
                    amountBlocked += tile.army - 1
                else:
                    amountBlocked -= tile.army + 1

            tilesAtDist = best_enemy_threat.armyAnalysis.tileDistancesLookup.get(i, None)
            if tilesAtDist:
                if tile in tilesAtDist:
                    bestCaseInterceptTurn = min(bestCaseInterceptTurn, i)
                for t in tilesAtDist:
                    if tile in t.movable:
                        bestCaseInterceptTurn = min(bestCaseInterceptTurn, i + 2)

            # worstCaseInterceptTurn =


        enArmy = int(best_enemy_threat.path.value)
        interceptDist = best_enemy_threat.armyAnalysis.bMap[interceptPath.tail.tile]
        # This assumes the intercept is moving towards the threat, pretty sure
        # interceptDist = frDist - path.length
        # interceptDist =
        enLen = best_enemy_threat.path.length

        # skip backwards until the threat is capturing tiles (eg for threats that send a 20 army through our 40 to our general, or whatever)
        node = best_enemy_threat.path.tail
        while node is not None and enArmy < 0 and enLen > interceptDist:
            if self.map.is_tile_on_team_with(node.tile, best_enemy_threat.threatPlayer):
                enArmy -= node.tile.army
            else:
                enArmy += node.tile.army

            enArmy += 1
            node = node.prev
            enLen -= 1

        initialEnArmyAtCapStartOrIntercept = enArmy
        enArmy -= amountBlocked
        enemyArmyLeftAtInterceptPointBeforeRemainingCapture = enArmy
        econValueBlocked = 0

        while node is not None and enArmy < 0 and enLen > interceptDist and turnsLeft > 0:
            if self.map.is_tile_on_team_with(node.tile, best_enemy_threat.threatPlayer):
                enArmy -= node.tile.army
            else:
                enArmy += node.tile.army
                if self.map.is_tile_friendly(node.tile):
                    if node.tile.isCity or node.tile.isGeneral:
                        # TODO model this better
                        econValueBlocked += 5
                    econValueBlocked += 2
                else:
                    econValueBlocked += 1

            enArmy += 1
            node = node.prev
            enLen -= 1
            turnsLeft -= 1

        if self.log_debug:
            logbook.info(f'blocked {econValueBlocked} econ dmg, ({amountBlocked} army), at interceptDist {interceptDist}. enemy army at intercept {initialEnArmyAtCapStartOrIntercept}, enemy army left at intercept {enemyArmyLeftAtInterceptPointBeforeRemainingCapture}: path {str(interceptPath)}')

        return econValueBlocked, enemyArmyLeftAtInterceptPointBeforeRemainingCapture, bestCaseInterceptTurn, worstCaseInterceptTurn

    def get_intercept_blocking_tiles_for_split_hinting(
            self,
            tile: Tile,
            threatsByTile: typing.Dict[Tile, typing.List[ThreatObj]]
    ) -> typing.Dict[Tile, ThreatBlockInfo]:
        """
        Returns a map from tile to the amount of army that should be left on them in order to block multiple threats.

        @param tile:
        @param threatsByTile:
        @return:
        """
        blockingTiles = {}

        for otherTile, otherThreats in threatsByTile.items():
            # blockOnMultiple = False
            # if otherTile == tile:
            #     blockOnMultiple = True
            #     # continue

            # for chokeTile in plan.common_intercept_choke_widths.keys():
            #     if not self._map.is_tile_friendly(chokeTile):
            #         continue
            #     if chokeTile.army < tile.army // 3:
            #         continue
            #
            #     blockingTiles.add(chokeTile)
            for threat in otherThreats:
                realThreatVal = threat.path.calculate_value(threat.threatPlayer, self.map._teams, doNotSaveToPath=True)
                self.ensure_threat_army_analysis(threat)
                gen = self.map.generals[self.map.player_index]
                towardsUs = self.map.get_distance_between(gen, threat.path.start.tile) - self.map.get_distance_between(gen, threat.path.tail.tile) > 0
                if not towardsUs:
                    continue

                for chokeTile in threat.path.tileList:
                    if not self.map.is_tile_friendly(chokeTile):
                        continue
                    if chokeTile.army < otherTile.army // 3:
                        continue

                    # blockAmount = threat.threatValue
                    blockAmount = realThreatVal + chokeTile.army
                    blockInfo = blockingTiles.get(chokeTile, None)
                    if blockInfo is None:
                        blockInfo = ThreatBlockInfo(chokeTile, blockAmount)
                        blockingTiles[chokeTile] = blockInfo

                    canDie = realThreatVal > 0 and threat.threatType == ThreatType.Kill

                    for moveable in chokeTile.movable:
                        # if moveable not in threat.armyAnalysis.shortestPathWay.tiles:
                        if canDie or (moveable not in threat.path.tileSet and (moveable not in threat.armyAnalysis.shortestPathWay.tiles or threat.armyAnalysis.bMap[moveable] >= threat.armyAnalysis.bMap[chokeTile])):
                            blockInfo.add_blocked_destination(moveable)

                    if blockInfo.amount_needed_to_block < blockAmount:
                        blockInfo.amount_needed_to_block = blockAmount
                        # blockingTiles[chokeTile] = blockInfo

        return blockingTiles

    def _should_delay_or_split(self, tile: Tile, interceptionPath: Path, threats: typing.List[ThreatValueInfo], turnsLeftInCycle: int) -> typing.Tuple[bool, bool]:
        """
        Returns shouldDelay, shouldSplit

        @param tile:
        @param interceptionPath:
        @param threats:
        @param turnsLeftInCycle:
        @return:
        """
        shouldSplit = False
        shouldDelay = False
        firstThreat = threats[0].threat
        isTwoAway = firstThreat.armyAnalysis.bMap[interceptionPath.start.tile] == 2
        threatArmy = firstThreat.path.start.tile.army
        if self.map.is_tile_on_team_with(firstThreat.path.start.next.tile, firstThreat.threatPlayer):
            threatArmy += firstThreat.path.start.next.tile.army - 1
        else:
            threatArmy -= firstThreat.path.start.next.tile.army + 1

        if isTwoAway:
            threatNexts = set()
            usNexts = set()
            for threatInfo in threats:
                threatNext = threatInfo.threat.path.tileList[1]
                threatNexts.add(threatNext)
                if threatNext in interceptionPath.start.tile.movable:
                    usNexts.add(threatNext)

            if len(threatNexts) > 1 and len(usNexts) > 1 and threatNexts.issubset(usNexts):
                if interceptionPath.start.tile.army // 2 - 2 < threatArmy:
                    shouldDelay = True
                else:
                    shouldSplit = True

        return shouldDelay, shouldSplit



