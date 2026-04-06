"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""
import heapq
import math
import queue
import random
import time
import traceback
import typing
from queue import Queue


import logbook


import BotLogging
import DebugHelper
import EarlyExpandUtils
import Gather
import SearchUtils
import ExpandUtils
import Utils
from Algorithms import MapSpanningUtils, TileIslandBuilder, WatchmanRouteUtils, TileIsland
from Army import Army
from ArmyAnalyzer import ArmyAnalyzer
from ArmyEngine import ArmyEngine, ArmySimResult
from Behavior.ArmyInterceptor import ArmyInterceptor, ArmyInterception, ThreatBlockInfo, InterceptionOptionInfo
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
from CityAnalyzer import CityAnalyzer, CityScoreData
from Communication import TeammateCommunicator, TileCompressor
from DistanceMapperImpl import DistanceMapperImpl
from Gather import GatherCapturePlan
from GatherAnalyzer import GatherAnalyzer
from Interfaces import TilePlanInterface, MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet, TileSet
from MctsLudii import MctsDUCT
from Path import Path, MoveListPath
from PerformanceTimer import PerformanceTimer
from BoardAnalyzer import BoardAnalyzer
from BotModules.BotCityOps import BotCityOps
from BotModules.BotCombatOps import BotCombatOps
from BotModules.BotComms import BotComms
from BotModules.BotDefense import BotDefense
from BotModules.BotEventHandlers import BotEventHandlers
from BotModules.BotExplorationOps import BotExplorationOps
from BotModules.BotExpansionOps import BotExpansionOps
from BotModules.BotGatherOps import BotGatherOps
from BotModules.BotLifecycle import BotLifecycle
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotRendering import BotRendering
from BotModules.BotRepetition import BotRepetition
from BotModules.BotSerialization import BotSerialization
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotTimings import BotTimings
from BotModules.BotTargeting import BotTargeting
from Sim.TextMapLoader import TextMapLoader
from Strategy import OpponentTracker, WinConditionAnalyzer, CaptureLineTracker
from Strategy.WinConditionAnalyzer import WinCondition
from StrategyModels import CycleStatsData, ExpansionPotential
from ViewInfo import ViewInfo, PathColorer, TargetStyle
from base import Colors
from base.client.generals import ChatUpdate, _spawn
from base.client.map import Player, Tile, MapBase, PLAYER_CHAR_BY_INDEX, new_value_grid, MODIFIER_TORUS, MODIFIER_MISTY_VEIL, MODIFIER_WATCHTOWER, MODIFIER_DEFENSELESS, MODIFIER_CITY_STATE
from DangerAnalyzer import DangerAnalyzer, ThreatType, ThreatObj
from Models import GatherTreeNode, Move, ContestData
from Directives import Timings
from History import History  # TODO replace these when city contestation
from Territory import TerritoryClassifier
from ArmyTracker import ArmyTracker


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


