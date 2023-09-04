'''
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
'''
import os
import random
import typing

import BotLogging
import EarlyExpandUtils
import GatherUtils
import SearchUtils
from ArmyEngine import ArmyEngine, ArmySimResult
from CityAnalyzer import CityAnalyzer, CityScoreData
from ExpandUtils import get_optimal_expansion
from GatherAnalyzer import GatherAnalyzer
from PerformanceTimer import PerformanceTimer
from BoardAnalyzer import *
from ViewInfo import ViewInfo, PathColorer, TargetStyle
from base.client.map import Player, new_tile_matrix
from DangerAnalyzer import DangerAnalyzer, ThreatType, ThreatObj
from DataModels import get_tile_set_from_path, get_player_army_amount_on_path, get_tile_list_from_path
from Directives import *
from History import *
from Territory import *
from ArmyTracker import *

# was 30. Prevents runaway CPU usage...?
GATHER_SWITCH_POINT = 150

def scale(inValue, inBottom, inTop, outBottom, outTop):
    if inBottom > inTop:
        raise RuntimeError("inBottom > inTop")
    inValue = max(inBottom, inValue)
    inValue = min(inTop, inValue)
    numerator = (inValue - inBottom)
    divisor = (inTop - inBottom)
    if divisor == 0:
        return outTop
    valRatio = numerator / divisor
    outVal = valRatio * (outTop - outBottom) + outBottom
    return outVal


def is_gather_worthwhile(gather, parent):
    gatherWorthwhile = True
    if parent is not None:
        gatherWorthwhile = (gather.value > 0 and gather.value > parent.value / 13) or parent.fromTile is None
        #gatherWorthwhile = (gather.value > 0 and gather.value > parent.value / 20) or parent.fromTile is None
        #logging.info("{},{} <- Gather worthwhile? {} {},{}   maxGath {}  parent {}".format(parent.tile.x, parent.tile.y, gatherWorthwhile, gather.tile.x, gather.tile.y, gather.value, parent.value))
    #else:
        #logging.info("      <- No parent. True {},{}   maxGath {}".format(gather.tile.x, gather.tile.y, gather.value))
    return gatherWorthwhile


def compare_gathers(gatherA, gatherB, preferNeutrals, leaveCitiesLast = True):
    if gatherA is None:
        return gatherB
    if leaveCitiesLast:
        if gatherA.tile.isCity and not gatherB.tile.isCity:
            return gatherB
        elif gatherB.tile.isCity and not gatherA.tile.isCity:
            return gatherA
    if preferNeutrals and gatherA.neutrals < gatherB.neutrals:
        return gatherB
    elif preferNeutrals and gatherA.neutrals > gatherB.neutrals:
        return gatherA
    if gatherB.value / gatherB.gatherTurns >= gatherA.value / gatherA.gatherTurns:
        return gatherB
    return gatherA


######################### Move Making #########################
THREAD_COUNT = 6


