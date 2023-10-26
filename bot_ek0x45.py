"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""
import logging
import math
import queue
import random
import time
import typing
from collections import deque
from queue import PriorityQueue, Queue

import BotLogging
import DebugHelper
import EarlyExpandUtils
import GatherUtils
import SearchUtils
import ExpandUtils
from ArmyAnalyzer import ArmyAnalyzer
from ArmyEngine import ArmyEngine, ArmySimResult
from CityAnalyzer import CityAnalyzer, CityScoreData
from Communication import TeammateCommunicator, TileCompressor, ServerTileCompressor
from GatherAnalyzer import GatherAnalyzer
from KnapsackUtils import solve_knapsack
from MapMatrix import MapMatrix
from MctsLudii import MctsDUCT
from Path import Path
from PerformanceTimer import PerformanceTimer
from BoardAnalyzer import BoardAnalyzer, PlayerAggressionTracker
from ViewInfo import ViewInfo, PathColorer, TargetStyle
from base.client.generals import ChatUpdate
from base.client.map import Player, new_tile_grid, Tile, MapBase
from DangerAnalyzer import DangerAnalyzer, ThreatType, ThreatObj
from DataModels import get_tile_set_from_path, get_tile_list_from_path, GatherTreeNode, \
    Move, PathNode, ContestData
from Directives import Timings
from History import History, PlayerCapture, ContestedCityInfo, ContestInstance  # TODO replace these when city contestation
from Territory import TerritoryClassifier
from ArmyTracker import Army, ArmyTracker

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


######################### Move Making #########################
THREAD_COUNT = 6


class EklipZBot(object):
    def __init__(self):
        self.behavior_end_of_turn_scrim_army_count: int = 5
        self.teams: typing.List[int] = []
        self.contest_data: typing.Dict[Tile, ContestData] = {}
        self.army_out_of_play: bool = False
        self._lastTargetPlayerCityCount: int = 0
        self.armies_moved_this_turn: typing.List[Tile] = []
        self.logDirectory: str | None = None
        self.perf_timer = PerformanceTimer()
        self.cities_gathered_this_cycle: typing.Set[Tile] = set()
        self.tiles_gathered_to_this_cycle: typing.Set[Tile] = set()
        self.player: Player = Player(-1)
        self.targetPlayerObj: typing.Union[Player, None] = None
        self.expand_plan: EarlyExpandUtils.ExpansionPlan | None = None
        self.force_city_take = False
        self._gen_distances: typing.List[typing.List[int]] = []
        self._ally_distances: typing.List[typing.List[int]] = []
        self.defend_economy = False
        self._spawn_cramped: bool | None = None
        self.defending_economy_spent_turns: int = 0
        self.general_safe_func_set = {}
        self.clear_moves_func: typing.Union[None, typing.Callable] = None
        self._map: MapBase | None = None
        self.curPath: Path | None = None
        self.curPathPrio = -1
        self.gathers = 0
        self.attacks = 0
        self.leafMoves = []
        self.attackFailedTurn = 0
        self.countFailedQuickAttacks = 0
        self.countFailedHighDepthAttacks = 0
        self.largeTilesNearEnemyKings = {}
        self.no_file_logging: bool = False
        self.enemyCities = []
        self.dangerAnalyzer: DangerAnalyzer | None = None
        self.cityAnalyzer: CityAnalyzer | None = None
        self.gatherAnalyzer: GatherAnalyzer | None = None
        self.lastTimingFactor = -1
        self.lastTimingTurn = 0
        self._evaluatedUndiscoveredCache = []
        self.lastTurnTime = 0
        self.currently_forcing_out_of_play_gathers: bool = False
        self.is_rapid_capturing_neut_cities: bool = False

        self.allIn = False
        self.all_in_army_advantage_counter: int = 0
        self.all_in_army_advantage_cycle: int = 35
        self.all_in_army_advantage: bool = False
        self.all_in_city_behind: bool = False
        """If set to true, will use the expansion cycle timing to all in gather at opp and op cities."""

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
        self.is_blocking_neutral_city_captures: bool = False
        self.targetPlayer = -1
        self.leafValueGrid: typing.List[typing.List[int | None]] = []
        self.failedUndiscoveredSearches = 0
        self.largePlayerTiles: typing.List[Tile] = []
        """The large tiles owned by us."""
        self.playerTargetScores = [0 for i in range(16)]
        self.general: Tile | None = None
        self.gatherNodes = None
        self.redGatherTreeNodes = None
        self.isInitialized = False
        self.last_init_turn: int = 0
        """
        Mainly just for testing purposes, prevents the bot from performing a turn update more than once per turn, 
        which tests sometimes need to trigger ahead of time in order to check bot state ahead of a move.
        """

        # 2v2
        self.teammate: int | None = None
        self.teammate_path: Path | None = None
        self.teammate_general: Tile | None = None

        self._outbound_team_chat: "Queue[str]" = queue.Queue()
        self._tile_ping_queue: "Queue[Tile]" = queue.Queue()

        self._chat_messages_received: "Queue[ChatUpdate]" = queue.Queue()
        self._tiles_pinged_by_teammate: "Queue[Tile]" = queue.Queue()
        self._communications_sent_cooldown_cache: typing.Dict[str, int] = {}
        self.tiles_pinged_by_teammate_this_turn: typing.Set[Tile] = set()
        self.teamed_with_bot: bool = False
        self.teammate_communicator: TeammateCommunicator | None = None
        self.tile_compressor: TileCompressor | None = None

        self.oldAllyThreat: ThreatObj | None = None
        """Last turns ally threat."""

        self.oldThreat: ThreatObj | None = None
        """Last turns threat against us."""

        self.makingUpTileDeficit = False
        self.territories: TerritoryClassifier | None = None

        self.target_player_gather_targets: typing.Set[Tile] = set()
        self.target_player_gather_path: Path | None = None
        self.shortest_path_to_target_player: Path | None = None
        self.shortest_path_to_target_player_distances: typing.List[typing.List[int]] = []

        self.viewInfo: ViewInfo | None = None

        self._minAllowableArmy = -1
        self.threat: ThreatObj | None = None
        self.best_defense_leaves: typing.List[GatherTreeNode] = []
        self.pathableTiles = set()
        self.history = History()
        self.timings: Timings | None = None
        self.armyTracker: ArmyTracker | None = None
        self.finishing_exploration = True
        self.targetPlayerExpectedGeneralLocation: Tile | None = None
        self.lastPlayerKilled = None
        self.launchPoints: typing.List[Tile] | None = []
        self.locked_launch_point: Tile | None = None
        self.flanking: bool = False
        """Set to true if the bot is flanking this cycle and should prepare to launch an earlier attack than normal."""

        self.explored_this_turn = False
        self.undiscovered_priorities: typing.List[typing.List[float]] = []
        self.board_analysis: BoardAnalyzer | None = None

        # engine stuff
        self.targetingArmy: Army | None = None
        self.cached_scrims: typing.Dict[str, ArmySimResult] = {}
        self.next_scrimming_army_tile: Tile | None = None

        # configuration
        self.disable_engine: bool = False

        self.engine_use_mcts: bool = True
        self.mcts_engine: MctsDUCT = MctsDUCT()
        self.engine_allow_force_incoming_armies_towards: bool = False
        self.engine_allow_enemy_no_op: bool = True
        self.engine_force_multi_tile_mcts = True
        self.engine_army_nearby_tiles_range: int = 4
        self.engine_mcts_scrim_armies_per_player_limit: int = 2
        self.engine_honor_mcts_expected_score: bool = False
        self.engine_honor_mcts_expanded_expected_score: bool = True
        self.engine_always_include_last_move_tile_in_scrims: bool = True
        self.engine_mcts_move_estimation_net_differential_cutoff: float = -0.9
        """An engine move result below this score will be ignored in some situations. Lower closer to -1.0 to respect more engine moves."""

        self.gather_include_shortest_pathway_as_negatives: bool = False
        self.gather_include_distance_from_enemy_TERRITORY_as_negatives: int = 3  # 4 is bad, confirmed 217-279 in 500 game match after other previous

        # 2 and 3 both perform well, probably need to make the selection method more complicated as there are probably times it should use 2 and times it should use 3.
        self.gather_include_distance_from_enemy_TILES_as_negatives: int = 3  # 3 is definitely too much, confirmed in lots of games. ACTUALLY SEEMS TO BE CONTESTED NOW 3 WON 500 GAME MATCH, won another 500 game match, using 3...

        self.gather_include_distance_from_enemy_general_as_negatives: float = 0.0
        self.gather_include_distance_from_enemy_general_large_map_as_negatives: float = 0.0

        self.expansion_force_no_global_visited: bool = False
        self.expansion_force_global_visited_stage_1: bool = True
        self.expansion_use_iterative_negative_tiles: bool = True
        self.expansion_use_multi_per_dist_per_tile: bool = True
        self.expansion_allow_leaf_moves: bool = True
        self.expansion_use_leaf_moves_first: bool = True
        self.expansion_single_iteration_time_cap: float = 0.07  # 0.1 did slightly better than 0.06, but revert to 0.06 if expansion takes too long
        self.expansion_length_weight_offset: float = 0.5
        """Positive means prefer longer paths, slightly...?"""

        self.expansion_use_cutoff: bool = True
        """The time cap per large tile search when finding expansions"""

        self.expansion_full_time_limit: float = 0.15
        """The full time limit for an optimal_expansion cycle. Will be cut short if it would run the move too long."""

        self.expansion_small_tile_time_ratio: float = 1.0
        """The ratio of expansion_single_iteration_time_cap that will be used for each small tile path find iteration."""

        self.behavior_out_of_play_defense_threshold: float = 0.40
        """What ratio of army needs to be outside the behavior_out_of_play_distance_over_shortest_ratio distance to trigger out of play defense."""

        self.behavior_losing_on_economy_skip_defense_threshold: float = 0.0
        """The threshold (where 1.0 means even on economy, and 0.9 means losing by 10%) at which we stop defending general."""

        self.behavior_early_retake_bonus_gather_turns: int = 0
        """This is probably just bad but was currently 3. How long to spend gathering to needToKill tiles around general before switching to main gather."""

        self.behavior_max_allowed_quick_expand: int = 7
        """Number of quickexpand turns max always allowed, unrelated to greedy leaves."""

        self.behavior_out_of_play_distance_over_shortest_ratio: float = 0.45
        """Between 0 and 1. 0.3 means any tiles outside 1.3x the shortest pathway length will be considered out of play for out of play army defense."""

        self.behavior_launch_timing_offset: int = 3
        """Negative means launch x turns earlier, positive means later. The actual answer here is probably 'launch after your opponent', so a dynamic launch timing would make the most sense."""

        self.behavior_flank_launch_timing_offset: int = -4
        """Negative means launch x turns earlier, positive means later than normal launch timing would have been."""

        self.behavior_allow_defense_army_scrim: bool = False
        """If true, allows running a scrim with the defense leafmove that WOULD have been made if the defense wasn't immediately necessary, when shorter gather prunes are found."""

        # TODO drop this probably when iterative gather/expansion done.
        self.behavior_allow_pre_gather_greedy_leaves: bool = True
        """If true, allow just-ahead-of-opponent greedy leaf move blobbing."""

        self.behavior_pre_gather_greedy_leaves_army_ratio_cutoff: float = 0.98
        """Smaller = greedy expansion even when behind on army, larger = only do it when already winning on army"""

        self.behavior_pre_gather_greedy_leaves_offset: int = 0
        """Negative means capture that many extra tiles after hitting the 1.05 ratio. Positive means let them stay a little ahead on tiles."""

        self.info_render_gather_values: bool = False

        self.info_render_leaf_move_values: bool = False

        self.info_render_army_emergence_values: bool = True

        self.info_render_city_priority_debug_info: bool = True

        self.info_render_general_undiscovered_prediction_values: bool = False

        self.info_render_tile_deltas: bool = True

        self.info_render_gather_locality_values: bool = False


    def __repr__(self):
        return str(self)

    def __str__(self):
        return f'[eklipz_bot {str(self._map)}]'

    def spawnWorkerThreads(self):
        return

    def detect_repetition(self, move, turns=4, numReps = 2):
        """

        @param move:
        @param turns:
        @param numReps:
        @return:
        """
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
                            logging.info(
                                f"  ---    YOOOOOOOOOO detected {reps} repetitions on {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} in the last {turns} turns")
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

            if self.teammate_communicator is not None:
                teammate_messages = self.teammate_communicator.produce_teammate_communications()
                for msg in teammate_messages:
                    self.send_teammate_communication(msg.message, msg.ping_tile, msg.cooldown, msg.cooldown_detection_on_message_alone, msg.cooldown_key)

            self._map.last_player_index_submitted_move = None
            if move is not None and move.source.player != self.general.player:
                raise AssertionError(f'select_move just returned {str(move)} moving from a tile we didnt own...')
            if move is not None:
                self._map.last_player_index_submitted_move = (move.source, move.dest, move.move_half)

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
        logging.info(f"EH: City found handler! City {str(tile)}")
        self.armyTracker.add_need_to_track_city(tile)
        self.territories.needToUpdateAroundTiles.add(tile)
        if tile.player != -1:
            self.board_analysis.should_rescan = True
        return None

    def handle_tile_captures(self, tile: Tile):
        logging.info(
            f"EH: Tile captured! Tile {repr(tile)}, oldOwner {tile.delta.oldOwner} newOwner {tile.delta.newOwner}")
        self.territories.needToUpdateAroundTiles.add(tile)
        if tile.isCity:
            self.armyTracker.add_need_to_track_city(tile)

            if tile.delta.oldOwner == -1 or tile.delta.newOwner == -1:
                self.board_analysis.should_rescan = True
                if tile.delta.newOwner == -1:
                    return

        if tile.delta.oldOwner == self.general.player or tile.delta.oldOwner in self._map.teammates:
            if not self._map.is_tile_friendly(tile):
                murderer = self._map.players[tile.player]

                # capturing our tiles in no mans land
                tileScore = 10
                if self.territories.territoryMap[tile.x][tile.y] == tile.delta.newOwner:
                    # just protecting themselves in their own territory...?
                    tileScore = 5
                elif self._map.is_player_on_team_with(self.territories.territoryMap[tile.x][tile.y], self.general.player):
                    tileScore = 30

                if tile.isCity:
                    tileScore += 5
                    tileScore = tileScore * 10

                murderer.aggression_factor += tileScore

        return None

    def handle_player_captures(self, capturee: int, capturer: int):
        """
        NOTE: This currently gets called BEFORE the map update is received that updates the visible tiles.

        @param capturee:
        @param capturer:
        @return:
        """
        logging.info(
            f"EH: Player captured! capturee {self._map.usernames[capturee]} ({capturee}) capturer {self._map.usernames[capturer]} ({capturer})")
        for army in list(self.armyTracker.armies.values()):
            if army.player == capturee:
                logging.info(f"EH:   scrapping dead players army {str(army)}")
                self.armyTracker.scrap_army(army)

        self.history.captured_player(self._map.turn, capturee, capturer)

        if capturer == self.general.player:
            logging.info(f"setting lastPlayerKilled to {capturee}")
            self.lastPlayerKilled = capturee
            playerGen = self._map.players[capturee].general
            self.launchPoints.append(playerGen)

        if self._map.remainingPlayers <= 3:
            if not self.winning_on_economy(byRatio=0.8):
                self.viewInfo.addAdditionalInfoLine("not even on economy, going all in effective immediately")
                self.allIn = True
                self.all_in_counter = 300

        return None

    def handle_tile_deltas(self, tile):
        logging.info(f"EH: Tile delta handler! Tile {repr(tile)} delta {tile.delta.armyDelta}")
        return None

    def handle_tile_discovered(self, tile):
        logging.info(f"EH: Tile discovered handler! Tile {repr(tile)}")
        self.territories.needToUpdateAroundTiles.add(tile)
        if tile.isCity and tile.player != -1:
            self.board_analysis.should_rescan = True

        if tile.player >= 0:
            player = self._map.players[tile.player]
            if len(player.tiles) < 4 and tile.player == self.targetPlayer and self.curPath:
                self.viewInfo.addAdditionalInfoLine("killing current path because JUST discovered player...")
                self.curPath = None

        return None

    def handle_tile_vision_change(self, tile: Tile):
        """
        Called whenever we gain or lose vision of a tile.

        @param tile:
        @return:
        """
        logging.info(f"EH: Tile vision change handler! Tile {repr(tile)}")

        self.territories.needToUpdateAroundTiles.add(tile)
        if tile.visible:
            self.territories.revealed_tile(tile)
            if tile.player == -1 and not tile.isMountain and not tile.isCity:
                self.armyTracker.tile_discovered_neutral(tile)

        if tile.visible and tile.player >= 0 and len(self._map.players[tile.player].tiles) < 3:
            if self._map.turn > 15:
                allNew = True
                for otherTile in self._map.players[tile.player].tiles:
                    if not otherTile.delta.gainedSight:
                        allNew = False

                for adj in tile.adjacents:
                    if adj.player in self._map.teammates and adj.delta.armyDelta != 0:
                        # don't announce you found them to teammate when the teammate actually found them.
                        allNew = False

                if allNew:
                    self.send_teammate_communication(f'Found {self._map.usernames[tile.player]}', tile, cooldown=5, detectOnMessageAlone=True)

        if tile.isMountain:
            if self.curPath is not None and tile in self.curPath.tileSet:
                self.curPath = None
            if tile.delta.oldOwner != -1:
                self.armyTracker.add_need_to_track_city(tile)
                self.viewInfo.addAdditionalInfoLine(f'FOG CITY {repr(tile)} WAS WRONG, FORCING RESCANS AND PLAYER PATH RECALCS')
                self.recalculate_player_paths(force=True)
                self.board_analysis.should_rescan = True

        if tile.visible and tile.isCity and tile.player == -1 and tile.delta.oldOwner != -1:
            if self.curPath is not None and tile in self.curPath.tileSet:
                self.viewInfo.addAdditionalInfoLine(f'Ceasing curPath because target city was actually neutral.')
                self.curPath = None
            # TODO

        if tile.isCity:
            self.armyTracker.add_need_to_track_city(tile)

        return None

    def handle_army_moved(self, tile: Tile):
        logging.info(f"EH: Army Moved handler! Tile {repr(tile)}")
        self.armies_moved_this_turn.append(tile)
        # TODO this is very wrong, this handler should take an army / player as param, the mover may not own the tile they moved towards... But probably doesn't matter since we dont need this turn to be super accurate.
        player = self._map.players[tile.player]
        player.last_seen_move_turn = self._map.turn
        self.territories.needToUpdateAroundTiles.add(tile)
        self.territories.revealed_tile(tile)
        return None

    def handle_army_emerged(self, army: Army):
        logging.info(f"EH: Army emerged handler! Army {str(army)}")
        self.territories.needToUpdateAroundTiles.add(army.tile)
        self.territories.revealed_tile(army.tile)
        return None

    def get_elapsed(self):
        return round(time.perf_counter() - self.lastTurnTime, 3)

    def init_turn(self, secondAttempt = False):
        if self.last_init_turn == self._map.turn:
            return

        if not secondAttempt:
            self.viewInfo.turnInc()

        # self.pinged_tiles = set()

        if self._map.is_2v2:
            playerTeam = self._map.teams[self._map.player_index]
            self.teammate = [p for p, t in enumerate(self._map.teams) if t == playerTeam and p != self._map.player_index][0]
            teammatePlayer = self._map.players[self.teammate]
            if not teammatePlayer.dead:
                self.teammate_general = self._map.generals[self.teammate]
                self.teammate_path = self.get_path_to_target(self.teammate_general, preferEnemy=True, preferNeutral=True)
            else:
                self.teammate_general = None
                self.teammate_path = None

            if self.teammate_communicator is None:
                if self.tile_compressor is None:
                    # self.tile_compressor = ServerTileCompressor(self._map)
                    self.tile_compressor = TileCompressor(self._map)  # use friendly one for now, to debug
                self.teammate_communicator = TeammateCommunicator(self._map, self.tile_compressor, self.board_analysis)
            self.teammate_communicator.begin_next_turn()

        self.tiles_pinged_by_teammate_this_turn = set()
        while self._tiles_pinged_by_teammate.qsize() > 0:
            tile = self._tiles_pinged_by_teammate.get()
            self.viewInfo.add_targeted_tile(tile, TargetStyle.GREEN)
            self.tiles_pinged_by_teammate_this_turn.add(tile)

        while self._chat_messages_received.qsize() > 0:
            chatUpdate = self._chat_messages_received.get()
            self.handle_chat_message(chatUpdate)

        self.check_target_player_just_took_city()

        self._spawn_cramped = None

        self.last_init_turn = self._map.turn

        if self._map.turn % 50 == 0:
            for otherPlayer in self._map.players:
                otherPlayer.aggression_factor = otherPlayer.aggression_factor // 2

        if not secondAttempt:
            self.explored_this_turn = False

        if self.defend_economy:
            self.defending_economy_spent_turns += 1

        self.threat_kill_path = None

        timeSinceLastUpdate = 0
        self.redGatherTreeNodes = None
        now = time.perf_counter()
        if self.lastTurnTime != 0:
            timeSinceLastUpdate = now - self.lastTurnTime

        self.lastTurnTime = now
        logging.info(f"\n       ~~~\n       Turn {self._map.turn}   ({timeSinceLastUpdate:.3f})\n       ~~~\n")
        if self.general is not None:
            self._gen_distances = SearchUtils.build_distance_map(self._map, [self.general])

        if self.teammate_general is not None:
            self._ally_distances = SearchUtils.build_distance_map(self._map, [self.teammate_general])

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
            self.armyTracker.scan(lastMove, self._map.turn, self._gen_distances)

        if self._map.turn >= 3 and self.board_analysis.should_rescan:
            # I think reachable tiles isn't built till turn 2? so chokes aren't built properly turn 1
            with self.perf_timer.begin_move_event('Choke re-scan'):
                self.board_analysis.rescan_chokes()

        if self.territories.should_recalculate(self._map.turn):
            with self.perf_timer.begin_move_event('Territory Scan'):
                self.territories.scan()

        for path in self.armyTracker.fogPaths:
            self.viewInfo.color_path(PathColorer(path, 255, 84, 0, 255, 30, 150))

        self.cached_scrims = {}

    def get_timings(self):
        with self.perf_timer.begin_move_event('GatherAnalyzer scan'):
            self.gatherAnalyzer.scan()

        countOnPath = 0
        if self.target_player_gather_targets is not None:
            countOnPath = SearchUtils.count(self.target_player_gather_targets, lambda tile: self._map.is_tile_friendly(tile))
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

        frTileCount = genPlayer.tileCount
        for teammate in self._map.teammates:
            teamPlayer = self._map.players[teammate]
            frTileCount += teamPlayer.tileCount

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
            gatherSplit = 20

        gatherSplit = min(gatherSplit, genPlayer.tileCount - countOnPath)

        if self.targetPlayer == -1 and self._map.remainingPlayers == 2:
            gatherSplit += 3
        gatherSplit += randomVal

        quickExpandSplit = 0
        if self._map.turn > 50:
            if self.targetPlayer != -1:
                maxAllowed = self.behavior_max_allowed_quick_expand
                winningBasedMin = int(targPlayer.tileCount - genPlayer.tileCount + genPlayer.tileCount / 8)
                quickExpandSplit = min(maxAllowed, max(0, winningBasedMin))
                logging.info(f"quickExpandSplit: {quickExpandSplit}")

        if self.defend_economy:
            gatherSplit += 4
            quickExpandSplit = 0

        if self.currently_forcing_out_of_play_gathers:
            gatherSplit += 10
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

        launchTiming = cycleDuration - pathValueWeight - pathLength - 10 + self.behavior_launch_timing_offset

        if self.flanking:
            gatherSplit += self.behavior_flank_launch_timing_offset
            launchTiming = gatherSplit
            quickExpandSplit = 0
            # launchTiming += self.behavior_flank_launch_timing_offset
            # if launchTiming > gatherSplit:
            #     launchTiming = gatherSplit

        if self.target_player_gather_path.start.tile == self.teammate_general:
            gatherSplit -= self.teammate_path.length // 2 + 2
            launchTiming = gatherSplit

        if launchTiming < gatherSplit:
            gatherSplit += self.behavior_launch_timing_offset
            if self.flanking:
                gatherSplit += self.behavior_flank_launch_timing_offset
            self.viewInfo.addAdditionalInfoLine(f'launchTiming was {launchTiming} (pathValueWeight {pathValueWeight}), targetLen {pathLength}, adjusting to be same as gatherSplit {gatherSplit}')
            launchTiming = gatherSplit
        else:
            self.viewInfo.addAdditionalInfoLine(f'launchTiming {launchTiming} (pathValueWeight {pathValueWeight}), targetLen {pathLength}')

        # should usually be 0 except the first turn
        correction = self._map.turn % 50
        timings = Timings(cycleDuration, quickExpandSplit, gatherSplit, launchTiming, offset, self._map.turn + cycleDuration - correction, disallowEnemyGather)

        logging.info(f"Recalculated timings. longSpawns {longSpawns}, Timings {str(timings)}")
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
            includeGatherTreeNodesThatGatherNegative=True,
            pruneToValuePerTurn: bool = False,
            priorityMatrix: MapMatrix[float] | None = None
    ) -> typing.Union[Move, None]:
        turnOffset = self._map.turn + self.timings.offsetTurns
        turnCycleOffset = turnOffset % self.timings.cycleTurns
        if force or (self._map.turn >= 50 and turnCycleOffset < self.timings.splitTurns and startTiles is not None and len(startTiles) > 0):
            self.finishing_exploration = False
            if targetTurns != -1:
                depth = targetTurns
            else:
                depth = self.timings.splitTurns - turnCycleOffset

            if depth <= 0:
                depth += self.timings.cycleTurns

            if depth > GATHER_SWITCH_POINT:
                with self.perf_timer.begin_move_event(f"USING OLD MST GATH depth {depth}"):
                    gatherNodes = self.build_mst(startTiles, 1.0, depth - 1, negativeTiles)
                    # self.redGatherTreeNodes = [node.deep_clone() for node in GatherTreeNodes]
                    gatherNodes = GatherUtils.prune_mst_to_turns(
                        gatherNodes,
                        depth - 1,
                        self.general.player,
                        viewInfo=self.viewInfo if self.info_render_gather_values else None)
                gatherMove = self.get_tree_move_default(gatherNodes)
                if gatherMove is not None:
                    self.viewInfo.addAdditionalInfoLine(
                        f"OLD LEAF MST GATHER MOVE! {gatherMove.source.x},{gatherMove.source.y} -> {gatherMove.dest.x},{gatherMove.dest.y}  leafGatherDepth: {depth}")
                    self.gatherNodes = gatherNodes
                    return self.move_half_on_repetition(gatherMove, 6)
            else:
                skipFunc = None
                if self._map.remainingPlayers > 2:
                    # avoid gathering to undiscovered tiles when there are third parties on the map
                    skipFunc = lambda tile, tilePriorityObject: not tile.discovered

                # if self.defendEconomy:
                #     # we are going to prune down a max value per turn gather so over-gather a bit.
                #     depth = int(depth * 1.3)

                enemyDistanceMap = self.board_analysis.intergeneral_analysis.bMap
                value, gatherNodes = GatherUtils.knapsack_levels_backpack_gather_with_value(
                    self._map,
                    startTiles,
                    depth,
                    negativeTiles=negativeTiles,
                    searchingPlayer=self.general.player,
                    skipFunc=skipFunc,
                    viewInfo=self.viewInfo if self.info_render_gather_values else None,
                    skipTiles=skipTiles,
                    distPriorityMap=enemyDistanceMap,
                    priorityTiles=priorityTiles,
                    includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
                    incrementBackward=False,
                    priorityMatrix=priorityMatrix)

                if self.defend_economy or pruneToValuePerTurn:
                    minGather = value // 3
                    reason = ''
                    if self.defend_economy:
                        minGather = 2 * value // 3
                        reason = 'ECON DEF '
                    prunedCount, prunedValue, gatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                        gatherNodes,
                        minArmy=minGather,
                        searchingPlayer=self.general.player,
                        teams=MapBase.get_teams_array(self._map),
                        viewInfo=self.viewInfo if self.info_render_gather_values else None,
                        allowBranchPrune=False
                    )
                    self.viewInfo.addAdditionalInfoLine(f"{reason}pruned to max gather/turn {prunedValue}/{prunedCount} (min {minGather})")

                self.gatherNodes = gatherNodes

                move = self.get_tree_move_default(self.gatherNodes)
                if move is not None:
                    return self.move_half_on_repetition(move, 6, 4)
                else:
                    logging.info("NO MOVE WAS RETURNED FOR timing_gather?????????????????????")
        else:
            self.finishing_exploration = True
            self.viewInfo.addAdditionalInfoLine("finishExp=True in timing_gather because outside cycle...?")
            logging.info(f"No timing move because outside gather timing window. Timings: {str(self.timings)}")
        return None

    def make_first_25_move(self) -> Move | None:
        if self._map.remainingPlayers < 4 or self._map.is_2v2:
            move = self.get_optimal_first_25_plan_move()
            # TODO should be able to build the whole plan above in an MST prune, no...?
            if move is not None:
                if move.source.player == self.general.player:
                    return move
            return None
            #
            # self.viewInfo.addAdditionalInfoLine('wtf, explan plan was empty but we''re in first 25 still..? Switching to old expansion')
        else:
            with self.perf_timer.begin_move_event(
                    f'First 25 expansion FFA'):

                if self._map.turn < 22:
                    return None

                nonGeneralArmyTiles = [tile for tile in filter(lambda tile: tile != self.general and tile.army > 1, self._map.players[self.general.player].tiles)]

                negativeTiles = set()

                if len(nonGeneralArmyTiles) > 0:
                    negativeTiles.add(self.general)
                elif self.general.army < 3 and self._map.turn < 45:
                    return None

                # EXPLORATION was the old way for 1v1 pre-optimal-first-25
                # path = self.get_optimal_exploration(50 - self._map.turn, negativeTiles=negativeTiles)

                # prioritize tiles that explore the least
                distMap = [[1000 for y in range(self._map.rows)] for x in range(self._map.cols)]
                for tile in self._map.reachableTiles:
                    val = 60 - int(self.get_distance_from_board_center(tile, center_ratio=0.0))
                    distMap[tile.x][tile.y] = val

                # hack
                oldDistMap = self.board_analysis.intergeneral_analysis.bMap
                try:
                    self.board_analysis.intergeneral_analysis.bMap = distMap
                    path, otherPaths = ExpandUtils.get_optimal_expansion(
                        self._map,
                        self.general.player,
                        self.targetPlayer,
                        50 - self._map.turn,
                        self.board_analysis,
                        self.territories.territoryMap,
                        negativeTiles,
                        viewInfo=self.viewInfo
                    )
                finally:
                    self.board_analysis.intergeneral_analysis.bMap = oldDistMap

                if (self._map.turn < 46
                        and self.general.army < 3
                        and len(nonGeneralArmyTiles) == 0
                        and SearchUtils.count(self.general.movable, lambda tile: not tile.isMountain and tile.player == -1) > 0):
                    self.info("Skipping move because general.army < 3 and all army on general and self._map.turn < 46")
                    # dont send 2 army except right before the bonus, making perfect first 25 much more likely
                    return None
                move = None
                if path:
                    self.info("Dont make me expand. You don't want to see me when I'm expanding.")
                    move = self.get_first_path_move(path)
                return move

    def perform_move_prep(self):
        with self.perf_timer.begin_move_event('scan_map()'):
            self.scan_map_for_large_tiles_and_leaf_moves()

        if self.timings and self.timings.get_turn_in_cycle(self._map.turn) == 0:
            self.timing_cycle_ended()

        if self.curPath is not None and self.curPath.start.next.tile.isMountain:
            self.viewInfo.addAdditionalInfoLine(f'Killing curPath because it moved through a mountain.')
            self.curPath = None

        wasFlanking = self.flanking
        if self.target_player_gather_path is None:
            self.recalculate_player_paths(force=True)

        if self.timings is None:
            # needed to not be none for holding fresh cities
            with self.perf_timer.begin_move_event('Recalculating Timings first time...'):
                self.timings = self.get_timings()

        self.check_if_need_to_gather_longer_to_hold_fresh_cities()

        self.army_out_of_play = self.check_army_out_of_play_ratio()
        if not wasFlanking and self.army_out_of_play:
            self.flanking = False
            self.locked_launch_point = None
            self.recalculate_player_paths(force=True)

        if self.timings is None or self.timings.should_recalculate(self._map.turn):
            with self.perf_timer.begin_move_event('Recalculating Timings...'):
                self.timings = self.get_timings()

        if self.determine_should_winning_all_in():
            wasAllIn = self.all_in_army_advantage
            self.all_in_army_advantage = True
            if not wasAllIn:
                cycle = 75
                if self._map.players[self.general.player].tileCount - self.target_player_gather_path.length < 50:
                    cycle = 40
                self.set_all_in_cycle_to_hit_with_current_timings(cycle)
                self.viewInfo.addAdditionalInfoLine(f"GOING ARMY ADV TEMP ALL IN CYCLE {cycle}, CLEARING STUFF")
                self.curPath = None
                self.timings = self.get_timings()
                if self.targetPlayerObj.general is not None and not self.targetPlayerObj.general.visible:
                    self.targetPlayerObj.general.army = 3
                    self.clear_fog_armies_around(self.targetPlayerObj.general)
                self.recalculate_player_paths(force=True)
            # self.all_in_army_advantage_counter += 1
        elif self.all_in_army_advantage and not self.all_in_city_behind:
            self.all_in_army_advantage = False
            self.all_in_army_advantage_counter = 0

        # This is the attempt to resolve the 'dropped packets devolve into unresponsive bot making random moves
        # even though it thinks it is making sane moves' issue. If we seem to have dropped a move, clear moves on
        # the server before sending more moves to prevent moves from backing up and getting executed later.
        if self._map.turn - 1 in self.history.move_history:
            if self.droppedMove():
                logging.info(
                    "\n\n\n^^^^^^^^^VVVVVVVVVVVVVVVVV^^^^^^^^^^^^^VVVVVVVVV^^^^^^^^^^^^^\nD R O P P E D   M O V E ? ? ? ? (Dropped move)... Sending clear_moves...\n^^^^^^^^^VVVVVVVVVVVVVVVVV^^^^^^^^^^^^^VVVVVVVVV^^^^^^^^^^^^^")
                if self.clear_moves_func:
                    with self.perf_timer.begin_move_event('Sending clear_moves due to dropped move'):
                        self.clear_moves_func()

    def select_move(self, allowRetry=True):
        start = time.perf_counter()
        self.init_turn(secondAttempt=not allowRetry)

        if self._map.turn <= 1:
            # bypass divide by 0 error instead of fixing it
            return None

        if self._map.remainingPlayers == 1:
            return None

        self.perform_move_prep()

        with self.perf_timer.begin_move_event("recalculating player path"):
            self.recalculate_player_paths()

        self.prune_timing_split_if_necessary()

        with self.perf_timer.begin_move_event('calculating general danger / threats'):
            self.calculate_general_danger()

        # with self.perf_timer.begin_move_event('Checking 1 move kills'):
        #     quickKillMove = self.check_for_1_move_kills()
        #     if quickKillMove is not None:
        #         return quickKillMove

        if self._map.turn < 50:
            return self.make_first_25_move()

        if self._map.turn < 250 and self._map.remainingPlayers > 3:
            with self.perf_timer.begin_move_event('Ffa Turtle Move'):
                move = self.look_for_ffa_turtle_move()
            if move is not None:
                return move

        self.clean_up_path_before_evaluating()

        if self.curPathPrio >= 0:
            logging.info(f"curPathPrio: {str(self.curPathPrio)}")

        threat = None

        if self.dangerAnalyzer.fastestThreat is not None:
            threat = self.dangerAnalyzer.fastestThreat

        if self.dangerAnalyzer.fastestAllyThreat is not None and (threat is None or self.dangerAnalyzer.fastestAllyThreat.turns < threat.turns):
            if self.determine_should_defend_ally():
                threat = self.dangerAnalyzer.fastestAllyThreat

        if threat is None and not self.giving_up_counter > 30 and self.dangerAnalyzer.fastestVisionThreat is not None:
            threat = self.dangerAnalyzer.fastestVisionThreat

        #  # # # #   ENEMY KING KILLS
        with self.perf_timer.begin_move_event('Checking for king kills and races'):
            (killMove, kingKillPath, canRace) = self.check_for_king_kills_and_races(threat)
            if killMove is not None:
                return killMove

        self.threat = threat
        if threat is not None and threat.saveTile is not None:
            self.viewInfo.evaluatedGrid[threat.saveTile.x][threat.saveTile.y] = 200

        self.check_should_be_all_in()

        if self.allIn:
            logging.info(f"~~~ ___ {self.get_elapsed()}\n   YO WE ALL IN DAWG\n~~~ ___")

        defenseCriticalTileSet = set()
        #if not self.isAllIn() and (threat.turns > -1 and self.dangerAnalyzer.anyThreat):
        #    armyAmount = (self.general_min_army_allowable() + enemyNearGen) * 1.1 if threat is None else threat.threatValue + general.army + 1

        defenseSavePath: Path | None = None
        if threat is not None and not self.allIn and (threat.turns > -1 and threat.threatType == ThreatType.Kill):
            with self.perf_timer.begin_move_event(f'THREAT DEFENSE {threat.turns} {str(threat.path.start.tile)}'):
                defenseMove, defenseSavePath = self.get_defense_moves(defenseCriticalTileSet, kingKillPath)
                if defenseSavePath is not None:
                    self.viewInfo.color_path(PathColorer(defenseSavePath, 255, 100, 255, 200))
                if defenseMove is not None:
                    if defenseMove.source in self.largePlayerTiles:
                        self.targetingArmy = self.get_army_at(threat.path.start.tile)
                    return defenseMove

        if kingKillPath is not None and threat.threatType == ThreatType.Kill:
            if defenseSavePath is None or defenseSavePath.start.tile != kingKillPath.start.tile:
                if defenseSavePath is not None:
                    logging.info(f"savePath was {str(defenseSavePath)}")
                else:
                    logging.info("savePath was NONE")
                self.info(f"    Delayed defense kingKillPath. canRace {canRace}  {str(kingKillPath)}")
                self.viewInfo.color_path(PathColorer(kingKillPath, 158, 158, 158, 255, 10, 200))

                return Move(kingKillPath.start.tile, kingKillPath.start.next.tile)
            else:
                if defenseSavePath is not None:
                    logging.info(f"savePath was {str(defenseSavePath)}")
                else:
                    logging.info("savePath was NONE")
                logging.info(
                    f"savePath tile was also kingKillPath tile, skipped kingKillPath {str(kingKillPath)}")

        with self.perf_timer.begin_move_event('ARMY SCRIMS'):
            armyScrimMove = self.check_for_army_movement_scrims()
            if armyScrimMove is not None:
                #already logged
                return armyScrimMove

        with self.perf_timer.begin_move_event('DANGER TILES'):
            dangerTileKillMove = self.check_for_danger_tile_moves()
            if dangerTileKillMove is not None:
                return dangerTileKillMove   # already logged to info

        gatherTargets = self.target_player_gather_path.tileList

        if not self.allIn:
            with self.perf_timer.begin_move_event('City Analyzer'):
                self.cityAnalyzer.re_scan(self.board_analysis)

            with self.perf_timer.begin_move_event('city_quick_kill'):
                path = self.get_quick_kill_on_enemy_cities(defenseCriticalTileSet)
            if path is not None:
                self.info(f'Quick Kill on enemy city: {str(path)}')
                self.curPath = path
                return self.get_first_path_move(path)

        numTilesAdjKing = SearchUtils.count(self.general.adjacents, lambda tile: tile.army > 2 and self._map.is_tile_enemy(tile))
        if numTilesAdjKing == 1:
            visionTiles = filter(lambda tile: self._map.is_tile_enemy(tile) and tile.army > 2, self.general.adjacents)
            for annoyingTile in visionTiles:
                playerTilesAdjEnemyVision = [x for x in filter(lambda threatAdjTile: threatAdjTile.player == self.general.player and threatAdjTile.army > annoyingTile.army // 2 and threatAdjTile.army > 1, annoyingTile.movable)]
                if len(playerTilesAdjEnemyVision) > 0:
                    largestAdjTile = max(playerTilesAdjEnemyVision, key=lambda myTile: myTile.army)
                    if largestAdjTile and (not largestAdjTile.isGeneral or largestAdjTile.army + 1 > annoyingTile.army):
                        nukeMove = Move(largestAdjTile, annoyingTile)
                        self.info(f'Nuking general-adjacent vision tile {str(nukeMove)}.')
                        self.targetingArmy = self.get_army_at(annoyingTile)
                        return nukeMove

        if self.targetingArmy and not self.targetingArmy.scrapped and self.targetingArmy.tile.army > 2:
            with self.perf_timer.begin_move_event('Continue Army Kill'):
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
        self.defend_economy = self.should_defend_economy()

        with self.perf_timer.begin_move_event(f'capture_cities'):
            (cityPath, gatherMove) = self.capture_cities(defenseCriticalTileSet)

        if cityPath is not None:
            logging.info(f"{self.get_elapsed()} returning capture_cities cityPath {str(cityPath)}")
            self.curPath = cityPath
            return self.get_first_path_move(cityPath)
        elif gatherMove is not None:
            logging.info(f"{self.get_elapsed()} returning capture_cities gatherMove {str(gatherMove)}")
            return gatherMove

        # if self.threat_kill_path is not None and self.threat_kill_path:
        #     self.info(f"we're pretty safe from threat via gather, trying to kill threat instead.")
        #     # self.curPath = path
        #     self.targetingArmy = self.get_army_at(self.threat.path.start.tile)
        #     move = self.get_first_path_move(self.threat_kill_path)
        #     if not self.detect_repetition(move, 4, numReps=3):
        #         if self.detect_repetition(move, 4, numReps=2):
        #             move.move_half = True
        #         return move

        if 50 <= self._map.turn < 75:
            move = self.try_gather_tendrils_towards_enemy()
            if move is not None:
                return move

        threatDefenseLength = 2 * self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3 + 1
        if self.targetPlayerExpectedGeneralLocation.isGeneral:
            threatDefenseLength = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 2 + 2

        if (
                threat is not None
                and threat.threatType == ThreatType.Kill
                and threat.path.length < threatDefenseLength
                and not self.is_all_in()
                and self._map.remainingPlayers < 4
                and threat.threatPlayer == self.targetPlayer
        ):
            logging.info(f"*\\*\\*\\*\\*\\*\n  Kill (non-vision) threat??? ({time.perf_counter() - start:.3f} in)")
            threatKill = self.kill_threat(threat)
            if threatKill and self.worth_path_kill(threatKill, threat.path, threat.armyAnalysis):
                self.targetingArmy = self.get_army_at(threat.path.start.tile)
                saveTile = threatKill.start.tile
                nextTile = threatKill.start.next.tile
                move = Move(saveTile, nextTile)
                if not self.detect_repetition(move, 6, 3):
                    self.viewInfo.color_path(PathColorer(threatKill, 0, 255, 204, 255, 10, 200))
                    move.move_half = self.should_kill_path_move_half(threatKill)
                    self.info(f"Threat kill. half {move.move_half}, {threatKill.toString()}")
                    return move

        if (
                threat is not None
                and threat.threatType == ThreatType.Vision
                and not self.is_all_in()
                and threat.path.start.tile.visible
                and self.should_kill(threat.path.start.tile)
                and self.just_moved(threat.path.start.tile)
                and threat.path.length < min(10, self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 2 + 1)
                and self._map.remainingPlayers < 4
                and threat.threatPlayer == self.targetPlayer
        ):
            logging.info(f"*\\*\\*\\*\\*\\*\n  Kill vision threat. ({time.perf_counter() - start:.3f} in)")
            # Just kill threat then, nothing crazy
            path = self.kill_enemy_path(threat.path, allowGeneral = True)

            visionKillDistance = 5
            if path is not None and self.worth_path_kill(path, threat.path, threat.armyAnalysis, visionKillDistance):
                self.targetingArmy = self.get_army_at(threat.path.start.tile)
                self.info(f"Killing vision threat {threat.path.start.tile.toString()} with path {str(path)}")
                self.viewInfo.color_path(PathColorer(path, 0, 156, 124, 255, 10, 200))
                move = self.get_first_path_move(path)
                if not self.detect_repetition(move, turns=4, numReps=2) and (not path.start.tile.isGeneral or self.general_move_safe(move.dest)):
                    move.move_half = self.should_kill_path_move_half(path)
                    return move
            elif threat.path.start.tile == self.targetingArmy:
                logging.info("threat.path.start.tile == self.targetingArmy and not worth_path_kill. Setting targetingArmy to None")
                self.targetingArmy = None
            elif path is None:
                logging.info("No vision threat kill path?")

        exploreMove = self.try_find_exploration_move(defenseCriticalTileSet)
        if exploreMove is not None:
            return exploreMove  # already logged

        if self.is_all_in():
            hitGeneralAtTurn = self.all_in_army_advantage_cycle - self.all_in_army_advantage_counter % self.all_in_army_advantage_cycle
            flankAllInMove = self.try_find_flank_all_in(hitGeneralAtTurn)

            if flankAllInMove:
                self.all_in_army_advantage_counter += 1
                return flankAllInMove

            targets = [self.targetPlayerExpectedGeneralLocation]
            andTargs = ''
            if self.all_in_army_advantage or self.all_in_city_behind:
                andTargs = ' (and cities)'
                if self.all_in_city_behind or self._map.remainingPlayers == 2:
                    targets.extend(self.targetPlayerObj.cities)
            msg = f'all in gather AT target general{andTargs}, {hitGeneralAtTurn} remaining'

            with self.perf_timer.begin_move_event(f'all in gather AT target general{andTargs}, {hitGeneralAtTurn} remaining. self.all_in_army_advantage_cycle {self.all_in_army_advantage_cycle}, self.all_in_army_advantage_counter {self.all_in_army_advantage_counter}'):
                gathNeg = defenseCriticalTileSet.copy()
                if self.all_in_army_advantage:
                    for contestedCity in self.cityAnalyzer.owned_contested_cities:
                        gathNeg.add(contestedCity)

                move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_target_tiles(
                    targets,
                    0.1,
                    hitGeneralAtTurn,
                    maximizeArmyGatheredPerTurn=True,
                    negativeSet=gathNeg)
            if move is not None:
                self.info(msg)
                if hitGeneralAtTurn > 15:
                    self.send_teammate_communication(f'All in here, hit in {hitGeneralAtTurn} moves', detectionKey='allInAtGenTargets', cooldown=10)

                for target in targets:
                    self.send_teammate_tile_ping(target, cooldown=25, cooldownKey=f'allIn{str(target)}')

                self.all_in_army_advantage_counter += 1
                self.gatherNodes = gatherNodes
                return move

        #if len(paths) == 0 and (self.curPath is None or self.curPath.start.next is None) and self._map.turn >= 50:
        if (self.curPath is None or self.curPath.start.next is None) and not self.defend_economy:
            attackLaunchMove = self.check_for_attack_launch_move()
            if attackLaunchMove is not None:
                return attackLaunchMove

            move = self.try_find_expansion_move(defenseCriticalTileSet)
            if move is not None:
                return move  # already logged

        needToKillTiles = list()
        if not self.timings.disallowEnemyGather and not self.allIn:
            needToKillTiles = self.find_key_enemy_vision_tiles()
            for tile in needToKillTiles:
                self.viewInfo.add_targeted_tile(tile, TargetStyle.RED)

        # LEAF MOVES for the first few moves of each cycle
        timingTurn = self.timings.get_turn_in_cycle(self._map.turn)
        quickExpTimingTurns = self.timings.quickExpandTurns - self._map.turn % self.timings.cycleTurns

        earlyRetakeTurns = quickExpTimingTurns + self.behavior_early_retake_bonus_gather_turns - self._map.turn % self.timings.cycleTurns

        if (not self.is_all_in()
                and self._map.remainingPlayers <= 3
                and earlyRetakeTurns > 0
                and len(needToKillTiles) > 0
                and timingTurn >= self.timings.quickExpandTurns
        ):
            actualGatherTurns = earlyRetakeTurns

            with self.perf_timer.begin_move_event(f'early retake turn gather?'):
                gatherNodes = GatherUtils.knapsack_levels_backpack_gather(
                    self._map,
                    list(needToKillTiles),
                    actualGatherTurns,
                    negativeTiles=defenseCriticalTileSet,
                    searchingPlayer=self.general.player,
                    incrementBackward=False,
                    viewInfo= self.viewInfo if self.info_render_gather_values else None,
                    ignoreStartTile=True,
                    useTrueValueGathered=True)
            self.gatherNodes = gatherNodes
            move = self.get_tree_move_default(gatherNodes)
            if move is not None:
                self.info(
                    f"NeedToKillTiles for turns {earlyRetakeTurns} ({actualGatherTurns}) in quickExpand. Move {str(move)}")
                return move

        if self.curPath is not None:
            move = self.continue_cur_path(threat, defenseCriticalTileSet)
            if move is not None:
                return move  # already logged

        if not self.is_all_in() and not self.defend_economy and quickExpTimingTurns > 0:
            move = self.try_gather_tendrils_towards_enemy(quickExpTimingTurns)
            if move is not None:
                return move

            moves = self.prioritize_expansion_leaves(self.leafMoves)
            if len(moves) > 0:
                move = moves[0]
                self.info(f"quickExpand leafMove {str(move)}")
                return move

        if self.defend_economy:
            move = self.try_find_army_out_of_position_move(defenseCriticalTileSet)
            if move is not None:
                return move  # already logged

        if self.behavior_allow_pre_gather_greedy_leaves:
            if (
                    not self._map.remainingPlayers > 2
                    and not self.is_player_spawn_cramped()
                    and not self.winning_on_economy(byRatio=1.05, cityValue=10, offset=self.behavior_pre_gather_greedy_leaves_offset)
                    and self.winning_on_army(self.behavior_pre_gather_greedy_leaves_army_ratio_cutoff)
                    and self.shortest_path_to_target_player.length > 17
            ):
                if not self.is_all_in():
                    with self.perf_timer.begin_move_event(f'GREEDY prio leafMove'):
                        moves = self.prioritize_expansion_leaves(self.leafMoves)
                    if len(moves) > 0:
                        move = moves[0]
                        self.info(f"GREEDY prio leafMove {str(move)}")
                        return move
                    with self.perf_timer.begin_move_event(f'GREEDY leafMove'):
                        leafMove = self.find_leaf_move(self.leafMoves)
                    if leafMove is not None:
                        self.info(f"GREEDY leafMove {str(leafMove)}")
                        return leafMove

        with self.perf_timer.begin_move_event('MAIN GATHER OUTER'):
            gathMove = self.try_find_gather_move(threat, defenseCriticalTileSet, self.leafMoves, needToKillTiles)
        if gathMove is not None:
            # already logged / perf countered internally
            return gathMove

        with self.perf_timer.begin_move_event(f'No gather found final scrim'):
            scrimMove = self.find_end_of_turn_scrim_move(threat, kingKillPath)
            if scrimMove is not None:
                return scrimMove

        # NOTE NOTHING PAST THIS POINT CAN TAKE ANY EXTRA TIME

        if not self.is_all_in():
            with self.perf_timer.begin_move_event(f'No move found leafMove'):
                leafMove = self.find_leaf_move(self.leafMoves)
            if leafMove is not None:
                self.info(f"No move found leafMove? {str(leafMove)}")
                return leafMove

        self.curPathPrio = -1

        with self.perf_timer.begin_move_event('FOUND NO MOVES FINAL GATH'):
            gathers = self.build_mst(self.target_player_gather_targets, 1.0, 25,  None)

            turns, value, gathers = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                gathers,
                1,
                self.general.player,
                teams=MapBase.get_teams_array(self._map),
                viewInfo=self.viewInfo if self.info_render_gather_values else None)

            self.gatherNodes = gathers
            #move = self.get_gather_move(gathers, None, 1, 0, preferNeutral = True)
            move = self.get_tree_move_default(gathers)
            if move is None:
                turnInCycle = self.timings.get_turn_in_cycle(self._map.turn)
                if self.timings.cycleTurns - turnInCycle < self.timings.cycleTurns - self.target_player_gather_path.length * 0.66:
                    self.info("Found-no-moves-gather NO MOVE? Set launch now.")
                    self.timings.launchTiming = self._map.turn % self.timings.cycleTurns
                else:
                    self.info("Found-no-moves-gather found no move, launch ineffective, no move.")
            elif self.is_move_safe_valid(move):
                self.info(f"Found-no-moves-gather found {value}v/{turns}t gather, using {str(move)}")
                return move
            else:
                self.info(
                    f"Found-no-moves-gather move {str(move)} was not safe or valid!")

        return None

    def is_all_in(self):
        return self.allIn or self.all_in_army_advantage or self.all_in_city_behind

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
            if self._map.is_tile_enemy(tile):
                keyTiles.add(tile)
        for city in genPlayer.cities:
            if self._map.turn - city.turn_captured > 20:
                for tile in city.adjacents:
                    if self._map.is_tile_enemy(tile):
                        keyTiles.add(tile)

        for tile in self._map.pathableTiles:
            if self._map.is_tile_enemy(tile):
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
            self.viewInfo.paths.append(PathColorer(pathKill.clone(), 163, 129, 50, 255, 0, 100))
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
        canGoOtherDirection = True
        for node in self.best_defense_leaves:
            if node.tile == pathKill.start.tile:
                # if self.board_analysis.intergeneral_analysis.bMap[node.fromTile.x][node.fromTile.y] >= startDist:
                    # we have to move backwards anyway, kill the threat.
                canGoOtherDirection = False
        logging.info(
            f"worth_path_kill: movingTowardsOppo {movingTowardsOppo}  ({pathKill.start.tile.toString()} [{startDist}]  ->  {lastTile.toString()} [{tailDist}])")
        onShortestPathwayAlready = (pathKill.start.tile in analysis.pathWayLookupMatrix[threatPath.start.tile].tiles
                                    or (pathKill.start.tile in analysis.pathWayLookupMatrix
                                        and analysis.pathWayLookupMatrix[pathKill.start.tile].distance < analysis.pathWayLookupMatrix[threatPath.start.tile].distance))

        logging.info(
            f"worth_path_kill: onPath = pathKill.start.tile {pathKill.start.tile.toString()} in analysis.pathways[threatPath.start.tile {threatPath.start.tile.toString()}].tiles: {onShortestPathwayAlready}")

        enTilesInPath = SearchUtils.where(pathKill.tileList, lambda t: self._map.is_tile_enemy(t))

        # TODO switch to true based returns.
        # moving towards opp with recapture potential at end of round, etc.

        threatNegs = pathKill.tileSet.copy()
        threatNegs.add(threatPath.tail.tile)
        threatNegs.discard(threatPath.start.tile)
        killOverlap = pathKill.calculate_value(self.general.player, threatPath.tileSet) - threatPath.calculate_value(threatPath.start.tile.player, threatNegs)

        turnsLeftInCycle = self.timings.get_turns_left_in_cycle(self._map.turn)
        turnsLeftInCycleCutoffThresh = turnsLeftInCycle // 2 - 1
        if pathKill.length - len(enTilesInPath) > turnsLeftInCycleCutoffThresh and canGoOtherDirection and not movingTowardsOppo:
            self.viewInfo.addAdditionalInfoLine(f'Eliminated path kill due to len {pathKill.length} - enTilesInPath {len(enTilesInPath)} > cycleCutoffThresh {turnsLeftInCycleCutoffThresh}')
            return False

        #if pathKill.length > cutoffDistance and onShortestPathwayAlready and not movingTowardsOppo:
        # if pathKill.length > cutoffDistance and not movingTowardsOppo and canGoOtherDirection:
        #     # then we're already on their attack path? Don't waste time moving towards it unless we're close.
        #     self.viewInfo.paths.append(PathColorer(pathKill.clone(), 217, 0, 0, 255, 0, 100))
        #     logging.info(
        #         f"  path kill eliminated due to pathKill.length > cutoffDistance {cutoffDistance} ({pathKill.length > cutoffDistance}) and onShortestPathwayAlready {onShortestPathwayAlready} and not movingTowardsOppo {movingTowardsOppo}")
        #     return False
        logging.info(f"  path kill worth it because not eliminated ({pathKill.toString()})")
        return True

    def kill_army(
            self,
            army: Army,
            allowGeneral=False,
            allowWorthPathKillCheck=True
    ):
        def pathToGenFunc(current: Tile, curArmyAmt: int, distance: int) -> bool:
            if current == self.general:
                return True
            return False
        # return None
        path = SearchUtils.breadth_first_find_queue(self._map, [army.tile], pathToGenFunc, noNeutralCities = True, searchingPlayer = army.player)

        if not path:
            logging.info(f"In Kill_army: No bfs dynamic path found from army tile {str(army)} ???????")
            return None

        self.viewInfo.paths.append(PathColorer(path.clone(), 100, 0, 100, 200, 5, 100))
        killPath = self.kill_enemy_path(path, allowGeneral)

        if killPath is not None:
            if not allowWorthPathKillCheck:
                return killPath
            with self.perf_timer.begin_move_event(f'build army analyzer for continue army kill of {repr(army)}'):
                analyzer = ArmyAnalyzer(self._map, self.general, army.tile)
            worthPathKill = self.worth_path_kill(killPath, path, analyzer)
            if worthPathKill:
                return killPath

            self.viewInfo.addAdditionalInfoLine(
                f"NO army cont kill on {str(army)} because not worth with path {str(killPath)}")
        else:
            self.viewInfo.addAdditionalInfoLine(f"NO army cont kill on {str(army)}, no pathKill was found.")

        return None

    def kill_enemy_path(self, threatPath: Path, allowGeneral = False) -> Path | None:
        """
        This is some wild shit that needs to be redone.
        @param threatPath: The threat path, except for some reason it starts at the general and ends at the threat
        @param allowGeneral:
        @return:
        """
        path = self.try_find_counter_army_scrim_path_killpath(threatPath, allowGeneral)
        if path is not None:
            return path

        armyAnalysis = ArmyAnalyzer(self._map, self.get_army_at(threatPath.tail.tile), self.get_army_at(threatPath.start.tile))
        threat = ThreatObj(threatPath.length, threatPath.value, threatPath, ThreatType.Vision, armyAnalysis=armyAnalysis)

        # move, value, turnsUsed, gatherNodes = self.get_gather_to_threat_path(threat, gatherMax=False)
        # if move is not None:
        #     path = Path()
        #     path.add_next(move.source)
        #     path.add_next(move.dest)
        #     return path
        #
        # return None

        negativeTiles = set()

        # Doesn't make any sense to have the general defend against his own threat, does it? Maybe it does actually hm
        if not allowGeneral:
            negativeTiles.add(self.general)

        logging.info(f"Starting kill_enemy_path for path {threatPath.toString()}")

        if threatPath.value <= 0:
            # the enemy path has to path through us, just try to kill the army
            killPath = SearchUtils.dest_breadth_first_target(self._map, [threatPath.tail.tile], maxDepth=6, negativeTiles=negativeTiles)
            if killPath is not None:
                return killPath

        if threatPath.length <= 3:
            logging.info('threat path too short for kill_enemy_path and no army scrim move found..?')
            return None

        startTime = time.perf_counter()
        shorterThreatPath = threatPath.get_subsegment(threatPath.length - 2)
        threatPathSet = shorterThreatPath.tileSet.copy()
        threatPathSet.remove(threatPath.start.tile)
        #negativeTiles = threatPathSet.copy()

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
            #for tile in threatPathSet:
            #    if tile.player == threatPath.start.tile.player:
            #        negativeTiles.add(tile)
            logging.info(
                f"threatValue was originally {threatPath.value}, removed player negatives and is now {threatValue}")
        else:
            logging.info(f"threatValue is {threatValue}")

        # First try one move kills on next tile, since I think this is broken in the loop for whatever reason... (make it 2 moves though bc other stuff depends on tail tile)
        for adj in threatPath.start.next.tile.movable:
            if adj.army > 3 and adj.player == self.general.player and adj.army >= threatValue and adj != threatTile:
                path = Path()
                path.add_next(adj)
                path.add_next(threatPath.start.next.tile)
                path.add_next(threatTile)
                self.viewInfo.addAdditionalInfoLine(f"returning nextTile direct-kill move {str(path)}")
                return path

        # Then try one move kills on the threat tile. 0 = 1 move????
        for adj in threatTile.movable:
            if adj.army > 3 and adj.player == self.general.player and adj.army >= threatValue:
                path = Path()
                path.add_next(adj)
                path.add_next(threatTile)
                self.viewInfo.addAdditionalInfoLine(f"returning direct-kill move {str(path)}")
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
            gatherToThreatPath = SearchUtils.dest_breadth_first_target(self._map, [curNode.tile], targetArmy = threatValue + threatModifier, maxDepth = max(1, i), searchingPlayer = self.general.player, negativeTiles = negativeTiles, noLog = True, ignoreGoalArmy = True)
            #if curNode.tile.player == self.general.player:
            #    nodeVal = curNode.tile.army - 1
            #gatherToThreatPath = SearchUtils.dest_breadth_first_target(self._map, [curNode.tile], targetArmy = threatValue + nodeVal, maxDepth = max(1, i), searchingPlayer = self.general.player, negativeTiles = negativeTiles, noLog = True)
            i += 1
            curNode = curNode.next

        if gatherToThreatPath is not None:
            self.viewInfo.addAdditionalInfoLine(
                f"whoo, found kill on threatpath with path {gatherToThreatPath.toString()}")
            alpha = 140
            minAlpha = 100
            alphaDec = 2
            self.viewInfo.color_path(PathColorer(gatherToThreatPath.clone(), 150, 10, 255, alpha, alphaDec, minAlpha))
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

            threatPathToThreat = SearchUtils.breadth_first_dynamic(self._map, inputTiles, goalFunc, noNeutralCities=True, priorityFunc=threatPathSortFunc)
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

    def get_gather_to_target_tile(
            self,
            target: Tile,
            maxTime: float,
            gatherTurns: int,
            negativeSet: typing.Set[Tile] | None = None,
            targetArmy: int = -1,
            useTrueValueGathered = False,
            includeGatherTreeNodesThatGatherNegative = False,
            maximizeArmyGatheredPerTurn: bool = False
    ) -> typing.Tuple[typing.Union[Move, None], int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        """
        returns move, valueGathered, turnsUsed

        @param target:
        @param maxTime:
        @param gatherTurns:
        @param negativeSet:
        @param targetArmy:
        @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
         capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
         so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
         gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
         Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
        @param maximizeArmyGatheredPerTurn: if set to True, will prune the result to the maximum gather value amount per turn.
        @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
         to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
         Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
        @return:
        """
        targets = [target]
        gatherTuple = self.get_gather_to_target_tiles(
            targets,
            maxTime,
            gatherTurns,
            negativeSet,
            targetArmy,
            useTrueValueGathered=useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            maximizeArmyGatheredPerTurn=maximizeArmyGatheredPerTurn)
        return gatherTuple

    # set useTrueValueGathered to True for things like defense gathers,
    # where you want to take into account army lost gathering over enemy or neutral tiles etc.
    def get_gather_to_target_tiles(
            self,
            targets,
            maxTime,
            gatherTurns,
            negativeSet = None,
            targetArmy = -1,
            useTrueValueGathered = False,
            leafMoveSelectionPriorityFunc = None,
            leafMoveSelectionValueFunc = None,
            includeGatherTreeNodesThatGatherNegative = False,
            maximizeArmyGatheredPerTurn: bool = False,
            additionalIncrement: int = 0,
            shouldLog: bool =False,
    ) -> typing.Tuple[typing.Union[Move, None], int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        """
        returns move, valueGathered, turnsUsed, gatherNodes

        @param targets:
        @param maxTime:
        @param gatherTurns:
        @param negativeSet:
        @param targetArmy:
        @param additionalIncrement: if need to gather extra army due to incrementing, include the POSITIVE enemy city increment or NEGATIVE allied increment value here.
        @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
         capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
         so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
         gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
         Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
        @param maximizeArmyGatheredPerTurn: if set to True, will prune the result to the maximum gather value amount per turn.
        @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
         to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
         Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
        @param leafMoveSelectionPriorityFunc:
        @param leafMoveSelectionValueFunc:
        @return:
        """

        #gatherNodes = self.build_mst(targets, maxTime, gatherTurns, gatherNegatives, negativeSet)
        #move = self.get_gather_move(gatherNodes, None, targetArmy, None)
        if gatherTurns > GATHER_SWITCH_POINT:
            logging.info(f"    gather_to_target_tiles  USING OLD GATHER DUE TO gatherTurns {gatherTurns}")
            gatherNodes = self.build_mst(targets, maxTime, gatherTurns - 1, negativeSet)
            gatherNodes = GatherUtils.prune_mst_to_turns(gatherNodes, gatherTurns - 1, self.general.player, viewInfo=self.viewInfo)

            if maximizeArmyGatheredPerTurn:
                turns, value, gatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                    gatherNodes,
                    targetArmy,
                    searchingPlayer=self.general.player,
                    teams=MapBase.get_teams_array(self._map),
                    additionalIncrement=additionalIncrement,
                    viewInfo=self.viewInfo)

            gatherMove = self.get_tree_move_default(gatherNodes, priorityFunc=leafMoveSelectionPriorityFunc, valueFunc=leafMoveSelectionValueFunc)
            value = 0
            turns = 0
            for node in gatherNodes:
                value += node.value
                turns += node.gatherTurns
            if gatherMove is not None:
                self.info(
                    f"gather_to_target_tiles OLD GATHER {gatherMove.source.toString()} -> {gatherMove.dest.toString()}  gatherTurns: {gatherTurns}")
                self.gatherNodes = gatherNodes
                return self.move_half_on_repetition(gatherMove, 6), value, turns, gatherNodes
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
                includeGatherTreeNodesThatGatherNegative = includeGatherTreeNodesThatGatherNegative,
                shouldLog=shouldLog)

            if maximizeArmyGatheredPerTurn:
                turns, value, gatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                    gatherNodes,
                    targetArmy,
                    searchingPlayer=self.general.player,
                    teams=MapBase.get_teams_array(self._map),
                    additionalIncrement=additionalIncrement,
                    viewInfo=self.viewInfo)

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
            negativeSet = None,
            targetArmy = -1,
            useTrueValueGathered = False,
            priorityFunc = None,
            valueFunc = None,
            includeGatherTreeNodesThatGatherNegative = False,
            maximizeArmyGatheredPerTurn: bool = False,
            shouldLog: bool =False
    ) -> typing.Tuple[typing.Union[Move, None], int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        """
        returns move, valueGathered, turnsUsed, gatherNodes

        @param targets:
        @param maxTime:
        @param gatherTurns:
        @param negativeSet:
        @param targetArmy:
        @param useTrueValueGathered: Use True for things like capturing stuff. Causes the algo to include the cost of
         capturing tiles in the value calculation. Also include the cost of the gather start tile into the gather FINDER
         so that it only finds paths that kill the target. Avoid using this when just gathering as it prevents
         gathering tiles on the other side of enemy territory, which is the opposite of good general gather behavior.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
         Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
        @param maximizeArmyGatheredPerTurn: if set to True, will prune the result to the maximum gather value amount per turn.
        @param includeGatherTreeNodesThatGatherNegative: if set True, allows the gather PLAN to gather
         to tiles without killing them. Use this for defense for example, when you dont need to fully kill the threat tile with each gather move.
         Use includeGatherTreeNodesThatGatherNegative to allow a gather to return gather nodes in the final result that fail to flip an enemy node in the path to friendly.
         Use useTrueValueGathered to make sure the gatherValue returned by the gather matches the actual amount of army you will have on the gather target tiles at the end of the gather execution.
        @param priorityFunc:
        @param valueFunc:
        @return:
        """

        gatherNodes = GatherUtils.greedy_backpack_gather(
            self._map,
            targets,
            gatherTurns,
            targetArmy,
            negativeTiles = negativeSet,
            searchingPlayer = self.general.player,
            viewInfo = self.viewInfo,
            useTrueValueGathered = useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            shouldLog=shouldLog)

        if maximizeArmyGatheredPerTurn:
            turns, value, gatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                gatherNodes,
                targetArmy,
                searchingPlayer=self.general.player,
                teams=MapBase.get_teams_array(self._map),
                viewInfo=self.viewInfo)

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

    def euclidDist(self, x: float, y: float, x2: float, y2: float) -> float:
        if x == x2 and y == y2:
            return 0
        return pow(pow(abs(x - x2), 2) + pow(abs(y - y2), 2), 0.5)

    def euclidDistTile(self, a: Tile, b: Tile) -> float:
        return self.euclidDist(a.x, a.y, b.x, b.y)

    def sum_enemy_army_near_tile(self, startTile: Tile, distance: int = 2) -> int:
        """does NOT include the value of the tile itself."""
        enemyNear = SearchUtils.Counter(0)

        counterLambda = lambda tile: enemyNear.add(tile.army - 1)
        negativeLambda = lambda tile: tile.isNeutral or self._map.is_tile_friendly(tile)
        skipFunc = lambda tile: tile.isCity and tile.isNeutral and tile != startTile
        SearchUtils.breadth_first_foreach(self._map, [startTile], distance, counterLambda, negativeLambda, skipFunc, noLog = True, bypassDefaultSkip=True)
        value = enemyNear.value
        if self._map.is_tile_enemy(startTile):
            # don't include the tiles army itself...
            value = value - (startTile.army - 1)
        #logging.info("enemy_army_near for tile {},{} returned {}".format(tile.x, tile.y, value))
        return value

    def count_enemy_territory_near_tile(self, startTile: Tile, distance: int = 2) -> int:
        enemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile):
            tileIsNeutAndNotEnemyTerritory = tile.isNeutral and (tile.visible or self.territories.territoryMap[tile.x][tile.y] != self.targetPlayer)
            if not tileIsNeutAndNotEnemyTerritory and self._map.is_tile_enemy(tile):
                enemyNear.add(1)

        skipFunc = lambda tile: tile.isObstacle and tile != startTile
        SearchUtils.breadth_first_foreach(self._map, [startTile], distance, counterFunc, skipFunc=skipFunc, noLog=True, bypassDefaultSkip=True)
        value = enemyNear.value
        return value

    def count_enemy_tiles_near_tile(self, startTile: Tile, distance: int = 2) -> int:
        enemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile):
            if not tile.isNeutral and not self._map.is_tile_friendly(tile):
                enemyNear.add(1)

        skipFunc = lambda tile: tile.isObstacle and tile != startTile
        SearchUtils.breadth_first_foreach(self._map, [startTile], distance, counterFunc, skipFunc=skipFunc, noLog = True)
        value = enemyNear.value
        return value

    def sum_player_army_near_tile(self, tile: Tile, distance: int = 2, player: int | None = None) -> int:
        """
        does not include the army value ON the tile itself.

        @param tile:
        @param distance:
        @param player: if None, will use self.general.player
        @return:
        """

        armyNear = self.sum_player_army_near_or_on_tiles([tile], distance, player)
        logging.info(f"player_army_near for tile {tile.x},{tile.y} player {player} returned {armyNear}")
        if tile.player == player:
            # don't include the tiles army itself...
            armyNear = armyNear - (tile.army - 1)
        return armyNear

    def sum_player_army_near_or_on_tiles(self, tiles: typing.List[Tile], distance: int = 2, player: int | None = None) -> int:
        """
        DOES include the army value ON the tile itself.

        @param tiles:
        @param distance:
        @param player: if None, will use self.general.player
        @return:
        """
        if player is None:
            player = self._map.player_index
        armyNear = SearchUtils.Counter(0)
        counterLambda = lambda tile: armyNear.add(tile.army - 1)
        negativeLambda = lambda tile: tile.player != player
        SearchUtils.breadth_first_foreach(self._map, tiles, distance, counterLambda, negativeLambda)
        value = armyNear.value
        return value

    def sum_friendly_army_near_tile(self, tile: Tile, distance: int = 2, player: int | None = None) -> int:
        """
        does not include the army value ON the tile itself.

        @param tile:
        @param distance:
        @param player: if None, will use self.general.player
        @return:
        """

        armyNear = self.sum_friendly_army_near_or_on_tiles([tile], distance, player)
        logging.info(f"friendly_army_near for tile {tile.x},{tile.y} player {player} returned {armyNear}")
        if self._map.is_tile_on_team_with(tile, player):
            # don't include the tiles army itself...
            armyNear = armyNear - (tile.army - 1)
        return armyNear

    def sum_friendly_army_near_or_on_tiles(self, tiles: typing.List[Tile], distance: int = 2, player: int | None = None) -> int:
        """
        DOES include the army value ON the tile itself.

        @param tiles:
        @param distance:
        @param player: if None, will use self.general.player
        @return:
        """
        if player is None:
            player = self._map.player_index
        armyNear = SearchUtils.Counter(0)
        counterLambda = lambda tile: armyNear.add(tile.army - 1)
        negativeLambda = lambda tile: not self._map.is_tile_on_team_with(tile, player)
        SearchUtils.breadth_first_foreach(self._map, tiles, distance, counterLambda, negativeLambda)
        value = armyNear.value
        return value

    def get_first_path_move(self, path):
        return Move(path.start.tile, path.start.next.tile, path.start.move_half)

    def get_afk_players(self) -> typing.List[Player]:
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

    def get_optimal_exploration(
            self,
            turns,
            negativeTiles: typing.Set[Tile] = None,
            valueFunc=None,
            priorityFunc=None,
            initFunc=None,
            skipFunc=None,
            minArmy=0
    ) -> Path | None:
        # allow exploration again

        negMinArmy = 0 - minArmy

        logging.info(f"\n\nAttempting Optimal EXPLORATION (tm) for turns {turns}:\n")
        startTime = time.perf_counter()
        generalPlayer = self._map.players[self.general.player]
        searchingPlayer = self.general.player
        if negativeTiles is None:
            negativeTiles = set()
        else:
            negativeTiles = negativeTiles.copy()
        for tile in negativeTiles:
            logging.info(f"negativeTile: {str(tile)}")

        distSource = [self.general]
        if self.target_player_gather_path is not None:
            distSource = [self.targetPlayerExpectedGeneralLocation]
        distMap = SearchUtils.build_distance_map(self._map, distSource)

        ourArmies = SearchUtils.where(self.armyTracker.armies.values(), lambda army: army.player == self.general.player and army.tile.player == self.general.player and army.tile.army > 1)
        ourArmyTiles = [army.tile for army in ourArmies]
        if len(ourArmyTiles) == 0:
            logging.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 5 instead.")
            ourArmyTiles = SearchUtils.where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 5)
        if len(ourArmyTiles) == 0:
            logging.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 2 instead.")
            ourArmyTiles = SearchUtils.where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 2)
        if len(ourArmyTiles) == 0:
            logging.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 1 instead.")
            ourArmyTiles = SearchUtils.where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 1)

        ourArmyTiles = SearchUtils.where(ourArmyTiles, lambda t: t.army > negMinArmy)

        # require any exploration path go through at least one of these tiles.
        def validExplorationTileEvaluater(tile):
            # tile not visible, and enemy territory or near expected general location or bordered by their tile
            if not tile.discovered and (self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer
                                            or distMap[tile.x][tile.y] < 6):
                return True
            return False

        validExplorationTiles = new_tile_grid(self._map, validExplorationTileEvaluater)

        #skipFunc(next, nextVal). Not sure why this is 0 instead of 1, but 1 breaks it. I guess the 1 is already subtracted
        if not skipFunc:
            def skip_after_out_of_army(nextTile, nextVal):
                wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = nextVal
                if negArmyRemaining >= negMinArmy:
                    return True
                if distSoFar > 5 and negValidExplorationCount == 0:
                    return True
                if wastedMoves > 5:
                    return True
                return False
            skipFunc = skip_after_out_of_army

        if not valueFunc:
            def value_priority_army_dist(currentTile, priorityObject):
                wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = priorityObject
                # negative these back to positive
                if negValidExplorationCount == 0:
                    return None
                if negArmyRemaining > 0:
                    return None

                posPathPrio = 0-pathPriorityDivided

                # pathPriority includes emergence values.
                value = 0 - (negRevealedCount + enemyTiles * 6 + neutralTiles) / distSoFar

                return value, posPathPrio, distSoFar

            valueFunc = value_priority_army_dist

        if not priorityFunc:
            def default_priority_func(nextTile, currentPriorityObject):
                wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = currentPriorityObject
                armyRemaining = 0 - negArmyRemaining
                nextTileSet = tileSetSoFar.copy()
                distSoFar += 1
                # weight tiles closer to the target player higher
                addedPriority = -4 - max(2.0, distMap[nextTile.x][nextTile.y] / 3)
                #addedPriority = -7 - max(3, distMap[nextTile.x][nextTile.y] / 4)
                if nextTile not in nextTileSet:
                    armyRemaining -= 1
                    releventAdjacents = SearchUtils.where(nextTile.adjacents, lambda adjTile: adjTile not in revealedSoFar and adjTile not in tileSetSoFar)
                    revealedCount = SearchUtils.count(releventAdjacents, lambda adjTile: not adjTile.discovered)
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
                        #numEnemyNear = SearchUtils.count(nextTile.adjacents, lambda adjTile: adjTile.player == self.targetPlayer)
                        #numEnemyLocked = SearchUtils.count(releventAdjacents, lambda adjTile: adjTile.player == self.targetPlayer)
                        ##    for every other nearby enemy tile on the path that we've already included in the path, add some priority
                        #addedPriority += (numEnemyNear - numEnemyLocked) * 12
                    elif nextTile.player == -1:
                        # we'd prefer to be killing enemy tiles, yeah?
                        wastedMoves += 0.2
                        neutralTiles -= 1
                        # points for capping tiles in general
                        addedPriority += 1
                        # points for taking neutrals next to enemy tiles
                        numEnemyNear = SearchUtils.count(nextTile.movable, lambda adjTile: adjTile not in revealedSoFar and adjTile.player == self.targetPlayer)
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
                    #addedPriority += SearchUtils.count(releventAdjacents, lambda adjTile: not adjTile.visible)
                else:
                    wastedMoves += 1

                nextRevealedSet = revealedSoFar.copy()
                for adj in SearchUtils.where(nextTile.adjacents, lambda tile: not tile.discovered):
                    nextRevealedSet.add(adj)
                newPathPriority = pathPriority - addedPriority
                #if generalPlayer.tileCount < 46:
                #    logging.info("nextTile {}, newPathPriority / distSoFar {:.2f}, armyRemaining {}, newPathPriority {}, distSoFar {}, len(nextTileSet) {}".format(nextTile.toString(), newPathPriority / distSoFar, armyRemaining, newPathPriority, distSoFar, len(nextTileSet)))
                return wastedMoves, newPathPriority / distSoFar, 0 - armyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, newPathPriority, distSoFar, nextTileSet, nextRevealedSet
            priorityFunc = default_priority_func

        if not initFunc:
            def initial_value_func_default(t: Tile):
                startingSet = set()
                startingSet.add(t)
                startingAdjSet = set()
                for adj in t.adjacents:
                    startingAdjSet.add(adj)
                return 0, 10, 0 - t.army, 0, 0, 0, 0, 0, 0, startingSet, startingAdjSet
            initFunc = initial_value_func_default

        if turns <= 0:
            logging.info("turns <= 0 in optimal_exploration? Setting to 50")
            turns = 50
        remainingTurns = turns
        sortedTiles = sorted(ourArmyTiles, key=lambda t: t.army, reverse=True)
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
            #tilesLargerThanAverage = SearchUtils.where(generalPlayer.tiles, lambda tile: tile.army > 1)
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
            path, pathValue = SearchUtils.breadth_first_dynamic_max(
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

                    if self._map.is_tile_friendly(node.tile) and (node.tile.isCity or node.tile.isGeneral):
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
            self.viewInfo.paths = deque(SearchUtils.where(self.viewInfo.paths, lambda pathCol: pathCol.path != path))
            self.viewInfo.color_path(PathColorer(path, 55, 100, 200, alpha, alphaDec, minAlpha))
        else:
            logging.info("No EXPLORATION plan.... :( Duration {:.3f},".format(time.perf_counter() - startTime))

        return path

    def explore_target_player_undiscovered(self, negativeTiles) -> typing.Union[None, Path]:
        #if self._map.turn < 100 or self.targetPlayer == -1 or self._map.generals[self.targetPlayer] is not None:
        if negativeTiles:
            negativeTiles = negativeTiles.copy()
        if self._map.turn < 50 or self.targetPlayer == -1:
            return None

        turnInCycle = self.timings.get_turn_in_cycle(self._map.turn)
        exploringUnknown = self._map.generals[self.targetPlayer] is None

        # TODO 2v2
        genPlayer = self._map.players[self.general.player]
        behindOnCities = genPlayer.cityCount < self._map.players[self.targetPlayer].cityCount

        if not self.is_all_in():
            if self.explored_this_turn:
                logging.info("(skipping new exploration because already explored this turn)")
                return None
            if not self.finishing_exploration and behindOnCities:
                logging.info("(skipping new exploration because behind on cities and wasn't finishing exploration)")
                return None

        # if self.is_all_in():
        #     minArmy = int(genPlayer.standingArmy ** 0.75) - 15
        #     path = self.explore_target_player_undiscovered_short(minArmy, negativeTiles)
        #     if path is not None:
        #         # already logged
        #         return path

        # if not self.winning_on_army(byRatio=1.25):
        #     return None

        self.explored_this_turn = True
        turns = self.timings.cycleTurns - turnInCycle
        minArmy = int(genPlayer.standingArmy ** 0.76) - 20
        self.info(f"Forcing explore to t{turns} and minArmy to {minArmy}")
        if self.is_all_in() and not self.all_in_army_advantage and not self.all_in_city_behind:
            turns = 15
            minArmy = int(genPlayer.standingArmy ** 0.83) - 10
            self.info(f"Forcing explore to t{turns} and minArmy to {minArmy} because self.is_all_in()")
        elif turns < 6:
            logging.info(f"Forcing explore turns to minimum of 5, was {turns}")
            turns = 5
        elif turnInCycle < 6 and exploringUnknown:
            logging.info(f"Forcing explore turns to minimum of 6, was {turns}")
            turns = 6

        if self._map.turn < 100:
            return None

        # this thing isn't working right...?
        path = self.get_optimal_exploration(turns, negativeTiles, minArmy=minArmy)
        if path:
            logging.info(f"Oh no way, explore found a path lol? {str(path)}")
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
            self.viewInfo.addAdditionalInfoLine(
                f"hunting tilesRevealed {len(tilesRevealed)} ({revealedPerMove:.2f}), Score {score} ({scorePerMove:.2f}), path.length {path.length}")
            if ((revealedPerMove > 0.5 and scorePerMove > 4)
                        or (revealedPerMove > 0.8 and scorePerMove > 1)
                        or revealedPerMove > 1.5):
                if path.length > 2:
                    path = path.get_subsegment(2)

                self.finishing_exploration = True
                self.info(
                    f"NEW hunting, search turns {turns}, minArmy {minArmy}, allIn {self.allIn} finishingExp {self.finishing_exploration} ")
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

        #path = SearchUtils.breadth_first_dynamic(self._map,
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
            logging.info(f"BUILD-MST DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")

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
            gather = self.get_gather_mst(tile, None, fromMap, 0, searchingPlayer)
            if gather.tile.player == searchingPlayer:
                gather.value -= gather.tile.army
            else:
                gather.value += gather.tile.army

            results.append(gather)
        return results

    def get_gather_mst(self, tile, fromTile, fromMap, turn, searchingPlayer):
        gatherTotal = tile.army
        turnTotal = 1
        if tile.player != searchingPlayer:
            gatherTotal = 0 - tile.army
        gatherTotal -= 1
        thisNode = GatherTreeNode(tile, fromTile, turn)
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
            gather = self.get_gather_mst(move, tile, fromMap, turn + 1, searchingPlayer)
            if gather.value > 0:
                gatherTotal += gather.value
                turnTotal += gather.gatherTurns
                thisNode.children.append(gather)

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
        if self._map.is_tile_friendly(gather.tile) and (gather.tile.isCity or gather.tile.isGeneral):
            thisNodeFoundCity = True
        if not thisNodeFoundCity:
            count += 1
        return thisNodeFoundCity, count

    def get_tree_move_default(
            self,
            gathers: typing.List[GatherTreeNode],
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


        def addToNodeLookupFunc(node: GatherTreeNode):
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
                if self._map.is_tile_friendly(nextTile):
                    if nextTile.isGeneral or nextTile.isCity:
                        cityCount += 1
                else:
                    negUnfriendlyTileCount -= 1

                distFromPlayArea = self.shortest_path_to_target_player_distances[nextTile.x][nextTile.y]

                if self._map.is_tile_friendly(nextTile):
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
                node: GatherTreeNode = nodeLookup[currentTile]
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
                    # self.viewInfo.add_targeted_tile(threat.saveTile, TargetStyle.GREEN)
                    logging.info("(killthreat) dict[threat.saveTile] = (0, {})  -- threat.saveTile {},{}".format(threat.saveTile.army, threat.saveTile.x, threat.saveTile.y))
                savePathSearchModifier = 2
                if largestTile in threat.path.start.tile.movable:
                    logging.info("largestTile was adjacent to the real threat tile, so savepath needs to be 1 turn shorter for this to be safe")
                    # then we have to be prepared for this move to fail the first turn. Look for savePath - 1
                    savePathSearchModifier = 3
                # threatKillSearchAmount = armyAmount + threatModifier - largestTile.army #- 1
                # postThreatKillSearchTurns = searchTurns - savePathSearchModifier
                # logging.info("Searching post-threatKill path with threatKillSearchAmount {} for postThreatKillSearchTurns {}".format(threatKillSearchAmount, postThreatKillSearchTurns))
                # bestPath = SearchUtils.dest_breadth_first_target(self._map, dict, threatKillSearchAmount, 0.1, postThreatKillSearchTurns, negativeTilesIncludingThreat, searchingPlayer = self.general.player, ignoreGoalArmy=True)
                # if bestPath is not None and bestPath.length > 0:
                #     self.viewInfo.color_path(PathColorer(bestPath, 250, 250, 250, 200, 12, 100))
                #     if largestTile.army > 7 or threat.threatValue <= largestTile.army:
                #         logging.info("reeeeeeeeeeeeeeeee\nkilling threat tile with {},{}, we still have time for defense after with path {}:".format(largestTile.x, largestTile.y, bestPath.toString()))
                #         saveTile = largestTile
                #     else:
                #         logging.info("threatKill {},{} -> {},{} not worthwhile?".format(largestTile.x, largestTile.y, source.x, source.y))
                # else:
                #     logging.info("largestTile {} couldn't save us because no bestPath save path found post-kill".format(largestTile.toString()))

        if saveTile is not None:
            self.history.attempted_threat_kills.add(self._map.turn)
            return Move(saveTile, source)
        return None

    def should_proactively_take_cities(self):
        # never take cities proactively in FFA when we're engaging a player
        #if self.targetPlayer != -1 and self._map.remainingPlayers > 2:
        #    return False
        if self.defend_economy:
            logging.info("No proactive cities because defending economy :)")
            return False

        # TODO 2v2 revamp needed
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

    def capture_cities(
            self,
            negativeTiles: typing.Set[Tile],
            forceNeutralCapture: bool = False,
    ) -> typing.Tuple[Path | None, Move | None]:
        """
        if ForceNeutralCapture is set true, then if a neutral city is viable this WILL produce a gather/capture path to
        it even if there isn't enough army on the map to capture it this cycle etc.

        @param negativeTiles:
        @param forceNeutralCapture:
        @return:
        """
        if self.is_all_in() and not self.all_in_city_behind:
            return None, None
        logging.info(f"------------\n     CAPTURE_CITIES (force_city_take {self.force_city_take}), negativeTiles {str(negativeTiles)}\n--------------")
        genDist = min(30, self.distance_from_general(self.targetPlayerExpectedGeneralLocation))
        killSearchDist = max(4, int(genDist * 0.2))
        isNeutCity = False

        wasCityAllIn = self.all_in_city_behind

        with self.perf_timer.begin_move_event('Render City Analyzer'):
            tileScores = self.cityAnalyzer.get_sorted_neutral_scores()
            enemyTileScores = self.cityAnalyzer.get_sorted_enemy_scores()

            if self.info_render_city_priority_debug_info:
                for i, ts in enumerate(tileScores):
                    tile, cityScore = ts
                    self.viewInfo.midLeftGridText[tile.x][tile.y] = f'c{i}'
                    EklipZBot.add_city_score_to_view_info(cityScore, self.viewInfo)

                for i, ts in enumerate(enemyTileScores):
                    tile, cityScore = ts
                    self.viewInfo.midLeftGridText[tile.x][tile.y] = f'm{i}'
                    EklipZBot.add_city_score_to_view_info(cityScore, self.viewInfo)

        # detect FFA scenarios where we're ahead on army but behind on cities and have lots of tiles and
        # should just rapid-capture tons of cities.
        rapidCityPath = self.find_rapid_city_path()
        if rapidCityPath is not None:
            # already logged
            return rapidCityPath, None

        with self.perf_timer.begin_move_event('Find Enemy City Path'):
            path = self.find_enemy_city_path(set())

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

        with self.perf_timer.begin_move_event('finding neutral city path'):
            neutPath = self.find_neutral_city_path()

        mustContestEnemy = False
        if path is not None:
            enCity = path.tail.tile
            if not self.is_tile_in_enemy_territory(enCity) and enCity.discovered:
                logging.info(f'MUST CONTEST ENEMY CITY {str(enCity)}')
                mustContestEnemy = True

        ourCityCounts = self._map.players[self.general.player].cityCount
        if self.teammate_general is not None:
            ourCityCounts += self._map.players[self.teammate_general.player].cityCount

        if self._map.is_2v2 and self._map.remainingPlayers == 3 and self.targetPlayerObj.cityCount <= ourCityCounts:
            mustContestEnemy = True

        shouldAllowNeutralCapture = self.should_allow_neutral_city_capture(
                targetPlayer=targetPlayer,
                genPlayer=player,
                forceNeutralCapture=forceNeutralCapture
        )
        if not mustContestEnemy and shouldAllowNeutralCapture:
            # TODO this / 4 shit should take into account whether we have enough army to heavily contest even far away
            #  cities. Many positions should just go sit on enemy cities, always.
            if neutPath and (self.targetPlayer == -1 or path is None or neutPath.length < path.length / 4):
                logging.info(f"Targeting neutral city {str(neutPath.tail.tile)}")
                path = neutPath
                isNeutCity = True

        if path is None:
            logging.info(f"xxxxxxxxx\n  xxxxx\n    NO ENEMY CITY FOUND or Neutral city prioritized??? mustContestEnemy {mustContestEnemy} shouldAllowNeutralCapture {shouldAllowNeutralCapture}\n  xxxxx\nxxxxxxxx")

            downOnCities = not self.even_or_up_on_cities(self.targetPlayer)
            if downOnCities:
                cycleTurn = self.timings.get_turn_in_cycle(self._map.turn)
                if not self.all_in_city_behind:
                    if cycleTurn < 5:
                        self.send_teammate_communication("Going all in due to lack of cities, attacking end of cycle", self.targetPlayerExpectedGeneralLocation)
                        self.info(f'Going all in, down on cities and no city path found.')
                        self.all_in_army_advantage = True
                        self.allIn = True
                        self.all_in_city_behind = True

                        self.set_all_in_cycle_to_hit_with_current_timings(50, bufferTurnsEndOfCycle=5)
                # else:
                #     self.all_in_army_advantage_counter += 1

                if cycleTurn < 20 and not self.are_more_teams_alive_than(2):
                    revealPath, move = self.hunt_for_fog_neutral_city(negativeTiles)
                    if move is not None or revealPath is not None:
                        return revealPath, move
            return None, None

        if self.all_in_city_behind:
            self.send_teammate_communication("Ceasing all-in, hold", self.locked_launch_point)
            # not all in anymore, we found a city, play normally
            self.all_in_city_behind = False
            self.all_in_army_advantage = False
            self.allIn = False
            self.all_in_army_advantage_counter = 0

        target = path.tail.tile
        if player.standingArmy + 5 <= target.army:
            return None, None

        enemyArmyNearDist = 3
        enemyArmyNear = self.sum_enemy_army_near_tile(target, enemyArmyNearDist)

        targetArmy = enemyArmyNear

        if not isNeutCity and not self._map.is_player_on_team_with(self.territories.territoryMap[target.x][target.y], self.general.player):
            # killSearchDist = 2 * killSearchDist // 3 + 1
            targetArmy = max(2, int(self.sum_enemy_army_near_tile(target, 2) * 1.1))
        else:
            killSearchDist = 3
            if wasCityAllIn:
                targetArmy += 5

        targetArmyGather = target.army + targetArmy

        self.viewInfo.evaluatedGrid[target.x][target.y] = 140
        # gather to the 2 tiles in front of the city
        logging.info(
            f"xxxxxxxxx\n    SEARCHED AND FOUND NEAREST NEUTRAL / ENEMY CITY {target.x},{target.y} dist {path.length}. Searching {targetArmy} army searchDist {killSearchDist}\nxxxxxxxx")
        if path.length > 1 and path.tail.tile.player == -1:
            # strip the city off
            path = path.get_subsegment(path.length - 1)
        if path.length > 2:
            # strip all but 2 end tiles off
            path = path.get_subsegment(2, end=True)

        allowGather = False
        gatherDuration = 15
        # gatherDuration = 25
        if player.tileCount > 125 and target.isNeutral:
            gatherDuration = 15
        if not target.isNeutral:
            gatherDuration = 35

        winningOnArmy = self.winning_on_army()
        inGathSplit = self.timings.in_gather_split(self._map.turn) or self.timings.in_quick_expand_split(self._map.turn)
        evenOrUpOnCities = self.even_or_up_on_cities(targetPlayer.index)
        longSpawns = genDist > 22
        targetCityIsEn = target.player >= 0
        if (winningOnArmy
                or inGathSplit
                or not evenOrUpOnCities
                or longSpawns
                or targetCityIsEn):
            allowGather = True

        capturePath, move = self.plan_city_capture(
            target,
            path,
            allowGather=allowGather,
            targetKillArmy=targetArmy,
            targetGatherArmy=targetArmyGather,
            killSearchDist=killSearchDist,
            gatherMaxDuration=gatherDuration,
            negativeTiles=negativeTiles)

        if capturePath is None and move is None:
            logging.info(
                f"xxxxxxxxx\n  xxxxx\n    GATHERING TO CITY FAILED :( {target.x},{target.y} \n  xxxxx\nxxxxxxxx")
        elif target.player >= 0:
            self.send_teammate_communication("Lets hold this city", target, cooldown=10)
        else:
            self.send_teammate_communication("Planning to take a city. Ping one of our generals to force defense, or the enemy to force offense.", target, cooldown=15)

        return capturePath, move

    def mark_tile(self, tile, alpha = 100):
        self.viewInfo.evaluatedGrid[tile.x][tile.y] = alpha

    def find_neutral_city_path(self) -> Path | None:
        """
        Prioritizes a neutral city and returns a path to it, if one is found. Will refuse to return one if it doesn't make sense to take a city right now.

        @return:
        """
        is1v1 = self._map.remainingPlayers == 2 or self._map.is_2v2
        wayAheadOnEcon = self.winning_on_economy(byRatio=1.5, cityValue=40)
        isNotLateGame = self._map.turn < 500

        if is1v1 and wayAheadOnEcon and isNotLateGame:
            return None

        targetCity: Tile | None = None
        maxScore: CityScoreData | None = None
        for city in self.cityAnalyzer.city_scores.keys():
            score = self.cityAnalyzer.city_scores[city]
            enemyVision = [tile for tile in filter(lambda t: self._map.is_tile_enemy(t), city.adjacents)]
            cityDistanceRatioThresh = 0.93
            if len(enemyVision) > 0:
                if self.player.cityCount < 4:
                    cityDistanceRatioThresh = 0.25  # 0.75 is too high to allow taking while enemy has vision.
                else:
                    cityDistanceRatioThresh = 0.55
            if (
                    (maxScore is None or maxScore.get_weighted_neutral_value() < score.get_weighted_neutral_value())
                    and score.general_distances_ratio < cityDistanceRatioThresh
            ):
                maxScore = score
                targetCity = city

        path: Path | None = None
        if targetCity is not None:
            logging.info(
                f"Found a neutral city path, closest to me and furthest from enemy. Chose city {targetCity.toString()} with rating {maxScore.get_weighted_neutral_value()}")

            path = self.get_path_to_targets(
                [t for t in targetCity.movable if not t.isNotPathable],
                skipNeutralCities=False,
                preferNeutral=False,
                preferEnemy=False)
            if path is not None:
                path.add_next(targetCity)
            logging.info(f"    path {str(path)}")
        else:
            logging.info(f"{self.get_elapsed()} No neutral city found...")

        return path

    def find_enemy_city_path(self, negativeTiles) -> Path | None:
        armyRatio = (self.player.standingArmy + 15) / (self.targetPlayerObj.standingArmy + 15)
        contestDistanceRatio = scale(armyRatio, 0.8, 3.0, 0.80, 4.0)

        logging.info(f'find enemy city path contest distance ratio {contestDistanceRatio:.3f}')
        scores = [s for s, score in self.cityAnalyzer.get_sorted_enemy_scores() if s.discovered and score.general_distances_ratio < contestDistanceRatio]
        if len(scores) == 0:
            return None

        return self.get_path_to_target(scores[0])

    def get_value_per_turn_subsegment(
            self,
            path,
            minFactor = 0.7,
            minLengthFactor = 0.1
    ) -> Path:
        pathMoveList = get_tile_list_from_path(path)
        totalCount = len(pathMoveList)
        fullValue = 0
        for tile in pathMoveList:
            if self._map.is_player_on_team_with(tile.player, self.general.player):
                fullValue += tile.army - 1

        if fullValue == 0:
            return path

        i = 1
        curSum = 0
        maxValuePerTurn = 0

        lastValueTile = None
        reversedPath = list(reversed(pathMoveList))
        logging.info(f"get_value_per_turn_subsegment: len(pathMoveList) == {len(pathMoveList)}")
        logging.info(f"get_value_per_turn_subsegment input path: {str(path)}")
        for tile in reversedPath:
            if self._map.is_tile_friendly(tile):
                curSum += tile.army - 1
                valuePerTurn = curSum / i
                logging.info(f"  [{i}]  {tile.x},{tile.y}  value per turn was {'%.1f' % valuePerTurn}")
                if valuePerTurn >= maxValuePerTurn and i <= totalCount and i > totalCount * minLengthFactor:
                    logging.info(
                        f" ![{i}]  {tile.x},{tile.y}  new max!    {'%.1f' % valuePerTurn} > {'%.1f' % maxValuePerTurn}")
                    maxValuePerTurn = valuePerTurn
                    lastValueTile = tile
            i += 1

        i = 1
        lastValueIndex = path.length
        curSum = 0
        #logging.info("len(reversedPath) {}".format(len(reversedPath)))
        for tile in reversedPath:
            if self._map.is_tile_friendly(tile):
                curSum += tile.army - 1
                valuePerTurn = curSum / i
                logging.info(f"  [{i}]  {tile.x},{tile.y}   2nd pass {'%.1f' % valuePerTurn}")
                if valuePerTurn >= maxValuePerTurn * minFactor and tile.player == self.general.player:
                    lastValueIndex = i
                    lastValueTile = tile
                    logging.info(
                        f"!![{i}]  {tile.x},{tile.y}    minFactor max   {'%.1f' % valuePerTurn} >= {'%.1f' % maxValuePerTurn}")
            i += 1
        if lastValueTile:
            logging.info(f"       -----   ---- lastValueIndex was {lastValueIndex} tile {lastValueTile.toString()}")
        else:
            logging.warning(f"No lastValueTile found??? lastValueIndex was {lastValueIndex}")

        newPath = path.get_subsegment(lastValueIndex, end=True)
        if newPath.start.tile.army == 1:
            self.info(f'VT SUBSEGMENT HAD BAD ARMY {newPath.start.tile.army} on start tile {newPath.start.tile}')
            logging.error(f'value_per_turn_subsegment turned {str(path)} into {str(newPath)}...? Start tile is 1. Returning original path...')
            # newPath = path
        if newPath.start.tile.player != self.general.player:
            self.info(f'VT SUBSEGMENT HAD BAD PLAYER {newPath.start.tile.player} on start tile {newPath.start.tile}')
            logging.error(f'value_per_turn_subsegment turned {str(path)} into {str(newPath)}...? Start tile is not even owned by us. Returning the original path...')
            # newPath = path
            # raise AssertionError('Ok clearly we fucked up')
        newPath.calculate_value(self.general.player)

        while newPath.start is not None and (newPath.start.tile.army < 2 or newPath.start.tile.player != self.general.player):
            self.viewInfo.addAdditionalInfoLine(f'Popping bad move {str(newPath.start.tile)} off of value-per-turn-subsegment-path')
            newPath.made_move()
            if newPath.length == 0:
                break

        if newPath.length == 0:
            newPath = path.clone()
            self.viewInfo.addAdditionalInfoLine(f'VT subsegment repair ALSO bad.')

            while newPath.start is not None and (newPath.start.tile.army < 2 or newPath.start.tile.player != self.general.player):
                self.viewInfo.addAdditionalInfoLine(f'Popping bad move {str(newPath.start.tile)} off of value-per-turn-subsegment-path')
                newPath.made_move()

        return newPath

    def calculate_general_danger(self):
        depth = (self.distance_from_general(self.targetPlayerExpectedGeneralLocation) * 3) // 4
        if depth < 9:
            depth = 9
        if self.is_2v2_teammate_still_alive():
            depth += 5

        self.oldThreat = self.dangerAnalyzer.fastestThreat
        self.oldAllyThreat = self.dangerAnalyzer.fastestAllyThreat

        self.dangerAnalyzer.analyze(self.general, depth, self.armyTracker.armies)

        if self.should_abandon_king_defense():
            self.viewInfo.addAdditionalInfoLine(f'skipping defense because losing on econ')
            return

        if self.dangerAnalyzer.fastestThreat:
            self.viewInfo.addAdditionalInfoLine(f'Threat: {self.dangerAnalyzer.fastestThreat.path.toString()}')
            if self.dangerAnalyzer.fastestThreat.saveTile is not None:
                self.viewInfo.add_targeted_tile(self.dangerAnalyzer.fastestThreat.saveTile, TargetStyle.GOLD)

            # self.alert_teammate_threat_if_necessary(oldThreat, self.dangerAnalyzer.fastestThreat)
        # if self.dangerAnalyzer.highestThreat:
        #     self.viewInfo.addAdditionalInfoLine(f'highest threat found: {self.dangerAnalyzer.highestThreat.path.toString()}')
        if self.dangerAnalyzer.fastestVisionThreat:
            self.viewInfo.addAdditionalInfoLine(f'VThreat: {str(self.dangerAnalyzer.fastestVisionThreat.path)}')
            # if self.dangerAnalyzer.fastestVisionThreat.saveTile is not None:
            #     self.viewInfo.add_targeted_tile(self.dangerAnalyzer.fastestVisionThreat.saveTile, TargetStyle.GREEN)
        if self.dangerAnalyzer.fastestAllyThreat:
            self.viewInfo.addAdditionalInfoLine(f'AThreat: {str(self.dangerAnalyzer.fastestAllyThreat.path)}')
            # if self.dangerAnalyzer.fastestVisionThreat.saveTile is not None:
            #     self.viewInfo.add_targeted_tile(self.dangerAnalyzer.fastestVisionThreat.saveTile, TargetStyle.GREEN)
        if self.dangerAnalyzer.fastestPotentialThreat:
            self.viewInfo.addAdditionalInfoLine(f'PotThreat: {str(self.dangerAnalyzer.fastestPotentialThreat.path)}')
            # if self.dangerAnalyzer.fastestVisionThreat.saveTile is not None:
            #     self.viewInfo.add_targeted_tile(self.dangerAnalyzer.fastestVisionThreat.saveTile, TargetStyle.GREEN)

    def check_should_be_all_in(self) -> bool:
        general = self._map.generals[self._map.player_index]
        if general is None:
            return False

        generalPlayer = self._map.players[self.general.player]

        self.allIn = False

        if self.targetPlayer == -1:
            return False

        tileCount = self._map.players[self.general.player].tileCount
        score = self._map.players[self.general.player].score
        standingArmy = self._map.players[self.general.player].standingArmy
        cities = self._map.players[self.general.player].cityCount

        oppTileCount = self._map.players[self.targetPlayer].tileCount
        oppScore = self._map.players[self.targetPlayer].score
        oppStandingArmy = self._map.players[self.targetPlayer].standingArmy
        oppCities = self._map.players[self.targetPlayer].cityCount

        if self._map.remainingPlayers > 2 and self._map.teams is not None:
            ally = self.teammate
            enAlly = [p.index for p in self._map.players if self._map.teams[p.index] == self._map.teams[self.targetPlayer] and p.index != self.targetPlayer][0]

            tileCount += self._map.players[ally].tileCount
            score += self._map.players[ally].score
            standingArmy += self._map.players[ally].standingArmy
            cities += self._map.players[ally].cityCount

            oppTileCount += self._map.players[enAlly].tileCount
            oppScore += self._map.players[enAlly].score
            oppStandingArmy += self._map.players[enAlly].standingArmy
            oppCities += self._map.players[enAlly].cityCount

        #give up if we're massively losing
        if self._map.remainingPlayers == 2 or self._map.is_2v2:
            should2v2PartnerDeadAllIn = (self._map.is_2v2 and self.teammate_general is None and self._map.remainingPlayers > 2)
            if should2v2PartnerDeadAllIn:
                self.allIn = True

            if self._map.turn > 250 and oppTileCount + 20 * (oppCities - 1) > tileCount * 1.3 + 5 + 20 * (cities + 2) and oppStandingArmy > standingArmy * 1.25 + 5:
                self.allIn = True
                self.all_in_counter = 200
            elif self._map.turn > 150 and oppTileCount + 15 * oppCities > tileCount * 1.4 + 5 + 15 * (cities + 2) and oppStandingArmy > standingArmy * 1.25 + 5:
                # self.allIn = True
                self.all_in_counter += 3
            elif should2v2PartnerDeadAllIn or (not self.all_in_army_advantage and self._map.turn > 50 and oppTileCount + 35 * oppCities > 5 + tileCount * 1.1 + (35 * cities)):
                self.all_in_counter += 1
            else:
                self.all_in_counter = 0
            if self.all_in_counter > tileCount:
                self.allIn = True
            if oppTileCount + 35 * oppCities > tileCount * 1.5 + 5 + 35 * cities and oppScore > score * 1.6 + 5:
                self.giving_up_counter += 1
                logging.info(
                    f"~ ~ ~ ~ ~ ~ ~ giving_up_counter: {self.giving_up_counter}. Player {self.targetPlayer} (or team) with {oppTileCount} tiles and {oppScore} army.")
                if self.giving_up_counter > tileCount + 20 and not self.finishing_exploration:
                    logging.info(
                        f"~ ~ ~ ~ ~ ~ ~ giving up due to player {self.targetPlayer} (or team) with {oppTileCount} tiles and {oppScore} army.")
                    time.sleep(2)
                    self._map.result = False
                    self._map.complete = True
            else:
                self.giving_up_counter = 0

        self._minAllowableArmy = 1
        return self.allIn

    def is_move_safe_valid(self, move, allowNonKill = True):
        if move is None:
            return False
        if move.source == self.general:
            return self.general_move_safe(move.dest)
        if move.source.player != move.dest.player and move.source.army - 2 < move.dest.army and not allowNonKill:
            logging.info(
                f"{move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} was not a move that killed the dest tile")
            return False
        return True

    def general_move_safe(self, target, move_half=False):
        dangerTiles = self.get_general_move_blocking_tiles(target, move_half)
        return len(dangerTiles) == 0

    def get_general_move_blocking_tiles(self, target, move_half=False):
        blockingTiles = []

        dangerTiles = self.get_danger_tiles(move_half)

        for dangerTile in dangerTiles:
            dangerTileIsTarget = target.x == dangerTile.x and target.y == dangerTile.y
            dangerTileIsNextTarget = target.x == (dangerTile.x + self.general.x) >> 2 and (dangerTile.y + self.general.y) >> 2
            if not (dangerTileIsTarget or dangerTileIsNextTarget):
                blockingTiles.append(dangerTile)
                logging.info(
                    f"BLOCK Enemy tile {dangerTile.x},{dangerTile.y} is preventing king moves. NOT dangerTileIsTarget {dangerTileIsTarget} or dangerTileIsNextTarget {dangerTileIsNextTarget}")
            else:
                logging.info(
                    f"ALLOW Enemy tile {dangerTile.x},{dangerTile.y} allowed due to dangerTileIsTarget {dangerTileIsTarget} or dangerTileIsNextTarget {dangerTileIsNextTarget}.")
        return blockingTiles

    def should_defend_economy(self):
        if self._map.remainingPlayers > 2:
            return False
        if self.targetPlayer == -1:
            return False

        if self.targetPlayerObj.last_seen_move_turn < self._map.turn - 100:
            self.viewInfo.addAdditionalInfoLine(f'ignoring econ defense against afk player')
            return False

        if self.defending_economy_spent_turns > 150:
            self.viewInfo.addAdditionalInfoLine(f'ignoring econ defense because already spent {self.defending_economy_spent_turns} on econ defense.')
            return False

        self.defend_economy = False

        largeEnemyTiles = self.find_large_tiles_near(
            [t for t in self.board_analysis.intergeneral_analysis.shortestPathWay.tiles],
            distance=4,
            forPlayer=self.targetPlayer,
            limit=1,
            minArmy=30,
            allowGeneral=False
        )

        largeFriendlyTiles = self.find_large_tiles_near(
            [t for t in self.board_analysis.intergeneral_analysis.shortestPathWay.tiles],
            distance=5,
            forPlayer=self.general.player,
            limit=1,
            minArmy=1,
            allowGeneral=False
        )

        largeFriendlyArmy = 0
        if len(largeFriendlyTiles) > 0:
            largeFriendlyArmy = largeFriendlyTiles[0].army

        self.is_blocking_neutral_city_captures = False

        genPlayer = self._map.players[self.general.player]

        if len(largeEnemyTiles) > 0:
            largeEnTile = largeEnemyTiles[0]
            me = self._map.players[self.general.player]
            dist = self.distance_from_general(largeEnTile)
            thresh = 2 * me.standingArmy // 3 + dist
            if largeEnTile.army > largeFriendlyArmy and largeEnTile.army > thresh and dist < 2 * self.board_analysis.inter_general_distance // 3 and not largeEnTile.isGeneral:
                self.defend_economy = True
                self.viewInfo.addAdditionalInfoLine(f'marking defending economy due to large enemy tile {str(largeEnTile)} (thresh {thresh})')
                self.force_city_take = False
                if largeEnTile.army > largeFriendlyArmy + 35 and largeEnTile.army > me.standingArmy // 2 - 35:
                    self.is_blocking_neutral_city_captures = True

            if self.curPath and self.curPath.tail.tile.isCity and self.curPath.tail.tile.isNeutral and self.is_blocking_neutral_city_captures:
                targetNeutCity = self.curPath.tail.tile
                if self.is_blocking_neutral_city_captures:
                    self.info(
                        f'forcibly stopped taking neutral city {str(targetNeutCity)} due to unsafe tile {str(largeEnTile)}')
                    self.curPath = None
                    self.force_city_take = False

            if self.defend_economy:
                return True

        if self.timings.get_turn_in_cycle(self._map.turn) < self.timings.launchTiming:
            if (
                self.army_out_of_play
                and not self.winning_on_army(byRatio=1.7)
                and self.winning_on_economy(byRatio=1.1)
                and genPlayer.tileCount < 120
                and not self.flanking
            ):
                self.defend_economy = True

                if not self.currently_forcing_out_of_play_gathers:
                    self.currently_forcing_out_of_play_gathers = True
                    self.timings = self.get_timings()

                return True
            else:
                self.currently_forcing_out_of_play_gathers = False

        winningText = "first 100 still"
        if self._map.turn >= 100:
            econRatio = 1.16
            armyRatio = 1.42
            # 1.45 might be too much?
            enemyCatchUpOffset = -15
            # -5 offset leads to defending economy on exactly equal tiles 1 city up.
            # Maybe -15 will be too greedy? Try -10 if it gets itself killed too much.

            winningEcon = self.winning_on_economy(econRatio, cityValue=20, againstPlayer=self.targetPlayer, offset=enemyCatchUpOffset)
            winningArmy = self.winning_on_army(armyRatio)
            pathLen = 20
            if self.shortest_path_to_target_player is not None:
                pathLen = self.shortest_path_to_target_player.length

            playerArmyNearGeneral = self.sum_friendly_army_near_or_on_tiles(self.shortest_path_to_target_player.tileList, distance=pathLen // 4 + 1)
            armyThresh = int(self.targetPlayerObj.standingArmy ** 0.93)
            hasEnoughArmyNearGeneral = playerArmyNearGeneral > armyThresh

            self.defend_economy = winningEcon and (not winningArmy or not hasEnoughArmyNearGeneral)
            if self.defend_economy:
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

        return self.defend_economy

    def get_danger_tiles(self, move_half=False) -> typing.Set[Tile]:
        dangerPath = SearchUtils.dest_breadth_first_target(self._map, self.general.movable, targetArmy=3, maxTime=0.1, maxDepth=4, searchingPlayer=self.targetPlayer, ignoreGoalArmy=False)

        if dangerPath is not None:
            return set(SearchUtils.where(dangerPath.tileList, lambda t: self._map.is_tile_enemy(t)))

        return set()

    def even_or_up_on_cities(self, againstPlayer: int = -2, cityCountOffset: int = 0) -> bool:
        """

        @param againstPlayer:
        @param cityCountOffset: applied to OUR city count. So -1 translates this method to 'even-or-up-on-cities' while +1 translates to 'up by 2 cities'
        @return:
        """
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer

        targetCities = 0
        meCities = 0

        for player in self._map.players:
            if self._map.is_player_on_team_with(player.index, self.general.player):
                meCities += player.cityCount
            elif self._map.is_player_on_team_with(player.index, againstPlayer):
                targetCities += player.cityCount

        return meCities + cityCountOffset >= targetCities

    def up_on_cities(self, againstPlayer: int = -2, cityCountOffset: int = 0) -> bool:
        """

        @param againstPlayer:
        @param cityCountOffset: applied to OUR city count. So -1 translates this method to 'even-or-up-on-cities' while +1 translates to 'up by 2 cities'
        @return:
        """
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer

        targetCities = 0
        meCities = 0

        for player in self._map.players:
            if self._map.is_player_on_team_with(player.index, self.general.player):
                meCities += player.cityCount
            elif self._map.is_player_on_team_with(player.index, againstPlayer):
                targetCities += player.cityCount

        return meCities + cityCountOffset > targetCities

    def winning_on_economy(self, byRatio: float = 1.0, cityValue: int = 30, againstPlayer: int = -2, offset: int = 0):
        """

        @param byRatio:
        @param cityValue:
        @param againstPlayer:
        @param offset: Positive means more likely to return true, negative is less.
        @return:
        """
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer
        if againstPlayer == -1:
            return True

        tileCount = self._map.players[self.general.player].tileCount
        score = self._map.players[self.general.player].score
        standingArmy = self._map.players[self.general.player].standingArmy
        cities = self._map.players[self.general.player].cityCount

        oppTileCount = self._map.players[againstPlayer].tileCount
        oppScore = self._map.players[againstPlayer].score
        oppStandingArmy = self._map.players[againstPlayer].standingArmy
        oppCities = self._map.players[againstPlayer].cityCount

        if self._map.remainingPlayers > 2 and self._map.teams is not None:
            ally = self.teammate
            enAlly = [p.index for p in self._map.players if self._map.teams[p.index] == self._map.teams[
                againstPlayer] and p.index != againstPlayer][0]

            tileCount += self._map.players[ally].tileCount
            score += self._map.players[ally].score
            standingArmy += self._map.players[ally].standingArmy
            cities += self._map.players[ally].cityCount

            oppTileCount += self._map.players[enAlly].tileCount
            oppScore += self._map.players[enAlly].score
            oppStandingArmy += self._map.players[enAlly].standingArmy
            oppCities += self._map.players[enAlly].cityCount

        playerEconValue = (tileCount + cities * cityValue) + offset
        oppEconValue = (oppTileCount + oppCities * cityValue) * byRatio
        return playerEconValue >= oppEconValue

    def winning_on_army(self, byRatio: float = 1.0, useFullArmy: bool = False, againstPlayer: int = -2):
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer
        if againstPlayer == -1:
            return True

        tileCount = self._map.players[self.general.player].tileCount
        score = self._map.players[self.general.player].score
        standingArmy = self._map.players[self.general.player].standingArmy
        cities = self._map.players[self.general.player].cityCount

        oppTileCount = self._map.players[againstPlayer].tileCount
        oppScore = self._map.players[againstPlayer].score
        oppStandingArmy = self._map.players[againstPlayer].standingArmy
        oppCities = self._map.players[againstPlayer].cityCount

        if self._map.remainingPlayers > 2 and self._map.teams is not None:
            ally = self.teammate
            enAlly = [p.index for p in self._map.players if self._map.teams[p.index] == self._map.teams[
                againstPlayer] and p.index != againstPlayer][0]

            tileCount += self._map.players[ally].tileCount
            score += self._map.players[ally].score
            standingArmy += self._map.players[ally].standingArmy
            cities += self._map.players[ally].cityCount

            oppTileCount += self._map.players[enAlly].tileCount
            oppScore += self._map.players[enAlly].score
            oppStandingArmy += self._map.players[enAlly].standingArmy
            oppCities += self._map.players[enAlly].cityCount

        targetArmy = oppStandingArmy
        playerArmy = standingArmy

        if useFullArmy:
            targetArmy = oppScore
            playerArmy = score

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
            self.viewInfo.addAdditionalInfoLine(
                f"NOT WORTH ATTACKING TARGET BECAUSE {wPStanding}     <  {oppStanding}        and   {wPIncome} >   {wOppIncome}")
            return False

        #factor in some time for exploring after the attack, + 1 * 1.1
        if self.target_player_gather_path is None:
            logging.info("ELIM due to no path")
            return False
        value = self.get_player_army_amount_on_path(self.target_player_gather_path, self._map.player_index, 0, self.target_player_gather_path.length)
        logging.info(
            f"Player army amount on path: {value}   TARGET PLAYER PATH IS REVERSED ? {self.target_player_gather_path.toString()}")
        subsegment = self.get_value_per_turn_subsegment(self.target_player_gather_path)
        logging.info(f"value per turn subsegment = {subsegment.toString()}")
        subsegmentTargets = get_tile_set_from_path(subsegment)

        lengthRatio = len(self.target_player_gather_targets) / max(1, len(subsegmentTargets))

        sqrtVal = 0
        if value > 0:
            sqrtVal = value ** 0.5
            logging.info(f"value ** 0.5 -> sqrtVal {sqrtVal}")
        if player.tileCount < 60:
            sqrtVal = value / 2.0
            logging.info(f"value / 2.3  -> sqrtVal {sqrtVal}")
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
            logging.info(
                f"  ~~~  ---  ~~~  lastTimingFactor {'%.3f' % self.lastTimingFactor} <<<< timingFactor {'%.3f' % timingFactor}")
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
        logging.info(
            f"OoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoO\n   {self._map.turn}  oOo  timingFactor {'%.3f' % timingFactor},  factorTurns {factorTurns},  turnOffset {turnOffset},  factorScale {factorScale},  sqrtVal {'%.1f' % sqrtVal},  dist {dist}")

        playerEffectiveStandingArmy = player.standingArmy - 9 * (player.cityCount - 1)
        if self.target_player_gather_path.length < 2:
            logging.info(
                f"ELIM due to path length {self.distance_from_general(self.targetPlayerExpectedGeneralLocation)}")
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
            logging.info(
                f"    --   playerEffectiveStandingArmy: {playerEffectiveStandingArmy},  NEEDEDVAL: {'%.1f' % neededVal},            VALUE: {value}")
            logging.info(
                f"    --                                     rawNeeded: {'%.1f' % rawNeeded},  rawNeededScaled: {'%.1f' % rawNeededScaled},  lengthRatio: {'%.1f' % lengthRatio}, targetPlayerArmyThreshold: {'%.1f' % targetPlayerArmyThreshold}")
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
            logging.info(
                f"    --    playerEffectiveStandingArmy: {playerEffectiveStandingArmy},  NEEDEDVAL: {'%.1f' % neededVal},            VALUE: {value},      expBase: {'%.2f' % expBase},   exp: {'%.2f' % exp},       expValue: {'%.2f' % expValue}")
            logging.info(
                f"    --                                      rawNeeded: {'%.1f' % rawNeeded},  rawNeededScaled: {'%.1f' % rawNeededScaled},  lengthRatio: {'%.1f' % lengthRatio}, targetPlayerArmyThreshold: {'%.1f' % targetPlayerArmyThreshold}")
            return value >= neededVal

    def get_player_army_amount_on_path(self, path, player, startIdx=0, endIdx=1000):
        value = 0
        idx = 0
        pathNode = path.start
        while pathNode is not None:
            if self._map.is_player_on_team_with(pathNode.tile.player, player) and startIdx <= idx <= endIdx:
                value += (pathNode.tile.army - 1)
            pathNode = pathNode.next
            idx += 1
        return value

    def get_target_army_inc_adjacent_enemy(self, tile):
        sumAdj = 0
        for adj in tile.adjacents:
            if self._map.is_tile_enemy(adj):
                sumAdj += adj.army - 1
        armyToSearch = sumAdj
        # if tile.army > 5 and tile.player != self._map.player_index and not tile.isNeutral:
        #     armyToSearch += tile.army / 2
        return armyToSearch

    def find_leaf_move(self, allLeaves):
        leafMoves = self.prioritize_expansion_leaves(allLeaves)
        if self.target_player_gather_path is not None:
            leafMoves = list(SearchUtils.where(leafMoves, lambda move: move.source not in self.target_player_gather_path.tileSet))
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
            # if source not in analysis.pathWayLookupMatrix or dest not in analysis.pathWayLookupMatrix:
            #     continue
            # if analysis.bMap[dest.x][dest.y] > self.board_analysis.inter_general_distance + 3:
            #     # don't leafmove moves that are overly far from the opp general..?
            #     continue
            if (
                    self.territories.territoryMap[dest.x][dest.y] != -1
                    and not self._map.is_player_on_team_with(self.territories.territoryMap[dest.x][dest.y], self.general.player)
                    and dest.player == -1
                    and self._map.turn % 50 < 45
            ):
                # no neutral leafmoves into enemy territory except at cycle end...?
                continue
            # sourcePathway = analysis.pathWayLookupMatrix[source]
            # destPathway = analysis.pathWayLookupMatrix[dest]

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
            distEnemyPoints = (analysis.aMap[dest.x][dest.y] + 1) / (analysis.bMap[dest.x][dest.y] + 1)

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

        with self.perf_timer.begin_move_event('get_predicted_target_player_general_location'):
            maxTile: Tile = self.get_predicted_target_player_general_location()

        if maxTile is None:
            return None

        # self.viewInfo.addAdditionalInfoLine(f'maxTile {str(maxTile)}')

        if self.targetPlayerExpectedGeneralLocation != maxTile and self._map.turn > 50:
            self.send_teammate_communication(f"I will be targeting {self._map.usernames[self.targetPlayer]} over here.", maxTile, cooldown=50, detectOnMessageAlone=True)

        self.targetPlayerExpectedGeneralLocation = maxTile

        with self.perf_timer.begin_move_event('rebuilding intergeneral_analysis'):
            self.board_analysis.rebuild_intergeneral_analysis(self.targetPlayerExpectedGeneralLocation)
            if len(self.board_analysis.intergeneral_analysis.shortestPathWay.tiles) > 0:
                self.shortest_path_to_target_player_distances = SearchUtils.build_distance_map(
                    self._map,
                    [tile for tile in self.board_analysis.intergeneral_analysis.shortestPathWay.tiles],
                    skipTiles=[])

        enemyDistMap = None
        if self.board_analysis is not None and self.board_analysis.intergeneral_analysis is not None and self.board_analysis.intergeneral_analysis.bMap is not None:
            enemyDistMap = self.board_analysis.intergeneral_analysis.bMap
        else:
            enemyDistMap = SearchUtils.build_distance_map(self._map, [self.targetPlayerExpectedGeneralLocation])

        fromTile = self.general
        if self._map.is_2v2 and self.teammate_general is not None:
            fromTile = self.get_2v2_launch_point()
            self.locked_launch_point = fromTile

        if self.locked_launch_point is not None:
            fromTile = self.locked_launch_point
        else:
            startTime = time.perf_counter()
            targetPlayerObj = None
            if self.targetPlayer != -1:
                targetPlayerObj = self._map.players[self.targetPlayer]
            if targetPlayerObj is None or not targetPlayerObj.knowsKingLocation:
                for genLaunchPoint in self.launchPoints:
                    if genLaunchPoint is None:
                        logging.info("wtf genlaunchpoint was none????")
                    elif enemyDistMap[genLaunchPoint.x][genLaunchPoint.y] < enemyDistMap[fromTile.x][fromTile.y]:
                        logging.info(f"using launchPoint {genLaunchPoint.toString()}")
                        fromTile = genLaunchPoint

            if self._map.remainingPlayers == 2 and not self.army_out_of_play:
                with self.perf_timer.begin_move_event('checking for sketchy fog flanks'):
                    sketchyFogPath = self.find_sketchy_fog_flank_from_enemy_in_play_area()
                if sketchyFogPath is not None:
                    self.viewInfo.addAdditionalInfoLine(f'Using sketchy flank launch {str(sketchyFogPath)}')
                    fromTile = sketchyFogPath.start.tile
                    self.flanking = True

            self.locked_launch_point = fromTile

        preferNeut = self._map.remainingPlayers < 3
        preferNeut = not isAllIn
        path = self.get_path_to_target(maxTile, skipEnemyCities = isAllIn, preferNeutral = preferNeut, fromTile = fromTile, preferEnemy = not isAllIn)
        if cutLength is not None and path.length > cutLength:
            path = path.get_subsegment(cutLength, end = True)

        if self.targetPlayer == -1 and self._map.remainingPlayers > 2 and not self._map.is_2v2:
            # To avoid launching out into the middle of the FFA, just return the general tile and the next tile in the path as the path.
            # this sort of triggers camping-city-taking behavior at the moment.
            fakeGenPath = path.get_subsegment(1)
            logging.info(f"FakeGenPath because FFA: {fakeGenPath.toString()}")
            return fakeGenPath
        return path

    def get_best_defense(self, defendingTile: Tile, turns: int, negativeTileList: typing.List[Tile]) -> Path | None:
        searchingPlayer = defendingTile.player
        logging.info("Trying to get_best_defense. Turns {}. Searching player {}".format(turns, searchingPlayer))
        negativeTiles = set()

        for negTile in negativeTileList:
            negativeTiles.add(negTile)

        startTiles = [defendingTile]

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

        def default_base_case_func(t, startingDist):
            return 0, 0, t.x, t.y
        baseCaseFunc = default_base_case_func

        startTilesDict = {}
        for tile in startTiles:
            # then use baseCaseFunc to initialize their priorities, and set initial distance to 0
            startTilesDict[tile] = (baseCaseFunc(tile, 0), 0)
            #negativeTiles.add(tile)

        for tile in startTilesDict.keys():
            (startPriorityObject, distance) = startTilesDict[tile]
            logging.info("   Including tile {},{} in startTiles at distance {}".format(tile.x, tile.y, distance))

        valuePerTurnPath = SearchUtils.breadth_first_dynamic_max(
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
            logging.info(f"Best defense: {valuePerTurnPath.toString()}")
            savePath = valuePerTurnPath.get_reversed()
            negs = set(negativeTileList)
            negs.add(defendingTile)
            savePath.calculate_value(forPlayer=defendingTile.player, negativeTiles=negs)
            self.viewInfo.color_path(PathColorer(savePath, 255, 255, 255, 255, 10, 150))
            return savePath

        logging.info("Best defense: NONE")
        return None

    def info(self, text):
        self.viewInfo.infoText = text
        self.viewInfo.addAdditionalInfoLine(text)

    def get_path_to_target(
            self,
            target,
            maxTime=0.1,
            maxDepth=85,
            skipNeutralCities=True,
            skipEnemyCities=False,
            preferNeutral=True,
            fromTile=None,
            preferEnemy=False
    ) -> Path:
        targets = set()
        targets.add(target)
        return self.get_path_to_targets(
            targets,
            maxTime,
            maxDepth,
            skipNeutralCities,
            skipEnemyCities,
            preferNeutral,
            fromTile,
            preferEnemy=preferEnemy)

    def get_path_to_targets(
            self,
            targets,
            maxTime=0.1,
            maxDepth=85,
            skipNeutralCities=True,
            skipEnemyCities=False,
            preferNeutral=True,
            fromTile=None,
            preferEnemy=True
    ) -> Path:
        if fromTile is None:
            fromTile = self.general
        negativeTiles = None
        if skipEnemyCities:
            negativeTiles = set()
            for enemyCity in self.enemyCities:
                negativeTiles.add(enemyCity)
        skipFunc = None
        if skipEnemyCities:
            skipFunc = lambda tile, prioObject: tile.isCity and self._map.is_tile_enemy(tile)

        def path_to_targets_priority_func(
                nextTile: Tile,
                currentPriorityObject):
            (dist, negEnemyTiles, negCityCount, negArmySum, goalIncrement) = currentPriorityObject
            dist += 1

            if preferEnemy and not self.is_all_in():
                if nextTile.player == self.targetPlayer:
                    negEnemyTiles -= 1
                    if nextTile.isCity:
                        negCityCount -= 1

                if not self._map.remainingPlayers > 3:
                    if not nextTile.visible:
                        negEnemyTiles -= 1
                    if not nextTile.discovered:
                        negEnemyTiles -= 1

                negEnemyTiles -= int(self.armyTracker.emergenceLocationMap[self.targetPlayer][nextTile.x][nextTile.y] ** 0.25)

            if negativeTiles is None or nextTile not in negativeTiles:
                if self._map.is_tile_friendly(nextTile):
                    negArmySum -= nextTile.army
                else:
                    negArmySum += nextTile.army
            # always leaving 1 army behind. + because this is negative.
            negArmySum += 1
            # -= because we passed it in positive for our general and negative for enemy gen / cities
            negArmySum -= goalIncrement
            return dist, negEnemyTiles, negCityCount, negArmySum, goalIncrement

        startPriorityObject = (0, 0, 0, 0, 0.5)
        startTiles = {}
        startTiles[fromTile] = (startPriorityObject, 0)

        path = SearchUtils.breadth_first_dynamic(
            self._map,
            startTiles,
            lambda tile, prioObj: tile in targets,
            maxTime,
            maxDepth,
            skipNeutralCities,
            negativeTiles = negativeTiles,
            preferNeutral = preferNeutral,
            skipFunc = skipFunc,
            priorityFunc = path_to_targets_priority_func)

        #path = SearchUtils.breadth_first_dynamic(self._map, [fromTile], lambda tile, prioObj: tile in targets, maxTime, maxDepth, skipNeutralCities, negativeTiles = negativeTiles, preferNeutral = preferNeutral, skipFunc = skipFunc)
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


    def distance_from_teammate(self, sourceTile):
        if sourceTile == self.teammate_general:
            return 0
        val = 0

        if self._ally_distances:
            val = self._ally_distances[sourceTile.x][sourceTile.y]
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

    def scan_map_for_large_tiles_and_leaf_moves(self):
        self.general_safe_func_set[self.general] = self.general_move_safe
        self.leafMoves = []
        self.largeTilesNearEnemyKings: typing.Dict[Tile, typing.List[Tile]] = {}
        self.allUndiscovered = []
        self.largePlayerTiles = []
        player = self._map.players[self.general.player]
        largePlayerTileThreshold = player.standingArmy / player.tileCount * 5
        general = self._map.generals[self._map.player_index]
        generalApproximations = [[0, 0, 0, None] for i in range(len(self._map.generals))]
        for tile in general.adjacents:
            if self._map.is_tile_enemy(tile):
                self._map.players[tile.player].knowsKingLocation = True
                if self._map.teams is not None:
                    for teamPlayer in self._map.players:
                        if self._map.teams[teamPlayer.index] == self._map.teams[tile.player]:
                            teamPlayer.knowsKingLocation = True

        if self.teammate_general is not None:
            for tile in self.teammate_general.adjacents:
                if self._map.is_tile_enemy(tile):
                    for teamPlayer in self._map.players:
                        if self._map.teams[teamPlayer.index] == self._map.teams[tile.player]:
                            teamPlayer.knowsAllyKingLocationing = True

        for enemyGen in self._map.generals:
            if enemyGen is not None and self._map.is_tile_enemy(enemyGen):
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

                if self._map.is_tile_enemy(tile) and self._map.generals[tile.player] is None:
                    for nextTile in tile.movable:
                        if not nextTile.discovered and not nextTile.isNotPathable:
                            approx = generalApproximations[tile.player]
                            approx[0] += nextTile.x
                            approx[1] += nextTile.y
                            approx[2] += 1

                if tile.player == self._map.player_index:
                    for nextTile in tile.movable:
                        if not self._map.is_tile_friendly(nextTile) and not nextTile.isObstacle:
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
                        if tile.army > enemyGen.army and self.euclidDist(tile.x, tile.y, enemyGen.x, enemyGen.y) < 11:
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

        oldTgPlayer = self.targetPlayer
        self.targetPlayer = self.calculate_target_player()

        self.targetPlayerObj = self._map.players[self.targetPlayer]

        if self.targetPlayer != oldTgPlayer:
            self._lastTargetPlayerCityCount = self.targetPlayerObj.cityCount

    def determine_should_winning_all_in(self):
        if self.targetPlayer < 0:
            return False

        targetPlayer: Player = self._map.players[self.targetPlayer]
        thisPlayer: Player = self._map.players[self.general.player]

        if thisPlayer.standingArmy < 100:
            return False

        factoredArmyThreshold = targetPlayer.standingArmy * 2 + 20

        # if already all in, keep pushing for longer
        if self.all_in_army_advantage:
            factoredArmyThreshold = targetPlayer.standingArmy * 1.4 + 10

        if thisPlayer.standingArmy > factoredArmyThreshold:
            self.viewInfo.addAdditionalInfoLine(f"TEMP ALL IN ON ARMY ADV {thisPlayer.standingArmy} vs {targetPlayer.standingArmy} thr({factoredArmyThreshold})")
            return True

        return False

    def find_expected_1v1_general_location_on_undiscovered_map(
            self,
            undiscoveredCounterDepth: int,
            minSpawnDistance: int
    ) -> typing.List[typing.List[int]]:
        """bigger number in the matrix is better"""
        # finding path to some predicted general location in neutral territory
        # TODO look into the void and see it staring back at yourself
        # find mirror spot in the void? Or just discover the most tiles possible.
        # Kind of done. Except really, shouldn't be BFSing with so much CPU for this lol.
        localMaxTile = self.general
        maxAmount: int = 0
        grid = [[0 for y in range(self._map.rows)] for x in range(self._map.cols)]

        def tile_meets_criteria_for_value_around_general(t: Tile) -> bool:
            return ((not t.discovered)
                and not (t.isNotPathable or t.isMountain))

        def tile_meets_criteria_for_general(t: Tile) -> bool:
            return tile_meets_criteria_for_value_around_general(t) and self.distance_from_general(t) >= minSpawnDistance and (self.teammate_general is None or self.distance_from_teammate(t) >= minSpawnDistance)

        for tile in self.pathableTiles:
            if tile_meets_criteria_for_general(tile):
                # if not divide by 2, overly weights far tiles. Prefer mid-far central tiles
                genDist = self.distance_from_general(tile) / 2
                distFromCenter = self.get_distance_from_board_center(tile, center_ratio=0.25)

                counter = SearchUtils.Counter(genDist - distFromCenter)
                if self.info_render_general_undiscovered_prediction_values:
                    self.viewInfo.bottomLeftGridText[tile.x][tile.y] = genDist - distFromCenter

                # the lambda for counting stuff!
                def count_undiscovered(curTile):
                    if tile_meets_criteria_for_value_around_general(curTile):
                        counter.add(1)

                SearchUtils.breadth_first_foreach(self._map, [tile], undiscoveredCounterDepth, count_undiscovered, noLog=True)

                grid[tile.x][tile.y] = counter.value

                if counter.value > maxAmount:
                    localMaxTile = tile
                    maxAmount = counter.value

        if self.targetPlayer == -1:
            def mark_undiscovered(curTile):
                if tile_meets_criteria_for_value_around_general(curTile):
                    self._evaluatedUndiscoveredCache.append(curTile)
                    if self.info_render_general_undiscovered_prediction_values:
                        self.viewInfo.evaluatedGrid[curTile.x][curTile.y] = 1

            SearchUtils.breadth_first_foreach(self._map, [localMaxTile], undiscoveredCounterDepth, mark_undiscovered, noLog=True)

        return grid

    def prune_timing_split_if_necessary(self):
        if self.target_player_gather_path is None:
            return

        splitTurn = self.timings.get_turn_in_cycle(self._map.turn)
        tilesUngathered = SearchUtils.count(
            self.pathableTiles,
            lambda tile: (
                    tile.player == self.general.player
                    and tile not in self.target_player_gather_path.tileSet
                    and tile.army > 1
            )
        )

        player = self._map.players[self.general.player]
        if tilesUngathered - player.cityCount - 1 < 1:
            timingAdjusted = splitTurn + tilesUngathered
            if timingAdjusted < self.timings.launchTiming:
                self.viewInfo.addAdditionalInfoLine(f"Moving up launch timing from {self.timings.launchTiming} to splitTurn {splitTurn} + tilesUngathered {tilesUngathered} = ({timingAdjusted})")
                self.timings.launchTiming = timingAdjusted
                self.timings.splitTurns = timingAdjusted

    def get_distance_from_board_center(self, tile, center_ratio = 0.25) -> float:
        """
        bigger center_ratio means more of the center of the board counts as 0.

        @param tile:
        @param center_ratio:
        @return:
        """
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
            with self.perf_timer.begin_move_event('get_max_explorable_undiscovered_tile'):
                return self.get_max_explorable_undiscovered_tile(minSpawnDist)

        if self._map.generals[self.targetPlayer] is not None:
            return self._map.generals[self.targetPlayer]

        maxTile = self.general
        values = [[0.0 for x in range(self._map.rows)] for y in range(self._map.cols)]

        def skipPlayerAndDiscoveredFunc(tile):
            if (
                    self._map.is_tile_friendly(tile)
                    or (not skipDiscoveredAsNeutralFilter and tile.discoveredAsNeutral)
                    or tile.isNotPathable
                    or tile.isMountain
            ):
                return True
            return False

        enemyCounter = SearchUtils.Counter(0)
        undiscCounter = SearchUtils.Counter(0)


        # the lambda for counting stuff! Lower weight for undiscovereds, we prefer enemy tiles.
        def undiscoveredEnemyCounter(tile):
            if tile.isNotPathable or tile.isMountain:
                return

            discoveredNonEnemy = tile.discovered and (tile.player == -1 or self._map.is_tile_friendly(tile))
            if discoveredNonEnemy:
                return

            if not tile.discovered:
                if self._map.is_player_on_team_with(self.territories.territoryMap[tile.x][tile.y], self.targetPlayer) or self._map.is_player_on_team_with(tile.player, self.targetPlayer):
                    undiscCounter.add(1)
            elif self._map.is_player_on_team_with(tile.player, self.targetPlayer):
                enemyCounter.add(1)
            if self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y] > 0:
                undiscCounter.add(0.1)

        maxOldTile = maxTile
        maxOldAmount = -1

        maxAmount = -1
        undiscoveredCounterDepth = 6

        for tile in self.pathableTiles:
            if tile.discovered or tile.isMountain or tile.isNotPathable:
                continue

            # if (self._map.remainingPlayers > 2
            #         and 0 == SearchUtils.count(tile.adjacents, lambda adjTile: adjTile.player == self.targetPlayer)
            # ):
            #     # in FFA, don't evaluate tiles other than those directly next to enemy tiles (to avoid overshooting into 3rd party territory)
            #     continue

            if self.distance_from_general(tile) < minSpawnDist or (self.teammate_general is not None and self.distance_from_teammate(tile) < minSpawnDist):
                continue

            undiscCounter.value = 0
            enemyCounter.value = 0

            SearchUtils.breadth_first_foreach(self._map, [tile], undiscoveredCounterDepth, undiscoveredEnemyCounter,
                                  noLog=True, skipFunc=skipPlayerAndDiscoveredFunc)
            foundValue = 10 * enemyCounter.value + undiscCounter.value
            if enemyCounter.value > 0 and foundValue > maxOldAmount:
                maxOldTile = tile
                maxOldAmount = foundValue

            if foundValue > 0:
                if self.info_render_general_undiscovered_prediction_values:
                    self.viewInfo.midLeftGridText[tile.x][tile.y] = f'pe{foundValue}'

            if self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y] > 0:
                # foundValue += emergenceLogFactor * math.log(self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y], 2)
                foundValue += self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y] * 10
            values[tile.x][tile.y] = foundValue
            if enemyCounter.value > 0 and foundValue > maxAmount:
                maxTile = tile
                maxAmount = foundValue
            if foundValue > 0 and self.info_render_general_undiscovered_prediction_values:
                self.viewInfo.midRightGridText[tile.x][tile.y] = f'we{foundValue}'

        self.viewInfo.add_targeted_tile(maxOldTile, TargetStyle.GOLD)
        self.viewInfo.add_targeted_tile(maxTile, TargetStyle.BLUE)

        # if (maxTile == self.general or maxTile == None) and not skipDiscoveredAsNeutralFilter:
        #     self.viewInfo.addAdditionalInfoLine("target path failed, retry without forcing discoveredAsNeutral.")
        #     tile = self.get_predicted_target_player_general_location(skipDiscoveredAsNeutralFilter=True)
        #     if tile != self.general and tile is not None and not tile.isObstacle:
        #         maxTile = tile

        if (maxTile == self.general or maxTile is None or maxTile.isObstacle) and self.targetPlayer != -1:
            self.viewInfo.addAdditionalInfoLine("target path failed, hacky gen approx attempt:")
            with self.perf_timer.begin_move_event('find_hacky_path_to_find_target_player_spawn_approx'):
                maxTile = self.find_hacky_path_to_find_target_player_spawn_approx(minSpawnDist)

        if (maxTile == self.general or maxTile is None or maxTile.isObstacle) and self.targetPlayer != -1:
            for tile in self._map.get_all_tiles():
                if tile.player == self.targetPlayer:
                    for adjTile in tile.movable:
                        if not adjTile.discovered and not adjTile.isObstacle:
                            self.viewInfo.addAdditionalInfoLine("target path failed, falling back to a random tile adjacent to enemy tile.")
                            return adjTile

        if maxTile == self.general or maxTile is None or maxTile.isObstacle:
            self.viewInfo.addAdditionalInfoLine("target path failed, falling back to undiscovered path.")
            with self.perf_timer.begin_move_event('get_max_explorable_undiscovered_tile'):
                fallbackTile = self.get_max_explorable_undiscovered_tile(minSpawnDist)

            if fallbackTile is None or fallbackTile == self.general:
                self.viewInfo.addAdditionalInfoLine("target path fallback failed, returning tile next to general.")
                return self.general.movable[0]
            return fallbackTile

        self.undiscovered_priorities = values

        logging.info(f"OLD PREDICTION = {str(maxOldTile)}")

        logging.info(f"NEW PREDICTION = {str(maxTile)} ??????")

        logging.info(
            f"Highest density undiscovered tile {str(maxTile)} with value {maxAmount} found")

        return maxTile

    def is_player_spawn_cramped(self, spawnDist = -1) -> bool:
        if self._spawn_cramped is not None:
            return self._spawn_cramped

        if spawnDist == -1:
            self.target_player_gather_targets = self.target_player_gather_path.tileSet
            spawnDist = self.shortest_path_to_target_player.length

        tiles = [self.general]

        counter = SearchUtils.Counter(0)

        # if we dont find enemy territory (which is around halfway point)
        spawnDist = spawnDist / 2.0

        def count_neutral(curTile: Tile):
            tileTerritory = self.territories.territoryMap[curTile.x][curTile.y]
            isTileContested = self._map.is_tile_enemy(curTile)
            isTileContested |= tileTerritory != self.general.player and tileTerritory >= 0 and tileTerritory not in self._map.teammates
            if not curTile.isNotPathable:
                counter.add(0.5)
            if not isTileContested:
                counter.add(0.5)

        counter.value = 0
        SearchUtils.breadth_first_foreach(self._map, tiles, 8, count_neutral, noLog=True)
        count8 = counter.value

        counter.value = 0
        SearchUtils.breadth_first_foreach(self._map, tiles, 6, count_neutral, noLog=True)
        count6 = counter.value

        counter.value = 0
        SearchUtils.breadth_first_foreach(self._map, tiles, 4, count_neutral, noLog=True)
        count4 = counter.value

        enTerritoryStr = ''
        if self.targetPlayer != -1:
            enemyTerritoryFoundCounter = SearchUtils.Counter(0)
            targetPlayer: Player = self._map.players[self.targetPlayer]
            visibleTiles = [t for t in filter(lambda tile: tile.visible, targetPlayer.tiles)]
            enemyVisibleTileCount = len(visibleTiles)

            def count_enemy_territory(curTile: Tile, object):
                tileTerritory = self.territories.territoryMap[curTile.x][curTile.y]
                isTileContested = self._map.is_tile_enemy(curTile)
                isTileContested |= tileTerritory != self.general.player and tileTerritory >= 0 and tileTerritory not in self._map.teammates
                if isTileContested:
                    enemyTerritoryFoundCounter.add(1)

                if enemyTerritoryFoundCounter.value > enemyVisibleTileCount:
                    return True

                return False

            path = SearchUtils.breadth_first_dynamic(
                self._map,
                tiles,
                count_enemy_territory,
                noNeutralCities=True,
                searchingPlayer=self.general.player)

            if path is not None:
                territoryTile = path.tileList[-1]
                self.viewInfo.add_targeted_tile(territoryTile, TargetStyle.RED)
                # self.viewInfo.addAdditionalInfoLine(f"found enemy territory at dist {path.length} {str(territoryTile)}")
                enTerritoryStr = f'enTerr d{path.length} @{str(territoryTile)}'
                spawnDist = path.length

        spawnDistFactor = spawnDist - 10

        thisPlayer = self._map.players[self.general.player]
        cap8 = 68 - 9 * (thisPlayer.cityCount - 1) + spawnDistFactor
        cap6 = 42 - 6 * (thisPlayer.cityCount - 1) + spawnDistFactor
        cap4 = 21 - 3 * (thisPlayer.cityCount - 1) + spawnDistFactor

        cramped = False
        if count8 < cap8 or count6 < cap6 or count4 < cap4:
            cramped = True

        self.viewInfo.addAdditionalInfoLine(f"Cramped: {cramped} 8[{count8}/{cap8}] 6[{count6}/{cap6}] 4[{count4}/{cap4}] spawnDistFactor[{spawnDistFactor}] {enTerritoryStr}")

        self._spawn_cramped = cramped

        return cramped

    def timing_cycle_ended(self):
        self.viewInfo.addAdditionalInfoLine(f'Timing cycle ended, turn {self._map.turn}')
        self.cities_gathered_this_cycle = set()
        self.tiles_gathered_to_this_cycle = set()
        player = self._map.players[self.general.player]
        cityCount = player.cityCount

        citiesAvoided = 0
        if player.cityCount > 4:
            for city in sorted(player.cities, key=lambda c: c.army):
                if citiesAvoided >= cityCount // 2 - 2:
                    break
                citiesAvoided += 1
                self.viewInfo.addAdditionalInfoLine(f'AVOIDING CITY {repr(city)}')
                self.cities_gathered_this_cycle.add(city)

        self.locked_launch_point = None
        self.flanking = False

    def dump_turn_data_to_string(self):
        charMap = {
            0: 'a',
            1: 'b',
            2: 'c',
            3: 'd',
            4: 'e',
            5: 'f',
            6: 'g',
            7: 'h',
            8: 'i',
            9: 'j',
            10: 'k',
            11: 'l',
            12: 'm',
            13: 'n',
            14: 'o',
            15: 'p',
        }

        data = []

        data.append(f'bot_target_player={self.targetPlayer}')
        if self.targetPlayerExpectedGeneralLocation:
            data.append(f'targetPlayerExpectedGeneralLocation={self.targetPlayerExpectedGeneralLocation.x},{self.targetPlayerExpectedGeneralLocation.y}')
        data.append(f'bot_all_in_counter={self.all_in_counter}')
        data.append(f'bot_all_in={self.allIn}')
        data.append(f'bot_all_in_army_advantage={self.all_in_army_advantage}')
        data.append(f'bot_all_in_army_advantage_counter={self.all_in_army_advantage_counter}')
        data.append(f'bot_all_in_army_advantage_cycle={self.all_in_army_advantage_cycle}')
        data.append(f'bot_is_rapid_capturing_neut_cities={self.is_rapid_capturing_neut_cities}')
        data.append(f'bot_is_blocking_neutral_city_captures={self.is_blocking_neutral_city_captures}')
        data.append(f'bot_finishing_exploration={self.finishing_exploration}')
        if self.targetingArmy:
            data.append(f'bot_targeting_army={self.targetingArmy.tile.x},{self.targetingArmy.tile.y}')
        data.append(f'bot_cur_path={str(self.curPath)}')

        for player in self._map.players:
            char = charMap[player.index]
            unsaveUserName = self._map.usernames[player.index].replace('=', '__')

            safeUserName = ''.join([i if ord(i) < 128 else ' ' for i in unsaveUserName])
            data.append(f'{char}Username={safeUserName}')
            data.append(f'{char}Tiles={player.tileCount}')
            data.append(f'{char}Score={player.score}')
            data.append(f'{char}StandingArmy={player.standingArmy}')
            data.append(f'{char}Stars={player.stars}')
            data.append(f'{char}CityCount={player.cityCount}')
            if player.general is not None:
                data.append(f'{char}General={player.general.x},{player.general.y}')
            data.append(f'{char}KnowsKingLocation={player.knowsKingLocation}')
            if self._map.is_2v2:
                data.append(f'{char}KnowsAllyKingLocation={player.knowsAllyKingLocation}')
            data.append(f'{char}Dead={player.dead}')
            data.append(f'{char}LeftGame={player.leftGame}')
            data.append(f'{char}LeftGameTurn={player.leftGameTurn}')
            data.append(f'{char}AggressionFactor={player.aggression_factor}')
            data.append(f'{char}Delta25Tiles={player.delta25tiles}')
            data.append(f'{char}Delta25Score={player.delta25score}')
            data.append(f'{char}CityGainedTurn={player.cityGainedTurn}')
            data.append(f'{char}CityLostTurn={player.cityLostTurn}')
            data.append(f'{char}LastSeenMoveTurn={player.last_seen_move_turn}')
            if self.generalApproximations[player.index][3] is not None:
                data.append(f'{char}_bot_general_approx={str(self.generalApproximations[player.index][3])}')

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
            force_turns_up_threat_path=0,
            gatherMax: bool = True,
            shouldLog: bool = False,
            addlTurns: int = 0,
            requiredContribution: int | None = None,
            additionalNegatives: typing.Set[Tile] | None = None
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        """
        returns move, value, turnsUsed, gatherNodes

        @param threat:
        @param force_turns_up_threat_path:
        @param gatherMax:
        @param shouldLog:
        @param addlTurns: if you want to gather longer than the threat, for final save.
        @param requiredContribution: replaces the threat.threatValue as the required army contribution if passed. Does nothing if gatherMax is True.
        @param additionalNegatives:
        @return: move, value, turnsUsed, gatherNodes
        """
        gatherDepth = threat.path.length - 1 + addlTurns
        # stuff closest to threat tile will have high initial distance

        distDict = threat.convert_to_dist_dict(allowNonChoke=force_turns_up_threat_path != 0)

        if self._map.is_player_on_team_with(threat.path.start.tile.player, self.general.player):
            raise AssertionError(f'threat paths should start with enemy tile, not friendly tile. Path {str(threat.path)}')

        tail = threat.path.tail
        for i in range(force_turns_up_threat_path):
            if tail is not None:
                # self.viewInfo.add_targeted_tile(tail.tile, TargetStyle.GREEN)
                distDict.pop(tail.tile, None)
                tail = tail.prev

        move_closest_priority_func = None
        move_closest_value_func = None
        if force_turns_up_threat_path == 0:
            move_closest_priority_func, move_closest_value_func = self.get_defense_tree_move_prio_funcs(threat)

        survivalThreshold = requiredContribution

        if survivalThreshold is None:
            survivalThreshold = threat.threatValue

        targetArmy = survivalThreshold
        if gatherMax:
            targetArmy = -1

        negatives = threat.path.tileSet.copy()

        if threat.path.tail != self.general:
            if len(self.get_danger_tiles()) > 0:
                negatives.add(self.general)

        if additionalNegatives is not None:
            negatives.update(negatives)

        move, value, turnsUsed, gatherNodes = self.get_gather_to_target_tiles(
            distDict,
            maxTime=0.05,
            gatherTurns=gatherDepth,
            targetArmy=targetArmy,
            useTrueValueGathered=False,
            negativeSet=negatives,
            leafMoveSelectionPriorityFunc=move_closest_priority_func,
            leafMoveSelectionValueFunc=move_closest_value_func,
            includeGatherTreeNodesThatGatherNegative=True,
            shouldLog=shouldLog)
        logging.info(f'get_gather_to_threat_path for depth {gatherDepth} force_turns_up_threat_path {force_turns_up_threat_path} returned {str(move)}, val {value} turns {turnsUsed}')

        return move, value, turnsUsed, gatherNodes

    def get_gather_to_threat_path_greedy(
            self,
            threat: ThreatObj,
            force_turns_up_threat_path = 0,
            gatherMax: bool = True,
            shouldLog: bool = False
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
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
                # self.viewInfo.add_targeted_tile(tail.tile, TargetStyle.GREEN)
                del distDict[tail.tile]
                tail = tail.prev

        distMap = SearchUtils.build_distance_map(self._map, [threat.path.start.tile])

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
            includeGatherTreeNodesThatGatherNegative=True,
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

            if self.target_player_gather_path is not None and self.target_player_gather_path.length > 20 and self._map.players[self.general.player].cityCount > 1:
                self.target_player_gather_path = self.target_player_gather_path.get_subsegment(20, end=True)

            if self.teammate_communicator is not None and self.teammate_general is not None:
                self.teammate_communicator.determine_leads(self._gen_distances, self._ally_distances, self.targetPlayerExpectedGeneralLocation)

        spawnDist = 12
        if self.target_player_gather_path is not None:
            self.target_player_gather_targets = self.target_player_gather_path.tileSet
            spawnDist = self.shortest_path_to_target_player.length

        with self.perf_timer.begin_move_event('calculating is_player_spawn_cramped'):
            self.force_city_take = self.is_player_spawn_cramped(spawnDist) and self._map.turn > 150
    #
    # def check_for_1_move_kills(self) -> typing.Union[None, Move]:
    #     """
    #     due to enemy_army_near_king logic, need to explicitly check for 1-tile-kills that we might win on luck
    #     @return:
    #     """
    #     for enemyGeneral in self._map.generals:
    #         if enemyGeneral is None or enemyGeneral == self.general:
    #             continue
    #
    #         for adj in enemyGeneral.movable:
    #             if adj.player == self.general.player and adj.army - 1 > enemyGeneral.army:
    #                 logging.info(f"Adjacent kill on general lul :^) {enemyGeneral.x},{enemyGeneral.y}")
    #                 return Move(adj, enemyGeneral)
    #
    #     return None

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
        if self.allIn and not self.all_in_city_behind:
            alwaysCheckKingKillWithinRange = 7

        for enemyGeneral in self.largeTilesNearEnemyKings.keys():
            if enemyGeneral is None or enemyGeneral.player == self.general.player or enemyGeneral.player in self._map.teammates:
                continue

            if not enemyGeneral.isGeneral:
                # TODO the exploration strategy right now backtracks a ton and doesn't capture tiles effectively,
                #  opt out except after army bonus for now unless we KNOW where the enemy gen is.
                #  Remove this later after fixing the backtracking problem and hunting generals more effectively.
                continue

            thisPlayerDepth = alwaysCheckKingKillWithinRange
            attackNegTiles = set()
            targetArmy = 1
            enPlayer = enemyGeneral.player
            if enPlayer == -1:
                enPlayer = self.targetPlayer

            nonGenArmy = 0
            if not enemyGeneral.isGeneral:
                targetArmy = nonGenArmy = 2 + int(self._map.players[enPlayer].standingArmy ** 0.5)
                thisPlayerDepth = max(1, thisPlayerDepth - 5)

            logging.info(
                f"Performing depth increasing BFS kill search on enemy king {enemyGeneral.toString()} depth {thisPlayerDepth}")
            for depth in range(2, thisPlayerDepth):
                enemyNegTiles = []
                if threat is not None:
                    enemyNegTiles.append(threat.path.start.tile)
                enemySavePath = self.get_best_defense(enemyGeneral, depth - 1, enemyNegTiles)
                if enemySavePath is not None:
                    targetArmy = enemySavePath.value + nonGenArmy
                    logging.info(f"  targetArmy {targetArmy}, enemySavePath {enemySavePath.toString()}")
                    attackNegTiles = enemySavePath.tileSet.copy()
                    attackNegTiles.remove(enemyGeneral)
                logging.info(f"  targetArmy to add to enemyGeneral kill = {targetArmy}")
                killPath = SearchUtils.dest_breadth_first_target(
                    self._map,
                    [enemyGeneral],
                    max(targetArmy, 1),
                    0.05,
                    depth,
                    attackNegTiles,
                    self.general.player,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog = True)
                if killPath is not None and killPath.length > 0:
                    logging.info(f"    depth {depth} path found to kill enemy king? {str(killPath)}")
                    if threat is None or (threat.turns >= killPath.length):
                        logging.info(f"    DEST BFS K found kill path length {killPath.length} :^)")
                        self.viewInfo.color_path(PathColorer(killPath, 255, 240, 79, 244, 5, 200))
                        move = Move(killPath.start.tile, killPath.start.next.tile)
                        self.curPath = None
                        if killPath.start.next.tile.isCity:
                            self.curPath = killPath
                        if self.is_move_safe_valid(move):
                            self.viewInfo.infoText = f"Depth increasing Killpath against general length {killPath.length}"
                            return move, killPath, canRace
                    else:
                        logging.info(
                            f"    DEST BFS K found kill path {str(killPath)} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
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
            killPath = SearchUtils.dest_breadth_first_target(self._map, [enemyGeneral], targetArmy + additionalKillArmyRequirement, 0.05, depth, attackNegTiles, self.general.player, False, 3)
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
                    f"DEST BFS K found kill path {str(killPath)} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
                if kingKillPath is None:
                    logging.info("  saving above kingKillPath as backup in case we can't defend threat")
                    if threat.turns + 1 == killPath.length:
                        self.viewInfo.addAdditionalInfoLine("     CAN RACE THOUGH!")
                        canRace = True

                    kingKillPath = killPath

            # king = enemyGeneral
            # tiles = self.largeTilesNearEnemyKings[king]
            # if len(tiles) > 0:
            #     logging.info(f"Attempting to find A_STAR kill path against general {king.player} ({king.x},{king.y})")
            #     bestTurn = 1000
            #     bestPath = None
            #     path = a_star_kill(
            #         self._map,
            #         tiles,
            #         king,
            #         0.03,
            #         self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 4,
            #         self.general_safe_func_set,
            #         requireExtraArmy = targetArmy + additionalKillArmyRequirement,
            #         negativeTiles = attackNegTiles)
            #
            #     if (path is not None and path.length >= 0) and (threat is None or ((threat.turns >= path.length or self.allIn) and threat.threatPlayer == king.player)):
            #         logging.info(f"  A_STAR found kill path length {path.length} :^)")
            #         self.viewInfo.color_path(PathColorer(path, 174, 4, 214, 255, 10, 200))
            #         self.curPath = path.get_subsegment(2)
            #         self.curPathPrio = 5
            #         if path.length < bestTurn:
            #             bestPath = path
            #             bestTurn = path.length
            #     elif path is not None and path.length > 0:
            #         logging.info(f"  A_STAR found kill path {str(path)} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
            #         self.viewInfo.color_path(PathColorer(path, 114, 4, 194, 255, 20, 100))
            #         if kingKillPath is None:
            #             logging.info("    saving above kingKillPath as backup in case we can't defend threat")
            #             if threat.turns + 1 == path.length:
            #                 self.viewInfo.addAdditionalInfoLine("     CAN RACE THOUGH!")
            #                 canRace = True
            #             kingKillPath = path
            #     if bestPath is not None:
            #         self.info(f"A* Killpath! {king.toString()},  {bestPath.toString()}")
            #         self.viewInfo.evaluatedGrid[king.x][king.y] = 200
            #         move = Move(bestPath.start.tile, bestPath.start.next.tile)
            #         return move, path, canRace
        return None, kingKillPath, canRace

    def calculate_target_player(self) -> int:
        targetPlayer = -1
        playerScore = 0

        if self._map.remainingPlayers == 2:
            for player in self._map.players:
                if player.index != self.general.player and not player.dead and player.index not in self._map.teammates:
                    return player.index

        allAfk = len(self.get_afk_players()) >= self._map.remainingPlayers - 1 - len(self._map.teammates)
        if allAfk or self._map.is_2v2:
            playerScore = -10000000

        minStars = 10000
        starSum = 0
        for player in self._map.players:
            minStars = min(minStars, player.stars)
            starSum += player.stars
        starAvg = starSum * 1.0 / len(self._map.players)
        self.playerTargetScores = [0 for i in range(len(self._map.players))]
        generalPlayer = self._map.players[self.general.player]

        for player in self._map.players:
            seenPlayer = len(player.tiles) != 0
            if player.dead or player.index == self._map.player_index or not seenPlayer or player.index in self._map.teammates:
                continue

            curScore = 300

            if self._map.remainingPlayers > 3:
                # ? I"M FRIENDLY I SWEAR
                curScore = -30
                if player.aggression_factor < 25:
                    curScore -= 50

            enGen = self._map.generals[player.index]

            knowsWhereEnemyGeneralIsBonus = 100
            if self._map.is_2v2:
                knowsWhereEnemyGeneralIsBonus = 1000
            if enGen is not None:
                curScore += knowsWhereEnemyGeneralIsBonus

            if player.leftGame and not player.dead:
                armyEnGenCutoffFactor = 0.75
                if enGen is not None:
                    if enGen.army < generalPlayer.standingArmy ** armyEnGenCutoffFactor:
                        self.viewInfo.addAdditionalInfoLine(f'leftGame GEN bonus army generalPlayer.standingArmy ** {armyEnGenCutoffFactor} {generalPlayer.standingArmy ** armyEnGenCutoffFactor} > enGen.army {enGen.army}')
                        curScore += 300
                    else:
                        curScore += 2500 // player.tileCount
                factor = 0.95
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    self.viewInfo.addAdditionalInfoLine(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 200
                factor = 0.88
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    self.viewInfo.addAdditionalInfoLine(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 100
                factor = 0.81
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    self.viewInfo.addAdditionalInfoLine(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 50
                factor = 0.75
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    self.viewInfo.addAdditionalInfoLine(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 30

            alreadyTargetingBonus = 120
            if player.index == self.targetPlayer:
                curScore += alreadyTargetingBonus

            curScore += player.aggression_factor

            # target players with better economies first
            #curScore += (player.tileCount + player.cityCount * 20 - player.standingArmy ** 0.88) / 4

            if generalPlayer.standingArmy > player.standingArmy * 0.7:
                # target players with better economies first more when we are winning
                curScore += player.cityCount * 20
                curScore += player.tileCount
                # 30% bonus for winning
                curScore *= 1.3

            if player.knowsKingLocation or player.knowsAllyKingLocation:
                curScore += 150
                curScore *= 2

            if self.generalApproximations[player.index][3] is not None:
                enApprox = self.generalApproximations[player.index][3]
                genDist = self.distance_from_general(enApprox)
                if self.teammate_general is not None:
                    genDist += self.euclidDist(self.teammate_general.x, self.teammate_general.y, enApprox.x, enApprox.y)
                    genDist = genDist // 2
            else:
                logging.info(f"           wot {self._map.usernames[targetPlayer]} didn't have a gen approx tile???")
                genDist = self.euclidDist(self.generalApproximations[player.index][0], self.generalApproximations[player.index][1], self.general.x, self.general.y)

                if self.teammate_general is not None:
                    genDist += self.euclidDist(self.teammate_general.x, self.teammate_general.y, self.generalApproximations[player.index][0], self.generalApproximations[player.index][1])
                    genDist = genDist // 2

            curScore = curScore + 2 * curScore / (max(10, genDist) - 2)

            if player.index != self.targetPlayer and not self._map.is_2v2:
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
        if self._map.remainingPlayers > 2 and playerScore < -100 and not self._map.is_2v2:
            return -1

        if targetPlayer != -1:
            logging.info(f"target player: {self._map.usernames[targetPlayer]} ({int(playerScore)})")

        return targetPlayer

    def get_gather_tiebreak_matrix(self) -> MapMatrix[float]:
        """
        Returns a MapMatrix that includes an int value that indicates how to tiebreak gather values.

        @return:
        """

        matrix = MapMatrix(self._map, 0.0)

        prioritized = self.prioritize_expansion_leaves(self.leafMoves)

        # for now just deprio 15

        for i, leafMove in enumerate(prioritized[0:10]):
            matrix[leafMove.source] = -4.0 / (i + 4)

        for tile in self.board_analysis.intergeneral_analysis.shortestPathWay.tiles:
            matrix[tile] -= 0.5

        return matrix

    def get_defense_moves(
            self,
            defenseCriticalTileSet: typing.Set[Tile],
            raceEnemyKingKillPath: typing.Union[Path, None]
    ) -> typing.Tuple[typing.Union[None, Move], typing.Union[None, Path]]:
        """
        Defend against a threat. Modifies the defense critical set to include save-tiles if a prune-defense is calculated and only barely saves.

        @param defenseCriticalTileSet:
        @param raceEnemyKingKillPath:
        @return:
        """

        outputDefenseCriticalTileSet = defenseCriticalTileSet
        defenseCriticalTileSet = defenseCriticalTileSet.copy()
        self.best_defense_leaves = []

        threats = []
        if self.dangerAnalyzer.fastestThreat is not None and self.dangerAnalyzer.fastestThreat.turns > -1:
            threats.append(self.dangerAnalyzer.fastestThreat)
        if self.dangerAnalyzer.fastestAllyThreat is not None and self.dangerAnalyzer.fastestAllyThreat.turns > -1:
            threats.append(self.dangerAnalyzer.fastestAllyThreat)

        threats = [t for t in sorted(threats, key=lambda t: t.threatValue, reverse=True)]

        negativeTilesIncludingThreat = set()
        for tile in outputDefenseCriticalTileSet:
            negativeTilesIncludingThreat.add(tile)

        for threat in threats:
            if threat is not None and threat.threatType == ThreatType.Kill:
                # dict = {}
                # dict[self.general] = (0, threat.threatValue, 0)
                for tile in threat.path.tileSet:
                    negativeTilesIncludingThreat.add(tile)

        anyRealThreats = False
        for threat in threats:
            isRealThreat = True
            if threat.turns < 6:
                with self.perf_timer.begin_move_event(f'def scrim @{str(threat.path.start.tile)} {str(threat.path)}'):
                    path, simResult = self.try_find_counter_army_scrim_path_kill(threat.path, allowGeneral=True, forceEnemyTowardsGeneral=True)
                if path is not None and simResult.net_economy_differential > -30:
                    return self.get_first_path_move(path), path

            if threat.path.start.tile in self.armyTracker.armies:
                self.targetingArmy = self.armyTracker.armies[threat.path.start.tile]

            savePath: Path = None
            searchTurns = threat.turns

            with self.perf_timer.begin_move_event('Searching for a threat killer move...'):
                move = self.get_threat_killer_move(threat, searchTurns, outputDefenseCriticalTileSet)
            if move is not None and (move.dest == threat.path.start.tile or move.dest == threat.path.start.next.tile):
                self.viewInfo.infoText = f"threat killer move! {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y}"
                if self.curPath is not None and move.source.tile == self.curPath.start.tile:
                    self.curPath.add_start(move.dest)
                    self.viewInfo.infoText = f"threat killer move {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} WITH ADDED FUN TO GET PATH BACK ON TRACK!"
                return self.move_half_on_repetition(move, 5, 4), savePath

            armyAmount = threat.threatValue + 1
            logging.info(
                f"\n!-!-!-!-!-!  general in danger in {threat.turns}, gather {armyAmount} to general in {searchTurns} turns  !-!-!-!-!-!")

            self.viewInfo.add_targeted_tile(self.general)
            gatherPaths = []
            flags = ''
            if threat is not None and threat.threatType == ThreatType.Kill:
                targetTile = None
                dict = {}
                dict[self.general] = (0, threat.threatValue, 0)

                # still have to gather the same amount to saveTile that we would have to the king
                if threat.saveTile is not None:
                    dict[threat.saveTile] = (0, threat.threatValue, -0.5)
                    self.viewInfo.add_targeted_tile(threat.saveTile, TargetStyle.PURPLE)
                    logging.info(
                        f"dict[threat.saveTile] = (0, {threat.threatValue})  -- threat.saveTile {threat.saveTile.x},{threat.saveTile.y}")

                # defenseNegatives = set(threat.path.tileSet)
                # defenseNegatives = set(threat.armyAnalysis.shortestPathWay.tiles)

                survivalThreshold = threat.threatValue
                # gatherVal = int(threat.threatValue * 0.8)
                with self.perf_timer.begin_move_event(f'Defense Threat Gather @ {str(threat.path.start.tile)}->{str(threat.path.tail.tile)}'):
                    additionalNegatives = set()
                    if self.teammate_communicator is not None:
                        survivalThreshold, additionalNegatives = self.teammate_communicator.get_additional_defense_negatives_and_contribution_requirement(threat)
                    outputDefenseCriticalTileSet.update(additionalNegatives)  # don't try to use these tiles for any other purpose, ally has purposed them for our defense
                    move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_threat_path(threat, requiredContribution=survivalThreshold, additionalNegatives=additionalNegatives)

                if move:
                    if valueGathered > survivalThreshold:
                        pruned = [node.deep_clone() for node in gatherNodes]
                        sumPrunedTurns, sumPruned, pruned = GatherUtils.prune_mst_to_army_with_values(
                            pruned,
                            survivalThreshold + 1,
                            self.general.player,
                            MapBase.get_teams_array(self._map),
                            self._map.turn,
                            viewInfo=self.viewInfo,
                            noLog=False)

                        if self.is_blocking_neutral_city_captures or valueGathered - sumPruned < 45:
                            self.block_neutral_captures('due to pruned defense being less than safe if we take the city.')

                        citiesInPruned = SearchUtils.Counter(0)
                        GatherUtils.iterate_tree_nodes(pruned, lambda n: citiesInPruned.add(1 * ((n.tile.isGeneral or n.tile.isCity) and self._map.is_tile_friendly(n.tile))))
                        turnGap = threat.turns - sumPrunedTurns
                        sumPruned += (turnGap * citiesInPruned.value // 2)
                        if sumPruned < survivalThreshold:
                            if SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING:
                                raise AssertionError(
                                    f'We should absolutely never get here with army pruned {sumPruned} being less than threat {survivalThreshold} but inside the original gather {valueGathered} greater than threat.')

                        saveTurns = threat.turns - 1
                        if threat.saveTile is not None:
                            saveTurns += 1
                        leavesGreaterThanDistance = GatherUtils.get_tree_leaves_further_than_distance(pruned, threat.armyAnalysis.aMap, saveTurns)
                        anyLeafIsSameDistAsThreat = len(leavesGreaterThanDistance) > 0
                        if anyLeafIsSameDistAsThreat:
                            flags = f'leafDist {flags}'
                        else:
                            leavesGreaterThanBlockDistance = GatherUtils.get_tree_leaves_further_than_distance(pruned, threat.armyAnalysis.aMap, saveTurns - 1)
                            if len(leavesGreaterThanBlockDistance) > 0:
                                outputDefenseCriticalTileSet.update([n.tile for n in leavesGreaterThanBlockDistance])

                        if sumPrunedTurns >= threat.turns - 1 or anyLeafIsSameDistAsThreat:  # was - 2, but that fails this test: test_should_not_defense_loop_let_army_engine_make_moves
                            pruned = [node.deep_clone() for node in gatherNodes]
                            sumPrunedTurns, sumPruned, pruned = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                                pruned,
                                survivalThreshold,
                                self.general.player,
                                MapBase.get_teams_array(self._map),
                                viewInfo=self.viewInfo)

                            move_closest_priority_func, move_closest_value_func = self.get_defense_tree_move_prio_funcs(threat, anyLeafIsSameDistAsThreat)
                            self.redGatherTreeNodes = gatherNodes

                            self.gatherNodes = pruned
                            move = self.get_tree_move_default(pruned, move_closest_priority_func, move_closest_value_func)
                            self.communicate_threat_to_ally(threat, sumPruned, pruned)
                            self.info(f'{flags}GathDef {str(move)} val {valueGathered}/p{sumPruned}/{survivalThreshold} turns {turnsUsed}/p{sumPrunedTurns}/{threat.turns}')
                            return move, savePath
                        else:
                            self.communicate_threat_to_ally(threat, sumPruned, pruned)
                            isRealThreat = False
                            # the threat is harmless...?
                            self.best_defense_leaves = GatherUtils.get_tree_leaves(pruned)

                            if sumPrunedTurns >= threat.turns - 2:
                                def addPrunedDefenseToDefenseNegatives(tn: GatherTreeNode):
                                    if tn.tile in self.board_analysis.intergeneral_analysis.pathChokes or tn.tile in threat.armyAnalysis.pathChokes:
                                        logging.info(f'    outputDefenseCriticalTileSet SKIPPING CHOKE {str(tn.tile)}')
                                    else:
                                        logging.info(f'    outputDefenseCriticalTileSet adding {str(tn.tile)}')
                                        outputDefenseCriticalTileSet.add(tn.tile)

                                GatherUtils.iterate_tree_nodes(pruned, addPrunedDefenseToDefenseNegatives)

                                if self.is_tile_in_friendly_territory(threat.path.start.tile):
                                    self.targetingArmy = self.get_army_at(threat.path.start.tile)
                                # logging.info(f"we're pretty safe from threat via gather, try fancier gather AT threat")
                                # atThreatMove, altValueGathered, altTurnsUsed, altGatherNodes = self.get_gather_to_threat_path(threat, force_turns_up_threat_path=threat.turns//2)
                                # if atThreatMove:
                                #     self.info(f'{str(atThreatMove)} AT threat value {altValueGathered}/{survivalThreshold} turns {altTurnsUsed}/{threat.turns}')
                                #     self.gatherNodes = altGatherNodes
                                #     return atThreatMove, savePath

                                self.viewInfo.addAdditionalInfoLine(f'  DEF NEG ADD - prune t{sumPrunedTurns} < threat.turns - 3 {threat.turns - 3} (threatVal {survivalThreshold} v pruneVal {sumPruned})')

                # they might not find us, giving us more time to gather. Also they'll likely waste some army running around our tiles so subtract 10 from the threshold.
                abandonDefenseThreshold = survivalThreshold * 0.8 - 3 - threat.turns
                threatMovingWrongWay = False
                threatTile = threat.path.start.tile
                if threatTile.delta.fromTile:
                    threatDist = self.euclidDist(threatTile.x, threatTile.y, threat.path.tail.tile.x, threat.path.tail.tile.y)
                    threatFromDist = self.euclidDist(threatTile.delta.fromTile.x, threatTile.delta.fromTile.y, threat.path.tail.tile.x, threat.path.tail.tile.y)
                    if threatDist >= threatFromDist:
                        threatMovingWrongWay = True
                if len(self._map.players) == 2 and self._map.turn > 250 and not threatMovingWrongWay:
                    # then they probably have a really good idea of where we are by now.

                    # TODO replace this with a "percentage of our forward tiles discovered by enemy" based calculation.
                    #  In FFAs where the player has barely seen us till 200+ tiles, dont abandon defense easily. Etc.
                    abandonDefenseThreshold = survivalThreshold * 0.94 - threat.turns // 2
                if self._map.players[threat.threatPlayer].knowsKingLocation:
                    abandonDefenseThreshold = survivalThreshold * 0.97

                if valueGathered < survivalThreshold - 1:
                    self.communicate_threat_to_ally(threat, valueGathered, gatherNodes)
                    flags = f'DEAD {flags}'

                    with self.perf_timer.begin_move_event(f'+1 Defense Threat Gather'):
                        altMove, altValueGathered, altTurnsUsed, altGatherNodes = self.get_gather_to_threat_path(threat, requiredContribution=survivalThreshold, additionalNegatives=additionalNegatives, addlTurns=1)
                    if altMove is not None:
                        directlyAttacksDest = altMove.dest == threat.path.start.tile
                        if directlyAttacksDest or gatherNodes is None or not self.is_2v2_teammate_still_alive():  # or valueGathered / turnsUsed < survivalThreshold / (2 * threat.turns) ?
                            if altValueGathered >= survivalThreshold:
                                self.redGatherTreeNodes = gatherNodes
                                move = altMove
                                valueGathered = altValueGathered
                                turnsUsed = altTurnsUsed
                                gatherNodes = altGatherNodes

                if not isRealThreat:
                    flags = f'wait {flags}'
                    self.redGatherTreeNodes = gatherNodes
                    self.gatherNodes = None

                self.info(f'{flags}GathDef {str(move)} val {valueGathered}/{survivalThreshold} turns {turnsUsed}/{threat.turns} (abandThresh {abandonDefenseThreshold:.0f})')
                if isRealThreat:
                    anyRealThreats = True
                    if threat.turns < 6:
                        self.increment_attack_counts(threat.path.tail.tile)

                    if valueGathered > abandonDefenseThreshold or (self.is_2v2_teammate_still_alive() and len(additionalNegatives) == 0):
                        self.curPath = None
                        self.gatherNodes = gatherNodes
                        return move, savePath

            if not isRealThreat:
                continue

            armyAmount = 1
            defenseNegatives = set(threat.path.tileSet)
            defenseNegatives = set(threat.armyAnalysis.shortestPathWay.tiles)
            altKillOffset = 0
            if not self.targetPlayerExpectedGeneralLocation.isGeneral:
                altKillOffset = 5 + int(len(self.targetPlayerObj.tiles) ** 0.5)
                logging.info(f'altKillOffset {altKillOffset} because dont know enemy gen position for sure')
            with self.perf_timer.begin_move_event(
                    f"ATTEMPTING TO FIND KILL ON ENEMY KING UNDISCOVERED SINCE WE CANNOT SAVE OURSELVES, TURNS {threat.turns - 1}:"):
                altKingKillPath = SearchUtils.dest_breadth_first_target(
                    self._map,
                    [self.targetPlayerExpectedGeneralLocation],
                    12,
                    0.1,
                    threat.turns + 1,
                    outputDefenseCriticalTileSet,
                    searchingPlayer=self.general.player,
                    dontEvacCities=False)
                if altKingKillPath is not None:
                    logging.info(
                        f"   Did find a killpath on enemy gen / undiscovered {str(altKingKillPath)}")
                    # these only return if we think we can win/tie the race
                    if (raceEnemyKingKillPath is None or raceEnemyKingKillPath.length >= threat.turns) and altKingKillPath.length + altKillOffset < threat.turns:
                        self.info(f"{flags} altKingKillPath {str(altKingKillPath)} altKillOffset {altKillOffset}")
                        self.viewInfo.color_path(PathColorer(altKingKillPath, 122, 97, 97, 255, 10, 200))
                        return self.get_first_path_move(altKingKillPath), savePath
                    elif raceEnemyKingKillPath is not None:
                        logging.info("   raceEnemyKingKillPath already existing, will not use the above.")
                        self.info(f"{flags} raceEnemyKingKillPath {str(raceEnemyKingKillPath)} altKillOffset {altKillOffset}")
                        self.viewInfo.color_path(PathColorer(raceEnemyKingKillPath, 152, 97, 97, 255, 10, 200))
                        return self.get_first_path_move(raceEnemyKingKillPath), savePath

            if altKingKillPath is not None:
                if raceEnemyKingKillPath is None or raceEnemyKingKillPath.length > threat.turns:
                    self.info(
                        f"{flags} altKingKillPath (long {altKingKillPath.length} vs threat {threat.turns}) {str(altKingKillPath)}")
                    self.viewInfo.color_path(PathColorer(altKingKillPath, 122, 97, 97, 255, 10, 200))
                    return self.get_first_path_move(altKingKillPath), savePath
                elif raceEnemyKingKillPath is not None:
                    logging.info("   raceEnemyKingKillPath already existing, will not use the above.")
                    self.info(
                        f"{flags} raceEnemyKingKillPath (long {altKingKillPath.length} vs threat {threat.turns}) {str(raceEnemyKingKillPath)}")
                    self.viewInfo.color_path(PathColorer(raceEnemyKingKillPath, 152, 97, 97, 255, 10, 200))
                    return self.get_first_path_move(raceEnemyKingKillPath), savePath

            logging.info(
                f"LEGACY dest_breadth_first_target: armyAmount {armyAmount}, searchTurns {searchTurns}, ignoreGoalArmy True")
            legacySavePath = SearchUtils.dest_breadth_first_target(self._map, dict, armyAmount, 0.1, searchTurns, negativeTilesIncludingThreat, searchingPlayer = self.general.player, ignoreGoalArmy=True)
            legacySavePath: Path = None
            if legacySavePath is not None and legacySavePath.length > 0:
                legacySavePath.calculate_value(self.general.player)
                logging.info(
                    f"    DEST BFS TARGET to save king, \n   turn {legacySavePath.length}, value {legacySavePath.value} : {legacySavePath.toString()}")
                gatherPaths.append(legacySavePath)
            else:
                targetGen = self._map.generals[threat.threatPlayer]
                if targetGen is not None and not targetGen.visible and targetGen.army > 10:
                    logging.info("\n\n!-!-!-!-!-! \nIt may be too late to save general, setting their general val to 3\n!-!-!-!-!-!")
                    targetGen.army = 3

        if not anyRealThreats:
            # if self.behavior_allow_defense_army_scrim:
            #     scrimMove = self.try_scrim_against_threat_with_largest_pruned_gather_node(move, pruned, threat)
            #     if scrimMove is not None:
            #         return scrimMove, savePath
            #
            return None, None

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
                    outputDefenseCriticalTileSet.add(saveNode.tile)
                    saveNode = saveNode.next
        else:
            while not queue.empty() and len(paths) < 5:
                node = queue.get()
                legacySavePath = node[1]
                paths.append(legacySavePath)
                self.info(
                    f"GHETTO QUEUE path to save king, ({node[0]}) turn {legacySavePath.length}, value {legacySavePath.value} : {legacySavePath.toString()}")

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

        if isRealThreat:
            # try hunt kill...?
            explorePath = self.get_optimal_exploration(max(5, threat.turns))
            if explorePath is not None:
                self.info(f'DEAD EXPLORE {str(explorePath)}')
                return self.get_first_path_move(explorePath), explorePath

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
        if self.teammate_general is not None:
            negExpandTiles.update(self._map.players[self.teammate_general.player].tiles)

        # we already stripped the move we're not doing off curPath so + 1
        lengthToReplaceCurrentPlan = curPath.length
        rePlanLength = lengthToReplaceCurrentPlan + countExtraUseableMoves
        with self.perf_timer.begin_move_event(f'Re-calc F25 Expansion for {str(move.source)} (length {rePlanLength})'):
            newPath, otherPaths = ExpandUtils.get_optimal_expansion(
                self._map,
                self.general.player,
                self.targetPlayer,
                rePlanLength,
                self.board_analysis,
                self.territories.territoryMap,
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

    def get_army_at(self, tile: Tile, no_expected_path: bool=False):
        return self.armyTracker.get_or_create_army_at(tile, skip_expected_path=no_expected_path)

    def get_army_at_x_y(self, x: int, y: int):
        tile = self._map.GetTile(x, y)
        return self.get_army_at(tile)

    def initialize_map_for_first_time(self, map: MapBase):
        self._map = map

        self.initialize_logging()
        self.general = self._map.generals[self._map.player_index]
        self.player = self._map.players[self.general.player]

        self.teams = MapBase.get_teams_array(map)

        for teammate in self._map.teammates:
            teammatePlayer = self._map.players[teammate]
            if teammatePlayer.dead:
                continue
            self.teammate_general = self._map.generals[teammate]
            self._ally_distances = SearchUtils.build_distance_map(self._map, [self.teammate_general])
            allyUsername = self._map.usernames[self.teammate_general.player]
            if "EklipZ" in allyUsername or "Teammate.exe" == allyUsername or "Human.exe" == allyUsername or "Exe.human" == allyUsername:
                # Use more excessive pings when paired with a bot for inter-bot communication.
                self.teamed_with_bot = True

        self._gen_distances = SearchUtils.build_distance_map(self._map, [self.general])
            
        self.dangerAnalyzer = DangerAnalyzer(self._map)
        self.cityAnalyzer = CityAnalyzer(self._map, self.general)
        self.gatherAnalyzer = GatherAnalyzer(self._map)
        self.viewInfo = ViewInfo(2, self._map.cols, self._map.rows)
        self.isInitialized = True

        self._map.notify_city_found.append(self.handle_city_found)
        self._map.notify_tile_captures.append(self.handle_tile_captures)
        self._map.notify_tile_deltas.append(self.handle_tile_deltas)
        self._map.notify_tile_discovered.append(self.handle_tile_discovered)
        self._map.notify_tile_revealed.append(self.handle_tile_vision_change)
        self._map.notify_player_captures.append(self.handle_player_captures)
        if self.territories is None:
            self.territories = TerritoryClassifier(self._map)

        self.armyTracker = ArmyTracker(self._map)
        self.armyTracker.notify_unresolved_army_emerged.append(self.handle_tile_vision_change)
        self.armyTracker.notify_army_moved.append(self.handle_army_moved)
        self.targetPlayerExpectedGeneralLocation = self.general.movable[0]
        self.launchPoints.append(self.general)
        self.board_analysis = BoardAnalyzer(self._map, self.general, self.teammate_general)
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
        """

        @param defenseCriticalTileSet:
        @return:
        """

        if self.winning_on_economy(byRatio=1.5) and self.all_in_army_advantage:
            return None

        cityDepthCutoffEnTerritory = max(3, int(self._map.players[self.general.player].tileCount**0.31))
        """
        for i in [50, 75, 100, 150, 200, 250]:
            print(f'{i}: {i ** 0.31:.2f}')
            50: 3.36
            75: 3.81
            100: 4.17
            150: 4.73
            200: 5.17
            250: 5.54
        """

        shortestKill: Path | None = None
        #if (len(self.enemyCities) > 5):
        #    cityDepthSearch = 5
        enemyCitiesOrderedByPriority = self.cityAnalyzer.get_sorted_enemy_scores()
        for enemyCity, score in enemyCitiesOrderedByPriority:
            negTilesToUse = defenseCriticalTileSet.copy()

            # if the city is part of the threat path, leaving it in negative tiles tries to kill it with '1' army instead of the actual value on it.
            # negTilesToUse.discard(enemyCity)
            if enemyCity in defenseCriticalTileSet:
                negTilesToUse = set()

            cityDepthSearch = cityDepthCutoffEnTerritory
            if self.is_tile_in_friendly_territory(enemyCity):
                cityDepthSearch = cityDepthCutoffEnTerritory + 6
            elif not self.is_tile_in_enemy_territory(enemyCity):
                cityDepthSearch = cityDepthCutoffEnTerritory + 3

            if self.dangerAnalyzer.fastestThreat is not None and enemyCity in self.dangerAnalyzer.fastestThreat.path.tileSet:
                # if we got here, we either can't defend the threat or we're already safe from the threat with whats on
                # the path, and the threat includes the city, so then we're safe to use anything on the path to kill part of the threat.
                logging.info(f'bypassing defenseCriticalTileSet for city quick kill on {str(enemyCity)} due to it being part of threat path')
                negTilesToUse = set()

            logging.info(
                f"{self.get_elapsed()} searching for depth {cityDepthSearch} dest bfs kill on city {enemyCity.x},{enemyCity.y}")
            self.viewInfo.add_targeted_tile(enemyCity, TargetStyle.RED)
            armyToSearch = self.get_target_army_inc_adjacent_enemy(enemyCity) + 1
            addlIncrementing = SearchUtils.count(enemyCity.adjacents, lambda tile: tile.isCity and self._map.is_tile_enemy(tile))

            # TODO switch to dynamic max beyond range xyz
            killPath = SearchUtils.dest_breadth_first_target(
                self._map,
                [enemyCity],
                armyToSearch,
                0.1,
                cityDepthSearch,
                negTilesToUse,
                searchingPlayer = self.general.player,
                dontEvacCities=False,
                additionalIncrement=addlIncrementing / 2,
                )
            if killPath is not None:
                if killPath.start.tile.isCity and self.should_kill_path_move_half(killPath, armyToSearch - enemyCity.army):
                    killPath.start.move_half = True
                if shortestKill is None or shortestKill.length > killPath.length:
                    self.info(
                        f"En city kill len {killPath.length} on {str(enemyCity)}: {str(killPath)}")
                    shortestKill = killPath

        if shortestKill is not None:
            tgCity = shortestKill.tail.tile
            negTilesToUse = defenseCriticalTileSet
            if tgCity in defenseCriticalTileSet:
                negTilesToUse = set()

            if self.dangerAnalyzer.fastestThreat is not None and tgCity in self.dangerAnalyzer.fastestThreat.path.tileSet:
                # if we got here, we either can't defend the threat or we're already safe from the threat with whats on
                # the path, and the threat includes the city, so then we're safe to use anything on the path to kill part of the threat.
                logging.info(f'bypassing defenseCriticalTileSet for city quick kill on {str(tgCity)} due to it being part of threat path')
                negTilesToUse = set()

            armyToSearch = self.get_target_army_inc_adjacent_enemy(tgCity)
            cityPath = shortestKill.get_subsegment(3, end=True)
            # armyToSearch = 1
            path, move = self.plan_city_capture(
                tgCity,
                cityPath,
                allowGather=True,
                targetKillArmy=armyToSearch - 1,
                targetGatherArmy=tgCity.army + armyToSearch - 1,
                killSearchDist=5,
                gatherMaxDuration=int(self.player.tileCount ** 0.32) + 1,
                negativeTiles=negTilesToUse)
            if path is not None:
                return path
            if move is not None:
                fakePath = Path()
                fakePath.add_next(move.source)
                fakePath.add_next(move.dest)
                return fakePath

        return None

    def prep_view_info_for_render(self):
        self.viewInfo.board_analysis = self.board_analysis
        self.viewInfo.targetingArmy = self.targetingArmy
        self.viewInfo.armyTracker = self.armyTracker
        self.viewInfo.dangerAnalyzer = self.dangerAnalyzer
        self.viewInfo.currentPath = self.curPath
        self.viewInfo.gatherNodes = self.gatherNodes
        self.viewInfo.redGatherNodes = self.redGatherTreeNodes
        self.viewInfo.territories = self.territories
        self.viewInfo.allIn = self.allIn
        self.viewInfo.timings = self.timings
        self.viewInfo.allInCounter = self.all_in_counter
        self.viewInfo.targetPlayer = self.targetPlayer
        self.viewInfo.generalApproximations = self.generalApproximations
        self.viewInfo.playerTargetScores = self.playerTargetScores

        if self.armyTracker is not None:
            if self.info_render_army_emergence_values:
                for tile in self._map.reachableTiles:
                    val = self.armyTracker.emergenceLocationMap[self.targetPlayer][tile.x][tile.y]
                    if val != 0:
                        textVal = f"e{val:.0f}"
                        self.viewInfo.bottomMidRightGridText[tile.x][tile.y] = textVal

            for tile in self.armyTracker.dropped_fog_tiles_this_turn:
                self.viewInfo.add_targeted_tile(tile, TargetStyle.RED)

            for tile in self.armyTracker.decremented_fog_tiles_this_turn:
                self.viewInfo.add_targeted_tile(tile, TargetStyle.GREEN)

        if self.gatherAnalyzer is not None and self.info_render_gather_locality_values:
            for tile in self._map.pathableTiles:
                if tile.player == self.general.player:
                    self.viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'g{self.gatherAnalyzer.gather_locality_map[tile]}'

        if self.info_render_tile_deltas:
            self.render_tile_deltas_in_view_info(self.viewInfo, self._map)

        if self.target_player_gather_path is not None:
            alpha = 140
            minAlpha = 100
            alphaDec = 5
            self.viewInfo.color_path(PathColorer(self.target_player_gather_path, 60, 50, 00, alpha, alphaDec, minAlpha))

        if self.board_analysis.intergeneral_analysis is not None:
            nonZoneMatrix = MapMatrix(self._map, False)
            for tile in self._map.get_all_tiles():
                if tile not in self.board_analysis.core_play_area_matrix:
                    nonZoneMatrix[tile] = True
            self.viewInfo.add_map_zone(nonZoneMatrix, (100, 100, 50), alpha=35)

            # self.viewInfo.add_map_zone(self.board_analysis.extended_play_area_matrix, (255, 220, 0), alpha=50)
            self.viewInfo.add_map_division(self.board_analysis.extended_play_area_matrix, (255, 230, 0), alpha=100)

            self.viewInfo.add_map_division(self.board_analysis.flank_danger_play_area_matrix, (205, 80, 40), alpha=150)

    def get_move_if_afk_player_situation(self) -> Move | None:
        afkPlayers = self.get_afk_players()
        allOtherPlayersAfk = len(afkPlayers) + 1 == self._map.remainingPlayers
        numTilesVisible = 0
        if self.targetPlayer != -1:
            numTilesVisible = len(self._map.players[self.targetPlayer].tiles)

        logging.info(
            f"{self.get_elapsed()} TEMP! len(self._map.players[self.targetPlayer].tiles) {numTilesVisible}, allOtherPlayersAfk {allOtherPlayersAfk}, ")
        if allOtherPlayersAfk and numTilesVisible == 0:
            # then just expand until we can find them
            with self.perf_timer.begin_move_event('AFK Player optimal EXPLORATION'):
                path = self.get_optimal_exploration(30, None, minArmy= 0)
            if path is not None:
                self.info(f"Rapid EXPLORE due to AFK player {self.targetPlayer}:  {str(path)}")

                self.finishing_exploration = True
                self.viewInfo.addAdditionalInfoLine("Setting finishingExploration to True because allOtherPlayersAfk and found an explore path")
                return self.get_first_path_move(path)

            expansionNegatives = set()
            territoryMap = self.territories.territoryMap
            with self.perf_timer.begin_move_event('AFK Player optimal EXPANSION'):
                if self.teammate_general is not None:
                    expansionNegatives.add(self.teammate_general)
                path, otherPaths = ExpandUtils.get_optimal_expansion(
                    self._map,
                    self.general.player,
                    self.targetPlayer,
                    15,
                    self.board_analysis,
                    territoryMap,
                    expansionNegatives,
                    self.leafMoves,
                    allowLeafMoves = False,
                    viewInfo=self.viewInfo)

            if path is not None:
                self.finishing_exploration = True
                self.info(f"Rapid EXPAND due to AFK player {self.targetPlayer}:  {str(path)}")
                return self.get_first_path_move(path)

        if self.targetPlayer != -1:
            if self._map.players[self.targetPlayer].leftGame and self._map.turn < self._map.players[self.targetPlayer].leftGameTurn + 50:
                remainingTurns = self._map.players[self.targetPlayer].leftGameTurn + 50 - self._map.turn
                turns = max(8, remainingTurns - 15)
                with self.perf_timer.begin_move_event(f'Quick kill gather to player who left, {remainingTurns} until they arent capturable'):
                    move = self.timing_gather(
                        [self.targetPlayerExpectedGeneralLocation],
                        force=True,
                        targetTurns=turns,
                        pruneToValuePerTurn=True)
                if move is not None:
                    self.info(f"quick-kill gather to opposing player who left! {str(move)}")
                    return move

            if allOtherPlayersAfk and self.targetPlayerExpectedGeneralLocation is not None and self.targetPlayerExpectedGeneralLocation.isGeneral:
                # attempt to quick-gather to this gen for kill
                with self.perf_timer.begin_move_event(f'quick-kill gather to opposing player!'):
                    move = self.timing_gather(
                        [self.targetPlayerExpectedGeneralLocation],
                        force=True,
                        pruneToValuePerTurn=True)
                if move is not None:
                    self.info(f"quick-kill gather to opposing player! {str(move)}")
                    return move

        return None

    def clear_fog_armies_around(self, enemyGeneral: Tile):

        def fog_army_clear_func(tile: Tile):
            if not tile.visible and tile in self.armyTracker.armies:
                army = self.armyTracker.armies[tile]
                if army.player == enemyGeneral.player:
                    self.armyTracker.scrap_army(army)

        SearchUtils.breadth_first_foreach(self._map, [enemyGeneral], maxDepth=7, foreachFunc=fog_army_clear_func)

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
                if tile and maxAmount < self.undiscovered_priorities[x][y] and self.distance_from_general(tile) > minSpawnDist and (self.teammate_general is None or self.distance_from_teammate(tile) > minSpawnDist):
                    maxAmount = self.undiscovered_priorities[x][y]
                    maxTile = tile
                if self.targetPlayer == -1:
                    if self.undiscovered_priorities[x][y] > 0 and self.info_render_general_undiscovered_prediction_values:
                        self.viewInfo.bottomRightGridText[x][y] = f'u{self.undiscovered_priorities[x][y]}'

        self.viewInfo.add_targeted_tile(maxTile, TargetStyle.PURPLE)
        return maxTile

    def try_gather_tendrils_towards_enemy(self, turns: int | None = None) -> Move | None:
        # # TODO hack for now because this doesn't perform well
        return None
        if self._map.remainingPlayers > 3 and self.targetPlayer == -1:
            return None
        generalApproxErrorLvl = 10
        if self.target_player_gather_path is not None:
            generalApproxErrorLvl = self.target_player_gather_path.length + 5
            if self._map.turn > 200:
                generalApproxErrorLvl = self.target_player_gather_path.length // 2

        if turns is None:
            turns = 25 - self._map.turn % 25
        targets = []
        if self.targetPlayer != -1:
            for tile in self._map.pathableTiles:
                if tile.visible:
                    continue

                if (self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer
                    or (
                        self.board_analysis.intergeneral_analysis is not None
                        and self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y] < generalApproxErrorLvl
                    )
                    or tile.player == self.targetPlayer
                    or tile == self.targetPlayerExpectedGeneralLocation
                ):
                    targets.append(tile)
        else:
            distMap = SearchUtils.build_distance_map(self._map, [self.targetPlayerExpectedGeneralLocation])
            for tile in self._map.pathableTiles:
                if not SearchUtils.any_where(tile.movable, lambda t: not t.visible):
                    continue

                if self.distance_from_general(tile) < 15:
                    continue

                if (self.territories.territoryMap[tile.x][tile.y] == self.targetPlayer
                    or distMap[tile.x][tile.y] < generalApproxErrorLvl
                    or tile.player == self.targetPlayer
                    or tile == self.targetPlayerExpectedGeneralLocation
                ):
                    targets.append(tile)

        for target in targets:
            self.mark_tile(target, 255)

        move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_target_tiles(
            targets,
            0.1,
            turns,
            negativeSet=self.target_player_gather_targets,
            includeGatherTreeNodesThatGatherNegative=True,
            useTrueValueGathered=False,
            maximizeArmyGatheredPerTurn=True,
            targetArmy=-60)
        if move is not None:
            self.info(f'lmao gather AT tg loc, gathered {valueGathered} turns used {turnsUsed}')
            self.gatherNodes = gatherNodes
            return move

        greedyValue, turnsUsed, gatherNodes = GatherUtils.greedy_backpack_gather_values(
            self._map,
            targets,
            turns,
            targetArmy=-60,
            negativeTiles=self.target_player_gather_targets,
            includeGatherTreeNodesThatGatherNegative=True,
            useTrueValueGathered=False,
            preferNeutral=True)

        totalValue = 0
        gathTurns = 0
        for gather in gatherNodes:
            logging.info(f"gatherNode {gather.tile.toString()} value {gather.value}")
            totalValue += gather.value
            gathTurns += gather.gatherTurns
        if totalValue != greedyValue or gathTurns != turnsUsed:
            self.info(f'Greedy said it did v{greedyValue}/t{turnsUsed} but we found v{totalValue}/t{gathTurns}')

        move = self.get_tree_move_default(gatherNodes)
        if move is not None:
            self.info(f'Greedy tendrils, non-greedy failed? v{totalValue}/t{gathTurns}')
            self.gatherNodes = gatherNodes
            return move

        self.info('tendrils failed')
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
            if (
                    firstPathMove
                    and not result.best_result_state.captured_by_enemy
                    and (result.net_economy_differential > self.engine_mcts_move_estimation_net_differential_cutoff or forceKeepMove)
            ):
                self.info(f'ARMY SCRIM MOVE {str(friendlyArmyTile)}@{str(enemyArmyTile)} EVAL {str(result)}: {str(firstPathMove)}')

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

        friendlyPath, enemyPath = self.extract_engine_result_paths_and_render_sim_moves(result)

        return friendlyPath, enemyPath, result

    def get_army_scrim_result(
            self,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            enemyCannotMoveAway: bool = False,
            enemyHasKillThreat: bool | None = None,
            friendlyHasKillThreat: bool | None = None
    ) -> ArmySimResult:
        frArmies = [self.get_army_at(friendlyArmyTile)]
        enArmies = [self.get_army_at(enemyArmyTile)]

        if self.engine_use_mcts and self.engine_force_multi_tile_mcts:
            frTiles = self.find_large_tiles_near(
                fromTiles=[friendlyArmyTile, enemyArmyTile],
                distance=self.engine_army_nearby_tiles_range,
                forPlayer=self.general.player,
                allowGeneral=True,
                limit=self.engine_mcts_scrim_armies_per_player_limit,
                minArmy=6,
            )
            enTiles = self.find_large_tiles_near(
                fromTiles=[friendlyArmyTile, enemyArmyTile],
                distance=self.engine_army_nearby_tiles_range,
                forPlayer=enemyArmyTile.player,
                allowGeneral=True,
                limit=self.engine_mcts_scrim_armies_per_player_limit - 1,
                minArmy=6,
            )

            for frTile in frTiles:
                if frTile != friendlyArmyTile:
                    frArmies.append(self.get_army_at(frTile))
                    self.viewInfo.add_targeted_tile(frTile, TargetStyle.TEAL)

            for enTile in enTiles:
                if enTile != enemyArmyTile:
                    enArmies.append(self.get_army_at(enTile))
                    self.viewInfo.add_targeted_tile(enTile, TargetStyle.PURPLE)

            lastMove: Move | None = self.armyTracker.lastMove
            if self.engine_always_include_last_move_tile_in_scrims and lastMove is not None:
                if lastMove.dest.player == self.general.player and lastMove.dest.army > 1:
                    lastMoveArmy = self.get_army_at(lastMove.dest)
                    if lastMoveArmy not in frArmies:
                        frArmies.append(lastMoveArmy)

        result = self.get_armies_scrim_result(
            friendlyArmies=frArmies,
            enemyArmies=enArmies,
            enemyCannotMoveAway=enemyCannotMoveAway,
            enemyHasKillThreat=enemyHasKillThreat,
            friendlyHasKillThreat=friendlyHasKillThreat,
        )
        return result

    def get_armies_scrim_result(
            self,
            friendlyArmies: typing.List[Army],
            enemyArmies: typing.List[Army],
            enemyCannotMoveAway: bool = False,
            enemyHasKillThreat: bool | None = None,
            friendlyHasKillThreat: bool | None = None,
            time_limit: float = 0.05
    ) -> ArmySimResult:
        result = self.get_scrim_cached(friendlyArmies, enemyArmies)
        if result is not None:
            self.info(
                f'  ScC {"+".join([str(a.tile) for a in friendlyArmies])}@{"+".join([str(a.tile) for a in enemyArmies])}: {str(result)} {repr(result.expected_best_moves)}')
            return result

        if friendlyHasKillThreat is None:
            friendlyHasKillThreat = False
            for frArmy in friendlyArmies:
                friendlyArmyTile = frArmy.tile
                path = SearchUtils.a_star_kill(
                    self._map,
                    [friendlyArmyTile],
                    self.targetPlayerExpectedGeneralLocation,
                    0.03,
                    self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3,
                    # self.general_safe_func_set,
                    requireExtraArmy=5 if self.targetPlayerExpectedGeneralLocation.isGeneral else 20,
                    negativeTiles=set([a.tile for a in enemyArmies]))
                if path is not None:
                    friendlyHasKillThreat = True

        if enemyHasKillThreat is None:
            enemyHasKillThreat = False
            for enArmy in enemyArmies:
                if enArmy.expectedPath is not None and enArmy.expectedPath.tail.tile.isGeneral and self._map.is_tile_friendly(enArmy.expectedPath.tail.tile):
                    if enArmy.expectedPath.calculate_value(enArmy.player, set([a.tile for a in friendlyArmies])) > 0:
                        enemyHasKillThreat = True

        if len(enemyArmies) == 0:
            enemyArmies = [self.get_army_at(self._map.players[self.targetPlayer].tiles[0])]

        engine: ArmyEngine = ArmyEngine(self._map, friendlyArmies, enemyArmies, self.board_analysis, timeCap=0.05, mctsRunner=self.mcts_engine)
        engine.eval_params = self.mcts_engine.eval_params
        engine.allow_enemy_no_op = self.engine_allow_enemy_no_op
        engine.honor_mcts_expected_score = self.engine_honor_mcts_expected_score
        engine.honor_mcts_expanded_expected_score = self.engine_honor_mcts_expanded_expected_score

        depth = 4
        # only check this stuff for the primary threat army
        enemyArmy = enemyArmies[0]
        if enemyCannotMoveAway and self.engine_allow_force_incoming_armies_towards:
            # we can scan much deeper when the enemies moves are heavily restricted.
            depth = 6
            if enemyArmy.expectedPath is not None:
                engine.force_enemy_towards = SearchUtils.build_distance_map_matrix(self._map, [enemyArmy.expectedPath.tail.tile])
                logging.info(f'forcing enemy scrim moves towards {str(enemyArmy.expectedPath.tail.tile)}')
            else:
                engine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(self._map, [self.general])
                logging.info(f'forcing enemy scrim moves towards our general')

            engine.allow_enemy_no_op = False

        if DebugHelper.IS_DEBUGGING:
            engine.time_limit = 1000
            engine.iteration_limit = 1000
        else:
            engine.time_limit = time_limit
            # TODO remove this stuff once we do end-of-turn scrim instead
            depthInMove = self.perf_timer.current_move.get_time_elapsed()
            if depthInMove > 0.15:
                engine.time_limit = 0.06
            if depthInMove > 0.25:
                engine.time_limit = 0.04
            if depthInMove > 0.3:
                engine.time_limit = 0.02

        engine.friendly_has_kill_threat = friendlyHasKillThreat
        engine.enemy_has_kill_threat = enemyHasKillThreat and not self.should_abandon_king_defense()
        if self.disable_engine:
            depth = 0

        result = engine.scan(depth, noThrow=True, mcts=self.engine_use_mcts)
        self.info(f' Scr {"+".join([str(a.tile) for a in friendlyArmies])}@{"+".join([str(a.tile) for a in enemyArmies])}: {str(result)} {repr(result.expected_best_moves)}')
        scrimCacheKey = self.get_scrim_cache_key(friendlyArmies, enemyArmies)
        self.cached_scrims[scrimCacheKey] = result
        return result

    def extend_interspersed_path_moves(self, paths: typing.List[Path], move: Move | None):
        if move is not None:
            if move.dest is None:
                raise AssertionError()

            curPath: Path | None = None
            for p in paths:
                if p.tail is not None and p.tail.tile == move.source:
                    curPath = p
                    break

            if curPath is None:
                curPath = Path()
                curPath.add_next(move.source)
                paths.append(curPath)
            curPath.add_next(move.dest, move.move_half)

    def extract_engine_result_paths_and_render_sim_moves(self, result: ArmySimResult) -> typing.Tuple[Path | None, Path | None]:
        friendlyPaths: typing.List[Path] = []
        enemyPaths: typing.List[Path] = []

        for friendlyMove, enemyMove in result.expected_best_moves:
            self.extend_interspersed_path_moves(friendlyPaths, friendlyMove)
            self.extend_interspersed_path_moves(enemyPaths, enemyMove)

        friendlyPath: Path | None = None
        enemyPath: Path | None = None
        i = 0
        for path in friendlyPaths:
            if result.expected_best_moves[0][0] is not None and path.start.tile == result.expected_best_moves[0][0].source:
                friendlyPath = path
            else:
                self.viewInfo.color_path(PathColorer(path, 15, max(0, 255 - 40 * i), 105, max(50, 160 - 20 * i)))
            i += 1
        i = 0
        for path in enemyPaths:
            if result.expected_best_moves[0][1] is not None and path.start.tile == result.expected_best_moves[0][1].source:
                enemyPath = path
            else:
                self.viewInfo.color_path(PathColorer(path, 105, 0, max(0, 255 - 40 * i), max(50, 160 - 20 * i)))
            i += 1

        # sometimes being afk is the optimal move, in which case these paths may have no moves
        if friendlyPath is None or friendlyPath.length == 0:
            friendlyPath = None
        else:
            self.viewInfo.color_path(PathColorer(friendlyPath, 40, 255, 165, 255))

        if enemyPath is None or enemyPath.length == 0:
            enemyPath = None
        else:
            self.viewInfo.color_path(PathColorer(enemyPath, 175, 0, 255, 255))

        if len(result.expected_best_moves) > 0:
            if result.expected_best_moves[0][0] is None:
                friendlyPath = None
            if result.expected_best_moves[0][1] is None:
                enemyPath = None

        return friendlyPath, enemyPath

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
                    logging.info(
                        f"Switched targets from {self.targetingArmy.toString()} to {str(army)} because it is a different army now?")
                    self.targetingArmy = army
                else:
                    logging.info(
                        f"Stopped targeting Army {self.targetingArmy.toString()} because its tile is owned by the wrong player in armyTracker now")
                    self.targetingArmy = None
        else:
            self.targetingArmy = None
            logging.info(
                f"Stopped targeting Army {str(self.targetingArmy)} because it no longer exists in armyTracker.armies")

        if not self.targetingArmy:
            return None

        enArmyDist = self.distance_from_general(self.targetingArmy.tile)
        armyStillInRange = enArmyDist < self.distance_from_opp(self.targetingArmy.tile) + 2 or self.is_tile_in_friendly_territory(self.targetingArmy.tile)
        if armyStillInRange and self.should_kill(self.targetingArmy.tile):
            forceKill = enArmyDist <= 4
            path = self.kill_army(self.targetingArmy, allowGeneral=True, allowWorthPathKillCheck=not forceKill)
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
                f"Stopped targeting Army {self.targetingArmy.toString()} due to armyStillInRange {armyStillInRange} or should_kill() returned false.")
            self.targetingArmy = None

        return None

    def try_find_counter_army_scrim_path_killpath(
            self,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> Path | None:
        path, simResult = self.try_find_counter_army_scrim_path_kill(threatPath, allowGeneral=allowGeneral, forceEnemyTowardsGeneral=forceEnemyTowardsGeneral)
        return path

    def try_find_counter_army_scrim_path_kill(
            self,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> typing.Tuple[Path | None, ArmySimResult | None]:
        if threatPath.start.tile.army < 4:
            logging.info('fuck off, dont try to scrim against tiny tiles idiot')
            return None, None
        friendlyPath, simResult = self.try_find_counter_army_scrim_path(threatPath, allowGeneral, forceEnemyTowardsGeneral=forceEnemyTowardsGeneral)
        if simResult is not None and friendlyPath is not None:
            armiesIntercept = simResult.best_result_state.kills_all_enemy_armies

            if friendlyPath is not None and armiesIntercept and not simResult.best_result_state.captured_by_enemy:
                self.info(f'CnASPaK EVAL {str(simResult)}: {str(friendlyPath)}')
                self.targetingArmy = self.get_army_at(threatPath.start.tile)
                return friendlyPath, simResult

        return None, None

    def try_find_counter_army_scrim_path(
            self,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
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
        threatArmy = self.get_army_at(threatTile)
        threatArmy.expectedPath = threatPath

        largeTilesNearTarget = self.find_large_tiles_near(
            fromTiles = threatPath.tileList[0:3],
            distance=self.engine_army_nearby_tiles_range,
            limit=self.engine_mcts_scrim_armies_per_player_limit,
            forPlayer=self.general.player,
            allowGeneral=allowGeneral,
            addlFilterFunc=lambda t, dist: self.distance_from_general(t) < threatDist + 1,
            minArmy=max(3, min(15, threatPath.value // 2))
        )

        bestPath: Path | None = None
        bestSimRes: ArmySimResult | None = None
        if not self.engine_use_mcts:
            for largeTile in largeTilesNearTarget:
                if largeTile in threatPath.tileSet and largeTile.army < threatPath.value:
                    continue
                with self.perf_timer.begin_move_event(f'BfScr {str(largeTile)}@{str(threatTile)}'):
                    friendlyPath, enemyPath, simResult = self.get_army_scrim_paths(largeTile, enemyArmyTile=threatTile, enemyCannotMoveAway=True)
                if bestSimRes is None or bestSimRes.best_result_state.calculate_value_int() < simResult.best_result_state.calculate_value_int():
                    bestPath = friendlyPath
                    bestSimRes = simResult
        elif len(largeTilesNearTarget) > 0:
            enTiles = self.find_large_tiles_near(
                fromTiles=threatPath.tileList,
                distance=self.engine_army_nearby_tiles_range,
                forPlayer=threatArmy.player,
                allowGeneral=True,
                limit=self.engine_mcts_scrim_armies_per_player_limit,
                minArmy=3,
            )

            frArmies: typing.List[Army] = []
            enArmies: typing.List[Army] = []
            for frTile in largeTilesNearTarget:
                frArmies.append(self.get_army_at(frTile))
                self.viewInfo.add_targeted_tile(frTile, TargetStyle.GOLD)

            for enTile in enTiles:
                enArmies.append(self.get_army_at(enTile))
                self.viewInfo.add_targeted_tile(enTile, TargetStyle.PURPLE)

            with self.perf_timer.begin_move_event(f'Scr {"+".join([str(largeTile) for largeTile in largeTilesNearTarget])}@{"+".join([str(enTile) for enTile in enTiles])}'):
                simResult = self.get_armies_scrim_result(
                    frArmies,
                    enArmies,
                    enemyCannotMoveAway=forceEnemyTowardsGeneral,
                    # enemyHasKillThreat=True,
                    time_limit=0.07)

                friendlyPath, enemyPath = self.extract_engine_result_paths_and_render_sim_moves(simResult)

            if bestSimRes is None:
                bestPath = friendlyPath
                bestSimRes = simResult

        if len(largeTilesNearTarget) == 0:
            logging.info(f'No large tiles in range of {str(threatTile)} :/')

        return bestPath, bestSimRes

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

    def check_for_army_movement_scrims(self, econCutoff=2.0) -> Move | None:
        curScrim = 0
        cutoff = 3

        bestScrimPath: Path | None = None
        bestScrim: ArmySimResult | None = None

        # TODO include nearbies, drop cutoff, etc
        for tile in sorted(self.armies_moved_this_turn, key=lambda t: t.army, reverse=True):
            # if tile.player == self.general.player:
            #     self.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.GREEN)
            # elif tile.player != self.targetPlayer:
            #     self.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.GOLD)

            if tile.player == self.targetPlayer:
                # self.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.RED)
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
                            and (bestScrimPath is None or bestScrim.best_result_state.calculate_value_int() < simResult.best_result_state.calculate_value_int()):
                        self.info(f'new best scrim @ {str(tile)} {simResult.net_economy_differential:+0.1f} ({str(simResult)}) {str(friendlyPath)}')
                        bestScrimPath = friendlyPath
                        bestScrim = simResult
                else:
                    self.next_scrimming_army_tile = None

                curScrim += 1
                # attempt scrim intercept? :)
                army = self.get_army_at(tile)
                with self.perf_timer.begin_move_event(f'try scrim @{army.name} {str(tile)}'):
                    if army.expectedPath is None:
                        targets = self._map.players[self.general.player].cities.copy()
                        targets.append(self.general)
                        if self.teammate_general is not None:
                            targets.append(self.teammate_general)
                            targets.extend(self._map.players[self.teammate].cities)
                        army.expectedPath = self.get_path_to_targets(
                            targets,
                            0.1,
                            preferNeutral=False,
                            fromTile=tile)
                        self.viewInfo.addAdditionalInfoLine(f'predict army {army.name} path {str(army.expectedPath)}')

                    path, scrimResult = self.try_find_counter_army_scrim_path(army.expectedPath, allowGeneral=True)
                    if path is not None and scrimResult is not None:
                        if scrimResult.best_result_state.captured_by_enemy:
                            self.viewInfo.addAdditionalInfoLine(f'scrim says cap by enemy in {str(scrimResult.best_result_state)} @{army.name} {str(tile)} lol')
                        elif (bestScrimPath is None
                              or bestScrim.best_result_state.calculate_value_int() < scrimResult.best_result_state.calculate_value_int()):
                            if scrimResult.net_economy_differential < 0:
                                self.viewInfo.addAdditionalInfoLine(f'scrim @ {str(tile)} bad result, {str(scrimResult)} including anyway as new best scrim')
                            else:
                                self.info(
                                    f'new best scrim @ {str(tile)} {scrimResult.net_economy_differential:+.1f} ({str(scrimResult)}) {str(path)}')
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
        #                 and (bestScrimPath is None or bestScrim.best_result_state.calculate_value_int() < simResult.best_result_state.calculate_value_int()):
        #             bestScrimPath = friendlyPath
        #             bestScrim = simResult
        # else:
        #     self.next_scrimming_army_tile = None

        if bestScrimPath is not None and bestScrim is not None and bestScrim.net_economy_differential > econCutoff:
            self.info(f'Scrim cont ({str(bestScrim)}) {str(bestScrimPath)}')

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

    def check_for_danger_tile_moves(self) -> Move | None:
        dangerTiles = self.get_danger_tiles()
        if len(dangerTiles) == 0 or self.all_in_counter > 15:
            return None

        for tile in dangerTiles:
            self.viewInfo.add_targeted_tile(tile, TargetStyle.RED)
            negTiles = []
            if self.curPath is not None:
                negTiles = [tile for tile in self.curPath.tileSet]
            armyToSearch = self.get_target_army_inc_adjacent_enemy(tile)
            killPath = SearchUtils.dest_breadth_first_target(
                self._map,
                [tile],
                armyToSearch,
                0.1,
                6,
                negTiles,
                searchingPlayer=self.general.player,
                dontEvacCities=False)

            if killPath is None:
                continue

            move = self.get_first_path_move(killPath)
            if self.is_move_safe_valid(move):
                if self.detect_repetition(move, 4, 2):
                    self.info(
                        f"Danger tile kill resulted in repetitions, fuck it. {str(tile)} {str(killPath)}")
                    return None

                self.info(
                    f"Depth {killPath.length} dest bfs kill on danger tile {str(tile)} {str(killPath)}")
                self.targetingArmy = self.get_army_at(tile)
                return move
    #
    # def try_scrim_against_threat_with_largest_pruned_gather_node(
    #         self,
    #         threats: typing.List[ThreatObj]
    # ):
    #     maxNode: typing.List[GatherTreeNode | None] = [None]
    #
    #     def largestGatherTreeNodeFunc(node: GatherTreeNode):
    #         if node.tile.player == self.general.player and (
    #                 maxNode[0] is None or maxNode[0].tile.army < node.tile.army):
    #             maxNode[0] = node
    #
    #     GatherUtils.iterate_tree_nodes(pruned, largestGatherTreeNodeFunc)
    #
    #     largestGatherTile = gatherMove.source
    #     if maxNode[0] is not None:
    #         largestGatherTile = maxNode[0].tile
    #
    #     threatTile = threat.path.start.tile
    #
    #     # check for ArMyEnGiNe scrim results
    #     inRangeForScrimGen = self.is_tile_in_range_from(
    #         largestGatherTile,
    #         self.general,
    #         threat.turns + 1,
    #         threat.turns - 8)
    #     inRangeForScrim = self.is_tile_in_range_from(
    #         largestGatherTile,
    #         threatTile,
    #         threat.turns + 5,
    #         threat.turns - 5)
    #     goodInterceptCandidate = largestGatherTile.army > threatTile.army - threat.turns * 2 and largestGatherTile.army > 30
    #     if goodInterceptCandidate and inRangeForScrim and inRangeForScrimGen:
    #         with self.perf_timer.begin_move_event(f'defense army scrim @ {str(threatTile)}'):
    #             scrimMove = self.get_army_scrim_move(
    #                 largestGatherTile,
    #                 threatTile,
    #                 friendlyHasKillThreat=False,
    #                 forceKeepMove=threat.turns < 3)
    #         if scrimMove is not None:
    #             self.targetingArmy = self.get_army_at(threatTile)
    #             # already logged
    #             return scrimMove
    #
    #     with self.perf_timer.begin_move_event(f'defense kill_threat @ {str(threatTile)}'):
    #         path = self.kill_threat(threat, allowGeneral=True)
    #     if path is not None:
    #         self.threat_kill_path = path
    #
    #     return None

    def get_optimal_first_25_plan_move(self) -> Move | None:
        # if self._map.turn < 50:
        #     self.send_teammate_communication("Hi I'm a bot, I try to play cooperatively! Here are the keys to the start of my messages:", cooldown=50)
        #     if self._map.turn > 3:
        #         self.send_teammate_communication("|   = You can defend yourself, I'm not helping.", cooldown=50)
        #     if self._map.turn > 7:
        #         self.send_teammate_communication("--   = You can technically defend yourself but its close, I'll prepare to help.", cooldown=50)
        #     if self._map.turn > 11:
        #         self.send_teammate_communication("---   = You will probably die without my help.", cooldown=50)

        calcedThisTurn = False
        distSource = [self.general]
        if self.targetPlayerExpectedGeneralLocation is not None:
            distSource = [self.targetPlayerExpectedGeneralLocation]
        distMap = SearchUtils.build_distance_map(self._map, distSource)

        if self._map.is_2v2:
            for teammate in self._map.teammates:
                teammateDistances = SearchUtils.build_distance_map(self._map, [self._map.generals[teammate]])
                for x in range(self._map.cols):
                    for y in range(self._map.rows):
                        teammateDistances[x][y] = 250 // (teammateDistances[x][y] + 6) + distMap[x][y]

                distMap = teammateDistances

        if self.expand_plan is None or len(self.expand_plan.plan_paths) == 0:
            with self.perf_timer.begin_move_event('optimize_first_25'):
                calcedThisTurn = True
                self.expand_plan = EarlyExpandUtils.optimize_first_25(self._map, self.general, distMap)
                while len(self.expand_plan.plan_paths) > 0 and self.expand_plan.plan_paths[0] is None:
                    self.expand_plan.plan_paths.pop(0)
                if self._map.turn < 50:
                    self.send_teammate_communication("I'm planning my start expand here, try to avoid these pinged tiles.", cooldown=50)

        r = 255
        for plan in self.expand_plan.plan_paths:
            r -= 25

            if plan is None:
                continue

            self.viewInfo.color_path(
                PathColorer(plan.clone(), r, 50, 50, alpha=r, alphaDecreaseRate=5, alphaMinimum=100))

            if (calcedThisTurn or self._map.turn % 10 == 0) and not self._map.turn > 41:
                self.send_teammate_path_ping(plan)

        if self.expand_plan.launch_turn > self._map.turn:
            self.info(
                f"Expand plan ({self.expand_plan.tile_captures}) isn't ready to launch yet, launch turn {self.expand_plan.launch_turn}")
            return None

        if not calcedThisTurn and not SearchUtils.any_where(self.player.tiles, lambda tile: not tile.isGeneral and tile.army > 1):
            self.expand_plan.tile_captures = EarlyExpandUtils.get_start_expand_value(
                    self._map,
                    self.general,
                    self.general.army,
                    self._map.turn,
                    self.expand_plan.plan_paths,
                    noLog=False)

        if len(self.expand_plan.plan_paths) > 0:
            countNone = 0
            for p in self.expand_plan.plan_paths:
                if p is not None:
                    break
                countNone += 1

            curPath = self.expand_plan.plan_paths[0]
            if curPath is None:
                self.info(
                    f'Expand plan {self.expand_plan.tile_captures} no-opped until turn {countNone + self._map.turn} :)')
                self.expand_plan.plan_paths.pop(0)
                return None

            move = self.get_first_path_move(curPath)
            self.info(f'Expand plan {self.expand_plan.tile_captures} path move {str(move)}')

            collidedWithEnemyAndWastingArmy = move.source.player != move.dest.player and move.dest.player != -1 and move.source.army - 1 <= move.dest.army or move.dest.player in self._map.teammates

            if collidedWithEnemyAndWastingArmy and move.source.player == self.general.player:
                # if tiles > 2 we either prevent them from continuing their expand OR we cap the tile they just vacate, depending who loses the tiebreak
                collisionCapsOrPreventsEnemy = move.source.army == move.dest.army and move.source.army > 2 and move.dest.player not in self._map.teammates
                if not collisionCapsOrPreventsEnemy:
                    newPath = self.attempt_first_25_collision_reroute(curPath, move, distMap)
                    if newPath is None:
                        # self.expand_plan = None

                        bMap = self.board_analysis.intergeneral_analysis.bMap
                        self.board_analysis.intergeneral_analysis.bMap = distMap
                        expansionNegatives = set()
                        if self.teammate_general is not None:
                            expansionNegatives.update(self._map.players[self.teammate_general.player].tiles)
                        path, otherPaths = ExpandUtils.get_optimal_expansion(
                            self._map,
                            self.general.player,
                            self.targetPlayer,
                            50 - self._map.turn,
                            self.board_analysis,
                            self.territories.territoryMap,
                            negativeTiles=expansionNegatives,
                            viewInfo=self.viewInfo
                        )

                        self.board_analysis.intergeneral_analysis.bMap = bMap

                        if path is not None:
                            self.info(f'F25 Exp collided at {str(move.dest.tile)}, falling back to EXP {str(path)}')
                            return self.get_first_path_move(path)

                        self.info(f'F25 Exp collided at {str(move.dest.tile)}, no alternative found. No-opping')
                        return None

                    self.viewInfo.addAdditionalInfoLine(
                        f'F25 Exp collided at {str(move.dest.tile)}, capping {str(newPath)} instead.')
                    move = self.get_first_path_move(newPath)
                    curPath = newPath
                else:
                    self.info(
                        f'F25 Exp collided at {str(move.dest.tile)}, continuing because collisionCapsOrPreventsEnemy.')

            curPath.made_move()
            if curPath.length == 0:
                self.expand_plan.plan_paths.pop(0)

            return move
        return None

    def look_for_ffa_turtle_move(self) -> Move | None:
        """

        @return:
        """
        # consider not drawing attention to ourselves by camping FFA for an extra cycle
        # consider: NO leaf moves, gather 100% of tiles and take neut city; calc if possible?
        haveSeenOtherPlayer: bool = False
        neutCity: Tile | None = None
        nearEdgeOfMap: bool = self.get_distance_from_board_center(self.general, center_ratio=0.25) > 5

        if not neutCity or haveSeenOtherPlayer:
            return None

        remainingCycleTurns = 50 - self._map.turn % 50
        # potentialGenBonus = self._map.players[self.general.player].cityCount *
        potentialGenBonus = remainingCycleTurns // 2
        sumArmy = self.sum_player_army_near_tile(neutCity, distance=100, player=self.general.player)
        if sumArmy + potentialGenBonus - 3 > neutCity.army:
            path, move = self.capture_cities(negativeTiles=set(), forceNeutralCapture=True)
            if move is not None:
                self.info(f'AM I NOT TURTLEY ENOUGH FOR THE TURTLE CLUB? {str(move)}')
                return move
            if path is not None:
                self.info(f'AM I NOT TURTLEY ENOUGH FOR THE TURTLE CLUB? {str(path)}')
                return self.get_first_path_move(path)

        return None

    def plan_city_capture(
            self,
            targetCity: Tile,
            cityGatherPath: Path,
            allowGather: bool,
            targetKillArmy: int,
            targetGatherArmy: int,
            killSearchDist: int,
            gatherMaxDuration: int,
            negativeTiles: typing.Set[Tile],
    ) -> typing.Tuple[Path | None, Move | None]:
        """

        @param targetCity:
        @param cityGatherPath:
        @param allowGather:
        @param targetKillArmy: The amount of EXTRA army to kill with. 0 means exact capture.
        @param targetGatherArmy: The amount of EXTRA army to kill with. 0 means exact capture.
        @param killSearchDist: How many tiles away to search for a raw kill.
        Must be greater than or equal to path.length, anything smaller than path.length will be replaced by path.length.
        Shorten the path over shortening the killSearchDist.
        @param gatherMaxDuration: Caps the amount of turns the gather can be computed.
        Note the actual kill will be pruned down to the min number of turns to capture the city.
        @param negativeTiles:
        @return:
        """
        if targetGatherArmy < targetKillArmy + targetCity.army:
            raise AssertionError(f'You cant gather less army {targetGatherArmy} to a city than the kill requirement {targetKillArmy} or the kill requirement will never fire and you will gather-loop.')

        targetKillArmy += 1
        targetGatherArmy += 1

        if cityGatherPath.length > killSearchDist:
            killSearchDist = cityGatherPath.length

        if targetCity in negativeTiles:
            negativeTiles = set()
        else:
            negativeTiles = negativeTiles.copy()
            # negativeTiles.discard(targetCity)

        potentialThreatNegs = self.get_potential_threat_movement_negatives(targetCity)
        negativeTiles.update(potentialThreatNegs)

        addlIncrementing = SearchUtils.count(targetCity.adjacents, lambda tile: tile.isCity and self._map.is_tile_enemy(tile))
        # # TODO replace with stateful 'strategy' plan for the city capture...
        # incrementingAdjuster = ((self._map.turn % 16) // 2) * addlIncrementing
        # targetKillArmy += incrementingAdjuster

        logging.info(
            f"Searching for city kill on {str(targetCity)} in {killSearchDist} turns with targetArmy {targetKillArmy}...")
        # TODO make a new method for finding extra-army-falloffs so that we capture a city RIGHT NEXT to an army with very little extra, but the further the found 'path' gets the more of the 'extra army requirement' gets enforced.
        killPath = SearchUtils.dest_breadth_first_target(
            self._map,
            [targetCity],
            targetArmy=targetKillArmy,  # TODO good lord fix the 0.5 increment bug...
            maxTime=0.03,
            maxDepth=killSearchDist,
            noNeutralCities=True,
            negativeTiles=negativeTiles,
            searchingPlayer=self.general.player,
            additionalIncrement=addlIncrementing / 2)

        if targetCity.player >= 0:
            altKillArmy = 1 + self.sum_enemy_army_near_tile(targetCity, distance=1)
            altKillPath = SearchUtils.dest_breadth_first_target(
                self._map,
                [targetCity],
                targetArmy=altKillArmy,
                maxTime=0.03,
                maxDepth=3,
                noNeutralCities=True,
                negativeTiles=negativeTiles,
                searchingPlayer=self.general.player)
            if altKillPath is not None and (killPath is None or altKillPath.length <= killPath.length // 2):
                if killPath is not None:
                    self.info(f'Using short enCity cap len {altKillPath.length} over larger len {killPath.length}')
                killPath = altKillPath

        # killPath = SearchUtils.dest_breadth_first_target(self._map, [target], targetArmy, 0.1, searchDist, negativeTiles, dontEvacCities=True)
        if killPath is not None:
            logging.info(
                f"found depth {killPath.length} dest bfs kill on Neutral or Enemy city {targetCity.x},{targetCity.y} \n{str(killPath)}")
            self.info(f"City killpath {targetCity.x},{targetCity.y}  setting GatherTreeNodes to None")
            self.viewInfo.evaluatedGrid[targetCity.x][targetCity.y] = 300
            self.gatherNodes = None
            addlArmy = 0
            if targetCity.player != -1:
                addlArmy += killPath.length
            if addlIncrementing > 0:
                addlArmy += killPath.length
            killPath.start.move_half = self.should_kill_path_move_half(killPath, targetKillArmy + addlArmy)
            return killPath, None

        if not allowGather:
            return None, None

        # reduce the necessary gather army by the amount on the start nodes.
        armyAlreadyPrepped = 0
        for tile in cityGatherPath.tileList:
            if self._map.is_player_on_team_with(tile.player, self.general.player):
                armyAlreadyPrepped += tile.army - 1
            elif not tile.isCity:
                armyAlreadyPrepped -= tile.army + 1
        targetGatherArmy -= armyAlreadyPrepped

        # TODO if neutral city, prioritize NOT pulling any army off of the main attack paths,
        #  abandon neut gathers if it would weaken us substantially
        with self.perf_timer.begin_move_event(f'Capture City gath to {str(cityGatherPath.tileList)}'):
            # gatherDist = (gatherDuration - self._map.turn % gatherDuration)
            gatherDist = gatherMaxDuration  # we're gonna prune anyway
            negativeTiles = negativeTiles.copy()
            # negativeTiles.add(self.general)
            for t in cityGatherPath.tileList:
                self.viewInfo.add_targeted_tile(t, TargetStyle.PURPLE)

            mePlayer = self._map.players[self.general.player]

            cycleTurn = self.timings.get_turn_in_cycle(self._map.turn)
            turnsLeft = self.timings.get_turns_left_in_cycle(self._map.turn)
            notLateGame = mePlayer.tileCount < 150 and (self._map.remainingPlayers == 2 or self._map.is_2v2)
            if targetCity.isNeutral and notLateGame:
                genAlreadyInNeg = self.general in negativeTiles
                # towards the end of cycle, only gather to cities from further and further from enemy.

                offsetByNearEndOfCycle = cycleTurn // 20
                offsetByNearEndOfCycle = 0

                negativeTiles.update(self.cityAnalyzer.owned_contested_cities)
                #
                # if turnsLeft < 10:
                # negativeTiles = self.get_timing_gather_negatives_unioned(
                #     negativeTiles,
                #     additional_offset=offsetByNearEndOfCycle,
                #     forceAllowCities=True)

                if not genAlreadyInNeg and self.general in negativeTiles:
                    negativeTiles.remove(self.general)

            self.viewInfo.addAdditionalInfoLine(
                f"city gath target_tile gatherDist {gatherDist} - targetArmyGather {targetGatherArmy} (prepped {armyAlreadyPrepped}), negatives {'+'.join([str(t) for t in negativeTiles])}")

            if targetCity.player >= 0 and targetCity not in cityGatherPath.tileSet:
                addlIncrementing += 1

            move, gatherValue, gatherTurns, gatherNodes = self.get_gather_to_target_tiles(
                cityGatherPath.tileList,
                0.03,
                gatherDist,
                negativeSet=negativeTiles,
                targetArmy=targetGatherArmy,
                additionalIncrement=addlIncrementing)

            if move is not None:
                # if targetCity.player != -1:
                #     targetGatherArmy += 4 + gatherDist // 4

                if targetCity.isNeutral:
                    origPrunedTurns, origPrunedValue, prunedGatherNodes = GatherUtils.prune_mst_to_army_with_values(
                        gatherNodes,
                        targetGatherArmy,
                        self.general.player,
                        teams=MapBase.get_teams_array(self._map),
                        turn=self._map.turn,
                        additionalIncrement=addlIncrementing,
                        viewInfo=self.viewInfo if self.info_render_gather_values else None)
                    prunedTurns, prunedValue, prunedGatherNodes = GatherUtils.prune_mst_to_army_with_values(
                        prunedGatherNodes,
                        targetGatherArmy,
                        self.general.player,
                        teams=MapBase.get_teams_array(self._map),
                        turn=self._map.turn,
                        additionalIncrement=addlIncrementing,
                        viewInfo=self.viewInfo if self.info_render_gather_values else None)
                    if prunedTurns != origPrunedTurns or prunedValue != origPrunedValue:
                        self.viewInfo.addAdditionalInfoLine(f'prune to army pass 2 diff than pass 1. Turns {origPrunedTurns} vs {prunedTurns}, val {origPrunedValue} vs {prunedValue}')
                else:
                    prunedTurns, prunedValue, prunedGatherNodes = GatherUtils.prune_mst_to_max_army_per_turn_with_values(
                        gatherNodes,
                        targetGatherArmy,
                        self.general.player,
                        teams=MapBase.get_teams_array(self._map),
                        additionalIncrement = addlIncrementing,
                        viewInfo=self.viewInfo if self.info_render_gather_values else None)

                if targetCity.isNeutral and turnsLeft - prunedTurns < 10 and notLateGame:
                    # not enough time left in cycle to be worth city capture, return None.
                    self.info(
                        f"GC TOO SLOW {str(targetCity)} {str(move)} t{prunedTurns}/{gatherTurns}/{gatherDist}  prun{prunedValue + armyAlreadyPrepped}/pre{gatherValue + armyAlreadyPrepped}/req{targetGatherArmy + armyAlreadyPrepped} -proact {self.should_proactively_take_cities()}")
                    self.viewInfo.evaluatedGrid[targetCity.x][targetCity.y] = 300
                    return None, None

                move = self.get_tree_move_default(prunedGatherNodes)

                self.gatherNodes = prunedGatherNodes
                self.info(
                    f"GC {str(targetCity)} {str(move)} t{prunedTurns}/{gatherTurns}/{gatherDist}  prun{prunedValue + armyAlreadyPrepped}/pre{gatherValue + armyAlreadyPrepped}/req{targetGatherArmy + armyAlreadyPrepped} -proact {self.should_proactively_take_cities()}")
                self.viewInfo.evaluatedGrid[targetCity.x][targetCity.y] = 300
                return None, move

        return None, None

    def get_timing_gather_negatives_unioned(
            self,
            gatherNegatives: typing.Set[Tile],
            additional_offset: int = 0,
            forceAllowCities: bool = False,
    ) -> typing.Set[Tile]:
        if not forceAllowCities:
            gatherNegatives = gatherNegatives.union(self.cities_gathered_this_cycle)

        if self.is_all_in():
            return gatherNegatives

        if self.gather_include_shortest_pathway_as_negatives:
            gatherNegatives = gatherNegatives.union(self.board_analysis.intergeneral_analysis.shortestPathWay.tiles)

        armyCutoff = int(self._map.players[self.general.player].standingArmy ** 0.5)

        def foreach_func(tile: Tile):
            if tile in self.tiles_gathered_to_this_cycle:
                return

            if not self._map.is_tile_friendly(tile):
                return

            if tile.army > armyCutoff:
                return

            gatherNegatives.add(tile)

        if self.gather_include_distance_from_enemy_general_as_negatives > 0:
            ratio = self.gather_include_distance_from_enemy_general_large_map_as_negatives
            if self.targetPlayerObj.tileCount < 150:
                ratio = self.gather_include_distance_from_enemy_general_as_negatives
            excludeDist = int(self.shortest_path_to_target_player.length * ratio)

            excludeDist += additional_offset

            SearchUtils.breadth_first_foreach(
                self._map,
                [self.targetPlayerExpectedGeneralLocation],
                maxDepth=excludeDist,
                foreachFunc=foreach_func,
            )

        if self.gather_include_distance_from_enemy_TERRITORY_as_negatives > 0:
            excludeDist = self.gather_include_distance_from_enemy_TERRITORY_as_negatives + additional_offset

            startTiles = [t for t in self._map.get_all_tiles() if self.territories.territoryMap[t.x][t.y] == self.targetPlayer]

            SearchUtils.breadth_first_foreach(
                self._map,
                startTiles,
                maxDepth=excludeDist,
                foreachFunc=foreach_func,
            )

        if self.gather_include_distance_from_enemy_TILES_as_negatives > 0:
            excludeDist = self.gather_include_distance_from_enemy_TILES_as_negatives

            startTiles = [t for t in self._map.get_all_tiles() if t.player == self.targetPlayer and not self._map.is_player_on_team_with(self.territories.territoryMap[t.x][t.y], self.general.player)]

            if len(startTiles) > 0:
                SearchUtils.breadth_first_foreach(
                    self._map,
                    startTiles,
                    maxDepth=excludeDist,
                    foreachFunc=foreach_func,
                )

        return gatherNegatives

    def is_path_moving_mostly_away(self, path: Path, bMap: typing.List[typing.List[int]]):
        distSum = 0
        for tile in path.tileList:
            distSum += bMap[tile.x][tile.y]

        distAvg = distSum / path.length

        distStart = bMap[path.start.tile.x][path.start.tile.y]
        distEnd = bMap[path.tail.tile.x][path.tail.tile.y]

        doesntAverageCloserToEnemySlightly = distEnd > distStart - path.length // 4
        notHuntingNearby = distEnd > self.shortest_path_to_target_player.length // 6

        if notHuntingNearby and doesntAverageCloserToEnemySlightly and distAvg > distStart - path.length // 4:
            return True

        return False

    def check_army_out_of_play_ratio(self) -> bool:
        """
        0.0 means all army is in the core play area
        1.0 means all army is outside the core play area.
        0.5 means hella sketchy, half our army is outside the play area.
        @return:
        """

        if self._map.is_2v2 and self.teammate_general is not None:
            return False

        inPlaySum = 0
        medPlaySum = 0
        outOfPlaySum = 0
        nearOppSum = 0
        genPlayer = self._map.players[self.general.player]
        pathLen = self.shortest_path_to_target_player.length
        inPlayCutoff = pathLen + pathLen * (self.behavior_out_of_play_distance_over_shortest_ratio / 2)
        mediumRangeCutoff = pathLen + pathLen * self.behavior_out_of_play_distance_over_shortest_ratio

        for tile in genPlayer.tiles:
            genDist = self.board_analysis.intergeneral_analysis.aMap[tile.x][tile.y]
            enDist = self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y]
            if genDist > enDist * 2:
                nearOppSum += tile.army - 1
                continue
            if tile.isGeneral:
                continue

            pathWay = self.board_analysis.intergeneral_analysis.pathWayLookupMatrix[tile]
            if pathWay is None:
                self.viewInfo.addAdditionalInfoLine(f'tile {str(tile)} had no pathway...? genDist{genDist} enDist{enDist}')

            if pathWay is not None and pathWay.distance <= inPlayCutoff:
                inPlaySum += tile.army - 1
            elif pathWay is not None and pathWay.distance < mediumRangeCutoff:
                medPlaySum += tile.army - 1
            else:
                outOfPlaySum += tile.army - 1

        total = medPlaySum + inPlaySum + outOfPlaySum + nearOppSum
        if total == 0:
            return False

        # once we have lots of army this becomes harder, subtract some square root of our army - 100 or something
        hugeGameOffset = 0
        realTotal = total
        incMedium = medPlaySum // 2
        if total > 90:
            hugeGameOffset = int((total - 90) ** 0.8)
            total = 90 + hugeGameOffset
            incMedium = 0

        inPlayRat = inPlaySum / total
        medPlayRat = medPlaySum / total
        outOfPlaySumFactored = outOfPlaySum - nearOppSum // 3 + incMedium
        outOfPlayRat = (outOfPlaySumFactored) / total

        aboveOutOfPlay = outOfPlayRat > self.behavior_out_of_play_defense_threshold

        self.viewInfo.addAdditionalInfoLine(f'out-of-play {aboveOutOfPlay} {total:.0f}@dist{mediumRangeCutoff:.1f}: OUT{outOfPlaySum}-OPP{nearOppSum}+MF{incMedium}({outOfPlayRat:.2f}>{self.behavior_out_of_play_defense_threshold:.2f}), IN{inPlaySum}({inPlayRat:.2f}), MED{medPlaySum}({medPlayRat:.2f}), Tot{total} ogTot{realTotal} (huge {hugeGameOffset})')

        return aboveOutOfPlay

    def should_allow_neutral_city_capture(
            self,
            targetPlayer: Player,
            genPlayer: Player,
            forceNeutralCapture: bool
    ) -> bool:
        if self.currently_forcing_out_of_play_gathers:
            return False

        if self.is_blocking_neutral_city_captures:
            return False

        # we now take cities proactively?
        proactivelyTakeCity = self.should_proactively_take_cities() or forceNeutralCapture
        safeFromThreat = self.threat is None or self.threat.threatType != ThreatType.Kill or self.threat.threatValue <= self.threat.turns or (self.threat.turns > 6 and not self.threat.path.start.tile.visible)
        if not safeFromThreat:
            self.viewInfo.addAdditionalInfoLine("Will not proactively take cities due to the existing threat....")
            proactivelyTakeCity = False
            if self.threat.threatValue > 20:
                forceNeutralCapture = False
                self.force_city_take = False

        forceCityOffset = 0
        if self.force_city_take:
            forceCityOffset = 1

        targCities = 1
        if targetPlayer is not None:
            targCities = targetPlayer.cityCount

        cityTakeThreshold = targCities + forceCityOffset

        logging.info(f'force_city_take {self.force_city_take}, cityTakeThreshold {cityTakeThreshold}, targCities {targCities}')
        if self.targetPlayer == -1 or self._map.remainingPlayers <= 3 or self.force_city_take:
            if (
                targetPlayer is None
                or (
                    (genPlayer.cityCount < cityTakeThreshold or proactivelyTakeCity)
                    and safeFromThreat
                )
            ):
                logging.info("Didn't skip neut cities.")
                # ? move this logic into proactivelytakecities?
                sqrtFactor = 10
                # if (targetPlayer is None or player.cityCount < cityTakeThreshold) and math.sqrt(player.standingArmy) * sqrtFactor > largestTile.army\
                if forceNeutralCapture or targetPlayer is None or genPlayer.cityCount < cityTakeThreshold or self.force_city_take:
                    return True
                else:
                    logging.info(
                        f"We shouldn't be taking more neutral cities, we're too defenseless right now.")
            else:
                logging.info(
                    f"Skipped neut cities. in_gather_split(self._map.turn) {self.timings.in_gather_split(self._map.turn)} and (player.cityCount < targetPlayer.cityCount {genPlayer.cityCount < targetPlayer.cityCount} or proactivelyTakeCity {proactivelyTakeCity})")
        return False

    def find_hacky_path_to_find_target_player_spawn_approx(self, minSpawnDist: int):
        prios = self.find_expected_1v1_general_location_on_undiscovered_map(
            undiscoveredCounterDepth=10,
            minSpawnDistance=minSpawnDist)

        def value_func(tile: Tile, prioObj):
            (realDist, negScore, dist, lastTile) = prioObj

            if realDist < minSpawnDist:
                return None

            score = 0 - negScore
            scoreOverDist = score / (realDist * dist + 1)
            return (scoreOverDist, 0 - realDist)

        def prio_func(tile: Tile, prioObj):
            (fakeDist, negScore, dist, lastTile) = prioObj
            if tile.player == self.targetPlayer:
                negScore -= 200
            if tile.visible:
                fakeDist += 2
            else:
                negScore -= 100
            if lastTile is not None and not lastTile.visible and tile.visible:
                negScore += 10000
            undiscScore = prios[tile.x][tile.y]
            negScore -= undiscScore
            negScore += 5
            realDist = self.distance_from_general(tile)
            return realDist, negScore, dist + 1, tile

        def skip_func(tile: Tile, prioObj):
            return tile.visible and tile.player != self.targetPlayer

        startDict = { }
        for targetTile in self.targetPlayerObj.tiles:
            startDict[targetTile] = ((self.distance_from_general(targetTile), 0, 0, None), 0)

        path = SearchUtils.breadth_first_dynamic_max(
            self._map,
            startDict,
            valueFunc=value_func,
            maxTime=0.1,
            maxTurns=45,
            maxDepth=100,
            noNeutralCities=True,
            priorityFunc=prio_func,
            skipFunc=skip_func
            # useGlobalVisitedSet=False
        )

        self.viewInfo.addAdditionalInfoLine(f'hacky path {str(path)}...?')

        self.viewInfo.color_path(PathColorer(path, 255, 0, 0))
        if path is not None:
            return path.tail.tile

        return None

    def should_rapid_capture_neutral_cities(self) -> bool:
        if self.targetPlayer == -1:
            return True

        if self._map.is_2v2 and self.teammate_general is not None:
            seenOtherPlayer = False
            for player in self._map.players:
                if not self._map.is_player_on_team_with(player.index, self.general.player):
                    if len(player.tiles) > 0:
                        seenOtherPlayer = True

            if not seenOtherPlayer:
                return True
            return False

        mePlayer = self._map.players[self.general.player]
        targPlayer = self._map.players[self.targetPlayer]

        # if self._map.remainingPlayers == 2 and mePlayer.cityCount +

        haveLotsOfExcessArmy = mePlayer.standingArmy > mePlayer.tileCount * 2
        aheadOfOppArmyByHundreds = mePlayer.standingArmy > targPlayer.standingArmy + 100
        notWinningEcon = not self.winning_on_economy(byRatio=0.8, cityValue=40)
        hasDoubleEcon = targPlayer.cityCount + 2 < mePlayer.cityCount // 2 and not self._map.remainingPlayers > 3
        hasTripleEcon = targPlayer.cityCount + 1 < mePlayer.cityCount // 3
        if self._map.is_2v2:
            hasDoubleEcon = self.winning_on_economy(2.0, cityValue=100)
            hasTripleEcon = self.winning_on_economy(3.0, cityValue=100)

        # TODO track how much the opp has explored, the difference between our tile count BFSed from enemy territory to general distance - the amount they've seen is how much buffer time we probably have.
        numberOfTilesEnemyNeedsToExploreToFindUsAvg = mePlayer.tileCount // 2 - 50
        if targPlayer.aggression_factor < 20:
            # then this enemy isn't attacking us, city-up
            numberOfTilesEnemyNeedsToExploreToFindUsAvg = mePlayer.tileCount // 2

        if (
                not self.all_in_army_advantage
                and (
                        (mePlayer.tileCount > 200 and mePlayer.standingArmy > mePlayer.tileCount * 3)
                        or (mePlayer.tileCount > 150 and mePlayer.standingArmy > mePlayer.tileCount * 4)
                        or (mePlayer.tileCount > 110 and mePlayer.standingArmy > mePlayer.tileCount * 5)
                )
                and mePlayer.standingArmy > targPlayer.standingArmy - numberOfTilesEnemyNeedsToExploreToFindUsAvg
                and not targPlayer.knowsKingLocation
                and (not hasDoubleEcon or targPlayer.aggression_factor < 30 and not hasTripleEcon)
        ):
            self.viewInfo.addAdditionalInfoLine(f'RAPID CITY EXPAND due to sheer volume of tiles/army')
            self.is_rapid_capturing_neut_cities = True
            return True

        haveMinimumArmyAdv = mePlayer.standingArmy > targPlayer.standingArmy * 0.8 or targPlayer.aggression_factor < 150
        haveAchievedEconomicDominance = self.winning_on_economy(byRatio=1.45, cityValue=1000)

        if (
            1 == 1
            # and mePlayer.tileCount > 120
            and (
                (aheadOfOppArmyByHundreds and notWinningEcon and targPlayer.aggression_factor < 200)
                or (haveLotsOfExcessArmy and self.is_rapid_capturing_neut_cities)
            )
            and not targPlayer.knowsKingLocation
            and not hasDoubleEcon
        ):
            if not haveMinimumArmyAdv:
                self.viewInfo.addAdditionalInfoLine(f'Ceasing rapid city expand due to sketchy army amount territory')
            elif haveAchievedEconomicDominance:
                self.viewInfo.addAdditionalInfoLine(f'Ceasing rapid city expand due to economic dominance achieved')
            else:
                self.is_rapid_capturing_neut_cities = True
                return True

        self.is_rapid_capturing_neut_cities = False
        return False

    def find_rapid_city_path(self) -> Path | None:
        if not self.should_rapid_capture_neutral_cities():
            return None

        longDistSearchCities = []
        for neutCity in self.cityAnalyzer.city_scores:
            if not neutCity.discovered:
                continue  # don't try to rapid expand into fictitious cities
            if self.sum_enemy_army_near_tile(neutCity, 2) == 0 and self.count_enemy_territory_near_tile(neutCity, 3) == 0:
                longDistSearchCities.append(neutCity)

        shortDistSearchCities = []
        if self.targetPlayerObj is not None and self.targetPlayerObj.aggression_factor > 200:
            for enCity in self.cityAnalyzer.enemy_city_scores:
                if not enCity.discovered:
                    continue  # don't try to rapid expand into fictitious cities
                shortDistSearchCities.append(enCity)
                if not self.is_tile_in_enemy_territory(enCity):
                    longDistSearchCities.append(enCity)

        if len(shortDistSearchCities) > 0:
            quickestKillPath = SearchUtils.dest_breadth_first_target(self._map, shortDistSearchCities, maxDepth=4)
            if quickestKillPath is not None:
                self.info(f'RAPID CITY EN EXPAND DUE TO should_rapid_capture_neutral_cities')
                return quickestKillPath

        if len(longDistSearchCities) > 0:
            quickestKillPath = SearchUtils.dest_breadth_first_target(self._map, longDistSearchCities, maxDepth=9)
            if quickestKillPath is not None:
                self.info(f'RAPID CITY EXPAND DUE TO should_rapid_capture_neutral_cities')
                return quickestKillPath

        return None

    def get_remaining_move_time(self) -> float:
        used = time.perf_counter() - self.perf_timer.current_move.move_beginning_time
        moveCycleTime = 0.5
        latencyBuffer = 0.15
        allowedLatest = moveCycleTime - latencyBuffer
        return allowedLatest - used

    def should_abandon_king_defense(self) -> bool:
        return self._map.remainingPlayers == 2 and not self.winning_on_economy(byRatio=self.behavior_losing_on_economy_skip_defense_threshold)

    def block_neutral_captures(self, reason: str = ''):
        if self.curPath and self.curPath.tail.tile.isCity and self.curPath.tail.tile.isNeutral:
            targetNeutCity = self.curPath.tail.tile
            if self.is_blocking_neutral_city_captures:
                self.info(
                    f'forcibly stopped taking neutral city {str(targetNeutCity)} {reason}')
                self.curPath = None
        logging.info(f'Preventing neutral city captures for now {reason}')
        self.is_blocking_neutral_city_captures = True

    def is_tile_in_friendly_territory(self, tile: Tile) -> bool:
        """Returns False if tile is in neutral or enemy territory. True only for player territory."""
        territory = self.get_tile_territory(tile)
        if territory == -1:
            return False
        return self.teams[territory] == self.teams[self.general.player]

    def is_tile_in_enemy_territory(self, tile: Tile) -> bool:
        """Returns True if the tile is not in neutral or friendly territory."""

        territory = self.get_tile_territory(tile)
        return territory >= 0 and territory != self.general.player and territory not in self._map.teammates

    def get_tile_territory(self, tile: Tile) -> int:
        return self.territories.territoryMap[tile.x][tile.y]

    def continue_cur_path(self, threat: ThreatObj | None, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        inc = 0
        while (
                self.curPath.start.tile.army <= 1 or self.curPath.start.tile.player != self._map.player_index) and self.curPath.start.next is not None:
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
            if source.isGeneral and not self.general_move_safe(dest):
                logging.info(
                    f"Attempting to execute path move from self.curPath?")
                # self.curPath = None
                # self.curPathPrio = -1
                # logging.info("General move in path would have violated general min army allowable. Repathing.")
                if self.general_move_safe(dest, move_half=True):
                    logging.info("General move in path would have violated general min army allowable. Moving half.")
                    move = Move(source, dest, True)
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
                                # self.curPath = killThreatPath
                                self.viewInfo.color_path(PathColorer(killThreatPath, 0, 255, 204, 255, 10, 200))
                                self.targetingArmy = self.armyTracker.armies[threat.path.start.tile]
                                return self.get_first_path_move(killThreatPath)
                        else:
                            logging.warning("Negative tiles prevented a move but there was no threat???")

                    elif self.curPath.start.next is not None and self.curPath.start.next.next is not None and self.curPath.start.tile == self.curPath.start.next.next.tile and self.curPath.start.next.tile.player == self.curPath.start.tile.player:
                        logging.info("\n\n\n~~~~~~~~~~~\nCleaned double-back from path\n~~~~~~~~~~~~~\n\n~~~\n")
                        self.curPath.made_move()
                    elif self.curPath.start.tile.player != self._map.player_index or self.curPath.start.tile.army < 2:
                        logging.info("\n\n\n~~~~~~~~~~~\nCleaned useless move from path\n~~~~~~~~~~~~~\n\n~~~\n")
                        self.curPath.made_move()
                    else:
                        cleanPath = True
                if self.curPath is not None and self.curPath.start.next is not None:
                    if self.curPath.start.tile == self.general and not self.general_move_safe(
                            self.curPath.start.next.tile, self.curPath.start.move_half):
                        self.curPath = None
                        self.curPathPrio = -1
                    else:
                        move = self.get_first_path_move(self.curPath)
                        end = time.perf_counter()
                        logging.info(f"Path Move continuation of curPath.")
                        # self.info("MAKING MOVE FROM NEW PATH CLASS! Path {}".format(self.curPath.toString()))
                        return self.move_half_on_repetition(move, 6, 3)
        self.info("path move failed...? setting curPath to none...")
        self.curPath = None
        return None

    def try_find_gather_move(
            self,
            threat: ThreatObj | None,
            defenseCriticalTileSet: typing.Set[Tile],
            leafMoves: typing.List[Move],
            needToKillTiles: typing.List[Tile],
    ) -> Move | None:
        tryGather = True
        player = self._map.players[self.general.player]
        enemyGather = False
        if (
                not self._map.remainingPlayers > 2
                and not self.winning_on_economy(byRatio=1, cityValue=0)
                and self.winning_on_army(0.95)
        ):
            logging.info("Forced enemyGather to true due to NOT winning_on_economy(by tiles only) and winning_on_army")
            enemyGather = True

        # neutralGather = len(targets) <= 2
        neutralGather = False
        turn = self._map.turn
        tiles = player.tileCount

        # TODO 2v2 calculations
        tileDeficitThreshold = self._map.players[self.targetPlayer].tileCount * 1.05
        if self.makingUpTileDeficit:
            tileDeficitThreshold = self._map.players[self.targetPlayer].tileCount * 1.15 + 8

        if (
                not self.defend_economy
                and self.distance_from_general(self.targetPlayerExpectedGeneralLocation) > 2
                and player.tileCount < tileDeficitThreshold
                and not (self.is_all_in() or self.all_in_counter > 50)
        ):
            logging.info("ayyyyyyyyyyyyyyyyyyyyyyyyy set enemyGather to True because we're behind on tiles")
            enemyGather = True
            skipFFANeutralGather = (self._map.turn > 50 and self._map.remainingPlayers > 2)
            # if not skipFFANeutralGather and (self._map.turn < 120 or self.distance_from_general(self.targetPlayerExpectedGeneralLocation) < 3):
            #    neutralGather = True
            self.makingUpTileDeficit = True
        else:
            self.makingUpTileDeficit = False

        if self.defend_economy:
            logging.info("we're playing defensively, neutralGather and enemyGather set to false...")
            neutralGather = False
            enemyGather = False
        # TODO maybe replace with optimal expand? But shouldn't be before gather anymore.
        # if (self.makingUpTileDeficit):
        #    leafMove = self.find_leaf_move(allLeaves)
        #    if (None != leafMove):
        #        self.info("doing tileDeficit leafMove stuff mannn")
        #        return leafMove

        if not tryGather:
            return None

        gathString = ""
        gathStartTime = time.perf_counter()
        gatherTargets = self.target_player_gather_targets.copy()
        # if self.launchPoints is not None:
        #     gatherTargets.update(self.launchPoints)
        gatherNegatives = defenseCriticalTileSet.copy()
        negSet = set()
        # for tile in self.largePlayerTiles:
        #    gatherNegatives.add(tile)
        if self.curPath is not None:
            negSet.add(self.curPath.start.tile)

        # De-prioritize smallish tiles that are in enemy territory from being gathered
        genPlayer = self._map.players[self.general.player]
        for tile in genPlayer.tiles:
            # if self._map.is_player_on_team_with(self.territories.territoryMap[tile.x][tile.y], self.targetPlayer) and tile.army < 8:
            if self._map.is_player_on_team_with(self.territories.territoryMap[tile.x][tile.y], self.targetPlayer):
                gatherNegatives.add(tile)
        if self.teammate_general is not None:
            allyPlayer = self._map.players[self.teammate_general.player]
            for tile in allyPlayer.tiles:
                # if self._map.is_player_on_team_with(self.territories.territoryMap[tile.x][tile.y], self.targetPlayer) and tile.army < 8:
                if self._map.is_player_on_team_with(self.territories.territoryMap[tile.x][tile.y], self.targetPlayer):
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

            shortestLength = self.shortest_path_to_target_player.length
            if not self.is_all_in() and not self.defend_economy and enemyGather and self._map.turn >= 150:
                # Add support for 'green arrows', pushing outer territory towards enemy territory.
                goodLeaves = self.board_analysis.find_flank_leaves(
                    leafMoves,
                    minAltPathCount=2,
                    maxAltLength=shortestLength + shortestLength // 3)
                for goodLeaf in goodLeaves:
                    # if goodLeaf.dest.player == self.targetPlayer:

                    self.mark_tile(goodLeaf.dest, 255)
                    # gatherTargets.add(goodLeaf.dest)
                    gatherNegatives.add(goodLeaf.dest)

            # for leaf in filter(lambda move: move.dest.army > 0 and (move.source.player == move.dest.player or move.source.army - 1 > move.dest.army), leafMoves):
            for leaf in filter(lambda move: move.dest.player == self.targetPlayer or (neutralGather and move.dest.player == -1), leafMoves):
                if (
                        not (leaf.dest.isCity and leaf.dest.player == -1)
                        and not leaf.dest in self.target_player_gather_targets
                ):
                    if leaf.dest.player != self.targetPlayer and leaf.dest.player >= 0:
                        continue
                    useTile = leaf.source
                    if leaf.dest.player == self.targetPlayer:
                        useTile = leaf.dest

                    if (
                            self.targetPlayer != -1
                            and not neutralGather
                            and (leaf.dest.player == -1 or leaf.source.player == -1)
                    ):
                        continue

                    # only gather to enemy tiles in our territory as leaves.
                    # OR to tiles that move the army closer to the conflict path
                    if (
                            self.territories.territoryMap[useTile.x][useTile.y] != self.general.player
                            and self.territories.territoryMap[useTile.x][useTile.y] not in self._map.teammates
                            and (
                                self.distance_from_target_path(leaf.source) <= self.distance_from_target_path(leaf.dest)
                                or self.distance_from_target_path(leaf.source) > self.shortest_path_to_target_player.length / 3
                            )
                    ):
                        continue

                    # if self.distance_from_target_path(useTile) > self.shortest_path_to_target_player.length / 2.5:
                    #     self.viewInfo.evaluatedGrid[useTile.x][useTile.y] += 100
                    #     continue

                    # gatherTargets.add(useTile)
                    gatherNegatives.add(useTile)
                    # TEMPORARILY GATHER TO ALL ENEMY TILES IN OUR TERRITORY?
                    ## determine whether leaf is worth expanding to
                    # counter = SearchUtils.Counter(0)
                    # def counterFunc(tile):
                    #    if (tile.player == self.targetPlayer or tile.player == -1) and not ((not tile.discovered and tile.isNotPathable) or tile.isMountain):
                    #        counter.add(1)
                    # def skipFunc(tile):
                    #    return tile.player == self.general.player or tile.isMountain or (not tile.discovered and tile.isNotPathable)
                    # SearchUtils.breadth_first_foreach(self._map, [useTile], 6, counterFunc, None, skipFunc, None, self.general.player, noLog = True)
                    # if counter.value > 2:
                    #    logging.info("leaf {} explorability {}:".format(useTile.toString(), counter.value))
                    #    leafGatherTargets.append(useTile)
                    # else:
                    #    logging.info("pruned leaf {} from gather due to explorability {}:".format(useTile.toString(), counter.value))
            logging.info("pruning leaves and stuff took {:.3f}".format(time.perf_counter() - leafPruneStartTime))
            negSet.add(self.general)

        forceGatherToEnemy = self.should_force_gather_to_enemy_tiles()

        if len(needToKillTiles) > 0 and not self.flanking:
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

                    SearchUtils.breadth_first_foreach(self._map, [tile], 2, tile_remover, None, None, noLog=True)

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
                        skipTiles=set(genPlayer.cities),
                        force=True,
                        priorityTiles=None,
                        targetTurns=targetTurns,
                        includeGatherTreeNodesThatGatherNegative=False)
                if move is not None:
                    self.curPath = None
                    self.info(
                        f"GATHER needToKill{gathString}! Gather move: {str(move)} Duration {time.perf_counter() - gathStartTime:.3f}")
                    return self.move_half_on_repetition(move, 6, 4)
                else:
                    logging.info("No needToKill gather move found")
        else:
            needToKillTiles = None

        with self.perf_timer.begin_move_event(f'Timing Gather (normal / defensive)'):
            gatherNegatives = self.get_timing_gather_negatives_unioned(gatherNegatives)

            gatherPriorities = self.get_gather_tiebreak_matrix()

            if self.currently_forcing_out_of_play_gathers:
                gathString += " +out of play"
                genPlayer = self._map.players[self.general.player]
                for tile in genPlayer.tiles:
                    if tile in self.board_analysis.core_play_area_matrix and tile not in self.tiles_gathered_to_this_cycle:
                        gatherNegatives.add(tile)

            move = self.timing_gather(
                [t for t in gatherTargets],
                gatherNegatives,
                skipTiles=None,
                force=True,
                priorityTiles=None,
                priorityMatrix=gatherPriorities)

        if move is not None:
            if move.dest.player != self.player.index and move.dest not in self.target_player_gather_targets and not self.flanking:
                self.timings.splitTurns += 1
                self.timings.launchTiming += 1

            if move.source.isCity or move.source.isGeneral:
                self.cities_gathered_this_cycle.add(move.source)

            if move.dest.isCity and move.dest.player == self.player.index and move.dest in self.cities_gathered_this_cycle:
                self.cities_gathered_this_cycle.remove(move.dest)

            self.tiles_gathered_to_this_cycle.add(move.dest)
            self.tiles_gathered_to_this_cycle.discard(move.source)

            self.curPath = None
            self.info(
                f"GATHER {gathString}! Gather move: {str(move)} Duration {time.perf_counter() - gathStartTime:.3f}")
            return self.move_half_on_repetition(move, 6, 4)
        else:
            logging.info("No gather move found")

        return None

    @staticmethod
    def render_tile_deltas_in_view_info(viewInfo: ViewInfo, map: MapBase):
        for tile in map.get_all_tiles():
            renderMore = False
            if (
                tile.delta.armyMovedHere
                or tile.delta.lostSight
                or tile.delta.gainedSight
                or tile.delta.discovered
                or tile.delta.armyDelta != 0
                or tile.delta.unexplainedDelta != 0
                # or tile.delta.imperfectArmyDelta
                or tile.delta.fromTile is not None
                or tile.delta.toTile is not None
            ):
                renderMore = True

            s = []
            if tile.delta.armyMovedHere:
                s.append('M')
            if tile.delta.imperfectArmyDelta:
                s.append('I')
            if tile.delta.lostSight:
                s.append('L')
            if tile.delta.gainedSight:
                s.append('G')
            if tile.delta.discovered:
                s.append('D')
            s.append(' ')
            viewInfo.bottomRightGridText[tile.x][tile.y] = ''.join(s)

            if tile.delta.armyDelta != 0:
                viewInfo.bottomLeftGridText[tile.x][tile.y] = f'd{tile.delta.armyDelta:+d}'
            if tile.delta.unexplainedDelta != 0:
                viewInfo.bottomMidLeftGridText[tile.x][tile.y] = f'u{tile.delta.unexplainedDelta:+d}'
            if renderMore:
                moves = ''
                if tile.delta.toTile and tile.delta.fromTile:
                    moves = f'{str(tile.delta.fromTile)}-{str(tile.delta.toTile)}'
                elif tile.delta.fromTile:
                    moves = f'<-{str(tile.delta.fromTile)}'
                elif tile.delta.toTile:
                    moves = f'->{str(tile.delta.toTile)}'
                viewInfo.topRightGridText[tile.x][tile.y] = moves
                viewInfo.midRightGridText[tile.x][tile.y] = f'{tile.delta.oldArmy}'
                if tile.delta.oldOwner != tile.delta.newOwner:
                    viewInfo.bottomMidRightGridText[tile.x][tile.y] = f'{tile.delta.oldOwner}-{tile.delta.newOwner}'

    def check_if_need_to_gather_longer_to_hold_fresh_cities(self):
        freshCityCount = 0
        sketchiestCity: Tile = self.general
        contestCity: Tile | None = None

        offset = 8

        for city in self._map.players[self.general.player].cities:
            if not self._map.is_player_on_team_with(city.delta.oldOwner, self.general.player):
                freshCityCount += 1

                nearerToUs = self.board_analysis.intergeneral_analysis.aMap[city.x][city.y] < self.board_analysis.intergeneral_analysis.bMap[city.x][city.y]
                nearerToEnemyThanSketchiest = self.board_analysis.intergeneral_analysis.bMap[city.x][city.y] < self.board_analysis.intergeneral_analysis.bMap[sketchiestCity.x][sketchiestCity.y]
                enemyTilesVisionRange = self.count_enemy_tiles_near_tile(city, 2)
                enemyTilesNear = self.count_enemy_tiles_near_tile(city, self.shortest_path_to_target_player.length // 5)
                if nearerToUs and nearerToEnemyThanSketchiest and (enemyTilesNear > 5 or enemyTilesVisionRange > 0):
                    sketchiestCity = city
                elif city.delta.oldOwner >= 0 and (contestCity is None or self.board_analysis.intergeneral_analysis.aMap[city.x][city.y] < self.board_analysis.intergeneral_analysis.aMap[contestCity.x][contestCity.y]):
                    contestCity = city

                if city.delta.oldOwner >= 0:
                    offset = 7

        earlyCycleSlightlyWinning = self.timings is not None and self.timings.get_turn_in_cycle(self._map.turn) < 15 and self.winning_on_economy(byRatio=1.05)
        heavilyWinning = self.winning_on_economy(byRatio=1.25, cityValue=50)

        if (heavilyWinning or earlyCycleSlightlyWinning) and self.all_in_city_behind and self.even_or_up_on_cities():
            self.all_in_city_behind = False
            self.allIn = False
            self.all_in_army_advantage = False

        if freshCityCount > 0 and (earlyCycleSlightlyWinning or heavilyWinning) and not self._map.remainingPlayers > 2:
            self.flanking = False
            winningEcon = self.winning_on_economy(byRatio=1.2)
            # todo need same for 2v2
            d25 = self._map.players[self.targetPlayer].delta25tiles - self._map.players[self.general.player].delta25tiles
            if d25 < 10 and self.up_on_cities():
                offset += 10
            if winningEcon and self._map.remainingPlayers == 2:
                offset += 7
            if heavilyWinning and self.winning_on_army():
                offset += 10

            if offset < 15:
                return

            self.locked_launch_point = sketchiestCity
            if contestCity is not None:
                self.locked_launch_point = contestCity
            self.recalculate_player_paths(force=True)
            curTurn = self.timings.get_turn_in_cycle(self._map.turn)
            self.timings.splitTurns = min(self.timings.cycleTurns - 8, max(curTurn + offset, self.timings.splitTurns + offset))
            self.viewInfo.addAdditionalInfoLine(f'CCAP GATH, d25 {d25}, offset {offset} winningEcon 1.2 {str(winningEcon)[0]} heavilyWinning {str(heavilyWinning)[0]}')
            self.timings.launchTiming = max(self.timings.splitTurns, self.timings.launchTiming)

    def get_scrim_cached(self, friendlyArmies: typing.List[Army], enemyArmies: typing.List[Army]) -> ArmySimResult | None:
        key = self.get_scrim_cache_key(friendlyArmies, enemyArmies)
        cachedSimResult: ArmySimResult | None = self.cached_scrims.get(key, None)
        return cachedSimResult

    def get_scrim_cache_key(self, friendlyArmies: typing.List[Army], enemyArmies: typing.List[Army]) -> str:
        sortedArmies = list(sorted(friendlyArmies, key=lambda a: a.tile))
        sortedArmies.extend(list(sorted(enemyArmies, key=lambda a: a.tile)))
        key = ''.join([str(a.tile) for a in sortedArmies])
        return key

    def find_sketchy_fog_flank_from_enemy_in_play_area(self) -> Path | None:
        """
        Hunts for a sketchy flank attack point the enemy might be inclined to abuse from a city/general,
        and returns it as a fog-only path to the enemy attack source.
        """

        launchPoints = [self.targetPlayerExpectedGeneralLocation]
        for c in self.targetPlayerObj.cities:
            if not c.discovered:
                continue
            if not self.is_tile_in_enemy_territory(c):
                continue
            launchPoints.append(c)

        distCap = self.board_analysis.inter_general_distance
        # distCap = self.board_analysis.inter_general_distance
        depth = min(25, distCap)

        distMatrix = SearchUtils.build_distance_map_matrix(self._map, [self.general])

        sketchyPath = self.find_flank_opportunity(
            targetPlayer = self.general.player,
            flankingPlayer = self.targetPlayer,
            flankPlayerLaunchPoints= launchPoints,
            depth = depth,
            targetDistMap=distMatrix,
            validEmergencePointMatrix=self.board_analysis.flank_danger_play_area_matrix)

        return sketchyPath

    def check_for_attack_launch_move(self) -> Move | None:
        if self.target_player_gather_path.value < 0 and not self.flanking:
            return None

        path = self.get_value_per_turn_subsegment(self.target_player_gather_path, 1.0, 0.25)
        origPathLength = path.length

        logging.info(f"{self.get_elapsed()} -----------\nATTACK LAUNCH ?? -------")
        # reduce the length of the path to allow for other use of the army

        targetPathLength = path.length * 4 // 9 + 1
        if self.is_all_in():
            allInPathLength = path.length * 5 // 9 + 1
            self.viewInfo.addAdditionalInfoLine(
                f"because all in, changed path length from {targetPathLength} to {allInPathLength}")
            targetPathLength = allInPathLength

        if self.flanking:
            targetPathLength = targetPathLength // 2 + 1
        #
        # if not self.targetPlayerExpectedGeneralLocation.isGeneral:
        #     targetPathLength += 2

        maxLength = 17
        if self.timings.cycleTurns > 50:
            maxLength = 34

        # never use a super long path because it leaves no time to expand.
        # This is just cutting off the attack-send path length to stop rallying
        # the attack around enemy territory to let the bot expand or whatever. This isn't modifying the real path.
        targetPathLength = min(maxLength, targetPathLength)
        path = path.get_subsegment(targetPathLength)
        if path.length == 0:
            return None

        path.calculate_value(self.general.player)
        logging.info(f"  value subsegment = {str(path)}")
        timingTurn = (self._map.turn + self.timings.offsetTurns) % self.timings.cycleTurns
        player = self._map.players[self.general.player]

        enemyGenAdj = []
        for generalAdj in self.general.adjacents:
            if self._map.is_tile_enemy(generalAdj):
                self.viewInfo.add_targeted_tile(generalAdj)
                enemyGenAdj.append(generalAdj)

        if self._map.turn >= 50 and self.timings.in_launch_split(self._map.turn) and (
                self.targetPlayer != -1 or self._map.remainingPlayers <= 2):
            pathWorth = self.get_player_army_amount_on_path(self.target_player_gather_path, self.general.player)
            inAttackWindow = timingTurn < self.timings.launchTiming + 4
            minArmy = min(player.standingArmy ** 0.9, (player.standingArmy ** 0.72) * 1.7)
            if self.flanking and pathWorth > 0:
                minArmy = 0

            self.info(
                f"  T Launch window {inAttackWindow} - minArmy {minArmy}, pathVal {path.value}, timingTurn {timingTurn} < launchTiming + origPathLength {origPathLength} / 3 {self.timings.launchTiming + origPathLength / 2:.1f}")

            if path is not None and path.length > 0 and pathWorth > minArmy and inAttackWindow and path.start.tile.player == self.general.player:
                # Then it is worth launching the attack?
                logging.info(
                    f"  attacking because NEW worth_attacking_target(), pathWorth {pathWorth}, minArmy {minArmy}: {str(path)}")
                self.lastTargetAttackTurn = self._map.turn
                # return self.move_half_on_repetition(Move(path[1].tile, path[1].parent.tile, path[1].move_half), 7, 3)
                self.curPath = path
                return self.get_first_path_move(path)

            elif path is not None:
                logging.info(
                    "  Did NOT attack because NOT pathWorth > minArmy or not inAttackWindow??? pathWorth {}, minArmy {}, inAttackWindow {}: {}".format(
                        pathWorth, minArmy, path.toString(), inAttackWindow))
            else:
                logging.info("  Did not attack because path was None.")
        else:
            logging.info("skipped launch because outside launch window")

        return None

    def set_all_in_cycle_to_hit_with_current_timings(self, cycle: int, bufferTurnsEndOfCycle: int = 5):
        """
        @param cycle: The amount of turns to keep cycling the all in after the initial timing hit.

        @return:
        """

        turnsLeftInCurrentCycle = self.timings.cycleTurns - self.timings.get_turn_in_cycle(self._map.turn)
        self.all_in_army_advantage_counter = cycle - turnsLeftInCurrentCycle + bufferTurnsEndOfCycle
        self.all_in_army_advantage_cycle = cycle

    def try_find_flank_all_in(self, hitGeneralAtTurn: int) -> Move | None:
        launchPoint: Move | None = None
        return None

    def find_flank_opportunity(
            self,
            targetPlayer: int,
            flankingPlayer: int,
            flankPlayerLaunchPoints: typing.List[Tile],
            depth: int,
            targetDistMap: MapMatrix[int],
            validEmergencePointMatrix: MapMatrix[bool] | None
    ) -> Path | None:
        def prioFunc(curTile: Tile, prioObj):
            dist, negMaxPerTurn, zoningPenalty, fogTileCount, sequentialNonFog, totalNonFog, minDistFogEmergence, hadPossibleVision, hadDefiniteVision, fromTile = prioObj

            hasPossibleVision = SearchUtils.any_where(curTile.adjacents, lambda t: t.player == targetPlayer or (not curTile.visible and self.territories.territoryMap[t.x][t.y] == targetPlayer))
            hasDefiniteVision = SearchUtils.any_where(curTile.adjacents, lambda t: t.player == targetPlayer)

            if fromTile is not None:
                hasPossibleFromVision = SearchUtils.any_where(fromTile.adjacents, lambda t: t.player == targetPlayer or (not fromTile.visible and self.territories.territoryMap[t.x][t.y] == targetPlayer))
                hasDefiniteFromVision = SearchUtils.any_where(fromTile.adjacents, lambda t: t.player == targetPlayer)

                if not hasPossibleFromVision and not hasDefiniteFromVision and hasDefiniteVision:
                    return None

            if not hasPossibleVision:
                fogTileCount += 1
                sequentialNonFog = 0
            elif not hasDefiniteVision:
                fogTileCount += 0.5
                sequentialNonFog += 0.5
                minDistFogEmergence = min(dist + 1, minDistFogEmergence)
            else:
                sequentialNonFog += 1
                totalNonFog += 1
                minDistFogEmergence = min(dist, minDistFogEmergence)

            zoningPenalty = 1 / (1 + self.get_distance_from_board_center(curTile, center_ratio=0.0))

            dist += 1

            return dist, 0 - fogTileCount / dist, zoningPenalty, fogTileCount, sequentialNonFog, totalNonFog, minDistFogEmergence, hasPossibleVision, hasDefiniteVision, curTile

        def valueFunc(curTile: Tile, prioObj):
            dist, negMaxPerTurn, zoningPenalty, fogTileCount, sequentialNonFog, totalNonFog, minDistFogEmergence, hasPossibleVision, hasDefiniteVision, fromTile = prioObj

            if fromTile is not None and targetDistMap[fromTile] < targetDistMap[curTile]:
                return None
            if sequentialNonFog > 0:
                return None
            if totalNonFog > fogTileCount // 2:
                return None
            if validEmergencePointMatrix is not None and curTile not in validEmergencePointMatrix:
                return None

            return minDistFogEmergence - zoningPenalty

        startTiles = {}
        for tile in flankPlayerLaunchPoints:
            startTiles[tile] = ((0, 0, 0, 0, 0, 0, 1000, 0, 0, None), 0)
        flankPath = SearchUtils.breadth_first_dynamic_max(
            self._map,
            startTiles,
            priorityFunc=prioFunc,
            valueFunc=valueFunc,
            noNeutralCities=False,
            skipFunc=lambda t, prio: t.isUndiscoveredObstacle,
            maxDepth=depth,
        )

        if flankPath is not None:
            flankPath = flankPath.get_reversed()

        return flankPath

    def check_target_player_just_took_city(self):
        if self.targetPlayerObj is not None:
            if self.targetPlayerObj.cityCount > self._lastTargetPlayerCityCount:
                self.viewInfo.addAdditionalInfoLine(f'Dropping timings because target player just took a city.')
                self.timings = None

            self._lastTargetPlayerCityCount = self.targetPlayerObj.cityCount

    def get_2v2_launch_point(self) -> Tile:
        fromTile = self.general
        usDist = self.distance_from_general(self.targetPlayerExpectedGeneralLocation)
        allyAttackPath = self.get_path_to_target(self.targetPlayerExpectedGeneralLocation, preferEnemy=True,
                                                 preferNeutral=True, fromTile=self.teammate_general)
        allyDist = allyAttackPath.length
        lockGeneral = False

        teammateDistFromUs = self.teammate_path.length

        teammateRallyDistOffset = teammateDistFromUs // 4

        if self.targetPlayerObj.knowsAllyKingLocation and self.targetPlayerObj.knowsKingLocation:
            fromTile = self.teammate_path.get_subsegment(2 * self.teammate_path.length // 5).tail.tile
            teammateRallyDistOffset = teammateDistFromUs // 2
            lockGeneral = False
        elif self.targetPlayerObj.knowsAllyKingLocation:
            fromTile = self.teammate_general
            lockGeneral = True
            self.viewInfo.addAdditionalInfoLine(
                f'ALLY lp {str(fromTile)} due to vision')
        elif self.targetPlayerObj.knowsKingLocation:
            fromTile = self.general
            lockGeneral = True
            self.viewInfo.addAdditionalInfoLine(
                f'SELF lp {str(fromTile)} due to vision')

        if teammateDistFromUs < 15 and not lockGeneral:
            contested = self.get_contested_targets()
            if len(contested) > 0:
                fromTile = contested[0].tile
                self.launchPoints = [c.tile for c in contested]
            elif allyDist + teammateRallyDistOffset <= usDist:
                # then use ally as the launch point
                # TODO make sure we're not gonna get flanked by other player...?
                fromTile = self.teammate_general
                # TODO lock or not lock?
                self.viewInfo.addAdditionalInfoLine(
                    f'Ally lp {str(self.teammate_general)} dist {allyDist} from {str(self.targetPlayerExpectedGeneralLocation)} vs us {usDist}')

        return fromTile

    def increment_attack_counts(self, tile: Tile):
        contestData = self.contest_data.get(tile, None)
        if contestData is None:
            contestData = ContestData(tile)
            self.contest_data[tile] = contestData

        if contestData.last_attacked_turn < self._map.turn - 5:
            contestData.attacked_count += 1

        contestData.last_attacked_turn = self._map.turn

    def get_contested_targets(self, shortTermContestCutoff: int = 25, longTermContestCutoff: int = 60) -> typing.List[ContestData]:
        """
        Finds up to 3 recently contested targets within last shortTermContestCutoff moves.
        If it fails to find those, looks for at least one within last longTermContestCutoff moves.
        """

        contestedSorted = [c for c in sorted(self.contest_data.values(), key=lambda c: c.last_attacked_turn, reverse=True)]

        mostRecentTargets = [c for c in contestedSorted[0:3] if c.last_attacked_turn > self._map.turn - longTermContestCutoff]

        if len(mostRecentTargets) == 0:
            return []

        shortTermTargets = [t for t in mostRecentTargets if t.last_attacked_turn > self._map.turn - shortTermContestCutoff]
        if len(shortTermTargets) > 0:
            mostRecentTargets = shortTermTargets

        logging.info(f'Found contested tiles in get_contested_targets: {mostRecentTargets}')

        return mostRecentTargets

    def send_teammate_communication(self, message: str, pingTile: Tile | None = None, cooldown: int = 10, detectOnMessageAlone: bool = False, detectionKey: str | None = None):
        """
        Use this to send a chat message to team-chat only, as well as an optional tile ping.

        @param message:
        @param pingTile:
        @param cooldown: the number of turns before this message with this tile can be sent again.
        @param detectOnMessageAlone: if True, detect cooldown-duplication based on message, not message + tile. When duplicate on message is detected this way, the message will not even be written to the UI.
        @param detectionKey: if present, will be used to detect whether something shouldn't be sent to teammate due to cooldown.
        @return:
        """

        commKey = message

        if detectOnMessageAlone:
            lastSentTurn = self._communications_sent_cooldown_cache.get(commKey, -50)
            if lastSentTurn > self._map.turn - cooldown:
                return

            if pingTile is not None:
                self._communications_sent_cooldown_cache[commKey] = self._map.turn

        if pingTile is not None:
            commKey = f'[@{str(pingTile)}] {commKey}'
        self.viewInfo.addAdditionalInfoLine(f'Send: {commKey}')

        if detectionKey is None:
            detectionKey = commKey

        if not self._map.is_2v2:
            return

        lastSentTurn = self._communications_sent_cooldown_cache.get(detectionKey, -50)
        if lastSentTurn < self._map.turn - cooldown:
            self._outbound_team_chat.put(message)

            if pingTile is not None:
                self.send_teammate_tile_ping(pingTile)
            self._communications_sent_cooldown_cache[detectionKey] = self._map.turn

    def send_teammate_path_ping(self, path: Path, cooldown: int = 0, cooldownKey: str | None = None):
        """Pings all the tiles in a path"""
        for tile in path.tileList:
            self.send_teammate_tile_ping(tile, cooldown, cooldownKey)

    def send_teammate_tile_ping(self, pingTile: Tile, cooldown: int = 0, cooldownKey: str | None = None):
        """
        Use this to send a tile ping.
GAME START
12:12:56.983
42["game_start",{"playerIndex":0,"playerColors":[0,1,2,3],"replay_id":"SeGpX_VWT","chat_room":"game_1697051578054SDTRNZlxr5ZbYoIPAN-p","team_chat_room":"game_1697051578054SDTRNZlxr5ZbYoIPAN-p_team_1","usernames":["EklipZ_0x45","[Bot]EklipZ_ai","[Bot] Sora_ai_ek","[Bot] Sora_ai_2"],"teams":[1,1,2,2],"game_type":"2v2","swamps":[],"lights":[],"options":{}},null]	361
12:12:59.484



        SENDING
42["ping_tile",125]	19

all chat
(sent)
42["chat_message","game_1697051578054SDTRNZlxr5ZbYoIPAN-p","norm chat",""]
(self received)
42["chat_message","game_1697051578054SDTRNZlxr5ZbYoIPAN-p",{"username":"EklipZ_0x45","text":"norm chat","prefix":"","playerColor":0,"turn":13}]

team chat
(sent)
42["chat_message","game_1697051578054SDTRNZlxr5ZbYoIPAN-p_team_1","team chat","[team] "]
(self received)
42["chat_message","game_1697051578054SDTRNZlxr5ZbYoIPAN-p_team_1",{"username":"EklipZ_0x45","text":"team chat","prefix":"[team] ","playerColor":0,"turn":20}]

Surrender
(sent)
42["surrender"]	15
(recv)
42["chat_message","game_1697051578054SDTRNZlxr5ZbYoIPAN-p",{"text":"EklipZ_0x45 surrendered.","playerColor":0,"turn":43}]	121
(recv)
42["game_lost",{"surrender":true},null]	39
(recv)
42["game_update",{"scores":[{"total":22,"tiles":18,"i":2,"colo


RECV BY OTHER PLAYER

2023-10-11 12:13:05.949347 - WS recv: "42[\"chat_message\",\"game_1697051578054SDTRNZlxr5ZbYoIPAN-p\",{\"username\":\"EklipZ_0x45\",\"text\":\"norm chat\",\"prefix\":\"\",\"playerColor\":0,\"turn\":13}]"
~~~
~~~
From EklipZ_0x45: norm chat
~~~



2023-10-11 12:13:09.115008 - WS recv: "42[\"chat_message\",\"game_1697051578054SDTRNZlxr5ZbYoIPAN-p_team_1\",{\"username\":\"EklipZ_0x45\",\"text\":\"team chat\",\"prefix\":\"[team] \",\"playerColor\":0,\"turn\":20}]"
~~~
~~~
From EklipZ_0x45: team chat
~~~
~~~


2023-10-11 12:13:10.200755 - WS recv: "42[\"ping_tile\",125,0]"
Unknown message type: ['ping_tile', 125, 0]

42["game_update",{"scores":[{"total":62,"tiles":39,"i":2,"color":2,"dead":false},{"total":45,"tiles":19,"i":1,"color":1,"dead":false},{"total":44,"tiles":26,"i":3,"color":3,"dead":false},{"total":35,"tiles":1,"i":0,"color":0,"dead":true}],"turn":66,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[333,2,2,1,1,1,18,22,1,1,2,1,35,19,1,2,539],"cities_diff":[2]},null]	371
12:13:32.006
42["game_update",{"scores":[{"total":63,"tiles":40,"i":2,"color":2,"dead":false},{"total":45,"tiles":19,"i":1,"color":1,"dead":false},{"total":43,"tiles":25,"i":3,"color":3,"dead":false},{"total":35,"tiles":1,"i":0,"color":0,"dead":true}],"turn":67,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[332,2,2,1,25,1,2,22,1,1,539],"cities_diff":[2]},null]	357
12:13:32.506
42["game_update",{"scores":[{"total":61,"tiles":39,"i":2,"color":2,"dead":false},{"total":47,"tiles":26,"i":3,"color":3,"dead":false},{"total":46,"tiles":19,"i":1,"color":1,"dead":false},{"total":36,"tiles":1,"i":0,"color":0,"dead":true}],"turn":68,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[313,1,19,22,1,1,25,1,36,19,1,2,539],"cities_diff":[2]},null]	364
12:13:33.006
42["game_update",{"scores":[{"total":61,"tiles":39,"i":2,"color":2,"dead":false},{"total":47,"tiles":26,"i":3,"color":3,"dead":false},{"total":46,"tiles":19,"i":1,"color":1,"dead":false},{"total":36,"tiles":1,"i":0,"color":0,"dead":true}],"turn":69,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[314,1,3,22,1,1,21,1,3,22,1,1,539],"cities_diff":[2]},null]	362
12:13:33.507
42["game_update",{"scores":[{"total":62,"tiles":39,"i":2,"color":2,"dead":false},{"total":48,"tiles":26,"i":3,"color":3,"dead":false},{"total":47,"tiles":19,"i":1,"color":1,"dead":false},{"total":37,"tiles":1,"i":0,"color":0,"dead":true}],"turn":70,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[290,2,20,3,21,2,1,1,16,2,2,1,29,1,37,19,1,2,539],"cities_diff":[2]},null]	377
12:13:34.007
42["game_update",{"scores":[{"total":62,"tiles":39,"i":2,"color":2,"dead":false},{"total":48,"tiles":26,"i":3,"color":3,"dead":false},{"total":47,"tiles":19,"i":1,"color":1,"dead":false},{"total":37,"tiles":1,"i":0,"color":0,"dead":true}],"turn":71,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[268,1,3,22,1,1,16,1,2,22,1,1,27,1,4,22,1,1,539],"cities_diff":[2]},null]	376
12:13:34.509
42["game_update",{"scores":[{"total":60,"tiles":38,"i":2,"color":2,"dead":false},{"total":49,"tiles":26,"i":3,"color":3,"dead":false},{"total":45,"tiles":20,"i":1,"color":1,"dead":false},{"total":38,"tiles":1,"i":0,"color":0,"dead":true}],"turn":72,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[243,3,2,1,1,21,2,16,1,16,1,3,4,1,1,17,1,1,53,1,38,19,1,2,320,3,2,2,2,21,1,1,194],"cities_diff":[2]},null]	409
12:13:35.008
42["game_update",{"scores":[{"total":60,"tiles":38,"i":2,"color":2,"dead":false},{"total":49,"tiles":26,"i":3,"color":3,"dead":false},{"total":45,"tiles":20,"i":1,"color":1,"dead":false},{"total":38,"tiles":1,"i":0,"color":0,"dead":true}],"turn":73,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[243,1,3,22,1,1,92,1,5,22,1,1,539],"cities_diff":[2]},null]	362
12:13:35.508
42["game_update",{"scores":[{"total":60,"tiles":37,"i":2,"color":2,"dead":false},{"total":50,"tiles":26,"i":3,"color":3,"dead":false},{"total":45,"tiles":21,"i":1,"color":1,"dead":false},{"total":39,"tiles":1,"i":0,"color":0,"dead":true}],"turn":74,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[242,2,4,1,22,2,14,1,20,1,1,73,1,39,19,1,2,319,1,2,22,2,-2,1,21,1,2,173],"cities_diff":[2]},null]	400
12:13:36.009
42["game_update",{"scores":[{"total":60,"tiles":37,"i":2,"color":2,"dead":false},{"total":50,"tiles":26,"i":3,"color":3,"dead":false},{"total":45,"tiles":21,"i":1,"color":1,"dead":false},{"total":39,"tiles":1,"i":0,"color":0,"dead":true}],"turn":75,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[242,1,1,116,1,6,22,1,1,539],"cities_diff":[2]},null]	356
12:13:36.509
42["game_update",{"scores":[{"total":60,"tiles":36,"i":2,"color":2,"dead":false},{"total":51,"tiles":26,"i":3,"color":3,"dead":false},{"total":45,"tiles":22,"i":1,"color":1,"dead":false},{"total":40,"tiles":1,"i":0,"color":0,"dead":true}],"turn":76,"attackIndex":0,"generals":[360,380,-1,-1],"map_diff":[219,2,5,2,22,1,12,22,1,1,95,1,40,19,1,2,296,3,2,2,-2,21,1,1,218],"cities_diff":[2]},null]	393
12:13:37.010
42["game_update",{"scores":[{"total":60,"tiles":36,"i":2,"color":2,"dead":false},{"total":51,"tiles":26,"i":3,"color":3,"dead":false},{"total":45,"tiles":22,"i":1,"color":1,"dead":false},{"tota
        @param pingTile:
        @param cooldown: how many turns to refuse to ping this tile again for.
        @return:
        """

        if not self._map.is_2v2:
            return

        if cooldown > 0:
            if cooldownKey is None:
                cooldownKey = str(pingTile)

            cooldownKey = f'PINGCOOL{cooldownKey}'

            coolTurn = self._communications_sent_cooldown_cache.get(cooldownKey, -250)
            if coolTurn > self._map.turn - cooldown:
                return
            self._communications_sent_cooldown_cache[cooldownKey] = self._map.turn

        self.viewInfo.add_targeted_tile(pingTile, targetStyle=TargetStyle.GOLD)
        self._tile_ping_queue.put(pingTile)

    def get_queued_tile_pings(self) -> typing.List[Tile]:
        outbound = []
        while self._tile_ping_queue.qsize() > 0:
            outbound.append(self._tile_ping_queue.get())

        return outbound

    def get_queued_teammate_messages(self) -> typing.List[str]:
        outbound = []
        while self._outbound_team_chat.qsize() > 0:
            outbound.append(self._outbound_team_chat.get())

        return outbound

    def notify_chat_message(self, chatUpdate: ChatUpdate):
        self._chat_messages_received.put(chatUpdate)

    def notify_tile_ping(self, pingedTile: Tile):
        self._tiles_pinged_by_teammate.put(pingedTile)

    def determine_should_defend_ally(self) -> bool:
        # then this is a threat against ally, check if they defend:
        threat = self.dangerAnalyzer.fastestAllyThreat
        general = self._map.generals[threat.path.tail.tile.player]

        # TODO hack for now until fog duplication issues in 2v2 are resolved.
        if not threat.path.start.tile.visible:
            return False

        if self.teammate_communicator is not None:
            if self.teammate_communicator.is_defense_lead:
                return True

        teammateSelfSavePathShort = self.get_best_defense(
            threat.path.tail.tile,
            threat.turns - 3,
            threat.path.tileList)
        if teammateSelfSavePathShort is not None:
            logging.info(
                f"  threatVal {threat.threatValue}, teammateSelfSavePathShort {str(teammateSelfSavePathShort)}")
            if threat.threatValue < teammateSelfSavePathShort.value:
                self.send_teammate_communication(
                    f"|  Need {threat.threatValue} @ you in {threat.turns} moves. Expecting you to block by yourself with pinged tile.",
                    threat.path.start.tile,
                    detectionKey='allyDefense',
                    cooldown=5)
                self.send_teammate_tile_ping(threat.path.tail.tile, cooldown=3)
                self.send_teammate_tile_ping(teammateSelfSavePathShort.start.tile, cooldown=3)
                return False

        teammateSelfSavePath = self.get_best_defense(
            threat.path.tail.tile,
            threat.turns - 1,
            threat.path.tileList)
        if teammateSelfSavePath is not None:
            logging.info(
                f"  threatVal {threat.threatValue}, teammateSelfSavePath {str(teammateSelfSavePath)}")
            if threat.threatValue < teammateSelfSavePath.value:
                # if threat.path.start.tile in teammateSelfSavePath.tail.tile.adjacents:
                #     return False
                self.send_teammate_communication(
                    f"-- Need {threat.threatValue} @ you in {threat.turns} moves. You may barely manage. Protecting you just in case.",
                    threat.path.start.tile,
                    detectionKey='allyDefense',
                    cooldown=5)
                self.send_teammate_tile_ping(threat.path.tail.tile, cooldown=3)
                self.send_teammate_tile_ping(teammateSelfSavePath.start.tile, cooldown=3)
                return True
            else:
                # if threat.path.start.tile in teammateSelfSavePath.tail.tile.adjacents:
                #     return False
                self.send_teammate_communication(
                    f"---Need {threat.threatValue} @ you in {threat.turns} moves. You may be unable to save yourself by {threat.threatValue - teammateSelfSavePath.value} army, trying to help.",
                    threat.path.start.tile,
                    detectionKey='allyDefense',
                    cooldown=5)
                # self.send_teammate_tile_ping(threat.path.tail.tile, cooldown=3)
                if teammateSelfSavePath.start.tile.lastMovedTurn < self._map.turn - 1:
                    self.send_teammate_tile_ping(teammateSelfSavePath.start.tile, cooldown=5)
                return True

        self.send_teammate_communication(
            f"---Need {threat.threatValue} @ you in {threat.turns} moves. You have no defense, trying to defend you.",
            threat.path.start.tile,
            detectionKey='allyDefense',
            cooldown=2)
        self.send_teammate_tile_ping(threat.path.tail.tile, cooldown=3)
        return True

    def find_end_of_turn_sim_result(self, threat: ThreatObj | None, kingKillPath: Path | None, time_limit: float | None = None) -> ArmySimResult | None:
        # frArmies = [a for a in self.armyTracker.armies.values() if a.player == self.general.player]
        # if len(frArmies) <= self.behavior_end_of_turn_scrim_army_count:
        frArmies = self.get_largest_tiles_as_armies(player=self.general.player, limit=self.behavior_end_of_turn_scrim_army_count)

        # enArmies = [a for a in self.armyTracker.armies.values() if a.player == self.targetPlayer]
        # if len(enArmies) <= self.behavior_end_of_turn_scrim_army_count:
        enArmies = self.get_largest_tiles_as_armies(player=self.targetPlayer, limit=self.behavior_end_of_turn_scrim_army_count)

        if len(enArmies) == 0:
            self.targetPlayerExpectedGeneralLocation.player = self.targetPlayer
            enArmies = [self.get_army_at(self.targetPlayerExpectedGeneralLocation, no_expected_path=True)]

        enemyHasKillThreat = threat is not None and threat.threatType == ThreatType.Kill
        friendlyHasKillThreat = kingKillPath is not None

        if time_limit is None:
            time_limit = self.get_remaining_move_time()

        if time_limit < 0.06:
            logging.info(f'not enough time left ({time_limit:.3f}) for end of turn scrim. Returning none.')
            return None

        old_allow_random_no_ops = self.mcts_engine.allow_random_no_ops
        old_friendly_move_no_op_scale_10_fraction = self.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction
        old_enemy_move_no_op_scale_10_fraction = self.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction

        self.mcts_engine.allow_random_no_ops = False
        self.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 0
        self.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = 0

        simResult = self.get_armies_scrim_result(
            frArmies,
            enArmies,
            enemyHasKillThreat=enemyHasKillThreat,
            friendlyHasKillThreat=friendlyHasKillThreat,
            time_limit=time_limit - 0.01)

        self.mcts_engine.allow_random_no_ops = old_allow_random_no_ops
        self.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = old_friendly_move_no_op_scale_10_fraction
        self.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = old_enemy_move_no_op_scale_10_fraction

        self.info(f'finScr {str(simResult)} {str(simResult.expected_best_moves)}')

        return simResult

    def find_end_of_turn_scrim_move(self, threat: ThreatObj | None, kingKillPath: Path | None, time_limit: float | None = None) -> Move | None:
        simResult = self.find_end_of_turn_sim_result(threat, kingKillPath, time_limit)

        if simResult is not None:
            friendlyPath, enemyPath = self.extract_engine_result_paths_and_render_sim_moves(simResult)
            if friendlyPath is not None:
                return self.get_first_path_move(friendlyPath)

        return None

    def get_largest_tiles_as_armies(self, player: int, limit: int) -> typing.List[Army]:
        player = self._map.players[player]

        def sortFunc(t: Tile) -> float:
            pw = self.board_analysis.intergeneral_analysis.pathWayLookupMatrix[t]
            dist = 100
            if pw is not None:
                dist = pw.distance
            else:
                logging.error(f'pathway none again for {str(t)}')
            return (t.army - 1) / (dist + 5)

        tiles = sorted(
            player.tiles,
            key=sortFunc,
            reverse=True)

        armies = [self.get_army_at(t, no_expected_path=True) for t in tiles[0:limit] if t.army > 1]

        return armies

    def get_defense_tree_move_prio_funcs(
            self,
            threat: ThreatObj,
            anyLeafIsSameDistAsThreat: bool = False
    ) -> typing.Tuple[typing.Callable[[Tile, typing.Any], typing.Any], typing.Callable[[Tile, typing.Any], typing.Any]]:
        threatenedTileDistMap = SearchUtils.build_distance_map(self._map, [threat.path.tail.tile])

        moveClosestMap = SearchUtils.build_distance_map(self._map, [threat.path.start.tile])

        def move_closest_priority_func(nextTile: Tile, currentPriorityObject):
            # closenessToThreat = moveClosestMap[nextTile.x][nextTile.y] - threatenedTileDistMap[nextTile.x][nextTile.y]
            closenessToThreat = 0 - threatenedTileDistMap[nextTile.x][nextTile.y]
            return (
                anyLeafIsSameDistAsThreat or nextTile.isCity,
                # nextTile in threat.armyAnalysis.shortestPathWay.tiles,
                closenessToThreat,
                0 - nextTile.army
            )

        def move_closest_value_func(curTile: Tile, currentPriorityObject):
            # closenessToThreat = threatenedTileDistMap[curTile.x][curTile.y] - moveClosestMap[curTile.x][curTile.y]
            closenessToThreat = threatenedTileDistMap[curTile.x][curTile.y] - 0
            return (
                not (anyLeafIsSameDistAsThreat or curTile.isCity),
                # curTile not in threat.armyAnalysis.shortestPathWay.tiles,
                closenessToThreat,
                curTile.army
            )

        return move_closest_priority_func, move_closest_value_func

    def hunt_for_fog_neutral_city(self, negativeTiles: typing.Set[Tile]) -> typing.Tuple[Path | None, Move | None]:
        fogObstacleAdjacents = MapMatrix(self._map, 0)
        tilesNear = []

        def foreachFogObstacleCounter(tile: Tile, dist: int):
            if (
                # not tile.discovered
                not SearchUtils.any_where(tile.adjacents, lambda t: self.is_tile_in_enemy_territory(t) or t.player >= 0)
                and not tile.isUndiscoveredObstacle
            ):
                count = 0
                for adj in tile.adjacents:
                    if self.distance_from_general(tile) > self.distance_from_general(adj):
                        continue
                    if adj.isUndiscoveredObstacle:
                        count += 1
                        count += fogObstacleAdjacents[adj]

                fogObstacleAdjacents[tile] = count
                if count > 0:
                    tilesNear.append((tile, dist))

        SearchUtils.breadth_first_foreach_dist(
            self._map,
            self.player.tiles,
            maxDepth=4,
            foreachFunc=foreachFogObstacleCounter,
            skipFunc=lambda t: self.is_tile_in_enemy_territory(t),
            bypassDefaultSkip=True
        )

        logging.info(f'GATHERING TO FOG UNDISC')

        def sorter(tileDistTuple) -> float:
            tile, dist = tileDistTuple
            rating = fogObstacleAdjacents[tile] / self.distance_from_general(tile) / dist
            return rating

        prioritized = [t for t, d in sorted(tilesNear, key=sorter, reverse=True)]

        keyAreas = prioritized[0:20]

        for t in keyAreas:
            self.viewInfo.add_targeted_tile(t, TargetStyle.WHITE)

        path = SearchUtils.dest_breadth_first_target(self._map, keyAreas, targetArmy=1, negativeTiles=negativeTiles, maxDepth=3)
        if path is not None:
            self.curPath = path
            return path, None

        with self.perf_timer.begin_move_event('Hunting for fog neutral cities'):
            move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_target_tiles(keyAreas, 0.1, self._map.turn % 5 + 1, negativeTiles, targetArmy=1, useTrueValueGathered=True, maximizeArmyGatheredPerTurn=True)

        if move is not None:
            self.gatherNodes = gatherNodes
            self.info(f'Hunting for fog neutral cities: {str(move)}')
            return None, move

        return None, None

    def try_find_exploration_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        # if losing on economy, finishing exp false
        genPlayer = self._map.players[self.general.player]

        largeTileThresh = 15 * genPlayer.standingArmy / genPlayer.tileCount
        haveLargeTilesStill = len(SearchUtils.where(genPlayer.tiles, lambda tile: tile.army > largeTileThresh)) > 0
        logging.info(
            "Will stop finishingExploration if we don't have tiles larger than {:.1f}. Have larger tiles? {}".format(
                largeTileThresh, haveLargeTilesStill))
        if not self.winning_on_economy(cityValue=0) and not haveLargeTilesStill:
            self.finishing_exploration = False

        demolishingTargetPlayer = (self.winning_on_army(1.5, useFullArmy=False, againstPlayer=self.targetPlayer)
                                   and self.winning_on_economy(1.5, cityValue=10, againstPlayer=self.targetPlayer))

        allInAndKnowsGenPosition = (
           (self.all_in_army_advantage or self.all_in_counter > self.targetPlayerObj.tileCount // 3)
           and self.targetPlayerExpectedGeneralLocation.isGeneral
           and not self.all_in_city_behind
        )
        targetPlayer = self._map.players[self.targetPlayer]
        stillDontKnowAboutEnemyCityPosition = len(targetPlayer.cities) + 1 < targetPlayer.cityCount
        stillHaveSomethingToSearchFor = (
            (self.is_all_in() or self.finishing_exploration or demolishingTargetPlayer)
            and (not self.targetPlayerExpectedGeneralLocation.isGeneral or stillDontKnowAboutEnemyCityPosition)
        )

        logging.info(
            f"stillDontKnowAboutEnemyCityPosition: {stillDontKnowAboutEnemyCityPosition}, allInAndKnowsGenPosition: {allInAndKnowsGenPosition}, stillHaveSomethingToSearchFor: {stillHaveSomethingToSearchFor}")
        if not allInAndKnowsGenPosition and stillHaveSomethingToSearchFor and not self.defend_economy:
            undiscNeg = defenseCriticalTileSet.copy()

            if (
                self.all_in_city_behind
                or (
                    self.all_in_army_advantage
                    and self.winning_on_economy(byRatio=0.8, cityValue=50)
                )
            ):
                path = self.get_quick_kill_on_enemy_cities(defenseCriticalTileSet)
                if path is not None:
                    # self.curPath = path
                    self.info(f'ALL IN ARMY ADVANTAGE CITY CONTEST {str(path)}')
                    return self.get_first_path_move(path)

                for contestedCity in self.cityAnalyzer.owned_contested_cities:
                    undiscNeg.add(contestedCity)

            self.viewInfo.addAdditionalInfoLine(
                f"exp: unknownEnCity: {stillDontKnowAboutEnemyCityPosition}, allInAgainstGen: {allInAndKnowsGenPosition}, stillSearch: {stillHaveSomethingToSearchFor}")
            with self.perf_timer.begin_move_event('Attempting to finish/continue exploration'):
                for city in self._map.players[self.general.player].cities:
                    undiscNeg.add(city)
                halfTargetPath = self.target_player_gather_path.get_subsegment(
                    self.target_player_gather_path.length // 2)
                undiscNeg.add(self.general)
                for tile in halfTargetPath.tileList:
                    undiscNeg.add(tile)
                path = self.explore_target_player_undiscovered(undiscNeg)
                if path is not None:
                    self.viewInfo.color_path(PathColorer(path, 120, 150, 127, 200, 12, 100))
                    if not self.is_path_moving_mostly_away(path, self.board_analysis.intergeneral_analysis.bMap):
                        valueSubsegment = self.get_value_per_turn_subsegment(path, minLengthFactor=0)
                        if valueSubsegment.length != path.length:
                            logging.info(f"BAD explore_target_player_undiscovered")
                            self.info(
                                f"WHOAH, tried to make a bad exploration path...? Fixed with {str(valueSubsegment)}")
                            path = valueSubsegment
                        move = self.get_first_path_move(path)
                        if not self.detect_repetition(move, 7, 2):
                            if self.all_in_army_advantage:
                                self.all_in_army_advantage_counter -= 2
                            return move
                        else:
                            self.info('bypassed hunting due to repetitions.')
                    else:
                        self.info(f'IGNORING BAD HUNTING PATH BECAUSE MOVES AWAY FROM GEN APPROX')

        return None

    def handle_chat_message(self, chatUpdate: ChatUpdate):
        if chatUpdate.from_user == self._map.usernames[self._map.player_index]:
            # ignore our own messages?
            return

        self.viewInfo.addAdditionalInfoLine(str(chatUpdate))
        if self.is_2v2_teammate_still_alive() and chatUpdate.is_team_chat:
            if self.teamed_with_bot:
                self.handle_bot_chat(chatUpdate)
            else:
                self.handle_human_chat(chatUpdate)
        else:
            # chat in other modes, FFA teaming...?
            pass

    def is_2v2_teammate_still_alive(self) -> bool:
        if not self._map.is_2v2:
            return False
        if self.teammate_general is None:
            return False
        return True

    def handle_bot_chat(self, chatUpdate: ChatUpdate):
        if chatUpdate.message.startswith("!"):
            self.teammate_communicator.handle_coordination_update(chatUpdate)

    def handle_human_chat(self, chatUpdate: ChatUpdate):
        pass

    def communicate_threat_to_ally(self, threat: ThreatObj, valueGathered: int, defensePlan: typing.List[GatherTreeNode]):
        if self.teammate_communicator is not None and self.teammate_communicator.is_teammate_coordinated_bot:
            self.teammate_communicator.communicate_defense_plan(threat, valueGathered, defensePlan)
        elif threat.threatValue - valueGathered > 0:
            self.send_teammate_communication(f"HELP! NEED {threat.threatValue - valueGathered} in {threat.turns - 1}")
            self.send_teammate_path_ping(threat.path, cooldown=2, cooldownKey="HELP ME")

    def try_find_expansion_move(self, defenseCriticalTileSet: typing.Set[Tile]):
        skipForAllIn = (self.is_all_in() and self.targetPlayerExpectedGeneralLocation.isGeneral)

        if not self.defend_economy and self.timings.in_expand_split(self._map.turn) and not skipForAllIn:
            logging.info(f"------------\n Checking optimal expansion.")

            expansionNegatives = defenseCriticalTileSet.copy()
            splitTurn = self.timings.get_turn_in_cycle(self._map.turn)
            if splitTurn < self.timings.launchTiming and self._map.turn > 50:
                self.viewInfo.addAdditionalInfoLine(
                    f"splitTurn {splitTurn} < launchTiming {self.timings.launchTiming}...?")
                for tile in self.target_player_gather_targets:
                    if self._map.is_tile_friendly(tile):
                        expansionNegatives.add(tile)

            territoryMap = self.territories.territoryMap

            numDanger = 0
            for tile in self.general.movable:
                if (self._map.is_tile_enemy(tile)
                        and tile.army > 5):
                    numDanger += 1
                    if tile.army > self.general.army - 1:
                        numDanger += 1
            if numDanger > 1:
                expansionNegatives.add(self.general)

            countTilesWithArmyNonCities = SearchUtils.count(
                self._map.players[self.general.player].tiles,
                filter_func=lambda t: t.army > 1 and not t.isCity and not t.isGeneral)

            remainingCycleTurns = self.timings.cycleTurns - self.timings.get_turn_in_cycle(self._map.turn)

            if self.expand_plan is not None and len(self.expand_plan.plan_paths) == 0:
                self.expand_plan = None

            if self.expand_plan is not None or (
                    countTilesWithArmyNonCities == 0 and remainingCycleTurns < 21 and not self._map.remainingPlayers > 3):
                with self.perf_timer.begin_move_event(f'EXP - first25 reuse'):
                    move = self.get_optimal_first_25_plan_move()
                    if move is not None and (move.source.army == 1 or move.source.player != self.general.player):
                        # abort
                        self.expand_plan = None
                    else:
                        self.info(f'Optimal Expansion {str(move)} piggybacking early expand utils.')
                        return move

            with self.perf_timer.begin_move_event(f'optimal_expansion - main timing'):
                timeLimit = self.expansion_full_time_limit
                remainingMoveTime = self.get_remaining_move_time()
                if remainingMoveTime < timeLimit and not DebugHelper.IS_DEBUGGING:
                    timeLimit = remainingMoveTime
                    if remainingMoveTime < 0.05:
                        timeLimit = 0.05

                if self.teammate_general is not None:
                    expansionNegatives.add(self.teammate_general)

                    for army in self.armyTracker.armies.values():
                        if army.player in self._map.teammates and army.last_moved_turn > self._map.turn - 3:
                            expansionNegatives.add(army.tile)

                    if self.threat is not None and self.threat.turns < 2 and self.threat.path.tail.tile == self.general:
                        # teammate might defend us, don't throw it all away
                        expansionNegatives.add(self.general)

                path, otherPaths = ExpandUtils.get_optimal_expansion(
                    self._map,
                    searchingPlayer=self.player.index,
                    targetPlayer=self.targetPlayer,
                    turns=remainingCycleTurns,
                    boardAnalysis=self.board_analysis,
                    territoryMap=territoryMap,
                    negativeTiles=expansionNegatives,
                    leafMoves=self.leafMoves,
                    useLeafMovesFirst=self.expansion_use_leaf_moves_first,
                    viewInfo=self.viewInfo,
                    singleIterationPathTimeCap=self.expansion_single_iteration_time_cap,
                    forceNoGlobalVisited=self.expansion_force_no_global_visited,
                    forceGlobalVisitedStage1=self.expansion_force_global_visited_stage_1,
                    useIterativeNegTiles=self.expansion_use_iterative_negative_tiles,
                    allowLeafMoves=self.expansion_allow_leaf_moves,
                    allowMultiPathMultiDistReturn=self.expansion_use_multi_per_dist_per_tile,
                    time_limit=timeLimit,
                    lengthWeightOffset=self.expansion_length_weight_offset,
                    useCutoff=self.expansion_use_cutoff,
                    smallTileExpansionTimeRatio=self.expansion_small_tile_time_ratio)

            expansionNegStr = f'({"), (".join([str(t) for t in expansionNegatives])})'
            if path:
                if path.start.tile.isGeneral or path.start.tile.isCity:
                    self.curPath = path.get_subsegment(path.length // 2 + 1)

                move = self.get_first_path_move(path)
                if self.is_all_in() and move.move_half:
                    move.move_half = False
                if self.is_move_safe_valid(move):
                    self.info(
                        f"EXP {str(move)} neg {expansionNegStr}")
                    return move
            elif len(otherPaths) > 0:
                self.info(
                    f"Exp said wait. neg {expansionNegStr}")
                return None
            else:
                self.info(
                    f"Exp move not found...? neg {expansionNegStr}")
        else:
            self.viewInfo.addAdditionalInfoLine(
                f"skipping optimal expansion because self.all_in_counter ({self.all_in_counter}) or self.defendEconomy ({self.defend_economy})")
        return None

    def try_find_army_out_of_position_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        thresh = self.targetPlayerObj.standingArmy ** 0.6
        logging.info(f'Checking for out of position tiles with army greater than threshold {thresh:.0f}')
        outOfPositionArmies = []
        for tile in self.largePlayerTiles:
            distFr = self.board_analysis.intergeneral_analysis.aMap[tile.x][tile.y]
            distEn = self.board_analysis.intergeneral_analysis.bMap[tile.x][tile.y]

            if tile in self.board_analysis.extended_play_area_matrix and distEn > distFr:
                continue

            if tile in self.board_analysis.core_play_area_matrix and distEn * 2 > distFr:
                continue

            if tile.army < thresh:
                continue

            if self.is_tile_in_friendly_territory(tile):
                continue

            outOfPositionArmies.append(self.get_army_at(tile))

            if len(outOfPositionArmies) > 5:
                break

        if len(outOfPositionArmies) == 0:
            return None

        result = self.get_armies_scrim_result(friendlyArmies=outOfPositionArmies, enemyArmies=self.get_largest_tiles_as_armies(self.targetPlayer, 7), enemyCannotMoveAway=False)

        if result is not None:
            friendlyPath, enemyPath = self.extract_engine_result_paths_and_render_sim_moves(result)
            if friendlyPath is not None:
                move = self.get_first_path_move(friendlyPath)
                self.info(f'Army out of position scrim {str(move)}')
                return move

        return None

    def are_more_teams_alive_than(self, numTeams: int) -> bool:
        aliveTeams = set()
        teams = MapBase.get_teams_array(self._map)
        for player in self._map.players:
            if not player.dead:
                aliveTeams.add(teams[player.index])

        if len(aliveTeams) > numTeams:
            return True
        return False

    def get_potential_threat_movement_negatives(self, targetTile: Tile | None = None) -> typing.Set[Tile]:
        """
        Based on an available potential threat path, determine if any tiles are not allowed to move because they would increase risk.

        @param targetTile: Optionally include the target tile that you are calculating moves AGAINST which will allow tile use that would otherwise be blocked if the target is part of the threat.

        @return:
        """
        potThreat = self.dangerAnalyzer.fastestPotentialThreat
        potNegs = set()

        if potThreat is None:
            return potNegs

        if targetTile is not None and targetTile in potThreat.armyAnalysis.shortestPathWay.tiles:
            return potNegs

        threatArmy = self.armyTracker.armies.get(potThreat.path.start.tile, None)

        if threatArmy is not None and not threatArmy.tile.visible:
            if potThreat.turns < 7:
                self.targetingArmy = threatArmy
            elif threatArmy.last_seen_turn < self._map.turn - 4 and threatArmy.last_moved_turn < self._map.turn - 1:
                # ignore threats from non-visible armies that we haven't seen in a while.
                return potNegs

        for tile in potThreat.path.tileList:
            if self._map.is_tile_friendly(tile) and potThreat.threatValue + tile.army > potThreat.turns:
                potNegs.add(tile)

        return potNegs