class EklipZBot(object):
    def __init__(self):
        self.blocking_tile_info: typing.Dict[Tile, ThreatBlockInfo] = {}
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
        self.tiles_captured_this_cycle: typing.Set[Tile] = set()
        self.tiles_evacuated_this_cycle: typing.Set[Tile] = set()
        self.player: Player = Player(-1)
        self.targetPlayerObj: typing.Union[Player, None] = None
        self.city_expand_plan: EarlyExpandUtils.CityExpansionPlan | None = None
        self.force_city_take = False
        self._gen_distances: MapMatrixInterface[int] = None
        self._ally_distances: MapMatrixInterface[int] = None
        self.defend_economy = False
        self._spawn_cramped: bool = False
        self.defending_economy_spent_turns: int = 0
        self.general_safe_func_set = {}
        self.clear_moves_func: typing.Union[None, typing.Callable] = None
        self.surrender_func: typing.Union[None, typing.Callable] = None
        self._map: MapBase | None = None
        self.curPath: Path | None = None
        self.curPathPrio = -1
        self.gathers = 0
        self.attacks = 0

        self.leafMoves: typing.List[Move] = []
        """All leaves that border an enemy or neutral tile, regardless of whether the tile has enough army to capture the adjacent."""
        self.captureLeafMoves: typing.List[Move] = []
        """All leaf moves that can capture the adjacent."""

        self.targetPlayerLeafMoves: typing.List[Move] = []
        """All moves by the target player that could capture adjacent."""

        self.attackFailedTurn = 0
        self.countFailedQuickAttacks = 0
        self.countFailedHighDepthAttacks = 0
        self.largeTilesNearEnemyKings = {}
        self.no_file_logging: bool = False
        self.enemyCities = []
        self.enemy_city_approxed_attacks: typing.Dict[Tile, typing.Tuple[int, int, int]] = {}
        """Contains a mapping from an enemy city, to the approximate (turns, ourAttack, theirDefense)"""

        self.dangerAnalyzer: DangerAnalyzer | None = None
        self.cityAnalyzer: CityAnalyzer | None = None
        self.gatherAnalyzer: GatherAnalyzer | None = None
        self.lastTimingFactor = -1
        self.lastTimingTurn = 0
        self._evaluatedUndiscoveredCache = []
        self.lastTurnStartTime = 0
        self.currently_forcing_out_of_play_gathers: bool = False
        self.force_far_gathers: bool = False
        """If true, far gathers will be FORCED after defense."""
        self.force_far_gathers_turns: int = 0
        """The turns aiming to force for"""
        self.force_far_gathers_sleep_turns: int = 50
        """The number of turns to wait for another far gather for"""

        self.out_of_play_tiles: typing.Set[Tile] = set()

        self.is_rapid_capturing_neut_cities: bool = False

        self.is_winning_gather_cyclic: bool = False

        self.is_all_in_losing = False
        self.all_in_army_advantage_counter: int = 0
        self.all_in_army_advantage_cycle: int = 35
        self.is_all_in_army_advantage: bool = False
        self.all_in_city_behind: bool = False
        """If set to true, will use the expansion cycle timing to all in gather at opp and op cities."""

        self.trigger_player_capture_re_eval: bool = False
        """Set to true to trigger start of turn re-evaluation of stuff due to a player capture"""

        self.giving_up_counter: int = 0
        self.all_in_losing_counter: int = 0
        self.approximate_greedy_turns_avail: int = 0
        self.lastTargetAttackTurn = 0
        self.gather_kill_priorities: typing.Set[Tile] = set()
        self.threat_kill_path: Path | None = None
        """Set this to a threat kill path for post-city-recapture-threat-interception"""

        self.expansion_plan: ExpansionPotential | None = None

        self.enemy_expansion_plan: ExpansionPotential | None = None

        self.enemy_expansion_plan_tile_path_cap_values: typing.Dict[Tile, int] = {}

        self.intercept_plans: typing.Dict[Tile, ArmyInterception] = {}

        self.generalApproximations: typing.List[typing.Tuple[float, float, int, Tile | None]] = []
        """
        List of general location approximation data as averaged by enemy tiles bordering undiscovered and euclid averaged.
        Tuple is (xAvg, yAvg, countUsed, generalTileIfKnown)
        Used for player targeting (we do the expensive approximation only for the target player?)
        This is aids.
        """

        self.opponent_tracker: OpponentTracker = None


        self.lastGeneralGatherTurn = -2
        self.is_blocking_neutral_city_captures: bool = False
        self.was_allowing_neutral_cities_last_turn: bool = True
        self.city_capture_plan_tiles: typing.Set[Tile] = set()
        self.city_capture_plan_last_updated: int = 0
        self._expansion_value_matrix: MapMatrixInterface[float] | None = None
        self.targetPlayer = -1
        self.failedUndiscoveredSearches = 0
        self.largePlayerTiles: typing.List[Tile] = []
        """The large tiles owned by us."""

        self.largeNegativeNeutralTiles: typing.List[Tile] = []
        """Large negative neutral tiles (less than or equal to -2), ordered from most-negative to least-negative."""
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
        self._outbound_all_chat: "Queue[str]" = queue.Queue()
        self._tile_ping_queue: "Queue[Tile]" = queue.Queue()

        self._chat_messages_received: "Queue[ChatUpdate]" = queue.Queue()
        self._tiles_pinged_by_teammate: "Queue[Tile]" = queue.Queue()
        self._communications_sent_cooldown_cache: typing.Dict[str, int] = {}
        self.tiles_pinged_by_teammate_this_turn: typing.Set[Tile] = set()
        self._tiles_pinged_by_teammate_first_25: typing.Set[Tile] = set()
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
        self.defensive_spanning_tree: typing.Set[Tile] = set()

        self.enemy_attack_path: Path | None = None
        """The probable enemy attack path."""

        self.likely_kill_push: bool = False

        self.viewInfo: ViewInfo | None = None

        self._minAllowableArmy = -1
        self.threat: ThreatObj | None = None
        self.best_defense_leaves: typing.List[GatherTreeNode] = []
        self.has_defenseless_modifier: bool = False
        self.has_watchtower_modifier: bool = False
        self.has_misty_veil_modifier: bool = False

        self.is_weird_custom: bool = False

        self.history = History()
        self.timings: Timings | None = None
        self.tileIslandBuilder: TileIslandBuilder = None
        self._should_recalc_tile_islands: bool = False
        self.armyTracker: ArmyTracker = None
        self.army_interceptor: ArmyInterceptor = None
        self.win_condition_analyzer: WinConditionAnalyzer = None
        self.capture_line_tracker: CaptureLineTracker = None
        self.finishing_exploration = True
        self.targetPlayerExpectedGeneralLocation: Tile | None = None

        self.alt_en_gen_positions: typing.List[typing.List[Tile]] = []
        """Decently possible enemy general spawn positions, separated from each other by at least 2 tiles."""

        self._alt_en_gen_position_distances: typing.List[MapMatrixInterface[int] | None] = []
        self.lastPlayerKilled = None
        self.launchPoints: typing.List[Tile] | None = []
        self.locked_launch_point: Tile | None = None
        self.high_fog_risk: bool = False
        self.fog_risk_amount: int = 0
        self.flanking: bool = False
        self.sketchiest_potential_inbound_flank_path: Path | None = None
        self.completed_first_100: bool = False
        """Set to true if the bot is flanking this cycle and should prepare to launch an earlier attack than normal."""

        self.is_lag_massive_map: bool = False

        self.undiscovered_priorities: MapMatrixInterface[float] | None = None
        self._undisc_prio_turn: int = -1
        self._afk_players: typing.List[Player] | None = None
        self._is_ffa_situation: bool | None = None

        self.explored_this_turn = False
        self.board_analysis: BoardAnalyzer | None = None

        # engine stuff
        self.targetingArmy: Army | None = None
        self.cached_scrims: typing.Dict[str, ArmySimResult] = {}
        self.next_scrimming_army_tile: Tile | None = None

        # configuration
        self.disable_engine: bool = True

        self.engine_use_mcts: bool = True
        self.mcts_engine: MctsDUCT = MctsDUCT()
        self.engine_allow_force_incoming_armies_towards: bool = False
        self.engine_allow_enemy_no_op: bool = True
        self.engine_include_path_pre_expansion: bool = True
        self.engine_path_pre_expansion_cutoff_length: int = 5
        self.engine_force_multi_tile_mcts = True
        self.engine_army_nearby_tiles_range: int = 4
        self.engine_mcts_scrim_armies_per_player_limit: int = 2
        self.engine_honor_mcts_expected_score: bool = False
        self.engine_honor_mcts_expanded_expected_score: bool = True
        self.engine_always_include_last_move_tile_in_scrims: bool = True
        self.engine_mcts_move_estimation_net_differential_cutoff: float = -0.9
        """An engine move result below this score will be ignored in some situations. Lower closer to -1.0 to respect more engine moves."""

        self.gather_include_shortest_pathway_as_negatives: bool = False
        self.gather_include_distance_from_enemy_TERRITORY_as_negatives: int = 2  # 4 is bad, confirmed 217-279 in 500 game match after other previous

        # 2 and 3 both perform well, probably need to make the selection method more complicated as there are probably times it should use 2 and times it should use 3.
        self.gather_include_distance_from_enemy_TILES_as_negatives: int = 3  # 3 is definitely too much, confirmed in lots of games. ACTUALLY SEEMS TO BE CONTESTED NOW 3 WON 500 GAME MATCH, won another 500 game match, using 3...

        self.gather_include_distance_from_enemy_general_as_negatives: float = 0.0
        self.gather_include_distance_from_enemy_general_large_map_as_negatives: float = 0.0
        self.gather_use_pcst: bool = False
        # swaps between max iterative and max set, now
        self.gather_use_max_set: bool = False
        """If true, use max-set. If False, use max iterative"""

        self.expansion_force_no_global_visited: bool = False
        self.expansion_force_global_visited_stage_1: bool = True
        self.expansion_use_iterative_negative_tiles: bool = True
        self.expansion_allow_leaf_moves: bool = True
        self.expansion_use_leaf_moves_first: bool = False
        self.expansion_enemy_expansion_plan_inbound_penalty: float = 0.55
        self.expansion_single_iteration_time_cap: float = 0.03  # 0.1 did slightly better than 0.06, but revert to 0.06 if expansion takes too long
        self.expansion_length_weight_offset: float = 0.5
        """Positive means prefer longer paths, slightly...?"""

        self.expansion_allow_gather_plan_extension: bool = True
        """If true, look at leafmoves that do not capture tiles and see if we can gather a capture to their target in 2 moves."""

        self.expansion_always_include_non_terminating_leafmoves_in_iteration: bool = True
        """If true, forces the expansion plan to always consider non-terminating leafmove tiles in one of the iterations."""

        self.expansion_use_iterative_flow: bool = False
        self.expansion_use_legacy: bool = True
        self.expansion_use_tile_islands: bool = False
        self.expansion_full_time_limit: float = 0.15
        """The full time limit for an optimal_expansion cycle. Will be cut short if it would run the move too long."""

        self.expansion_use_cutoff: bool = True
        """The time cap per large tile search when finding expansions"""

        self.expansion_small_tile_time_ratio: float = 1.0
        """The ratio of expansion_single_iteration_time_cap that will be used for each small tile path find iteration."""

        self.behavior_out_of_play_defense_threshold: float = 0.40
        """What ratio of army needs to be outside the behavior_out_of_play_distance_over_shortest_ratio distance to trigger out of play defense."""

        self.behavior_losing_on_economy_skip_defense_threshold: float = 0.0
        """The threshold (where 1.0 means even on economy, and 0.9 means losing by 10%) at which we stop defending general."""

        self.behavior_early_retake_bonus_gather_turns: int = 0
        """This is probably just bad but was currently 3. How long to spend gathering to needToKill tiles around general before switching to main gather."""

        self.behavior_max_allowed_quick_expand: int = 0  # was 7
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

        self.behavior_pre_gather_greedy_leaves_army_ratio_cutoff: float = 0.97
        """Smaller = greedy expansion even when behind on army, larger = only do it when already winning on army"""

        self.behavior_pre_gather_greedy_leaves_offset: int = 0
        """Negative means capture that many extra tiles after hitting the 1.05 ratio. Positive means let them stay a little ahead on tiles."""

        self.info_render_gather_values: bool = False
        """render trunk value etc from actual gather nodes during prunes etc"""

        self.info_render_gather_matrix_values: bool = False
        """render the gather priority matrix values"""

        self.info_render_gather_locality_values: bool = False

        self.info_render_centrality_distances: bool = False
        self.info_render_leaf_move_values: bool = False
        self.info_render_army_emergence_values: bool = False
        self.info_render_board_analysis_choke_widths: bool = False
        self.info_render_board_analysis_zones: bool = True
        self.info_render_city_priority_debug_info: bool = False
        self.info_render_general_undiscovered_prediction_values: bool = False
        self.info_render_tile_deltas: bool = False
        self.info_render_tile_states: bool = False
        self.info_render_expansion_matrix_values: bool = False
        self.info_render_intercept_data: bool = False
        self.info_render_tile_islands: bool = True
        self.info_render_defense_spanning_tree: bool = True

    # STEP2: Stay in EklipZBotV2.py. Tiny object-display helper with no domain logic; keep on the outer bot shell unchanged.
    def __repr__(self):
        return str(self)

    # STEP2: Stay in EklipZBotV2.py. Tiny object-display helper with no domain logic; keep on the outer bot shell unchanged.
    def __str__(self):
        return f'[eklipz_bot {str(self._map)}]'

    # STEP2: Stay in EklipZBotV2.py. Lifecycle stub with no body today; preserve on the shell for compatibility with existing callers.
    def spawnWorkerThreads(self):
        return

    # STEP2: Stay in EklipZBotV2.py. Top-level move orchestration/error handling/history/render prep spanning many modules; keep on shell and have it call extracted helpers.
    def find_move(self, is_lag_move=False) -> Move | None:
        move: Move | None = None
        try:
            move = self.select_move(is_lag_move=is_lag_move)

            if move is not None and move.source.isGeneral and not BotPathingUtils.is_move_safe_valid(self, move, allowNonKill=True):
                logbook.error(f'TRIED TO PERFORM AN IMMEDIATE DEATH MOVE, INVESTIGATE: {move}')
                self.info(f'Tried to perform a move that dies immediately. {move}')
                dangerTiles = BotDefense.get_danger_tiles(self)
                replaced = False
                for dangerTile in dangerTiles:
                    if self.general in dangerTile.movable:
                        altMove = Move(self.general, dangerTile)
                        if not BotPathingUtils.is_move_safe_valid(self, altMove, allowNonKill=True):
                            altMove.move_half = True
                        if BotPathingUtils.is_move_safe_valid(self, altMove, allowNonKill=True):
                            self.info(f'Replacing with danger kill {altMove}')
                            move = altMove
                            replaced = True
                            break

                if not replaced and self.expansion_plan:
                    for opt in self.expansion_plan.all_paths:
                        firstMove = opt.get_first_move()
                        if BotPathingUtils.is_move_safe_valid(self, firstMove, allowNonKill=True):
                            move = firstMove
                            self.info(f'Replacing with exp move {firstMove}')
                            replaced = True
                            break

                if not replaced:
                    self.info(f'Replacing with no-op...')
                    move = None

            if self.teammate_communicator is not None:
                teammate_messages = self.teammate_communicator.produce_teammate_communications()
                for msg in teammate_messages:
                    BotComms.send_teammate_communication(self, msg.message, msg.ping_tile, msg.cooldown, msg.cooldown_detection_on_message_alone, msg.cooldown_key)

            self._map.last_player_index_submitted_move = None
            if move is not None and move.source.player != self.general.player:
                raise AssertionError(f'select_move just returned {move} moving from a tile we didn\'t own...')
            if move is not None:
                self._map.last_player_index_submitted_move = (move.source, move.dest, move.move_half)
        except Exception as ex:
            self.viewInfo.add_info_line(f'BOT ERROR')
            infoStr = traceback.format_exc()
            broken = infoStr.split('\n')
            if len(broken) < 34:
                for line in broken:
                    self.viewInfo.add_info_line(line)
            else:
                for line in broken[:4]:
                    self.viewInfo.add_info_line(line)
                self.viewInfo.add_info_line('...')
                for line in broken[-26:]:
                    self.viewInfo.add_info_line(line)

            raise
        finally:
            # # this fucks performance, need to make it not slow
            # if move is not None and not BotDefense.is_move_safe_against_threats(self, move):
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

            BotPathingUtils.check_cur_path(self)

            if move is not None and self.curPath is not None:
                curPathMove = self.curPath.get_first_move()
                if curPathMove.source == move.source and curPathMove.dest != move.dest:
                    logbook.info("Returned a move using the tile that was curPath, but wasn't the next path move. Resetting path...")
                    self.curPath = None
                    self.curPathPrio = -1

            if self._map.turn not in self.history.move_history:
                self.history.move_history[self._map.turn] = []
            self.history.move_history[self._map.turn].append(move)

            BotRendering.prep_view_info_for_render(self, move)

        return move

    # STEP2: Stay in EklipZBotV2.py. Tiny shell utility used broadly for perf/log timing display; keep local on the bot.
    def get_elapsed(self):
        return round(self.perf_timer.get_elapsed_since_update(self._map.turn), 3)

    # STEP2: Stay in EklipZBotV2.py. Core turn initialization/orchestration entrypoint spanning trackers, analyzers, communications, targeting, and caches; keep on shell and delegate sub-steps later.
    def init_turn(self, secondAttempt=False):
        if self.last_init_turn == self._map.turn:
            return

        self._alt_en_gen_position_distances: typing.List[MapMatrixInterface[int] | None] = [None for _ in self._map.players]

        self._afk_players = None
        self._is_ffa_situation = None

        self.gathers = None
        self.gatherNodes = None

        timeSinceLastUpdate = 0
        now = time.perf_counter()
        if self.lastTurnStartTime != 0:
            timeSinceLastUpdate = now - self.lastTurnStartTime

        self._expansion_value_matrix = None

        self.lastTurnStartTime = now
        logbook.info(f"\n       ~~~\n       Turn {self._map.turn}   ({timeSinceLastUpdate:.3f})\n       ~~~\n")

        if not secondAttempt:
            self.viewInfo.clear_for_next_turn()

        # self.pinged_tiles = set()
        self.was_allowing_neutral_cities_last_turn = not self.is_blocking_neutral_city_captures
        self.is_blocking_neutral_city_captures = False

        if self._map.is_2v2 or len(self._map.get_teammates_no_self(self._map.player_index)) > 0:
            playerTeam = self._map.teams[self._map.player_index]
            self.teammate = [p for p, t in enumerate(self._map.teams) if t == playerTeam and p != self._map.player_index][0]
            teammatePlayer = self._map.players[self.teammate]
            if not teammatePlayer.dead and self._map.generals[self.teammate]:
                self.teammate_general = self._map.generals[self.teammate]
                self.teammate_path = BotPathingUtils.get_path_to_target(self, self.teammate_general, preferEnemy=True, preferNeutral=True)
            else:
                self.teammate_general = None
                self.teammate_path = None

            if self.teammate_communicator is None:
                if self.tile_compressor is None:
                    # self.tile_compressor = ServerTileCompressor(self._map)
                    self.tile_compressor = TileCompressor(self._map)  # use friendly one for now, to debug
                self.teammate_communicator = TeammateCommunicator(self._map, self.tile_compressor, self.board_analysis)
            self.teammate_communicator.begin_next_turn()

        while self._chat_messages_received.qsize() > 0:
            chatUpdate = self._chat_messages_received.get()
            BotComms.handle_chat_message(self, chatUpdate)

        BotTargeting.check_target_player_just_took_city(self)

        # None tells the cache to recalculate this turn to either true or false... Don't change to false, moron.
        self._spawn_cramped = None

        self.last_init_turn = self._map.turn

        if self._map.is_army_bonus_turn:
            for otherPlayer in self._map.players:
                otherPlayer.aggression_factor = otherPlayer.aggression_factor // 2

        if not secondAttempt:
            self.explored_this_turn = False

        if self.defend_economy:
            self.defending_economy_spent_turns += 1

        self.threat_kill_path = None

        self.redGatherTreeNodes = None
        if self.general is not None:
            self._gen_distances = self._map.distance_mapper.get_tile_dist_matrix(self.general)

        if self.teammate_general is not None:
            self._ally_distances = self._map.distance_mapper.get_tile_dist_matrix(self.teammate_general)

        if not self.isInitialized and self._map is not None:
            self.initialize_from_map_for_first_time(self._map)

        if self.trigger_player_capture_re_eval:
            BotEventHandlers.reevaluate_after_player_capture(self, )
            self.trigger_player_capture_re_eval = False

        self._minAllowableArmy = -1
        self.enemyCities = []
        if self._map.turn - 3 > self.lastTimingTurn:
            self.lastTimingFactor = -1

        lastMove = None

        if self._map.turn - 1 in self.history.move_history:
            lastMove = self.history.move_history[self._map.turn - 1][0]

        with self.perf_timer.begin_move_event(f'ArmyTracker Move/Emerge'):
            self.armies_moved_this_turn = []
            # the callback on armies moved will fill the list above back up during armyTracker.scan
            self.armyTracker.scan_movement_and_emergences(lastMove, self._map.turn, self.board_analysis)

        for tile, emergenceTuple in self._map.army_emergences.items():
            emergedAmount, emergingPlayer = emergenceTuple
            if emergedAmount > 0 or not self._map.is_player_on_team_with(tile.delta.oldOwner, tile.player):  # otherwise, this is just the player moving into fog generally.
                self.opponent_tracker.notify_emerged_army(tile, emergingPlayer, emergedAmount)

        # with self.perf_timer.begin_move_event('ArmyTracker bisector'):
        #     self.gather_kill_priorities = BotTargeting.find_fog_bisection_targets(self, )

        # if self._map.turn >= 3 and self.board_analysis.should_rescan:
        # I think reachable tiles isn't built till turn 2? so chokes aren't built properly turn 1

        self.approximate_greedy_turns_avail = BotTimings._get_approximate_greedy_turns_available(self)

        if self.board_analysis.central_defense_point and self.board_analysis.intergeneral_analysis:
            centralPoint = self.board_analysis.central_defense_point
            self.viewInfo.add_targeted_tile(centralPoint, TargetStyle.TEAL, radiusReduction=2)
            if (self.locked_launch_point is None or self.locked_launch_point == self.general) and self.board_analysis.intergeneral_analysis.bMap[centralPoint] < self.board_analysis.inter_general_distance:
                # then the central defense point is further forward than our general, lock it as launch point.
                self.viewInfo.add_info_line(f"locking in central launch point {str(centralPoint)}")
                self.locked_launch_point = centralPoint
                self.recalculate_player_paths(force=True)

        BotCityOps.ensure_reachability_matrix_built(self)

        if self.board_analysis.intergeneral_analysis:
            with self.perf_timer.begin_move_event('City Analyzer'):
                self.cityAnalyzer.re_scan(self.board_analysis)

        with self.perf_timer.begin_move_event('OpponentTracker Analyze'):
            self.opponent_tracker.analyze_turn(self.targetPlayer)

        with self.perf_timer.begin_move_event('Fog annihilation sink'):
            for team in self.teams:
                annihilatedFog = self.opponent_tracker.get_team_annihilated_fog(team)
                if annihilatedFog > 0:
                    for player in self._map.players:
                        if player.team == team:
                            if self.armyTracker.try_find_army_sink(player.index, annihilatedFog, tookNeutCity=BotCityOps.did_player_just_take_fog_city(self, player.index)):
                                break

        with self.perf_timer.begin_move_event('ArmyTracker fog land builder'):
            fogTileCounts = self.opponent_tracker.get_all_player_fog_tile_count_dict()
            for player in self._map.players:
                self.armyTracker.update_fog_prediction(player.index, fogTileCounts[player.index], None)

        self._evaluatedUndiscoveredCache = []
        with self.perf_timer.begin_move_event('get_predicted_target_player_general_location'):
            maxTile: Tile = BotTargeting.get_predicted_target_player_general_location(self)
            self.info(f'DEBUG: en tile {maxTile} get_predicted_target_player_general_location')
            if (self.targetPlayerExpectedGeneralLocation != maxTile or self.shortest_path_to_target_player is None) and maxTile is not None:
                self.targetPlayerExpectedGeneralLocation = maxTile
                self.recalculate_player_paths(force=True)
            if self.targetPlayerExpectedGeneralLocation is None:
                self.targetPlayerExpectedGeneralLocation = self.general

        if self.board_analysis is None:
            return

        if not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 3) % 5 == 0:
            with self.perf_timer.begin_move_event('Inter-general analysis'):
                # also rescans chokes, now.
                self.board_analysis.rebuild_intergeneral_analysis(self.targetPlayerExpectedGeneralLocation, self.armyTracker.valid_general_positions_by_player)

        with self.perf_timer.begin_move_event('get_alt_en_gen_positions'):
            if not self.is_lag_massive_map or (self._map.turn + 2) % 5 == 0:
                altEnGenPositions = None
                enPotentialGenDistances = None
                for player in self._map.players:
                    if player.team != self.player.team:
                        if not self.armyTracker.seen_player_lookup[player.index]:
                            if altEnGenPositions is None:
                                with self.perf_timer.begin_move_event(f'get furthest apart 3 enemy gen locs {player.index}'):
                                    altEnGenPositions, enPotentialGenDistances = BotTargeting._get_furthest_apart_3_enemy_general_locations(self, player.index)
                                self.alt_en_gen_positions[player.index] = altEnGenPositions
                                self._alt_en_gen_position_distances[player.index] = enPotentialGenDistances
                        else:
                            limitNearbyTileRange = -1
                            if len(self._map.players) > 4:
                                limitNearbyTileRange = 12
                            altEnGenPositions = BotTargeting.get_target_player_possible_general_location_tiles_sorted(self, elimNearbyRange=2, player=player.index, cutoffEmergenceRatio=0.3, limitNearbyTileRange=limitNearbyTileRange)
                            self.alt_en_gen_positions[player.index] = altEnGenPositions
                            self._alt_en_gen_position_distances[player.index] = None

        if self._map.is_army_bonus_turn or self._should_recalc_tile_islands:
            with self.perf_timer.begin_move_event('TileIsland recalc'):
                self.tileIslandBuilder.recalculate_tile_islands(self.targetPlayerExpectedGeneralLocation)
                self._should_recalc_tile_islands = False
        else:
            # EXPANSION RELIES ON TILE ISLANDS BEING ACCURATE OR ELSE IT WILL DIVE INTO CORNERS WHERE IT ALREADY CUT OFF ITS RECAPTURE PATH BECAUSE IT THINKS IT CAN RECAPTURE USING THE TILES ITS COMING FROM
            with self.perf_timer.begin_move_event('TileIsland update'):
                self.tileIslandBuilder.update_tile_islands(self.targetPlayerExpectedGeneralLocation)

        self.armyTracker.verify_player_tile_and_army_counts_valid()

        if not BotStateQueries.is_all_in(self) and (not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 5) % 5 == 0):
            with self.perf_timer.begin_move_event('WinConditionAnalyzer Analyze'):
                self.win_condition_analyzer.analyze(self.targetPlayer, self.targetPlayerExpectedGeneralLocation)

                self.viewInfo.add_stats_line(f'WinConns: {", ".join([str(c).replace("WinCondition.", "") for c in self.win_condition_analyzer.viable_win_conditions])}')

                for tile in self.win_condition_analyzer.defend_cities:
                    self.viewInfo.add_targeted_tile(tile, TargetStyle.GREEN, radiusReduction=4)

                for tile in self.win_condition_analyzer.contestable_cities:
                    self.viewInfo.add_targeted_tile(tile, TargetStyle.PURPLE, radiusReduction=4)

        if not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 4) % 5 == 0:
            if self.territories.should_recalculate(self._map.turn):
                with self.perf_timer.begin_move_event('Territory Scan'):
                    self.territories.scan()

        for path in self.armyTracker.fogPaths:
            self.viewInfo.color_path(PathColorer(path, 255, 84, 0, 255, 30, 150))

        self.cached_scrims = {}

    # STEP2: Stay in EklipZBotV2.py. High-level pre-move orchestration that coordinates timings, path recalculation, out-of-play mode, all-in state, and dropped-move recovery across many domains.
    def perform_move_prep(self, is_lag_move: bool = False):
        with self.perf_timer.begin_move_event('scan_map_for_large_tiles_and_leaf_moves()'):
            self.scan_map_for_large_tiles_and_leaf_moves()

        if self.timings and self.timings.get_turn_in_cycle(self._map.turn) == 0:
            BotTimings.timing_cycle_ended(self, )

        if self.curPath is not None:
            nextMove = self.curPath.get_first_move()

            if nextMove and nextMove.dest is not None and nextMove.dest.isMountain:
                self.viewInfo.add_info_line(f'Killing curPath because it moved through a mountain.')
                self.curPath = None

        wasFlanking = self.flanking
        if self.target_player_gather_path is None or self.target_player_gather_path.tail.tile != self.targetPlayerExpectedGeneralLocation:
            with self.perf_timer.begin_move_event('No path recalculate_player_paths'):
                self.recalculate_player_paths(force=True)

        if self.timings is None:
            # needed to not be none for holding fresh cities
            with self.perf_timer.begin_move_event('Recalculating Timings first time...'):
                self.timings = BotTimings.get_timings(self)

        # self.check_if_need_to_gather_longer_to_hold_fresh_cities()

        # allowOutOfPlayCheck = self._map.cols * self._map.rows < 400 and len(self.player.cities) < 7
        oldOutOfPlay = self.army_out_of_play
        cycleRemaining = self.timings.get_turns_left_in_cycle(self._map.turn)
        allowSwapToOutOfPlay = cycleRemaining > 15 or (self.opponent_tracker.winning_on_army(byRatio=1.2) and self.opponent_tracker.winning_on_economy(byRatio=1.2)) or self.army_out_of_play
        self.army_out_of_play = allowSwapToOutOfPlay and BotExpansionOps.check_army_out_of_play_ratio(self)
        if not is_lag_move and not wasFlanking and self.army_out_of_play != oldOutOfPlay:
            with self.perf_timer.begin_move_event('flank/outOfPlay recalc_player_paths'):
                self.recalculate_player_paths(force=True)

        if self.timings is None or self.timings.should_recalculate(self._map.turn):
            with self.perf_timer.begin_move_event('Recalculating Timings...'):
                self.timings = BotTimings.get_timings(self)

        if BotCombatOps.determine_should_winning_all_in(self):
            wasAllIn = self.is_all_in_army_advantage
            self.is_all_in_army_advantage = True
            if not wasAllIn:
                self.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0)
                self.city_expand_plan = None
                self.enemy_expansion_plan = None
                cycle = 50
                if self._map.players[self.general.player].tileCount - self.target_player_gather_path.length < 60:
                    cycle = 30
                BotTimings.set_all_in_cycle_to_hit_with_current_timings(self, cycle)
                self.viewInfo.add_info_line(f"GOING ARMY ADV TEMP ALL IN CYCLE {cycle}, PRESERVING CURPATH")
                # self.timings = BotTimings.get_timings(self)
                if self.targetPlayerObj.general is not None and not self.targetPlayerObj.general.visible:
                    self.targetPlayerObj.general.army = 3
                    BotEventHandlers.clear_fog_armies_around(self, self.targetPlayerObj.general)

                if not is_lag_move:
                    with self.perf_timer.begin_move_event('all in change recalculate_player_paths'):
                        self.recalculate_player_paths(force=True)
            # self.all_in_army_advantage_counter += 1
        elif self.is_all_in_army_advantage and not self.all_in_city_behind:
            self.is_all_in_army_advantage = False
            self.all_in_army_advantage_counter = 0

        # This is the attempt to resolve the 'dropped packets devolve into unresponsive bot making random moves
        # even though it thinks it is making sane moves' issue. If we seem to have dropped a move, clear moves on
        # the server before sending more moves to prevent moves from backing up and getting executed later.
        if self._map.turn - 1 in self.history.move_history:
            if BotRepetition.dropped_move(self):
                matrix = MapMatrix(self._map, True, emptyVal=False)
                self.viewInfo.add_map_zone(matrix, (255, 200, 0), alpha=40)
                msg = "(Dropped move)... Sending clear_moves..."
                self.viewInfo.add_info_line(msg)
                logbook.info(
                    f"\n\n\n^^^^^^^^^VVVVVVVVVVVVVVVVV^^^^^^^^^^^^^VVVVVVVVV^^^^^^^^^^^^^\nD R O P P E D   M O V E ? ? ? ? {msg}\n^^^^^^^^^VVVVVVVVVVVVVVVVV^^^^^^^^^^^^^VVVVVVVVV^^^^^^^^^^^^^")
                if self.clear_moves_func:
                    with self.perf_timer.begin_move_event('Sending clear_moves due to dropped move'):
                        self.clear_moves_func()
            else:
                lastMove = self.history.move_history[self._map.turn - 1][0]
                if lastMove is not None:
                    if self._map.is_player_on_team_with(lastMove.dest.delta.oldOwner, self.general.player):
                        self.tiles_gathered_to_this_cycle.add(lastMove.dest)
                        if lastMove.dest.isCity:
                            self.cities_gathered_this_cycle.discard(lastMove.dest)
                    elif lastMove.dest.player == self.general.player:
                        self.tiles_captured_this_cycle.add(lastMove.dest)

                    if not lastMove.move_half:
                        self.tiles_gathered_to_this_cycle.discard(lastMove.source)
                        self.tiles_evacuated_this_cycle.add(lastMove.source)
                        if lastMove.source.isCity:
                            self.cities_gathered_this_cycle.add(lastMove.source)
                    if self.curPath and self.curPath.get_first_move() and self.curPath.get_first_move().source == lastMove.source:
                        self.curPath.pop_first_move()
                if self.force_far_gathers:
                    self.force_far_gathers_turns -= 1
                else:
                    self.force_far_gathers_sleep_turns -= 1

    # STEP2: Stay in EklipZBotV2.py. Primary turn move-selection entrypoint that sequences prep, lag handling, path recalculation, and final pick; keep as shell orchestration.
    def select_move(self, is_lag_move=False) -> Move | None:
        self.init_turn()

        self.tiles_pinged_by_teammate_this_turn = set()
        while self._tiles_pinged_by_teammate.qsize() > 0:
            tile = self._tiles_pinged_by_teammate.get()
            self.viewInfo.add_targeted_tile(tile, TargetStyle.GREEN)
            self.tiles_pinged_by_teammate_this_turn.add(tile)
            if self._map.turn < 50:
                self._tiles_pinged_by_teammate_first_25.add(tile)

        if is_lag_move:
            self.viewInfo.add_info_line(f'skipping some stuff because is_lag_move == True')
            matrix = MapMatrix(self._map, True, emptyVal=False)
            self.viewInfo.add_map_zone(matrix, (250, 140, 0), alpha=25)

        if self._map.turn <= 1:
            # bypass divide by 0 error instead of fixing it
            return None

        if self._map.remainingPlayers == 1:
            return None

        self.perform_move_prep(is_lag_move=is_lag_move)

        if is_lag_move and self.curPath and self.is_lag_massive_map:
            moves = self.curPath.get_move_list()
            for move in moves:
                if move.source.player == self.general.player and move.source.army > 3:
                    self.info(f'LAG CONTINUING PLANNED MOVES {move}')
                    return move

        if self._map.turn - 1 in self.history.move_history:
            lastMove = self.history.move_history[self._map.turn - 1][0]
            if BotRepetition.dropped_move(self) and self._map.turn <= 50 and lastMove is not None:
                if lastMove.source != self.general:
                    self.viewInfo.add_info_line(f're-performing dropped first-25 non-general move {str(lastMove)}')
                    return lastMove
                else:
                    # force reset the expansion plan so we recalculate from general.
                    self.city_expand_plan = None

        if not is_lag_move and not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 2) % 5 == 0:
            with self.perf_timer.begin_move_event("recalculating player path"):
                self.recalculate_player_paths()

        if not BotStateQueries.is_still_ffa_and_non_dominant(self):
            BotTimings.prune_timing_split_if_necessary(self)

        move = self.pick_move_after_prep(is_lag_move)

        if move and self.curPath and move.source in self.curPath.tileSet and move != self.curPath.get_first_move():
            self.curPath = None

        return move

    # STEP2: Stay in EklipZBotV2.py. Central post-prep decision tree coordinating combat, defense, city capture, expansion, and continuation logic; keep on shell and delegate subroutines out.
    def pick_move_after_prep(self, is_lag_move=False):
        with self.perf_timer.begin_move_event('calculating general danger / threats'):
            BotDefense.calculate_general_danger(self)

        if self._map.turn <= 4:
            if self._map.has_city_state:
                for t in self.general.movable:
                    if t.isCity and t.isNeutral and t.army == -1:
                        return Move(self.general, t)
        BotPathingUtils.clean_up_path_before_evaluating(self)

        if self.curPathPrio >= 0:
            logbook.info(f"curPathPrio: {str(self.curPathPrio)}")

        threat = None

        if self.dangerAnalyzer.fastestThreat is not None:
            threat = self.dangerAnalyzer.fastestThreat

        if self.dangerAnalyzer.fastestAllyThreat is not None and (threat is None or self.dangerAnalyzer.fastestAllyThreat.turns < threat.turns):
            if BotDefense.determine_should_defend_ally(self, ):
                threat = self.dangerAnalyzer.fastestAllyThreat

        if self.dangerAnalyzer.fastestCityThreat is not None and threat is None:
            threat = self.dangerAnalyzer.fastestCityThreat

        if threat is None and not self.giving_up_counter > 30 and self.dangerAnalyzer.fastestVisionThreat is not None:
            threat = self.dangerAnalyzer.fastestVisionThreat

        #  # # # #   ENEMY KING KILLS
        with self.perf_timer.begin_move_event('Checking for king kills and races'):
            killMove, kingKillPath, raceChance = BotCombatOps.check_for_king_kills_and_races(self, threat)
            if killMove is not None:
                return killMove

        defenseCriticalTileSet = set()
        if self.teammate_general is not None and self.teammate_general.player in self._map.teammates:
            for army in self.armyTracker.armies.values():
                if army.player in self._map.teammates:
                    if army.last_moved_turn > self._map.turn - 3:
                        defenseCriticalTileSet.add(army.tile)
                    if army.tile.delta.armyDelta != 0 and (army.tile.delta.oldOwner != army.player or army.tile.delta.oldArmy < army.tile.army):
                        defenseCriticalTileSet.add(army.tile)

        self.threat = threat

        BotCombatOps.check_should_be_all_in_losing(self)

        if self.is_all_in_losing:
            logbook.info(f"~~~ ___ {self.get_elapsed()}\n   YO WE ALL IN DAWG\n~~~ ___")

        # if not self.isAllIn() and (threat.turns > -1 and self.dangerAnalyzer.anyThreat):
        #    armyAmount = (self.general_min_army_allowable() + enemyNearGen) * 1.1 if threat is None else threat.threatValue + general.army + 1

        if not BotStateQueries.is_all_in(self) and (not is_lag_move and not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 2) % 5 == 0):
            with self.perf_timer.begin_move_event('ENEMY Expansion quick check'):
                self.enemy_expansion_plan = BotExpansionOps.build_enemy_expansion_plan(self, timeLimit=0.007, pathColor=(255, 150, 130))

        self.intercept_plans = BotDefense.build_intercept_plans(self, defenseCriticalTileSet)
        for i, interceptPlan in enumerate(self.intercept_plans.values()):
            BotRendering.render_intercept_plan(self, interceptPlan, colorIndex=i)

        if not BotStateQueries.is_all_in(self) and not is_lag_move:
            with self.perf_timer.begin_move_event('Expansion quick check'):
                redoTimings = False
                if self.expansion_plan is None or self.timings is None or self._map.turn >= self.timings.nextRecalcTurn:
                    redoTimings = True

                negs = {t for t in defenseCriticalTileSet if not self._map.is_tile_on_team_with(t, self.targetPlayer)}
                BotExpansionOps._add_expansion_threat_negs(self, negs)
                checkCityRoundEndPlans = self._map.is_army_bonus_turn
                self.expansion_plan = BotExpansionOps.build_expansion_plan(self, timeLimit=0.012, expansionNegatives=negs, pathColor=(150, 100, 150), includeExtraGenAndCityArmy=checkCityRoundEndPlans)

                self.capture_line_tracker.process_plan(self.targetPlayer, self.expansion_plan)

                if redoTimings:
                    self.timings = BotTimings.get_timings(self)

        defenseSavePath: Path | None = None
        if not self.is_all_in_losing and threat is not None and threat.threatType != ThreatType.Vision:
            with self.perf_timer.begin_move_event(f'THREAT DEFENSE {threat.turns} {str(threat.path.start.tile)}'):
                defenseMove, defenseSavePath = BotDefense.get_defense_moves(self, defenseCriticalTileSet, kingKillPath, raceChance)

                if defenseSavePath is not None:
                    self.viewInfo.color_path(PathColorer(defenseSavePath, 255, 100, 255, 200))
                if defenseMove is not None:
                    if not BotRepetition.detect_repetition(self, defenseMove, turns=6, numReps=3) or (threat.threatType == ThreatType.Kill and threat.path.tail.tile.isGeneral):
                        if defenseMove.source in self.largePlayerTiles and self.targetingArmy is None:
                            logbook.info(f'threatDefense overriding targetingArmy with {str(threat.path.start.tile)}')
                            self.targetingArmy = self.get_army_at(threat.path.start.tile)
                        return defenseMove
                    else:
                        self.viewInfo.add_info_line(f'BYPASSING DEF REP {str(defenseMove)} :(')

        if self._map.turn < 100:
            isNoExpansionGame = ((len(self._map.swamps) > 0 or len(self._map.deserts) > 0) and BotExpansionOps.get_unexpandable_ratio(self, ) > 0.7)
            if isNoExpansionGame or self._map.is_low_cost_city_game:
                # # assume we must take cities instead, then.
                # if self._map.walled_city_base_value is None or self._map.walled_city_base_value > 10:
                #     self._map.set_walled_cities(10)
                if self._map.turn < 30:
                    qkPath, shouldWait = BotCityOps._check_should_wait_city_capture(self, )
                    if qkPath is not None:
                        self.info(f'f15 QUICK KILL CITY {qkPath}')
                        return qkPath.get_first_move()
                    if shouldWait:
                        self.info(f'f15 wants to wait on city')
                        return None
                if not self.army_out_of_play:
                    path, move = BotCityOps.capture_cities(self, set(), forceNeutralCapture=True)
                    if move is not None:
                        self.info(f'f50 City cap instead... {move}')
                        self.city_expand_plan = None
                        return move
                    if path is not None:
                        self.info(f'f50 City cap instead... {path}')
                        self.city_expand_plan = None
                        return BotPathingUtils.get_first_path_move(self, path)

        if self._map.turn < 50:
            if not self._map.is_low_cost_city_game and not self._map.modifiers_by_id[MODIFIER_CITY_STATE]:
                return BotExpansionOps.make_first_25_move(self)
            else:
                self.info(f'Byp f25 bc weird_custom {self.is_weird_custom} (walled_city {self._map.is_walled_city_game} or low_cost_city {self._map.is_low_cost_city_game}) or cityState {self._map.modifiers_by_id[MODIFIER_CITY_STATE]}')

        if self._map.turn < 250 and self._map.remainingPlayers > 3:
            with self.perf_timer.begin_move_event('Ffa Turtle Move'):
                move = BotExpansionOps.look_for_ffa_turtle_move(self)
            if move is not None:
                return move
        if self.expansion_plan:
            for t in self.expansion_plan.blocking_tiles:
                if t not in defenseCriticalTileSet:
                    defenseCriticalTileSet.add(t)
                    self.viewInfo.add_info_line(f'{t} added to defense crit from expPlan.blocking')

        if self._map.is_army_bonus_turn or self.defensive_spanning_tree is None:
            with self.perf_timer.begin_move_event('defensive spanning tree'):
                self.defensive_spanning_tree = BotDefense._get_defensive_spanning_tree(self, defenseCriticalTileSet, BotGatherOps.get_gather_tiebreak_matrix(self, ))

        if kingKillPath is not None and threat.threatType == ThreatType.Kill:
            attackingWithSavePath = defenseSavePath is not None and defenseSavePath.start.tile == kingKillPath.start.tile
            attackingWithRestrictedArmyMovement = False
            blocks = self.blocking_tile_info.get(kingKillPath.start.tile)
            if blocks:
                if kingKillPath.start.next.tile in blocks.blocked_destinations:
                    attackingWithRestrictedArmyMovement = True
            if not attackingWithSavePath and not attackingWithRestrictedArmyMovement:
                if defenseSavePath is not None:
                    logbook.info(f"savePath was {str(defenseSavePath)}")
                else:
                    logbook.info("savePath was NONE")
                self.info(f"    Delayed defense kingKillPath.  {str(kingKillPath)}")
                self.viewInfo.color_path(PathColorer(kingKillPath, 158, 158, 158, 255, 10, 200))

                return Move(kingKillPath.start.tile, kingKillPath.start.next.tile)
            else:
                if defenseSavePath is not None:
                    logbook.info(f"savePath was {str(defenseSavePath)}")
                else:
                    logbook.info("savePath was NONE")
                logbook.info(
                    f"savePath tile was also kingKillPath tile, skipped kingKillPath {str(kingKillPath)}")

        with self.perf_timer.begin_move_event('ARMY SCRIMS'):
            armyScrimMove = BotCombatOps.check_for_army_movement_scrims(self)
            if armyScrimMove is not None:
                # already logged
                return armyScrimMove

        with self.perf_timer.begin_move_event('DANGER TILES'):
            dangerTileKillMove = BotDefense.check_for_danger_tile_moves(self)
            if dangerTileKillMove is not None:
                return dangerTileKillMove  # already logged to info

        with self.perf_timer.begin_move_event('Flank defense / Vision expansion HIGH PRI'):
            flankDefMove = BotDefense.find_flank_defense_move(self, defenseCriticalTileSet, highPriority=True)
            if flankDefMove:
                return flankDefMove

        if not self.is_all_in_losing:
            with self.perf_timer.begin_move_event('get_quick_kill_on_enemy_cities'):
                path = BotCityOps.get_quick_kill_on_enemy_cities(self, defenseCriticalTileSet)
            if path is not None:
                self.info(f'Quick Kill on enemy city: {str(path)}')
                self.curPath = path
                if self.curPath.length > 1:
                    self.curPath = self.curPath.get_subsegment(path.length - 2)
                move = BotPathingUtils.get_first_path_move(self, path)
                if not BotRepetition.detect_repetition(self, move):
                    return move

        if self.force_far_gathers and self.force_far_gathers_turns > 0:
            with self.perf_timer.begin_move_event(f'FORCE_FAR_GATHERS {self.force_far_gathers_turns}'):
                roughTurns = self.force_far_gathers_turns
                targets = None
                if self.enemy_attack_path:
                    targets = [t for t in self.enemy_attack_path.get_subsegment(int(self.enemy_attack_path.length / 2)).tileList if self._map.is_tile_enemy(t) or not t.visible]
                    self.info(f'FFG using enemy attack path {targets}')
                if not targets or len(targets) == 0:
                    targets = self.win_condition_analyzer.contestable_cities.copy()
                    self.info(f'FFG using contestable cities {targets}')
                if not targets or len(targets) == 0:
                    targets = self.win_condition_analyzer.defend_cities.copy()
                    self.info(f'FFG using defend cities {targets}')
                if (not targets or len(targets) == 0) and self.target_player_gather_path:
                    targets = [t for t in self.target_player_gather_path.get_subsegment(self.target_player_gather_path.length // 2, end=True).tileList if self._map.is_tile_enemy(t) or not t.visible]
                    self.info(f'FFG using end of target path {targets}')
                if not targets or len(targets) == 0:
                    targets = [self.general]
                    self.info(f'FFG fell back to general...? {targets}')
                for t in targets:
                    self.viewInfo.add_targeted_tile(t, TargetStyle.ORANGE)
                minTurns = roughTurns - 15
                maxTurns = roughTurns + 15

                if isinstance(self.curPath, GatherCapturePlan):
                    firstMove = self.curPath.get_first_move()

                    if firstMove is not None and firstMove.source.isSwamp or maxTurns >= self.curPath.length >= minTurns:
                        self.info(f'CONTINUING FFG plan')
                        BotPathingUtils.clean_up_path_before_evaluating(self)
                        return self.curPath.get_first_move()

                gcp = Gather.gather_approximate_turns_to_tiles(
                    self._map,
                    targets,
                    roughTurns,
                    self.player.index,
                    minTurns=minTurns,
                    maxTurns=maxTurns,
                    gatherMatrix=BotGatherOps.get_gather_tiebreak_matrix(self, ),
                    captureMatrix=BotExpansionOps.get_expansion_weight_matrix(self, ),
                    negativeTiles=defenseCriticalTileSet,
                    prioritizeCaptureHighArmyTiles=True,
                    useTrueValueGathered=False,
                    includeGatherPriorityAsEconValues=True,
                    timeLimit=min(0.05, BotTimings.get_remaining_move_time(self, ))
                )

                if gcp is None:
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    useTrueVal = False
                    gathMat = BotGatherOps.get_gather_tiebreak_matrix(self, )
                    move, valGathered, turnsUsed, gatherNodes = BotGatherOps.get_gather_to_target_tiles(
                        self,
                        targets,
                        0.05,
                        maxTurns,
                        defenseCriticalTileSet,
                        useTrueValueGathered=useTrueVal,
                        maximizeArmyGatheredPerTurn=True,
                        priorityMatrix=gathMat,
                    )

                    if gatherNodes:
                        gcp = GatherCapturePlan.build_from_root_nodes(
                            self._map,
                            gatherNodes,
                            defenseCriticalTileSet,
                            self.general.player,
                            onlyCalculateFriendlyArmy=useTrueVal,
                            priorityMatrix=gathMat,
                            includeGatherPriorityAsEconValues=True,
                            includeCapturePriorityAsEconValues=True,
                        )
                if gcp is not None:
                    move = gcp.get_first_move()
                    self.gatherNodes = gcp.root_nodes
                    self.info(f'pcst FORCE_FAR_GATHERS {move} min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    self.curPath = gcp
                    return move
                else:
                    self.info(f'FAILED FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')

        if not self.is_weird_custom:
            second = BotExpansionOps.make_second_25_move(self)
            if second:
                return second

        numTilesAdjKing = SearchUtils.count(self.general.adjacents, lambda tile: tile.army > 2 and self._map.is_tile_enemy(tile))
        if numTilesAdjKing == 1:
            visionTiles = filter(lambda tile: self._map.is_tile_enemy(tile) and tile.army > 2, self.general.adjacents)
            for annoyingTile in visionTiles:
                playerTilesAdjEnemyVision = [x for x in filter(lambda threatAdjTile: threatAdjTile.player == self.general.player and threatAdjTile.army > annoyingTile.army // 2 and threatAdjTile.army > 1, annoyingTile.movable)]
                if len(playerTilesAdjEnemyVision) > 0:
                    largestAdjTile = max(playerTilesAdjEnemyVision, key=lambda myTile: myTile.army)
                    if largestAdjTile and (not largestAdjTile.isGeneral or largestAdjTile.army + 1 > annoyingTile.army):
                        nukeMove = Move(largestAdjTile, annoyingTile)
                        self.info(f'Nuking general-adjacent vision tile {str(nukeMove)}, targeting it as targeting army.')
                        self.targetingArmy = self.get_army_at(annoyingTile)
                        return nukeMove

        afkPlayerMove = BotExplorationOps.get_move_if_afk_player_situation(self)
        if afkPlayerMove:
            return afkPlayerMove

        BotPathingUtils.check_cur_path(self)

        # needs to happen before defend_economy because defend_economy uses the properties set by this method.
        BotDefense.check_fog_risk(self, )

        # if ahead on economy, but not %30 ahead on army we should play defensively
        self.defend_economy = BotDefense.should_defend_economy(self, defenseCriticalTileSet)

        if WinCondition.DefendContestedFriendlyCity in self.win_condition_analyzer.viable_win_conditions:
            with self.perf_timer.begin_move_event(f'Getting city preemptive defense {str(self.win_condition_analyzer.defend_cities)}'):
                cityDefenseMove = BotCityOps.get_city_preemptive_defense_move(self, defenseCriticalTileSet)
            if cityDefenseMove is not None:
                self.info(f'City preemptive defense move! {str(cityDefenseMove)}')
                return cityDefenseMove

        with self.perf_timer.begin_move_event(f'capture_cities'):
            (cityPath, gatherMove) = BotCityOps.capture_cities(self, defenseCriticalTileSet)
        if gatherMove is not None:
            logbook.info(f"{self.get_elapsed()} returning capture_cities gatherMove {str(gatherMove)}")
            if cityPath is not None:
                self.curPath = cityPath
            return gatherMove
        elif cityPath is not None:
            logbook.info(f"{self.get_elapsed()} returning capture_cities cityPath {str(cityPath)}")
            # self.curPath = cityPath
            return BotPathingUtils.get_first_path_move(self, cityPath)

        # AFTER city capture because of test_should_contest_city_not_intercept_it. If this causes problems, then NEED to feed city attack/defense into the RoundPlanner and stop this hacky order shit...
        if self.expansion_plan and self.expansion_plan.includes_intercept and not self.is_all_in_losing:
            move = self.expansion_plan.selected_option.get_first_move()
            if not BotRepetition.detect_repetition(self, move):
                self.info(f'Pass thru EXP int! {move} {self.expansion_plan.selected_option}')
                return move

        with self.perf_timer.begin_move_event('try_get_enemy_territory_exploration_continuation_move'):
            expNegs = set(defenseCriticalTileSet)
            if WinCondition.DefendEconomicLead in self.win_condition_analyzer.viable_win_conditions:
                expNegs.update(self.win_condition_analyzer.defend_cities)
                expNegs.update(self.win_condition_analyzer.contestable_cities)
            largeArmyExpContinuationMove = BotExpansionOps.try_get_enemy_territory_exploration_continuation_move(self, expNegs)

        if largeArmyExpContinuationMove is not None and not BotRepetition.detect_repetition(self, largeArmyExpContinuationMove):
            # already logged
            return largeArmyExpContinuationMove

        if 50 <= self._map.turn < 75:
            move = BotExpansionOps.try_gather_tendrils_towards_enemy(self)
            if move is not None:
                return move

        if self.curPath is not None:
            move = BotPathingUtils.continue_cur_path(self, threat, defenseCriticalTileSet)
            if move is not None:
                return move  # already logged

        exploreMove = BotExpansionOps.try_find_exploration_move(self, defenseCriticalTileSet)
        if exploreMove is not None:
            return exploreMove  # already logged

        allInMove = BotCombatOps.get_all_in_move(self, defenseCriticalTileSet)
        if allInMove:
            # already logged
            return allInMove

        expMove = BotExpansionOps.try_find_main_timing_expansion_move_if_applicable(self, defenseCriticalTileSet)
        if expMove is not None:
            return expMove  # already logged

        needToKillTiles = list()
        if not self.timings.disallowEnemyGather and not self.is_all_in_losing:
            needToKillTiles = BotCombatOps.find_key_enemy_vision_tiles(self, )
            for tile in needToKillTiles:
                self.viewInfo.add_targeted_tile(tile, TargetStyle.RED)

        # LEAF MOVES for the first few moves of each cycle
        timingTurn = self.timings.get_turn_in_cycle(self._map.turn)
        quickExpTimingTurns = self.timings.quickExpandTurns - self._map.turn % self.timings.cycleTurns

        earlyRetakeTurns = quickExpTimingTurns + self.behavior_early_retake_bonus_gather_turns - self._map.turn % self.timings.cycleTurns

        if (not BotStateQueries.is_all_in(self)
                and self._map.remainingPlayers <= 3
                and earlyRetakeTurns > 0
                and len(needToKillTiles) > 0
                and timingTurn >= self.timings.quickExpandTurns
        ):
            actualGatherTurns = earlyRetakeTurns

            with self.perf_timer.begin_move_event(f'early retake turn gather?'):
                gatherNodes = Gather.knapsack_depth_gather(
                    self._map,
                    list(needToKillTiles),
                    actualGatherTurns,
                    negativeTiles=defenseCriticalTileSet,
                    searchingPlayer=self.general.player,
                    incrementBackward=False,
                    viewInfo=self.viewInfo if self.info_render_gather_values else None,
                    ignoreStartTile=True,
                    useTrueValueGathered=True)
            self.gatherNodes = gatherNodes
            move = self.get_tree_move_default(gatherNodes)
            if move is not None:
                self.info(
                    f"NeedToKillTiles for turns {earlyRetakeTurns} ({actualGatherTurns}) in quickExpand. Move {move}")
                return move

        with self.perf_timer.begin_move_event('Flank defense / Vision expansion low pri'):
            flankDefMove = BotDefense.find_flank_defense_move(self, defenseCriticalTileSet, highPriority=False)
            if flankDefMove:
                return flankDefMove

        if self.defend_economy:
            move = BotCombatOps.try_find_army_out_of_position_move(self, defenseCriticalTileSet)
            if move is not None:
                return move  # already logged

        cyclicAllInMove = BotCombatOps.try_get_cyclic_all_in_move(self, defenseCriticalTileSet)
        if cyclicAllInMove:
            return cyclicAllInMove  # already logged

        if not BotStateQueries.is_all_in(self) and not self.defend_economy and quickExpTimingTurns > 0:
            move = BotExpansionOps.try_gather_tendrils_towards_enemy(self, quickExpTimingTurns)
            if move is not None:
                return move

            moves = BotExpansionOps.prioritize_expansion_leaves(self, self.leafMoves)
            if len(moves) > 0:
                move = moves[0]
                self.info(f"quickExpand leafMove {move}")
                return move

        expMove = BotExpansionOps._get_expansion_plan_quick_capture_move(self, defenseCriticalTileSet)
        if expMove:
            self.info(f"quickCap move {expMove}")
            return expMove

        with self.perf_timer.begin_move_event(f'MAIN GATHER OUTER, negs {[str(t) for t in defenseCriticalTileSet]}'):
            gathMove = BotGatherOps.try_find_gather_move(self, threat, defenseCriticalTileSet, self.leafMoves, needToKillTiles)

        if gathMove is not None:
            # already logged / perf countered internally
            return gathMove

        isFfaAfkScenario = self._map.remainingCycleTurns > 14 and BotStateQueries.is_still_ffa_and_non_dominant(self) and self._map.cycleTurn < self.timings.launchTiming and not self._map.is_walled_city_game
        if isFfaAfkScenario:
            self.info(f'FFA AFK')
            return None

        # NOTE NOTHING PAST THIS POINT CAN TAKE ANY EXTRA TIME

        if not BotStateQueries.is_all_in(self):
            with self.perf_timer.begin_move_event(f'No move found leafMove'):
                leafMove = BotExpansionOps.find_leaf_move(self, self.leafMoves)
            if leafMove is not None:
                self.info(f"No move found leafMove? {str(leafMove)}")
                return leafMove

        self.curPathPrio = -1
        if BotTimings.get_remaining_move_time(self, ) > 0.01:
            with self.perf_timer.begin_move_event('FOUND NO MOVES GATH'):
                self.info(f'No move found main gather')
                targets = []
                if self.targetPlayer >= 0:
                    targets.extend(self.targetPlayerObj.tiles)
                else:
                    targets.extend(t for t in self._map.get_all_tiles() if t.player == -1 and not t.isObstacle)
                negatives = defenseCriticalTileSet.copy()
                negatives.update(self.target_player_gather_targets)
                turns = self.timings.launchTiming - self.timings.get_turn_in_cycle(self._map.turn)
                gathMove = BotGatherOps.timing_gather(
                self,
                targets,
                negatives,
                    None,
                    force=True,
                    pruneToValuePerTurn=True,
                    useTrueValueGathered=True,
                    includeGatherTreeNodesThatGatherNegative=False,
                    targetTurns=turns,
                    logStuff=True)
                if gathMove:
                    return gathMove
        move = None
        value = -1

        if move is None:
            self.info("Found-no-moves-gather found no move, random expansion move?")
            if self.expansion_plan and self.expansion_plan.selected_option:
                for opt in self.expansion_plan.all_paths:
                    move = opt.get_first_move()
                    if move is not None and move.source.player == self._map.player_index and move.source.army > 1:
                        self.curPath = opt
                        return move

        elif BotPathingUtils.is_move_safe_valid(self, move):
            self.info(f"Found-no-moves-gather found {value}v/{turns}t gather, using {move}")
            return move
        else:
            self.info(
                f"Found-no-moves-gather move {move} was not safe or valid!")

        return None

    # STEP2: Stay in EklipZBotV2.py or move very late to BotTargeting as a tiny legacy distance helper. Euclidean nearest-enemy-general approximation utility.
    def getDistToEnemy(self, tile):
        dist = 1000
        for i in range(len(self._map.generals)):
            gen = self._map.generals[i]
            genDist = 0
            if gen is not None:
                genDist = self._map.euclidDist(gen.x, gen.y, tile.x, tile.y)
            elif self.generalApproximations[i][2] > 0:
                genDist = self._map.euclidDist(self.generalApproximations[i][0], self.generalApproximations[i][1], tile.x, tile.y)

            if genDist < dist:
                dist = genDist
        return dist


    # STEP2: Stay in EklipZBotV2.py. Tiny shell logging/view-info convenience helper used broadly across modules.
    def info(self, text):
        self.viewInfo.infoText = text
        self.viewInfo.add_info_line(text)


    # STEP2: Stay in EklipZBotV2.py or move very late to BotPathingUtils as a tiny cached-distance query. Small convenience wrapper over precomputed general distances.
    def distance_from_general(self, sourceTile):
        if sourceTile == self.general:
            return 0
        val = 0

        if self._gen_distances:
            val = self._gen_distances[sourceTile]
        return val

    # STEP2: Stay in EklipZBotV2.py or move very late to BotPathingUtils as a tiny cached-distance query. Small convenience wrapper over precomputed ally distances.
    def distance_from_teammate(self, sourceTile):
        if sourceTile == self.teammate_general:
            return 0
        val = 0

        if self._ally_distances:
            val = self._ally_distances[sourceTile]
        return val

    # STEP2: Stay in EklipZBotV2.py initially, then potentially split later between BotTargeting/BotExpansionOps/BotCombatOps. This scan seeds shared per-turn collections and target-player selection used everywhere.
    def scan_map_for_large_tiles_and_leaf_moves(self):
        self.general_safe_func_set[self.general] = lambda target, move_half=False: BotDefense.general_move_safe(self, target, move_half)
        self.leafMoves = []
        self.captureLeafMoves = []
        self.targetPlayerLeafMoves = []
        self.largeTilesNearEnemyKings: typing.Dict[Tile, typing.List[Tile]] = {}

        self.largePlayerTiles = []
        largeNegativeNeutralTiles = []
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
                            teamPlayer.knowsAllyKingLocation = True

        for enemyGen in self._map.generals:
            if enemyGen is not None and self._map.is_tile_enemy(enemyGen):
                self.largeTilesNearEnemyKings[enemyGen] = []
        if not self.targetPlayerExpectedGeneralLocation.isGeneral:
            # self.targetPlayerExpectedGeneralLocation.player = self.player
            self.largeTilesNearEnemyKings[self.targetPlayerExpectedGeneralLocation] = []

        for tile in self._map.tiles_by_index:
            if self._map.is_tile_enemy(tile) and self._map.generals[tile.player] is None:
                for nextTile in tile.movable:
                    if not nextTile.discovered and not nextTile.isNotPathable:
                        approx = generalApproximations[tile.player]
                        approx[0] += nextTile.x
                        approx[1] += nextTile.y
                        approx[2] += 1

            if tile.player == self._map.player_index:
                for nextTile in tile.movable:
                    if not self._map.is_tile_friendly(nextTile) and not nextTile.isObstacle and not nextTile.isSwamp and (not nextTile.isDesert or nextTile.player >= 0):
                        mv = Move(tile, nextTile)
                        self.leafMoves.append(mv)
                        if tile.army - 1 > nextTile.army and tile.army > 1:
                            self.captureLeafMoves.append(mv)
                if tile.army > largePlayerTileThreshold:
                    self.largePlayerTiles.append(tile)

            elif tile.player != -1:
                if tile.player == self.targetPlayer:
                    for nextTile in tile.movable:
                        if not self._map.is_tile_on_team_with(nextTile, self.targetPlayer) and not nextTile.isObstacle and tile.army - 1 > nextTile.army and tile.army > 1:
                            self.targetPlayerLeafMoves.append(Move(tile, nextTile))
                if tile.isCity and self._map.is_tile_enemy(tile):
                    self.enemyCities.append(tile)
            elif tile.army < -1:
                heapq.heappush(largeNegativeNeutralTiles, (tile.army, tile))

            if tile.player == self._map.player_index and tile.army > 5:
                for enemyGen in self.largeTilesNearEnemyKings.keys():
                    if tile.army > enemyGen.army and self._map.euclidDist(tile.x, tile.y, enemyGen.x, enemyGen.y) < 11:
                        self.largeTilesNearEnemyKings[enemyGen].append(tile)

        self.largeNegativeNeutralTiles = []
        while largeNegativeNeutralTiles:
            army, tile = heapq.heappop(largeNegativeNeutralTiles)
            self.largeNegativeNeutralTiles.append(tile)

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

                # calculate vector
                delta = ((generalApproximations[i][0] - general.x) * 1.1, (generalApproximations[i][1] - general.y) * 1.1)
                generalApproximations[i][0] = general.x + delta[0]
                generalApproximations[i][1] = general.y + delta[1]
        for i in range(len(self._map.generals)):
            gen = self._map.generals[i]
            genDist = 1000

            if gen is None and generalApproximations[i][2] > 0:
                for tile in self._map.pathable_tiles:
                    if not tile.discovered and not tile.isNotPathable:
                        tileDist = self._map.euclidDist(generalApproximations[i][0], generalApproximations[i][1], tile.x, tile.y)
                        if tileDist < genDist and self.distance_from_general(tile) < 1000:
                            generalApproximations[i][3] = tile
                            genDist = tileDist

        self.generalApproximations = generalApproximations

        oldTgPlayer = self.targetPlayer
        self.targetPlayer = BotTargeting.calculate_target_player(self)
        self.opponent_tracker.targetPlayer = self.targetPlayer

        self.targetPlayerObj = self._map.players[self.targetPlayer]

        if self.targetPlayer != oldTgPlayer:
            self._lastTargetPlayerCityCount = 0
            if self.targetPlayer >= 0:
                self._lastTargetPlayerCityCount = self.opponent_tracker.get_current_team_scores_by_player(self.targetPlayer).cityCount


    # STEP2: Stay in EklipZBotV2.py or move to a dedicated resume/debug module late. This restores broad bot/runtime state across trackers, timings, paths, and debug serialization.
    def load_resume_data(self, resume_data: typing.Dict[str, str]):
        if f'bot_target_player' in resume_data:  # ={self.player}')
            self.targetPlayer = int(resume_data[f'bot_target_player'])
            if self.targetPlayer >= 0:
                self.targetPlayerObj = self._map.players[self.targetPlayer]
            self.opponent_tracker.targetPlayer = self.targetPlayer
        if f'targetPlayerExpectedGeneralLocation' in resume_data:  # ={self.targetPlayerExpectedGeneralLocation.x},{self.targetPlayerExpectedGeneralLocation.y}')
            self.targetPlayerExpectedGeneralLocation = BotStateQueries.parse_tile_str(self, resume_data[f'targetPlayerExpectedGeneralLocation'])
        if f'bot_is_all_in_losing' in resume_data:  # ={self.is_all_in_losing}')
            self.is_all_in_losing = BotStateQueries.parse_bool(self, resume_data[f'bot_is_all_in_losing'])
        if f'bot_all_in_losing_counter' in resume_data:  # ={self.all_in_losing_counter}')
            self.all_in_losing_counter = int(resume_data[f'bot_all_in_losing_counter'])

        if f'bot_is_all_in_army_advantage' in resume_data:  # ={self.is_all_in_army_advantage}')
            self.is_all_in_army_advantage = BotStateQueries.parse_bool(self, resume_data[f'bot_is_all_in_army_advantage'])
        if f'bot_is_winning_gather_cyclic' in resume_data:  # ={self.is_all_in_army_advantage}')
            self.is_winning_gather_cyclic = BotStateQueries.parse_bool(self, resume_data[f'bot_is_winning_gather_cyclic'])
        if f'bot_all_in_army_advantage_counter' in resume_data:  # ={self.all_in_army_advantage_counter}')
            self.all_in_army_advantage_counter = int(resume_data[f'bot_all_in_army_advantage_counter'])
        if f'bot_all_in_army_advantage_cycle' in resume_data:  # ={self.all_in_army_advantage_cycle}')
            self.all_in_army_advantage_cycle = int(resume_data[f'bot_all_in_army_advantage_cycle'])
        if f'bot_defend_economy' in resume_data:
            self.defend_economy = BotStateQueries.parse_bool(self, resume_data[f'bot_defend_economy'])

        if f'bot_timings_launch_timing' in resume_data:
            # self.timings = None
            # if self._map.turn % 50 != 0:
            cycleTurns = self._map.turn + self._map.remainingCycleTurns
            self.timings = Timings(0, 0, 0, 0, 0, cycleTurns, disallowEnemyGather=True)
            self.timings.launchTiming = int(resume_data[f'bot_timings_launch_timing'])
            self.timings.splitTurns = int(resume_data[f'bot_timings_split_turns'])
            self.timings.quickExpandTurns = int(resume_data[f'bot_timings_quick_expand_turns'])
            self.timings.cycleTurns = int(resume_data[f'bot_timings_cycle_turns'])

        if f'bot_is_rapid_capturing_neut_cities' in resume_data:  # ={self.is_rapid_capturing_neut_cities}')
            self.is_rapid_capturing_neut_cities = BotStateQueries.parse_bool(self, resume_data[f'bot_is_rapid_capturing_neut_cities'])
        if f'bot_is_blocking_neutral_city_captures' in resume_data:  # ={self.is_blocking_neutral_city_captures}')
            self.is_blocking_neutral_city_captures = BotStateQueries.parse_bool(self, resume_data[f'bot_is_blocking_neutral_city_captures'])
        if f'bot_finishing_exploration' in resume_data:  # ={self.finishing_exploration}')
            self.finishing_exploration = BotStateQueries.parse_bool(self, resume_data[f'bot_finishing_exploration'])
        if f'bot_targeting_army' in resume_data:  # ={self.targetingArmy.tile.x},{self.targetingArmy.tile.y}')
            self.targetingArmy = self.get_army_at(BotStateQueries.parse_tile_str(self, resume_data[f'bot_targeting_army']))
        else:
            self.targetingArmy = None
        if f'bot_cur_path' in resume_data:  # ={str(self.curPath)}')
            self.curPath = TextMapLoader.parse_path(self._map, resume_data[f'bot_cur_path'])
        else:
            self.curPath = None

        for player in self._map.players:
            char = PLAYER_CHAR_BY_INDEX[player.index]
            if f'{char}Emergences' in resume_data:
                self.armyTracker.emergenceLocationMap[player.index] = BotSerialization.convert_string_to_float_map_matrix(self, resume_data[f'{char}Emergences'])
            elif f'targetPlayerExpectedGeneralLocation' in resume_data and player.index == self.targetPlayer and len(self._map.players[self.targetPlayer].tiles) > 0:
                # only do the old behavior when explicit emergences arent available.
                self.armyTracker.emergenceLocationMap[self.targetPlayer][self.targetPlayerExpectedGeneralLocation] = 5
            if f'{char}ValidGeneralPos' in resume_data:
                self.armyTracker.valid_general_positions_by_player[player.index] = BotSerialization.convert_string_to_bool_map_matrix_set(self, resume_data[f'{char}ValidGeneralPos'])
            if f'{char}TilesEverOwned' in resume_data:
                self.armyTracker.tiles_ever_owned_by_player[player.index] = BotSerialization.convert_string_to_tile_set(self, resume_data[f'{char}TilesEverOwned'])
            if f'{char}UneliminatedEmergences' in resume_data:
                self.armyTracker.uneliminated_emergence_events[player.index] = BotSerialization.convert_string_to_tile_int_dict(self, resume_data[f'{char}UneliminatedEmergences'])
            if f'{char}UneliminatedEmergenceCityPerfectInfo' in resume_data:
                self.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index] = BotSerialization.convert_string_to_tile_set(self, resume_data[f'{char}UneliminatedEmergenceCityPerfectInfo'])
            else:
                self.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index] = {t for t in self.armyTracker.uneliminated_emergence_events[player.index].keys()}
            if f'{char}UnrecapturedEmergences' in resume_data:
                self.armyTracker.unrecaptured_emergence_events[player.index] = BotSerialization.convert_string_to_tile_set(self, resume_data[f'{char}UnrecapturedEmergences'])
            else:
                pUnelim = self.armyTracker.uneliminated_emergence_events[player.index]
                pUnrecaptured = self.armyTracker.unrecaptured_emergence_events[player.index]
                for t in self._map.get_all_tiles():
                    if t in pUnelim:
                        pUnrecaptured.add(t)

        if f'TempFogTiles' in resume_data:
            tiles = BotSerialization.convert_string_to_tile_set(self, resume_data[f'TempFogTiles'])
            for tile in tiles:
                tile.isTempFogPrediction = True
        if f'DiscoveredNeutral' in resume_data:
            tiles = BotSerialization.convert_string_to_tile_set(self, resume_data[f'DiscoveredNeutral'])
            for tile in tiles:
                tile.discoveredAsNeutral = True

        if 'is_custom_map' in resume_data:
            self._map.is_custom_map = bool(resume_data['is_custom_map'])
        if 'walled_city_base_value' in resume_data:
            self._map.walled_city_base_value = int(resume_data['walled_city_base_value'])
            self._map.is_walled_city_game = True

        if 'PATHABLE_CITY_THRESHOLD' in resume_data:
            Tile.PATHABLE_CITY_THRESHOLD = int(resume_data['PATHABLE_CITY_THRESHOLD'])
            self._map.distance_mapper.recalculate()
            self._map.update_reachable()
        else:
            Tile.PATHABLE_CITY_THRESHOLD = 5  # old replays, no cities were ever pathable.

        if self.targetPlayerExpectedGeneralLocation:
            self.board_analysis.rebuild_intergeneral_analysis(self.targetPlayerExpectedGeneralLocation, self.armyTracker.valid_general_positions_by_player)

        self.opponent_tracker.load_from_map_data(resume_data)
        if self.targetPlayer >= 0:
            self._lastTargetPlayerCityCount = self.opponent_tracker.get_current_team_scores_by_player(self.targetPlayer).cityCount

        self.last_init_turn = self._map.turn - 1

        self.city_expand_plan = None
        self.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0)
        self.enemy_expansion_plan = None

        loadedArmies = TextMapLoader.load_armies(self._map, resume_data)
        if len(loadedArmies) == 0:
            for army in self.armyTracker.armies.values():
                army.last_moved_turn = self._map.turn - 3

            if self.targetingArmy:
                self.targetingArmy.last_moved_turn = self._map.turn - 1

            for army in self.armyTracker.armies.values():
                if army.tile.discovered:
                    army.last_moved_turn = self._map.turn - 1
                else:
                    army.last_moved_turn = self._map.turn - 5

        else:
            self.armyTracker.armies = loadedArmies

        self.history = History()

        # force a rebuild
        self.cityAnalyzer.reset_reachability()

        return

    # STEP2: Stay in EklipZBotV2.py initially, then potentially split across BotTargeting/BotTimings/BotComms later. This recalculates shared target/gather/flank state used by many modules.
    def recalculate_player_paths(self, force: bool = False):
        BotCityOps.ensure_reachability_matrix_built(self)
        reevaluate = force
        if len(self._evaluatedUndiscoveredCache) > 0:
            for tile in self._evaluatedUndiscoveredCache:
                if tile.discovered:
                    reevaluate = True
                    break
        if self.targetPlayerExpectedGeneralLocation is not None and self.targetPlayerExpectedGeneralLocation.visible and not self.targetPlayerExpectedGeneralLocation.isGeneral:
            reevaluate = True

        if SearchUtils.any_where(self._map.get_all_tiles(), lambda t: t.isCity and t.player >= 0 and t.delta.oldOwner == -1):
            reevaluate = True

        intentionallyGatheringAtNonGeneralTarget = self.target_player_gather_path is None or (not self.target_player_gather_path.tail.tile.isGeneral and self._map.generals[self.targetPlayer] is not None)
        if (self.target_player_gather_path is None
                or reevaluate
                or self.target_player_gather_path.tail.tile.isCity
                or self._map.turn % 50 < 2
                or self.timings.in_launch_split(self._map.turn - 3)
                or self._map.turn < 100
                or intentionallyGatheringAtNonGeneralTarget
                or self.curPath is None):

            # self.undiscovered_priorities = None

            self.shortest_path_to_target_player = BotTargeting.get_path_to_target_player(self, isAllIn=BotStateQueries.is_all_in(self), cutLength=None)
            self.info(f'DEBUG: shortest_path_to_target_player {self.shortest_path_to_target_player}')
            if self.shortest_path_to_target_player is None:
                self.shortest_path_to_target_player = Path()
                self.shortest_path_to_target_player.add_next(self.general)
                self.shortest_path_to_target_player.add_next(next(iter(self.general.movableNoObstacles)))

            self.enemy_attack_path = BotDefense.get_enemy_probable_attack_path(self, self.targetPlayer)

            self.target_player_gather_path = self.shortest_path_to_target_player

            # limit = max(self._map.cols, self._map.rows)
            # if self.target_player_gather_path is not None and self.target_player_gather_path.length > limit and self._map.players[self.general.player].cityCount > 1:
            #     self.target_player_gather_path = self.target_player_gather_path.get_subsegment(limit, end=True)

            if self.teammate_communicator is not None and self.teammate_general is not None:
                self.teammate_communicator.determine_leads(self._gen_distances, self._ally_distances, self.targetPlayerExpectedGeneralLocation)

        if self.targetPlayer != -1 and self.target_player_gather_path is not None:
            with self.perf_timer.begin_move_event(f'find sketchiest fog flank'):
                self.sketchiest_potential_inbound_flank_path = BotDefense.find_sketchiest_fog_flank_from_enemy(self)
            if self.sketchiest_potential_inbound_flank_path is not None:
                self.viewInfo.add_stats_line(f'skFlank: {self.sketchiest_potential_inbound_flank_path}')
                self.viewInfo.color_path(PathColorer(
                    self.sketchiest_potential_inbound_flank_path, 0, 0, 0
                ))

        spawnDist = 12
        if self.target_player_gather_path is not None:
            pathTillVisibleToTarget = self.target_player_gather_path
            if self.targetPlayer != -1 and BotTargeting.is_ffa_situation(self):
                pathTillVisibleToTarget = self.target_player_gather_path.get_subsegment_until_visible_to_player(self._map.get_teammates(self.targetPlayer))
            self.target_player_gather_targets = {t for t in pathTillVisibleToTarget.tileList if not t.isSwamp and (not t.isDesert or self._map.is_tile_friendly(t))}
            if len(self.target_player_gather_targets) == 0:
                self.info(f'WARNING, BAD GATHER TARGETS, CANT AVOID DESERTS AND SWAMPS...')
                self.target_player_gather_targets = self.target_player_gather_path.tileSet
            spawnDist = self.shortest_path_to_target_player.length
        else:
            self.target_player_gather_targets = None

        with self.perf_timer.begin_move_event('calculating is_player_spawn_cramped'):
            self.force_city_take = BotTargeting.is_player_spawn_cramped(self, spawnDist) and self._map.turn > 150

    # STEP2: Stay in EklipZBotV2.py or move very late to BotStateQueries as a tiny tracker accessor. Frequently used convenience wrapper over ArmyTracker.
    def get_army_at(self, tile: Tile, no_expected_path: bool = False):
        return self.armyTracker.get_or_create_army_at(tile, skip_expected_path=no_expected_path)

    # STEP2: Stay in EklipZBotV2.py or move very late to BotStateQueries as a tiny tracker accessor. Convenience coordinate wrapper over get_army_at.
    def get_army_at_x_y(self, x: int, y: int):
        tile = self._map.GetTile(x, y)
        return self.get_army_at(tile)

    # STEP2: Stay in EklipZBotV2.py. Core one-time lifecycle/bootstrap wiring for all analyzers, trackers, callbacks, and bot state; keep on outer shell.
    def initialize_from_map_for_first_time(self, map: MapBase):
        self._map = map
        self._map.distance_mapper = DistanceMapperImpl(map)
        self.viewInfo = ViewInfo(2, self._map)
        self.is_lag_massive_map = self._map.rows * self._map.cols > 1000

        self.completed_first_100 = self._map.turn > 85

        BotLifecycle.initialize_logging(self)
        self.general = self._map.generals[self._map.player_index]
        self.player = self._map.players[self.general.player]
        self.alt_en_gen_positions = [[] for p in self._map.players]
        self._alt_en_gen_position_distances = [None for p in self._map.players]

        self.teams = MapBase.get_teams_array(map)
        self.opponent_tracker = OpponentTracker(self._map, self.viewInfo)
        self.opponent_tracker.analyze_turn(-1)
        self.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0)

        for teammate in self._map.teammates:
            teammatePlayer = self._map.players[teammate]
            if teammatePlayer.dead or not self._map.generals[teammate]:
                continue
            self.teammate_general = self._map.generals[teammate]
            self._ally_distances = self._map.distance_mapper.get_tile_dist_matrix(self.teammate_general)
            allyUsername = self._map.usernames[self.teammate_general.player]
            if "Teammate.exe" == allyUsername or "Human.exe" == allyUsername or "Exe.human" == allyUsername:  # or "EklipZ" in allyUsername
                # Use more excessive pings when paired with a bot for inter-bot communication.
                self.teamed_with_bot = True

        self._gen_distances = self._map.distance_mapper.get_tile_dist_matrix(self.general)

        self.dangerAnalyzer = DangerAnalyzer(self._map)
        self.cityAnalyzer = CityAnalyzer(self._map, self.general)
        self.gatherAnalyzer = GatherAnalyzer(self._map)
        self.isInitialized = True

        self.has_defenseless_modifier = self._map.modifiers_by_id[MODIFIER_DEFENSELESS]
        self.has_watchtower_modifier = self._map.modifiers_by_id[MODIFIER_WATCHTOWER]
        self.has_misty_veil_modifier = self._map.modifiers_by_id[MODIFIER_MISTY_VEIL]

        self._map.notify_city_found.append(lambda tile: BotEventHandlers.handle_city_found(self, tile))
        self._map.notify_tile_captures.append(lambda tile: BotEventHandlers.handle_tile_captures(self, tile))
        self._map.notify_tile_discovered.append(lambda tile: BotEventHandlers.handle_tile_discovered(self, tile))
        self._map.notify_tile_vision_changed.append(lambda tile: BotEventHandlers.handle_tile_vision_change(self, tile))
        self._map.notify_player_captures.append(lambda playerIndex: BotEventHandlers.handle_player_captures(self, playerIndex))
        if self.territories is None:
            self.territories = TerritoryClassifier(self._map)

        self.armyTracker = ArmyTracker(self._map, self.perf_timer)
        self.armyTracker.notify_unresolved_army_emerged.append(lambda tile: BotEventHandlers.handle_tile_vision_change(self, tile))
        self.armyTracker.notify_army_moved.append(lambda move: BotEventHandlers.handle_army_moved(self, move))
        self.armyTracker.notify_army_moved.append(self.opponent_tracker.notify_army_moved)
        self.targetPlayerExpectedGeneralLocation = self.general.movable[0]
        self.tileIslandBuilder = TileIslandBuilder(self._map)
        self.tileIslandBuilder.recalculate_tile_islands(enemyGeneralExpectedLocation=self.targetPlayerExpectedGeneralLocation)
        self.launchPoints.append(self.general)
        self.board_analysis = BoardAnalyzer(self._map, self.general, self.teammate_general)
        self.army_interceptor = ArmyInterceptor(self._map, self.board_analysis)
        self.win_condition_analyzer = WinConditionAnalyzer(self._map, self.opponent_tracker, self.cityAnalyzer, self.territories, self.board_analysis)
        self.capture_line_tracker = CaptureLineTracker(self._map)
        BotTimings.timing_cycle_ended(self)
        self.opponent_tracker.outbound_emergence_notifications.append(self.armyTracker.notify_concrete_emergence)
        self.is_weird_custom = self._map.is_walled_city_game or self._map.is_low_cost_city_game
        if self._map.cols < 13 or self._map.rows < 13:
            self.is_weird_custom = True

        # minCity = None
        # for tile in self._map.get_all_tiles():
        #     if tile.isCity and tile.isNeutral and (minCity is None or minCity.army > tile.army):
        #         minCity = tile
        #
        # if minCity is not None and minCity.army < 30:
        #     self.is_weird_custom = True
        #     self._map.set_walled_cities(minCity.army)

    # STEP2: Stay in EklipZBotV2.py. Serialization guard on the shell object; keep unchanged with bot lifecycle methods.
    def __getstate__(self):
        raise AssertionError("EklipZBot Should never be serialized")

    # STEP2: Stay in EklipZBotV2.py. Serialization guard on the shell object; keep unchanged with bot lifecycle methods.
    def __setstate__(self, state):
        raise AssertionError("EklipZBot Should never be deserialized")

    def hunt_for_fog_neutral_city(self, negativeTiles: typing.Set[Tile], maxTurns: int) -> typing.Tuple[Path | None, Move | None]:
        fogObstacleAdjacents = MapMatrix(self._map, 0)
        tilesNear = []

        skipTiles = set()
        for t in self.player.tiles:
            if t.army <= 1:
                skipTiles.add(t)

        def foreachFogObstacleCounter(tile: Tile, dist: int):
            if (
                    # not tile.discovered
                    not SearchUtils.any_where(tile.adjacents, lambda t: self.territories.is_tile_in_enemy_territory(t) or self._map.is_tile_enemy(t))
                    and not tile.isUndiscoveredObstacle
                    and not (tile.isCity and tile.isNeutral)
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

            return self.territories.is_tile_in_enemy_territory(t) or t.isUndiscoveredObstacle or (t.isCity and not self._map.is_tile_friendly(t))

        SearchUtils.breadth_first_foreach_dist(
            self._map,
            self.player.tiles,
            maxDepth=4,
            foreachFunc=foreachFogObstacleCounter,
            bypassDefaultSkip=True
        )

        logbook.info(f'GATHERING TO FOG UNDISC')

        def sorter(tileDistTuple) -> float:
            tile, dist = tileDistTuple
            rating = fogObstacleAdjacents[tile] / self.distance_from_general(tile) / dist
            return rating

        prioritized = [t for t, d in sorted(tilesNear, key=sorter, reverse=True)]

        for tile in self._map.get_all_tiles():
            self.viewInfo.midRightGridText[tile] = f'fa{fogObstacleAdjacents[tile]}'

        keyAreas = prioritized[0:5]

        for t in keyAreas:
            self.viewInfo.add_targeted_tile(t, TargetStyle.WHITE)

        path = SearchUtils.dest_breadth_first_target(self._map, keyAreas, targetArmy=1, negativeTiles=negativeTiles, skipTiles=skipTiles, maxDepth=min(3, maxTurns))
        if path is not None:
            self.curPath = path
            return path, None

        with self.perf_timer.begin_move_event('Hunting for fog neutral cities'):
            move, valueGathered, turnsUsed, gatherNodes = BotGatherOps.get_gather_to_target_tiles(self, keyAreas, 0.1, self._map.turn % 5 + 1, negativeTiles, targetArmy=1, useTrueValueGathered=True, maximizeArmyGatheredPerTurn=True)

        if move is not None:
            self.gatherNodes = gatherNodes
            self.info(f'Hunting for fog neutral cities: {move}')
            return None, move

        return None, None