class EklipZBot(object):
    def __init__(self, threadCount):
        self.next_scrimming_army_tile: Tile | None = None
        self.armies_moved_this_turn: typing.List[Tile] = []
        self.logDirectory: str = None
        self.perf_timer = PerformanceTimer()
        self.cities_gathered_this_cycle: typing.Set[Tile] = set()
        self.player: Player = Player(-1)
        self.targetPlayerObj: typing.Union[Player, None] = None
        self.expand_plan: EarlyExpandUtils.ExpansionPlan = None
        self.force_city_take = False
        self._gen_distances: typing.List[typing.List[int]] = []
        self.defendEconomy = False
        self.general_safe_func_set = {}
        self.threadCount = threadCount
        self.threads = []
        self.clear_moves_func: typing.Union[None, typing.Callable] = None
        self._map: MapBase = None
        self.curPath = None
        self.curPathPrio = -1
        self.gathers = 0
        self.attacks = 0
        self.leafMoves = []
        self.attackFailedTurn = 0
        self.countFailedQuickAttacks = 0
        self.countFailedHighDepthAttacks = 0
        self.largeTilesNearEnemyKings = {}
        self.enemyCities = []
        self.dangerAnalyzer: DangerAnalyzer = None
        self.cityAnalyzer: CityAnalyzer = None
        self.gatherAnalyzer: GatherAnalyzer = None
        self.lastTimingFactor = -1
        self.lastTimingTurn = 0
        self._evaluatedUndiscoveredCache = []
        self.lastTurnTime = 0

        self.allIn = False
        self.all_in_army_advantage_counter: int = 0
        self.all_in_army_advantage: bool = False
        self.giving_up_counter: int = 0
        self.all_in_counter: int = 0
        self.lastTargetAttackTurn = 0
        self.threat_kill_path: Path | None = None
        """Set this to a threat kill path for post-city-recapture-threat-interception"""

        self.generalApproximations: typing.List[typing.Tuple[float, float, int, Tile | None]] = []
        """
        List of general location approximation data as averaged by enemy tiles bordering undiscovered and euclid averaged.
        Tuple is (xAvg, yAvg, countUsed, generalTileIfKnown)
        Used for player targeting (we do the expensive approximation only for the target player?)
        This is aids.
        """

        self.allUndiscovered = []
        self.lastGeneralGatherTurn = -2
        self.targetPlayer = -1
        self.leafValueGrid = None
        self.failedUndiscoveredSearches = 0
        self.largePlayerTiles = []
        self.playerTargetScores = [0 for i in range(8)]
        self.general: Tile = None
        self.gatherNodes = None
        self.redTreeNodes = None
        self.isInitialized = False
        self.last_init_turn: int = 0
        """
        Mainly just for testing purposes, prevents the bot from performing a turn update more than once per turn, 
        which tests sometimes need to trigger ahead of time in order to check bot state ahead of a move.
        """

        self.makingUpTileDeficit = False
        self.territories: TerritoryClassifier = None

        self.target_player_gather_targets: typing.Set[Tile] = set()
        self.target_player_gather_path: Path | None = None
        self.shortest_path_to_target_player: Path | None = None
        self.shortest_path_to_target_player_distances: typing.List[typing.List[int]] = None

        self.viewInfo: ViewInfo = None

        self._minAllowableArmy = -1
        self.threat: ThreatObj | None = None
        self.pathableTiles = set()
        self.history = History()
        self.timings: Timings | None = None
        self.armyTracker: ArmyTracker = None
        self.finishingExploration = True
        self.targetPlayerExpectedGeneralLocation = None
        self.lastPlayerKilled = None
        self.launchPoints = set()
        self.explored_this_turn = False
        self.undiscovered_priorities: typing.List[typing.List[float]] = []
        self.board_analysis: BoardAnalyzer = None
        self.targetingArmy: Army | None = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f'[eklipz_bot {str(self._map)}]'

    def spawnWorkerThreads(self):
        return

    def detect_repetition(self, move, turns, numReps = 3):
        if move is None:
            return False
        curTurn = self._map.turn
        reps = 0
        for turn in range(int(curTurn - turns), curTurn):
            if turn in self.history.move_history:
                for oldMove in self.history.move_history[turn]:
                    if not turn in self.history.droppedHistory and (oldMove is not None
                            and ((oldMove.dest == move.source and oldMove.source == move.dest)
                            or (oldMove.source == move.source and oldMove.dest == move.dest))):
                        reps += 1
                        if reps == numReps:
                            logging.info("  ---    YOOOOOOOOOO detected {} repetitions on {},{} -> {},{} in the last {} turns".format(reps, move.source.x, move.source.y, move.dest.x, move.dest.y, turns))
                            return True
        return False

    def move_half_on_repetition(self, move, repetitionTurns, repCount = 3):
        if self.detect_repetition(move, repetitionTurns, repCount):
            move.move_half = True
        return move

    def find_move(self, allowRetry = True) -> Move | None:
        move: Move | None = None
        try:
            move = self.select_move(allowRetry)

        finally:
            # # this fucks performance, need to make it not slow
            # if move is not None and not self.is_move_safe_against_threats(move):
            #     self.curPath = None
            #     path: Path = None
            #     if self.threat.path.start.tile in self.armyTracker.armies:
            #         path = self.kill_army(self.armyTracker.armies[self.threat.path.start.tile], allowGeneral=False, allowWorthPathKillCheck=True)
            #         if path is not None and False:
            #             self.curPath = path
            #             self.info('overrode unsafe move with threat kill')
            #             move = Move(path.start.tile, path.start.next.tile)
            #     if path is None:
            #         self.info(f'overrode unsafe move with threat gather depth {gatherDepth} after no threat kill found')
            #         move = self.gather_to_threat_path(self.threat)

            if move is not None and self.curPath is not None and self.curPath.start.tile == move.source and self.curPath.start.next.tile != move.dest:
                logging.info("Returned a move using the tile that was curPath, but wasn't the next path move. Resetting path...")
                self.curPath = None
                self.curPathPrio = -1

            if self.armyTracker is not None:
                for tile in self._map.pathableTiles:
                    val = self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y]
                    if val != 0:
                        textVal = "e{:.0f}".format(val)
                        self.viewInfo.bottomMidRightGridText[tile.x][tile.y] = textVal

            if self._map.turn not in self.history.move_history:
                self.history.move_history[self._map.turn] = []
            self.history.move_history[self._map.turn].append(move)

            self.prep_view_info_for_render()

        return move

    def clean_up_path_before_evaluating(self):
        if self.curPath is not None and self.curPath.start.next is not None and not self.droppedMove(self.curPath.start.tile, self.curPath.start.next.tile):
            self.curPath.made_move()
            if self.curPath.length <= 0:
                logging.info("TERMINATING CURPATH BECAUSE <= 0 ???? Path better be over")
                self.curPath = None
            if self.curPath is not None:
                if self.curPath.start.next is not None and self.curPath.start.next.next is not None and self.curPath.start.next.next.next is not None and self.curPath.start.tile == self.curPath.start.next.next.tile and self.curPath.start.next.tile == self.curPath.start.next.next.next.tile:
                    logging.info("\n\n\n~~~~~~~~~~~\nDe-duped path\n~~~~~~~~~~~~~\n\n~~~\n")
                    self.curPath.made_move()
                    self.curPath.made_move()
                    self.curPath.made_move()
                    self.curPath.made_move()
                elif self.curPath.start.next is not None and self.curPath.start.tile.x == self.curPath.start.next.tile.x and self.curPath.start.tile.y == self.curPath.start.next.tile.y:
                    logging.warning("           wtf, doubled up tiles in path?????")
                    self.curPath.made_move()
                    self.curPath.made_move()
        elif self.curPath is not None:
            logging.info("         --         missed move?")

    def droppedMove(self, fromTile = None, toTile = None, movedHalf = None):
        log = True
        lastMove = None
        if (self._map.turn - 1) in self.history.move_history:
            lastMove = self.history.move_history[self._map.turn - 1][0]
        if movedHalf is None and lastMove is not None:
            movedHalf = lastMove.move_half
        elif movedHalf is None:
            movedHalf = False
        if fromTile is None or toTile is None:
            if lastMove is None:
                if log:
                    logging.info("DM: False because no last move")
                return False
            fromTile = lastMove.source
            toTile = lastMove.dest
        # easy stuff
        # if somebody else took the fromTile, then its fine.
        if fromTile.player != self.general.player:
            if log:
                logging.info("DM: False because another player captured fromTile so our move may or may not have been processed first")
            return False
        #if movedHalf:
        #    if log:
        #        logging.info("DM: False (may be wrong) because not bothering to calculate when movedHalf=True")
        #    return False
        # if army on from is what we expect
        expectedFrom = 1
        expectedToDeltaOnMiss = 0
        if self._map.is_army_bonus_turn:
            expectedFrom += 1
            if toTile.player != -1:
                expectedToDeltaOnMiss += 1
        if (fromTile.isCity or fromTile.isGeneral) and self._map.is_city_bonus_turn:
            expectedFrom += 1
        if ((toTile.isCity and toTile.player != -1) or toTile.isGeneral) and self._map.is_city_bonus_turn:
            expectedToDeltaOnMiss += 1
        dropped = True
        if not movedHalf:
            if fromTile.army <= expectedFrom:
                if log:
                    logging.info("DM: False because fromTile.army {} <= expectedFrom {}".format(fromTile.army, expectedFrom))
                dropped = False
            else:
                if log:
                    logging.info("DM: True because fromTile.army {} <= expectedFrom {}".format(fromTile.army, expectedFrom))
                dropped = True
        else:
            if abs(toTile.delta.armyDelta) != expectedToDeltaOnMiss:
                if log:
                    logging.info("DM: False because movedHalf and toTile delta {} != expectedToDeltaOnMiss {}".format(abs(toTile.delta.armyDelta), expectedToDeltaOnMiss))
                dropped = False
            else:
                if log:
                    logging.info("DM: True because movedHalf and toTile delta {} == expectedToDeltaOnMiss {}".format(abs(toTile.delta.armyDelta), expectedToDeltaOnMiss))
                dropped = True
        if dropped:
            self.history.droppedHistory[self._map.turn - 1] = True
        return dropped

    def handle_city_found(self, tile):
        logging.info("EH: City found handler! City {}".format(tile.toString()))
        self.territories.needToUpdateAroundTiles.add(tile)
        if tile.player != -1:
            self.board_analysis.should_rescan = True
        return None

    def handle_tile_captures(self, tile):
        logging.info("EH: Tile captured! Tile {}, oldOwner {} newOwner {}".format(tile.toString(), tile.delta.oldOwner, tile.delta.newOwner))
        self.territories.needToUpdateAroundTiles.add(tile)
        if tile.isCity and tile.delta.oldOwner == -1:
            self.board_analysis.should_rescan = True
        return None

    def handle_player_captures(self, capturee, capturer):
        logging.info("EH: Player captured! caputered {} ({}) capturer {} ({})".format(self._map.usernames[capturee], capturee, self._map.usernames[capturer], capturer))
        for army in list(self.armyTracker.armies.values()):
            if army.player == capturee:
                logging.info("EH:   scrapping dead players army {}".format(army.toString()))
                self.armyTracker.scrap_army(army)

        self.history.captured_player(self._map.turn, capturee, capturer)

        if capturer == self.general.player:
            logging.info("setting lastPlayerKilled to {}".format(capturee))
            self.lastPlayerKilled = capturee
            playerGen = self._map.players[capturee].general
            self.launchPoints.add(playerGen)
        return None

    def handle_tile_deltas(self, tile):
        logging.info("EH: Tile delta handler! Tile {} delta {}".format(tile.toString(), tile.delta.armyDelta))
        return None

    def handle_tile_discovered(self, tile):
        logging.info("EH: Tile discovered handler! Tile {}".format(tile.toString()))
        self.territories.needToUpdateAroundTiles.add(tile)
        if tile.isCity and tile.player != -1:
            self.board_analysis.should_rescan = True

        if tile.player >= 0:
            player = self._map.players[tile.player]
            if len(player.tiles) < 4 and tile.player == self.targetPlayer and self.curPath:
                self.viewInfo.addAdditionalInfoLine("killing current path because JUST discovered player...")
                self.curPath = None

        return None

    def handle_tile_revealed(self, tile):
        logging.info("EH: Tile revealed handler! Tile {}".format(tile.toString()))
        self.territories.needToUpdateAroundTiles.add(tile)
        self.territories.revealed_tile(tile)
        if tile.player == -1:
            self.armyTracker.tile_discovered_neutral(tile)
        return None

    def handle_army_moved(self, tile: Tile):
        logging.info("EH: Army Moved handler! Tile {}".format(tile.toString()))
        self.armies_moved_this_turn.append(tile)
        self.territories.needToUpdateAroundTiles.add(tile)
        self.territories.revealed_tile(tile)
        return None

    def handle_army_emerged(self, army):
        logging.info("EH: Army emerged handler! Army {}".format(army.toString()))
        self.territories.needToUpdateAroundTiles.add(army.tile)
        self.territories.revealed_tile(army.tile)
        return None

    def get_elapsed(self):
        return round(time.perf_counter() - self.lastTurnTime, 3)

    def init_turn(self, secondAttempt = False):
        if self.last_init_turn == self._map.turn:
            return

        self.last_init_turn = self._map.turn

        if not secondAttempt:
            self.explored_this_turn = False

        self.threat_kill_path = None

        timeSinceLastUpdate = 0
        self.redTreeNodes = None
        now = time.perf_counter()
        if self.lastTurnTime != 0:
            timeSinceLastUpdate = now - self.lastTurnTime

        self.lastTurnTime = now
        logging.info("\n       ~~~\n       Turn {}   ({:.3f})\n       ~~~\n".format(self._map.turn, timeSinceLastUpdate))
        if self.general is not None:
            self._gen_distances = build_distance_map(self._map, [self.general])

        if not self.isInitialized and self._map is not None:
            self.initialize_map_for_first_time(self._map)

        self._minAllowableArmy = -1
        self.enemyCities = []
        if self._map.turn - 3 > self.lastTimingTurn:
            self.lastTimingFactor = -1

        lastMove = None

        if self._map.turn - 1 in self.history.move_history:
            lastMove = self.history.move_history[self._map.turn - 1][0]

        with self.perf_timer.begin_move_event('Army Tracker Scan'):
            self.armies_moved_this_turn = []
            # the callback on armies moved will fill the list above back up during armyTracker.scan
            self.armyTracker.scan(lastMove, self._map.turn)

        if self._map.turn == 3 or self.board_analysis.should_rescan:
            # I think reachable tiles isn't built till turn 2? so chokes aren't built properly turn 1
            with self.perf_timer.begin_move_event('Choke re-scan'):
                self.board_analysis.rescan_chokes()

        if self.territories.should_recalculate(self._map.turn):
            with self.perf_timer.begin_move_event('Territory Scan'):
                self.territories.scan()

        for path in self.armyTracker.fogPaths:
            self.viewInfo.color_path(PathColorer(path, 255, 84, 0, 255, 30, 150))



    def get_timings(self):
        with self.perf_timer.begin_move_event('GatherAnalyzer scan'):
            self.gatherAnalyzer.scan()

        countOnPath = 0
        if self.target_player_gather_targets is not None:
            countOnPath = count(self.target_player_gather_targets, lambda tile: tile.player == self.general.player)
        randomVal = random.randint(-2, 3)
        # what size cycle to use, normally the 50 turn cycle
        cycleDuration = 50

        # at what point in the cycle to gatherSplit from gather to utility moves. TODO dynamically determine this based on available utility moves?
        gatherSplit = 0

        # offset so that this timing doesn't always sync up with every 100 moves, instead could sync up with 250, 350 instead of 300, 400 etc.
        # for cycle 50 this is always 0
        realDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation)
        longSpawns = self.target_player_gather_path is not None and realDist > 22
        genPlayer = self._map.players[self.general.player]
        targPlayer = None
        if self.targetPlayer != -1:
            targPlayer = self._map.players[self.targetPlayer]
        # hack removed longspawns, this doesn't actually help?
        if False and longSpawns and genPlayer.tileCount > 80:
            # LONG SPAWNS
            if self.is_all_in():
                if genPlayer.tileCount > 80:
                    cycleDuration = 100
                    gatherSplit = 70
                else:
                    gatherSplit = min(40, genPlayer.tileCount - 10)
            elif genPlayer.tileCount > 120:
                cycleDuration = 100
                gatherSplit = 60
            elif genPlayer.tileCount > 100:
                cycleDuration = 100
                gatherSplit = 55
        else:
            if self.is_all_in():
                if genPlayer.tileCount > 95:
                    cycleDuration = 100
                    gatherSplit = 76
                else:
                    cycleDuration = 50
                    gatherSplit = 35
            elif genPlayer.tileCount - countOnPath > 140 or realDist > 35:
                cycleDuration = 100
                gatherSplit = 65
            elif genPlayer.tileCount - countOnPath > 120 or realDist > 29:
                # cycleDuration = 100
                # gatherSplit = 65
                gatherSplit = 27
            elif genPlayer.tileCount - countOnPath > 100:
                # slightly longer gatherSplit
                gatherSplit = 26
            elif genPlayer.tileCount - countOnPath > 85:
                # slightly longer gatherSplit
                gatherSplit = 25
            elif genPlayer.tileCount - countOnPath > 65:
                # slightly longer gatherSplit
                gatherSplit = 23
            elif genPlayer.tileCount - countOnPath > 45:
                # slightly longer gatherSplit
                gatherSplit = 21
            elif genPlayer.tileCount - countOnPath > 30:
                # slightly longer gatherSplit
                gatherSplit = 18
            elif genPlayer.tileCount - countOnPath > 21:
                # slightly longer gatherSplit
                gatherSplit = 16
            else:
                gatherSplit = genPlayer.tileCount - countOnPath
                randomVal = 0

            gatherSplit = min(gatherSplit, genPlayer.tileCount - countOnPath)

        if self._map.turn < 100:
            cycleDuration = 50
            gatherSplit = 25

        gatherSplit = min(gatherSplit, genPlayer.tileCount - countOnPath)

        if self.targetPlayer == -1 and self._map.remainingPlayers == 2:
            gatherSplit += 3
        gatherSplit += randomVal

        quickExpandSplit = 0
        if self._map.turn > 50:
            if self.targetPlayer != -1:
                maxAllowed = 5
                winningBasedMin = int(targPlayer.tileCount - genPlayer.tileCount + genPlayer.tileCount / 8)
                quickExpandSplit = min(maxAllowed, max(0, winningBasedMin))
                logging.info(f"quickExpandSplit: {quickExpandSplit}")

        if self.defendEconomy:
            gatherSplit += 4
            quickExpandSplit = 0

        disallowEnemyGather = False

        offset = self._map.turn % cycleDuration
        if offset % 50 != 0:
            self.viewInfo.addAdditionalInfoLine(f"offset being reset to 0 from {offset}")
            # When this gets set on random turns, if we don't set it to 0 it will always keep recycling on that offkilter turn.
            offset = 0

        # if the gather path is real long, then we need to launch the attack a bit earlier.
        if self.target_player_gather_path is not None and self.target_player_gather_path.length > 20:
            diff = self.target_player_gather_path.length - 23
            logging.info(f'the gather path is really long ({self.target_player_gather_path.length}), then we need to launch the attack a bit earlier. Switching from {gatherSplit} to {gatherSplit - diff}')
            gatherSplit -= diff
        #
        # if self.force_city_take:
        #     quickExpandSplit = 0

        # gatherSplit += quickExpandSplit

        # launchTiming should be cycleTurns - expected travel time to enemy territory - expected time spent in enemy territory
        # pathValueWeight = 10
        pathValueWeight = 0
        pathLength = 8
        if self.target_player_gather_path is not None:
            subsegment: Path = self.target_player_gather_path.get_subsegment(int(self.target_player_gather_path.length // 2))
            subsegment.calculate_value(self.general.player)
            pathValueWeight = max(pathValueWeight, int(max(1, subsegment.value) ** 0.75))
            pathLength = max(pathLength, self.target_player_gather_path.length)

        launchTiming = cycleDuration - pathValueWeight - pathLength - 10
        if launchTiming < gatherSplit:
            self.viewInfo.addAdditionalInfoLine(f'launchTiming was {launchTiming} (pathValueWeight {pathValueWeight}), targetLen {pathLength}, adjusting to be same as gatherSplit {gatherSplit}')
            launchTiming = gatherSplit
        else:
            self.viewInfo.addAdditionalInfoLine(f'launchTiming {launchTiming} (pathValueWeight {pathValueWeight}), targetLen {pathLength}')

        # should usually be 0 except the first turn
        correction = self._map.turn % 50
        timings = Timings(cycleDuration, quickExpandSplit, gatherSplit, launchTiming, offset, self._map.turn + cycleDuration - correction, disallowEnemyGather)

        logging.info("Recalculated timings. longSpawns {}, Timings {}".format(longSpawns, timings.toString()))
        return timings

    def timing_expand(self):
        turnOffset = self._map.turn + self.timings.offsetTurns
        turnCycleOffset = turnOffset % self.timings.cycleTurns
        if turnCycleOffset >= self.timings.splitTurns:
            return None
        return None

    def timing_gather(
            self,
            startTiles: typing.List[Tile],
            negativeTiles: typing.Set[Tile] | None = None,
            skipTiles: typing.Set[Tile] | None = None,
            force = False,
            priorityTiles: typing.Set[Tile] | None = None,
            targetTurns = -1,
            includeTreeNodesThatGatherNegative=True
    ) -> typing.Union[Move, None]:
        turnOffset = self._map.turn + self.timings.offsetTurns
        turnCycleOffset = turnOffset % self.timings.cycleTurns
        if force or (self._map.turn >= 50 and turnCycleOffset < self.timings.splitTurns and startTiles is not None and len(startTiles) > 0):
            self.finishingExploration = False
            if targetTurns != -1:
                depth = targetTurns
            else:
                depth = self.timings.splitTurns - turnCycleOffset
                if not self.defendEconomy:
                    if force:
                        self.viewInfo.addAdditionalInfoLine(f"Forced gather timing window, resulting depth {depth}")
                    else:
                        self.viewInfo.addAdditionalInfoLine("Inside gather timing window, resulting depth {depth}")
                elif self.defendEconomy:
                    ogDepth = depth
                    depth = 16 - self._map.turn % 15
                    if self.targetPlayerObj.tileCount > 45:
                        depth = 21 - self._map.turn % 20
                    if self.targetPlayerObj.tileCount > 90:
                        depth = 26 - self._map.turn % 25
                    if self.targetPlayerObj.tileCount > 130:
                        depth = 51 - self._map.turn % 50
                    self.viewInfo.addAdditionalInfoLine(f'Due to economy defense, gather depth changed from {ogDepth} to {depth}')

            if depth <= 0:
                depth += self.timings.cycleTurns

            if depth > GATHER_SWITCH_POINT:
                with self.perf_timer.begin_move_event(f"USING OLD MST GATH depth {depth}"):
                    treeNodes = self.build_mst(startTiles, 1.0, depth - 1, negativeTiles)
                    # self.redTreeNodes = [node.deep_clone() for node in treeNodes]
                    treeNodes = GatherUtils.prune_mst_to_turns(treeNodes, depth - 1, self.general.player, self.viewInfo)
                gatherMove = self.get_tree_move_default(treeNodes)
                if gatherMove is not None:
                    self.viewInfo.addAdditionalInfoLine(
                        f"OLD LEAF MST GATHER MOVE! {gatherMove.source.x},{gatherMove.source.y} -> {gatherMove.dest.x},{gatherMove.dest.y}  leafGatherDepth: {depth}")
                    self.gatherNodes = treeNodes
                    return self.move_half_on_repetition(gatherMove, 6)
            else:
                skipFunc = None
                if self._map.remainingPlayers > 2:
                    # avoid gathering to undiscovered tiles when there are third parties on the map
                    skipFunc = lambda tile, tilePriorityObject: not tile.discovered

                enemyDistanceMap = self.board_analysis.intergeneral_analysis.bMap
                value, gatherNodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
                    self._map,
                    startTiles,
                    depth,
                    negativeTiles = negativeTiles,
                    searchingPlayer = self.general.player,
                    skipFunc = skipFunc,
                    viewInfo = self.viewInfo,
                    skipTiles = skipTiles,
                    distPriorityMap = enemyDistanceMap,
                    priorityTiles = priorityTiles,
                    includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative,
                    incrementBackward=False)
                self.gatherNodes = gatherNodes
                move = self.get_tree_move_default(self.gatherNodes)
                if move is not None:
                    return self.move_half_on_repetition(move, 6, 4)
                else:
                    logging.info("NO MOVE WAS RETURNED FOR timing_gather?????????????????????")
        else:
            self.finishingExploration = True
            self.viewInfo.addAdditionalInfoLine("finishExp=True in timing_gather because outside cycle...?")
            logging.info("No timing move because outside gather timing window. Timings: {}".format(self.timings.toString()))
        return None


    def make_first_25_move(self):
        calcedThisTurn = False
        distSource = [self.general]
        if self.targetPlayerExpectedGeneralLocation is not None:
            distSource = [self.targetPlayerExpectedGeneralLocation]
        distMap = build_distance_map(self._map, distSource)

        if self.expand_plan is None or len(self.expand_plan.plan_paths) == 0:
            with self.perf_timer.begin_move_event('optimize_first_25'):
                calcedThisTurn = True
                self.expand_plan = EarlyExpandUtils.optimize_first_25(self._map, self.general, distMap)
                while len(self.expand_plan.plan_paths) > 0 and self.expand_plan.plan_paths[0] is None:
                    self.expand_plan.plan_paths.pop(0)

        r = 255
        for plan in self.expand_plan.plan_paths:
            r -= 25

            if plan is None:
                continue

            self.viewInfo.color_path(PathColorer(plan.clone(), r, 50, 50, alpha=r, alphaDecreaseRate=5, alphaMinimum=100))

        if self.expand_plan.launch_turn > self._map.turn:
            self.info(f"Expand plan ({self.expand_plan.tile_captures}) isn't ready to launch yet, launch turn {self.expand_plan.launch_turn}")
            return None

        if not calcedThisTurn and not any(self.player.tiles, lambda tile: not tile.isGeneral and tile.army > 1):
            self.expand_plan.tile_captures = EarlyExpandUtils.get_start_expand_value(self._map, self.general, self.general.army, self._map.turn, self.expand_plan.plan_paths, noLog=False)

        if len(self.expand_plan.plan_paths) > 0:
            countNone = 0
            for p in self.expand_plan.plan_paths:
                if p is not None:
                    break
                countNone += 1

            curPath = self.expand_plan.plan_paths[0]
            if curPath is None:
                self.info(f'Expand plan {self.expand_plan.tile_captures} no-opped until turn {countNone + self._map.turn} :)')
                self.expand_plan.plan_paths.pop(0)
                return None

            move = self.get_first_path_move(curPath)
            self.info(f'Expand plan {self.expand_plan.tile_captures} path move {str(move)}')

            collidedWithEnemyAndWastingArmy = move.source.player != move.dest.player and move.dest.player != -1 and move.source.army - 1 <= move.dest.army

            if collidedWithEnemyAndWastingArmy:
                # if tiles > 2 we either prevent them from continuing their expand OR we cap the tile they just vacate, depending who loses the tiebreak
                collisionCapsOrPreventsEnemy = move.source.army == move.dest.army and move.source.army > 2
                if not collisionCapsOrPreventsEnemy:
                    newPath = self.attempt_first_25_collision_reroute(curPath, move, distMap)
                    if newPath is None:
                        self.info(f'F25 Expansion collided at {str(move.dest.tile)}, no alternative found. No-opping')
                        curPath.made_move()
                        if curPath.length == 0:
                            self.expand_plan.plan_paths.pop(0)
                        return None

                    self.viewInfo.addAdditionalInfoLine(
                        f'F25 Expansion collided at {str(move.dest.tile)}, capping {str(newPath)} instead.')
                    move = self.get_first_path_move(newPath)
                    curPath = newPath
                else:
                    self.info(f'F25 Expansion collided at {str(move.dest.tile)}, continuing because collisionCapsOrPreventsEnemy.')

            curPath.made_move()
            if curPath.length == 0:
                self.expand_plan.plan_paths.pop(0)

            return move

        self.viewInfo.addAdditionalInfoLine('wtf, explan plan was empty but we''re in first 25 still..?')

        # TODO should be able to build the whole plan above in an MST prune, no...?

        nonGeneralArmyTiles = [tile for tile in filter(lambda tile: tile != self.general and tile.army > 1, self._map.players[self.general.player].tiles)]

        negativeTiles = set()

        if len(nonGeneralArmyTiles) > 0:
            negativeTiles.add(self.general)

        path = self.get_optimal_exploration(50 - self._map.turn, negativeTiles=negativeTiles)
        #is1v1 = self._map.remainingPlayers == 2
        #gatherNodes = self.build_mst([self.general])
        #self.gatherNodes = gatherNodes

        if (self._map.turn < 46
                and self.general.army < 3
                and len(nonGeneralArmyTiles) == 0
                and count(self.general.movable, lambda tile: not tile.isMountain and tile.player == -1) > 0):
            self.info("Skipping move because general.army < 3 and all army on general and self._map.turn < 46")
            # dont send 2 army except right before the bonus, making perfect first 25 much more likely
            return None
        move = None
        if path:
            self.info("Dont make me expand. You don't want to see me when I'm expanding.")
            move = self.get_first_path_move(path)
        return move


    def select_move(self, allowRetry = True):
        origPathLength = 20
        start = time.perf_counter()
        self.init_turn(secondAttempt = not allowRetry)
        if allowRetry:
            self.viewInfo.turnInc()

        if self.timings and self.timings.get_turn_in_cycle(self._map.turn) == 0:
            self.timing_cycle_ended()

        if self.timings is None or self.timings.should_recalculate(self._map.turn):
            with self.perf_timer.begin_move_event('Recalculating Timings...'):
                self.timings = self.get_timings()

        if self.determine_should_winning_all_in():
            wasAllIn = self.all_in_army_advantage
            self.all_in_army_advantage = True
            if not wasAllIn:
                self.viewInfo.addAdditionalInfoLine("GOING ALL IN TEMPORARILY ON ARMY ADVANTAGE, CLEARING STUFF")
                self.curPath = None
                self.timings = self.get_timings()
                if self.targetPlayerObj.general is not None and not self.targetPlayerObj.general.visible:
                    self.targetPlayerObj.general.army = 3
                    self.clear_fog_armies_around(self.targetPlayerObj.general)
                self.recalculate_player_paths(force=True)
            self.all_in_army_advantage_counter += 1
        else:
            self.all_in_army_advantage = False
            self.all_in_army_advantage_counter = 0

        # This is the attempt to resolve the 'dropped packets devolve into unresponsive bot making random moves
        # even though it thinks it is making sane moves' issue. If we seem to have dropped a move, clear moves on
        # the server before sending more moves to prevent moves from backing up and getting executed later.
        if self._map.turn - 1 in self.history.move_history:
            if self.droppedMove():
                logging.info("\n\n\n^^^^^^^^^VVVVVVVVVVVVVVVVV^^^^^^^^^^^^^VVVVVVVVV^^^^^^^^^^^^^\nD R O P P E D   M O V E ? ? ? ? (Dropped move)... Sending clear_moves...\n^^^^^^^^^VVVVVVVVVVVVVVVVV^^^^^^^^^^^^^VVVVVVVVV^^^^^^^^^^^^^")
                if self.clear_moves_func:
                    with self.perf_timer.begin_move_event('Sending clear_moves due to dropped move'):
                        self.clear_moves_func()
        #if (self.turnsTillDeath > 0):
        #    self.turnsTillDeath -= 1
            #logging.info("\n\n---------TURNS TILL DEATH AT MOVE START {}\n".format(self.turnsTillDeath))
        if self._map.turn <= 1:
            # bypass divide by 0 error instead of fixing it
            return None

        with self.perf_timer.begin_move_event('scan_map()'):
            self.scan_map()

        if self._map.remainingPlayers == 1:
            return None

        self.recalculate_player_paths()

        self.prune_timing_split_if_necessary()

        with self.perf_timer.begin_move_event('calculating general danger / threats'):
            self.calculate_general_danger()

        quickKillMove = self.check_for_1_move_kills()
        if quickKillMove is not None:
            return quickKillMove

        if self._map.turn < 50:
            return self.make_first_25_move()

        self.clean_up_path_before_evaluating()

        if self.curPathPrio >= 0:
            logging.info("curPathPrio: " + str(self.curPathPrio))

        threat = None
        visionThreat = None
        if not self.giving_up_counter > 30:
            if self.dangerAnalyzer.fastestVisionThreat is not None:
                threat = self.dangerAnalyzer.fastestVisionThreat
                visionThreat = threat

            if self.dangerAnalyzer.fastestThreat is not None:
                threat = self.dangerAnalyzer.fastestThreat

        #  # # # #   ENEMY KING KILLS
        with self.perf_timer.begin_move_event('Checking for king kills and races'):
            (killMove, kingKillPath, canRace) = self.check_for_king_kills_and_races(threat)
            if killMove is not None:
                return killMove

        self.threat = threat
        if threat is not None and threat.saveTile is not None:
            self.viewInfo.lastEvaluatedGrid[threat.saveTile.x][threat.saveTile.y] = 200

        enemyNearGen = self.sum_enemy_army_near_tile(self.general)
        genArmyWeighted = self.general.army - enemyNearGen
        genLowArmy = self.general_min_army_allowable() / 2 > genArmyWeighted and self._map.remainingPlayers <= 3
        if genLowArmy:
            logging.info("gen low army")

        if self.allIn:
            logging.info("~~~ ___ {}\n   YO WE ALL IN DAWG\n~~~ ___".format(self.get_elapsed()))

        defenseCriticalTileSet = set()
        #if not self.isAllIn() and (threat.turns > -1 and self.dangerAnalyzer.anyThreat):
        #    armyAmount = (self.general_min_army_allowable() + enemyNearGen) * 1.1 if threat is None else threat.threatValue + general.army + 1

        defenseSavePath: Path = None
        if threat is not None and not self.allIn and (threat.turns > -1 and threat.threatType == ThreatType.Kill):
            # if threat.turns > 3:
            #     logging.info('trying scrim as defense...?')
            #

            with self.perf_timer.begin_move_event(f'THREAT DEFENSE {threat.turns} {str(threat.path.start.tile)}'):
                defenseMove, defenseSavePath = self.get_defense_moves(threat, defenseCriticalTileSet, kingKillPath)
                if defenseSavePath is not None:
                    self.viewInfo.color_path(PathColorer(defenseSavePath, 255, 100, 255, 200))
                if defenseMove is not None:
                    return defenseMove

        if kingKillPath is not None:
            if defenseSavePath is None or defenseSavePath.start.tile != kingKillPath.start.tile:
                if defenseSavePath is not None:
                    logging.info("savePath was {}".format(defenseSavePath.toString()))
                else:
                    logging.info("savePath was NONE")
                self.info("    Delayed defense kingKillPath. canRace {}  {}".format(canRace, kingKillPath.toString()))
                self.viewInfo.color_path(PathColorer(kingKillPath, 158, 158, 158, 255, 10, 200))

                return Move(kingKillPath.start.tile, kingKillPath.start.next.tile)
            else:
                if defenseSavePath is not None:
                    logging.info("savePath was {}".format(defenseSavePath.toString()))
                else:
                    logging.info("savePath was NONE")
                logging.info("savePath tile was also kingKillPath tile, skipped kingKillPath {}".format(kingKillPath.toString()))

        with self.perf_timer.begin_move_event('ARMY SCRIMS'):
            armyScrimMove = self.check_for_army_movement_scrims()
            if armyScrimMove is not None:
                #already logged
                return armyScrimMove

        dangerTiles = self.get_danger_tiles()
        if len(dangerTiles) > 0 and not self.all_in_counter > 15:
            logging.info("trying to kill danger tiles ({:.3f} in)".format(time.perf_counter() - start))
            for tile in dangerTiles:
                self.viewInfo.add_targeted_tile(tile, TargetStyle.RED)
                negTiles = []
                if self.curPath is not None:
                    negTiles = [tile for tile in self.curPath.tileSet]
                armyToSearch = self.get_target_army_inc_adjacent_enemy(tile)
                killPath = dest_breadth_first_target(self._map, [tile], armyToSearch, 0.1, 6, negTiles, searchingPlayer = self.general.player, dontEvacCities=False)
                if killPath is not None:
                    self.info("found depth {} dest bfs kill on danger tile {},{} \n{}".format(killPath.length, tile.x, tile.y, killPath.toString()))
                    return self.get_first_path_move(killPath)
                    # self.curPath = killPath

        gatherTargets = self.target_player_gather_path.tileList
        paths: typing.List[Path] = []
        if not self.is_all_in():
            with self.perf_timer.begin_move_event('City Analyzer'):
                self.cityAnalyzer.re_scan(self.board_analysis)

            with self.perf_timer.begin_move_event('city_quick_kill'):
                path = self.get_quick_kill_on_enemy_cities(defenseCriticalTileSet)
            if path is not None:
                paths.append(path)
        if len(paths) > 0:
            path = list(sorted(paths, key=lambda p: p.length, reverse=False))[0]
            self.info(f'Quick Kill on enemy city: {str(path)}')
            self.curPath = path
            return self.get_first_path_move(path)

        numTilesAdjKing = count(self.general.adjacents, lambda tile: tile.player >= 0 and tile.player != self.general.player and tile.army > 2)
        if numTilesAdjKing == 1:
            visionTiles = filter(lambda tile: tile.player >= 0 and tile.player != self.general.player and tile.army > 2, self.general.adjacents)
            for annoyingTile in visionTiles:
                playerTilesAdjEnemyVision = [x for x in filter(lambda threatAdjTile: threatAdjTile.player == self.general.player and threatAdjTile.army > annoyingTile.army // 2 and threatAdjTile.army > 1, annoyingTile.movable)]
                if len(playerTilesAdjEnemyVision) > 0:
                    largestAdjTile = max(playerTilesAdjEnemyVision, key=lambda myTile: myTile.army)
                    if largestAdjTile and (not largestAdjTile.isGeneral or largestAdjTile.army + 1 > annoyingTile.army):
                        self.info('Nuking general-adjacent vision tile.')
                        return Move(largestAdjTile, annoyingTile)

        if self.targetingArmy and not self.targetingArmy.scrapped and self.targetingArmy.tile.army > 2:
            logging.info("************\n  Turn {} Continue Army Kill({:.3f} in)".format(self._map.turn, time.perf_counter() - start))
            armyTargetMove = self.continue_killing_target_army()
            if armyTargetMove:
                # already logged internally
                return armyTargetMove
        else:
            self.targetingArmy = None

        afkPlayerMove = self.get_move_if_afk_player_situation()
        if afkPlayerMove:
            return afkPlayerMove

        # if ahead on economy, but not %30 ahead on army we should play defensively
        self.defendEconomy = self.should_defend_economy()

        if len(paths) == 0:
            with self.perf_timer.begin_move_event(f'capture_cities'):
                (cityPath, gatherMove) = self.capture_cities(defenseCriticalTileSet)
            if cityPath is not None:
                logging.info("{} returning capture_cities cityPath {}".format(self.get_elapsed(), cityPath.toString()))
                paths.append(cityPath)
                self.curPath = cityPath
            elif gatherMove is not None:
                logging.info("{} returning capture_cities gatherMove {}".format(self.get_elapsed(), gatherMove.toString()))
                return gatherMove

        if self.threat_kill_path is not None:
            self.info(f"we're pretty safe from threat via gather, trying to kill threat instead.")
            # self.curPath = path
            self.targetingArmy = self.get_army_at(self.threat.path.start.tile)
            move = self.get_first_path_move(self.threat_kill_path)
            if not self.detect_repetition(move, 4, numReps=3):
                return move
            if self.detect_repetition(move, 4, numReps=2):
                move.move_half = True
                return move

        if self._map.turn >= 50 and self._map.turn < 75:
            move = self.try_gather_tendrils_towards_enemy()

        threatDefenseLength = 2 * self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3 + 1
        if self.targetPlayerExpectedGeneralLocation.isGeneral:
            threatDefenseLength = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 2 + 2
        if (len(paths) == 0 and threat is not None and threat.threatType == ThreatType.Kill
                    and threat.path.length < threatDefenseLength
                    and not self.is_all_in()
                    and self._map.remainingPlayers < 4 and threat.threatPlayer == self.targetPlayer):
            logging.info("*\\*\\*\\*\\*\\*\n  Kill (non-vision) threat??? ({:.3f} in)".format(time.perf_counter() - start))
            threatKill = self.kill_threat(threat)
            if threatKill and self.worth_path_kill(threatKill, threat.path, threat.armyAnalysis):
                self.targetingArmy = self.get_army_at(threat.path.start.tile)
                saveTile = threatKill.start.tile
                nextTile = threatKill.start.next.tile
                move = Move(saveTile, nextTile)
                if not self.detect_repetition(move, 6, 3):
                    self.viewInfo.color_path(PathColorer(threatKill, 0, 255, 204, 255, 10, 200))
                    move.move_half = self.should_kill_path_move_half(threatKill)
                    self.info("Threat kill. half {}, {}".format(move.move_half, threatKill.toString()))
                    return move

        if (len(paths) == 0 and threat is not None and threat.threatType == ThreatType.Vision
                    and not self.is_all_in()
                    and threat.path.start.tile.visible
                    and self.should_kill(threat.path.start.tile)
                    and self.just_moved(threat.path.start.tile)
                    and threat.path.length < min(10, self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 2 + 1)
                    and self._map.remainingPlayers < 4 and threat.threatPlayer == self.targetPlayer):
            logging.info("*\\*\\*\\*\\*\\*\n  Kill vision threat. ({:.3f} in)".format(time.perf_counter() - start))
            # Just kill threat then, nothing crazy
            path = self.kill_enemy_path(threat.path, allowGeneral = True)

            visionKillDistance = 5
            if path is not None and self.worth_path_kill(path, threat.path, threat.armyAnalysis, visionKillDistance):
                self.targetingArmy = self.get_army_at(threat.path.start.tile)
                self.info("Killing vision threat {} with path {}".format(threat.path.start.tile.toString(), path.toString()))
                self.viewInfo.color_path(PathColorer(path, 0, 156, 124, 255, 10, 200))
                move = self.get_first_path_move(path)
                move.move_half = self.should_kill_path_move_half(path)
                return move
            elif threat.path.start.tile == self.targetingArmy:
                logging.info("threat.path.start.tile == self.targetingArmy and not worth_path_kill. Setting targetingArmy to None")
                self.targetingArmy = None
            elif path is None:
                logging.info("No vision threat kill path?")

        # if losing on economy, finishing exp false
        genPlayer = self._map.players[self.general.player]
        largeTileThresh = 15 * genPlayer.standingArmy / genPlayer.tileCount
        haveLargeTilesStill = len(where(genPlayer.tiles, lambda tile: tile.army > largeTileThresh)) > 0
        logging.info("Will stop finishingExploration if we don't have tiles larger than {:.1f}. Have larger tiles? {}".format(largeTileThresh, haveLargeTilesStill))
        if not self.winning_on_economy(cityValue = 0) and not haveLargeTilesStill:
            self.finishingExploration = False

        demolishingTargetPlayer = (self.winning_on_army(1.5, useFullArmy = False, againstPlayer= self.targetPlayer)
                                   and self.winning_on_economy(1.5, cityValue = 10, againstPlayer= self.targetPlayer))

        allInAndKnowsGenPosition = (self.all_in_army_advantage or self.all_in_counter > self.targetPlayerObj.tileCount // 3) and self.targetPlayerExpectedGeneralLocation.isGeneral
        targetPlayer = self._map.players[self.targetPlayer]
        stillDontKnowAboutEnemyCityPosition = len(targetPlayer.cities) + 1 < targetPlayer.cityCount
        stillHaveSomethingToSearchFor = ((self.is_all_in() or self.finishingExploration or demolishingTargetPlayer)
                                   and (not self.targetPlayerExpectedGeneralLocation.isGeneral or stillDontKnowAboutEnemyCityPosition))

        logging.info(
            f"stillDontKnowAboutEnemyCityPosition: {stillDontKnowAboutEnemyCityPosition}, allInAndKnowsGenPosition: {allInAndKnowsGenPosition}, stillHaveSomethingToSearchFor: {stillHaveSomethingToSearchFor}")
        if not allInAndKnowsGenPosition and stillHaveSomethingToSearchFor:
            self.viewInfo.addAdditionalInfoLine(
                f"exp: unknownEnCity: {stillDontKnowAboutEnemyCityPosition}, allInAgainstGen: {allInAndKnowsGenPosition}, stillSearch: {stillHaveSomethingToSearchFor}")
            with self.perf_timer.begin_move_event('Attempting to finish/continue exploration'):
                undiscNeg = defenseCriticalTileSet.copy()
                for city in self._map.players[self.general.player].cities:
                    undiscNeg.add(city)
                halfTargetPath = self.target_player_gather_path.get_subsegment(self.target_player_gather_path.length // 2)
                undiscNeg.add(self.general)
                for tile in halfTargetPath.tileList:
                    undiscNeg.add(tile)
                path = self.explore_target_player_undiscovered(undiscNeg)
                if path is not None:
                    self.viewInfo.color_path(PathColorer(path, 120, 150, 127, 200, 12, 100))
                    valueSubsegment = self.get_value_per_turn_subsegment(path, minLengthFactor=0)
                    if valueSubsegment.length != path.length:
                        logging.info(f"BAD explore_target_player_undiscovered")
                        self.info(f"WHOAH, tried to make a bad exploration path...? Fixed with {str(valueSubsegment)}")
                        path = valueSubsegment
                    move = self.get_first_path_move(path)
                    self.info("Hunting: allIn {} finishingExp {} or demolishingTP {}: {}".format(self.allIn, self.finishingExploration, demolishingTargetPlayer, path.toString()))
                    return move

        if self.all_in_army_advantage and self.all_in_army_advantage_counter > 0:
            cycle = min(75, self._map.players[self.general.player].tileCount - self.target_player_gather_path.length)
            timing = cycle - self.all_in_army_advantage_counter % cycle
            self.viewInfo.addAdditionalInfoLine(f'all in gather AT target general, {timing} remaining')
            with self.perf_timer.begin_move_event(f'all in gather AT target general, {timing} remaining'):
                move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_target_tile(
                    self.targetPlayerExpectedGeneralLocation,
                    0.1,
                    timing,
                    gatherNegatives=None,
                    negativeSet=defenseCriticalTileSet)
                if move is not None:
                    self.info(f'all in gather AT target general, {timing} remaining')
                    self.gatherNodes = gatherNodes
                    return move

        #if len(paths) == 0 and (self.curPath is None or self.curPath.start.next is None) and self._map.turn >= 50:
        if len(paths) == 0 and (self.curPath is None or self.curPath.start.next is None) and not self.defendEconomy:
            path = self.get_value_per_turn_subsegment(self.target_player_gather_path, 1.0, 0.25)
            origPathLength = path.length

            logging.info("{} -----------\nATTACK LAUNCH ?? -------".format(self.get_elapsed()))
            # reduce the length of the path to allow for other use of the army

            targetPathLength = path.length * 4 // 9 + 1
            if self.is_all_in():
                allInPathLength = path.length * 5 // 9 + 1
                self.viewInfo.addAdditionalInfoLine(f"because all in, changed path length from {targetPathLength} to {allInPathLength}")
                targetPathLength = allInPathLength

            if not self.targetPlayerExpectedGeneralLocation.isGeneral:
                targetPathLength += 2

            maxLength = 17
            if self.timings.cycleTurns > 50:
                maxLength = 34

            # never use a super long path because it leaves no time to expand.
            # This is just cutting off the attack-send path length to stop rallying
            # the attack around enemy territory to let the bot expand or whatever. This isn't modifying the real path.
            targetPathLength = min(maxLength, targetPathLength)
            path = path.get_subsegment(targetPathLength)

            path.calculate_value(self.general.player)
            logging.info("  value subsegment = {}".format(path.toString()))
            timingTurn = (self._map.turn + self.timings.offsetTurns) % self.timings.cycleTurns
            player = self._map.players[self.general.player]

            largestEnemyAdj = None
            sumAdj = 0
            armyToGather = self.get_target_army_inc_adjacent_enemy(self.general)
            enemyGenAdj = []
            for generalAdj in self.general.adjacents:
                if generalAdj.player != self._map.player_index and generalAdj.player != -1:
                    self.viewInfo.add_targeted_tile(generalAdj)
                    enemyGenAdj.append(generalAdj)

            if self._map.turn >= 50 and self.timings.in_launch_split(self._map.turn) and (self.targetPlayer != -1 or self._map.remainingPlayers <= 2):
                pathWorth = get_player_army_amount_on_path(self.target_player_gather_path, self.general.player)
                inAttackWindow = timingTurn < self.timings.launchTiming + 4
                minArmy = min(player.standingArmy ** 0.9, (player.standingArmy ** 0.72) * 1.7)

                self.info("  Inside +split if. minArmy {}, path.value {}, timingTurn {} < self.timings.launchTiming + origPathLength {} / 3 {:.1f}: {}".format(minArmy, path.value, timingTurn, origPathLength, self.timings.launchTiming + origPathLength / 2, inAttackWindow))

                if path is not None and pathWorth > minArmy and inAttackWindow:
                    # Then it is worth launching the attack?
                    paths.append(path)
                    logging.info("  attacking because NEW worth_attacking_target(), pathWorth {}, minArmy {}: {}".format(pathWorth, minArmy, path.toString()))
                    self.lastTargetAttackTurn = self._map.turn
                    #return self.move_half_on_repetition(Move(path[1].tile, path[1].parent.tile, path[1].move_half), 7, 3)
                    self.curPath = path
                elif path is not None:
                    logging.info("  Did NOT attack because NOT pathWorth > minArmy or not inAttackWindow??? pathWorth {}, minArmy {}, inAttackWindow {}: {}".format(pathWorth, minArmy, path.toString(), inAttackWindow))
                else:
                    logging.info("  Did not attack because path was None.")


            else:
                logging.info("skipped launch because outside launch window")

            skipForAllIn = (self.is_all_in() and self.targetPlayerExpectedGeneralLocation.isGeneral)

            if len(paths) == 0 and not self.defendEconomy and self.timings.in_expand_split(self._map.turn) and not skipForAllIn:
                expStartTime = time.perf_counter()
                # no timing gather move, optimal expand?
                logging.info("-------------\n Checking for undisc kill, ({:.3f} in)".format(time.perf_counter() - start))

                if self.dangerAnalyzer.fastestThreat is not None:
                    for tile in self.dangerAnalyzer.fastestThreat.armyAnalysis.shortestPathWay.tiles:
                        defenseCriticalTileSet.add(tile)
                if self.dangerAnalyzer.fastestVisionThreat is not None:
                    for tile in self.dangerAnalyzer.fastestVisionThreat.armyAnalysis.shortestPathWay.tiles:
                        defenseCriticalTileSet.add(tile)
                if self.dangerAnalyzer.highestThreat is not None:
                    for tile in self.dangerAnalyzer.highestThreat.armyAnalysis.shortestPathWay.tiles:
                        defenseCriticalTileSet.add(tile)

                undiscNeg = defenseCriticalTileSet.copy()
                for city in self._map.players[self.general.player].cities:
                    undiscNeg.add(city)

                undiscNeg.add(self.general)
                path = self.explore_target_player_undiscovered(undiscNeg)
                if path is not None:
                    self.info("depth {} kill on undisc, Duration {:.3f}, {}".format(path.length, time.perf_counter() - expStartTime, path.toString()))
                    move = self.get_first_path_move(path)
                    return move
                logging.info("------------\n Checking optimal expansion. ({:.3f} in)".format(time.perf_counter() - start))

                expansionNegatives = defenseCriticalTileSet.copy()
                splitTurn = self.timings.get_turn_in_cycle(self._map.turn)
                if splitTurn < self.timings.launchTiming and self._map.turn > 50:
                    self.viewInfo.addAdditionalInfoLine(
                        f"splitTurn {splitTurn} < launchTiming {self.timings.launchTiming}...?")
                    for tile in self.target_player_gather_targets:
                        if tile.player == self.general.player:
                            expansionNegatives.add(tile)

                enemyDistMap = self.board_analysis.intergeneral_analysis.bMap
                territoryMap = self.territories.territoryMap
                innerChokes = self.board_analysis.innerChokes
                pathChokes = self.board_analysis.intergeneral_analysis.pathChokes

                with self.perf_timer.begin_move_event(f'optimal_expansion neg ({str(expansionNegatives)})'):
                    path = get_optimal_expansion(
                        self._map,
                        searchingPlayer=self.player.index,
                        targetPlayer=self.targetPlayer,
                        turns=self.timings.cycleTurns - self.timings.get_turn_in_cycle(self._map.turn),
                        enemyDistMap=enemyDistMap,
                        generalDistMap=self.board_analysis.genDistMap,
                        territoryMap=territoryMap,
                        innerChokes=innerChokes,
                        pathChokes=pathChokes,
                        negativeTiles=expansionNegatives,
                        leafMoves=self.leafMoves,
                        viewInfo=self.viewInfo)

                if path:
                    move = self.get_first_path_move(path)
                    self.info("{} We're using new expansion? {} Duration {:.3f}".format(self.get_elapsed(), move.toString(), time.perf_counter() - expStartTime))
                    return move
                else:
                    logging.info("{} No path found for optimal expansion??? Duration {:.3f}".format(self.get_elapsed(), time.perf_counter() - expStartTime))
            else:
                logging.info("skipping optimal expansion because len(paths) ({}) or self.all_in_counter ({}) or self.defendEconomy ({})".format(len(paths), self.all_in_counter, self.defendEconomy))
            #    #Gather to threat
                #if (self.threat is not None and threat.threatPlayer == self.targetPlayer and self.curPath is None):
                #    threatNextTile = self.threat.path.start.next.tile
                #    move = self.gather_to_target_tile(threatNextTile, 0.1, self.threat.turns)
                #    if (self.is_move_safe_valid(move)):
                #        logging.info("////////// Gathering to threat {},{}: {},{} -> {},{}".format(threatNextTile.x, threatNextTile.y, move.source.x, move.source.y, move.dest.x, move.dest.y))
                #        return move
            if not self.is_all_in() and (len(paths) == 0):
                for city in self._map.players[self.general.player].cities:
                    if city.player == -1:
                        continue
                    largestEnemyAdj = None
                    sumAdj = 0
                    enemyAdjCount = 0
                    friendlyAdjCount = 0
                    for cityAdj in city.adjacents:
                        if cityAdj.player == self._map.player_index:
                            friendlyAdjCount += 1

                        elif cityAdj.player != self._map.player_index and cityAdj.player != -1:
                            sumAdj += cityAdj.army
                            enemyAdjCount += 1
                            if largestEnemyAdj is None or largestEnemyAdj.army < cityAdj.army:
                                largestEnemyAdj = cityAdj
                    # Commenting out to avoid city adjacent timewastes. These should be gotten automatically during expansion timings now.
                    #if (largestEnemyAdj is not None and friendlyAdjCount > 0 and friendlyAdjCount >= enemyAdjCount and (self._map.players[self.general.player].standingArmy < 1000 or self._map.turn % 150 < 25)):
                    #    logging.info("KILLING CITY VISION TILES searching for dest bfs kill on tile {},{}".format(largestEnemyAdj.x, largestEnemyAdj.y))
                    #    self.viewInfo.addSearched(largestEnemyAdj)
                    #    killPath = dest_breadth_first_target(self._map, [largestEnemyAdj], sumAdj - largestEnemyAdj.army + 3, 0.2, 6, defenseCriticalTileSet)
                    #    if (killPath is not None):
                    #        self.info("found depth {} dest bfs kill on CITY vision tile {},{}\n{}".format(killPath.length, largestEnemyAdj.x, largestEnemyAdj.y, killPath.toString()))
                    #        paths.append(killPath)
                # if largestEnemyAdj is not None:
                #     logging.info("KILLING GENERAL VISION TILES searching for dest bfs kill on tile {},{}".format(largestEnemyAdj.x, largestEnemyAdj.y))
                #     self.viewInfo.addSearched(largestEnemyAdj)
                #     (killStart, killPath) = self.dest_breadth_first_kill(largestEnemyAdj, sumAdj - largestEnemyAdj.army + 5, 0.2, 11, defenseCriticalTileSet)
                #     if (killPath is not None):
                #         logging.info("found depth {} dest bfs kill on general vision tile {},{}\n{}".format(killPath.turn, largestEnemyAdj.x, largestEnemyAdj.y, killPath.toString()))
                #         paths.append(killPath)


            paths = sorted(paths, key=lambda x: (x.length, 0 - x.value))

        needToKillTiles = list()
        if not self.timings.disallowEnemyGather and not self.allIn:
            needToKillTiles = self.find_key_enemy_vision_tiles()
            for tile in needToKillTiles:
                self.viewInfo.add_targeted_tile(tile, TargetStyle.RED)

        # LEAF MOVES for the first few moves of each cycle
        timingTurn = self.timings.get_turn_in_cycle(self._map.turn)
        quickExpTimingTurns = self.timings.quickExpandTurns - self._map.turn % self.timings.cycleTurns
        earlyRetakeTurns = quickExpTimingTurns + 3 - self._map.turn % self.timings.cycleTurns

        if not self.is_all_in() \
                and self._map.remainingPlayers <= 3 \
                and earlyRetakeTurns > 0 \
                and len(needToKillTiles) > 0 \
                and timingTurn >= self.timings.quickExpandTurns:
            actualGatherTurns = earlyRetakeTurns

            with self.perf_timer.begin_move_event(f'early retake turn gather?'):
                gatherNodes = GatherUtils.knapsack_levels_backpack_gather(
                    self._map,
                    list(needToKillTiles),
                    actualGatherTurns,
                    negativeTiles = defenseCriticalTileSet,
                    searchingPlayer = self.general.player,
                    incrementBackward=False,
                    ignoreStartTile = True)
            self.gatherNodes = gatherNodes
            move = self.get_tree_move_default(gatherNodes)
            if move is not None:
                self.info("NeedToKillTiles for turns {} ({}) in quickExpand. Move {}".format(earlyRetakeTurns, actualGatherTurns, move.toString()))
                return move

        if not self.is_all_in() and len(paths) == 0 and (self.curPath is None or self.curPath.start.next is None):
            if not self.defendEconomy and quickExpTimingTurns > 0:
                logging.info("-----------\n Leaf moves??? Really come full circle. ({:.3f} in)".format(time.perf_counter() - start))
                moves = self.prioritize_expansion_leaves(self.leafMoves)
                if len(moves) > 0:
                    move = moves[0]
                    self.info("quickExpand leafMove {}".format(move.toString()))
                    return move

        if len(paths) == 0 and (self.curPath is None or self.curPath.start.next is None):
            logging.info("++++++++++++++\n Checking for primary gather phase ({:.3f} in)".format(time.perf_counter() - start))
            tryGather = True
            player = self._map.players[self.general.player]
            modVal = 0
            enemyGather = False
            if not self._map.remainingPlayers > 2 and not self.winning_on_economy(byRatio = 1, cityValue = 0) and self.winning_on_army(0.95):
                logging.info("Forced enemyGather to true due to NOT winning_on_economy(by tiles only) and winning_on_army")
                enemyGather = True

            #neutralGather = len(targets) <= 2
            neutralGather = False
            turn = self._map.turn
            tiles = player.tileCount

            tileDeficitThreshold = self._map.players[self.targetPlayer].tileCount * 1.05
            if self.makingUpTileDeficit:
                tileDeficitThreshold = self._map.players[self.targetPlayer].tileCount * 1.15 + 8

            if not self.defendEconomy and self.distance_from_general(self.targetPlayerExpectedGeneralLocation) > 2 and player.tileCount < tileDeficitThreshold and not (self.is_all_in() or self.all_in_counter > 50):
                logging.info("ayyyyyyyyyyyyyyyyyyyyyyyyy set enemyGather to True because we're behind on tiles")
                enemyGather = True
                skipFFANeutralGather = (self._map.turn > 50 and self._map.remainingPlayers > 2)
                #if not skipFFANeutralGather and (self._map.turn < 120 or self.distance_from_general(self.targetPlayerExpectedGeneralLocation) < 3):
                #    neutralGather = True
                self.makingUpTileDeficit = True
            else:
                self.makingUpTileDeficit = False

            if self.defendEconomy:
                logging.info("we're playing defensively, neutralGather and enemyGather set to false...")
                neutralGather = False
                enemyGather = False
            # TODO maybe replace with optimal expand? But shouldn't be before gather anymore.
            #if (self.makingUpTileDeficit):
            #    leafMove = self.find_leaf_move(allLeaves)
            #    if (None != leafMove):
            #        self.info("doing tileDeficit leafMove stuff mannn")
            #        return leafMove

            if tryGather:
                gathString = ""
                gathStartTime = time.perf_counter()
                gatherTargets = self.target_player_gather_targets.copy()
                gatherNegatives = defenseCriticalTileSet.copy()
                negSet = set()
                #for tile in self.largePlayerTiles:
                #    gatherNegatives.add(tile)
                if self.curPath is not None:
                    negSet.add(self.curPath.start.tile)

                # De-prioritize smallish tiles that are in enemy territory from being gathered
                genPlayer = self._map.players[self.general.player]
                for tile in genPlayer.tiles:
                    # if self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer and tile.army < 8:
                    if self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer:
                        gatherNegatives.add(tile)

                if self.targetPlayer == -1:
                    enemyGather = False

                if self.timings.disallowEnemyGather:
                    logging.info("Enemy gather was disallowed in timings, skipping enemy and neutral gathering.")
                    enemyGather = False
                    neutralGather = False

                if (enemyGather or neutralGather) and not self.is_all_in() and self._map.turn >= 150:
                    gathString += f" +leaf(enemy {enemyGather})"
                    # ENEMY TILE GATHER
                    leafPruneStartTime = time.perf_counter()

                    shortestLength = origPathLength
                    if not self.is_all_in() and not self.defendEconomy and enemyGather and self._map.turn >= 150:
                        # Add support for 'green arrows', pushing outer territory towards enemy territory.
                        goodLeaves = self.board_analysis.find_flank_leaves(
                            self.leafMoves,
                            minAltPathCount=2,
                            maxAltLength=shortestLength + shortestLength // 3)
                        for goodLeaf in goodLeaves:
                            # if goodLeaf.dest.player == self.targetPlayer:

                            self.mark_tile(goodLeaf.dest, 255)
                            # gatherTargets.add(goodLeaf.dest)
                            gatherNegatives.add(goodLeaf.dest)

                    #for leaf in filter(lambda move: move.dest.army > 0 and (move.source.player == move.dest.player or move.source.army - 1 > move.dest.army), self.leafMoves):
                    for leaf in filter(lambda move: move.dest.player == self.targetPlayer or (neutralGather and move.dest.player == -1), self.leafMoves):
                        if not (leaf.dest.isCity and leaf.dest.player == -1) and not leaf.dest in self.target_player_gather_targets:
                            if leaf.dest.player != self.targetPlayer:
                                continue
                            useTile = leaf.source
                            if leaf.dest.player == self.targetPlayer:
                                useTile = leaf.dest

                            if (self.targetPlayer != -1
                                    and not neutralGather
                                    and (leaf.dest.player == -1 or leaf.source.player == -1)):
                                continue

                            # only gather to enemy tiles in our territory as leaves.
                            # OR to tiles that move the army closer to the conflict path
                            if self.territories.territoryMap[useTile.x][useTile.y] != self.general.player \
                                    and (self.distance_from_target_path(leaf.source) <= self.distance_from_target_path(leaf.dest)
                                        or self.distance_from_target_path(leaf.source) > self.shortest_path_to_target_player.length / 3):
                                continue

                            # if self.distance_from_target_path(useTile) > self.shortest_path_to_target_player.length / 2.5:
                            #     self.viewInfo.evaluatedGrid[useTile.x][useTile.y] += 100
                            #     continue

                            # gatherTargets.add(useTile)
                            gatherNegatives.add(useTile)
                            # TEMPORARILY GATHER TO ALL ENEMY TILES IN OUR TERRITORY?
                            ## determine whether leaf is worth expanding to
                            #counter = Counter(0)
                            #def counterFunc(tile):
                            #    if (tile.player == self.targetPlayer or tile.player == -1) and not ((not tile.discovered and tile.isNotPathable) or tile.isMountain):
                            #        counter.add(1)
                            #def skipFunc(tile):
                            #    return tile.player == self.general.player or tile.isMountain or (not tile.discovered and tile.isNotPathable)
                            #breadth_first_foreach(self._map, [useTile], 6, counterFunc, None, skipFunc, None, self.general.player, noLog = True)
                            #if counter.value > 2:
                            #    logging.info("leaf {} explorability {}:".format(useTile.toString(), counter.value))
                            #    leafGatherTargets.append(useTile)
                            #else:
                            #    logging.info("pruned leaf {} from gather due to explorability {}:".format(useTile.toString(), counter.value))
                    logging.info("pruning leaves and stuff took {:.3f}".format(time.perf_counter() - leafPruneStartTime))
                    negSet.add(self.general)

                forceGatherToEnemy = self.should_force_gather_to_enemy_tiles()

                if len(needToKillTiles) > 0:
                    gathString += " +needToKill"
                    for tile in needToKillTiles:
                        if tile in gatherTargets and self.distance_from_general(tile) > 3:
                            continue

                        if not forceGatherToEnemy:
                            self.mark_tile(tile, 100)

                        if forceGatherToEnemy:
                            def tile_remover(curTile: Tile):
                                if curTile not in needToKillTiles and curTile in gatherTargets:
                                    gatherTargets.remove(curTile)

                            breadth_first_foreach(self._map, [tile], 2, tile_remover, None, None, noLog = True)

                            gatherTargets.add(tile)

                    if self.timings.in_quick_expand_split(self._map.turn) and forceGatherToEnemy:
                        negCopy = gatherNegatives.copy()
                        for pathTile in self.target_player_gather_path.tileList:
                            negCopy.add(pathTile)

                        targetTurns = 3
                        with self.perf_timer.begin_move_event(f'Timing Gather to enemy needToKill tiles depth {targetTurns}'):
                            move = self.timing_gather(
                                needToKillTiles,
                                negCopy,
                                skipTiles=genPlayer.cities,
                                force=True,
                                priorityTiles=None,
                                targetTurns=targetTurns,
                                includeTreeNodesThatGatherNegative=False)
                        if move is not None:
                            self.curPath = None
                            self.info(
                                f"GATHER needToKill{gathString}! Gather move: {move.toString()} Duration {time.perf_counter() - gathStartTime:.3f}")
                            return self.move_half_on_repetition(move, 6, 4)
                        else:
                            logging.info("No needToKill gather move found")
                else:
                    needToKillTiles = None

                with self.perf_timer.begin_move_event(f'Timing Gather (normal timings, or long timings if defensive)'):
                    move = self.timing_gather(
                        gatherTargets,
                        gatherNegatives.union(self.cities_gathered_this_cycle),
                        skipTiles = None,
                        force = True,
                        priorityTiles = None)
                if move is not None:
                    if move.dest.player != self.player.index and move.dest not in self.target_player_gather_targets:
                        self.timings.splitTurns += 1
                        self.timings.launchTiming += 1

                    if move.source.isCity or move.source.isGeneral:
                        self.cities_gathered_this_cycle.add(move.source)

                    if move.dest.isCity and move.dest.player == self.player.index and move.dest in self.cities_gathered_this_cycle:
                        self.cities_gathered_this_cycle.remove(move.dest)

                    self.curPath = None
                    self.info(
                        f"NEW GATHER TO GATHER PATH{gathString}! Gather move: {move.toString()} Duration {time.perf_counter() - gathStartTime:.3f}")
                    return self.move_half_on_repetition(move, 6, 4)
                else:
                    logging.info("No gather move found")
                ## TARGET PATH GATHER
                #self.gatherNodes = self.build_mst(gatherTargets, 1.0, 40, gatherNegatives, negSet)

                #move = self.get_gather_move(self.gatherNodes, None, allowNonKill = True)
                #if (move is not None):
                #    self.info("TARGET-PATH GATHER MOVE! {},{} -> {},{}".format(move.source.x, move.source.y, move.dest.x, move.dest.y))
                #    #self.curPath = None
                #    #self.curPathPrio = -1
                #    return self.move_half_on_repetition(move, 6)
            if not self.is_all_in():
                leafMove = self.find_leaf_move(self.leafMoves)
                if None != leafMove:
                    self.info("No move found leafMove? {}".format(leafMove.toString()))
                    return leafMove


        if self.curPath is None or self.curPath.start.next is None:
            if self.general is not None:
                highPriAttack = False
                attackable = []
                if self.attackFailedTurn <= self._map.turn - 100 and random.choice(range(3)) == 0:
                    for gen in self._map.generals:
                        if gen is not None and gen.player != self._map.player_index:
                            if self.is_cost_effective_to_attack(gen):
                                logging.info(f"Cost effective to attack general {gen.toString()}")
                                attackable.append(gen)
                                highPriAttack = True
                            else:
                                logging.info(f"Skipped attack of general {gen.player}")
                #attack undiscovered tiles and cities
                if self._map.turn > 250 and len(attackable) == 0 and random.choice(range(2)) == 0:
                    logging.info("\n------------\nGathering to attack undiscovered or cities:\n------------\n")
                    prio = PriorityQueue()
                    #for tile in self.get_enemy_undiscovered():
                    if self._map.generals[self.targetPlayer] is None:
                        if self.generalApproximations[self.targetPlayer][2] > 0:
                            for tile in random.sample(self.allUndiscovered, max(int(len(self.allUndiscovered) / 3), min(2, len(self.allUndiscovered)))):
                                prio.put((self.euclidDist(tile.x, tile.y, self.generalApproximations[self.targetPlayer][0], self.generalApproximations[self.targetPlayer][1]), tile))
                    iter = 0
                    while not prio.empty() and iter < 3:
                        iter += 1
                        attackable.append(prio.get()[1])

                    if not self.allIn and (len(attackable) == 0 or random.choice(range(4)) == 0) and self._map.players[self.general.player].standingArmy > 100:
                        logging.info("including cities")
                        for city in self.enemyCities:
                            attackable.append(city)
                    if len(attackable) == 0 and self.targetPlayer == -1:
                        #TODO prioritize better spots wtf not random
                        attackable = self.allUndiscovered



                if len(paths) > 0:
                    self.curPath = paths[0]
                    self.gathers += 1
                else:
                    self.curPathPrio = -1
        if self.curPath is not None:
            inc = 0
            while (self.curPath.start.tile.army <= 1 or self.curPath.start.tile.player != self._map.player_index) and self.curPath.start.next is not None:
                inc += 1
                if self.curPath.start.tile.army <= 1:
                    logging.info(
                        f"!!!!\nMove was from square with 1 or 0 army\n!!!!! {self.curPath.start.tile.x},{self.curPath.start.tile.y} -> {self.curPath.start.next.tile.x},{self.curPath.start.next.tile.y}")
                elif self.curPath.start.tile.player != self._map.player_index:
                    logging.info(
                        f"!!!!\nMove was from square OWNED BY THE ENEMY\n!!!!! [{self.curPath.start.tile.player}] {self.curPath.start.tile.x},{self.curPath.start.tile.y} -> {self.curPath.start.next.tile.x},{self.curPath.start.next.tile.y}")
                logging.info(f"{inc}: doing made move thing? Path: {self.curPath.toString()}")
                self.curPath.made_move()
                if inc > 20:
                    raise ArithmeticError("bitch, what you doin?")

            if self.curPath.start.next is not None:
                dest = self.curPath.start.next.tile
                source = self.curPath.start.tile
                if (dest.isCity or dest.isGeneral) and dest.player != self._map.player_index:
                    if source.army - 2 < dest.army:
                        gatherDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) / 2
                        logging.info("Tried to take a city / general with less than enough army.")
                        if dest.isGeneral and self._map.players[self.general.player].tileCount < self._map.players[self.targetPlayer].tileCount:
                            gatherDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) / 4
                            logging.info("Losing economically and target was general, searching a shorter additional killpath.")

                        armyAmount = -1
                        if dest.isGeneral or (dest.isCity and dest.player >= 0):
                            armyAmount = dest.army / 2
                        paths = self.weighted_breadth_search([dest], int(gatherDist), 0.12, -2, armyAmount, 10, defenseCriticalTileSet)
                        if len(paths) > 0:
                            self.curPath = paths[0]
                            logging.info(f"Found path to cap the city: {self.curPath.toString()}")
                        elif dest.isGeneral:
                            self.attackFailedTurn = self._map.turn
                            self.curPath = None
                            self.curPathPrio = -1
                        else:
                            self.curPath = None
                            self.curPathPrio = -1


                if self.curPath is not None and self.curPath.start.next is not None and self.curPath.start.tile.isGeneral and not self.general_move_safe(self.curPath.start.next.tile):
                    logging.info(
                        f"Attempting to execute path move from self.curPath? ({time.perf_counter() - start:.3f} in)")
                    #self.curPath = None
                    #self.curPathPrio = -1
                    #logging.info("General move in path would have violated general min army allowable. Repathing.")
                    if self.general_move_safe(self.curPath.start.next.tile, move_half=True):
                        logging.info("General move in path would have violated general min army allowable. Moving half.")
                        move = Move(self.curPath.start.tile, self.curPath.start.next.tile, True)
                        return move
                    else:
                        self.curPath = None
                        self.curPathPrio = -1
                        logging.info("General move in path would have violated general min army allowable. Repathing.")

                else:
                    cleanPath = False
                    while self.curPath is not None and not cleanPath:
                        if self.curPath.start.tile in defenseCriticalTileSet and self.curPath.start.tile.army > 5:
                            tile = self.curPath.start.tile
                            # self.curPathPrio = -1
                            logging.info(
                                f"\n\n\n~~~~~~~~~~~\nSKIPPED: Move was from a negative tile {tile.x},{tile.y}\n~~~~~~~~~~~~~\n\n~~~\n")
                            self.curPath = None
                            self.curPathPrio = -1
                            if threat is not None:
                                killThreatPath = self.kill_threat(self.threat)
                                if killThreatPath is not None:
                                    self.info(f"Final path to kill threat! {killThreatPath.toString()}")
                                    #self.curPath = killThreatPath
                                    self.viewInfo.color_path(PathColorer(killThreatPath, 0, 255, 204, 255, 10, 200))
                                    self.targetingArmy = self.armyTracker.armies[threat.path.start.tile]
                                    return self.get_first_path_move(killThreatPath)
                            else:
                                logging.warn("Negative tiles prevented a move but there was no threat???")

                        elif self.curPath.start.next is not None and self.curPath.start.next.next is not None and self.curPath.start.tile == self.curPath.start.next.next.tile and self.curPath.start.next.tile.player == self.curPath.start.tile.player:
                            logging.info("\n\n\n~~~~~~~~~~~\nCleaned double-back from path\n~~~~~~~~~~~~~\n\n~~~\n")
                            self.curPath.made_move()
                        elif self.curPath.start.tile.player != self._map.player_index or self.curPath.start.tile.army < 2:
                            logging.info("\n\n\n~~~~~~~~~~~\nCleaned useless move from path\n~~~~~~~~~~~~~\n\n~~~\n")
                            self.curPath.made_move()
                        else:
                            cleanPath = True
                    if self.curPath is not None and self.curPath.start.next is not None:
                        if self.curPath.start.tile == self.general and not self.general_move_safe(self.curPath.start.next.tile, self.curPath.start.move_half):
                            self.curPath = None
                            self.curPathPrio = -1
                        else:
                            move = self.get_first_path_move(self.curPath)
                            end = time.perf_counter()
                            logging.info(f"Path Move Duration: {end - start:.2f}")
                            #self.info("MAKING MOVE FROM NEW PATH CLASS! Path {}".format(self.curPath.toString()))
                            return self.move_half_on_repetition(move, 6, 3)


            self.curPath = None
        self.curPathPrio = -1
        self.info(f"!!!!\nFOUND NO MOVES, GONNA GATHER ({time.perf_counter() - start:.3f} in)\n!!!!")

        gathers = self.build_mst(self.target_player_gather_targets, 1.0, 25,  None)
        gathers = GatherUtils.prune_mst_to_turns(gathers, 25, self.general.player, self.viewInfo)
        self.gatherNodes = gathers
        #move = self.get_gather_move(gathers, None, 1, 0, preferNeutral = True)
        move = self.get_tree_move_default(gathers)
        if move is None:
            turnInCycle = self.timings.get_turn_in_cycle(self._map.turn)
            if self.timings.cycleTurns - turnInCycle > self.target_player_gather_path.length * 0.66:
                self.info("Found-no-moves-gather found no move ????? Setting launch to now.")
                self.timings.launchTiming = self._map.turn % self.timings.cycleTurns
            else:
                self.info("Found-no-moves-gather found no move, launch ineffective, no move.")
        elif self.is_move_safe_valid(move):
            return move
        else:
            self.info(
                f"Found-no-moves-gather move {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} was not safe or valid!")

        #if (allowRetry and time.perf_counter() - start < 0.15):
        #    logging.info("Retrying.")
        #    return self.select_move(False)
        return None

    def is_all_in(self):
        return self.allIn or self.all_in_army_advantage

    def should_kill(self, tile):
        # bypass bugs around city increment for kill_path.
        # If its a city and they aren't moving the army, no sense trying to treat it like an army intercept anyway.
        if tile.isCity and abs(tile.delta.armyDelta) < 3:
            return False
        return True

    def just_moved(self, tile):
        if abs(tile.delta.armyDelta) > 2:
            return True
        else:
            return False

    def should_kill_path_move_half(self, threatKill, additionalArmy = 0):
        start = threatKill.start.tile
        next = threatKill.start.next.tile
        threatKill.calculate_value(self.general.player)
        movingAwayFromEnemy = self.board_analysis.intergeneral_analysis.bMap[start.x][start.y] < self.board_analysis.intergeneral_analysis.bMap[next.x][next.y]
        move_half = movingAwayFromEnemy and threatKill.tail.tile.army + additionalArmy < (threatKill.value + threatKill.tail.tile.army) // 2
        logging.info(
            f"should_kill_path_move_half: movingAwayFromEnemy {movingAwayFromEnemy}\n                 threatKill.value = {threatKill.value}\n                 threatKill.tail.tile.army = {threatKill.tail.tile.army}\n                 (threatKill.value + threatKill.tail.tile.army) // 2 = {(threatKill.value + threatKill.tail.tile.army) // 2}\n                 : {move_half}")
        return move_half

    def find_key_enemy_vision_tiles(self):
        keyTiles = set()
        genPlayer = self._map.players[self.general.player]
        distFactor = 2
        priorityDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // distFactor
        if self.targetPlayerExpectedGeneralLocation.isGeneral:
            distFactor = 3
            priorityDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // distFactor + 1

        for tile in self.general.adjacents:
            if tile.player != -1 and tile.player != self.general.player:
                keyTiles.add(tile)
        for city in genPlayer.cities:
            if self._map.turn - city.turn_captured > 20:
                for tile in city.adjacents:
                    if tile.player != -1 and tile.player != self.general.player:
                        keyTiles.add(tile)


        for tile in self._map.pathableTiles:
            if tile.player != -1 and tile.player != self.general.player:
                if self.distance_from_general(tile) < priorityDist:
                    keyTiles.add(tile)

        return keyTiles

    def worth_path_kill(self, pathKill: Path, threatPath: Path, analysis = None, cutoffDistance = 5):
        if pathKill.start is None or pathKill.tail is None:
            return False

        lenTillInThreatPath = 0
        node = pathKill.start
        while node is not None and node.tile not in threatPath.tileSet:
            lenTillInThreatPath += 1
            node = node.next
        shortEnoughPath = lenTillInThreatPath < max(3, threatPath.length - 1)
        logging.info(
            f"worth_path_kill: shortEnoughPath = lenTillInThreatPath {lenTillInThreatPath} < max(3, threatPath.length - 1 ({threatPath.length - 1})): {shortEnoughPath}")
        if not shortEnoughPath:
            self.viewInfo.paths.append(PathColorer(pathKill.clone(), 163, 89, 0, 255, 0, 100))
            logging.info(f"  path kill eliminated due to shortEnoughPath {shortEnoughPath}")
            return False


        minSourceArmy = 8
        threatArmy = threatPath.start.tile.army
        if threatPath.start.tile in self.armyTracker.armies:
            army = self.armyTracker.armies[threatPath.start.tile]
            threatArmy = army.value
        threatMoved = abs(threatPath.start.tile.delta.armyDelta) >= 2
        if threatArmy < minSourceArmy and not threatMoved:
            logging.info(
                f"  path kill eliminated due to not threatMoved and threatArmy {threatArmy} < minSourceArmy {minSourceArmy}")
            return False

        if not analysis:
            analysis = ArmyAnalyzer(self._map, threatPath.start.tile, threatPath.tail.tile, threatPath.length)
        lastTile = pathKill.tail.tile
        if pathKill.start.next.next is not None:
            lastTile = pathKill.start.next.next.tile
        startDist = self.board_analysis.intergeneral_analysis.bMap[pathKill.start.tile.x][pathKill.start.tile.y]
        tailDist = self.board_analysis.intergeneral_analysis.bMap[lastTile.x][lastTile.y]
        movingTowardsOppo = startDist > tailDist
        logging.info(
            f"worth_path_kill: movingTowardsOppo {movingTowardsOppo}  ({pathKill.start.tile.toString()} [{startDist}]  ->  {lastTile.toString()} [{tailDist}])")
        onShortestPathwayAlready = (pathKill.start.tile in analysis.pathWayLookupMatrix[threatPath.start.tile].tiles
                                    or (pathKill.start.tile in analysis.pathWayLookupMatrix
                                        and analysis.pathWayLookupMatrix[pathKill.start.tile].distance < analysis.pathWayLookupMatrix[threatPath.start.tile].distance))

        logging.info(
            f"worth_path_kill: onPath = pathKill.start.tile {pathKill.start.tile.toString()} in analysis.pathways[threatPath.start.tile {threatPath.start.tile.toString()}].tiles: {onShortestPathwayAlready}")

        #if pathKill.length > cutoffDistance and onShortestPathwayAlready and not movingTowardsOppo:
        if pathKill.length > cutoffDistance and not movingTowardsOppo:
            # then we're already on their attack path? Don't waste time moving towards it unless we're close.
            self.viewInfo.paths.append(PathColorer(pathKill.clone(), 217, 0, 0, 255, 0, 100))
            logging.info(
                f"  path kill eliminated due to pathKill.length > cutoffDistance {cutoffDistance} ({pathKill.length > cutoffDistance}) and onShortestPathwayAlready {onShortestPathwayAlready} and not movingTowardsOppo {movingTowardsOppo}")
            return False
        logging.info(f"  path kill worth it because not eliminated ({pathKill.toString()})")
        return True

    def kill_army(self, army, allowGeneral = False, allowWorthPathKillCheck = True):
        path = breadth_first_dynamic(self._map, [army.tile], lambda tile, object: tile == self.general, noNeutralCities = True, searchingPlayer = army.player)

        if path:
            self.viewInfo.paths.append(PathColorer(path.clone(), 100,0,100, 200, 5, 100))
            killPath = self.kill_enemy_path(path, allowGeneral)

            if killPath is not None and ((not allowWorthPathKillCheck) or self.worth_path_kill(killPath, path, ArmyAnalyzer(self._map, self.general, army.tile))):
                return killPath
            else:
                if killPath is not None:
                    logging.info(
                        f"NOT Continuing to target army {army.toString()} because the pathkill isn't really worth it right now. killPath was {killPath.toString()}")
                else:
                    logging.info(f"NOT Continuing to target army {army.toString()}, no pathKill was found.")
        else:
            logging.info(f"In Kill_army: No bfs dynamic path found from army tile {army.toString()} ???????")
        return None

    def kill_enemy_path(self, threatPath: Path, allowGeneral = False) -> Path | None:
        """
        This is some wild shit that needs to be redone.
        @param threatPath:
        @param allowGeneral:
        @return:
        """
        path = self.try_find_counter_army_scrim_path_killpath(threatPath, allowGeneral)
        if path is not None:
            return path

        logging.info(f"Starting kill_enemy_path for path {threatPath.toString()}")
        if threatPath.length <= 3:
            logging.info('threat path too short for kill_enemy_path and no army scrim move found..?')
            return None

        startTime = time.perf_counter()
        shorterThreatPath = threatPath.get_subsegment(threatPath.length - 2)
        threatPathSet = shorterThreatPath.tileSet.copy()
        threatPathSet.remove(threatPath.start.tile)
        #negativeTiles = threatPathSet.copy()
        negativeTiles = set()

        threatTile = threatPath.start.tile
        threatPlayer = threatPath.start.tile.player
        if threatTile in self.armyTracker.armies:
            threatPlayer = self.armyTracker.armies[threatTile].player
        threatPath.calculate_value(threatPlayer)
        threatValue = max(threatPath.start.tile.army, threatPath.value)
        if threatTile.player != threatPlayer:
            threatValue = self.armyTracker.armies[threatTile].value
        if threatValue <= 0:
            # then we're probably blocking the threat in the negative tiles. Undo negative tiles and set desired value to the actual threat tile value.
            threatValue = threatTile.army
            if threatTile.player != threatPlayer:
                threatValue = self.armyTracker.armies[threatTile].value

            negativeTiles = set()
            #for tile in threatPathSet:
            #    if tile.player == threatPath.start.tile.player:
            #        negativeTiles.add(tile)
            logging.info(
                f"threatValue was originally {threatPath.value}, removed player negatives and is now {threatValue}")
        else:
            logging.info(f"threatValue is {threatValue}")

        # Doesn't make any sense to have the general defend against his own threat, does it? Maybe it does actually hm
        if not allowGeneral:
            negativeTiles.add(self.general)

        # First try one move kills on next tile, since I think this is broken in the loop for whatever reason... (make it 2 moves though bc other stuff depends on tail tile)
        for adj in threatPath.start.next.tile.movable:
            if adj.army > 3 and adj.player == self.general.player and adj.army >= threatValue:
                path = Path()
                path.add_next(adj)
                path.add_next(threatPath.start.next.tile)
                path.add_next(threatTile)
                self.viewInfo.addAdditionalInfoLine(f"returning nextTile direct-kill move {path.toString()}")
                return path

        # Then try one move kills on the threat tile. 0 = 1 move????
        for adj in threatTile.movable:
            if adj.army > 3 and adj.player == self.general.player and adj.army >= threatValue:
                path = Path()
                path.add_next(adj)
                path.add_next(threatTile)
                self.viewInfo.addAdditionalInfoLine(f"returning direct-kill move {path.toString()}")
                return path


        # Then iteratively search for a kill to the closest tile on the path to the threat, checking one tile further along the threat each time.
        curNode = threatPath.start.next
        # 0 = 1 move? lol
        i = 0
        threatModifier = 0
        gatherToThreatPath = None
        while gatherToThreatPath is None and curNode is not None:
            # trying to use the generals army as part of the path even though its in negative tiles? apparently negativetiles gets ignored for the start tile?
            # # NOT TRUE ANYMORE!!??!?!
            #if curNode.tile.player != threatPath.start.tile.player:
            #    threatModifier -= curNode.tile.army
            logging.info(
                f"Attempting threatKill on tile {curNode.tile.toString()} with threatValue {threatValue} + mod {threatModifier} = ({threatValue + threatModifier})")
            gatherToThreatPath = dest_breadth_first_target(self._map, [curNode.tile], targetArmy = threatValue + threatModifier, maxDepth = max(1, i), searchingPlayer = self.general.player, negativeTiles = negativeTiles, noLog = True, ignoreGoalArmy = True)
            #if curNode.tile.player == self.general.player:
            #    nodeVal = curNode.tile.army - 1
            #gatherToThreatPath = dest_breadth_first_target(self._map, [curNode.tile], targetArmy = threatValue + nodeVal, maxDepth = max(1, i), searchingPlayer = self.general.player, negativeTiles = negativeTiles, noLog = True)
            i += 1
            curNode = curNode.next

        if gatherToThreatPath is not None:
            self.viewInfo.addAdditionalInfoLine(
                f"whoo, found kill on threatpath with path {gatherToThreatPath.toString()}")
            alpha = 140
            minAlpha = 100
            alphaDec = 2
            self.viewInfo.color_path(PathColorer(gatherToThreatPath.clone(), 150, 150, 255, alpha, alphaDec, minAlpha))
            tail = gatherToThreatPath.tail.tile

            goalFunc = lambda tile, prioObject: tile == threatPath.start.tile

            def threatPathSortFunc(nextTile, prioObject):
                (dist, _, negNumThreatTiles, negArmy) = prioObject
                if nextTile in threatPathSet:
                    negNumThreatTiles -= 1
                if nextTile.player == self.general.player:
                    negArmy -= nextTile.army
                else:
                    negArmy += nextTile.army
                dist += 1
                return dist, self.euclidDist(nextTile.x, nextTile.y, threatTile.x, threatTile.y), negNumThreatTiles, negArmy
            inputTiles = {}
            inputTiles[tail] = ((0, 0, 0, 0), 0)

            threatPathToThreat = breadth_first_dynamic(self._map, inputTiles, goalFunc, noNeutralCities=True, priorityFunc=threatPathSortFunc)
            if threatPathToThreat is not None:
                logging.info(
                    f"whoo, finished off the threatpath kill {threatPathToThreat.toString()}\nCombining paths...")
                node = threatPathToThreat.start.next
                while node is not None:
                    gatherToThreatPath.add_next(node.tile)
                    node = node.next
                gatherToThreatPath.calculate_value(self.general.player)
        endTime = time.perf_counter() - startTime
        if gatherToThreatPath is not None:
            if gatherToThreatPath.length == 0:
                logging.info(
                    f"kill_enemy_path {threatPath.start.tile.toString()} completed in {endTime:.3f}, PATH {gatherToThreatPath.toString()} WAS LENGTH 0, RETURNING NONE! :(")
                return None
            else:
                logging.info(
                    f"kill_enemy_path {threatPath.start.tile.toString()} completed in {endTime:.3f}, path {gatherToThreatPath.toString()}")
        else:
            logging.info(
                f"kill_enemy_path {threatPath.start.tile.toString()} completed in {endTime:.3f}, No path found :(")
        return gatherToThreatPath

    def kill_threat(self, threat, allowGeneral = False):
        return self.kill_enemy_path(threat.path.get_subsegment(threat.path.length // 2), allowGeneral)

    def gather_to_target_MST(self, target, maxTime, gatherTurns, gatherNegatives = None, negativeSet = None, targetArmy = None):
        if targetArmy is None:
            targetArmy = target.army + 1
        targets = self.get_path_to_target(target, maxTime, gatherTurns, skipEnemyCities=True, preferNeutral=True).tileSet
        treeNodes = self.build_mst(targets, maxTime, gatherTurns, gatherNegatives, negativeSet)
        move = self.get_gather_move(treeNodes, None, targetArmy)
        if move is not None:
            self.gatherNodes = treeNodes
            #self.curPath = None
            #self.curPathPrio = -1
            return self.move_half_on_repetition(move, 5)
        return None

    def get_gather_move_to_target_tile(
            self,
            target,
            maxTime,
            gatherTurns,
            gatherNegatives = None,
            negativeSet = None,
            targetArmy = -1,
            useTrueValueGathered = False,
            includeTreeNodesThatGatherNegative = False
    ) -> typing.Union[Move, None]:
        """

        @param target:
        @param maxTime:
        @param gatherTurns:
        @param gatherNegatives:
        @param negativeSet:
        @param targetArmy:
        @param useTrueValueGathered:
        @param includeTreeNodesThatGatherNegative:
        @return:
        """
        targets = [target]
        gatherMove, gatherValue, gatherTurns, gatherNodes = self.get_gather_to_target_tiles(
            targets,
            maxTime,
            gatherTurns,
            gatherNegatives,
            negativeSet,
            targetArmy,
            useTrueValueGathered,
            includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative)
        if gatherMove is not None:
            self.gatherNodes = gatherNodes

        return gatherMove

    # set useTrueValueGathered to True for things like defense gathers, where you want to take into account army lost gathering over enemy or neutral tiles etc.
    def get_gather_move_to_target_tiles(
            self,
            targets,
            maxTime,
            gatherTurns,
            gatherNegatives = None,
            negativeSet = None,
            targetArmy = -1,
            useTrueValueGathered = False,
            includeTreeNodesThatGatherNegative = False
    ) -> typing.Union[Move, None]:
        """

        @param targets:
        @param maxTime:
        @param gatherTurns:
        @param gatherNegatives:
        @param negativeSet:
        @param targetArmy:
        @param useTrueValueGathered:
        @param includeTreeNodesThatGatherNegative:
        @return:
        """
        gatherMove, gatherValue, gatherTurns, gatherNodes = self.get_gather_to_target_tiles(
            targets,
            maxTime,
            gatherTurns,
            gatherNegatives,
            negativeSet,
            targetArmy,
            useTrueValueGathered,
            includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative)
        if gatherMove is not None:
            self.gatherNodes = gatherNodes

        return gatherMove

    def get_gather_to_target_tile(
            self,
            target: Tile,
            maxTime: float,
            gatherTurns: int,
            gatherNegatives: typing.Set[Tile] | None = None,
            negativeSet: typing.Set[Tile] | None = None,
            targetArmy: int = -1,
            useTrueValueGathered = False,
            includeTreeNodesThatGatherNegative = False
    ) -> typing.Tuple[typing.Union[Move, None], int, int, typing.Union[None, typing.List[TreeNode]]]:
        """
        returns move, valueGathered, turnsUsed

        @param target:
        @param maxTime:
        @param gatherTurns:
        @param gatherNegatives:
        @param negativeSet:
        @param targetArmy:
        @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
         capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
         so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
         gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
         Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
        @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
         to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
         Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
        @return:
        """
        targets = [target]
        gatherTuple = self.get_gather_to_target_tiles(
            targets,
            maxTime,
            gatherTurns,
            gatherNegatives,
            negativeSet,
            targetArmy,
            useTrueValueGathered=useTrueValueGathered,
            includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative)
        return gatherTuple

    # set useTrueValueGathered to True for things like defense gathers,
    # where you want to take into account army lost gathering over enemy or neutral tiles etc.
    def get_gather_to_target_tiles(
            self,
            targets,
            maxTime,
            gatherTurns,
            gatherNegatives = None,
            negativeSet = None,
            targetArmy = -1,
            useTrueValueGathered = False,
            leafMoveSelectionPriorityFunc = None,
            leafMoveSelectionValueFunc = None,
            includeTreeNodesThatGatherNegative = False,
            shouldLog: bool =False
    ) -> typing.Tuple[typing.Union[Move, None], int, int, typing.Union[None, typing.List[TreeNode]]]:
        """
        returns move, valueGathered, turnsUsed, gatherNodes

        @param targets:
        @param maxTime:
        @param gatherTurns:
        @param gatherNegatives:
        @param negativeSet:
        @param targetArmy:
        @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
         capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
         so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
         gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
         Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
        @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
         to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
         Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
        @param leafMoveSelectionPriorityFunc:
        @param leafMoveSelectionValueFunc:
        @return:
        """

        #gatherNodes = self.build_mst(targets, maxTime, gatherTurns, gatherNegatives, negativeSet)
        #move = self.get_gather_move(gatherNodes, None, targetArmy, None)
        if gatherTurns > GATHER_SWITCH_POINT:
            logging.info(f"    gather_to_target_tiles  USING OLD GATHER DUE TO gatherTurns {gatherTurns}")
            treeNodes = self.build_mst(targets, maxTime, gatherTurns - 1, gatherNegatives)
            treeNodes = GatherUtils.prune_mst_to_turns(treeNodes, gatherTurns - 1, self.general.player, self.viewInfo)
            gatherMove = self.get_tree_move_default(treeNodes, priorityFunc=leafMoveSelectionPriorityFunc, valueFunc=leafMoveSelectionValueFunc)
            value = 0
            turns = 0
            for node in treeNodes:
                value += node.value
                turns += node.gatherTurns
            if gatherMove is not None:
                self.info(
                    f"gather_to_target_tiles OLD GATHER {gatherMove.source.toString()} -> {gatherMove.dest.toString()}  gatherTurns: {gatherTurns}")
                self.gatherNodes = treeNodes
                return self.move_half_on_repetition(gatherMove, 6), value, turns, treeNodes
        else:
            gatherNodes = GatherUtils.knapsack_levels_backpack_gather(
                self._map,
                targets,
                gatherTurns,
                targetArmy,
                negativeTiles = negativeSet,
                searchingPlayer = self.general.player,
                viewInfo = self.viewInfo,
                useTrueValueGathered = useTrueValueGathered,
                incrementBackward=False,
                includeTreeNodesThatGatherNegative = includeTreeNodesThatGatherNegative,
                shouldLog=shouldLog)
            # gatherNodes = GatherUtils.greedy_backpack_gather(
            #     self._map,
            #     targets,
            #     gatherTurns,
            #     targetArmy,
            #     negativeTiles = negativeSet,
            #     searchingPlayer = self.general.player,
            #     viewInfo = self.viewInfo,
            #     useTrueValueGathered = useTrueValueGathered,
            #     includeTreeNodesThatGatherNegative = includeTreeNodesThatGatherNegative,
            #     shouldLog=shouldLog)

            totalValue = 0
            turns = 0
            for gather in gatherNodes:
                logging.info("gatherNode {} value {}".format(gather.tile.toString(), gather.value))
                totalValue += gather.value
                turns += gather.gatherTurns

            logging.info(
                f"gather_to_target_tiles totalValue was {totalValue}. Setting gatherNodes for visual debugging regardless of using them")
            if totalValue > targetArmy:
                move = self.get_tree_move_default(gatherNodes, priorityFunc=leafMoveSelectionPriorityFunc, valueFunc=leafMoveSelectionValueFunc)
                if move is not None:
                    self.gatherNodes = gatherNodes
                    return self.move_half_on_repetition(move, 4), totalValue, turns, gatherNodes
                else:
                    logging.info("Gather returned no moves :(")
            else:
                logging.info(f"Value {totalValue} was too small to return... (needed {targetArmy}) :(")
        return None, -1, -1, None


    # set useTrueValueGathered to True for things like defense gathers,
    # where you want to take into account army lost gathering over enemy or neutral tiles etc.
    def get_gather_to_target_tiles_greedy(
            self,
            targets,
            maxTime,
            gatherTurns,
            gatherNegatives = None,
            negativeSet = None,
            targetArmy = -1,
            useTrueValueGathered = False,
            priorityFunc = None,
            valueFunc = None,
            includeTreeNodesThatGatherNegative = False,
            shouldLog: bool =False
    ) -> typing.Tuple[typing.Union[Move, None], int, int, typing.Union[None, typing.List[TreeNode]]]:
        """
        returns move, valueGathered, turnsUsed, gatherNodes

        @param targets:
        @param maxTime:
        @param gatherTurns:
        @param gatherNegatives:
        @param negativeSet:
        @param targetArmy:
        @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
         capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
         so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
         gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
         Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
        @param includeTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
         to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
         Use includeTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
        @param priorityFunc:
        @param valueFunc:
        @return:
        """

        #gatherNodes = self.build_mst(targets, maxTime, gatherTurns, gatherNegatives, negativeSet)
        #move = self.get_gather_move(gatherNodes, None, targetArmy, None)
        if gatherTurns > GATHER_SWITCH_POINT:
            logging.info(f"    gather_to_target_tiles  USING OLD GATHER DUE TO gatherTurns {gatherTurns}")
            treeNodes = self.build_mst(targets, maxTime, gatherTurns - 1, gatherNegatives)
            treeNodes = GatherUtils.prune_mst_to_turns(treeNodes, gatherTurns - 1, self.general.player, self.viewInfo)
            gatherMove = self.get_tree_move_default(treeNodes, priorityFunc=priorityFunc, valueFunc=valueFunc)
            value = 0
            turns = 0
            for node in treeNodes:
                value += node.value
                turns += node.gatherTurns
            if gatherMove is not None:
                self.info(
                    f"gather_to_target_tiles OLD GATHER {gatherMove.source.toString()} -> {gatherMove.dest.toString()}  gatherTurns: {gatherTurns}")
                self.gatherNodes = treeNodes
                return self.move_half_on_repetition(gatherMove, 6), value, turns, treeNodes
        else:
            gatherNodes = GatherUtils.greedy_backpack_gather(
                self._map,
                targets,
                gatherTurns,
                targetArmy,
                negativeTiles = negativeSet,
                searchingPlayer = self.general.player,
                viewInfo = self.viewInfo,
                useTrueValueGathered = useTrueValueGathered,
                includeTreeNodesThatGatherNegative=includeTreeNodesThatGatherNegative,
                shouldLog=shouldLog)

            totalValue = 0
            turns = 0
            for gather in gatherNodes:
                logging.info(f"gatherNode {gather.tile.toString()} value {gather.value}")
                totalValue += gather.value
                turns += gather.gatherTurns

            logging.info(
                f"gather_to_target_tiles totalValue was {totalValue}. Setting gatherNodes for visual debugging regardless of using them")
            if totalValue > targetArmy:
                move = self.get_tree_move_default(gatherNodes, priorityFunc=priorityFunc, valueFunc=valueFunc)
                if move is not None:
                    self.gatherNodes = gatherNodes
                    return self.move_half_on_repetition(move, 4), totalValue, turns, gatherNodes
                else:
                    logging.info("Gather returned no moves :(")
            else:
                logging.info(f"Value {totalValue} was too small to return... (needed {targetArmy}) :(")
        return None, -1, -1, None

    def euclidDist(self, x, y, x2, y2):
        return pow(pow(abs(x - x2), 2) + pow(abs(y - y2), 2), 0.5)

    def is_cost_effective_to_attack(self, enemyGen):
        player = self._map.players[self.general.player]
        enemyPlayer = self._map.players[enemyGen.player]

        armyBase = player.standingArmy - self.general_min_army_allowable()

        if enemyPlayer.tileCount == 1 and enemyGen.army > 30 and self._map.remainingPlayers > 2:
            return False

        if armyBase * 0.7 < enemyGen.army + 15:
            return False
        return True

    def sum_enemy_army_near_tile(self, tile, distance = 2):
        """does NOT include the value of the tile itself."""
        enemyNear = Counter(0)
        counterLambda = lambda tile: enemyNear.add(tile.army - 1)
        negativeLambda = lambda tile: tile.player == self.general.player or tile.player == -1
        skipFunc = lambda tile: tile.isCity == True and tile.player == -1
        breadth_first_foreach(self._map, [tile], distance, counterLambda, negativeLambda, skipFunc, noLog = True)
        value = enemyNear.value
        if tile.player != -1 and tile.player != self.general.player:
            # don't include the tiles army itself...
            value = value - (tile.army - 1)
        #logging.info("enemy_army_near for tile {},{} returned {}".format(tile.x, tile.y, value))
        return value

    def count_enemy_territory_near_tile(self, tile, distance = 2):
        enemyNear = Counter(0)


        def counterFunc(tile: Tile):
            tileIsNeutAndNotEnemyTerritory = tile.isNeutral and (tile.visible or self.territories.territoryMap[tile.x][tile.y] != self.targetPlayer)
            if not tileIsNeutAndNotEnemyTerritory and tile.player != self.general.player:
                enemyNear.add(1)

        skipFunc = lambda tile: tile.isObstacle
        breadth_first_foreach(self._map, [tile], distance, counterFunc, skipFunc=skipFunc, noLog=True)
        value = enemyNear.value
        return value

    def count_enemy_tiles_near_tile(self, tile, distance = 2):
        enemyNear = Counter(0)

        def counterFunc(tile: Tile):
            if not tile.isNeutral and tile.player != self.general.player:
                enemyNear.add(1)

        skipFunc = lambda tile: tile.isObstacle
        breadth_first_foreach(self._map, [tile], distance, counterFunc, skipFunc=skipFunc, noLog = True)
        value = enemyNear.value
        return value

    def sum_player_army_near_tile(self, tile, distance = 2, player = None) -> int:
        """
        does not include the army value ON the tile itself.

        @param tile:
        @param distance:
        @param player:
        @return:
        """

        armyNear = self.sum_player_army_near_tiles([tile], distance, player)
        logging.info(f"player_army_near for tile {tile.x},{tile.y} player {player} returned {armyNear}")
        if tile.player == player:
            # don't include the tiles army itself...
            armyNear = armyNear - (tile.army - 1)
        return armyNear

    def sum_player_army_near_tiles(self, tiles: typing.List[Tile], distance = 2, player = None) -> int:
        """
        DOES include the army value ON the tile itself.

        @param tiles:
        @param distance:
        @param player:
        @return:
        """
        if player is None:
            player = self._map.player_index
        armyNear = Counter(0)
        counterLambda = lambda tile: armyNear.add(tile.army - 1)
        negativeLambda = lambda tile: tile.player != player or (tile.isCity and tile.player == -1)
        breadth_first_foreach(self._map, tiles, distance, counterLambda, negativeLambda)
        value = armyNear.value
        return value

    def attempt_predicted_general_exploration(self, negativeTiles):
        def priority_func_explore(nextTile, currentPriorityObject):
            distance, negTileTakenScore, negArmyFound = currentPriorityObject
            tilePlayer = nextTile.player
            if self.territories.territoryMap[nextTile.x][nextTile.y] == self.targetPlayer:
                tilePlayer = self.targetPlayer

            if nextTile not in negativeTiles:
                if nextTile.player == self.general.player:
                    negArmyFound -= nextTile.army
                else:
                    negArmyFound += nextTile.army
                    if not self.is_all_in() and self._map.remainingPlayers < 4:
                        if tilePlayer == -1:
                            negTileTakenScore -= 1
                        elif tilePlayer == self.targetPlayer:
                            negTileTakenScore -= 2

            negArmyFound += 1
            distance += 1
            return distance, negTileTakenScore, negArmyFound

        def goal_func_target_tile(currentTile, priorityObject):
            distance, negTileTakenScore, negArmyFound = priorityObject
            if negArmyFound < 0:
                return True
            return False

        predictionTargetingDepth = 5
        targetPredictionStart = {}
        targetPredictionStart[self.targetPlayerExpectedGeneralLocation] = ((0, 0, self.targetPlayerExpectedGeneralLocation.army + 1), 0)
        logging.info(
            f"   Attempting a {predictionTargetingDepth} turn kill on predicted general location {self.targetPlayerExpectedGeneralLocation.toString()}:")
        killPath = breadth_first_dynamic(self._map, targetPredictionStart, goal_func_target_tile, 0.1, predictionTargetingDepth,
                                   noNeutralCities = True,
                                   negativeTiles = negativeTiles,
                                   searchingPlayer = self.general.player,
                                   priorityFunc = priority_func_explore)

        #killPath = dest_breadth_first_target(self._map, [self.targetPlayerExpectedGeneralLocation], 30, 0.1, predictionTargetingDepth, None, dontEvacCities=False)
        if killPath is not None:
            killPath = killPath.get_reversed()
            self.info(f"UNDISCOVERED PREDICTION: {killPath.toString()}")
            killPath = self.get_value_per_turn_subsegment(killPath, 1.0)
            if killPath.length > 2:
                killPath = killPath.get_subsegment(2)
        else:
            logging.info("UNDISCOVERED PREDICTION KILL FAILED")

        return killPath

    def get_first_path_move(self, path):
        return Move(path.start.tile, path.start.next.tile, path.start.move_half)

    def get_afk_players(self):
        afks = []
        minTilesToNotBeAfk = math.sqrt(self._map.turn)
        for player in self._map.players:
            if player.index == self.general.player:
                continue
            #logging.info("player {}  self._map.turn {} > 50 ({}) and player.tileCount {} < minTilesToNotBeAfk {:.1f} ({}): {}".format(player.index, self._map.turn, self._map.turn > 50, player.tileCount, minTilesToNotBeAfk, player.tileCount < 10, self._map.turn > 50 and player.tileCount < 10))
            if (player.leftGame or (self._map.turn >= 50 and player.tileCount <= minTilesToNotBeAfk)) and not player.dead:
                afks.append(player)
                logging.info(f"player {self._map.usernames[player.index]} ({player.index}) was afk")

        return afks

    def get_optimal_exploration(self, turns, negativeTiles: typing.Set[Tile] = None, valueFunc = None, priorityFunc = None, initFunc = None, skipFunc = None, allowLeafMoves = True, calculateTrimmable = True, minArmy = 0):
        # allow exploration again

        logging.info(f"\n\nAttempting Optimal EXPLORATION (tm) for turns {turns}:\n")
        startTime = time.perf_counter()
        generalPlayer = self._map.players[self.general.player]
        searchingPlayer = self.general.player
        if negativeTiles is None:
            negativeTiles = set()
        else:
            negativeTiles = negativeTiles.copy()
        for tile in negativeTiles:
            logging.info(f"negativeTile: {tile.toString()}")

        distSource = [self.general]
        if self.target_player_gather_path is not None:
            distSource = [self.targetPlayerExpectedGeneralLocation]
        distMap = build_distance_map(self._map, distSource)

        ourArmies = where(self.armyTracker.armies.values(), lambda army: army.player == self.general.player and army.tile.player == self.general.player and army.tile.army > 1)
        ourArmyTiles = [army.tile for army in ourArmies]
        if len(ourArmyTiles) == 0:
            logging.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 5 instead.")
            ourArmyTiles =  where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 5)
        if len(ourArmyTiles) == 0:
            logging.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 2 instead.")
            ourArmyTiles =  where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 2)
        if len(ourArmyTiles) == 0:
            logging.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 1 instead.")
            ourArmyTiles =  where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 1)

        # require any exploration path go through at least one of these tiles.
        def validExplorationTileEvaluater(tile):
            # tile not visible, and enemy territory or near expected general location or bordered by their tile
            if not tile.discovered and (self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer
                                            or distMap[tile.x][tile.y] < 6):
                return True
            return False

        validExplorationTiles = new_tile_matrix(self._map, validExplorationTileEvaluater)

        #skipFunc(next, nextVal). Not sure why this is 0 instead of 1, but 1 breaks it. I guess the 1 is already subtracted
        if not skipFunc:
            def skip_after_out_of_army(nextTile, nextVal):
                wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = nextVal
                if negArmyRemaining >= 0:
                    return True
                if distSoFar > 8 and negValidExplorationCount == 0:
                    return True
                if wastedMoves > 10:
                    return True
                return False
            skipFunc = skip_after_out_of_army

        if not valueFunc:
            def value_priority_army_dist(currentTile, priorityObject):
                wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = priorityObject
                # negative these back to positive
                posPathPrio = 0-pathPriorityDivided
                dist = distSoFar + 0.1
                # pathPriority includes emergence values.
                value = -1000
                #value = 0-(negRevealedCount + enemyTiles * 2 + neutralTiles) / dist
                if negArmyRemaining < 0 and negValidExplorationCount < 0:
                    value = 0-(2 * negValidExplorationCount + negRevealedCount + enemyTiles * 2 + neutralTiles + pathPriority) / dist
                return value, posPathPrio, distSoFar

            valueFunc = value_priority_army_dist

        if not priorityFunc:
            def default_priority_func(nextTile, currentPriorityObject):
                wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = currentPriorityObject
                armyRemaining = 0 - negArmyRemaining
                nextTileSet = tileSetSoFar.copy()
                distSoFar += 1
                # weight tiles closer to the target player higher
                addedPriority = -4 - max(2, distMap[nextTile.x][nextTile.y] / 3)
                #addedPriority = -7 - max(3, distMap[nextTile.x][nextTile.y] / 4)
                if nextTile not in nextTileSet:
                    armyRemaining -= 1
                    releventAdjacents = where(nextTile.adjacents, lambda adjTile: adjTile not in revealedSoFar and adjTile not in tileSetSoFar)
                    revealedCount = count(releventAdjacents, lambda adjTile: not adjTile.discovered)
                    negRevealedCount -= revealedCount
                    if negativeTiles is None or (nextTile not in negativeTiles):
                        if searchingPlayer == nextTile.player:
                            armyRemaining += nextTile.army
                        else:
                            armyRemaining -= nextTile.army
                    if validExplorationTiles[nextTile.x][nextTile.y]:
                        negValidExplorationCount -= 1
                        addedPriority += 3
                    nextTileSet.add(nextTile)
                    # enemytiles or enemyterritory undiscovered tiles
                    if self.targetPlayer != -1 and (nextTile.player == self.targetPlayer or (not nextTile.visible and self.territories.territoryMap[nextTile.x][nextTile.y] == self.targetPlayer)):
                        if nextTile.player == -1:
                            # these are usually 2 or more army since usually after army bonus
                            armyRemaining -= 2
                        #    # points for maybe capping target tiles
                        #    addedPriority += 4
                        #    enemyTiles -= 0.5
                        #    neutralTiles -= 0.5
                        #    # treat this tile as if it is at least 1 cost
                        #else:
                        #    # points for capping target tiles
                        #    addedPriority += 6
                        #    enemyTiles -= 1
                        addedPriority += 8
                        enemyTiles -= 1
                        ## points for locking all nearby enemy tiles down
                        #numEnemyNear = count(nextTile.adjacents, lambda adjTile: adjTile.player == self.targetPlayer)
                        #numEnemyLocked = count(releventAdjacents, lambda adjTile: adjTile.player == self.targetPlayer)
                        ##    for every other nearby enemy tile on the path that we've already included in the path, add some priority
                        #addedPriority += (numEnemyNear - numEnemyLocked) * 12
                    elif nextTile.player == -1:
                        # we'd prefer to be killing enemy tiles, yeah?
                        wastedMoves += 0.2
                        neutralTiles -= 1
                        # points for capping tiles in general
                        addedPriority += 1
                        # points for taking neutrals next to enemy tiles
                        numEnemyNear = count(nextTile.movable, lambda adjTile: adjTile not in revealedSoFar and adjTile.player == self.targetPlayer)
                        if numEnemyNear > 0:
                            addedPriority += 1
                    else: # our tiles and non-target enemy tiles get negatively weighted
                        #addedPriority -= 2
                        # 0.7
                        wastedMoves += 1
                    # points for discovering new tiles
                    addedPriority += revealedCount * 2
                    if self.armyTracker.emergenceLocationMap[self.targetPlayer][nextTile.x][nextTile.y] > 0 and not nextTile.visible:
                        addedPriority += (self.armyTracker.emergenceLocationMap[self.targetPlayer][nextTile.x][nextTile.y] ** 0.5)
                    ## points for revealing tiles in the fog
                    #addedPriority += count(releventAdjacents, lambda adjTile: not adjTile.visible)
                else:
                    wastedMoves += 1

                nextRevealedSet = revealedSoFar.copy()
                for adj in where(nextTile.adjacents, lambda tile: not tile.discovered):
                    nextRevealedSet.add(adj)
                newPathPriority = pathPriority - addedPriority
                #if generalPlayer.tileCount < 46:
                #    logging.info("nextTile {}, newPathPriority / distSoFar {:.2f}, armyRemaining {}, newPathPriority {}, distSoFar {}, len(nextTileSet) {}".format(nextTile.toString(), newPathPriority / distSoFar, armyRemaining, newPathPriority, distSoFar, len(nextTileSet)))
                return wastedMoves, newPathPriority / distSoFar, 0 - armyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, newPathPriority, distSoFar, nextTileSet, nextRevealedSet
            priorityFunc = default_priority_func

        if not initFunc:
            def initial_value_func_default(tile):
                startingSet = set()
                startingSet.add(tile)
                startingAdjSet = set()
                for adj in tile.adjacents:
                    startingAdjSet.add(adj)
                return 0, 10, 0 - tile.army, 0, 0, 0, 0, 0, 0, startingSet, startingAdjSet
            initFunc = initial_value_func_default

        if turns <= 0:
            logging.info("turns <= 0 in optimal_exploration? Setting to 50")
            turns = 50
        remainingTurns = turns
        sortedTiles = sorted(ourArmyTiles, key = lambda tile: 0 - tile.army)
        paths = []

        player = self._map.players[self.general.player]
        logStuff = True

        # BACKPACK THIS EXPANSION! Don't stop at remainingTurns 0... just keep finding paths until out of time, then knapsack them

        # Switch this up to use more tiles at the start, just removing the first tile in each path at a time. Maybe this will let us find more 'maximal' paths?

        while len(sortedTiles) > 0:
            timeUsed = time.perf_counter() - startTime
            # Stages:
            # first 0.1s, use large tiles and shift smaller. (do nothing)
            # second 0.1s, use all tiles (to make sure our small tiles are included)
            # third 0.1s - knapsack optimal stuff outside this loop i guess?
            if timeUsed > 0.03:
                logging.info("timeUsed > 0.03... Breaking loop and knapsacking...")
                break

            #startIdx = max(0, ((cutoffFactor - 1) * len(sortedTiles))//fullCutoff)

            # hack,  see what happens TODO
            #tilesLargerThanAverage = where(generalPlayer.tiles, lambda tile: tile.army > 1)
            #logging.info("Filtered for tilesLargerThanAverage with army > {}, found {} of them".format(tilePercentile[-1].army, len(tilesLargerThanAverage)))
            startDict = {}
            for i, tile in enumerate(sortedTiles):
                # skip tiles we've already used or intentionally ignored
                if tile in negativeTiles:
                    continue
                #self.mark_tile(tile, 10)

                initVal = initFunc(tile)
                #wastedMoves, pathPriorityDivided, armyRemaining, pathPriority, distSoFar, tileSetSoFar
                # 10 because it puts the tile above any other first move tile, so it gets explored at least 1 deep...
                startDict[tile] = (initVal, 0)
            path, pathValue = breadth_first_dynamic_max(
                self._map,
                startDict,
                valueFunc,
                0.2,
                remainingTurns,
                turns,
                noNeutralCities = True,
                negativeTiles = negativeTiles,
                searchingPlayer = self.general.player,
                priorityFunc = priorityFunc,
                useGlobalVisitedSet = True,
                skipFunc = skipFunc,
                logResultValues = logStuff,
                includePathValue = True)


            if path:
                (pathPriorityPerTurn, posPathPrio, distSoFar) = pathValue
                logging.info("Path found for maximizing army usage? Duration {:.3f} path {}".format(time.perf_counter() - startTime, path.toString()))
                node = path.start
                # BYPASSED THIS BECAUSE KNAPSACK...
                # remainingTurns -= path.length
                tilesGrabbed = 0
                visited = set()
                friendlyCityCount = 0
                while node is not None:
                    negativeTiles.add(node.tile)

                    if node.tile.player == self.general.player and (node.tile.isCity or node.tile.isGeneral):
                        friendlyCityCount += 1
                    # this tile is now worth nothing because we already intend to use it ?
                    # negativeTiles.add(node.tile)
                    node = node.next
                sortedTiles.remove(path.start.tile)
                paths.append((friendlyCityCount, pathPriorityPerTurn, path))
            else:
                logging.info("Didn't find a super duper cool optimized EXPLORATION pathy thing. Breaking :(")
                break


        alpha = 75
        minAlpha = 50
        alphaDec = 2
        trimmable = {}

        # build knapsack weights and values
        weights = [pathTuple[2].length for pathTuple in paths]
        values = [int(100 * pathTuple[1]) for pathTuple in paths]
        logging.info("Feeding the following paths into knapsackSolver at turns {}...".format(turns))
        for i, pathTuple in enumerate(paths):
            friendlyCityCount, pathPriorityPerTurn, curPath = pathTuple
            logging.info("{}:  cities {} pathPriorityPerTurn {} length {} path {}".format(i, friendlyCityCount, pathPriorityPerTurn, curPath.length, curPath.toString()))

        totalValue, maxKnapsackedPaths = solve_knapsack(paths, turns, weights, values)
        logging.info("maxKnapsackedPaths value {} length {},".format(totalValue, len(maxKnapsackedPaths)))

        path = None
        if len(maxKnapsackedPaths) > 0:
            maxVal = (-100, -1)

            # Select which of the knapsack paths to move first
            for pathTuple in maxKnapsackedPaths:
                friendlyCityCount, tilesCaptured, curPath = pathTuple

                thisVal = (0 - friendlyCityCount, tilesCaptured / curPath.length)
                if thisVal > maxVal:
                    maxVal = thisVal
                    path = curPath
                    logging.info("no way this works, evaluation [{}], path {}".format('], ['.join(str(x) for x in maxVal), path.toString()))

                #draw other paths darker
                alpha = 150
                minAlpha = 150
                alphaDec = 0
                self.viewInfo.color_path(PathColorer(curPath, 50, 51, 204, alpha, alphaDec, minAlpha))
            logging.info("EXPLORATION PLANNED HOLY SHIT? Duration {:.3f}, path {}".format(time.perf_counter() - startTime, path.toString()))
            #draw maximal path darker
            alpha = 255
            minAlpha = 200
            alphaDec = 0
            self.viewInfo.paths = deque(where(self.viewInfo.paths, lambda pathCol: pathCol.path != path))
            self.viewInfo.color_path(PathColorer(path, 55, 100, 200, alpha, alphaDec, minAlpha))
        else:
            logging.info("No EXPLORATION plan.... :( Duration {:.3f},".format(time.perf_counter() - startTime))

        return path





    # TODO
    def explore_target_player_undiscovered(self, negativeTiles, targetArmy = 1, force = False) -> typing.Union[None, Path]:
        #if self._map.turn < 100 or self.targetPlayer == -1 or self._map.generals[self.targetPlayer] is not None:
        if negativeTiles:
            negativeTiles = negativeTiles.copy()
        if self._map.turn < 50 or self.targetPlayer == -1:
            return None

        turnInCycle = self.timings.get_turn_in_cycle(self._map.turn)
        exploringUnknown = self._map.generals[self.targetPlayer] is None

        if not self.is_all_in() and self.explored_this_turn:
            logging.info("(skipping new exploration because already explored this turn)")
            return None

        if self.is_all_in():
            logging.info("- - - - - ALL-IN, EXPLORE_TARGET_PLAYER_UNDISCOVERED (OLD) :( - - - - -")

            killPath = self.attempt_predicted_general_exploration(negativeTiles)
            if killPath is not None:
                self.finishingExploration = True
                self.viewInfo.addAdditionalInfoLine(
                    "finishExp=True in explore_target_player_undiscovered because found attempt_predicted_general_exploration path")
                return killPath

            path = self.explore_target_player_undiscovered_short(targetArmy, negativeTiles)
            if path is not None:
                return path

        if self.winning_on_army(byRatio=1.15):
            logging.info("- - - - - EXPLORE_TARGET_PLAYER_UNDISCOVERED (NEW) - - - - -")
            self.explored_this_turn = True
            turns = self.timings.cycleTurns - turnInCycle
            if self.is_all_in():
                logging.info("Forcing explore turns to 12 because self.is_all_in()")
                turns = 12
            elif turns < 6:
                logging.info("Forcing explore turns to minimum of 5, was {}".format(turns))
                turns = 5
            elif turnInCycle < 6 and exploringUnknown:
                logging.info("Forcing explore turns to minimum of 6, was {}".format(turns))
                turns = 6

            if self._map.turn < 100:
                return None

            # this thing isn't working right...?
            path = self.get_optimal_exploration(turns, negativeTiles)
            if path:
                logging.info("Oh no way, explore found a path lol? {}".format(path.toString()))
                tilesRevealed = set()
                score = 0
                node = path.start
                while node is not None:
                    if not node.tile.discovered and self.armyTracker.emergenceLocationMap[self.targetPlayer][node.tile.x][node.tile.y] > 0:
                        score += self.armyTracker.emergenceLocationMap[self.targetPlayer][node.tile.x][node.tile.y] ** 0.5
                    for adj in node.tile.adjacents:
                        if not adj.discovered:
                            tilesRevealed.add(adj)
                    node = node.next
                revealedPerMove = len(tilesRevealed) / path.length
                scorePerMove = score / path.length
                self.viewInfo.addAdditionalInfoLine("tilesRevealed {} ({:.2f}), Score {} ({:.2f}), path.length {}".format(len(tilesRevealed), revealedPerMove, score, scorePerMove, path.length))
                if ((revealedPerMove > 0.5 and scorePerMove > 4)
                            or (revealedPerMove > 0.8 and scorePerMove > 1)
                            or revealedPerMove > 1.5):
                    if path.length > 2:
                        path = path.get_subsegment(2)

                    self.finishingExploration = True
                    self.viewInfo.addAdditionalInfoLine(
                        "finishExp=True in explore_target_player_undiscovered because found get_optimal_exploration path")
                    return path
                else:
                    logging.info("path wasn't good enough, discarding")

        return None

        ## don't explore to 1 army from inside our own territory
        ##if not self.timings.in_gather_split(self._map.turn):
        #if negativeTiles is None:
        #    negativeTiles = set()
        #negativeTiles = negativeTiles.copy()
        #for tile in genPlayer.tiles:
        #    if self.territories.territoryMap[tile.x][tile.y] == self.general.player:
        #        logging.info("explore: adding tile {} to negativeTiles for lowArmy search".format(tile.toString()))
        #        negativeTiles.add(tile)

        #path = breadth_first_dynamic(self._map,
        #                            enemyUndiscBordered,
        #                            goal_func_short,
        #                            0.1,
        #                            3,
        #                            noNeutralCities = True,
        #                            negativeTiles = negativeTiles,
        #                            searchingPlayer = self.general.player,
        #                            priorityFunc = priority_func_non_all_in)
        #if path is not None:
        #    path = path.get_reversed()
        #    self.info("UD SMALL: depth {} bfd kill (pre-prune) \n{}".format(path.length, path.toString()))



    def get_median_tile_value(self, percentagePoint = 50):
        tiles = [tile for tile in self._map.players[self.general.player].tiles]
        tiles = sorted(tiles, key = lambda tile: tile.army)
        tileIdx = max(0, len(tiles)*percentagePoint//100 - 1)
        if len(tiles) > tileIdx:
            return tiles[tileIdx].army
        else:
            logging.info("whoah, dude cmon,Z ZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzz")
            logging.info("hit that weird tileIdx bug.")
            return 0


    def build_mst(self, startTiles, maxTime = 0.1, maxDepth = 30, negativeTiles: typing.Set[Tile] = None, avoidTiles = None, priorityFunc = None):
        LOG_TIME = False
        self.leafValueGrid = [[None for x in range(self._map.rows)] for y in range(self._map.cols)]
        searchingPlayer = self._map.player_index
        frontier = PriorityQueue()
        visitedBack = [[None for x in range(self._map.rows)] for y in range(self._map.cols)]

        if isinstance(startTiles, dict):
            for tile in startTiles.keys():
                if isinstance(startTiles[tile], int):
                    distance = startTiles[tile]
                    frontier.put((distance, (0, 0, distance, tile.x, tile.y), tile, tile))
                else:
                    (startPriorityObject, distance) = startTiles[tile]
                    startVal = startPriorityObject
                    frontier.put((distance, startVal, tile, tile))
        else:
            startTiles = set(startTiles)
            if priorityFunc is not None:
                raise AssertionError("You MUST use a dict of starttiles if not using the default priorityFunc")
            for tile in startTiles:
                negEnemyCount = 0
                if tile.player == self.targetPlayer:
                    negEnemyCount = -1
                frontier.put((0, (0, 0, 0, tile.x, tile.y), tile, tile))

        if not priorityFunc:
            def default_priority_func(nextTile, currentPriorityObject):
                (prio, negArmy, dist, xSum, ySum) = currentPriorityObject
                nextArmy = 0 - negArmy - 1
                if negativeTiles is None or nextTile not in negativeTiles:
                    if searchingPlayer == nextTile.player:
                        nextArmy += nextTile.army
                    else:
                        nextArmy -= nextTile.army
                dist += 1
                return 0 - nextArmy / dist, 0 - nextArmy, dist, xSum + nextTile.x, ySum + nextTile.y
            priorityFunc = default_priority_func
                # if newDist not in visited[next.x][next.y] or visited[next.x][next.y][newDist][0] < nextArmy:
                #     visited[next.x][next.y][newDist] = (nextArmy, current)



        # sort on distance, then army, then x and y (to stop the paths from shuffling randomly and looking annoying)
        start = time.perf_counter()
            #frontier.put((0, startArmy, tile.x, tile.y, tile, None, 0))
        depthEvaluated = 0
        while not frontier.empty():
            (dist, curPriorityVal, current, cameFrom) = frontier.get()
            x = current.x
            y = current.y
            if visitedBack[x][y] is not None:
                continue
            if avoidTiles is not None and current in avoidTiles:
                continue
            if current.isMountain or (not current.discovered and current.isNotPathable):
                continue
            if current.isCity and current.player != searchingPlayer and not current in startTiles:
                continue
            visitedBack[x][y] = cameFrom

            if dist > depthEvaluated:
                depthEvaluated = dist
            if dist <= maxDepth:
                dist += 1
                for next in current.movable: #new spots to try
                    nextPriorityVal = priorityFunc(next, curPriorityVal)
                    frontier.put((dist, nextPriorityVal, next, current))
        if LOG_TIME:
            logging.info("BUILD-MST DURATION: {:.3f}, DEPTH: {}".format(time.perf_counter() - start, depthEvaluated))

        result = self.build_mst_rebuild(startTiles, visitedBack, self._map.player_index)

        # hopefully this starts showing stuff?
        dictStart = {}
        if isinstance(startTiles, dict):
            for tile in startTiles.keys():
                dist = 0
                startVal = (0, 0, 0, tile.x, tile.y)
                dictStart[tile] = (startVal, dist)
        else:
            for tile in startTiles:
                dist = 0
                startVal = (0, 0, 0, tile.x, tile.y)
                dictStart[tile] = (startVal, dist)
        return result


    def get_prune_point(self, nodeMap, leafNode):
        logging.info("Getting prune point leafNode {}".format(leafNode.tile.toString()))
        totalVal = leafNode.value
        avgVal = leafNode.value
        newAvg = leafNode.value
        length = 1
        node = leafNode
        while node.fromTile in nodeMap and newAvg <= avgVal:
            avgVal = newAvg
            length += 1
            fromNode = nodeMap[node.fromTile]
            totalVal = fromNode.value
            newAvg = totalVal / length
            logging.info("   totalVal {} fromNode.value {} node.value {} newAvg {:.2f}".format(totalVal, fromNode.value, node.value, newAvg))
            node = fromNode
        if newAvg <= avgVal:
            logging.info("   still decreasing, totalVal {} newAvg {:.2f}".format(totalVal, newAvg))
            # fromTile was none above, but we were still decreasing. Whole thing is a prune...
            return newAvg, length
        else:
            return avgVal, length - 1


    def build_mst_rebuild(self, startTiles, fromMap, searchingPlayer):
        results = []
        for tile in startTiles:
            gather = self.get_gather(tile, None, fromMap, 0, searchingPlayer)
            if gather.tile.player == searchingPlayer:
                gather.value -= gather.tile.army
            else:
                gather.value += gather.tile.army

            results.append(gather)
        return results

    def get_gather(self, tile, fromTile, fromMap, turn, searchingPlayer):
        gatherTotal = tile.army
        turnTotal = 1
        if tile.player != searchingPlayer:
            gatherTotal = 0 - tile.army
        gatherTotal -= 1
        thisNode = TreeNode(tile, fromTile, turn)
        if tile.player == -1:
            thisNode.neutrals = 1
        for move in tile.movable:
            # logging.info("evaluating {},{}".format(move.x, move.y))
            if move == fromTile:
                # logging.info("move == fromTile  |  {},{}".format(move.x, move.y))
                continue
            if fromMap[move.x][move.y] != tile:
                # logging.info("fromMap[move.x][move.y] != tile  |  {},{}".format(move.x, move.y))
                continue
            gather = self.get_gather(move, tile, fromMap, turn + 1, searchingPlayer)
            if gather.value > 0:
                gatherTotal += gather.value
                turnTotal += gather.gatherTurns
                thisNode.children.append(gather)
                thisNode.neutrals += gather.neutrals

        thisNode.value = gatherTotal
        thisNode.gatherTurns = turnTotal
        # only de-prioritize cities when they are the leaf
        if thisNode.tile.isCity and 0 == len(thisNode.children):
            thisNode.value -= 10
        # logging.info("{},{} ({}  {})".format(thisNode.tile.x, thisNode.tile.y, thisNode.value, thisNode.gatherTurns))
        return thisNode

    def get_tree_move_non_city_leaf_count(self, gathers):
        # fuck it, do it recursively i'm too tired for this
        count = 0
        for gather in gathers:
            foundCity, countNonCityLeaves = self._get_tree_move_non_city_leaf_count_recurse(gather)
            count += countNonCityLeaves
        return count

    def _get_tree_move_non_city_leaf_count_recurse(self, gather):
        count = 0
        thisNodeFoundCity = False
        for child in gather.children:
            foundCity, countNonCityLeaves = self._get_tree_move_non_city_leaf_count_recurse(child)
            logging.info("child {} foundCity {} countNonCityLeaves {}".format(child.tile.toString(), foundCity, countNonCityLeaves))
            count += countNonCityLeaves
            if foundCity:
                thisNodeFoundCity = True
        if gather.tile.player == self.general.player and (gather.tile.isCity or gather.tile.isGeneral):
            thisNodeFoundCity = True
        if not thisNodeFoundCity:
            count += 1
        return thisNodeFoundCity, count

    def get_tree_move_default(
            self,
            gathers: typing.List[TreeNode],
            priorityFunc = None,
            valueFunc = None
    ) -> Move | None:
        """
        By default, gathers cities last.
        Gathers furthest tiles first.

        @param gathers:
        @param priorityFunc:
            def default_priority_func(nextTile, currentPriorityObject):
                cityCount = distFromPlayArea = negArmy = negUnfriendlyTileCount = 0
                if currentPriorityObject is not None:
                    (cityCount, negUnfriendlyTileCount, distFromPlayArea, negArmy) = currentPriorityObject
        @param valueFunc:
        @return:
        """

        nodeLookup = {}


        def addToNodeLookupFunc(node: TreeNode):
            nodeLookup[node.tile] = node

        GatherUtils.iterate_tree_nodes(gathers, addToNodeLookupFunc)

        # nonCityLeafCount = self.get_tree_move_non_city_leaf_count(gathers)
        # logging.info("G E T T R E E M O V E D E F A U L T ! ! ! nonCityLeafCount {}".format(nonCityLeafCount))
        if priorityFunc is None:
            # default priority func, gathers based on cityCount then distance from general
            def default_priority_func(nextTile, currentPriorityObject):
                cityCount = distFromPlayArea = negArmy = negUnfriendlyTileCount = 0
                # i don't think this does anything...?
                if currentPriorityObject is not None:
                    (cityCount, negUnfriendlyTileCount, distFromPlayArea, negArmy) = currentPriorityObject
                    negArmy += 1
                if nextTile.player == self.general.player:
                    if nextTile.isGeneral or nextTile.isCity:
                        cityCount += 1
                else:
                    negUnfriendlyTileCount -= 1

                distFromPlayArea = self.shortest_path_to_target_player_distances[nextTile.x][nextTile.y]

                if nextTile.player == self.general.player:
                    negArmy -= nextTile.army
                else:
                    negArmy += nextTile.army
                #heuristicVal = negArmy / distFromPlayArea
                return cityCount, negUnfriendlyTileCount, distFromPlayArea, negArmy

            # use 0 citycount to gather cities as needed instead of last. Should prevent the never-gathering-cities behavior
            # player = self._map.players[self.general.player]
            # def default_high_cities_func(nextTile, currentPriorityObject):
            #     cityCount = distFromPlayArea = negArmy = negUnfriendlyTileCount = 0
            #     if currentPriorityObject is not None:
            #         (cityCount, negUnfriendlyTileCount, distFromPlayArea, negArmy) = currentPriorityObject
            #         negArmy += 1
            #
            #     if nextTile.player != self.general.player:
            #         negUnfriendlyTileCount -= 1
            #
            #     distFromPlayArea = 0 - enemyDistanceMap[nextTile.x][nextTile.y]
            #     if nextTile.player == self.general.player:
            #         negArmy -= nextTile.army
            #     else:
            #         negArmy += nextTile.army
            #     return cityCount, negUnfriendlyTileCount, distFromPlayArea, negArmy

            # shitty hack to stop dropping city gathers when gathers are interrupted. Really, timings should store that info and delaying a gather should still complete the critical tiles on the primary gather
            # if nonCityLeafCount < 3 * player.cityCount:
            #     logging.info("Using default_high_cities_func for gather prio. player.cityCount {} > 4 or nonCityLeafCount {} < 4".format(player.cityCount, nonCityLeafCount))
            #     priorityFunc = default_high_cities_func
            # else:
            priorityFunc = default_priority_func

        if valueFunc is None:
            # default value func, gathers based on cityCount then distance from general
            def default_value_func(currentTile, currentPriorityObject):
                cityCount = distFromPlayArea = negArmy = negUnfriendlyTileCount = 0
                # Stupid hack because of the MST gathers leaving bad moves on the leaves....
                isGoodMove = 0
                if currentTile.player == self.general.player and currentTile.army > 1:
                    isGoodMove = 1
                if currentPriorityObject is not None:
                    (cityCount, negUnfriendlyTileCount, distFromPlayArea, negArmy) = currentPriorityObject

                # hack to not gather cities themselves until last, but still gather other leaves to cities
                if not (currentTile.isCity or currentTile.isGeneral):
                    cityCount = 0

                # distFromPlayArea can be INF in some cases
                distFromPlayArea = min(1000, distFromPlayArea)
                node: TreeNode = nodeLookup[currentTile]
                # gather the furthest from play area by
                # because these are all negated in the priorityFunc we need to negate them here for making them 'positive' weights for value
                return 0 - cityCount, node.value / max(1, node.trunkDistance), 0 - negArmy
                return isGoodMove, 0 - cityCount, 0 - negUnfriendlyTileCount, (0 - negArmy) * distFromPlayArea, 0 - negArmy  #492
                return isGoodMove, 0 - cityCount, 0 - negUnfriendlyTileCount, distFromPlayArea, 0 - negArmy  #492
                return isGoodMove, 0 - cityCount, 0 - negUnfriendlyTileCount, node.trunkDistance, 0 - negArmy  #493
                return isGoodMove, not cityCount > 0, 0 - negUnfriendlyTileCount, node.trunkDistance // (cityCount + 1), 0 - negArmy  #493
                return isGoodMove, not cityCount > 0, 0 - negUnfriendlyTileCount, node.trunkDistance, 0 - negArmy  #488
                return isGoodMove, not cityCount > 0, 0 - negUnfriendlyTileCount, (0 - negArmy) * (node.trunkDistance - 10), 0 - negArmy  #492
                return isGoodMove, not cityCount > 0, 0 - negUnfriendlyTileCount, (0 - negArmy) * distFromPlayArea, 0 - negArmy  #490
                return isGoodMove, not cityCount > 0, 0 - negUnfriendlyTileCount, distFromPlayArea, 0 - negArmy  #484
                return isGoodMove, not cityCount > 0, 0 - negUnfriendlyTileCount, (0 - negArmy) * node.trunkDistance, 0 - negArmy  #492
                return isGoodMove, not cityCount > 0, 0 - negUnfriendlyTileCount, (0 - negArmy) * (node.trunkDistance - 5), 0 - negArmy  #492
                #return (0 - cityCount, 0 - distFromPlayArea, 0 - negArmy)
            valueFunc = default_value_func

        return GatherUtils.get_tree_move(gathers, priorityFunc, valueFunc)

    def get_gather_move(self, gathers, parent, minGatherAmount = 0, pruneThreshold = None, preferNeutral = True, allowNonKill = False, leaveCitiesLast = True):
        #logging.info("G A T H E R I N G :  minGatherAmount {}, pruneThreshold {}, preferNeutral {}, allowNonKill {}".format(minGatherAmount, pruneThreshold, preferNeutral, allowNonKill))
        if pruneThreshold is None:
            player = self._map.players[self.general.player]
            pruneThreshPercent = 45
            pruneThreshold = self.get_median_tile_value(pruneThreshPercent) - 1
            logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(20, self.get_median_tile_value(20)))
            logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(35, self.get_median_tile_value(35)))
            logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(50, self.get_median_tile_value(50)))
            #logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(65, self.get_median_tile_value(65)))
            logging.info("~!~!~!~!~!~!~ MEDIAN {}: {}".format(75, self.get_median_tile_value(75)))
            logging.info("~!~!~!~!~!~!~ pruneThreshold {}: {}".format(pruneThreshPercent, pruneThreshold))

            pruneThreshold = math.floor((player.standingArmy - self.general.army) / player.tileCount)
            logging.info("~!~!~!~!~!~!~ pruneThreshold via average {}%: {}".format(pruneThreshPercent, pruneThreshold))
        logging.info("G A T H E R I N G :  minGatherAmount {}, pruneThreshold {}, preferNeutral {}, allowNonKill {}".format(minGatherAmount, pruneThreshold, preferNeutral, allowNonKill))
        start = time.perf_counter()
        logging.info("Gathering :)")
        move = self._get_gather_move_int_v2(gathers, parent, minGatherAmount, pruneThreshold, preferNeutral, allowNonKill = allowNonKill, leaveCitiesLast = leaveCitiesLast)
        if move is None and pruneThreshold > 0:
            newThreshold = max(0, self.get_median_tile_value(25) - 2)
            logging.info("\nEEEEEEEEEEEEEEEEEEEEEEEE\nEEEEEEEEE\nEE\nNo move found for pruneThreshold {}, retrying with {}".format(pruneThreshold, newThreshold))
            move = self._get_gather_move_int_v2(gathers, parent, minGatherAmount, newThreshold, preferNeutral, allowNonKill = allowNonKill, leaveCitiesLast = leaveCitiesLast)
        if move is None:
            logging.info("\nNo move found......... :(")
            newThreshold = 0
            logging.info("\nEEEEEEEEEEEEEEEEEEEEEEEE\nEEEEEEEEE\nEE\nNo move found for pruneThreshold {}, retrying with {}".format(pruneThreshold, newThreshold))
            move = self._get_gather_move_int_v2(gathers, parent, minGatherAmount, newThreshold, preferNeutral, allowNonKill = allowNonKill, leaveCitiesLast = leaveCitiesLast)
        if move is None:
            logging.info("\nNo move found......... :(")
        logging.info("GATHER MOVE DURATION: {:.2f}".format(time.perf_counter() - start))
        return move


    def _get_gather_move_int_v2(self, gathers, parent, minGatherAmount = 0, pruneThreshold = 0, preferNeutral = False, allowNonKill = False, leaveCitiesLast = True):
        LOG_STUFF = False
        pX = "  "
        pY = "  "
        minGatherAmount = 0
        if parent is not None:
            pX = parent.tile.x
            pY = parent.tile.y
        move = None
        maxGather = None
        for gather in gathers:
            curMove = None
            gatherWorthwhile = is_gather_worthwhile(gather, parent)
            if parent is None or gatherWorthwhile:
                curMove = self._get_gather_move_int_v2(gather.children, gather, minGatherAmount, pruneThreshold, preferNeutral, allowNonKill, leaveCitiesLast = leaveCitiesLast)
                #update this gathers value with its changed childrens values
                newVal = 0
                newTurns = 1
                if parent is not None:
                    newVal = gather.tile.army - 1
                    if gather.tile.player != self.general.player:
                        newVal = -1 - gather.tile.army
                for child in gather.children:
                    newVal += child.value
                    newTurns += child.gatherTurns
                if LOG_STUFF:
                    logging.info("{},{} <- [update] Gather {},{} updated value {}->{} and turns {}->{}".format(pX, pY, gather.tile.x, gather.tile.y, gather.value, newVal, gather.gatherTurns, newTurns))
                gather.value = newVal
                gather.gatherTurns = newTurns
            if gather.value > 0:
                self.leafValueGrid[gather.tile.x][gather.tile.y] = gather.value
            else:
                if LOG_STUFF:
                    logging.info("{},{} <- [!worth] Gather {},{} val-turns {}-{} was new maxGather".format(pX, pY, gather.tile.x, gather.tile.y, gather.value, gather.gatherTurns))
            #if maxGather is None or (gather.value - gather.tile.army) / gather.gatherTurns > (maxGather.value - maxGather.tile.army) / maxGather.gatherTurns:
            if gather.value / gather.gatherTurns > pruneThreshold and gather.value >= minGatherAmount:
                if gather == compare_gathers(maxGather, gather, preferNeutral, leaveCitiesLast = leaveCitiesLast):
                    if LOG_STUFF:
                        logging.info("{},{} <- [max!] Gather {},{} val-turns {}-{} was new maxGather".format(pX, pY, gather.tile.x, gather.tile.y, gather.value, gather.gatherTurns))
                    maxGather = gather
                    if self.is_move_safe_valid(curMove, allowNonKill = allowNonKill):
                        if LOG_STUFF:
                            logging.info("{},{} <- [max!] Gather {},{} val-turns {}-{} was new maxGather".format(pX, pY, gather.tile.x, gather.tile.y, gather.value, gather.gatherTurns))
                        move = curMove
                    elif curMove is not None:
                        if LOG_STUFF:
                            logging.info("{},{} <- [inval] Gather MOVE {},{} <- {},{} returned by gather {},{} wasn't safe or wasn't valid".format(pX, pY, curMove.dest.x, curMove.dest.y, curMove.source.x, curMove.source.y, gather.tile.x, gather.tile.y))
                    else:
                        if LOG_STUFF and False:
                            logging.info("{},{} <- [     ] Gather {},{} didn't return any child moves".format(pX, pY, gather.tile.x, gather.tile.y))
                else:
                    if LOG_STUFF:
                        logging.info("{},{} <- [worse] Gather {},{} val-turns {}-{} was worse than maxGather {},{} val-turns {}-{}".format(pX, pY, gather.tile.x, gather.tile.y, gather.value, gather.gatherTurns, maxGather.tile.x, maxGather.tile.y, maxGather.value, maxGather.gatherTurns))
            else:
                if LOG_STUFF:
                    logging.info("{},{} <- [prune] Gather {},{} val-turns {}-{} did not meet the prune threshold or min gather amount.".format(pX, pY, gather.tile.x, gather.tile.y, gather.value, gather.gatherTurns))


        if move is not None:
            return move
        if maxGather is not None:
            if LOG_STUFF:
                logging.info("{},{} <- maxGather was {},{} but no move. We should be considering making this as a move.".format(pX, pY, maxGather.tile.x, maxGather.tile.y))
            if parent is not None:
                if maxGather.tile.army <= 1 or maxGather.tile.player != self._map.player_index:
                    if LOG_STUFF:
                        logging.info("{},{} <- WTF tried to move {},{} with 1 or less army :v".format(pX, pY, maxGather.tile.x, maxGather.tile.y))
                elif maxGather.value > 0:
                    if LOG_STUFF:
                        logging.info("{},{} <- Returning {},{} -> {},{}".format(pX, pY, maxGather.tile.x, maxGather.tile.y, pX, pY))
                    #parent.children.remove(maxGather)
                    maxGather.children = []
                    maxGather.value = maxGather.tile.army - 1
                    maxGather.gatherTurns = 1
                    self.leafValueGrid[maxGather.tile.x][maxGather.tile.y] = maxGather.value
                    return Move(maxGather.tile, parent.tile)
        if LOG_STUFF:
            logging.info("{},{} <- FUCK! NO POSITIVE GATHER MOVE FOUND".format(pX, pY))
        return None

    def _get_gather_move_int(self, gathers, parent, minGatherAmount = 0, pruneThreshold = 0, preferNeutral = False, allowNonKill = False):
        move = None
        maxGather = None
        for gather in gathers:
            if gather.value <= 0:
                logging.info("gather {},{} worthless".format(gather.tile.x, gather.tile.y))
                # then just prune it and don't log it?
                continue
            #if maxGather is None or (gather.value - gather.tile.army) / gather.gatherTurns > (maxGather.value - maxGather.tile.army) / maxGather.gatherTurns:
            if gather.value / gather.gatherTurns > pruneThreshold:
                if gather.value >= minGatherAmount:
                    if gather == compare_gathers(maxGather, gather, preferNeutral):
                        maxGather = gather
                    else:
                        logging.info("[non] gather {},{} was worse than maxGather in compare_gathers, value/gather.gatherTurns {}/{} ({})".format(gather.tile.x, gather.tile.y, gather.value, gather.gatherTurns, (gather.value/gather.gatherTurns)))
                else:
                    logging.info("[low] gather {},{} value {} was less than minGatherAmount {}".format(gather.tile.x, gather.tile.y, gather.value, minGatherAmount))
            else:
                logging.info("[prn] gather {},{} value/gather.gatherTurns {}/{} ({}) was less than pruneThreshold {}".format(gather.tile.x, gather.tile.y, gather.value, gather.gatherTurns, (gather.value/gather.gatherTurns), pruneThreshold))

        # if maxGather is not None and (parent is None or maxGather.value / maxGather.gatherTurns > parent.value / parent.gatherTurns):
        if maxGather is not None:
            logging.info("}}max{{ gather {},{} was maxGather! value/gather.gatherTurns {}/{} ({}) pruneThreshold {}".format(maxGather.tile.x, maxGather.tile.y, maxGather.value, maxGather.gatherTurns, (maxGather.value/maxGather.gatherTurns), pruneThreshold))
            gatherWorthwhile = is_gather_worthwhile(maxGather, parent)
            if parent is None or gatherWorthwhile:
                # minGatherAmount = 1 is a hack because until the full gather is planned out in advance,
                # we don't know what will be pruned and can't keep this number evaluated correctly recursively.
                # So we only use it to pick an initial gather branch, and then don't prune any further than the trunk with it for now.
                minGatherAmount = 1
                move = self._get_gather_move_int(maxGather.children, maxGather, minGatherAmount, pruneThreshold, preferNeutral, allowNonKill)
                if self.is_move_safe_valid(move, allowNonKill = allowNonKill):
                    logging.info("Returning child move {},{} -> {},{}".format(move.source.x, move.source.y, move.dest.x, move.dest.y))
                    return move
            else:
                logging.info("Cut {},{} because not gatherWorthwhile or no parent".format(maxGather.tile.x, maxGather.tile.y))
            if parent is not None:
                if maxGather.tile.army <= 1 or maxGather.tile.player != self._map.player_index:
                    logging.info("WTF tried to move {},{} with 1 or less army :v".format(maxGather.tile.x, maxGather.tile.y))
                elif maxGather.value > 0:
                    logging.info("Returning {},{} -> {},{}".format(maxGather.tile.x, maxGather.tile.y, parent.tile.x, parent.tile.y))
                    parent.children.remove(maxGather)
                    return Move(maxGather.tile, parent.tile)
            logging.info("FUCK! NO POSITIVE, LEGAL, SAFE GATHER MOVE FOUND at gather {},{} value {} gatherTurns {}".format(maxGather.tile.x, maxGather.tile.y, maxGather.value, maxGather.gatherTurns))
        else:
            logging.info("FUCK! NO POSITIVE GATHER MOVE FOUND, no maxGather")

        return None

    def get_threat_killer_move(self, threat: ThreatObj, searchTurns, negativeTiles):
        """
        Attempt to find a threat kill path / move that kills a specific threat. TODO can this largely be replaced by defense backpack gather...?
        @param threat:
        @param searchTurns:
        @param negativeTiles:
        @return:
        """
        killTiles = [threat.path.start.next.tile, threat.path.start.tile]
        armyAmount = threat.threatValue + 1
        saveTile = None
        largestTile = None
        source = None
        for threatSource in killTiles:
            for tile in threatSource.movable:
                if tile.player == self._map.player_index and tile not in threat.path.tileSet:
                    if tile.army > 1 and (largestTile is None or tile.army > largestTile.army):
                        largestTile = tile
                        source = threatSource
        threatModifier = 3
        if (self._map.turn - 1) in self.history.attempted_threat_kills:
            logging.info("We attempted a threatKill last turn, using 1 instead of 3 as threatKill modifier.")
            threatModifier = 1

        if largestTile is not None:
            if threat.threatValue - largestTile.army + threatModifier < 0:
                logging.info("reeeeeeeeeeeeeeeee\nFUCK YES KILLING THREAT TILE {},{}".format(largestTile.x, largestTile.y))
                saveTile = largestTile
            else:
                # else see if we can save after killing threat tile
                negativeTilesIncludingThreat = set()
                negativeTilesIncludingThreat.add(largestTile)
                dict = {}
                dict[self.general] = (0, threat.threatValue, 0)
                for tile in negativeTiles:
                    negativeTilesIncludingThreat.add(tile)
                for tile in threat.path.tileSet:
                    negativeTilesIncludingThreat.add(tile)
                if threat.saveTile is not None:
                    dict[threat.saveTile] = (0, threat.threatValue, -0.5)
                    self.viewInfo.add_targeted_tile(threat.saveTile, TargetStyle.GREEN)
                    logging.info("(killthreat) dict[threat.saveTile] = (0, {})  -- threat.saveTile {},{}".format(threat.saveTile.army, threat.saveTile.x, threat.saveTile.y))
                savePathSearchModifier = 2
                if largestTile in threat.path.start.tile.movable:
                    logging.info("largestTile was adjacent to the real threat tile, so savepath needs to be 1 turn shorter for this to be safe")
                    # then we have to be prepared for this move to fail the first turn. Look for savePath - 1
                    savePathSearchModifier = 3
                threatKillSearchAmount = armyAmount + threatModifier - largestTile.army #- 1
                postThreatKillSearchTurns = searchTurns - savePathSearchModifier
                logging.info("Searching post-threatKill path with threatKillSearchAmount {} for postThreatKillSearchTurns {}".format(threatKillSearchAmount, postThreatKillSearchTurns))
                bestPath = dest_breadth_first_target(self._map, dict, threatKillSearchAmount, 0.1, postThreatKillSearchTurns, negativeTilesIncludingThreat, searchingPlayer = self.general.player, ignoreGoalArmy=True)
                if bestPath is not None and bestPath.length > 0:
                    self.viewInfo.color_path(PathColorer(bestPath, 250, 250, 250, 200, 12, 100))
                    if largestTile.army > 7 or threat.threatValue <= largestTile.army:
                        logging.info("reeeeeeeeeeeeeeeee\nkilling threat tile with {},{}, we still have time for defense after with path {}:".format(largestTile.x, largestTile.y, bestPath.toString()))
                        saveTile = largestTile
                    else:
                        logging.info("threatKill {},{} -> {},{} not worthwhile?".format(largestTile.x, largestTile.y, source.x, source.y))
                else:
                    logging.info("largestTile {} couldn't save us because no bestPath save path found post-kill".format(largestTile.toString()))


        if saveTile is not None:
            self.history.attempted_threat_kills.add(self._map.turn)
            return Move(saveTile, source)
        return None

    def get_cities_bordered_by_enemy(self, enemyTileCount = 1):
        player = self._map.players[self.general.player]
        cities = where(player.cities, lambda x: x.player == player.index and count(x.adjacents, lambda y: y.player >= 0 and y.player != player.index) >= enemyTileCount)
        return cities



    def a_star_search(self, start, goal, heurFunc, costFunc, goalFunc):
        frontier = PriorityQueue()
        frontier.put(start, 0)
        came_from = {}
        cost_so_far = {}
        came_from[start] = None
        cost_so_far[start] = 0

        while not frontier.empty():
            current = frontier.get()
            x = current.x
            y = current.y
            if current == goal:
                break
            for i in [[x - 1,y],[x + 1,y],[x,y - 1],[x,y + 1]]: #new spots to try
                if i[0] < 0 or i[1] < 0 or i[0] >= self._map.cols or i[1] >= self._map.rows:
                    continue
                next = self._map.grid[i[1]][i[0]]
                if next.isMountain or (not next.discovered and next.isNotPathable):
                    continue
                #new_cost = cost_so_far[current] + graph.cost(current, next)
                new_cost = cost_so_far[current] + costFunc(self, current, next)
                if next not in cost_so_far or new_cost < cost_so_far[next]:
                    cost_so_far[next] = new_cost
                    priority = new_cost + heurFunc(self, goal, next)
                    frontier.put(priority, next)
                    came_from[next] = current

        return came_from, cost_so_far

    def should_proactively_take_cities(self):
        # never take cities proactively in FFA when we're engaging a player
        #if self.targetPlayer != -1 and self._map.remainingPlayers > 2:
        #    return False

        if self.defendEconomy:
            logging.info("No proactive cities because defending economy :)")
            return False

        cityLeadWeight = 0
        dist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation)
        if self.targetPlayer != -1:
            opp = self._map.players[self.targetPlayer]
            me = self._map.players[self.general.player]
            # don't keep taking cities unless our lead is really huge
            # need 100 army lead for each additional city we want to take
            cityLeadWeight = (me.cityCount - opp.cityCount) * 70

        knowsWhereEnemyGenIs = self.targetPlayer != -1 and self._map.generals[self.targetPlayer] is not None
        if knowsWhereEnemyGenIs and dist < 18:
            logging.info("Not proactively taking neutral cities because we know enemy general location and map distance isn't incredibly short")
            return False
        player = self._map.players[self.general.player]
        targetPlayer = None
        if self.targetPlayer != -1:
            targetPlayer = self._map.players[self.targetPlayer]
        safeOnStandingArmy = targetPlayer is None or player.standingArmy > targetPlayer.standingArmy * 0.9
        if (safeOnStandingArmy and ((player.standingArmy > cityLeadWeight and (self.target_player_gather_path is None or dist > 24))
                    or (player.standingArmy > 30 + cityLeadWeight and (self.target_player_gather_path is None or dist > 22))
                    or (player.standingArmy > 40 + cityLeadWeight and (self.target_player_gather_path is None or dist > 20))
                    or (player.standingArmy > 60 + cityLeadWeight and (self.target_player_gather_path is None or dist > 18))
                    or (player.standingArmy > 70 + cityLeadWeight and (self.target_player_gather_path is None or dist > 16))
                    or (player.standingArmy > 100 + cityLeadWeight))):
            logging.info("Proactively taking cities! dist {}, safe {}, player.standingArmy {}, cityLeadWeight {}".format(dist, safeOnStandingArmy, player.standingArmy, cityLeadWeight))
            return True
        logging.info("No proactive cities :(     dist {}, safe {}, player.standingArmy {}, cityLeadWeight {}".format(dist, safeOnStandingArmy, player.standingArmy, cityLeadWeight))
        return False


    def capture_cities(self, negativeTiles) -> typing.Tuple[Path | None, Move | None]:
        if self.is_all_in():
            return None, None
        logging.info(f"------------\n     CAPTURE_CITIES (force_city_take {self.force_city_take}), negativeTiles {str(negativeTiles)}\n--------------")
        genDist = min(30, self.distance_from_general(self.targetPlayerExpectedGeneralLocation))
        maxDist = max(6, int(genDist * 0.4))
        maxDist = maxDist // 1
        isNeutCity = False

        with self.perf_timer.begin_move_event('Print City Analyzer'):
            tileScores = self.cityAnalyzer.get_sorted_neutral_scores()
            enemyTileScores = self.cityAnalyzer.get_sorted_enemy_scores()

            for i, ts in enumerate(tileScores):
                tile, cityScore = ts
                self.viewInfo.midLeftGridText[tile.x][tile.y] = f'c{i}'
                EklipZBot.add_city_score_to_view_info(cityScore, self.viewInfo)

            for i, ts in enumerate(enemyTileScores):
                tile, cityScore = ts
                self.viewInfo.midLeftGridText[tile.x][tile.y] = f'm{i}'
                EklipZBot.add_city_score_to_view_info(cityScore, self.viewInfo)

        with self.perf_timer.begin_move_event('Find Enemy City Path'):
            path = self.find_enemy_city_path(negativeTiles)

        if path:
            logging.info("   find_enemy_city_path returned {}".format(path.toString()))
        else:
            logging.info("   find_enemy_city_path returned None.")
        player = self._map.players[self.general.player]
        largestTile = self.general
        for tile in player.tiles:
            if tile.army > largestTile.army:
                largestTile = tile
        targetPlayer = None
        if self.targetPlayer != -1:
            targetPlayer = self._map.players[self.targetPlayer]
        neutDepth = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3
        # we now take cities proactively?
        proactivelyTakeCity = self.should_proactively_take_cities()
        if proactivelyTakeCity:
            if self.threat is not None and self.threat.threatType == ThreatType.Kill:
                logging.info("Will not proactively take cities due to the existing threat....")
                proactivelyTakeCity = False

        forceCityOffset = 0
        if self.force_city_take:
            forceCityOffset = 1

        targCities = 1
        if targetPlayer is not None:
            targCities = targetPlayer.cityCount

        cityTakeThreshold = targCities + forceCityOffset

        logging.info(f'force_city_take {self.force_city_take}, cityTakeThreshold {cityTakeThreshold}, targCities {targCities}')
        if self.targetPlayer == -1 or self._map.remainingPlayers <= 3 or self.force_city_take:
            if targetPlayer is None \
                    or ((player.cityCount < cityTakeThreshold or proactivelyTakeCity)
                        and (self.threat is None or self.threat.threatType != ThreatType.Kill)):
                logging.info("Didn't skip neut cities.")
                # ? move this logic into proactivelytakecities?
                sqrtFactor = 10
                # if (targetPlayer is None or player.cityCount < cityTakeThreshold) and math.sqrt(player.standingArmy) * sqrtFactor > largestTile.army\
                if targetPlayer is None or player.cityCount < cityTakeThreshold or self.force_city_take:
                    logging.info(".......... searching neutral city target at depth {} (we may still be targeting enemy cities though) .........".format(neutDepth))
                    with self.perf_timer.begin_move_event('finding neutral city path'):
                        neutPath = self.find_a_neutral_city_path()
                    if neutPath and (self.targetPlayer == -1 or path is None or neutPath.length < path.length / 2):
                        logging.info("Targeting neutral city {}".format(neutPath.tail.tile.toString()))
                        path = neutPath
                        isNeutCity = True
                else:
                    logging.info("We shouldn't be taking more neutral cities, we're too defenseless right now. math.sqrt(player.standingArmy) * {}: {} << largestTile.army: {}".format(sqrtFactor, math.sqrt(player.standingArmy) * sqrtFactor, largestTile.army))
            else:
                logging.info("Skipped neut cities. in_gather_split(self._map.turn) {} and (player.cityCount < targetPlayer.cityCount {} or proactivelyTakeCity {})".format(self.timings.in_gather_split(self._map.turn), player.cityCount < targetPlayer.cityCount, proactivelyTakeCity))

        if path is None:
            logging.info("xxxxxxxxx\n  xxxxx\n    NO ENEMY CITY FOUND or Neutral city prioritized??? \n  xxxxx\nxxxxxxxx")
            return None, None

        target = path.tail.tile
        if player.standingArmy + 8 <= target.army:
            return None, None

        targetArmyGather = target.army + self.sum_enemy_army_near_tile(target, 2)
        targetArmy = 0 + self.sum_enemy_army_near_tile(target, 2) * 1.5
        searchDist = maxDist
        self.viewInfo.lastEvaluatedGrid[target.x][target.y] = 140
        # gather to the 2 tiles in front of the city
        logging.info("xxxxxxxxx\n    SEARCHED AND FOUND NEAREST NEUTRAL / ENEMY CITY {},{} dist {}. Searching {} army searchDist {}\nxxxxxxxx".format(target.x, target.y, path.length, targetArmy, searchDist))
        if path.length > 1:
            # strip the city off
            path = path.get_subsegment(path.length - 1)
        if path.length > 2:
            # strip all but 2 end tiles off
            path = path.get_subsegment(2, end=True)
        if not isNeutCity:
            # TODO with proper city contestation, this should die and just be an as-fast-as-possible
            #  cap followed by gathers to hold the city.
            targetArmyGather = target.army + max(2, target.army / 3 + self.sum_enemy_army_near_tile(target, 4) * 1.2)
            targetArmy = max(2, self.sum_enemy_army_near_tile(target, 2) * 1.1)
            searchDist = 2 * maxDist // 3 + 1

        def goalFunc(currentTile, prioObject):
            (dist, negCityCount, negEnemyTileCount, negArmySum, x, y, goalIncrement) = prioObject
            if 0-negArmySum >= targetArmy:
                return True
            return False

        killPath = breadth_first_dynamic(self._map, [target], goalFunc, 0.03, max(4, searchDist - 4), noNeutralCities = True, negativeTiles = negativeTiles, searchingPlayer = self.general.player)
        #killPath = dest_breadth_first_target(self._map, [target], targetArmy, 0.1, searchDist, negativeTiles, dontEvacCities=True)
        if killPath is not None:
            killPath = killPath.get_reversed()
            logging.info("found depth {} dest bfs kill on Neutral or Enemy city {},{} \n{}".format(killPath.length, target.x, target.y, killPath.toString()))
            self.info("City killpath {},{}  setting TreeNodes to None".format(target.x, target.y))
            self.viewInfo.lastEvaluatedGrid[target.x][target.y] = 300
            self.gatherNodes = None
            addlArmy = 0
            if target.player != -1:
                addlArmy += killPath.length
            if count(target.adjacents, lambda tile: tile.isCity and tile.player != self.general.player and tile.player != -1) > 0:
                addlArmy += killPath.length
            killPath.start.move_half = self.should_kill_path_move_half(killPath, targetArmy + addlArmy)
            return killPath, None
        gatherDuration = 25
        if player.tileCount > 125:
            gatherDuration = 15

        if (self.winning_on_army()
                or self.timings.in_gather_split(self._map.turn)
                or targetPlayer.cityCount < self._map.players[self.general.player].cityCount
                or genDist > 22
                or target.player >= 0):
            # TODO implement gather quick-kill
            with self.perf_timer.begin_move_event(f'Capture City gath to {str(path.tileList)}'):
                gatherDist = (gatherDuration - self._map.turn % gatherDuration)
                gatherDist = 24
                negativeTiles = negativeTiles.copy()
                #negativeTiles.add(self.general)
                logging.info("self.gather_to_target_tile gatherDist {} - targetArmyGather {}".format(gatherDist, targetArmyGather))
                for t in path.tileList:
                    self.viewInfo.add_targeted_tile(t, TargetStyle.PURPLE)

                move, gatherValue, gatherTurns, gatherNodes = self.get_gather_to_target_tiles(
                    path.tileList,
                    0.03,
                    gatherDist,
                    gatherNegatives=negativeTiles,
                    targetArmy=targetArmyGather - gatherDist // 4)
                    # targetArmy=targetArmyGather - gatherDist // 2)

                if move is not None:
                    if target.player != -1:
                        targetArmyGather += 4 + gatherDist // 4

                    # TODO only prune to target army if we're attacking a neutral city,
                    #  for now. Until city contestation
                    gatherNodes = GatherUtils.prune_mst_to_army(gatherNodes, targetArmyGather + 1, self.general.player, self.viewInfo)
                    move = self.get_tree_move_default(gatherNodes)

                    self.gatherNodes = gatherNodes
                    self.info("Gathering to target city {},{}, proactivelyTakeCity {}, move {}".format(target.x, target.y, proactivelyTakeCity, move.toString()))
                    self.viewInfo.lastEvaluatedGrid[target.x][target.y] = 300
                    return None, move

        logging.info("xxxxxxxxx\n  xxxxx\n    GATHERING TO CITY FAILED :( {},{} \n  xxxxx\nxxxxxxxx".format(target.x, target.y))
        return None, None

    def mark_tile(self, tile, alpha = 100):
        self.viewInfo.lastEvaluatedGrid[tile.x][tile.y] = alpha

    def find_a_neutral_city_path(self):
        targetCity: Tile | None = None
        maxScore: CityScoreData | None = None
        for city in self.cityAnalyzer.city_scores.keys():
            score = self.cityAnalyzer.city_scores[city]
            enemyVision = [tile for tile in filter(lambda t: t.player != -1 and t.player != self.general.player, city.adjacents)]
            cityDistanceRatioThresh = 0.9
            if len(enemyVision) > 0:
                cityDistanceRatioThresh = 0.5
            if (maxScore is None or maxScore.get_weighted_neutral_value() < score.get_weighted_neutral_value()) \
                    and score.general_distances_ratio < cityDistanceRatioThresh:
                maxScore = score
                targetCity = city

        path: Path | None = None
        if targetCity is not None:
            logging.info("Found a neutral city path, closest to me and furthest from enemy. Chose city {} with rating {}".format(targetCity.toString(), maxScore.get_weighted_neutral_value()))

            path = self.get_path_to_targets(targetCity.movable)
            if path is not None:
                path.add_next(targetCity)
            logging.info("    path {}".format(path.toString()))
        else:
            logging.info("{} No neutral city found...".format(self.get_elapsed()))

        return path


    def find_enemy_city_path(self, negativeTiles):
        maxDist = 0
        playerArmy = self._map.players[self.general.player].standingArmy
        ignoreCityArmyThreshold = playerArmy / 3 + 50
        logging.info(f"ignoring enemy cities larger than {int(ignoreCityArmyThreshold)} army...")
        # our general has less than 500 standing army, only target cities owned by our target player
        searchLambda = lambda tile, prioObject: tile.isCity and tile.player == self.targetPlayer and tile.army < ignoreCityArmyThreshold

        if playerArmy > 1000: # our general has greater than 1000 standing army, capture neutrals up to 0.8* the dist to enemy general
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.5
        elif playerArmy > 700: # our general has greater than 700 standing army, capture neutrals
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.45
        elif playerArmy > 500:
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.4
        elif playerArmy > 400:
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.37
        else:
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.35
        maxDist = max(maxDist, 5)
        targetPath = self.target_player_gather_path
        if self.distance_from_general(self.targetPlayerExpectedGeneralLocation) > 6:
            targetPath = self.target_player_gather_path.get_subsegment(min(4, self.target_player_gather_path.length // 3))

        path = breadth_first_dynamic(self._map, targetPath.tileSet, searchLambda, 0.1, maxDist, preferNeutral = True)
        if path is not None:
            return path

        if playerArmy > 1000: # our general has greater than 1000 standing army, capture neutrals up to 0.8* the dist to enemy general
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.6
        elif playerArmy > 700: # our general has greater than 700 standing army, capture neutrals
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.5
        elif playerArmy > 500:
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.45
        elif playerArmy > 300:
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.42
        else:
            maxDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 0.35
        return breadth_first_dynamic(self._map, targetPath.tileSet, searchLambda, 0.1, maxDist, preferNeutral = True)

    def get_value_per_turn_subsegment(self, path, minFactor = 0.7, minLengthFactor = 0.25):
        pathMoveList = get_tile_list_from_path(path)
        totalCount = len(pathMoveList)
        fullValue = 0
        for tile in pathMoveList:
            if tile.player == self.general.player:
                fullValue += tile.army - 1
        i = 1
        curSum = 0
        maxValuePerTurn = 0

        lastValueTile = None
        reversedPath = list(reversed(pathMoveList))
        logging.info("get_value_per_turn_subsegment: len(pathMoveList) == {}".format(len(pathMoveList)))
        logging.info("get_value_per_turn_subsegment input path: {}".format(path.toString()))
        for tile in reversedPath:
            if tile.player == self.general.player:
                curSum += tile.army - 1
            valuePerTurn = curSum / i
            logging.info("  [{}]  {},{}  value per turn was {}".format(i, tile.x, tile.y, "%.1f" % valuePerTurn))
            if valuePerTurn >= maxValuePerTurn and i <= totalCount and i > totalCount * minLengthFactor:
                logging.info(" ![{}]  {},{}  new max!    {} > {}".format(i, tile.x, tile.y, "%.1f" % valuePerTurn, "%.1f" % maxValuePerTurn))
                maxValuePerTurn = valuePerTurn
                lastValueTile = tile
            i += 1

        i = 1
        lastValueIndex = 0
        curSum = 0
        #logging.info("len(reversedPath) {}".format(len(reversedPath)))
        for tile in reversedPath:
            if tile.player == self.general.player:
                curSum += tile.army - 1
            valuePerTurn = curSum / i
            logging.info("  [{}]  {},{}   2nd pass {}".format(i, tile.x, tile.y, "%.1f" % valuePerTurn))
            if valuePerTurn >= maxValuePerTurn * minFactor:
                lastValueIndex = i
                lastValueTile = tile
                logging.info("!![{}]  {},{}    minFactor max   {} >= {}".format(i, tile.x, tile.y, "%.1f" % valuePerTurn, "%.1f" % maxValuePerTurn))
            i += 1
        if lastValueTile:
            logging.info("       -----   ---- lastValueIndex was {} tile {}".format(lastValueIndex, lastValueTile.toString()))
        else:
            logging.warn("No lastValueTile found??? lastValueIndex was {}".format(lastValueIndex))

        newPath = path.get_subsegment(lastValueIndex, end=True)
        if newPath.start.tile.army == 1:
            self.info(f'BRO VALUE PER TURN SUBSEGMENT DOESNT WORK RIGHT')
            logging.error(f'value_per_turn_subsegment turned {str(path)} into {str(newPath)}...? Start tile is 1. Returning original path...')
            return path
            # raise AssertionError('Ok clearly we fucked up')
        newPath.calculate_value(self.general.player)
        return newPath

    #def get_path_list_subsegment(self, pathList, count, end=False):


    #def get_path_subsegment(self, path, count, end=False):
    #    pathMoveList = get_tile_list_from_path(path)


    #def get_path_subsegment_ratio(self, path, fraction, end=False):
    #    count = 0
    #    node = path
    #    while node is not None:
    #        count += 1
    #        node = node.parent


    def weighted_breadth_search(self, tiles, maxLength=50, maxTime = 0.2, playerSearching = -2, armyAmount = -1, returnAmount = 10, negativeTilesSet = None):
        """
        This is the ancient tech from bot v1.0

        @param tiles:
        @param maxLength:
        @param maxTime:
        @param playerSearching:
        @param armyAmount:
        @param returnAmount:
        @param negativeTilesSet:
        @return:
        """
        loggingOn = False
        frontier = PriorityQueue()
        tileArr = tiles
        tiles = set()
        for tile in tileArr:
            tiles.add(tile)
        #logging.info("searching, len tiles {}".format(len(tiles)))
        if playerSearching == -2:
            playerSearching = self._map.player_index
        general = self._map.generals[playerSearching]
        generalPlayer = self._map.players[playerSearching]
        cityRatio = self.get_city_ratio(playerSearching)


        for tile in tiles:
            if tile.player == playerSearching:
                if armyAmount != -1:
                    logging.info("\n\n------\nSearching nonstandard army amount {} to {},{}\n--------".format(armyAmount, tile.x, tile.y))
                frontier.put((-10000, PathNode(tile, None, tile.army, 1, 1 if tile.isCity or tile.isGeneral else 0, {(tile.x, tile.y) : 1}), armyAmount, False, 0))
            else:
                isIncrementing = (tile.isCity and tile.player != -1) or tile.isGeneral
                if isIncrementing:
                    logging.info("City or General is in this searches targets: {},{}".format(tile.x, tile.y))
                frontier.put((-10000 * (1 if not tile.isCity else cityRatio), PathNode(tile, None, 0 - tile.army, 1, 1 if tile.isCity or tile.isGeneral else 0, {(tile.x, tile.y) : 1}), 2, isIncrementing, 1))
        leafNodes = PriorityQueue()
        start = time.perf_counter()


        iter = 1
        undiscoveredTileSearchCount = 0
        score = self._map.scores[playerSearching]
        skippedTargetCount = 0
        isHalfTurn = False
        while not frontier.empty(): #make sure there are nodes to check left

            if iter & 32 == 0 and time.perf_counter() - start > maxTime:
                break

            prioNode = frontier.get() #grab the first nodep
            prioValue = prioNode[0]
            node = prioNode[1]
            enemyTileCount = prioNode[4]
            x = node.tile.x
            y = node.tile.y
            turn = node.turn
            curTile = node.tile

            #self._map[x][y]="explored" #make this spot explored so we don't try again

            if turn <= maxLength:
                value = node.value
                # cityCount = node.cityCount
                pathDict = node.pathDict
                #if (loggingOn):
                #    logging.info("{} evaluating {},{}: turn {} army {}".format(prioNode[0], x, y, turn, value))

                targetArmy = prioNode[2]
                isIncrementing = prioNode[3]

                neededArmy = targetArmy + 2
                if isIncrementing:
                    neededArmy += (turn / 2)

                for candTile in curTile.movable: #new spots to try
                    containsCount = pathDict.get((candTile.x, candTile.y), 0)
                    if containsCount <= 2:
                        if candTile.isNotPathable or candTile.isMountain or (candTile.isCity and candTile.player == -1):
                            continue

                        if candTile in tiles:
                            continue
                        self.viewInfo.evaluatedGrid[candTile.x][candTile.y] += 1
                        candTileArmyVal = 0

                        # if we've already visited this tile
                        if containsCount > 0:
                            candTileArmyVal = value

                        # if this tile is recommended not to be moved
                        elif negativeTilesSet is not None and candTile in negativeTilesSet:
                            #if (loggingOn):
                            #logging.info("Tile {},{} value calculated as 0 because it is in negativeTileSet".format(candTile.x, candTile.y))
                            candTileArmyVal = value

                        # if this tile is owned by the current player
                        elif candTile.player == playerSearching:
                            candTileArmyVal = value + (candTile.army - 1)
                            if candTile.isGeneral and isHalfTurn:
                                if playerSearching == self._map.player_index:
                                    if not self.general_move_safe(candTile):
                                        #logging.info("Bot is in danger. Refusing to use general tile altogether.")
                                        continue
                                    candTileArmyVal -= candTile.army / 2


                        # if this is an undiscovered neutral tile
                        elif not candTile.discovered:
                            if candTile.isNotPathable:
                                candTileArmyVal = value - 100
                            else:
                                candTileArmyVal = value - (candTile.army + 1)
                            undiscoveredTileSearchCount += 1
                        else:
                            candTileArmyVal = value - (candTile.army + 1)
                        weightedCandTileArmyVal = candTileArmyVal
                        if targetArmy > 0 and candTileArmyVal > neededArmy:
                            #weightedCandTileArmyVal = 2 * (candTileArmyVal - neededArmy) / 3 + neededArmy
                            weightedCandTileArmyVal = pow(candTileArmyVal - neededArmy, 0.9) + neededArmy
                        #paths starting through enemy territory carry a zero weight until troops are found, causing this to degenerate into breadth first search until we start collecting army (due to subtracting turn)
                        #weight paths closer to king
                        if weightedCandTileArmyVal <= -5 and general is not None:
                            distToGen = self.distance_from_general(candTile)
                            weightedCandTileArmyVal = weightedCandTileArmyVal - (distToGen / 5.0)
                            #if (loggingOn):
                            #    logging.info("{},{} weightedCandTileArmyVal <= 0, weighted: {}".format(candTile.x, candTile.y, weightedCandTileArmyVal))
                        #elif(loggingOn):
                        #    logging.info("{},{} weightedCandTileArmyVal > 0, weighted: {}".format(candTile.x, candTile.y, weightedCandTileArmyVal))


                        # candTileCityCount = cityCount if containsCount > 0 or not (candTile.isCity and candTile.player != -1) else cityCount + 1
                        candPathDict = pathDict.copy()
                        candPathDict[(candTile.x, candTile.y)] = containsCount + 1
                        candTileEnemyTileCount = enemyTileCount
                        if containsCount == 0 and (candTile.player != self._map.player_index and candTile.player != -1):
                            candTileEnemyTileCount += 1
                            if candTile.isCity and containsCount == 0:
                                candTileEnemyTileCount += (3 * cityRatio)
                        tileWeight = 0
                        #if (maximizeTurns):
                        #    weightedCandTileArmyVal - turn - score['total'] / 750.0 * pow(turn, 1.5)
                        #else:
                        # tileWeight = candTileEnemyTileCount + (candTileEnemyTileCount / 4.0 + candTileCityCount * 2) * weightedCandTileArmyVal + 14 * weightedCandTileArmyVal / turn - turn - (score['total'] / 900.0) * pow(turn, 1.33)
                        tileWeight = candTileEnemyTileCount + 14 * weightedCandTileArmyVal / turn - 2 * turn - (score.total / 900.0) * pow(turn, 1.1)
                            #tileWeight = (candTileCityCount + 2) * weightedCandTileArmyVal + 13 * weightedCandTileArmyVal / turn - turn - score['total'] / 750.0 * pow(turn, 1.5)
                        #if (loggingOn): logging.info("{},{} fullWeight: {}".format(candTile.x, candTile.y, tileWeight))
                        frontier.put((0 - tileWeight, PathNode(candTile, node, candTileArmyVal, turn + 1, 0, candPathDict), targetArmy, isIncrementing, candTileEnemyTileCount))#create the new spot, with node as the parent
                    #elif(loggingOn):
                    #    logging.info("{},{} already showed up twice".format(x, y))
            if curTile.player == playerSearching and curTile.army > 1 and targetArmy < value and turn > 1:
                leafNodes.put(prioNode)
            iter += 1
        best = []
        for i in range(returnAmount):
            if leafNodes.empty():
                break
            node = leafNodes.get()
            best.append(node)

        if len(best) > 0:
            logging.info("best: " + str(best[0][0]))
        end = time.perf_counter()
        logging.info("SEARCH ITERATIONS {}, TARGET SKIPPED {}, DURATION: {:.2f}".format(iter, skippedTargetCount, end - start))
        #if (undiscoveredTileSearchCount > 0):
        #    logging.info("~~evaluated undiscovered tiles during search: " + str(undiscoveredTileSearchCount))
        newBest = []
        for i, oldpath in enumerate(best):
            oldPathNode = oldpath[1]
            newPath = Path(oldPathNode.value)
            while oldPathNode is not None:
                newPath.add_next(oldPathNode.tile)
                oldPathNode = oldPathNode.parent
            newBest.append(newPath)
            logging.info("newBest {}:  {}\n{}".format(i, newPath.value, newPath.toString()))

        return newBest



    def get_city_ratio(self, player_index):
        enemyCityMax = 0
        generalPlayer = self._map.players[player_index]
        for player in self._map.players:
            if player.index != player_index and not player.dead:
                enemyCityMax = max(player.cityCount, enemyCityMax)
        cityRatio = max(1.0, 1.0 * enemyCityMax / generalPlayer.cityCount)

        otherPlayerIncomeMax = 0
        playerIncome = generalPlayer.tileCount + 25 * generalPlayer.cityCount
        for player in self._map.players:
            if player.index != player_index and not player.dead:
                otherPlayerIncomeMax = max(player.tileCount + 25 * player.cityCount, otherPlayerIncomeMax)
        incomeRatio = max(1.0, 1.0 * otherPlayerIncomeMax / playerIncome)
        tileCount = max(generalPlayer.tileCount, 1)
        theMax = max(cityRatio, incomeRatio)
        theMax = theMax * (self._map.remainingPlayers / 2.0)
        theMax = min(1.0 * generalPlayer.score / tileCount, theMax)
        logging.info("city ratio: {}".format(theMax))
        return theMax


    def calculate_general_danger(self):
        depth = (self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 3) // 4
        if depth < 9:
            depth = 9
        self.dangerAnalyzer.analyze(self.general, depth, self.armyTracker.armies)

        if self.dangerAnalyzer.fastestThreat:
            self.viewInfo.addAdditionalInfoLine(f'Threat: {self.dangerAnalyzer.fastestThreat.path.toString()}')
            if self.dangerAnalyzer.fastestThreat.saveTile is not None:
                self.viewInfo.add_targeted_tile(self.dangerAnalyzer.fastestThreat.saveTile, TargetStyle.GOLD)
        # if self.dangerAnalyzer.highestThreat:
        #     self.viewInfo.addAdditionalInfoLine(f'highest threat found: {self.dangerAnalyzer.highestThreat.path.toString()}')
        if self.dangerAnalyzer.fastestVisionThreat:
            self.viewInfo.addAdditionalInfoLine(f'VThreat: {self.dangerAnalyzer.fastestVisionThreat.path.toString()}')
            if self.dangerAnalyzer.fastestVisionThreat.saveTile is not None:
                self.viewInfo.add_targeted_tile(self.dangerAnalyzer.fastestVisionThreat.saveTile, TargetStyle.GREEN)


    def general_min_army_allowable(self):
        if self._minAllowableArmy != -1:
            return self._minAllowableArmy
        general = self._map.generals[self._map.player_index]
        if general is None:
            return -1
        maxPlayerPotentialArmy = 0
        generalScore = self._map.scores[self._map.player_index]
        generalPlayer = self._map.players[self.general.player]

        realDanger = False
        dangerousPath = None
        dangerValue = -1
        wasAllIn = self.allIn
        self.allIn = False
        for player in self._map.players:
            if player == generalPlayer or player is None or player.dead:
                continue
            #give up if we're massively losing
            if self._map.remainingPlayers == 2:
                if self._map.turn > 250 and player.tileCount + 20 * (player.cityCount - 1) > generalPlayer.tileCount * 1.3 + 5 + 20 * (generalPlayer.cityCount + 2) and player.standingArmy > generalPlayer.standingArmy * 1.25 + 5:
                    self.allIn = True
                    self.all_in_counter = 200
                elif self._map.turn > 150 and player.tileCount + 15 * player.cityCount > generalPlayer.tileCount * 1.4 + 5 + 15 * (generalPlayer.cityCount + 2) and player.standingArmy > generalPlayer.standingArmy * 1.25 + 5:
                    # self.allIn = True
                    self.all_in_counter += 3
                elif not self.all_in_army_advantage and self._map.turn > 50 and player.tileCount + 35 * player.cityCount > 5 + generalPlayer.tileCount * 1.1 + (35 * generalPlayer.cityCount):
                    self.all_in_counter += 1
                else:
                    self.all_in_counter = 0
                if self.all_in_counter > generalPlayer.tileCount:
                    self.allIn = True
                if player.tileCount + 35 * player.cityCount > generalPlayer.tileCount * 1.5 + 5 + 35 * generalPlayer.cityCount and player.score > generalPlayer.score * 1.6 + 5:
                    self.giving_up_counter += 1
                    logging.info("~ ~ ~ ~ ~ ~ ~ giving_up_counter: {}. Player {} with {} tiles and {} army.".format(self.giving_up_counter, player.index, player.tileCount, player.score))
                    if self.giving_up_counter > generalPlayer.tileCount + 20 and not self.finishingExploration:
                        logging.info("~ ~ ~ ~ ~ ~ ~ giving up due to player {} with {} tiles and {} army.".format(player.index, player.tileCount, player.score))
                        time.sleep(2)
                        self._map.result = False
                        self._map.complete = True
                else:
                    self.giving_up_counter = 0

        self._minAllowableArmy = 1
        return 1

    def is_move_safe_valid(self, move, allowNonKill = False):
        if move is None:
            return False
        if move.source == self.general:
            return self.general_move_safe(move.dest)
        if move.source.player != move.dest.player and move.source.army - 2 < move.dest.army and not allowNonKill:
            logging.info("{},{} -> {},{} was not a move that killed the dest tile".format(move.source.x, move.source.y, move.dest.x, move.dest.y))
            return False
        return True


    def general_move_safe(self, target, move_half=False):
        dangerTiles = self.get_general_move_blocking_tiles(target, move_half)
        return len(dangerTiles) == 0

    def get_general_move_blocking_tiles(self, target, move_half=False):
        blockingTiles = []

        dangerTiles = self.get_danger_tiles(move_half)

        general = self._map.generals[self._map.player_index]
        minArmy = self.general_min_army_allowable()

        genArmyAfterMove = 1

        safeSoFar = True

        for dangerTile in dangerTiles:
            dangerTileIsTarget = target.x == dangerTile.x and target.y == dangerTile.y
            dangerTileIsNextTarget = target.x == (dangerTile.x + self.general.x) >> 2 and (dangerTile.y + self.general.y) >> 2
            if not (dangerTileIsTarget or dangerTileIsNextTarget):
                safeSoFar = False
                blockingTiles.append(dangerTile)
                logging.info("BLOCK Enemy tile {},{} is preventing king moves. NOT dangerTileIsTarget {} or dangerTileIsNextTarget {}".format(dangerTile.x, dangerTile.y, dangerTileIsTarget, dangerTileIsNextTarget))
            else:
                logging.info("ALLOW Enemy tile {},{} allowed due to dangerTileIsTarget {} or dangerTileIsNextTarget {}.".format(dangerTile.x, dangerTile.y, dangerTileIsTarget, dangerTileIsNextTarget))
        return blockingTiles

    def should_defend_economy(self):
        if self._map.remainingPlayers > 2:
            return False
        if self.targetPlayer == -1:
            return False

        self.defendEconomy = False
        winningText = "first 100 still"
        if self._map.turn >= 100:
            econRatio = 1.16
            armyRatio = 1.45
            winningEcon = self.winning_on_economy(econRatio, cityValue=20, againstPlayer=self.targetPlayer, offset = -5)
            winningArmy = self.winning_on_army(armyRatio)
            pathLen = 20
            if self.shortest_path_to_target_player is not None:
                pathLen = self.shortest_path_to_target_player.length

            playerArmyNearGeneral = self.sum_player_army_near_tiles(self.shortest_path_to_target_player.tileList, distance=pathLen // 4 + 1)
            armyThresh = int(self.targetPlayerObj.standingArmy ** 0.93)
            hasEnoughArmyNearGeneral = playerArmyNearGeneral > armyThresh

            self.defendEconomy = winningEcon and (not winningArmy or not hasEnoughArmyNearGeneral)
            if self.defendEconomy:
                if not hasEnoughArmyNearGeneral and winningArmy:
                    self.viewInfo.addAdditionalInfoLine("FORCING MAX GATHER TIMINGS BECAUSE NOT ENOUGH ARMY NEAR GEN AND DEFENDING ECONOMY")
                    self.timings.split = self.timings.cycleTurns
                logging.info(
                    f"\n\nDEF ECONOMY! winning_on_econ({econRatio}) {str(winningEcon)[0]}, on_army({armyRatio}) {str(winningArmy)[0]}, enough_near_gen({playerArmyNearGeneral}/{armyThresh}) {str(hasEnoughArmyNearGeneral)[0]}")
                winningText = f"! woe{econRatio} {str(winningEcon)[0]}, woa{armyRatio} {str(winningArmy)[0]}, sa{playerArmyNearGeneral}/{armyThresh} {str(hasEnoughArmyNearGeneral)[0]}"
            else:
                logging.info(
                    f"\n\nNOT DEFENDING ECONOMY? winning_on_econ({econRatio}) {str(winningEcon)[0]}, on_army({armyRatio}) {str(winningArmy)[0]}, enough_near_gen({playerArmyNearGeneral}/{armyThresh}) {str(hasEnoughArmyNearGeneral)[0]}")
                winningText = f"  woe{econRatio} {str(winningEcon)[0]}, woa{armyRatio} {str(winningArmy)[0]}, sa{playerArmyNearGeneral}/{armyThresh} {str(hasEnoughArmyNearGeneral)[0]}"
        self.viewInfo.addlTimingsLineText = winningText
        return self.defendEconomy

    def get_danger_tiles(self, move_half=False) -> typing.Set[Tile]:
        dangerPath = SearchUtils.dest_breadth_first_target(self._map, self.general.movable, targetArmy=3, maxTime=0.1, maxDepth=4, searchingPlayer=self.targetPlayer, ignoreGoalArmy=False)

        if dangerPath is not None:
            return dangerPath.tileSet

        return set()



    def find_target_gather_leaves(self, allLeaves=None):
        self.leafValueGrid = [[None for x in range(self._map.rows)] for y in range(self._map.cols)]
        mapMid = (self._map.cols / 2, self._map.rows / 2)
        maxMoves = PriorityQueue()
        cityRatio = self.get_city_ratio(self._map.player_index)
        logging.info("CityRatio: {}".format(cityRatio))
        genArmy = self.general.army
        if self.general.army // 2 > self.general_min_army_allowable():
            genArmy = self.general.army // 2
        for leaf in allLeaves:
            #if (len(maxMoves) == 0 or leaf.source.army - leaf.dest.army >= maxMoves[0].source.army - maxMoves[0].dest.army):
            leafValue = 10 + leaf.dest.army

            midWeight = pow(pow(abs(leaf.dest.x - mapMid[0]), 2) + pow(abs(leaf.dest.y - mapMid[1]), 2), 0.5) - (self._map.cols + self._map.rows) / 6
            if midWeight < 0:
                midWeight = 0

            if self._map.remainingPlayers > 3:
                leafValue += midWeight
            else:
                leafValue -= midWeight


            if leaf.dest.isCity and leaf.dest.player == -1:
                curVal = self.leafValueGrid[leaf.dest.x][leaf.dest.y]
                if curVal is None:
                    self.leafValueGrid[leaf.dest.x][leaf.dest.y] = -1000000
                continue

            distToGen = max(self.distance_from_general(leaf.dest), 3)
            leafValue = leafValue + 600 / distToGen
            if leaf.dest.isCity and leaf.dest.player == -1:
                leafValue = leafValue + (350 - distToGen * 15) * cityRatio

            if leaf.dest.player != -1 and leaf.dest.player != self.targetPlayer and self.distance_from_general(leaf.dest) > self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3:
                # skip non-close tiles owned by enemies who are not the current target.
                # TODO support agrod enemies who are actively attacking us despite not being the current target. Also improve reprioritization for players aggroing us.
                self.viewInfo.lastEvaluatedGrid[leaf.dest.x][leaf.dest.y] = 200
                self.leafValueGrid[leaf.dest.x][leaf.dest.y] = -1000000
                continue
            elif leaf.dest.player == self.targetPlayer and self._map.turn < 50:
                leafValue *= 0.3
            elif leaf.dest.player == self.targetPlayer and self._map.turn < 100:
                leafValue *= 5.0 / min(self._map.remainingPlayers, 3)
            elif leaf.dest.player == self.targetPlayer and self._map.turn >= 100:
                leafValue *= 8.0 / min(self._map.remainingPlayers, 4)
            elif leaf.dest.player != -1:
                leafValue = leafValue * 2.0 / min(4, max(self._map.remainingPlayers, 2))
            if leaf.dest.isCity:
                cityRatActive = cityRatio
                if leaf.dest.player == -1:
                    inEnemyTerr = False
                    for adj in leaf.dest.adjacents:
                        if adj.player != -1 and adj.player != self._map.player_index:
                            inEnemyTerr = True
                    if inEnemyTerr:
                        cityRatActive = cityRatActive * 0.7
                distToGen = self.distance_from_general(leaf.dest)
                distToEnemy = self.getDistToEnemy(leaf.dest)
                leafValue *= 3
                if distToEnemy > 0:
                    distWeight = max(1.0, pow(distToGen * 2, 1.1) - pow((2 + distToEnemy) * 2.2, 1.4) / 4.0)
                    logging.info("distWeight {},{}: {} ({}, {})".format(leaf.dest.x, leaf.dest.y, distWeight, distToGen, distToEnemy))
                    leafValue = (leafValue / distWeight) * cityRatActive
                else:
                    leafValue = (leafValue / pow(distToGen / 2, 1.4)) * cityRatActive

            curVal = self.leafValueGrid[leaf.dest.x][leaf.dest.y]
            if curVal is None or curVal < leafValue:
                self.leafValueGrid[leaf.dest.x][leaf.dest.y] = leafValue
            leafValue = 0 - leafValue
            maxMoves.put((leafValue, leaf))

        moves = []
        addedSet = set()
        if not maxMoves.empty():
            moveNode = maxMoves.get()
            maxMove = moveNode[0]
            leeway = maxMove * 0.90
            #always return at least 1 potential targets
            # less than because the heuristic value goes negative for good values
            while moveNode[0] < leeway or len(moves) < 1:
                moveTuple = (moveNode[1].dest.x, moveNode[1].dest.y)
                if not moveTuple in addedSet:
                    tile = moveNode[1].dest
                    tileInfo = "{}, player {}".format(tile.army, tile.player)
                    if tile.isCity:
                        tileInfo += ", city"
                    if tile.isGeneral:
                        tileInfo += ", general"

                    logging.info("TargetGather including {},{} [{}] ({})".format(tile.x, tile.y, moveNode[0], tileInfo))
                    addedSet.add(moveTuple)
                    moves.append(moveNode[1])
                if maxMoves.empty():
                    break
                moveNode = maxMoves.get()
        return moves

    def winning_on_economy(self, byRatio = 1.0, cityValue = 30, againstPlayer = -2, offset = 0):
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer
        if againstPlayer == -1:
            return True
        targetPlayer = self._map.players[againstPlayer]
        generalPlayer = self._map.players[self.general.player]

        playerEconValue = (generalPlayer.tileCount + generalPlayer.cityCount * cityValue) + offset
        oppEconValue = (targetPlayer.tileCount + targetPlayer.cityCount * cityValue) * byRatio
        return playerEconValue >= oppEconValue

    def winning_on_army(self, byRatio = 1.0, useFullArmy = False, againstPlayer = -2):
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer
        if againstPlayer == -1:
            return True
        targetPlayer = self._map.players[againstPlayer]
        generalPlayer = self._map.players[self.general.player]

        targetArmy = targetPlayer.standingArmy
        playerArmy = generalPlayer.standingArmy
        if useFullArmy:
            targetArmy = targetPlayer.score
            playerArmy = generalPlayer.score
        winningOnArmy = playerArmy >= targetArmy * byRatio
        logging.info(
            f"winning_on_army({byRatio}): playerArmy {playerArmy} >= targetArmy {targetArmy} (weighted {targetArmy * byRatio:.1f}) ?  {winningOnArmy}")
        return winningOnArmy

    def worth_attacking_target(self):
        timingFactor = 1.0
        if self._map.turn < 50:
            self.viewInfo.addAdditionalInfoLine("Not worth attacking, turn < 50")
            return False

        knowsWhereEnemyGeneralIs = self.targetPlayer != -1 and self._map.generals[self.targetPlayer] is not None

        player = self._map.players[self.general.player]
        targetPlayer = self._map.players[self.targetPlayer]

        # if 20% ahead on economy and not 10% ahead on standing army, just gather, dont attack....
        wPStanding = player.standingArmy * 0.9
        oppStanding = targetPlayer.standingArmy
        wPIncome = player.tileCount + player.cityCount * 30
        wOppIncome = targetPlayer.tileCount * 1.2 + targetPlayer.cityCount * 35 + 5
        if self._map.turn >= 100 and wPStanding < oppStanding and wPIncome > wOppIncome:
            self.viewInfo.addAdditionalInfoLine("NOT WORTH ATTACKING TARGET BECAUSE wPStanding < oppStanding and wPIncome > wOppIncome")
            self.viewInfo.addAdditionalInfoLine("NOT WORTH ATTACKING TARGET BECAUSE {}     <  {}        and   {} >   {}".format(wPStanding, oppStanding, wPIncome, wOppIncome))
            return False

        #factor in some time for exploring after the attack, + 1 * 1.1
        if self.target_player_gather_path is None:
            logging.info("ELIM due to no path")
            return False
        value = get_player_army_amount_on_path(self.target_player_gather_path, self._map.player_index, 0, self.target_player_gather_path.length)
        logging.info("Player army amount on path: {}   TARGET PLAYER PATH IS REVERSED ? {}".format(value, self.target_player_gather_path.toString()))
        subsegment = self.get_value_per_turn_subsegment(self.target_player_gather_path)
        logging.info("value per turn subsegment = {}".format(subsegment.toString()))
        subsegmentTargets = get_tile_set_from_path(subsegment)

        lengthRatio = len(self.target_player_gather_targets) / max(1, len(subsegmentTargets))

        sqrtVal = 0
        if value > 0:
            sqrtVal = value ** 0.5
            logging.info("value ** 0.5 -> sqrtVal {}".format(sqrtVal))
        if player.tileCount < 60:
            sqrtVal = value / 2.0
            logging.info("value / 2.3  -> sqrtVal {}".format(sqrtVal))
        sqrtVal = min(20, sqrtVal)

        dist = int((len(subsegmentTargets)) + sqrtVal)
        factorTurns = 50
        if dist > 25 or player.tileCount > 110:
            factorTurns = 100
        turnOffset = self._map.turn + dist
        factorScale = turnOffset % factorTurns
        if factorScale < factorTurns / 2:
            logging.info("factorScale < factorTurns / 2")
            timingFactor = scale(factorScale, 0, factorTurns / 2, 0, 0.40)
        else:
            logging.info("factorScale >>>>>>>>> factorTurns / 2")
            timingFactor = scale(factorScale, factorTurns / 2, factorTurns, 0.30, 0)

        if self.lastTimingFactor != -1 and self.lastTimingFactor < timingFactor:
            logging.info("  ~~~  ---  ~~~  lastTimingFactor {} <<<< timingFactor {}".format("%.3f" % self.lastTimingFactor, "%.3f" % timingFactor))
            factor = self.lastTimingFactor
            self.lastTimingFactor = timingFactor
            timingFactor = factor
        self.lastTimingTurn = self._map.turn

        if player.tileCount > 200:
            #timing no longer matters after a certain point?
            timingFactor = 0.1

        # if we are already attacking, keep attacking
        alreadyAttacking = False
        if self._map.turn - 3 < self.lastTargetAttackTurn:
            timingFactor *= 0.3 # 0.3
            alreadyAttacking = True
            logging.info("already attacking :)")

        if player.standingArmy < 5 and timingFactor > 0.1:
            return False
        logging.info("OoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoO\n   {}  oOo  timingFactor {},  factorTurns {},  turnOffset {},  factorScale {},  sqrtVal {},  dist {}".format(self._map.turn, "%.3f" % timingFactor, factorTurns, turnOffset, factorScale, "%.1f" % sqrtVal, dist))

        playerEffectiveStandingArmy = player.standingArmy - 9 * (player.cityCount - 1)
        if self.target_player_gather_path.length < 2:
            logging.info("ELIM due to path length {}".format(self.distance_from_general(self.targetPlayerExpectedGeneralLocation)))
            return False

        targetPlayerArmyThreshold = self._map.players[self.targetPlayer].standingArmy + dist / 2
        if player.standingArmy < 70:
            timingFactor *= 2
            timingFactor = timingFactor ** 2
            if knowsWhereEnemyGeneralIs:
                timingFactor += 0.05
            rawNeeded = playerEffectiveStandingArmy * 0.62 + playerEffectiveStandingArmy * timingFactor
            rawNeededScaled = rawNeeded * lengthRatio
            neededVal = min(targetPlayerArmyThreshold, rawNeededScaled)
            if alreadyAttacking:
                neededVal *= 0.75
            logging.info("    --   playerEffectiveStandingArmy: {},  NEEDEDVAL: {},            VALUE: {}".format(playerEffectiveStandingArmy, "%.1f" % neededVal, value))
            logging.info("    --                                     rawNeeded: {},  rawNeededScaled: {},  lengthRatio: {}, targetPlayerArmyThreshold: {}".format("%.1f" % rawNeeded, "%.1f" % rawNeededScaled, "%.1f" % lengthRatio, "%.1f" % targetPlayerArmyThreshold))
            return value > neededVal
        else:
            if knowsWhereEnemyGeneralIs:
                timingFactor *= 1.5
                timingFactor += 0.03
            expBase = playerEffectiveStandingArmy * 0.15
            exp = 0.68 + timingFactor
            expValue = playerEffectiveStandingArmy ** exp
            rawNeeded = expBase + expValue
            rawNeededScaled = rawNeeded * lengthRatio
            neededVal = min(targetPlayerArmyThreshold, rawNeededScaled)
            if alreadyAttacking:
                neededVal *= 0.75
            logging.info("    --    playerEffectiveStandingArmy: {},  NEEDEDVAL: {},            VALUE: {},      expBase: {},   exp: {},       expValue: {}".format(playerEffectiveStandingArmy, "%.1f" % neededVal, value, "%.2f" % expBase, "%.2f" % exp, "%.2f" % expValue))
            logging.info("    --                                      rawNeeded: {},  rawNeededScaled: {},  lengthRatio: {}, targetPlayerArmyThreshold: {}".format("%.1f" % rawNeeded, "%.1f" % rawNeededScaled, "%.1f" % lengthRatio, "%.1f" % targetPlayerArmyThreshold))
            return value >= neededVal

    def get_target_army_inc_adjacent_enemy(self, tile):
        sumAdj = 0
        for adj in tile.adjacents:
            if adj.player != self._map.player_index and adj.player != -1:
                sumAdj += adj.army - 1
        armyToSearch = sumAdj
        # if tile.army > 5 and tile.player != self._map.player_index and not tile.isNeutral:
        #     armyToSearch += tile.army / 2
        return armyToSearch

    def find_leaf_move(self, allLeaves):
        leafMoves = self.prioritize_expansion_leaves(allLeaves)
        if self.target_player_gather_path is not None:
            leafMoves = list(where(leafMoves, lambda move: move.source not in self.target_player_gather_path.tileSet))
        if len(leafMoves) > 0:
            #self.curPath = None
            #self.curPathPrio = -1
            move = leafMoves[0]
            i = 0
            valid = True
            while move.source.isGeneral and not self.general_move_safe(move.dest):
                if self.general_move_safe(move.dest, True):
                    move.move_half = True
                    break
                else:
                    move = random.choice(leafMoves)
                    i += 1
                    if i > 10:
                        valid = False
                        break

            if valid:
                self.curPath = None
                self.curPathPrio = -1
                return move
        return None

    def prioritize_expansion_leaves(self, allLeaves = None, allowNonKill = False):
        queue = PriorityQueue()
        analysis = self.board_analysis.intergeneral_analysis
        for leafMove in allLeaves:
            if not allowNonKill and leafMove.source.army - leafMove.dest.army <= 1:
                continue
            if leafMove.dest.isCity and leafMove.dest.player == -1 and leafMove.dest.army > 25:
                continue

            dest = leafMove.dest
            source = leafMove.source
            if source not in analysis.pathWayLookupMatrix or dest not in analysis.pathWayLookupMatrix:
                continue
            if analysis.bMap[dest.x][dest.y] > analysis.aMap[self.targetPlayerExpectedGeneralLocation.x][self.targetPlayerExpectedGeneralLocation.y] + 2:
                continue
            if self.territories.territoryMap[dest.x][dest.y] != -1 and self.territories.territoryMap[dest.x][dest.y] != self.general.player and dest.player == -1:
                continue
            sourcePathway = analysis.pathWayLookupMatrix[source]
            destPathway = analysis.pathWayLookupMatrix[dest]

            points = 0

            if self.board_analysis.innerChokes[dest.x][dest.y]:
                # bonus points for retaking iChokes
                points += 0.1
            if not self.board_analysis.outerChokes[dest.x][dest.y]:
                # bonus points for avoiding oChokes
                points += 0.05

            if dest in self.board_analysis.intergeneral_analysis.pathChokes:
                points += 0.15

            towardsEnemy = analysis.bMap[dest.x][dest.y] < analysis.bMap[source.x][source.y]
            if towardsEnemy:
                points += 0.4

            awayFromUs = analysis.aMap[dest.x][dest.y] > analysis.aMap[source.x][source.y]
            if awayFromUs:
                points += 0.1

            if dest.player == self.targetPlayer:
                points += 1.5

            # extra points for tiles that are closer to enemy
            distEnemyPoints = analysis.aMap[dest.x][dest.y] / analysis.bMap[dest.x][dest.y]

            points += distEnemyPoints / 3

            logging.info("leafMove {}, points {:.2f} (distEnemyPoints {:.2f})".format(leafMove.toString(), points, distEnemyPoints))
            queue.put((0-points, leafMove))
        vals = []
        while not queue.empty():
            prio, move = queue.get()
            vals.append(move)
        return vals

    def getDistToEnemy(self, tile):
        dist = 1000
        for i in range(len(self._map.generals)):
            gen = self._map.generals[i]
            genDist = 0
            if gen is not None:
                genDist = self.euclidDist(gen.x, gen.y, tile.x, tile.y)
            elif self.generalApproximations[i][2] > 0:
                genDist = self.euclidDist(self.generalApproximations[i][0], self.generalApproximations[i][1], tile.x, tile.y)

            if genDist < dist:
                dist = genDist
        return dist

    def get_path_to_target_player(self, isAllIn = False, cutLength: typing.Union[None, int] = None):
        # TODO on long distances or higher city counts or FFA-post-kills don't use general path, just find max path to target player and gather to that

        self._evaluatedUndiscoveredCache = []

        fromTile = self.general
        maxTile: Tile = self.get_predicted_target_player_general_location()

        if maxTile is None:
            return None

        # self.viewInfo.addAdditionalInfoLine(f'maxTile {maxTile.toString()}')

        self.targetPlayerExpectedGeneralLocation = maxTile

        enemyDistMap = None
        if self.board_analysis is not None and self.board_analysis.intergeneral_analysis is not None and self.board_analysis.intergeneral_analysis.bMap is not None:
            enemyDistMap = self.board_analysis.intergeneral_analysis.bMap
        else:
            enemyDistMap = build_distance_map(self._map, [self.targetPlayerExpectedGeneralLocation])

        startTime = time.perf_counter()
        targetPlayerObj = None
        if self.targetPlayer != -1:
            targetPlayerObj = self._map.players[self.targetPlayer]
        if targetPlayerObj is None or not targetPlayerObj.knowsKingLocation:
            for genLaunchPoint in self.launchPoints:
                if genLaunchPoint is None:
                    logging.info("wtf genlaunchpoint was none????")
                elif enemyDistMap[genLaunchPoint.x][genLaunchPoint.y] < enemyDistMap[fromTile.x][fromTile.y]:
                    logging.info("using launchPoint {}".format(genLaunchPoint.toString()))
                    fromTile = genLaunchPoint

        preferNeut = self._map.remainingPlayers < 3
        preferNeut = not isAllIn
        path = self.get_path_to_target(maxTile, skipEnemyCities = isAllIn, preferNeutral = preferNeut, fromTile = fromTile, preferEnemy = not isAllIn)
        if cutLength is not None and path.length > cutLength:
            path = path.get_subsegment(cutLength, end = True)

        if self.targetPlayer == -1 and self._map.remainingPlayers > 2:
            # To avoid launching out into the middle of the FFA, just return the general tile and the next tile in the path as the path.
            # this sort of triggers camping-city-taking behavior at the moment.
            fakeGenPath = path.get_subsegment(1)
            logging.info("FakeGenPath because FFA: {}".format(fakeGenPath.toString()))
            return fakeGenPath
        return path

    def get_best_defense(self, tile: Tile, turns: int, negativeTileList: typing.List[Tile]):
        searchingPlayer = tile.player
        logging.info("Trying to get_best_defense. Turns {}. Searching player {}".format(turns, searchingPlayer))
        negativeTiles = set()

        for negTile in negativeTileList:
            negativeTiles.add(negTile)

        startTiles = [tile]

        def default_value_func_max_army(currentTile, priorityObject):
            (dist, negArmySum, xSum, ySum) = priorityObject
            return 0 - negArmySum, 0 - dist
        valueFunc = default_value_func_max_army

        def default_priority_func(nextTile, currentPriorityObject):
            (dist, negArmySum, xSum, ySum) = currentPriorityObject
            negArmySum += 1
            #if (nextTile not in negativeTiles):
            if searchingPlayer == nextTile.player:
                negArmySum -= nextTile.army
            else:
                negArmySum += nextTile.army

            #logging.info("prio: nextTile {} got realDist {}, negNextArmy {}, negNeutCount {}, newDist {}, xSum {}, ySum {}".format(nextTile.toString(), realDist + 1, 0-nextArmy, negNeutCount, dist + 1, xSum + nextTile.x, ySum + nextTile.y))
            return dist + 1, negArmySum, xSum + nextTile.x, ySum + nextTile.y
        priorityFunc = default_priority_func

        def default_base_case_func(tile, startingDist):
            return 0, 0, tile.x, tile.y
        baseCaseFunc = default_base_case_func


        startTilesDict = {}
        if isinstance(startTiles, dict):
            startTilesDict = startTiles
            for tile in startTiles.keys():
                negativeTiles.add(tile)
        else:
            for tile in startTiles:
                # then use baseCaseFunc to initialize their priorities, and set initial distance to 0
                startTilesDict[tile] = (baseCaseFunc(tile, 0), 0)
                #negativeTiles.add(tile)

        for tile in startTilesDict.keys():
            (startPriorityObject, distance) = startTilesDict[tile]
            logging.info("   Including tile {},{} in startTiles at distance {}".format(tile.x, tile.y, distance))

        valuePerTurnPath = breadth_first_dynamic_max(
            self._map,
            startTilesDict,
            valueFunc,
            0.1,
            turns,
            turns,
            noNeutralCities=True,
            negativeTiles = negativeTiles,
            searchingPlayer = searchingPlayer,
            priorityFunc = priorityFunc,
            ignoreStartTile = True,
            preferNeutral = False,
            noLog = True)

        if valuePerTurnPath is not None:
            logging.info("Best defense: {}".format(valuePerTurnPath.toString()))
            self.viewInfo.color_path(PathColorer(valuePerTurnPath, 255, 255, 255, 255, 10, 150))
        else:
            logging.info("Best defense: NONE")
        return valuePerTurnPath

    def info(self, text):
        self.viewInfo.infoText = text
        self.viewInfo.addAdditionalInfoLine(text)

    def get_path_to_target(self, target, maxTime=0.1, maxDepth=85, skipNeutralCities=True, skipEnemyCities=False,
                           preferNeutral=True, fromTile=None, preferEnemy=False):
        targets = set()
        targets.add(target)
        return self.get_path_to_targets(targets, maxTime, maxDepth, skipNeutralCities, skipEnemyCities, preferNeutral, fromTile, preferEnemy=preferEnemy)

    def get_path_to_targets(self, targets, maxTime=0.1, maxDepth=85, skipNeutralCities=True, skipEnemyCities=False,
                            preferNeutral=True, fromTile=None, preferEnemy=False):
        if fromTile is None:
            fromTile = self.general
        negativeTiles = None
        if skipEnemyCities:
            negativeTiles = set()
            for enemyCity in self.enemyCities:
                negativeTiles.add(enemyCity)
        skipFunc = None
        if skipEnemyCities:
            skipFunc = lambda tile, prioObject: tile.player != self.general.player and tile.isCity
                # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.

        def path_to_targets_priority_func(nextTile, currentPriorityObject):
            (dist, negEnemyTiles, negCityCount, negArmySum, xSum, ySum, goalIncrement) = currentPriorityObject
            dist += 1

            if nextTile.player == self.targetPlayer:
                negEnemyTiles -= 1
                if nextTile.isCity:
                    negCityCount -= 1

            if negativeTiles is None or next not in negativeTiles:
                if nextTile.player == self.general.player:
                    negArmySum -= nextTile.army
                else:
                    negArmySum += nextTile.army
            # always leaving 1 army behind. + because this is negative.
            negArmySum += 1
            # -= because we passed it in positive for our general and negative for enemy gen / cities
            negArmySum -= goalIncrement
            return dist, negEnemyTiles, negCityCount, negArmySum, xSum + nextTile.x, ySum + nextTile.y, goalIncrement

        startPriorityObject = (0, 0, 0, 0, 0, 0, 0.5)
        startTiles = {}
        startTiles[fromTile] = (startPriorityObject, 0)

        path = breadth_first_dynamic(self._map, startTiles, lambda tile, prioObj: tile in targets, maxTime, maxDepth, skipNeutralCities, negativeTiles = negativeTiles, preferNeutral = preferNeutral, skipFunc = skipFunc, priorityFunc = path_to_targets_priority_func)
        #path = breadth_first_dynamic(self._map, [fromTile], lambda tile, prioObj: tile in targets, maxTime, maxDepth, skipNeutralCities, negativeTiles = negativeTiles, preferNeutral = preferNeutral, skipFunc = skipFunc)
        if path is None:
            path = Path(0)
            path.add_next(self.general)
        return path

    def distance_from_general(self, sourceTile):
        if sourceTile == self.general:
            return 0
        val = 0

        if self._gen_distances:
            val = self._gen_distances[sourceTile.x][sourceTile.y]
        return val

    def distance_from_opp(self, sourceTile):
        if sourceTile == self.targetPlayerExpectedGeneralLocation:
            return 0
        val = 0
        if self.board_analysis and self.board_analysis.intergeneral_analysis:
            val = self.board_analysis.intergeneral_analysis.bMap[sourceTile.x][sourceTile.y]
        return val

    def distance_from_target_path(self, sourceTile):
        if sourceTile in self.shortest_path_to_target_player.tileSet:
            return 0

        val = 0
        if self.board_analysis and self.shortest_path_to_target_player_distances is not None:
            val = self.shortest_path_to_target_player_distances[sourceTile.x][sourceTile.y]
        return val

    def scan_map(self):
        self.general_safe_func_set[self.general] = self.general_move_safe
        self.leafMoves = []
        self.largeTilesNearEnemyKings: typing.Dict[Tile, typing.List[Tile]] = {}
        self.allUndiscovered = []
        self.largePlayerTiles = []
        player = self._map.players[self.general.player]
        largePlayerTileThreshold = player.standingArmy / player.tileCount * 5
        general = self._map.generals[self._map.player_index]
        generalApproximations = [[0, 0, 0, None] for i in range(len(self._map.generals))]
        for x in range(general.x - 1, general.x + 2):
            for y in range(general.y - 1, general.y + 2):
                if x == general.x and y == general.y:
                    continue
                tile = self._map.GetTile(x, y)
                if tile is not None and tile.player != general.player and tile.player != -1:
                    self._map.players[tile.player].knowsKingLocation = True

        for enemyGen in self._map.generals:
            if enemyGen is not None and enemyGen.player != self._map.player_index:
                self.largeTilesNearEnemyKings[enemyGen] = []
        if not self.targetPlayerExpectedGeneralLocation.isGeneral:
            # self.targetPlayerExpectedGeneralLocation.player = self.targetPlayer
            self.largeTilesNearEnemyKings[self.targetPlayerExpectedGeneralLocation] = []

        for x in range(self._map.cols):
            for y in range(self._map.rows):
                tile = self._map.grid[y][x]
                if tile.discovered and tile.player == -1:
                    tile.discoveredAsNeutral = True
                if not tile.discovered and not tile.isNotPathable:
                    self.allUndiscovered.append(tile)

                if tile.player != self._map.player_index and tile.player >= 0 and self._map.generals[tile.player] is None:
                    for nextTile in tile.movable:
                        if not nextTile.discovered and not nextTile.isNotPathable:
                            approx = generalApproximations[tile.player]
                            approx[0] += nextTile.x
                            approx[1] += nextTile.y
                            approx[2] += 1

                if tile.player == self._map.player_index:
                    for nextTile in tile.movable:
                        if nextTile.player != self._map.player_index and not nextTile.isMountain:
                            self.leafMoves.append(Move(tile, nextTile))
                    if tile.army > largePlayerTileThreshold:
                        self.largePlayerTiles.append(tile)

                elif tile.player != -1:
                    if tile.isCity:
                        self.enemyCities.append(tile)
                ## No idea what this was supposed to do. wtf
                #if (not tile.visible and not ((tile.isCity or tile.isGeneral) and self._map.turn > 250) and (self._map.turn - tile.lastSeen >= 100 or (self._map.turn - tile.lastSeen > 25 and tile.army > 25))):
                #    player = self._map.players[tile.player]
                #    if player.tileCount > 0:
                #        tile.army = int((player.standingArmy / player.tileCount) / (player.cityCount / 2 + 1))
                ## Same thing as above but for cities?
                #if (not tile.visible and tile.isCity and tile.player != -1 and self._map.turn - tile.lastSeen > 25):
                #    player = self._map.players[tile.player]
                #    if player.cityCount > 0:
                #        tile.army = int((player.standingArmy / player.cityCount) / 8)
                if tile.player == self._map.player_index and tile.army > 5:
                    for enemyGen in self.largeTilesNearEnemyKings.keys():
                        if tile.army > enemyGen.army and self.euclidDist(tile.x, tile.y, enemyGen.x, enemyGen.y) < 12:
                            self.largeTilesNearEnemyKings[enemyGen].append(tile)

        self.pathableTiles = self._map.pathableTiles

        # wtf is this doing
        for i in range(len(self._map.generals)):
            if self._map.generals[i] is not None:
                gen = self._map.generals[i]
                generalApproximations[i][0] = gen.x
                generalApproximations[i][1] = gen.y
                generalApproximations[i][3] = gen
            elif generalApproximations[i][2] > 0:

                generalApproximations[i][0] = generalApproximations[i][0] / generalApproximations[i][2]
                generalApproximations[i][1] = generalApproximations[i][1] / generalApproximations[i][2]

                #calculate vector
                delta = ((generalApproximations[i][0] - general.x) * 1.1, (generalApproximations[i][1] - general.y) * 1.1)
                generalApproximations[i][0] = general.x + delta[0]
                generalApproximations[i][1] = general.y + delta[1]
        for i in range(len(self._map.generals)):
            gen = self._map.generals[i]
            genDist = 1000

            if gen is None and generalApproximations[i][2] > 0:
                for tile in self.pathableTiles:
                    if not tile.discovered and not tile.isNotPathable:
                        tileDist = self.euclidDist(generalApproximations[i][0], generalApproximations[i][1], tile.x, tile.y)
                        if tileDist < genDist and self.distance_from_general(tile) < 1000:
                            generalApproximations[i][3] = tile
                            genDist = tileDist

        self.generalApproximations = generalApproximations

        self.targetPlayer = self.calculate_target_player()

        self.targetPlayerObj = self._map.players[self.targetPlayer]

    def determine_should_winning_all_in(self):
        if self.targetPlayer < 0:
            return False

        targetPlayer: Player = self._map.players[self.targetPlayer]
        thisPlayer: Player = self._map.players[self.general.player]

        factoredArmyThreshold = targetPlayer.standingArmy * 2.2 - targetPlayer.tileCount / 20

        if thisPlayer.standingArmy < 50:
            return False

        # if already all in, keep pushing for longer
        if self.all_in_army_advantage:
            factoredArmyThreshold = targetPlayer.standingArmy * 1.3 - targetPlayer.tileCount / 10

        if thisPlayer.standingArmy > factoredArmyThreshold:
            self.viewInfo.addAdditionalInfoLine(
                f"DEBUG: ARMY ADVANTAGE OF {thisPlayer.standingArmy} vs {targetPlayer.standingArmy} ({factoredArmyThreshold})")
            self.viewInfo.addAdditionalInfoLine(f"GOING ALL IN DUE TO ARMY ADVANTAGE OF {thisPlayer.standingArmy} vs {targetPlayer.standingArmy}")
            return True

        return False

    def find_expected_1v1_general_location_on_undiscovered_map(
            self,
            undiscoveredCounterDepth: int,
            minSpawnDistance: int
    ) -> typing.List[typing.List[int]]:
        # finding path to some predicted general location in neutral territory
        # TODO look into the void and see it staring back at yourself
        # find mirror spot in the void? Or just discover the most tiles possible.
        # Kind of done. Except really, shouldn't be BFSing with so much CPU for this lol.
        localMaxTile = self.general
        maxAmount: int = 0
        grid = [[0 for y in range(self._map.rows)] for x in range(self._map.cols)]

        def tile_meets_criteria_for_value_around_general(tile: Tile) -> bool:
            return ((not tile.discovered)
                and not (tile.isNotPathable or tile.isMountain))

        def tile_meets_criteria_for_general(tile: Tile) -> bool:
            return tile_meets_criteria_for_value_around_general(tile) and self.distance_from_general(tile) >= minSpawnDistance


        for tile in self.pathableTiles:
            if tile_meets_criteria_for_general(tile):
                # if not divide by 2, overly weights far tiles. Prefer mid-far central tiles
                genDist = self.distance_from_general(tile) / 2
                distFromCenter = self.get_distance_from_board_center(tile, center_ratio=0.25)

                counter = Counter(genDist - distFromCenter)
                self.viewInfo.bottomLeftGridText[tile.x][tile.y] = genDist - distFromCenter

                # the lambda for counting stuff!
                def count_undiscovered(curTile):
                    if tile_meets_criteria_for_value_around_general(curTile):
                        counter.add(1)

                breadth_first_foreach(self._map, [tile], undiscoveredCounterDepth, count_undiscovered, noLog=True)

                grid[tile.x][tile.y] = counter.value

                if counter.value > maxAmount:
                    localMaxTile = tile
                    maxAmount = counter.value

        if self.targetPlayer == -1:
            def mark_undiscovered(curTile):
                if tile_meets_criteria_for_value_around_general(curTile):
                    self._evaluatedUndiscoveredCache.append(curTile)
                    self.viewInfo.evaluatedGrid[curTile.x][curTile.y] = 1

            breadth_first_foreach(self._map, [localMaxTile], undiscoveredCounterDepth, mark_undiscovered, noLog=True)

        return grid

    def prune_timing_split_if_necessary(self):
        splitTurn = self.timings.get_turn_in_cycle(self._map.turn)
        tilesUngathered = count(self.pathableTiles, lambda tile: tile.player == self.general.player
                                                                  and tile not in self.target_player_gather_path.tileSet
                                                                  and tile.army > 1)
        player = self._map.players[self.general.player]
        if tilesUngathered - player.cityCount - 1 < 1:
            timingAdjusted = splitTurn + tilesUngathered
            if timingAdjusted < self.timings.launchTiming:
                self.viewInfo.addAdditionalInfoLine(f"Moving up launch timing from {self.timings.launchTiming} to splitTurn {splitTurn} + tilesUngathered {tilesUngathered} = ({timingAdjusted})")
                self.timings.launchTiming = timingAdjusted
                self.timings.splitTurns = timingAdjusted

    def get_distance_from_board_center(self, tile, center_ratio = 0.25) -> float:
        distFromCenterX = abs((self._map.cols / 2) - tile.x)
        distFromCenterY = abs((self._map.rows / 2) - tile.y)

        distFromCenterX -= self._map.cols * center_ratio
        distFromCenterY -= self._map.rows * center_ratio

        # prioritize the center box equally
        if distFromCenterX < 0:
            distFromCenterX = 0
        if distFromCenterY < 0:
            distFromCenterY = 0
        return distFromCenterX + distFromCenterY

    def get_predicted_target_player_general_location(self, skipDiscoveredAsNeutralFilter: bool = False):
        minSpawnDist = 15
        if self._map.remainingPlayers > 2:
            minSpawnDist = 9


        if self.targetPlayer == -1:
            return self.get_max_explorable_undiscovered_tile(minSpawnDist)

        if self._map.generals[self.targetPlayer] is not None:
            return self._map.generals[self.targetPlayer]


        maxTile = self.general
        values = [[0.0 for x in range(self._map.rows)] for y in range(self._map.cols)]

        def skipPlayerAndDiscoveredFunc(tile):
            if tile.player == self.general.player \
                    or (not skipDiscoveredAsNeutralFilter and tile.discoveredAsNeutral) \
                    or tile.isNotPathable \
                    or tile.isMountain:
                return True
            return False

        enemyCounter = Counter(0)
        undiscCounter = Counter(0)


        # the lambda for counting stuff! Lower weight for undiscovereds, we prefer enemy tiles.
        def undiscoveredEnemyCounter(tile):
            if tile.isNotPathable or tile.isMountain:
                return

            discoveredNonEnemy = tile.discovered and (tile.player == -1 or tile.player == self.general.player)
            if discoveredNonEnemy:
                return

            if not tile.discovered:
                if self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer:
                    undiscCounter.add(1)
            if self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y] > 0:
                undiscCounter.add(0.1)
            if tile.player == self.targetPlayer:
                enemyCounter.add(1)


        maxOldTile = maxTile
        maxOldAmount = -1

        maxAmount = -1
        undiscoveredCounterDepth = 6

        for tile in self.pathableTiles:
            if tile.discovered or tile.isMountain or tile.isNotPathable:
                continue

            # if (self._map.remainingPlayers > 2
            #         and 0 == count(tile.adjacents, lambda adjTile: adjTile.player == self.targetPlayer)
            # ):
            #     # in FFA, don't evaluate tiles other than those directly next to enemy tiles (to avoid overshooting into 3rd party territory)
            #     continue

            if self.distance_from_general(tile) < minSpawnDist:
                continue

            undiscCounter.value = 0
            enemyCounter.value = 0

            breadth_first_foreach(self._map, [tile], undiscoveredCounterDepth, undiscoveredEnemyCounter,
                                  noLog=True, skipFunc=skipPlayerAndDiscoveredFunc)
            foundValue = 10 * enemyCounter.value + undiscCounter.value
            if enemyCounter.value > 0 and foundValue > maxOldAmount:
                maxOldTile = tile
                maxOldAmount = foundValue

            if foundValue > 0:
                self.viewInfo.bottomLeftGridText[tile.x][tile.y] = foundValue

            if self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y] > 0:
                # foundValue += emergenceLogFactor * math.log(self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y], 2)
                foundValue += self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y] * 10
            values[tile.x][tile.y] = foundValue
            if enemyCounter.value > 0 and foundValue > maxAmount:
                maxTile = tile
                maxAmount = foundValue
            if foundValue > 0:
                self.viewInfo.midRightGridText[tile.x][tile.y] = foundValue // 10

        self.viewInfo.add_targeted_tile(maxOldTile, TargetStyle.GOLD)
        self.viewInfo.add_targeted_tile(maxTile, TargetStyle.BLUE)

        if (maxTile == self.general or maxTile == None) and not skipDiscoveredAsNeutralFilter:
            self.viewInfo.addAdditionalInfoLine("target path failed, retry without forcing discoveredAsNeutral.")
            tile = self.get_predicted_target_player_general_location(skipDiscoveredAsNeutralFilter=True)
            if tile != self.general and tile is not None and not tile.isObstacle:
                maxTile = tile

        if (maxTile == self.general or maxTile is None or maxTile.isObstacle) and self.targetPlayer != -1:
            for tile in self._map.get_all_tiles():
                if tile.player == self.targetPlayer:
                    for adjTile in tile.movable:
                        if not adjTile.discovered and not adjTile.isObstacle:
                            self.viewInfo.addAdditionalInfoLine("target path failed, falling back to a random tile adjacent to enemy tile.")
                            return adjTile

        if maxTile == self.general or maxTile is None or maxTile.isObstacle:
            self.viewInfo.addAdditionalInfoLine("target path failed, falling back to undiscovered path.")
            fallbackTile = self.get_max_explorable_undiscovered_tile(minSpawnDist)

            if fallbackTile is None or fallbackTile == self.general:
                self.viewInfo.addAdditionalInfoLine("target path fallback failed, returning tile next to general.")
                return self.general.movable[0]
            return fallbackTile

        self.undiscovered_priorities = values

        logging.info("OLD PREDICTION = {}".format(maxOldTile.toString()))

        logging.info("NEW PREDICTION = {} ??????".format(maxTile.toString()))

        logging.info(
            f"Highest density undiscovered tile {maxTile.x},{maxTile.y} with value {maxAmount} found")

        return maxTile

    def is_player_spawn_cramped(self, spawnDist = 12):
        tiles = [self.general]

        counter = Counter(0)

        # if we dont find enemy territory (which is around halfway point)
        spawnDist = spawnDist / 2.0

        def count_neutral(curTile: Tile):
            tileTerritory = self.territories.territoryMap[curTile.x][curTile.y]
            isTileContested = curTile.player != self.general.player and curTile.player >= 0
            isTileContested |= tileTerritory != self.general.player and tileTerritory >= 0
            if not curTile.isNotPathable:
                counter.add(0.5)
            if not isTileContested:
                counter.add(0.5)

        counter.value = 0
        breadth_first_foreach(self._map, tiles, 8, count_neutral, noLog=True)
        count8 = counter.value

        counter.value = 0
        breadth_first_foreach(self._map, tiles, 6, count_neutral, noLog=True)
        count6 = counter.value

        counter.value = 0
        breadth_first_foreach(self._map, tiles, 4, count_neutral, noLog=True)
        count4 = counter.value

        if self.targetPlayer != -1:
            enemyTerritoryFoundCounter = Counter(0)
            targetPlayer: Player = self._map.players[self.targetPlayer]
            visibleTiles = [t for t in filter(lambda tile: tile.visible, targetPlayer.tiles)]
            enemyVisibleTileCount = len(visibleTiles)


            def count_enemy_territory(curTile: Tile, object):
                tileTerritory = self.territories.territoryMap[curTile.x][curTile.y]
                isTileContested = tileTerritory != self.general.player and tileTerritory >= 0
                if isTileContested:
                    enemyTerritoryFoundCounter.add(1)

                if enemyTerritoryFoundCounter.value > enemyVisibleTileCount:
                    return True

                return False


            path = breadth_first_dynamic(
                self._map,
                tiles,
                count_enemy_territory,
                noNeutralCities=True,
                searchingPlayer=self.general.player)

            if path is not None:
                territoryTile = path.tileList[-1]
                self.viewInfo.add_targeted_tile(territoryTile, TargetStyle.GOLD)
                self.viewInfo.addAdditionalInfoLine(f"found enemy territory at dist {path.length} {territoryTile.toString()}")

                spawnDist = path.length

        spawnDistFactor = spawnDist - 10

        thisPlayer = self._map.players[self.general.player]
        cap8 = 68 - 9 * (thisPlayer.cityCount - 1) + spawnDistFactor
        cap6 = 42 - 6 * (thisPlayer.cityCount - 1) + spawnDistFactor
        cap4 = 21 - 3 * (thisPlayer.cityCount - 1) + spawnDistFactor

        cramped = False
        if count8 < cap8 or count6 < cap6 or count4 < cap4:
            cramped = True

        self.viewInfo.addAdditionalInfoLine(f"Cramped: {cramped} 8[{count8}/{cap8}] 6[{count6}/{cap6}] 4[{count4}/{cap4}] spawnDistFactor[{spawnDistFactor}]")
        # logging.info(f"NOT Cramped: 8[{count8}/{cap8}] 6[{count6}/{cap6}] 4[{count4}/{cap4}] spawnDistFactor[{spawnDistFactor}]")

        return cramped

    def timing_cycle_ended(self):
        self.viewInfo.addAdditionalInfoLine(f'Timing cycle ended, turn {self._map.turn}')
        self.cities_gathered_this_cycle = set()
        player = self._map.players[self.general.player]
        cityCount = player.cityCount

        citiesAvoided = 0
        if player.cityCount > 3:
            for city in sorted(player.cities, key=lambda c: c.army):
                citiesAvoided += 1
                self.viewInfo.addAdditionalInfoLine(f'AVOIDING CITY {str(city)}')
                if citiesAvoided >= cityCount // 2:
                    break

    def dump_turn_data_to_string(self):
        charMap = {
            0: 'a',
            1: 'b',
            2: 'c',
            3: 'd',
            4: 'e',
            5: 'f',
            6: 'g',
            7: 'h'
        }

        data = []
        if self.targetPlayerExpectedGeneralLocation:
            data.append(f'targetPlayerExpectedGeneralLocation={self.targetPlayerExpectedGeneralLocation.x},{self.targetPlayerExpectedGeneralLocation.y}')
        data.append(f'turn={self._map.turn}')
        data.append(f'bot_player_index={self._map.player_index}')

        for player in self._map.players:
            char = charMap[player.index]
            data.append(f'{char}Tiles={player.tileCount}')
            data.append(f'{char}Score={player.score}')
            data.append(f'{char}StandingArmy={player.standingArmy}')
            data.append(f'{char}Stars={player.stars}')
            data.append(f'{char}CityCount={player.cityCount}')
            if player.general is not None:
                data.append(f'{char}General={player.general.x},{player.general.y}')
            data.append(f'{char}KnowsKingLocation={player.knowsKingLocation}')
            data.append(f'{char}Dead={player.dead}')
            data.append(f'{char}LeftGame={player.leftGame}')
            data.append(f'{char}LeftGameTurn={player.leftGameTurn}')

        data.append(f'bot_target_player={self.targetPlayer}')
        if self.targetingArmy:
            data.append(f'bot_targeting_army={self.targetingArmy.tile.x},{self.targetingArmy.tile.y}')

        return '\n'.join(data)

    def is_move_safe_against_threats(self, move: Move):
        if not self.threat:
            return True

        if self.threat.threatType != ThreatType.Kill:
            return True

        # if attacking the threat, then cool
        if move.dest == self.threat.path.start.tile or move.dest == self.threat.path.start.next.tile:
            return True

        chokes = self.threat.armyAnalysis.pathChokes
        # if moving out of a choke, dont
        if move.source in chokes and move.dest not in chokes:
            self.viewInfo.addAdditionalInfoLine(f'not allowing army move out of threat choke {str(move.source)}')
            return False

        if move.source in self.threat.path.tileSet and move.dest not in self.threat.path.tileSet:
            self.viewInfo.addAdditionalInfoLine(f'not allowing army move out of threat path {str(move.source)}')
            return False

        return True

    def get_gather_to_threat_path(
            self,
            threat: ThreatObj,
            force_turns_up_threat_path = 0,
            gatherMax: bool = True,
            shouldLog: bool = False,
            addlTurns: int = 0
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[TreeNode]]:
        """
        returns move, valueGathered, turnsUsed

        @param threat:
        @param force_turns_up_threat_path:
        @param gatherMax:
        @param shouldLog:
        @param addlTurns: if you want to gather longer than the threat, for final save.
        @return:
        """
        gatherDepth = threat.path.length - 1 + addlTurns
        distDict = threat.convert_to_dist_dict()
        tail = threat.path.tail
        for i in range(force_turns_up_threat_path):
            if tail is not None:
                self.viewInfo.add_targeted_tile(tail.tile, TargetStyle.GREEN)
                del distDict[tail.tile]
                tail = tail.prev

        distMap = build_distance_map(self._map, [threat.path.tail.tile])

        def move_closest_priority_func(nextTile, currentPriorityObject):
            return (
                nextTile in threat.armyAnalysis.shortestPathWay.tiles,
                0 - distMap[nextTile.x][nextTile.y],
                0 - nextTile.army
            )

        def move_closest_value_func(curTile, currentPriorityObject):
            return (
                curTile not in threat.armyAnalysis.shortestPathWay.tiles,
                distMap[curTile.x][curTile.y],
                curTile.army
            )

        targetArmy = threat.threatValue
        if gatherMax:
            targetArmy = -1

        move, value, turnsUsed, gatherNodes = self.get_gather_to_target_tiles(
            distDict,
            maxTime=0.05,
            gatherTurns=gatherDepth,
            targetArmy=targetArmy,
            useTrueValueGathered=False,
            leafMoveSelectionPriorityFunc=move_closest_priority_func,
            leafMoveSelectionValueFunc=move_closest_value_func,
            includeTreeNodesThatGatherNegative=True,
            shouldLog=shouldLog)
        logging.info(f'get_gather_to_threat_path for depth {gatherDepth} force_turns_up_threat_path {force_turns_up_threat_path} returned {str(move)}, val {value} turns {turnsUsed}')

        return move, value, turnsUsed, gatherNodes

    def get_gather_to_threat_path_greedy(
            self,
            threat: ThreatObj,
            force_turns_up_threat_path = 0,
            gatherMax: bool = True,
            shouldLog: bool = False
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[TreeNode]]:
        """
        Greedy is faster than the main knapsack version.
        returns move, valueGathered, turnsUsed

        @return:
        """
        gatherDepth = threat.path.length - 1
        distDict = threat.convert_to_dist_dict()
        tail = threat.path.tail
        for i in range(force_turns_up_threat_path):
            if tail is not None:
                self.viewInfo.add_targeted_tile(tail.tile, TargetStyle.GREEN)
                del distDict[tail.tile]
                tail = tail.prev

        distMap = build_distance_map(self._map, [threat.path.start.tile])

        def move_closest_priority_func(nextTile, currentPriorityObject):
            return nextTile in threat.armyAnalysis.shortestPathWay.tiles, distMap[nextTile.x][nextTile.y]

        def move_closest_value_func(curTile, currentPriorityObject):
            return curTile not in threat.armyAnalysis.shortestPathWay.tiles, 0-distMap[curTile.x][curTile.y]

        targetArmy = threat.threatValue
        if gatherMax:
            targetArmy = -1

        move, value, turnsUsed, gatherNodes = self.get_gather_to_target_tiles_greedy(
            distDict,
            maxTime=0.05,
            gatherTurns=gatherDepth,
            targetArmy=targetArmy,
            useTrueValueGathered=True,
            priorityFunc=move_closest_priority_func,
            valueFunc=move_closest_value_func,
            includeTreeNodesThatGatherNegative=True,
            shouldLog=shouldLog)
        logging.info(f'get_gather_to_threat_path for depth {gatherDepth} force_turns_up_threat_path {force_turns_up_threat_path} returned {str(move)}, val {value} turns {turnsUsed}')

        return move, value, turnsUsed, gatherNodes

    def recalculate_player_paths(self, force: bool = False):
        reevaluate = force
        if len(self._evaluatedUndiscoveredCache) > 0:
            for tile in self._evaluatedUndiscoveredCache:
                if tile.discovered:
                    reevaluate = True
        intentionallyGatheringAtNonGeneralTarget = self.target_player_gather_path is None or (not self.target_player_gather_path.tail.tile.isGeneral and self._map.generals[self.targetPlayer] is not None)
        if (self.target_player_gather_path is None
                    or reevaluate
                    or self.target_player_gather_path.tail.tile.isCity
                    or self._map.turn % 50 < 2
                    or self._map.turn < 100
                    or intentionallyGatheringAtNonGeneralTarget
                    or self.curPath is None):
            self.shortest_path_to_target_player = self.get_path_to_target_player(isAllIn=self.is_all_in(), cutLength=None)

            self.target_player_gather_path = self.shortest_path_to_target_player

            if self.target_player_gather_path.length > 20 and self._map.players[self.general.player].cityCount > 1:
                self.target_player_gather_path = self.target_player_gather_path.get_subsegment(20, end=True)

            self.target_player_gather_targets = self.target_player_gather_path.tileSet

        spawnDist = 12
        if self.target_player_gather_path is not None:
            spawnDist = self.shortest_path_to_target_player.length

        with self.perf_timer.begin_move_event('calculating is_player_spawn_cramped'):
            self.force_city_take = self.is_player_spawn_cramped(spawnDist) and self._map.turn > 150

        if self.targetPlayerExpectedGeneralLocation is not None:
            with self.perf_timer.begin_move_event('rebuilding intergeneral_analysis'):
                self.board_analysis.rebuild_intergeneral_analysis(self.targetPlayerExpectedGeneralLocation)
                if len(self.board_analysis.intergeneral_analysis.shortestPathWay.tiles) > 0:
                    self.shortest_path_to_target_player_distances = build_distance_map(
                        self._map,
                        [tile for tile in self.board_analysis.intergeneral_analysis.shortestPathWay.tiles],
                        [])

    def check_for_1_move_kills(self) -> typing.Union[None, Move]:
        """
        due to enemy_army_near_king logic, need to explicitly check for 1-tile-kills that we might win on luck
        @return:
        """
        for enemyGeneral in self._map.generals:
            if enemyGeneral is None or enemyGeneral == self.general:
                continue

            for adj in enemyGeneral.movable:
                if adj.player == self.general.player and adj.army - 1 > enemyGeneral.army:
                    logging.info("Adjacent kill on general lul :^) {},{}".format(enemyGeneral.x, enemyGeneral.y))
                    return Move(adj, enemyGeneral)

        return None

    def check_for_king_kills_and_races(self, threat: ThreatObj, force: bool=False) -> typing.Tuple[typing.Union[Move, None], typing.Union[Path, None], bool]:
        """

        @param threat:
        @return: (kill move/none, kill path / none, boolean for whether the killpath can race current threat)
        """
        kingKillPath = None
        canRace = False
        alwaysCheckKingKillWithinRange = 5
        if self.target_player_gather_path is not None:
            alwaysCheckKingKillWithinRange = min(alwaysCheckKingKillWithinRange, self.target_player_gather_path.length // 4)
            # increasing this causes the bot to dive kings way too often with stuff that doesn't regularly kill, and kind of just kamikaze's its army without optimizing tile captures.
        if self.allIn:
            alwaysCheckKingKillWithinRange = 7

        for enemyGeneral in self.largeTilesNearEnemyKings.keys():
            if enemyGeneral is None or enemyGeneral.player == self.general.player or enemyGeneral.player in self._map.teammates:
                continue

            thisPlayerDepth = alwaysCheckKingKillWithinRange
            attackNegTiles = set()
            targetArmy = enemyGeneral.army
            enPlayer = enemyGeneral.player
            if enPlayer == -1:
                enPlayer = self.targetPlayer

            nonGenArmy = 0
            if not enemyGeneral.isGeneral:
                targetArmy = nonGenArmy = 2 + int(self._map.players[enPlayer].standingArmy ** 0.5)
                thisPlayerDepth = max(2, thisPlayerDepth - 2)

            logging.info(
                f"Performing depth increasing BFS kill search on enemy king {enemyGeneral.toString()} depth {thisPlayerDepth}")
            for depth in range (2, thisPlayerDepth):
                enemyNegTiles = []
                if threat is not None:
                    enemyNegTiles.append(threat.path.start.tile)
                enemySavePath = self.get_best_defense(enemyGeneral, depth - 1, enemyNegTiles)
                if enemySavePath is not None:
                    targetArmy = enemyGeneral.army + enemySavePath.value + nonGenArmy
                    logging.info(f"  targetArmy {targetArmy}, enemySavePath {enemySavePath.toString()}")
                    attackNegTiles = enemySavePath.tileSet.copy()
                    attackNegTiles.remove(enemyGeneral)
                logging.info(f"  targetArmy to add to enemyGeneral kill = {targetArmy}")
                killPath = dest_breadth_first_target(self._map, [enemyGeneral], max(targetArmy, 1), 0.05, depth, attackNegTiles, self.general.player, False, 3, noLog = True)
                if killPath is not None and killPath.length > 0:
                    logging.info(f"    depth {depth} path found to kill enemy king? {killPath.toString()}")
                    if threat is None or (threat.turns >= killPath.length):
                        logging.info(f"    DEST BFS K found kill path length {killPath.length} :^)")
                        self.viewInfo.color_path(PathColorer(killPath, 255, 240, 79, 244, 5, 200))
                        move = Move(killPath.start.tile, killPath.start.next.tile)
                        self.curPath = None
                        if killPath.start.next.tile.isCity:
                            self.curPath = killPath
                        if self.is_move_safe_valid(move):
                            self.viewInfo.infoText = f"Depth increasing Killpath against general length {killPath.length}"
                            return (move, killPath, canRace)
                    else:
                        logging.info(
                            f"    DEST BFS K found kill path {killPath.toString()} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
                        if kingKillPath is None:
                            logging.info("      saving above kingKillPath as backup in case we can't defend threat")
                            if threat.turns + 1 == killPath.length:
                                logging.info("       CAN RACE THOUGH!")
                                canRace = True
                            kingKillPath = killPath

            rangeBasedOnDistance = int(self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3 - 1)
            additionalKillArmyRequirement = 0
            if not force and (not self.winning_on_army(byRatio=1.3)
                and not self.winning_on_army(byRatio=1.3, againstPlayer=self.targetPlayer)
                and (threat is None or threat.threatType != ThreatType.Kill)
                and not self.is_all_in()):

                rangeBasedOnDistance = int(self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 4 - 1)
                # TEST THIS:
                # for i in [25, 50, 85, 110, 160, 250, 400, 800]:
                #     print(f'{i} -> {i ** 0.7}')
                # 25 -> 0.518269693579391
                # 50 -> 6.462474735549584
                # 85 -> 13.41781330242513
                # 110 -> 17.851891249034473
                # 160 -> 25.90470628408384
                # 250 -> 38.70435256643359
                # 400 -> 57.28908034679972
                # 800 -> 98.68692872787821

                additionalKillArmyRequirement = max(0, int(self._map.players[self.general.player].standingArmy ** 0.7) - 9)
                logging.info(f'additional kill army requirement is currently {additionalKillArmyRequirement}')

            depth = max(alwaysCheckKingKillWithinRange, rangeBasedOnDistance)

            if self.allIn:
                depth += 5

            logging.info(f"Performing depth {depth} BFS kill search on enemy king {enemyGeneral.toString()}")
            # uses targetArmy from depth 6 above
            killPath = dest_breadth_first_target(self._map, [enemyGeneral], targetArmy + additionalKillArmyRequirement, 0.05, depth, attackNegTiles, self.general.player, False, 3)
            if (killPath is not None and killPath.length >= 0) and (threat is None or (threat.turns >= killPath.length)):
                logging.info(f"DEST BFS K found kill path length {killPath.length} :^)")
                self.curPath = None
                self.viewInfo.color_path(PathColorer(killPath, 200, 100, 0))
                move = Move(killPath.start.tile, killPath.start.next.tile)

                if self.is_move_safe_valid(move):
                    self.viewInfo.infoText = f"destbfs Killpath against general length {killPath.length}"
                    return (move, killPath, canRace)

            elif killPath is not None and killPath.length > 0:
                logging.info(
                    f"DEST BFS K found kill path {killPath.toString()} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
                if kingKillPath is None:
                    logging.info("  saving above kingKillPath as backup in case we can't defend threat")
                    if threat.turns + 1 == killPath.length:
                        self.viewInfo.addAdditionalInfoLine("     CAN RACE THOUGH!")
                        canRace = True

                    kingKillPath = killPath

            king = enemyGeneral
            tiles = self.largeTilesNearEnemyKings[king]
            if len(tiles) > 0:
                logging.info(f"Attempting to find A_STAR kill path against general {king.player} ({king.x},{king.y})")
                bestTurn = 1000
                bestPath = None
                path = a_star_kill(
                    self._map,
                    tiles,
                    king,
                    0.03,
                    self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 4,
                    self.general_safe_func_set,
                    requireExtraArmy = targetArmy + additionalKillArmyRequirement,
                    negativeTiles = attackNegTiles)

                if (path is not None and path.length >= 0) and (threat is None or ((threat.turns >= path.length or self.allIn) and threat.threatPlayer == king.player)):
                    logging.info(f"  A_STAR found kill path length {path.length} :^)")
                    self.viewInfo.color_path(PathColorer(path, 174, 4, 214, 255, 10, 200))
                    self.curPath = path.get_subsegment(2)
                    self.curPathPrio = 5
                    if path.length < bestTurn:
                        bestPath = path
                        bestTurn = path.length
                elif path is not None and path.length > 0:
                    logging.info(f"  A_STAR found kill path {path.toString()} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
                    self.viewInfo.color_path(PathColorer(path, 114, 4, 194, 255, 20, 100))
                    if kingKillPath is None:
                        logging.info("    saving above kingKillPath as backup in case we can't defend threat")
                        if threat.turns + 1 == path.length:
                            self.viewInfo.addAdditionalInfoLine("     CAN RACE THOUGH!")
                            canRace = True
                        kingKillPath = path
                if bestPath is not None:
                    self.info(f"A* Killpath! {king.toString()},  {bestPath.toString()}")
                    self.viewInfo.lastEvaluatedGrid[king.x][king.y] = 200
                    move = Move(bestPath.start.tile, bestPath.start.next.tile)
                    return move, path, canRace
        return None, kingKillPath, canRace

    def calculate_target_player(self) -> int:
        targetPlayer = -1
        playerScore = -100000
        minStars = 10000
        starSum = 0
        for player in self._map.players:
            minStars = min(minStars, player.stars)
            starSum += player.stars
        starAvg = starSum * 1.0 / len(self._map.players)
        self.playerTargetScores = [0 for i in range(len(self._map.players))]
        generalPlayer = self._map.players[self.general.player]

        for player in self._map.players:
            seenPlayer = self.generalApproximations[player.index][2] > 0 or self._map.generals[player.index] is not None
            if not player.dead and player.index != self._map.player_index and seenPlayer:
                curScore = 300

                alreadyTargetingBonus = 120
                if player.index == self.targetPlayer:
                    curScore += alreadyTargetingBonus

                knowsWhereEnemyGeneralIsBonus = 100
                if self._map.generals[player.index] is not None:
                    curScore += knowsWhereEnemyGeneralIsBonus

                # target players with better economies first
                #curScore += (player.tileCount + player.cityCount * 20 - player.standingArmy ** 0.88) / 4

                if generalPlayer.standingArmy > player.standingArmy * 0.7:
                    # target players with better economies first more when we are winning
                    curScore += player.cityCount * 20
                    curScore += player.tileCount
                    # 30% bonus for winning
                    curScore *= 1.3

                if player.knowsKingLocation:
                    curScore += 150
                    curScore *= 2

                if self.generalApproximations[player.index][3] is not None:
                    genDist = self.distance_from_general(self.generalApproximations[player.index][3])
                else:
                    logging.info("           wot {} didn't have a gen approx tile???".format(self._map.usernames[targetPlayer]))
                    genDist = self.euclidDist(self.generalApproximations[player.index][0], self.generalApproximations[player.index][1], self.general.x, self.general.y)
                curScore = curScore + 2 * curScore / (max(10, genDist) - 2)

                if player.index != self.targetPlayer:
                    curScore = curScore / 2

                # deprio small players
                if (player.tileCount < 4 and player.general is None) or (player.general is not None and player.general.army > player.standingArmy * 0.6):
                    curScore = -100

                # losing massively to this player? -200 to target even single tile players higher than big fish
                if self._map.remainingPlayers > 2 and not self.winning_on_army(0.7, False, player.index) and not self.winning_on_economy(0.7, 20, player.index):
                    curScore = -200

                if 'PurdBlob' in self._map.usernames[player.index]:
                    curScore += 300

                if 'PurdPath' in self._map.usernames[player.index]:
                    curScore += 200

                if curScore > playerScore and player.index not in self._map.teammates:
                    playerScore = curScore
                    targetPlayer = player.index
                self.playerTargetScores[player.index] = curScore

        # don't target big fish when there are other players left
        if self._map.remainingPlayers > 2 and playerScore < -100:
            return -1

        if targetPlayer != -1:
            logging.info("target player: {} ({})".format(self._map.usernames[targetPlayer], int(playerScore)))

        return targetPlayer

    def get_defense_moves(
            self,
            threat: ThreatObj,
            defenseCriticalTileSet: typing.Set[Tile],
            raceEnemyKingKillPath: typing.Union[Path, None]
    ) -> typing.Tuple[typing.Union[None, Move], typing.Union[None, Path]]:
        """
        Defend against a threat
        @param threat:
        @param defenseCriticalTileSet:
        @param raceEnemyKingKillPath:
        @return:
        """
        isRealThreat = True
        with self.perf_timer.begin_move_event(f'def scrim @{str(threat.path.start.tile)} {str(threat.path)}'):
            path = self.try_find_counter_army_scrim_path_killpath(threat.path, allowGeneral=False)
        if path is not None:
            return self.get_first_path_move(path), path

        savePath: Path = None
        searchTurns = threat.turns
        with self.perf_timer.begin_move_event('Searching for a threat killer move...'):
            move = self.get_threat_killer_move(threat, searchTurns, defenseCriticalTileSet)
        if move is not None:
            if threat.path.start.tile in self.armyTracker.armies:
                self.targetingArmy = self.armyTracker.armies[threat.path.start.tile]

            self.viewInfo.infoText = "threat killer move! {},{} -> {},{}".format(move.source.x, move.source.y,
                                                                                 move.dest.x, move.dest.y)
            if self.curPath is not None and move.source.tile == self.curPath.start.tile:
                self.curPath.add_start(move.dest.tile)
                self.viewInfo.infoText = "threat killer move {},{} -> {},{} WITH ADDED FUN TO GET PATH BACK ON TRACK!".format(
                    move.source.x, move.source.y, move.dest.x, move.dest.y)
            return self.move_half_on_repetition(move, 5, 4), savePath
        armyAmount = threat.threatValue + 1
        logging.info(
            f"\n!-!-!-!-!-!  general in danger in {threat.turns}, gather {armyAmount} to general in {searchTurns} turns  !-!-!-!-!-!")

        self.viewInfo.add_targeted_tile(self.general)
        gatherPaths = []
        if threat is not None and threat.threatType == ThreatType.Kill:
            targetTile = None
            dict = {}
            dict[self.general] = (0, threat.threatValue, 0)
            negativeTilesIncludingThreat = set()
            for tile in defenseCriticalTileSet:
                negativeTilesIncludingThreat.add(tile)
            for tile in threat.path.tileSet:
                negativeTilesIncludingThreat.add(tile)

            # still have to gather the same amount to saveTile that we would have to the king
            if threat.saveTile is not None:
                dict[threat.saveTile] = (0, threat.threatValue, -0.5)
                self.viewInfo.add_targeted_tile(threat.saveTile, TargetStyle.PURPLE)
                logging.info(
                    f"dict[threat.saveTile] = (0, {threat.threatValue})  -- threat.saveTile {threat.saveTile.x},{threat.saveTile.y}")

            armyAmount = 1
            defenseNegatives = set(threat.path.tileSet)
            defenseNegatives = set(threat.armyAnalysis.shortestPathWay.tiles)
            altKillOffset = 0
            if not self.targetPlayerExpectedGeneralLocation.isGeneral:
                altKillOffset = 5 + int(len(self.targetPlayerObj.tiles) ** 0.5)
                logging.info(f'altKillOffset {altKillOffset} because dont know enemy gen position for sure')
            with self.perf_timer.begin_move_event(
                    f"ATTEMPTING TO FIND KILL ON ENEMY KING UNDISCOVERED SINCE WE CANNOT SAVE OURSELVES, TURNS {threat.turns - 1}:"):
                altKingKillPath = dest_breadth_first_target(
                    self._map,
                    [self.targetPlayerExpectedGeneralLocation],
                    12,
                    0.1,
                    threat.turns + 1,
                    None,
                    searchingPlayer=self.general.player,
                    dontEvacCities=False)
                if altKingKillPath is not None:
                    logging.info(
                        f"   Did find a killpath on enemy gen / undiscovered {altKingKillPath.toString()}")
                    # these only return if we think we can win/tie the race
                    if (raceEnemyKingKillPath is None or raceEnemyKingKillPath.length >= threat.turns) and altKingKillPath.length + altKillOffset < threat.turns:
                        self.info(f"FAILED DEFENSE altKingKillPath {altKingKillPath.toString()} altKillOffset {altKillOffset}")
                        self.viewInfo.color_path(PathColorer(altKingKillPath, 122, 97, 97, 255, 10, 200))
                        return self.get_first_path_move(altKingKillPath), savePath
                    elif raceEnemyKingKillPath is not None:
                        logging.info("   raceEnemyKingKillPath already existing, will not use the above.")
                        self.info(f"FAILED DEFENSE raceEnemyKingKillPath {raceEnemyKingKillPath.toString()} altKillOffset {altKillOffset}")
                        self.viewInfo.color_path(PathColorer(raceEnemyKingKillPath, 152, 97, 97, 255, 10, 200))
                        return self.get_first_path_move(raceEnemyKingKillPath), savePath

            defenseTiles = [self.general]
            if threat.saveTile:
                defenseTiles.append(threat.saveTile)

            # also include large tiles adjacent to the threat path
            # crappy hack to replace proper backpack defense
            defenseNegatives = set(threat.path.tileSet)
            defenseNegatives = set(threat.armyAnalysis.shortestPathWay.tiles)

            # gatherVal = int(threat.threatValue * 0.8)
            with self.perf_timer.begin_move_event(f'Defense Threat Gather'):
                move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_threat_path(threat)
            if move:
                pruned = [node.deep_clone() for node in gatherNodes]
                pruned = GatherUtils.prune_mst_to_turns(pruned, threat.turns - 3, self.general.player, self.viewInfo)
                sumPruned = 0
                sumPrunedTurns = 0
                for pruneNode in pruned:
                    sumPruned += pruneNode.value
                    sumPrunedTurns += pruneNode.gatherTurns

                self.viewInfo.addAdditionalInfoLine(f'Threat gath v{valueGathered}/{threat.threatValue} t{turnsUsed}/{threat.turns} (prune v{sumPruned}/{threat.threatValue} t{sumPrunedTurns}/{threat.turns})')

                if sumPruned > threat.threatValue:
                    maxNode: typing.List[TreeNode | None] = [None]
                    def largestTreeNodeFunc(node: TreeNode):
                        if node.tile.player == self.general.player and (maxNode[0] is None or maxNode[0].tile.army < node.tile.army):
                            maxNode[0] = node

                    GatherUtils.iterate_tree_nodes(pruned, largestTreeNodeFunc)

                    largestGatherTile = move.source
                    if maxNode[0] is not None:
                        largestGatherTile = maxNode[0].tile

                    threatTile = threat.path.start.tile

                    # check for ArMyEnGiNe scrim results
                    inRangeForScrimGen = self.is_tile_in_range_from(
                        largestGatherTile,
                        self.general,
                        threat.turns + 1,
                        threat.turns - 8)
                    inRangeForScrim = self.is_tile_in_range_from(
                        largestGatherTile,
                        threatTile,
                        threat.turns + 5,
                        threat.turns - 5)
                    goodInterceptCandidate = largestGatherTile.army > threatTile.army - threat.turns * 2 and largestGatherTile.army > 30
                    if goodInterceptCandidate and inRangeForScrim and inRangeForScrimGen:
                        with self.perf_timer.begin_move_event(f'defense army scrim @ {str(threatTile)}'):
                            scrimMove = self.get_army_scrim_move(largestGatherTile, threatTile, friendlyHasKillThreat=False, forceKeepMove=threat.turns < 7)
                        if scrimMove is not None:
                            self.targetingArmy = self.get_army_at(threatTile)
                            # already logged
                            return scrimMove, savePath

                    with self.perf_timer.begin_move_event(f'defense kill_threat @ {str(threatTile)}'):
                        path = self.kill_threat(threat, allowGeneral=True)
                    if path is not None:
                        self.threat_kill_path = path
                        return None, None

                    # logging.info(f"we're pretty safe from threat via gather, try fancier gather AT threat")
                    # atThreatMove, altValueGathered, altTurnsUsed, altGatherNodes = self.get_gather_to_threat_path(threat, force_turns_up_threat_path=threat.turns // 2)
                    # if atThreatMove:
                    #     self.info(f'{str(atThreatMove)} AT threat value {altValueGathered}/{threat.threatValue} turns {altTurnsUsed}/{threat.turns}')
                    #     self.gatherNodes = altGatherNodes
                    #     return atThreatMove, savePath

                    # the threat is harmless...?
                    isRealThreat = False

                # they might not find us, giving us more time to gather. Also they'll likely waste some army running around our tiles so subtract 10 from the threshold.
                abandonDefenseThreshold = threat.threatValue * 0.7 - 12
                if self._map.players[threat.threatPlayer].knowsKingLocation:
                    abandonDefenseThreshold = threat.threatValue * 0.92 - 3

                deadFlag = ''
                if valueGathered < threat.threatValue - 1:
                    deadFlag = 'DEAD '
                    with self.perf_timer.begin_move_event(f'+1 Defense Threat Gather'):
                        altMove, altValueGathered, altTurnsUsed, altGatherNodes = self.get_gather_to_threat_path(threat, addlTurns=1)
                    if altValueGathered >= threat.threatValue:
                        self.redTreeNodes = gatherNodes
                        move = altMove
                        valueGathered = altValueGathered
                        turnsUsed = altTurnsUsed
                        gatherNodes = altGatherNodes

                self.info(f'{deadFlag}GathDef {str(move)} val {valueGathered}/{threat.threatValue} turns {turnsUsed}/{threat.turns} (abandThresh {abandonDefenseThreshold})')
                if isRealThreat:
                    if valueGathered > abandonDefenseThreshold:
                        self.curPath = None
                        self.gatherNodes = gatherNodes
                        return move, savePath

            else:
                self.viewInfo.addAdditionalInfoLine("final panic gather failed to find any move")

            if altKingKillPath is not None:
                if raceEnemyKingKillPath is None or raceEnemyKingKillPath.length > threat.turns:
                    self.info(
                        f"FAILED DEFENSE altKingKillPath (long {altKingKillPath.length} vs threat {threat.turns}) {altKingKillPath.toString()}")
                    self.viewInfo.color_path(PathColorer(altKingKillPath, 122, 97, 97, 255, 10, 200))
                    return self.get_first_path_move(altKingKillPath), savePath
                elif raceEnemyKingKillPath is not None:
                    logging.info("   raceEnemyKingKillPath already existing, will not use the above.")
                    self.info(
                        f"FAILED DEFENSE raceEnemyKingKillPath (long {altKingKillPath.length} vs threat {threat.turns}) {raceEnemyKingKillPath.toString()}")
                    self.viewInfo.color_path(PathColorer(raceEnemyKingKillPath, 152, 97, 97, 255, 10, 200))
                    return self.get_first_path_move(raceEnemyKingKillPath), savePath

            logging.info("LEGACY dest_breadth_first_target: armyAmount {}, searchTurns {}, ignoreGoalArmy True".format(armyAmount, searchTurns))
            legacySavePath = dest_breadth_first_target(self._map, dict, armyAmount, 0.1, searchTurns, negativeTilesIncludingThreat, searchingPlayer = self.general.player, ignoreGoalArmy=True)
            legacySavePath: Path = None
            if legacySavePath is not None and legacySavePath.length > 0:
                legacySavePath.calculate_value(self.general.player)
                logging.info("            DEST BFS TARGET to save king, \n               turn {}, value {} : {}".format(
                    legacySavePath.length, legacySavePath.value, legacySavePath.toString()))
                gatherPaths.append(legacySavePath)
            else:
                logging.info("\n\n!-!-!-!-!-! \nIt may be too late to save general, setting their general val to 3\n!-!-!-!-!-!")
                targetGen = self._map.generals[threat.threatPlayer]
                if targetGen is not None and not targetGen.visible:
                    targetGen.army = 3

        paths = []
        queue = PriorityQueue()
        queueShortest = PriorityQueue()
        for legacySavePath in gatherPaths:
            #  - path.length / 2 because of general increment

            gatherVal = legacySavePath.value
            # I think this works including for meeting up to attack path earlier?
            lengthModifier = min(0, 1 - self.distance_from_general(legacySavePath.tail.tile))
            lengthModified = legacySavePath.length + lengthModifier
            if threat is not None:
                # If its a real threat, sort by shortest path
                logging.info(
                    "Looking for short save paths... lengthModifier {}, searchTurns {}, threatValue {}, gatherVal {}, path {}".format(
                        lengthModifier, searchTurns, threat.threatValue, gatherVal, legacySavePath.toString()))
                if gatherVal >= threat.threatValue:
                    logging.info("gatherVal [{}] >= threat.threatValue [{}]".format(gatherVal, threat.threatValue))
                    if legacySavePath.length + lengthModifier < searchTurns:
                        logging.info("path.length + lengthModifier [{}] < searchTurns [{}] SHORTEST ADD".format(
                            legacySavePath.length + lengthModifier, searchTurns))
                        queueShortest.put((0 - (legacySavePath.length + lengthModifier), 0 - legacySavePath.value, legacySavePath))
                    else:
                        logging.info("NOT path.length + lengthModifier [{}] < searchTurns [{}]".format(
                            legacySavePath.length + lengthModifier, searchTurns))
                else:
                    logging.info("NOT gatherVal [{}] >= threat.threatValue [{}]".format(gatherVal, threat.threatValue))

            if gatherVal > 0 and legacySavePath.length >= 1:
                pathVal = gatherVal / 1.5 + gatherVal / lengthModified
                if lengthModified > searchTurns:
                    pathVal = (pathVal / 100.0 - 1.0) / lengthModified
                queue.put((0 - pathVal, legacySavePath))

        if not queueShortest.empty():
            (negTurn, negPathVal, savePath) = queueShortest.get()
            self.viewInfo.addAdditionalInfoLine(
                "SAFE: SHORT path to save king. Length {}, value {} : {}".format(savePath.length, savePath.value,
                                                                                 savePath.toString()))
            paths = []
            alpha = 120
            minAlpha = 80
            alphaDec = 6
            self.viewInfo.color_path(PathColorer(savePath.clone(), 230, 220, 190, alpha, alphaDec, minAlpha))
            saveNode = savePath.start
            # mark all nodes on the savepath as negative tiles?
            if savePath.length > searchTurns - 2:
                self.viewInfo.addAdditionalInfoLine(
                    "SuperSafe: (savePath.length [{}] > searchTurns - 2 [{}]), Adding savepath to negative tiles.".format(
                        savePath.length, searchTurns - 2))
                while saveNode is not None:
                    defenseCriticalTileSet.add(saveNode.tile)
                    saveNode = saveNode.next


        else:
            while not queue.empty() and len(paths) < 5:
                node = queue.get()
                legacySavePath = node[1]
                paths.append(legacySavePath)
                self.info("GHETTO QUEUE path to save king, ({}) turn {}, value {} : {}".format(node[0], legacySavePath.length,
                                                                                               legacySavePath.value,
                                                                                               legacySavePath.toString()))

        if len(paths) > 0:
            self.lastGeneralGatherTurn = self._map.turn
            # if (threat is not None and threat.threatType == ThreatType.Kill):
            #    self.curPathPrio = 100
            # else:
            #    self.curPathPrio = 10
            savePath = paths[0]
            depth = 3
            node = savePath.start
            while node is not None and depth > 0:
                node = node.next
                depth -= 1
            self.info("setting curpath to save general. " + savePath.toString())
            if threat.path.start.tile in self.armyTracker.armies:
                threatArmy = self.armyTracker.armies[threat.path.start.tile]
                self.targetingArmy: Army = threatArmy
            if savePath.start.tile.army == 1:
                self.info("set curpath to save general AND HIT INC 0.5 BUG! " + savePath.toString())
                # then hit that bug where the general was saved by 0.5 increment, lul, and he's trying to move 0 army
                savePath.made_move()
            if savePath.start.next is not None:
                savePath = savePath.get_subsegment(1)
                self.curPath = savePath
                self.info("set curpath to save general (single move) {}" + savePath.toString())
                return Move(savePath.start.tile, savePath.start.next.tile), savePath
            else:
                self.viewInfo.addAdditionalInfoLine("COULDNT SAVE GENERAL AND HIT INC 0.5 BUG I THINK!" + savePath.toString())

        return None, None

    def attempt_first_25_collision_reroute(
            self,
            curPath: Path,
            move: Move,
            distMap: typing.List[typing.List[int]]
    ) -> typing.Union[Path, None]:
        countExtraUseableMoves = 0
        for path in self.expand_plan.plan_paths:
            if path is None:
                countExtraUseableMoves += 1

        negExpandTiles = set()
        negExpandTiles.add(self.general)
        # we already stripped the move we're not doing off curPath so + 1
        lengthToReplaceCurrentPlan = curPath.length
        rePlanLength = lengthToReplaceCurrentPlan + countExtraUseableMoves
        with self.perf_timer.begin_move_event(f'Re-calc F25 Expansion for {str(move.source)} (length {rePlanLength})'):
            newPath = get_optimal_expansion(
                self._map,
                self.general.player,
                move.dest.player,
                rePlanLength,
                distMap,
                self._gen_distances,
                self.territories.territoryMap,
                self.board_analysis.innerChokes,
                self.board_analysis.intergeneral_analysis.pathChokes,
                negExpandTiles,
                viewInfo=self.viewInfo
            )

        if newPath is not None:
            segments = newPath.break_overflow_into_one_move_path_subsegments(
                lengthToKeepInOnePath=lengthToReplaceCurrentPlan)
            self.expand_plan.plan_paths[0] = None
            if segments[0] is not None:
                for i in range(segments[0].length, lengthToReplaceCurrentPlan):
                    logging.info(f'plan segment 0 {str(segments[0])} was shorter than lengthToReplaceCurrentPlan {lengthToReplaceCurrentPlan}, inserting a None')
                    self.expand_plan.plan_paths.insert(0, None)

            curSegIndex = 0
            for i in range(len(self.expand_plan.plan_paths)):
                if self.expand_plan.plan_paths[i] is None and curSegIndex < len(segments):
                    if i > 0:
                        logging.info(f'Awesome, managed to replace expansion no-ops with expansion in F25 collision!')
                    self.expand_plan.plan_paths[i] = segments[curSegIndex]
                    curSegIndex += 1

            return segments[0]
        else:
            return None

    def get_army_at(self, tile: Tile):
        return self.armyTracker.get_or_create_army_at(tile)

    def get_army_at_x_y(self, x: int, y: int):
        tile = self._map.GetTile(x, y)
        return self.get_army_at(tile)

    def initialize_map_for_first_time(self, map: MapBase):
        self._map = map

        self.initialize_logging()
        self.general = self._map.generals[self._map.player_index]
        self.player = self._map.players[self.general.player]
        self._gen_distances = build_distance_map(self._map, [self.general])
        self.dangerAnalyzer = DangerAnalyzer(self._map)
        self.cityAnalyzer = CityAnalyzer(self._map, self.general)
        self.gatherAnalyzer = GatherAnalyzer(self._map)
        self.viewInfo = ViewInfo(2, self._map.cols, self._map.rows)
        self.isInitialized = True

        self._map.notify_city_found.append(self.handle_city_found)
        self._map.notify_tile_captures.append(self.handle_tile_captures)
        self._map.notify_tile_deltas.append(self.handle_tile_deltas)
        self._map.notify_tile_discovered.append(self.handle_tile_discovered)
        self._map.notify_tile_revealed.append(self.handle_tile_revealed)
        self._map.notify_player_captures.append(self.handle_player_captures)
        if self.territories is None:
            self.territories = TerritoryClassifier(self._map)

        self.armyTracker = ArmyTracker(self._map)
        self.armyTracker.notify_unresolved_army_emerged.append(self.handle_tile_revealed)
        self.armyTracker.notify_army_moved.append(self.handle_army_moved)
        self.targetPlayerExpectedGeneralLocation = self.general.movable[0]
        self.launchPoints.add(self.general)
        self.board_analysis = BoardAnalyzer(self._map, self.general)
        self.timing_cycle_ended()

    def __getstate__(self):
        raise AssertionError("EklipZBot Should never be serialized")

    def __setstate__(self, state):
        raise AssertionError("EklipZBot Should never be de-serialized")

    @staticmethod
    def add_city_score_to_view_info(score: CityScoreData, viewInfo: ViewInfo):
        tile = score.tile
        viewInfo.topRightGridText[tile.x][tile.y] = f'r{f"{score.city_relevance_score:.2f}".strip("0")}'
        viewInfo.midRightGridText[tile.x][tile.y] = f'e{f"{score.city_expandability_score:.2f}".strip("0")}'
        viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'd{f"{score.city_defensability_score:.2f}".strip("0")}'
        viewInfo.bottomRightGridText[tile.x][tile.y] = f'g{f"{score.city_general_defense_score:.2f}".strip("0")}'

        if tile.player >= 0:
            scoreVal = score.get_weighted_enemy_capture_value()
            viewInfo.bottomLeftGridText[tile.x][tile.y] = f'e{f"{scoreVal:.2f}".strip("0")}'
        else:
            scoreVal = score.get_weighted_neutral_value()
            viewInfo.bottomLeftGridText[tile.x][tile.y] = f'n{f"{scoreVal:.2f}".strip("0")}'

    def get_quick_kill_on_enemy_cities(self, defenseCriticalTileSet: typing.Set[Tile]) -> Path | None:
        # TODO REDUCE CITYDEPTHSEARCH NOW THAT WE HAVE CITY FIGHTING BASIC IMPL
        cityDepthSearch = max(2, int(self._map.players[self.general.player].tileCount**0.5 / 2))
        #if (len(self.enemyCities) > 5):
        #    cityDepthSearch = 5
        enemyCitiesOrderedByPriority = self.cityAnalyzer.get_sorted_enemy_scores()
        for enemyCity, score in enemyCitiesOrderedByPriority:
            logging.info("{} searching for depth {} dest bfs kill on city {},{}".format(self.get_elapsed(), cityDepthSearch, enemyCity.x, enemyCity.y))
            self.viewInfo.add_targeted_tile(enemyCity, TargetStyle.RED)
            armyToSearch = self.get_target_army_inc_adjacent_enemy(enemyCity)
            killPath = dest_breadth_first_target(self._map, [enemyCity], armyToSearch, 0.1, cityDepthSearch, defenseCriticalTileSet, searchingPlayer = self.general.player, dontEvacCities=True)
            if killPath is not None:
                self.info("{} found depth {} dest bfs kill on city {},{} \n{}".format(self.get_elapsed(), killPath.length, enemyCity.x, enemyCity.y, killPath.toString()))
                if killPath.start.tile.isCity and self.should_kill_path_move_half(killPath, armyToSearch - enemyCity.army):
                    killPath.start.move_half = True
                return killPath
        return None

    def prep_view_info_for_render(self):
        self.viewInfo.board_analysis = self.board_analysis
        self.viewInfo.targetingArmy = self.targetingArmy
        self.viewInfo.armyTracker = self.armyTracker
        self.viewInfo.dangerAnalyzer = self.dangerAnalyzer
        self.viewInfo.currentPath = self.curPath
        self.viewInfo.gatherNodes = self.gatherNodes
        self.viewInfo.redGatherNodes = self.redTreeNodes
        self.viewInfo.territories = self.territories
        self.viewInfo.allIn = self.allIn
        self.viewInfo.timings = self.timings
        self.viewInfo.allInCounter = self.all_in_counter
        self.viewInfo.targetPlayer = self.targetPlayer
        self.viewInfo.generalApproximations = self.generalApproximations
        self.viewInfo.playerTargetScores = self.playerTargetScores
        for tile in self._map.pathableTiles:
            if tile.player == self.general.player:
                self.viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'g{self.gatherAnalyzer.gather_locality_map[tile]}'

        if self.target_player_gather_path is not None:
            alpha = 140
            minAlpha = 100
            alphaDec = 5
            self.viewInfo.color_path(PathColorer(self.target_player_gather_path, 60, 50, 00, alpha, alphaDec, minAlpha))

    def get_move_if_afk_player_situation(self) -> Move | None:
        afkPlayers = self.get_afk_players()
        allOtherPlayersAfk = len(afkPlayers) + 1 == self._map.remainingPlayers
        numTilesVisible = 0
        if self.targetPlayer != -1:
            numTilesVisible = len(self._map.players[self.targetPlayer].tiles)

        logging.info("{} TEMP! len(self._map.players[self.targetPlayer].tiles) {}, allOtherPlayersAfk {}, ".format(self.get_elapsed(), numTilesVisible, allOtherPlayersAfk))
        if allOtherPlayersAfk and numTilesVisible == 0:
            # then just expand until we can find them
            with self.perf_timer.begin_move_event('AFK Player optimal EXPLORATION'):
                path = self.get_optimal_exploration(30, None, minArmy = 0)
            if path is not None:
                self.info("Rapid EXPLORE due to AFK player {}:  {}".format(self.targetPlayer, path.toString()))

                self.finishingExploration = True
                self.viewInfo.addAdditionalInfoLine("Setting finishingExploration to True because allOtherPlayersAfk and found an explore path")
                return self.get_first_path_move(path)

            expansionNegatives = set()
            territoryMap = self.territories.territoryMap
            enemyDistMap = self.board_analysis.intergeneral_analysis.bMap
            innerChokes = self.board_analysis.innerChokes
            pathChokes = self.board_analysis.intergeneral_analysis.pathChokes
            with self.perf_timer.begin_move_event('AFK Player optimal EXPANSION'):
                path = get_optimal_expansion(
                    self._map,
                    self.general.player,
                    self.targetPlayer,
                    15,
                    enemyDistMap,
                    self.board_analysis.genDistMap,
                    territoryMap,
                    innerChokes,
                    pathChokes,
                    expansionNegatives,
                    self.leafMoves,
                    allowLeafMoves = False,
                    viewInfo=self.viewInfo)

            if path is not None:
                self.finishingExploration = True
                self.info("Rapid EXPAND due to AFK player {}:  {}".format(self.targetPlayer, path.toString()))
                return self.get_first_path_move(path)

        if self.targetPlayer != -1:
            if self._map.players[self.targetPlayer].leftGame and self._map.turn < self._map.players[self.targetPlayer].leftGameTurn + 50:
                remainingTurns = self._map.players[self.targetPlayer].leftGameTurn + 50 - self._map.turn
                turns = max(5, remainingTurns - 15)
                with self.perf_timer.begin_move_event(f'Quick kill gather to player who left, {remainingTurns} until they arent capturable'):
                    move = self.timing_gather([self.targetPlayerExpectedGeneralLocation], force = True, targetTurns = turns)
                if move is not None:
                    self.info(f"quick-kill gather to opposing player who left! {move.toString()}")
                    return move

            if allOtherPlayersAfk and self.targetPlayerExpectedGeneralLocation is not None and self.targetPlayerExpectedGeneralLocation.isGeneral:
                # attempt to quick-gather to this gen for kill
                with self.perf_timer.begin_move_event(f'quick-kill gather to opposing player!'):
                    move = self.timing_gather([self.targetPlayerExpectedGeneralLocation], force = True)
                if move is not None:
                    self.info(f"quick-kill gather to opposing player! {move.toString()}")
                    return move

        return None

    def clear_fog_armies_around(self, enemyGeneral: Tile):

        def fog_army_clear_func(tile: Tile):
            if not tile.visible and tile in self.armyTracker.armies:
                army = self.armyTracker.armies[tile]
                if army.player == enemyGeneral.player:
                    self.armyTracker.scrap_army(army)

        breadth_first_foreach(self._map, [enemyGeneral], maxDepth=7, foreachFunc=fog_army_clear_func)

    def initialize_logging(self):
        self.logDirectory = BotLogging.get_file_logging_directory(self._map.usernames[self._map.player_index], self._map.replay_id)
        fileSafeUserName = BotLogging.get_file_safe_username(self._map.usernames[self._map.player_index])

        gameMode = '1v1'
        if self._map.remainingPlayers > 2:
            gameMode = 'ffa'

        BotLogging.add_file_log_output(fileSafeUserName, gameMode, self._map.replay_id, self.logDirectory)

    def get_max_explorable_undiscovered_tile(self, minSpawnDist: int):
        # 4 and larger gets dicey
        self.undiscovered_priorities = self.find_expected_1v1_general_location_on_undiscovered_map(
            undiscoveredCounterDepth=10,
            minSpawnDistance=minSpawnDist)

        maxAmount = 0
        maxTile = None
        for x in range(self._map.cols):
            for y in range(self._map.rows):
                tile = self._map.GetTile(x, y)
                if tile and maxAmount < self.undiscovered_priorities[x][y] and self.distance_from_general(tile) > minSpawnDist:
                    maxAmount = self.undiscovered_priorities[x][y]
                    maxTile = tile
                if self.targetPlayer == -1:
                    if self.undiscovered_priorities[x][y] > 0:
                        self.viewInfo.bottomRightGridText[x][y] = f'u{self.undiscovered_priorities[x][y]}'

        self.viewInfo.add_targeted_tile(maxTile, TargetStyle.PURPLE)
        return maxTile

    # TODO this shit doesn't work, wont gather if it doesn't kill the dest tile...
    def try_gather_tendrils_towards_enemy(self) -> Move | None:
        turns = 25 - self._map.turn % 25
        move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_target_tile(
            self.targetPlayerExpectedGeneralLocation, 0.1, turns, negativeSet=self.target_player_gather_targets,
            includeTreeNodesThatGatherNegative=True, targetArmy=-30)
        if move is not None:
            self.info(f'lmao gather AT tg loc, gathered {valueGathered} turns used {turnsUsed}')
            self.gatherNodes = gatherNodes
            return move

        gatherNodes = GatherUtils.greedy_backpack_gather(
            self._map,
            [self.targetPlayerExpectedGeneralLocation],
            turns,
            targetArmy=-40,
            negativeTiles=self.target_player_gather_targets,
            includeTreeNodesThatGatherNegative=True,
            preferNeutral=True)

        totalValue = 0
        gathTurns = 0
        for gather in gatherNodes:
            logging.info("gatherNode {} value {}".format(gather.tile.toString(), gather.value))
            totalValue += gather.value
            gathTurns += gather.gatherTurns

        logging.info(
            "greedy_backpack_gather totalValue was {}. Setting gatherNodes for visual debugging regardless of using them".format(
                totalValue))
        move = self.get_tree_move_default(gatherNodes)
        if move is not None:
            self.info(f'Greedy gather AT tg loc, val {totalValue}, turns {gathTurns}')
            return move

        # move = self.gather_to_target_MST(self.targetPlayerExpectedGeneralLocation, 0.1, turns, gatherNegatives=self.target_player_gather_targets, targetArmy=-30)
        # if move is not None:
        #     self.info(f'MST gather AT tg loc')
        #     return move
        return None

    def get_army_scrim_move(
            self,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            friendlyHasKillThreat: bool | None = None,
            forceKeepMove = False
    ) -> Move | None:
        friendlyPath, enemyPath, result = self.get_army_scrim_paths(
            friendlyArmyTile,
            enemyArmyTile,
            friendlyHasKillThreat=friendlyHasKillThreat)
        if friendlyPath is not None and friendlyPath.length > 0:
            firstPathMove = self.get_first_path_move(friendlyPath)
            if firstPathMove and not result.best_result_state.captured_by_enemy and (result.net_economy_differential > 0 or forceKeepMove):
                self.info(f'ARMY SCRIM MOVE {str(friendlyArmyTile)}@{str(enemyArmyTile)}: {str(firstPathMove)}, EXPECTED EVAL {str(result)}')

                return firstPathMove

        return None

    def get_army_scrim_paths(
            self,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            enemyCannotMoveAway: bool=True,
            friendlyHasKillThreat: bool | None = None
    ) -> typing.Tuple[Path | None, Path | None, ArmySimResult]:
        """
        Returns None for the path WHEN THE FIRST MOVE THE ENGINE WANTS TO MAKE INCLUDES A NO-OP.
        NOTE, These paths should not be executed as paths, they may contain removed-no-ops.

        @param friendlyArmyTile:
        @param enemyArmyTile:
        @param enemyCannotMoveAway:
        @param friendlyHasKillThreat: whether friendly tile is a kill threat against enemy or not. If not provided, will be calculated via a_star
        @return:
        """
        result = self.get_army_scrim_result(friendlyArmyTile, enemyArmyTile, enemyCannotMoveAway=enemyCannotMoveAway, friendlyHasKillThreat=friendlyHasKillThreat)

        if result.best_result_state.captured_by_enemy:
            self.viewInfo.addAdditionalInfoLine(f'scrim thinks enemy kills us :/ {str(result.expected_best_moves)}')
            return None, None, result

        if result.best_result_state.captures_enemy:
            self.viewInfo.addAdditionalInfoLine(f'scrim thinks we kill!? {str(result.expected_best_moves)} TODO implement race checks')
            return None, None, result

        if len(result.expected_best_moves) == 0:
            self.viewInfo.addAdditionalInfoLine(f'scrim returned no moves..? {str(result.expected_best_moves)}')
            return None, None, result

        friendlyPath = Path()
        enemyPath = Path()

        for friendlyMove, enemyMove in result.expected_best_moves:
            if friendlyMove is not None and friendlyMove.dest is not None:
                if friendlyPath.start is None:
                    friendlyPath.add_next(friendlyMove.source)
                friendlyPath.add_next(friendlyMove.dest)
            if enemyMove is not None and enemyMove.dest is not None:
                if enemyPath.start is None:
                    enemyPath.add_next(enemyMove.source)
                enemyPath.add_next(enemyMove.dest)

        # sometimes being afk is the optimal move, in which case these paths may have no moves
        if friendlyPath.length == 0:
            friendlyPath = None
        else:
            self.viewInfo.color_path(PathColorer(friendlyPath, 40, 255, 165, 255))

        if enemyPath.length == 0:
            enemyPath = None
        else:
            self.viewInfo.color_path(PathColorer(enemyPath, 175, 0, 255, 255))

        if result.expected_best_moves[0][0] is None:
            friendlyPath = None
        if result.expected_best_moves[0][1] is None:
            enemyPath = None

        return friendlyPath, enemyPath, result

    def get_army_scrim_result(
            self,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            enemyCannotMoveAway: bool = True,
            enemyHasKillThreat: bool = True,
            friendlyHasKillThreat: bool | None = None
    ) -> ArmySimResult:
        if friendlyHasKillThreat is None:
            path = a_star_kill(
                self._map,
                [friendlyArmyTile],
                self.targetPlayerExpectedGeneralLocation,
                0.03,
                self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3,
                self.general_safe_func_set,
                requireExtraArmy=5 if self.targetPlayerExpectedGeneralLocation.isGeneral else 20)
            friendlyHasKillThreat = path is not None

        enemyArmy = self.get_army_at(enemyArmyTile)
        engine: ArmyEngine = ArmyEngine(self._map, [self.get_army_at(friendlyArmyTile)], [enemyArmy], self.board_analysis)
        depth = 3
        if enemyCannotMoveAway:
            # we can scan much deeper when the enemies moves are heavily restricted.
            depth = 5
            if enemyArmy.expectedPath is not None:
                engine.force_enemy_towards = SearchUtils.build_distance_map_matrix(self._map, [enemyArmy.expectedPath.tail.tile])
            else:
                engine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(self._map, [self.general])

            engine.allow_enemy_no_op = False

        engine.friendly_has_kill_threat = friendlyHasKillThreat
        engine.enemy_has_kill_threat = enemyHasKillThreat
        result = engine.scan(depth, noThrow=True)
        return result

    def is_tile_in_range_from(self, source: Tile, target: Tile, maxDist: int, minDist: int = 0) -> bool:
        """
        Whether the dist between source and target is within the range of minDist and maxDist, inclusive.
        For optimization reasons, if one of the tiles is a friendly or enemy general, make the general tile be target.
        """
        dist = 1000
        if target == self.general:
            dist = self.distance_from_general(source)
        elif target == self.targetPlayerExpectedGeneralLocation:
            dist = self.distance_from_opp(source)
        else:
            captDist = [dist]
            def distFinder(tile: Tile, d: int):
                if tile.x == target.x and tile.y == target.y:
                    captDist[0] = d
            SearchUtils.breadth_first_foreach_dist(self._map, [source], maxDepth=maxDist + 1, foreachFunc=distFinder, skipFunc=lambda t: t.isObstacle)

            dist = captDist[0]

        return minDist <= dist <= maxDist

    def continue_killing_target_army(self) -> Move | None:
        # check if still same army
        if self.targetingArmy.tile in self.armyTracker.armies:
            army = self.armyTracker.armies[self.targetingArmy.tile]
            if army != self.targetingArmy:
                if army.player == self.targetingArmy.player:
                    logging.info("Switched targets from {} to {} because its a different army now?".format(
                        self.targetingArmy.toString(), army.toString()))
                    self.targetingArmy = army
                else:
                    logging.info(
                        "Stopped targeting Army {} because its tile is owned by the wrong player in armyTracker now".format(
                            self.targetingArmy.toString()))
                    self.targetingArmy = None
        else:
            self.targetingArmy = None
            logging.info(
                f"Stopped targeting Army {str(self.targetingArmy)} because it no longer exists in armyTracker.armies")

        if not self.targetingArmy:
            return None

        armyStillInRange = self.distance_from_general(self.targetingArmy.tile) < self.distance_from_opp(self.targetingArmy.tile)
        if armyStillInRange and self.should_kill(self.targetingArmy.tile):
            path = self.kill_army(self.targetingArmy, allowGeneral=True)
            if path:
                move = self.get_first_path_move(path)
                if self.targetingArmy.tile.army / path.length < 1:
                    self.info(f"Attacking army and ceasing to target army {self.targetingArmy.toString()}")
                    # self.targetingArmy = None
                    return move

                if not self.detect_repetition(move, 6, 3):
                    move.move_half = self.should_kill_path_move_half(path)
                    self.info("Continuing to kill army {} with half {} path {}".format(self.targetingArmy.toString(),
                                                                                       move.move_half, path.toString()))
                    self.viewInfo.color_path(PathColorer(path, 0, 112, 133, 255, 10, 200))
                    return move
                else:
                    logging.info("Stopped targeting Army {} because it was causing repetitions.".format(
                        self.targetingArmy.toString()))
                    # self.targetingArmy = None
        else:
            self.viewInfo.addAdditionalInfoLine(
                f"Stopped targeting Army {self.targetingArmy.toString()} due to distance {armyStillInRange} or should_kill() returned false.")
            self.targetingArmy = None

        return None

    def try_find_counter_army_scrim_path_killpath(
            self,
            threatPath: Path,
            allowGeneral: bool
    ) -> Path | None:
        path, simResult = self.try_find_counter_army_scrim_path_kill(threatPath, allowGeneral=allowGeneral)
        return path

    def try_find_counter_army_scrim_path_kill(
            self,
            threatPath: Path,
            allowGeneral: bool
    ) -> typing.Tuple[Path | None, ArmySimResult | None]:
        if threatPath.start.tile.army < 4:
            logging.info('fuck off, dont try to scrim against tiny tiles idiot')
            return None, None
        friendlyPath, simResult = self.try_find_counter_army_scrim_path(threatPath, allowGeneral)
        if simResult is not None and friendlyPath is not None:
            armiesIntercept = simResult.best_result_state.kills_all_friendly_armies or simResult.best_result_state.kills_all_enemy_armies

            if friendlyPath is not None and armiesIntercept and not simResult.best_result_state.captured_by_enemy:
                self.info(f'KILL ARMY SCRIM PATH: {str(friendlyPath)}, EXPECTED EVAL {str(simResult.best_result_state)}')
                self.targetingArmy = self.get_army_at(threatPath.start.tile)
                return friendlyPath, simResult

        return None, None

    def try_find_counter_army_scrim_path(
            self,
            threatPath: Path,
            allowGeneral: bool
    ) -> typing.Tuple[Path | None, ArmySimResult | None]:
        """
        Sometimes the best sim output involves no-opping one of the tiles. In that case,
        this will return a None path as the best ArmySimResult output. It should be honored, and this tile
        tracked as a scrimming tile, even though the tile should not be moved this turn.

        @param threatPath:
        @param allowGeneral:
        @return:
        """
        threatTile = threatPath.start.tile
        threatDist = self.distance_from_general(threatTile)

        largeTilesNearTarget = self.find_large_tiles_near(
            fromTiles = [threatTile],
            distance=4,
            limit=4,
            forPlayer=self.general.player,
            allowGeneral=allowGeneral,
            addlFilterFunc=lambda t, dist: self.distance_from_general(t) < threatDist + 3,
            minArmy=10
        )

        bestPath: Path | None = None
        bestSimRes: ArmySimResult | None = None
        for largeTile in largeTilesNearTarget:
            if largeTile in threatPath.tileSet:
                continue
            with self.perf_timer.begin_move_event(f'Scrim w {str(largeTile)} @ {str(threatTile)}'):
                friendlyPath, enemyPath, simResult = self.get_army_scrim_paths(largeTile, enemyArmyTile=threatTile, enemyCannotMoveAway=True)
            if bestSimRes is None or bestSimRes.calculate_value() < simResult.calculate_value():
                bestPath = friendlyPath
                bestSimRes = simResult

        if len(largeTilesNearTarget) == 0:
            logging.info(f'No large tiles in range of {str(threatTile)} :/')

        return bestPath, bestSimRes

    def explore_target_player_undiscovered_short(self, targetArmy: int, negativeTiles: typing.Set[Tile]):
        genPlayer = self._map.players[self.general.player]
        enemyUndiscBordered = {}
        if self.targetPlayer != -1:
            for tile in self.allUndiscovered:
                if tile.visible or tile.discovered:
                    continue
                if tile.isObstacle:
                    continue
                isEnemyTerritory = self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer
                bordersEnemyTile = any(tile.movable, lambda t: t.visible and t.player == self.targetPlayer)
                if isEnemyTerritory or bordersEnemyTile:
                    for move in tile.movable:
                        if move.player == self.targetPlayer and not move.discoveredAsNeutral:
                            enemyUndiscBordered[move] = ((0, 0, move.army), 0)

        longArmy = max(targetArmy, max(8, (genPlayer.standingArmy ** 0.5) / 4))
        # startTiles dict is (startPriorityObject, distance) = startTiles[tile]
        # goalFunc is (currentTile, priorityObject) -> True or False
        # priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject

        logging.info(
            "exploring target player undiscovered. targetArmy {}, longArmy {}".format(targetArmy, longArmy))
        negLongArmy = 0 - longArmy

        def goal_func_short(currentTile, priorityObject):
            distance, negTileTakenScore, negArmyFound = priorityObject
            if currentTile.army < 10:
                return False
            if currentTile.player != self.general.player:
                return False
            if negArmyFound < 0:
                return True
            return False

        def goal_func_long(currentTile, priorityObject):
            distance, negTileTakenScore, negArmyFound = priorityObject
            if currentTile.army < 10:
                return False
            if currentTile.player != self.general.player:
                return False
            if negArmyFound < negLongArmy:
                return True
            return False

        def priority_func_all_in(nextTile, currentPriorityObject):
            distance, negTileTakenScore, negArmyFound = currentPriorityObject
            if nextTile.discoveredAsNeutral or self.territories.territoryMap[nextTile.x][
                nextTile.y] != self.targetPlayer:
                negTileTakenScore += 1

            if nextTile not in negativeTiles:
                if nextTile.player == self.general.player:
                    negArmyFound -= nextTile.army
                else:
                    negArmyFound += nextTile.army

            negArmyFound += 1
            distance += 1
            return distance, negTileTakenScore + 1, negArmyFound

        # make large tiles do the thing?
        # negativeTiles.clear()
        path = breadth_first_dynamic(
            self._map,
            enemyUndiscBordered,
            goal_func_long,
            0.1,
            maxDepth=3,
            noNeutralCities=True,
            negativeTiles=negativeTiles,
            searchingPlayer=self.general.player,
            priorityFunc=priority_func_all_in)

        if path is not None:
            path = path.get_reversed()
            self.info("UNDISCOVERED SHORT: depth {} bfd kill (pre-prune) \n{}".format(path.length, path.toString()))
            path = self.get_value_per_turn_subsegment(path, 0.95, minLengthFactor=0)
            if path.length > 2:
                path = path.get_subsegment(2)

            self.finishingExploration = True
            self.viewInfo.addAdditionalInfoLine(
                "finishExp=True in explore_target_player_undiscovered because found UNDISCOVERED SHORT path")

        return path

    def find_large_tiles_near(
            self,
            fromTiles: typing.List[Tile],
            distance: int,
            forPlayer=-2,
            allowGeneral: bool = True,
            limit: int=5,
            minArmy:int=10,
            addlFilterFunc: typing.Callable[[Tile, int], bool] | None = None
    ) -> typing.List[Tile]:
        """
        Returns [limit] largest fromTiles for [forPlayer] within [distance] of [fromTiles]. Excludes generals unless allowGeneral is true.
        Returns them in order from largest army to smallest army.

        @param fromTiles:
        @param distance:
        @param forPlayer:
        @param allowGeneral:
        @param limit:
        @param minArmy:
        @param addlFilterFunc: None or func(tile, dist) should return False to exclude a tile, True to include it. Tile must STILL meet all the other restrictions.
        @return:
        """
        largeTilesNearTargets = []
        if forPlayer == -2:
            forPlayer = self.general.player
        def tile_finder(tile: Tile, dist: int):
            if (tile.player == forPlayer
                    and tile.army > minArmy  # - threatDist * 2
                    and (addlFilterFunc is None or addlFilterFunc(tile, dist))
                    and (not tile.isGeneral or allowGeneral)
            ):
                largeTilesNearTargets.append(tile)

        SearchUtils.breadth_first_foreach_dist(self._map, fromTiles, distance, foreachFunc=tile_finder)

        largeTilesNearTargets = [t for t in sorted(largeTilesNearTargets, key=lambda t: t.army, reverse=True)]

        return largeTilesNearTargets[0:limit]

    def check_for_army_movement_scrims(self) -> Move | None:
        curScrim = 0
        cutoff = 3

        bestScrimPath: Path | None = None
        bestScrim: ArmySimResult | None = None

        for tile in sorted(self.armies_moved_this_turn, key=lambda t: t.army, reverse=True):
            if tile.player == self.general.player:
                self.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.GREEN)
            elif tile.player != self.targetPlayer:
                self.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.GOLD)

            if tile.player == self.targetPlayer:
                self.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.RED)
                if tile.army <= 4:
                    continue

                # try continuing the scrim with this tile?
                if self.next_scrimming_army_tile is not None and self.next_scrimming_army_tile.army > 2 and self.next_scrimming_army_tile.player == self.general.player:
                    with self.perf_timer.begin_move_event(
                            f'Scrim prev {str(self.next_scrimming_army_tile)} @ {str(tile)}'):
                        friendlyPath, enemyPath, simResult = self.get_army_scrim_paths(
                            self.next_scrimming_army_tile,
                            enemyArmyTile=tile,
                            enemyCannotMoveAway=True)
                    if simResult is not None \
                            and (bestScrimPath is None or bestScrim.calculate_value() < simResult.calculate_value()):
                        bestScrimPath = friendlyPath
                        bestScrim = simResult
                else:
                    self.next_scrimming_army_tile = None

                curScrim += 1
                # attempt scrim intercept? :)
                with self.perf_timer.begin_move_event(f'try scrim @ {str(tile)}'):
                    army = self.get_army_at(tile)
                    if army.expectedPath is None:
                        targets = self._map.players[self.general.player].cities.copy()
                        targets.append(self.general)
                        army.expectedPath = self.get_path_to_targets(
                            targets,
                            0.1,
                            preferNeutral=False,
                            fromTile=tile)
                    self.viewInfo.addAdditionalInfoLine(f'predict army path {str(army.expectedPath)}')
                    path, scrimResult = self.try_find_counter_army_scrim_path(army.expectedPath, allowGeneral=True)
                    if path is not None and scrimResult is not None:
                        if scrimResult.best_result_state.captured_by_enemy:
                            logging.info('scrim says captured lol')
                        elif scrimResult.net_economy_differential < 0:
                            logging.info(f'scrim @ {str(tile)} bad result, {str(scrimResult)}')
                        elif (bestScrimPath is None
                              or bestScrim.calculate_value() < scrimResult.calculate_value()):
                            bestScrimPath = path
                            bestScrim = scrimResult

                if curScrim > cutoff:
                    break

        # # try continuing the scrim with this tile?
        # if self.next_scrimming_army_tile is not None and self.next_scrimming_army_tile.army > 2 and self.next_scrimming_army_tile.player == self.general.player:
        #     largestEnemyTilesNear = self.find_large_tiles_near([self.next_scrimming_army_tile], distance=4, forPlayer=self.targetPlayer, allowGeneral=True, limit = 1, minArmy=1)
        #     self.viewInfo.add_targeted_tile(self.next_scrimming_army_tile, TargetStyle.PURPLE)
        #     if len(largestEnemyTilesNear) > 0:
        #         largestEnemyTile = largestEnemyTilesNear[0]
        #         self.viewInfo.add_targeted_tile(largestEnemyTile, TargetStyle.BLUE)
        #         with self.perf_timer.begin_move_event(
        #                 f'Scrim current {str(self.next_scrimming_army_tile)} @ {str(largestEnemyTile)}'):
        #             friendlyPath, enemyPath, simResult = self.get_army_scrim_paths(
        #                 self.next_scrimming_army_tile,
        #                 enemyArmyTile=largestEnemyTile,
        #                 enemyCannotMoveAway=True)
        #         if simResult is not None and friendlyPath is not None \
        #                 and (bestScrimPath is None or bestScrim.calculate_value() < simResult.calculate_value()):
        #             bestScrimPath = friendlyPath
        #             bestScrim = simResult
        # else:
        #     self.next_scrimming_army_tile = None

        if bestScrimPath is not None and bestScrim is not None:
            self.info(f'Scrim cont +{bestScrim.net_economy_differential} ({str(bestScrim)})')

            self.next_scrimming_army_tile = bestScrimPath.start.next.tile
            return self.get_first_path_move(bestScrimPath)

    def should_force_gather_to_enemy_tiles(self) -> bool:
        """
        Determine whether we've let too much enemy tiles accumulate near our general,
         and it is getting out of hand and we should spend a cycle just gathering to kill them.
        """
        forceGatherToEnemy = False
        scaryDistance = 3
        if self.shortest_path_to_target_player is not None:
            scaryDistance = self.shortest_path_to_target_player.length // 3 + 2

        thresh = 1.3
        numEnemyTerritoryNearGen = self.count_enemy_territory_near_tile(self.general, distance=scaryDistance)
        enemyTileNearGenRatio = numEnemyTerritoryNearGen / max(1.0, scaryDistance)
        if enemyTileNearGenRatio > thresh:
            forceGatherToEnemy = True

        self.viewInfo.addAdditionalInfoLine(
            f'forceEn={forceGatherToEnemy} (near {numEnemyTerritoryNearGen}, dist {scaryDistance}, rat {enemyTileNearGenRatio:.2f} vs thresh {thresh:.2f})')
        return forceGatherToEnemy
