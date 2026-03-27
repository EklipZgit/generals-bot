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

    # DONE STEP2: Move to BotModules/BotRepetition.py as BotRepetition.detect_repetition_at_all. Pure move-history repetition scan against bot history/map state; delegate from shell.
    def detect_repetition_at_all(self, turns=4, numReps=2) -> bool:
        return BotRepetition.detect_repetition_at_all(self, turns, numReps)

    # DONE STEP2: Move to BotModules/BotRepetition.py as BotRepetition.detect_repetition. Pure repetition check on a candidate move using bot history only; keep shell pass-through for call-site stability.
    def detect_repetition(self, move, turns=4, numReps=2):
        return BotRepetition.detect_repetition(self, move, turns, numReps)

    # DONE STEP2: Move to BotModules/BotRepetition.py as BotRepetition.detect_repetition_tile. History-based tile repetition query; belongs with other repetition heuristics.
    def detect_repetition_tile(self, tile: Tile, turns=6, numReps=2):
        return BotRepetition.detect_repetition_tile(self, tile, turns, numReps)

    # DONE STEP2: Move to BotModules/BotRepetition.py as BotRepetition.move_half_on_repetition. Thin policy wrapper over repetition detection; migrate with the repetition cluster unchanged.
    def move_half_on_repetition(self, move, repetitionTurns, repCount=3):
        return BotRepetition.move_half_on_repetition(self, move, repetitionTurns, repCount)

    # STEP2: Stay in EklipZBotV2.py. Top-level move orchestration/error handling/history/render prep spanning many modules; keep on shell and have it call extracted helpers.
    def find_move(self, is_lag_move=False) -> Move | None:
        move: Move | None = None
        try:
            move = self.select_move(is_lag_move=is_lag_move)

            if move is not None and move.source.isGeneral and not self.is_move_safe_valid(move, allowNonKill=True):
                logbook.error(f'TRIED TO PERFORM AN IMMEDIATE DEATH MOVE, INVESTIGATE: {move}')
                self.info(f'Tried to perform a move that dies immediately. {move}')
                dangerTiles = self.get_danger_tiles()
                replaced = False
                for dangerTile in dangerTiles:
                    if self.general in dangerTile.movable:
                        altMove = Move(self.general, dangerTile)
                        if not self.is_move_safe_valid(altMove, allowNonKill=True):
                            altMove.move_half = True
                        if self.is_move_safe_valid(altMove, allowNonKill=True):
                            self.info(f'Replacing with danger kill {altMove}')
                            move = altMove
                            replaced = True
                            break

                if not replaced and self.expansion_plan:
                    for opt in self.expansion_plan.all_paths:
                        firstMove = opt.get_first_move()
                        if self.is_move_safe_valid(firstMove, allowNonKill=True):
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
                    self.send_teammate_communication(msg.message, msg.ping_tile, msg.cooldown, msg.cooldown_detection_on_message_alone, msg.cooldown_key)

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

            self.check_cur_path()

            if move is not None and self.curPath is not None:
                curPathMove = self.curPath.get_first_move()
                if curPathMove.source == move.source and curPathMove.dest != move.dest:
                    logbook.info("Returned a move using the tile that was curPath, but wasn't the next path move. Resetting path...")
                    self.curPath = None
                    self.curPathPrio = -1

            if self._map.turn not in self.history.move_history:
                self.history.move_history[self._map.turn] = []
            self.history.move_history[self._map.turn].append(move)

            self.prep_view_info_for_render(move)

        return move

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.clean_up_path_before_evaluating. CurPath maintenance / dedupe logic tied to path semantics, not top-level orchestration.
    def clean_up_path_before_evaluating(self):
        return BotPathingUtils.clean_up_path_before_evaluating(self)

    # DONE STEP2: Move to BotModules/BotRepetition.py as BotRepetition.dropped_move. Last-move/drop inference based on move history and map deltas; keep a thin bot alias because it is referenced from path maintenance.
    def droppedMove(self, fromTile=None, toTile=None, movedHalf=None):
        return BotRepetition.dropped_move(self, fromTile, toTile, movedHalf)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.handle_city_found. Small city discovery side-effect handler updating trackers/classifiers only.
    def handle_city_found(self, tile):
        return BotEventHandlers.handle_city_found(self, tile)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.handle_tile_captures. Capture-event bookkeeping that updates territory/army tracking and aggression state; migrate with event handlers.
    def handle_tile_captures(self, tile: Tile):
        return BotEventHandlers.handle_tile_captures(self, tile)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.handle_player_captures. Player-death event processing that scrubs tracker state and triggers re-evaluation; belongs in the event cluster.
    def handle_player_captures(self, capturee: int, capturer: int):
        return BotEventHandlers.handle_player_captures(self, capturee, capturer)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.handle_tile_deltas. Logging-only tile delta hook; keep with event handlers for completeness even though behavior is minimal.
    def handle_tile_deltas(self, tile):
        return BotEventHandlers.handle_tile_deltas(self, tile)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.handle_tile_discovered. Discovery event bookkeeping touching rescans, paths, and territory updates; keep grouped with map update handlers.
    def handle_tile_discovered(self, tile):
        return BotEventHandlers.handle_tile_discovered(self, tile)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.handle_tile_vision_change. Vision-change event handler with tracker/path invalidation side effects; migrate intact with the other event hooks.
    def handle_tile_vision_change(self, tile: Tile):
        return BotEventHandlers.handle_tile_vision_change(self, tile)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.handle_army_moved. Army movement event bookkeeping updating trackers/opponent data; belongs in the event-handler module.
    def handle_army_moved(self, army: Army):
        return BotEventHandlers.handle_army_moved(self, army)

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

        while self._chat_messages_received.qsize() > 0:
            chatUpdate = self._chat_messages_received.get()
            self.handle_chat_message(chatUpdate)

        self.check_target_player_just_took_city()

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
            self.reevaluate_after_player_capture()
            self.trigger_player_capture_re_eval = False

        self._minAllowableArmy = -1
        self.enemyCities = []
        if self._map.turn - 3 > self.lastTimingTurn:
            self.lastTimingFactor = -1

        lastMove = None

        if self._map.turn - 1 in self.history.move_history:
            lastMove = self.history.move_history[self._map.turn - 1][0]

        with self.perf_timer.begin_move_event('ArmyTracker Move/Emerge'):
            self.armies_moved_this_turn = []
            # the callback on armies moved will fill the list above back up during armyTracker.scan
            self.armyTracker.scan_movement_and_emergences(lastMove, self._map.turn, self.board_analysis)

        for tile, emergenceTuple in self._map.army_emergences.items():
            emergedAmount, emergingPlayer = emergenceTuple
            if emergedAmount > 0 or not self._map.is_player_on_team_with(tile.delta.oldOwner, tile.player):  # otherwise, this is just the player moving into fog generally.
                self.opponent_tracker.notify_emerged_army(tile, emergingPlayer, emergedAmount)

        # with self.perf_timer.begin_move_event('ArmyTracker bisector'):
        #     self.gather_kill_priorities = self.find_fog_bisection_targets()

        # if self._map.turn >= 3 and self.board_analysis.should_rescan:
        # I think reachable tiles isn't built till turn 2? so chokes aren't built properly turn 1

        self.approximate_greedy_turns_avail = self._get_approximate_greedy_turns_available()

        if self.board_analysis.central_defense_point and self.board_analysis.intergeneral_analysis:
            centralPoint = self.board_analysis.central_defense_point
            self.viewInfo.add_targeted_tile(centralPoint, TargetStyle.TEAL, radiusReduction=2)
            if (self.locked_launch_point is None or self.locked_launch_point == self.general) and self.board_analysis.intergeneral_analysis.bMap[centralPoint] < self.board_analysis.inter_general_distance:
                # then the central defense point is further forward than our general, lock it as launch point.
                self.viewInfo.add_info_line(f"locking in central launch point {str(centralPoint)}")
                self.locked_launch_point = centralPoint
                self.recalculate_player_paths(force=True)

        self.ensure_reachability_matrix_built()

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
                            if self.armyTracker.try_find_army_sink(player.index, annihilatedFog, tookNeutCity=self.did_player_just_take_fog_city(player.index)):
                                break

        with self.perf_timer.begin_move_event('ArmyTracker fog land builder'):
            fogTileCounts = self.opponent_tracker.get_all_player_fog_tile_count_dict()
            for player in self._map.players:
                self.armyTracker.update_fog_prediction(player.index, fogTileCounts[player.index], None)

        self._evaluatedUndiscoveredCache = []
        with self.perf_timer.begin_move_event('get_predicted_target_player_general_location'):
            maxTile: Tile = self.get_predicted_target_player_general_location()
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
                                    altEnGenPositions, enPotentialGenDistances = self._get_furthest_apart_3_enemy_general_locations(player.index)
                                self.alt_en_gen_positions[player.index] = altEnGenPositions
                                self._alt_en_gen_position_distances[player.index] = enPotentialGenDistances
                        else:
                            limitNearbyTileRange = -1
                            if len(self._map.players) > 4:
                                limitNearbyTileRange = 12
                            altEnGenPositions = self.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=2, player=player.index, cutoffEmergenceRatio=0.3, limitNearbyTileRange=limitNearbyTileRange)
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

        if not self.is_all_in() and (not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 5) % 5 == 0):
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

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings.is_player_aggressive. Small timing/policy query over aggression_factor; belongs with timing heuristics.
    def is_player_aggressive(self, player: int, turnPeriod: int = 50) -> bool:
        return BotTimings.is_player_aggressive(self, player, turnPeriod)

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings.get_timings_old. Legacy timing policy retained for reference/compatibility; move intact with timing logic and keep a shell pass-through if still referenced.
    def get_timings_old(self) -> Timings:
        return BotTimings.get_timings_old(self)

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings.get_timings. Primary timing/cycle policy calculator; strongly cohesive with other timing heuristics and should migrate as one unit.
    def get_timings(self) -> Timings:
        return BotTimings.get_timings(self)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_undiscovered_count_on_path. Tiny path-content utility used by timing/targeting logic; belongs with path helpers.
    def get_undiscovered_count_on_path(self, path: Path) -> int:
        return BotPathingUtils.get_undiscovered_count_on_path(self, path)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_enemy_count_on_path. Tiny path-content utility used by timing/path evaluation; keep with path helper cluster.
    def get_enemy_count_on_path(self, path: Path) -> int:
        return BotPathingUtils.get_enemy_count_on_path(self, path)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.timing_expand. Expansion timing stub/policy helper; keep with expansion even though it currently returns None.
    def timing_expand(self):
        return BotExpansionOps.timing_expand(self)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.timing_gather. Main timing-window gather executor with gather planning/pruning and path conversion; migrate intact with gather helpers.
    def timing_gather(
            self,
            startTiles: typing.List[Tile],
            negativeTiles: typing.Set[Tile] | None = None,
            skipTiles: typing.Set[Tile] | None = None,
            force=False,
            priorityTiles: typing.Set[Tile] | None = None,
            targetTurns=-1,
            includeGatherTreeNodesThatGatherNegative=False,  # DO NOT set this to True, causes us to slam tiles into dumb shit everywhere
            useTrueValueGathered: bool = False,
            pruneToValuePerTurn: bool = False,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            distancePriorities: MapMatrixInterface[int] | None = None,
            logStuff: bool = False
    ) -> Move | None:
        return BotGatherOps.timing_gather(self, startTiles, negativeTiles, skipTiles, force, priorityTiles, targetTurns, includeGatherTreeNodesThatGatherNegative, useTrueValueGathered, pruneToValuePerTurn, priorityMatrix, distancePriorities, logStuff)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.make_first_25_move. Early-game opening/expansion move chooser tied to city expansion plans and expansion search policy.
    def make_first_25_move(self) -> Move | None:
        return BotExpansionOps.make_first_25_move(self)

        # self.viewInfo.add_info_line('wtf, explan plan was empty but we\'re in first 25 still..? Switching to old expansion')
        # else:
        #     with self.perf_timer.begin_move_event(
        #             f'First 25 expansion FFA'):
        #
        #         if self._map.turn < 22:
        #             return None
        #
        #         nonGeneralArmyTiles = [tile for tile in filter(lambda tile: tile != self.general and tile.army > 1, self._map.players[self.general.player].tiles)]
        #
        #         skipTiles = set()
        #
        #         if len(nonGeneralArmyTiles) > 0:
        #             skipTiles.add(self.general)
        #         elif self.general.army < 3 and self._map.turn < 45:
        #             return None
        #
        #         # EXPLORATION was the old way for 1v1 pre-optimal-first-25
        #         # path = self.get_optimal_exploration(50 - self._map.turn, skipTiles=skipTiles)
        #
        #         # prioritize tiles that explore the least
        #         distMap = [[1000 for y in range(self._map.rows)] for x in range(self._map.cols)]
        #         for tile in self._map.reachableTiles:
        #             val = 60 - int(self.get_distance_from_board_center(tile, center_ratio=0.0))
        #             distMap[tile.x][tile.y] = val
        #
        #         # hack
        #         oldDistMap = self.board_analysis.intergeneral_analysis.bMap
        #         try:
        #             self.board_analysis.intergeneral_analysis.bMap = distMap
        #             path, allPaths = ExpandUtils.get_optimal_expansion(
        #                 self._map,
        #                 self.general.player,
        #                 self.player,
        #                 50 - self._map.turn,
        #                 self.board_analysis,
        #                 self.territories.territoryMap,
        #                 skipTiles,
        #                 viewInfo=self.viewInfo
        #             )
        #         finally:
        #             self.board_analysis.intergeneral_analysis.bMap = oldDistMap
        #
        #         if (self._map.turn < 46
        #                 and self.general.army < 3
        #                 and len(nonGeneralArmyTiles) == 0
        #                 and SearchUtils.count(self.general.movable, lambda tile: not tile.isMountain and tile.player == -1) > 0):
        #             self.info("Skipping move because general.army < 3 and all army on general and self._map.turn < 46")
        #             # dont send 2 army except right before the bonus, making perfect first 25 much more likely
        #             return None
        #         move = None
        #         if path:
        #             self.info("Dont make me expand. You don't want to see me when I'm expanding.")
        #             move = self.get_first_path_move(path)
        #         return move

    # STEP2: Stay in EklipZBotV2.py. High-level pre-move orchestration that coordinates timings, path recalculation, out-of-play mode, all-in state, and dropped-move recovery across many domains.
    def perform_move_prep(self, is_lag_move: bool = False):
        with self.perf_timer.begin_move_event('scan_map_for_large_tiles_and_leaf_moves()'):
            self.scan_map_for_large_tiles_and_leaf_moves()

        if self.timings and self.timings.get_turn_in_cycle(self._map.turn) == 0:
            self.timing_cycle_ended()

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
                self.timings = self.get_timings()

        # self.check_if_need_to_gather_longer_to_hold_fresh_cities()

        # allowOutOfPlayCheck = self._map.cols * self._map.rows < 400 and len(self.player.cities) < 7
        oldOutOfPlay = self.army_out_of_play
        cycleRemaining = self.timings.get_turns_left_in_cycle(self._map.turn)
        allowSwapToOutOfPlay = cycleRemaining > 15 or (self.opponent_tracker.winning_on_army(byRatio=1.2) and self.opponent_tracker.winning_on_economy(byRatio=1.2)) or self.army_out_of_play
        self.army_out_of_play = allowSwapToOutOfPlay and self.check_army_out_of_play_ratio()
        if not is_lag_move and not wasFlanking and self.army_out_of_play != oldOutOfPlay:
            with self.perf_timer.begin_move_event('flank/outOfPlay recalc_player_paths'):
                self.recalculate_player_paths(force=True)

        if self.timings is None or self.timings.should_recalculate(self._map.turn):
            with self.perf_timer.begin_move_event('Recalculating Timings...'):
                self.timings = self.get_timings()

        if self.determine_should_winning_all_in():
            wasAllIn = self.is_all_in_army_advantage
            self.is_all_in_army_advantage = True
            if not wasAllIn:
                self.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0)
                self.city_expand_plan = None
                self.enemy_expansion_plan = None
                cycle = 50
                if self._map.players[self.general.player].tileCount - self.target_player_gather_path.length < 60:
                    cycle = 30
                self.set_all_in_cycle_to_hit_with_current_timings(cycle)
                self.viewInfo.add_info_line(f"GOING ARMY ADV TEMP ALL IN CYCLE {cycle}, PRESERVING CURPATH")
                # self.timings = self.get_timings()
                if self.targetPlayerObj.general is not None and not self.targetPlayerObj.general.visible:
                    self.targetPlayerObj.general.army = 3
                    self.clear_fog_armies_around(self.targetPlayerObj.general)

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
            if self.droppedMove():
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
            if self.droppedMove() and self._map.turn <= 50 and lastMove is not None:
                if lastMove.source != self.general:
                    self.viewInfo.add_info_line(f're-performing dropped first-25 non-general move {str(lastMove)}')
                    return lastMove
                else:
                    # force reset the expansion plan so we recalculate from general.
                    self.city_expand_plan = None

        if not is_lag_move and not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 2) % 5 == 0:
            with self.perf_timer.begin_move_event("recalculating player path"):
                self.recalculate_player_paths()

        if not self.is_still_ffa_and_non_dominant():
            self.prune_timing_split_if_necessary()

        move = self.pick_move_after_prep(is_lag_move)

        if move and self.curPath and move.source in self.curPath.tileSet and move != self.curPath.get_first_move():
            self.curPath = None

        return move

    # STEP2: Stay in EklipZBotV2.py. Central post-prep decision tree coordinating combat, defense, city capture, expansion, and continuation logic; keep on shell and delegate subroutines out.
    def pick_move_after_prep(self, is_lag_move=False):
        with self.perf_timer.begin_move_event('calculating general danger / threats'):
            self.calculate_general_danger()

        if self._map.turn <= 4:
            if self._map.has_city_state:
                for t in self.general.movable:
                    if t.isCity and t.isNeutral and t.army == -1:
                        return Move(self.general, t)

        # with self.perf_timer.begin_move_event('Checking 1 move kills'):
        #     quickKillMove = self.check_for_1_move_kills()
        #     if quickKillMove is not None:
        #         return quickKillMove

        self.clean_up_path_before_evaluating()

        if self.curPathPrio >= 0:
            logbook.info(f"curPathPrio: {str(self.curPathPrio)}")

        threat = None

        if self.dangerAnalyzer.fastestThreat is not None:
            threat = self.dangerAnalyzer.fastestThreat

        if self.dangerAnalyzer.fastestAllyThreat is not None and (threat is None or self.dangerAnalyzer.fastestAllyThreat.turns < threat.turns):
            if self.determine_should_defend_ally():
                threat = self.dangerAnalyzer.fastestAllyThreat

        if self.dangerAnalyzer.fastestCityThreat is not None and threat is None:
            threat = self.dangerAnalyzer.fastestCityThreat

        if threat is None and not self.giving_up_counter > 30 and self.dangerAnalyzer.fastestVisionThreat is not None:
            threat = self.dangerAnalyzer.fastestVisionThreat

        #  # # # #   ENEMY KING KILLS
        with self.perf_timer.begin_move_event('Checking for king kills and races'):
            killMove, kingKillPath, raceChance = self.check_for_king_kills_and_races(threat)
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

        self.check_should_be_all_in_losing()

        if self.is_all_in_losing:
            logbook.info(f"~~~ ___ {self.get_elapsed()}\n   YO WE ALL IN DAWG\n~~~ ___")

        # if not self.isAllIn() and (threat.turns > -1 and self.dangerAnalyzer.anyThreat):
        #    armyAmount = (self.general_min_army_allowable() + enemyNearGen) * 1.1 if threat is None else threat.threatValue + general.army + 1

        if not self.is_all_in() and (not is_lag_move and not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 2) % 5 == 0):
            with self.perf_timer.begin_move_event('ENEMY Expansion quick check'):
                self.enemy_expansion_plan = self.build_enemy_expansion_plan(timeLimit=0.007, pathColor=(255, 150, 130))

        self.intercept_plans = self.build_intercept_plans(defenseCriticalTileSet)
        for i, interceptPlan in enumerate(self.intercept_plans.values()):
            self.render_intercept_plan(interceptPlan, colorIndex=i)

        if not self.is_all_in() and not is_lag_move:
            with self.perf_timer.begin_move_event('Expansion quick check'):
                redoTimings = False
                if self.expansion_plan is None or self.timings is None or self._map.turn >= self.timings.nextRecalcTurn:
                    redoTimings = True

                negs = {t for t in defenseCriticalTileSet if not self._map.is_tile_on_team_with(t, self.targetPlayer)}
                self._add_expansion_threat_negs(negs)
                checkCityRoundEndPlans = self._map.is_army_bonus_turn
                self.expansion_plan = self.build_expansion_plan(timeLimit=0.012, expansionNegatives=negs, pathColor=(150, 100, 150), includeExtraGenAndCityArmy=checkCityRoundEndPlans)

                self.capture_line_tracker.process_plan(self.targetPlayer, self.expansion_plan)

                if redoTimings:
                    self.timings = self.get_timings()

        defenseSavePath: Path | None = None
        if not self.is_all_in_losing and threat is not None and threat.threatType != ThreatType.Vision:
            with self.perf_timer.begin_move_event(f'THREAT DEFENSE {threat.turns} {str(threat.path.start.tile)}'):
                defenseMove, defenseSavePath = self.get_defense_moves(defenseCriticalTileSet, kingKillPath, raceChance)

                if defenseSavePath is not None:
                    self.viewInfo.color_path(PathColorer(defenseSavePath, 255, 100, 255, 200))
                if defenseMove is not None:
                    if not self.detect_repetition(defenseMove, turns=6, numReps=3) or (threat.threatType == ThreatType.Kill and threat.path.tail.tile.isGeneral):
                        if defenseMove.source in self.largePlayerTiles and self.targetingArmy is None:
                            logbook.info(f'threatDefense overriding targetingArmy with {str(threat.path.start.tile)}')
                            self.targetingArmy = self.get_army_at(threat.path.start.tile)
                        return defenseMove
                    else:
                        self.viewInfo.add_info_line(f'BYPASSING DEF REP {str(defenseMove)} :(')

        if self._map.turn < 100:
            isNoExpansionGame = ((len(self._map.swamps) > 0 or len(self._map.deserts) > 0) and self.get_unexpandable_ratio() > 0.7)
            if isNoExpansionGame or self._map.is_low_cost_city_game:
                # # assume we must take cities instead, then.
                # if self._map.walled_city_base_value is None or self._map.walled_city_base_value > 10:
                #     self._map.set_walled_cities(10)
                if self._map.turn < 30:
                    qkPath, shouldWait = self._check_should_wait_city_capture()
                    if qkPath is not None:
                        self.info(f'f15 QUICK KILL CITY {qkPath}')
                        return qkPath.get_first_move()
                    if shouldWait:
                        self.info(f'f15 wants to wait on city')
                        return None
                if not self.army_out_of_play:
                    path, move = self.capture_cities(set(), forceNeutralCapture=True)
                    if move is not None:
                        self.info(f'f50 City cap instead... {move}')
                        self.city_expand_plan = None
                        return move
                    if path is not None:
                        self.info(f'f50 City cap instead... {path}')
                        self.city_expand_plan = None
                        return self.get_first_path_move(path)

        if self._map.turn < 50:
            if not self._map.is_low_cost_city_game and not self._map.modifiers_by_id[MODIFIER_CITY_STATE]:
                return self.make_first_25_move()
            else:
                self.info(f'Byp f25 bc weird_custom {self.is_weird_custom} (walled_city {self._map.is_walled_city_game} or low_cost_city {self._map.is_low_cost_city_game}) or cityState {self._map.modifiers_by_id[MODIFIER_CITY_STATE]}')

        if self._map.turn < 250 and self._map.remainingPlayers > 3:
            with self.perf_timer.begin_move_event('Ffa Turtle Move'):
                move = self.look_for_ffa_turtle_move()
            if move is not None:
                return move
        if self.expansion_plan:
            for t in self.expansion_plan.blocking_tiles:
                if t not in defenseCriticalTileSet:
                    defenseCriticalTileSet.add(t)
                    self.viewInfo.add_info_line(f'{t} added to defense crit from expPlan.blocking')

        if self._map.is_army_bonus_turn or self.defensive_spanning_tree is None:
            with self.perf_timer.begin_move_event('defensive spanning tree'):
                self.defensive_spanning_tree = self._get_defensive_spanning_tree(defenseCriticalTileSet, self.get_gather_tiebreak_matrix())

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
            armyScrimMove = self.check_for_army_movement_scrims()
            if armyScrimMove is not None:
                # already logged
                return armyScrimMove

        with self.perf_timer.begin_move_event('DANGER TILES'):
            dangerTileKillMove = self.check_for_danger_tile_moves()
            if dangerTileKillMove is not None:
                return dangerTileKillMove  # already logged to info

        with self.perf_timer.begin_move_event('Flank defense / Vision expansion HIGH PRI'):
            flankDefMove = self.find_flank_defense_move(defenseCriticalTileSet, highPriority=True)
            if flankDefMove:
                return flankDefMove

        if not self.is_all_in_losing:
            with self.perf_timer.begin_move_event('get_quick_kill_on_enemy_cities'):
                path = self.get_quick_kill_on_enemy_cities(defenseCriticalTileSet)
            if path is not None:
                self.info(f'Quick Kill on enemy city: {str(path)}')
                self.curPath = path
                if self.curPath.length > 1:
                    self.curPath = self.curPath.get_subsegment(path.length - 2)
                move = self.get_first_path_move(path)
                if not self.detect_repetition(move):
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
                        self.clean_up_path_before_evaluating()
                        return self.curPath.get_first_move()

                gcp = Gather.gather_approximate_turns_to_tiles(
                    self._map,
                    targets,
                    roughTurns,
                    self.player.index,
                    minTurns=minTurns,
                    maxTurns=maxTurns,
                    gatherMatrix=self.get_gather_tiebreak_matrix(),
                    captureMatrix=self.get_expansion_weight_matrix(),
                    negativeTiles=defenseCriticalTileSet,
                    prioritizeCaptureHighArmyTiles=True,
                    useTrueValueGathered=False,
                    includeGatherPriorityAsEconValues=True,
                    timeLimit=min(0.05, self.get_remaining_move_time())
                )

                if gcp is None:
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    self.info(f'FAILED pcst FORCE_FAR_GATHERS min {minTurns}t max {maxTurns}t ideal {roughTurns}t, actual {gcp}')
                    useTrueVal = False
                    gathMat = self.get_gather_tiebreak_matrix()
                    move, valGathered, turnsUsed, gatherNodes = self.get_gather_to_target_tiles(
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
            second = self.make_second_25_move()
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

        afkPlayerMove = self.get_move_if_afk_player_situation()
        if afkPlayerMove:
            return afkPlayerMove

        self.check_cur_path()

        # needs to happen before defend_economy because defend_economy uses the properties set by this method.
        self.check_fog_risk()

        # if ahead on economy, but not %30 ahead on army we should play defensively
        self.defend_economy = self.should_defend_economy(defenseCriticalTileSet)

        # if self.targetingArmy and not self.targetingArmy.scrapped and self.targetingArmy.tile.army > 2 and not self.is_all_in_losing:
        #     with self.perf_timer.begin_move_event('Continue Army Kill'):
        #         armyTargetMove = self.continue_killing_target_army()
        #     if armyTargetMove:
        #         # already logged internally
        #         return armyTargetMove
        # else:
        #     self.targetingArmy = None

        if WinCondition.DefendContestedFriendlyCity in self.win_condition_analyzer.viable_win_conditions:
            with self.perf_timer.begin_move_event(f'Getting city preemptive defense {str(self.win_condition_analyzer.defend_cities)}'):
                cityDefenseMove = self.get_city_preemptive_defense_move(defenseCriticalTileSet)
            if cityDefenseMove is not None:
                self.info(f'City preemptive defense move! {str(cityDefenseMove)}')
                return cityDefenseMove

        with self.perf_timer.begin_move_event(f'capture_cities'):
            (cityPath, gatherMove) = self.capture_cities(defenseCriticalTileSet)
        if gatherMove is not None:
            logbook.info(f"{self.get_elapsed()} returning capture_cities gatherMove {str(gatherMove)}")
            if cityPath is not None:
                self.curPath = cityPath
            return gatherMove
        elif cityPath is not None:
            logbook.info(f"{self.get_elapsed()} returning capture_cities cityPath {str(cityPath)}")
            # self.curPath = cityPath
            return self.get_first_path_move(cityPath)

        # AFTER city capture because of test_should_contest_city_not_intercept_it. If this causes problems, then NEED to feed city attack/defense into the RoundPlanner and stop this hacky order shit...
        if self.expansion_plan and self.expansion_plan.includes_intercept and not self.is_all_in_losing:
            move = self.expansion_plan.selected_option.get_first_move()
            if not self.detect_repetition(move):
                # if isinstance(self.expansion_plan.selected_option, InterceptionOptionInfo):
                #     atTile = self.expansion_plan.selected_option.
                # atTile = None
                self.info(f'Pass thru EXP int! {move} {self.expansion_plan.selected_option}')
                return move

        with self.perf_timer.begin_move_event('try_get_enemy_territory_exploration_continuation_move'):
            expNegs = set(defenseCriticalTileSet)
            if WinCondition.DefendEconomicLead in self.win_condition_analyzer.viable_win_conditions:
                expNegs.update(self.win_condition_analyzer.defend_cities)
                expNegs.update(self.win_condition_analyzer.contestable_cities)
            largeArmyExpContinuationMove = self.try_get_enemy_territory_exploration_continuation_move(expNegs)

        if largeArmyExpContinuationMove is not None and not self.detect_repetition(largeArmyExpContinuationMove):
            # already logged
            return largeArmyExpContinuationMove

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
        #
        # threatDefenseLength = 2 * self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 3 + 1
        # if self.targetPlayerExpectedGeneralLocation.isGeneral:
        #     threatDefenseLength = self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 2 + 2
        #
        # if (
        #         threat is not None
        #         and threat.threatType == ThreatType.Kill
        #         and threat.path.length < threatDefenseLength
        #         and not self.is_all_in()
        #         and self._map.remainingPlayers < 4
        #         and threat.threatPlayer == self.targetPlayer
        # ):
        #     logbook.info(f"*\\*\\*\\*\\*\\*\n  Kill (non-vision) threat??? ({time.perf_counter() - start:.3f} in)")
        #     threatKill = self.kill_threat(threat)
        #     if threatKill and self.worth_path_kill(threatKill, threat.path, threat.armyAnalysis):
        #         if self.targetingArmy is None:
        #             logbook.info(f'setting targetingArmy to {str(threat.path.start.tile)} in Kill (non-vision) threat')
        #             self.targetingArmy = self.get_army_at(threat.path.start.tile)
        #         saveTile = threatKill.start.tile
        #         nextTile = threatKill.start.next.tile
        #         move = Move(saveTile, nextTile)
        #         if not self.detect_repetition(move, 6, 3):
        #             self.viewInfo.color_path(PathColorer(threatKill, 0, 255, 204, 255, 10, 200))
        #             move.move_half = self.should_kill_path_move_half(threatKill)
        #             self.info(f"Threat kill. half {move.move_half}, {threatKill.toString()}")
        #             return move

        # ARMY INTERCEPTION SHOULD NOW COVER VISION THREAT STUFF.
        # if (
        #         threat is not None
        #         and threat.threatType == ThreatType.Vision
        #         and not self.is_all_in()
        #         and threat.path.start.tile.visible
        #         and self.should_kill(threat.path.start.tile)
        #         and self.just_moved(threat.path.start.tile)
        #         and threat.path.length < min(10, self.distance_from_general(self.targetPlayerExpectedGeneralLocation) // 2 + 1)
        #         and self._map.remainingPlayers < 4
        #         and threat.threatPlayer == self.targetPlayer
        # ):
        #     logbook.info(f"*\\*\\*\\*\\*\\*\n  Kill vision threat. ({time.perf_counter() - start:.3f} in)")
        #     # Just kill threat then, nothing crazy
        #     path = self.kill_enemy_path(threat.path, allowGeneral = True)
        #
        #     visionKillDistance = 5
        #     if path is not None and self.worth_path_kill(path, threat.path, threat.armyAnalysis, visionKillDistance):
        #         if self.targetingArmy is None:
        #             logbook.info(f'setting targetingArmy to {str(threat.path.start.tile)} in Kill VISION threat')
        #             self.targetingArmy = self.get_army_at(threat.path.start.tile)
        #         self.info(f"Killing vision threat {threat.path.start.tile.toString()} with path {str(path)}")
        #         self.viewInfo.color_path(PathColorer(path, 0, 156, 124, 255, 10, 200))
        #         move = self.get_first_path_move(path)
        #         if not self.detect_repetition(move, turns=4, numReps=2) and (not path.start.tile.isGeneral or self.general_move_safe(move.dest)):
        #             move.move_half = self.should_kill_path_move_half(path)
        #             return move
        #     elif threat.path.start.tile == self.targetingArmy:
        #         logbook.info("threat.path.start.tile == self.targetingArmy and not worth_path_kill. Setting targetingArmy to None")
        #         self.targetingArmy = None
        #     elif path is None:
        #         logbook.info("No vision threat kill path?")

        if self.curPath is not None:
            move = self.continue_cur_path(threat, defenseCriticalTileSet)
            if move is not None:
                return move  # already logged

        exploreMove = self.try_find_exploration_move(defenseCriticalTileSet)
        if exploreMove is not None:
            return exploreMove  # already logged

        allInMove = self.get_all_in_move(defenseCriticalTileSet)
        if allInMove:
            # already logged
            return allInMove

        expMove = self.try_find_main_timing_expansion_move_if_applicable(defenseCriticalTileSet)
        if expMove is not None:
            return expMove  # already logged

        needToKillTiles = list()
        if not self.timings.disallowEnemyGather and not self.is_all_in_losing:
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
            flankDefMove = self.find_flank_defense_move(defenseCriticalTileSet, highPriority=False)
            if flankDefMove:
                return flankDefMove

        if self.defend_economy:
            move = self.try_find_army_out_of_position_move(defenseCriticalTileSet)
            if move is not None:
                return move  # already logged

        cyclicAllInMove = self.try_get_cyclic_all_in_move(defenseCriticalTileSet)
        if cyclicAllInMove:
            return cyclicAllInMove  # already logged

        if not self.is_all_in() and not self.defend_economy and quickExpTimingTurns > 0:
            move = self.try_gather_tendrils_towards_enemy(quickExpTimingTurns)
            if move is not None:
                return move

            moves = self.prioritize_expansion_leaves(self.leafMoves)
            if len(moves) > 0:
                move = moves[0]
                self.info(f"quickExpand leafMove {move}")
                return move

        expMove = self._get_expansion_plan_quick_capture_move(defenseCriticalTileSet)
        if expMove:
            self.info(f"quickCap move {expMove}")
            return expMove

        with self.perf_timer.begin_move_event(f'MAIN GATHER OUTER, negs {[str(t) for t in defenseCriticalTileSet]}'):
            gathMove = self.try_find_gather_move(threat, defenseCriticalTileSet, self.leafMoves, needToKillTiles)

        if gathMove is not None:
            # already logged / perf countered internally
            return gathMove

        isFfaAfkScenario = self._map.remainingCycleTurns > 14 and self.is_still_ffa_and_non_dominant() and self._map.cycleTurn < self.timings.launchTiming and not self._map.is_walled_city_game
        if isFfaAfkScenario:
            self.info(f'FFA AFK')
            return None

        # if self._map.turn > 150:
        #     with self.perf_timer.begin_move_event(f'No gather found final scrim'):
        #         scrimMove = self.find_end_of_turn_scrim_move(threat, kingKillPath)
        #         if scrimMove is not None:
        #             return scrimMove

        # NOTE NOTHING PAST THIS POINT CAN TAKE ANY EXTRA TIME

        if not self.is_all_in():
            with self.perf_timer.begin_move_event(f'No move found leafMove'):
                leafMove = self.find_leaf_move(self.leafMoves)
            if leafMove is not None:
                self.info(f"No move found leafMove? {str(leafMove)}")
                return leafMove

        self.curPathPrio = -1
        if self.get_remaining_move_time() > 0.01:
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
                gathMove = self.timing_gather(
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
        #
        # with self.perf_timer.begin_move_event('FOUND NO MOVES FINAL MST GATH'):
        #     gathers = self.build_mst(self.target_player_gather_targets, 1.0, 50, None)
        #
        #     turns, value, gathers = Gather.prune_mst_to_max_army_per_turn_with_values(
        #         gathers,
        #         1,
        #         self.general.player,
        #         teams=MapBase.get_teams_array(self._map),
        #         preferPrune=self.expansion_plan.preferred_tiles if self.expansion_plan is not None else None,
        #         viewInfo=self.viewInfo if self.info_render_gather_values else None)
        # self.gatherNodes = gathers
        # # move = self.get_gather_move(gathers, None, 1, 0, preferNeutral = True)
        # move = self.get_tree_move_default(gathers)

        if move is None:
            # turnInCycle = self.timings.get_turn_in_cycle(self._map.turn)
            # if self.timings.cycleTurns - turnInCycle < self.timings.cycleTurns - self.target_player_gather_path.length * 0.66:
            #     self.info("Found-no-moves-gather NO MOVE? Set launch now.")
            #     self.timings.launchTiming = self._map.turn % self.timings.cycleTurns
            # else:
            self.info("Found-no-moves-gather found no move, random expansion move?")
            if self.expansion_plan and self.expansion_plan.selected_option:
                for opt in self.expansion_plan.all_paths:
                    move = opt.get_first_move()
                    if move is not None and move.source.player == self._map.player_index and move.source.army > 1:
                        self.curPath = opt
                        return move

        elif self.is_move_safe_valid(move):
            self.info(f"Found-no-moves-gather found {value}v/{turns}t gather, using {move}")
            return move
        else:
            self.info(
                f"Found-no-moves-gather move {move} was not safe or valid!")

        return None

    # DONE STEP2: Move to BotModules/BotStateQueries.py late in the migration, or leave as a thin shell helper. Tiny derived-state query used everywhere; defer moving until larger modules stabilize.
    def is_all_in(self):
        return BotStateQueries.is_all_in(self)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.should_kill. Small combat predicate for whether a visible enemy/city should be treated as a kill target.
    def should_kill(self, tile):
        return BotCombatOps.should_kill(self, tile)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.just_moved. Small combat/targeting delta predicate used by tactical kill logic.
    def just_moved(self, tile):
        return BotCombatOps.just_moved(self, tile)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.should_kill_path_move_half. Tactical combat heuristic for partial-path kill execution; migrate with kill-path logic.
    def should_kill_path_move_half(self, threatKill, additionalArmy=0):
        return BotCombatOps.should_kill_path_move_half(self, threatKill, additionalArmy)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.find_key_enemy_vision_tiles. Tactical target selection for enemy vision/retake pressure; belongs with combat utility heuristics.
    def find_key_enemy_vision_tiles(self):
        return BotCombatOps.find_key_enemy_vision_tiles(self)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.worth_path_kill. Core tactical evaluator deciding whether a computed kill path is strategically worth taking.
    def worth_path_kill(self, pathKill: Path, threatPath: Path, analysis=None, cutoffDistance=5):
        return BotCombatOps.worth_path_kill(self, pathKill, threatPath, analysis, cutoffDistance)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.kill_army. Army-targeted tactical kill wrapper that builds/filters kill paths for tracked armies.
    def kill_army(
            self,
            army: Army,
            allowGeneral=False,
            allowWorthPathKillCheck=True
    ):
        return BotCombatOps.kill_army(self, army, allowGeneral, allowWorthPathKillCheck)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.kill_enemy_path. Thin wrapper into multi-path kill logic; migrate with the rest of the kill-path combat helpers.
    def kill_enemy_path(self, threatPath: Path, allowGeneral=False) -> Path | None:
        return BotCombatOps.kill_enemy_path(self, threatPath, allowGeneral)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.kill_enemy_paths. Main tactical kill-path construction logic over one or more threat paths; keep as a single intact combat cluster.
    def kill_enemy_paths(self, threatPaths: typing.List[Path], allowGeneral=False) -> Path | None:
        return BotCombatOps.kill_enemy_paths(self, threatPaths, allowGeneral)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.kill_threat. Tiny threat wrapper over kill_enemy_path; migrate with combat kill helpers.
    def kill_threat(self, threat: ThreatObj, allowGeneral=False):
        return BotCombatOps.kill_threat(self, threat, allowGeneral)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_gather_to_target_tile. Thin single-target adapter over the generic gather helper; keep with gather helper cluster.
    def get_gather_to_target_tile(
            self,
            target: Tile,
            maxTime: float,
            gatherTurns: int,
            negativeSet: typing.Set[Tile] | None = None,
            targetArmy: int = -1,
            useTrueValueGathered=False,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        return BotGatherOps.get_gather_to_target_tile(
            self,
            target,
            maxTime,
            gatherTurns,
            negativeSet,
            targetArmy,
            useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative,
            maximizeArmyGatheredPerTurn)

    # set useTrueValueGathered to True for things like defense gathers,
    # where you want to take into account army lost gathering over enemy or neutral tiles etc.
    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_defensive_gather_to_target_tiles. Defensive gather planner using targetArmy/priority adjustments; belongs in the gather module.
    def get_defensive_gather_to_target_tiles(
            self,
            targets,
            maxTime,
            gatherTurns,
            negativeSet=None,
            targetArmy=-1,
            useTrueValueGathered=False,
            leafMoveSelectionValueFunc=None,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False,
            additionalIncrement: int = 0,
            distPriorityMap: MapMatrix[int] | None = None,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            skipTiles: TileSet | None = None,
            shouldLog: bool = False,
            fastMode: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        return BotGatherOps.get_defensive_gather_to_target_tiles(
            self,
            targets,
            maxTime,
            gatherTurns,
            negativeSet,
            targetArmy,
            useTrueValueGathered,
            leafMoveSelectionValueFunc,
            includeGatherTreeNodesThatGatherNegative,
            maximizeArmyGatheredPerTurn,
            additionalIncrement,
            distPriorityMap,
            priorityMatrix,
            skipTiles,
            shouldLog,
            fastMode)

    # set useTrueValueGathered to True for things like defense gathers,
    # where you want to take into account army lost gathering over enemy or neutral tiles etc.
    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_gather_to_target_tiles. Main generic gather planner with PCST/old-MST/max-set/knapsack branches; migrate intact to avoid behavior drift.
    def get_gather_to_target_tiles(
            self,
            targets,
            maxTime,
            gatherTurns,
            negativeSet=None,
            targetArmy=-1,
            useTrueValueGathered=False,
            leafMoveSelectionValueFunc=None,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False,
            additionalIncrement: int = 0,
            distPriorityMap: MapMatrix[int] | None = None,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            skipTiles: TileSet | None = None,
            shouldLog: bool = False,
            fastMode: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        return BotGatherOps.get_gather_to_target_tiles(
            self,
            targets,
            maxTime,
            gatherTurns,
            negativeSet,
            targetArmy,
            useTrueValueGathered,
            leafMoveSelectionValueFunc,
            includeGatherTreeNodesThatGatherNegative,
            maximizeArmyGatheredPerTurn,
            additionalIncrement,
            distPriorityMap,
            priorityMatrix,
            skipTiles,
            shouldLog,
            fastMode)

    # set useTrueValueGathered to True for things like defense gathers,
    # where you want to take into account army lost gathering over enemy or neutral tiles etc.
    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_gather_to_target_tiles_greedy. Greedy fallback gather variant; keep with the rest of the gather planning surface.
    def get_gather_to_target_tiles_greedy(
            self,
            targets,
            maxTime,
            gatherTurns,
            negativeSet=None,
            targetArmy=-1,
            useTrueValueGathered=False,
            priorityFunc=None,
            valueFunc=None,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False,
            shouldLog: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        return BotGatherOps.get_gather_to_target_tiles_greedy(
            self,
            targets,
            maxTime,
            gatherTurns,
            negativeSet,
            targetArmy,
            useTrueValueGathered,
            priorityFunc,
            valueFunc,
            includeGatherTreeNodesThatGatherNegative,
            maximizeArmyGatheredPerTurn,
            shouldLog)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.sum_enemy_army_near_tile. Local tactical enemy-pressure query used by combat/city logic.
    def sum_enemy_army_near_tile(self, startTile: Tile, distance: int = 2) -> int:
        return BotCombatOps.sum_enemy_army_near_tile(self, startTile, distance)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.count_enemy_territory_near_tile. Tactical territory-pressure query used by combat/city heuristics.
    def count_enemy_territory_near_tile(self, startTile: Tile, distance: int = 2) -> int:
        return BotCombatOps.count_enemy_territory_near_tile(self, startTile, distance)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.count_enemy_tiles_near_tile. Small tactical proximity count helper used by combat heuristics.
    def count_enemy_tiles_near_tile(self, startTile: Tile, distance: int = 2) -> int:
        return BotCombatOps.count_enemy_tiles_near_tile(self, startTile, distance)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.sum_player_army_near_tile. Local army-pressure helper for arbitrary player proximity calculations.
    def sum_player_army_near_tile(self, tile: Tile, distance: int = 2, player: int | None = None) -> int:
        return BotCombatOps.sum_player_army_near_tile(self, tile, distance, player)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.sum_player_standing_army_near_or_on_tiles. Shared low-level army aggregation helper used by defense/combat heuristics.
    def sum_player_standing_army_near_or_on_tiles(self, tiles: typing.List[Tile], distance: int = 2, player: int | None = None) -> int:
        return BotCombatOps.sum_player_standing_army_near_or_on_tiles(self, tiles, distance, player)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.sum_friendly_army_near_tile. Friendly-team variant of the local army proximity helper.
    def sum_friendly_army_near_tile(self, tile: Tile, distance: int = 2, player: int | None = None) -> int:
        return BotCombatOps.sum_friendly_army_near_tile(self, tile, distance, player)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.sum_friendly_army_near_or_on_tiles. Shared team-aware army aggregation helper used in economy-defense and tactical checks.
    def sum_friendly_army_near_or_on_tiles(self, tiles: typing.List[Tile], distance: int = 2, player: int | None = None) -> int:
        return BotCombatOps.sum_friendly_army_near_or_on_tiles(self, tiles, distance, player)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_first_path_move. Extremely small convenience wrapper that is broadly referenced.
    def get_first_path_move(self, path: TilePlanInterface):
        return BotPathingUtils.get_first_path_move(self, path)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_afk_players. Cached opponent-state classification helper used for targeting/behavior decisions.
    def get_afk_players(self) -> typing.List[Player]:
        return BotTargeting.get_afk_players(self)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.get_optimal_exploration. Main exploration path planner using watchman routing and target reveal heuristics; keep intact with exploration logic.
    def get_optimal_exploration(
            self,
            turns,
            negativeTiles: typing.Set[Tile] = None,
            valueFunc=None,
            priorityFunc=None,
            initFunc=None,
            skipFunc=None,
            minArmy=0,
            maxTime: float | None = None,
            emergenceRatio: float = 0.15,
            includeCities: bool | None = None,
    ) -> Path | None:
        return BotExpansionOps.get_optimal_exploration(self, turns, negativeTiles, valueFunc, priorityFunc, initFunc, skipFunc, minArmy, maxTime, emergenceRatio, includeCities)

        # allow exploration again
        #
        # negMinArmy = 0 - minArmy
        #
        # logbook.info(f"\n\nAttempting Optimal EXPLORATION (tm) for turns {turns}:\n")
        # startTime = time.perf_counter()
        # generalPlayer = self._map.players[self.general.player]
        # searchingPlayer = self.general.player
        # if negativeTiles is None:
        #     negativeTiles = set()
        # else:
        #     negativeTiles = negativeTiles.copy()
        # logbook.info(f"negativeTiles: {str(negativeTiles)}")
        #
        # distSource = self.general
        # if self.target_player_gather_path is not None:
        #     distSource = self.targetPlayerExpectedGeneralLocation
        # distMap = self._map.distance_mapper.get_tile_dist_matrix(distSource)
        #
        # ourArmies = SearchUtils.where(self.armyTracker.armies.values(), lambda army: army.player == self.general.player and army.tile.player == self.general.player and army.tile.army > 1)
        # ourArmyTiles = [army.tile for army in ourArmies]
        # if len(ourArmyTiles) == 0:
        #     logbook.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 5 instead.")
        #     ourArmyTiles = SearchUtils.where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 5)
        # if len(ourArmyTiles) == 0:
        #     logbook.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 2 instead.")
        #     ourArmyTiles = SearchUtils.where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 2)
        # if len(ourArmyTiles) == 0:
        #     logbook.info("We didn't have any armies to use to optimal_exploration. Using our tiles with army > 1 instead.")
        #     ourArmyTiles = SearchUtils.where(self._map.players[self.general.player].tiles, lambda tile: tile.army > 1)
        #
        # ourArmyTiles = SearchUtils.where(ourArmyTiles, lambda t: t.army > negMinArmy)
        #
        # # require any exploration path go through at least one of these tiles.
        # validExplorationTiles = MapMatrixSet(self._map)
        # for tile in self._map.pathableTiles:
        #     if (
        #             not tile.discovered
        #             and (self.territories.territoryMap[tile] == self.targetPlayer or distMap[tile] < 6)
        #     ):
        #         validExplorationTiles.add(tile)
        #
        # # skipFunc(next, nextVal). Not sure why this is 0 instead of 1, but 1 breaks it. I guess the 1 is already subtracted
        # if not skipFunc:
        #     def skip_after_out_of_army(nextTile, nextVal):
        #         wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = nextVal
        #         if negArmyRemaining >= negMinArmy:
        #             return True
        #         if distSoFar > 6 and negValidExplorationCount == 0:
        #             return True
        #         if wastedMoves > 3:
        #             return True
        #         return False
        #
        #     skipFunc = skip_after_out_of_army
        #
        # if not valueFunc:
        #     def value_priority_army_dist(currentTile, priorityObject):
        #         wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = priorityObject
        #         # negative these back to positive
        #         if negValidExplorationCount == 0:
        #             return None
        #         if negArmyRemaining > 0:
        #             return None
        #
        #         posPathPrio = 0 - pathPriorityDivided
        #
        #         # pathPriority includes emergence values.
        #         value = 0 - (negRevealedCount + enemyTiles * 6 + neutralTiles) / distSoFar
        #
        #         return value, posPathPrio, distSoFar
        #
        #     valueFunc = value_priority_army_dist
        #
        # if not priorityFunc:
        #     def default_priority_func(nextTile, currentPriorityObject):
        #         wastedMoves, pathPriorityDivided, negArmyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, revealedSoFar = currentPriorityObject
        #         armyRemaining = 0 - negArmyRemaining
        #         nextTileSet = tileSetSoFar.copy()
        #         distSoFar += 1
        #         # weight tiles closer to the target player higher
        #         addedPriority = -4 - max(2.0, distMap[nextTile] / 3)
        #         # addedPriority = -7 - max(3, distMap[nextTile] / 4)
        #         if nextTile not in nextTileSet:
        #             armyRemaining -= 1
        #             releventAdjacents = SearchUtils.where(nextTile.adjacents, lambda adjTile: adjTile not in revealedSoFar and adjTile not in tileSetSoFar)
        #             revealedCount = SearchUtils.count(releventAdjacents, lambda adjTile: not adjTile.discovered)
        #             negRevealedCount -= revealedCount
        #             if negativeTiles is None or (nextTile not in negativeTiles):
        #                 if searchingPlayer == nextTile.player:
        #                     armyRemaining += nextTile.army
        #                 else:
        #                     armyRemaining -= nextTile.army
        #             if nextTile in validExplorationTiles:
        #                 negValidExplorationCount -= 1
        #                 addedPriority += 3
        #             nextTileSet.add(nextTile)
        #             # enemytiles or enemyterritory undiscovered tiles
        #             if self.targetPlayer != -1 and (nextTile.player == self.targetPlayer or (not nextTile.visible and self.territories.territoryMap[nextTile] == self.targetPlayer)):
        #                 if nextTile.player == -1:
        #                     # these are usually 2 or more army since usually after army bonus
        #                     armyRemaining -= 2
        #                 #    # points for maybe capping target tiles
        #                 #    addedPriority += 4
        #                 #    enemyTiles -= 0.5
        #                 #    neutralTiles -= 0.5
        #                 #    # treat this tile as if it is at least 1 cost
        #                 # else:
        #                 #    # points for capping target tiles
        #                 #    addedPriority += 6
        #                 #    enemyTiles -= 1
        #                 addedPriority += 8
        #                 enemyTiles -= 1
        #                 ## points for locking all nearby enemy tiles down
        #                 # numEnemyNear = SearchUtils.count(nextTile.adjacents, lambda adjTile: adjTile.player == self.player)
        #                 # numEnemyLocked = SearchUtils.count(releventAdjacents, lambda adjTile: adjTile.player == self.player)
        #                 ##    for every other nearby enemy tile on the path that we've already included in the path, add some priority
        #                 # addedPriority += (numEnemyNear - numEnemyLocked) * 12
        #             elif nextTile.player == -1:
        #                 # we'd prefer to be killing enemy tiles, yeah?
        #                 wastedMoves += 0.2
        #                 neutralTiles -= 1
        #                 # points for capping tiles in general
        #                 addedPriority += 1
        #                 # points for taking neutrals next to enemy tiles
        #                 numEnemyNear = SearchUtils.count(nextTile.movable, lambda adjTile: adjTile not in revealedSoFar and adjTile.player == self.targetPlayer)
        #                 if numEnemyNear > 0:
        #                     addedPriority += 1
        #             else:  # our tiles and non-target enemy tiles get negatively weighted
        #                 # addedPriority -= 2
        #                 # 0.7
        #                 wastedMoves += 1
        #             # points for discovering new tiles
        #             addedPriority += revealedCount * 2
        #             if self.armyTracker.emergenceLocationMap[self.targetPlayer][nextTile] > 0 and not nextTile.visible:
        #                 addedPriority += (self.armyTracker.emergenceLocationMap[self.targetPlayer][nextTile] ** 0.5)
        #             ## points for revealing tiles in the fog
        #             # addedPriority += SearchUtils.count(releventAdjacents, lambda adjTile: not adjTile.visible)
        #         else:
        #             wastedMoves += 1
        #
        #         nextRevealedSet = revealedSoFar.copy()
        #         for adj in SearchUtils.where(nextTile.adjacents, lambda tile: not tile.discovered):
        #             nextRevealedSet.add(adj)
        #         newPathPriority = pathPriority - addedPriority
        #         # if generalPlayer.tileCount < 46:
        #         #    logbook.info("nextTile {}, newPathPriority / distSoFar {:.2f}, armyRemaining {}, newPathPriority {}, distSoFar {}, len(nextTileSet) {}".format(nextTile.toString(), newPathPriority / distSoFar, armyRemaining, newPathPriority, distSoFar, len(nextTileSet)))
        #         return wastedMoves, newPathPriority / distSoFar, 0 - armyRemaining, negValidExplorationCount, negRevealedCount, enemyTiles, neutralTiles, newPathPriority, distSoFar, nextTileSet, nextRevealedSet
        #
        #     priorityFunc = default_priority_func
        #
        # if not initFunc:
        #     def initial_value_func_default(t: Tile):
        #         startingSet = set()
        #         startingSet.add(t)
        #         startingAdjSet = set()
        #         for adj in t.adjacents:
        #             startingAdjSet.add(adj)
        #         return 0, 10, 0 - t.army, 0, 0, 0, 0, 0, 0, startingSet, startingAdjSet
        #
        #     initFunc = initial_value_func_default
        #
        # if turns <= 0:
        #     logbook.info("turns <= 0 in optimal_exploration? Setting to 50")
        #     turns = 50
        # remainingTurns = turns
        # sortedTiles = sorted(ourArmyTiles, key=lambda t: t.army, reverse=True)
        # paths = []
        #
        # player = self._map.players[self.general.player]
        # logStuff = False
        #
        # # BACKPACK THIS EXPANSION! Don't stop at remainingTurns 0... just keep finding paths until out of time, then knapsack them
        #
        # # Switch this up to use more tiles at the start, just removing the first tile in each path at a time. Maybe this will let us find more 'maximal' paths?
        #
        # while sortedTiles:
        #     timeUsed = time.perf_counter() - startTime
        #     # Stages:
        #     # first 0.1s, use large tiles and shift smaller. (do nothing)
        #     # second 0.1s, use all tiles (to make sure our small tiles are included)
        #     # third 0.1s - knapsack optimal stuff outside this loop i guess?
        #     if timeUsed > 0.03:
        #         logbook.info(f"timeUsed {timeUsed:.3f} > 0.03... Breaking loop and knapsacking...")
        #         break
        #
        #     # startIdx = max(0, ((cutoffFactor - 1) * len(sortedTiles))//fullCutoff)
        #
        #     # hack,  see what happens TODO
        #     # tilesLargerThanAverage = SearchUtils.where(generalPlayer.tiles, lambda tile: tile.army > 1)
        #     # logbook.info("Filtered for tilesLargerThanAverage with army > {}, found {} of them".format(tilePercentile[-1].army, len(tilesLargerThanAverage)))
        #     startDict = {}
        #     for i, tile in enumerate(sortedTiles):
        #         # skip tiles we've already used or intentionally ignored
        #         if tile in negativeTiles:
        #             continue
        #         # self.mark_tile(tile, 10)
        #
        #         initVal = initFunc(tile)
        #         # wastedMoves, pathPriorityDivided, armyRemaining, pathPriority, distSoFar, tileSetSoFar
        #         # 10 because it puts the tile above any other first move tile, so it gets explored at least 1 deep...
        #         startDict[tile] = (initVal, 0)
        #     path, pathValue = SearchUtils.breadth_first_dynamic_max(
        #         self._map,
        #         startDict,
        #         valueFunc,
        #         0.025,
        #         remainingTurns,
        #         turns,
        #         noNeutralCities=True,
        #         negativeTiles=negativeTiles,
        #         searchingPlayer=self.general.player,
        #         priorityFunc=priorityFunc,
        #         useGlobalVisitedSet=False,
        #         skipFunc=skipFunc,
        #         logResultValues=logStuff,
        #         includePathValue=True)
        #
        #     if path:
        #         (pathPriorityPerTurn, posPathPrio, distSoFar) = pathValue
        #         logbook.info(f"Path found for maximizing army usage? Duration {time.perf_counter() - startTime:.3f} path {path.toString()}")
        #         node = path.start
        #         # BYPASSED THIS BECAUSE KNAPSACK...
        #         # remainingTurns -= path.length
        #         tilesGrabbed = 0
        #         visited = set()
        #         friendlyCityCount = 0
        #         while node is not None:
        #             negativeTiles.add(node.tile)
        #
        #             if self._map.is_tile_friendly(node.tile) and (node.tile.isCity or node.tile.isGeneral):
        #                 friendlyCityCount += 1
        #             # this tile is now worth nothing because we already intend to use it ?
        #             # skipTiles.add(node.tile)
        #             node = node.next
        #         sortedTiles.remove(path.start.tile)
        #         paths.append((friendlyCityCount, pathPriorityPerTurn, path))
        #     else:
        #         logbook.info("Didn't find a super duper cool optimized EXPLORATION pathy thing. Breaking :(")
        #         break
        #
        # alpha = 75
        # minAlpha = 50
        # alphaDec = 2
        # trimmable = {}
        #
        # # build knapsack weights and values
        # weights = [pathTuple[2].length for pathTuple in paths]
        # values = [int(100 * pathTuple[1]) for pathTuple in paths]
        # logbook.info(f"Feeding the following paths into knapsackSolver at turns {turns}...")
        # for i, pathTuple in enumerate(paths):
        #     friendlyCityCount, pathPriorityPerTurn, curPath = pathTuple
        #     logbook.info(f"{i}:  cities {friendlyCityCount} pathPriorityPerTurn {pathPriorityPerTurn} length {curPath.length} path {curPath.toString()}")
        #
        # totalValue, maxKnapsackedPaths = solve_knapsack(paths, turns, weights, values)
        # logbook.info(f"maxKnapsackedPaths value {totalValue} length {len(maxKnapsackedPaths)},")
        #
        # path = None
        # if len(maxKnapsackedPaths) > 0:
        #     maxVal = (-100, -1)
        #
        #     # Select which of the knapsack paths to move first
        #     for pathTuple in maxKnapsackedPaths:
        #         friendlyCityCount, tilesCaptured, curPath = pathTuple
        #
        #         thisVal = (0 - friendlyCityCount, tilesCaptured / curPath.length)
        #         if thisVal > maxVal:
        #             maxVal = thisVal
        #             path = curPath
        #             logbook.info(f"no way this works, evaluation [{'], ['.join(str(x) for x in maxVal)}], path {path.toString()}")
        #
        #         # draw other paths darker
        #         alpha = 150
        #         minAlpha = 150
        #         alphaDec = 0
        #         self.viewInfo.color_path(PathColorer(curPath, 50, 51, 204, alpha, alphaDec, minAlpha))
        #     logbook.info(f"EXPLORATION PLANNED HOLY SHIT? Duration {time.perf_counter() - startTime:.3f}, path {path.toString()}")
        #     # draw maximal path darker
        #     alpha = 255
        #     minAlpha = 200
        #     alphaDec = 0
        #     self.viewInfo.paths = deque(SearchUtils.where(self.viewInfo.paths, lambda pathCol: pathCol.path != path))
        #     self.viewInfo.color_path(PathColorer(path, 55, 100, 200, alpha, alphaDec, minAlpha))
        # else:
        #     logbook.info(f"No EXPLORATION plan.... :( Duration {time.perf_counter() - startTime:.3f},")
        #
        # return path

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.explore_target_player_undiscovered. Higher-level exploration decision logic around whether/when to run exploration and accept a reveal path.
    def explore_target_player_undiscovered(self, negativeTiles: typing.Set[Tile] | None, onlyHuntGeneral: bool | None = None, maxTime: float | None = None) -> Path | None:
        return BotExpansionOps.explore_target_player_undiscovered(self, negativeTiles, onlyHuntGeneral, maxTime)

        ## don't explore to 1 army from inside our own territory
        ##if not self.timings.in_gather_split(self._map.turn):
        # if skipTiles is None:
        #    skipTiles = set()
        # skipTiles = skipTiles.copy()
        # for tile in genPlayer.tiles:
        #    if self.territories.territoryMap[tile] == self.general.player:
        #        logbook.info("explore: adding tile {} to skipTiles for lowArmy search".format(tile.toString()))
        #        skipTiles.add(tile)

        # path = SearchUtils.breadth_first_dynamic(self._map,
        #                            enemyUndiscBordered,
        #                            goal_func_short,
        #                            0.1,
        #                            3,
        #                            noNeutralCities = True,
        #                            skipTiles = skipTiles,
        #                            searchingPlayer = self.general.player,
        #                            priorityFunc = priority_func_non_all_in)
        # if path is not None:
        #    path = path.get_reversed()
        #    self.info("UD SMALL: depth {} bfd kill (pre-prune) \n{}".format(path.length, path.toString()))

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_median_tile_value. Small targeting/heuristic utility over player tile-army distribution.
    def get_median_tile_value(self, percentagePoint=50, player: int = -1):
        return BotTargeting.get_median_tile_value(self, percentagePoint, player)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.build_mst. Core legacy MST gather/path builder used by multiple gather routines; migrate intact to the gather module.
    def build_mst(self, startTiles, maxTime=0.1, maxDepth=150, negativeTiles: typing.Set[Tile] = None, avoidTiles=None, priorityFunc=None):
        return BotGatherOps.build_mst(self, startTiles, maxTime, maxDepth, negativeTiles, avoidTiles, priorityFunc)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.build_mst_rebuild. Rebuild phase for the legacy MST gather structure; keep adjacent to build_mst.
    def build_mst_rebuild(self, startTiles, fromMap, searchingPlayer):
        return BotGatherOps.build_mst_rebuild(self, startTiles, fromMap, searchingPlayer)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_gather_mst. Recursive gather-tree reconstruction helper used only by the MST gather pipeline.
    def get_gather_mst(self, tile, fromTile, fromMap, turn, searchingPlayer):
        return BotGatherOps.get_gather_mst(self, tile, fromTile, fromMap, turn, searchingPlayer)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_tree_move_non_city_leaf_count. Gather-tree scoring helper used to evaluate leaf/city composition.
    def get_tree_move_non_city_leaf_count(self, gathers):
        return BotGatherOps.get_tree_move_non_city_leaf_count(self, gathers)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps._get_tree_move_non_city_leaf_count_recurse. Internal recursive helper for gather-tree leaf counting; keep adjacent to its caller.
    def _get_tree_move_non_city_leaf_count_recurse(self, gather):
        return BotGatherOps._get_tree_move_non_city_leaf_count_recurse(self, gather)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps._get_tree_move_default_value_func. Default gather-tree move valuation factory; core gather module helper.
    def _get_tree_move_default_value_func(self) -> typing.Callable[[Tile, typing.Tuple], typing.Tuple | None]:
        return BotGatherOps._get_tree_move_default_value_func(self)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_tree_move_default. Central gather-tree-to-move selector used throughout gather/city/defense flows.
    def get_tree_move_default(
            self,
            gathers: typing.List[GatherTreeNode],
            valueFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None] | None = None,
            pop: bool = False
    ) -> Move | None:
        return BotGatherOps.get_tree_move_default(self, gathers, valueFunc, pop)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_threat_killer_move. Threat-specific defensive kill attempt helper; belongs with threat response logic.
    def get_threat_killer_move(self, threat: ThreatObj, searchTurns, negativeTiles) -> Move | None:
        return BotDefense.get_threat_killer_move(self, threat, searchTurns, negativeTiles)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.should_proactively_take_cities. City-capture policy gate deciding when proactive neutral-city taking is strategically allowed.
    def should_proactively_take_cities(self):
        return BotCityOps.should_proactively_take_cities(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.capture_cities. Main city-capture orchestrator covering neutral/enemy city selection, contestation, gather planning, and all-in-on-cities behavior.
    def capture_cities(
            self,
            negativeTiles: typing.Set[Tile],
            forceNeutralCapture: bool = False,
    ) -> typing.Tuple[Path | None, Move | None]:
        return BotCityOps.capture_cities(self, negativeTiles, forceNeutralCapture)

    # DONE STEP2: Move to BotModules/BotRendering.py as BotRendering.mark_tile. Pure view-info annotation helper; presentation-only.
    def mark_tile(self, tile, alpha=100):
        return BotRendering.mark_tile(self, tile, alpha)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.find_neutral_city_path. Neutral-city candidate ranking and path selection logic; belongs in city operations.
    def find_neutral_city_path(self) -> Path | None:
        return BotCityOps.find_neutral_city_path(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.find_enemy_city_path. Enemy-city candidate ranking and path selection logic; belongs in targeting.
    def find_enemy_city_path(self, negativeTiles: TileSet, force: bool = False) -> typing.Tuple[int, Path | None]:
        return BotTargeting.find_enemy_city_path(self, negativeTiles, force)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_approximate_attack_defense_sweet_spot. Attack-vs-defense timing sweep helper for target evaluation over future turn windows.
    def get_approximate_attack_defense_sweet_spot(
            self,
            tile: Tile,
            negativeTiles: TileSet,
            cycleBase: int = 10,
            cycleInterval: int = 5,
            minTurns: int = 0,
            maxTurns: int = 35,
            attackingPlayer: int = -1,
            defendingPlayer: int = -1,
            returnDiffThresh: int = 1000,
            noLog: bool = False
    ) -> typing.Tuple[int, int, int]:
        return BotCombatOps.get_approximate_attack_defense_sweet_spot(self, tile, negativeTiles, cycleBase, cycleInterval, minTurns, maxTurns, attackingPlayer, defendingPlayer, returnDiffThresh, noLog)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_value_per_turn_subsegment. Path-trimming helper that keeps the best value-per-turn suffix for launch/attack paths.
    def get_value_per_turn_subsegment(
            self,
            path: Path,
            minFactor=0.7,
            minLengthFactor=0.1,
            negativeTiles=None
    ) -> Path:
        return BotPathingUtils.get_value_per_turn_subsegment(self, path, minFactor, minLengthFactor, negativeTiles)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.calculate_general_danger. Main danger-analyzer refresh for general/city/ally threats and threat rendering.
    def calculate_general_danger(self):
        return BotDefense.calculate_general_danger(self)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.check_should_be_all_in_losing. Main posture heuristic for switching into losing all-in mode or surrender trajectory.
    def check_should_be_all_in_losing(self) -> bool:
        return BotCombatOps.check_should_be_all_in_losing(self)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.is_move_safe_valid. Basic move sanity/safety wrapper used widely.
    def is_move_safe_valid(self, move, allowNonKill=True):
        return BotPathingUtils.is_move_safe_valid(self, move, allowNonKill)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.general_move_safe. Thin wrapper for checking whether a general move is blocked by danger tiles.
    def general_move_safe(self, target, move_half=False):
        return BotDefense.general_move_safe(self, target, move_half)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_general_move_blocking_tiles. Computes enemy danger tiles that make a general move unsafe.
    def get_general_move_blocking_tiles(self, target: Tile, move_half=False):
        return BotDefense.get_general_move_blocking_tiles(self, target, move_half)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.check_should_defend_economy_based_on_large_tiles. Large-enemy-army heuristic that can trigger econ defense and city-blocking.
    def check_should_defend_economy_based_on_large_tiles(self) -> bool:
        return BotDefense.check_should_defend_economy_based_on_large_tiles(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.should_defend_economy. Main defend-economy policy entrypoint combining large-tile, cycle, and army-near-general heuristics.
    def should_defend_economy(self, defenseTiles: typing.Set[Tile]):
        return BotDefense.should_defend_economy(self, defenseTiles)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_danger_tiles. Small helper returning the enemy tiles participating in current danger paths.
    def get_danger_tiles(self, move_half=False) -> typing.Set[Tile]:
        return BotDefense.get_danger_tiles(self, move_half)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_danger_paths. Builds short danger paths that threaten the general for current-move safety checks.
    def get_danger_paths(self, move_half=False) -> typing.List[Path]:
        return BotDefense.get_danger_paths(self, move_half)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.worth_attacking_target. Main attack-window heuristic deciding whether gather-path value justifies launching at the target.
    def worth_attacking_target(self) -> bool:
        return BotCombatOps.worth_attacking_target(self)

    # DONE STEP2: Move to BotModules/BotStateQueries.py as BotStateQueries.get_player_army_amount_on_path. Small path-aggregation helper for counting a player's army along a path.
    def get_player_army_amount_on_path(self, path, player, startIdx=0, endIdx=1000):
        return BotStateQueries.get_player_army_amount_on_path(self, path, player, startIdx, endIdx)

    # DONE STEP2: Move to BotModules/BotCombatOps.py or BotStateQueries late. Small adjacent-enemy-army helper used for target sizing heuristics.
    def get_target_army_inc_adjacent_enemy(self, tile):
        return BotStateQueries.get_target_army_inc_adjacent_enemy(self, tile)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.find_leaf_move. Chooses the best prioritized leaf capture/expand move with general-safety fallback.
    def find_leaf_move(self, allLeaves):
        return BotExpansionOps.find_leaf_move(self, allLeaves)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.prioritize_expansion_leaves. Scores and orders leaf moves for greedy expansion/capture use.
    def prioritize_expansion_leaves(
            self,
            allLeaves=None,
            allowNonKill=False,
            distPriorityMap: MapMatrixInterface[int] | None = None,
    ) -> typing.List[Move]:
        return BotExpansionOps.prioritize_expansion_leaves(self, allLeaves, allowNonKill, distPriorityMap)

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

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_path_to_target_player. Main launch-path builder toward the current target player/general approximation.
    def get_path_to_target_player(self, isAllIn=False, cutLength: int | None = None) -> Path | None:
        return BotTargeting.get_path_to_target_player(self, isAllIn, cutLength)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_best_defense. Search-based best-defense path finder for saving a tile/general against a threat.
    def get_best_defense(self, defendingTile: Tile, turns: int, negativeTileList: typing.List[Tile]) -> Path | None:
        return BotDefense.get_best_defense(self, defendingTile, turns, negativeTileList)

    # STEP2: Stay in EklipZBotV2.py. Tiny shell logging/view-info convenience helper used broadly across modules.
    def info(self, text):
        self.viewInfo.infoText = text
        self.viewInfo.add_info_line(text)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_path_to_target. Thin single-target wrapper around get_path_to_targets.
    def get_path_to_target(
            self,
            target,
            maxTime=0.1,
            maxDepth=400,
            skipNeutralCities=True,
            skipEnemyCities=False,
            preferNeutral=True,
            fromTile=None,
            preferEnemy=False,
            maxObstacleCost: int | None = None
    ) -> Path | None:
        return BotPathingUtils.get_path_to_target(self, target, maxTime, maxDepth, skipNeutralCities, skipEnemyCities, preferNeutral, fromTile, preferEnemy, maxObstacleCost)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_path_to_targets. Core bot path search wrapper with neutral/enemy/city preference logic.
    def get_path_to_targets(
            self,
            targets,
            maxTime=0.1,
            maxDepth=400,
            skipNeutralCities=True,
            skipEnemyCities=False,
            preferNeutral=True,
            fromTile=None,
            preferEnemy=True,
            maxObstacleCost: int | None = None
    ) -> Path | None:
        return BotPathingUtils.get_path_to_targets(self, targets, maxTime, maxDepth, skipNeutralCities, skipEnemyCities, preferNeutral, fromTile, preferEnemy, maxObstacleCost)

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

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.distance_from_opp. Small wrapper over intergeneral distance matrix used by many heuristics.
    def distance_from_opp(self, sourceTile):
        return BotPathingUtils.distance_from_opp(self, sourceTile)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.distance_from_target_path. Small wrapper over shortest-path distance cache.
    def distance_from_target_path(self, sourceTile):
        return BotPathingUtils.distance_from_target_path(self, sourceTile)

    # STEP2: Stay in EklipZBotV2.py initially, then potentially split later between BotTargeting/BotExpansionOps/BotCombatOps. This scan seeds shared per-turn collections and target-player selection used everywhere.
    def scan_map_for_large_tiles_and_leaf_moves(self):
        self.general_safe_func_set[self.general] = self.general_move_safe
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
        self.targetPlayer = self.calculate_target_player()
        self.opponent_tracker.targetPlayer = self.targetPlayer

        self.targetPlayerObj = self._map.players[self.targetPlayer]

        if self.targetPlayer != oldTgPlayer:
            self._lastTargetPlayerCityCount = 0
            if self.targetPlayer >= 0:
                self._lastTargetPlayerCityCount = self.opponent_tracker.get_current_team_scores_by_player(self.targetPlayer).cityCount

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.determine_should_winning_all_in. High-level combat aggression gate based on army advantage and path distance.
    def determine_should_winning_all_in(self):
        return BotCombatOps.determine_should_winning_all_in(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.find_expected_1v1_general_location_on_undiscovered_map. General-location prediction matrix builder for unseen-spawn targeting.
    def find_expected_1v1_general_location_on_undiscovered_map(
            self,
            undiscoveredCounterDepth: int,
            minSpawnDistance: int
    ) -> MapMatrixInterface[int]:
        return BotTargeting.find_expected_1v1_general_location_on_undiscovered_map(self, undiscoveredCounterDepth, minSpawnDistance)

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings.prune_timing_split_if_necessary. Timing-adjustment helper that tightens launch/split once gatherable tiles are exhausted.
    def prune_timing_split_if_necessary(self):
        return BotTimings.prune_timing_split_if_necessary(self)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_distance_from_board_center. Generic board-geometry helper used by exploration/targeting heuristics.
    def get_distance_from_board_center(self, tile, center_ratio=0.25) -> float:
        return BotPathingUtils.get_distance_from_board_center(self, tile, center_ratio)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_predicted_target_player_general_location. Main enemy-general prediction entrypoint combining emergence, valid spawn masks, hacky fallback search, and exploration fallback.
    def get_predicted_target_player_general_location(self, skipDiscoveredAsNeutralFilter: bool = False) -> Tile:
        return BotTargeting.get_predicted_target_player_general_location(self, skipDiscoveredAsNeutralFilter)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.is_player_spawn_cramped. Spawn-space heuristic used by target/expansion policy decisions.
    def is_player_spawn_cramped(self, spawnDist=-1) -> bool:
        return BotTargeting.is_player_spawn_cramped(self, spawnDist)

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings.timing_cycle_ended. Per-cycle state reset and timing-boundary bookkeeping; belongs in timing/cycle logic.
    def timing_cycle_ended(self):
        return BotTimings.timing_cycle_ended(self)

    # DONE STEP2: Move to BotModules/BotRendering.py as BotRendering.dump_turn_data_to_string. Debug/export serialization for current turn state; presentation/debug concern.
    def dump_turn_data_to_string(self):
        return BotRendering.dump_turn_data_to_string(self)

    # DONE STEP2: Move to BotModules/BotStateQueries.py or BotRendering late in the migration. Tiny string-to-tile parser used mainly by resume/debug serialization helpers.
    def parse_tile_str(self, tileStr: str) -> Tile:
        return BotStateQueries.parse_tile_str(self, tileStr)

    # DONE STEP2: Move to BotModules/BotStateQueries.py late in the migration. Tiny parsing helper used by resume/debug restoration code.
    def parse_bool(self, boolStr: str) -> bool:
        return BotStateQueries.parse_bool(self, boolStr)

    # STEP2: Stay in EklipZBotV2.py or move to a dedicated resume/debug module late. This restores broad bot/runtime state across trackers, timings, paths, and debug serialization.
    def load_resume_data(self, resume_data: typing.Dict[str, str]):
        if f'bot_target_player' in resume_data:  # ={self.player}')
            self.targetPlayer = int(resume_data[f'bot_target_player'])
            if self.targetPlayer >= 0:
                self.targetPlayerObj = self._map.players[self.targetPlayer]
            self.opponent_tracker.targetPlayer = self.targetPlayer
        if f'targetPlayerExpectedGeneralLocation' in resume_data:  # ={self.targetPlayerExpectedGeneralLocation.x},{self.targetPlayerExpectedGeneralLocation.y}')
            self.targetPlayerExpectedGeneralLocation = self.parse_tile_str(resume_data[f'targetPlayerExpectedGeneralLocation'])
        if f'bot_is_all_in_losing' in resume_data:  # ={self.is_all_in_losing}')
            self.is_all_in_losing = self.parse_bool(resume_data[f'bot_is_all_in_losing'])
        if f'bot_all_in_losing_counter' in resume_data:  # ={self.all_in_losing_counter}')
            self.all_in_losing_counter = int(resume_data[f'bot_all_in_losing_counter'])

        if f'bot_is_all_in_army_advantage' in resume_data:  # ={self.is_all_in_army_advantage}')
            self.is_all_in_army_advantage = self.parse_bool(resume_data[f'bot_is_all_in_army_advantage'])
        if f'bot_is_winning_gather_cyclic' in resume_data:  # ={self.is_all_in_army_advantage}')
            self.is_winning_gather_cyclic = self.parse_bool(resume_data[f'bot_is_winning_gather_cyclic'])
        if f'bot_all_in_army_advantage_counter' in resume_data:  # ={self.all_in_army_advantage_counter}')
            self.all_in_army_advantage_counter = int(resume_data[f'bot_all_in_army_advantage_counter'])
        if f'bot_all_in_army_advantage_cycle' in resume_data:  # ={self.all_in_army_advantage_cycle}')
            self.all_in_army_advantage_cycle = int(resume_data[f'bot_all_in_army_advantage_cycle'])
        if f'bot_defend_economy' in resume_data:
            self.defend_economy = self.parse_bool(resume_data[f'bot_defend_economy'])

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
            self.is_rapid_capturing_neut_cities = self.parse_bool(resume_data[f'bot_is_rapid_capturing_neut_cities'])
        if f'bot_is_blocking_neutral_city_captures' in resume_data:  # ={self.is_blocking_neutral_city_captures}')
            self.is_blocking_neutral_city_captures = self.parse_bool(resume_data[f'bot_is_blocking_neutral_city_captures'])
        if f'bot_finishing_exploration' in resume_data:  # ={self.finishing_exploration}')
            self.finishing_exploration = self.parse_bool(resume_data[f'bot_finishing_exploration'])
        if f'bot_targeting_army' in resume_data:  # ={self.targetingArmy.tile.x},{self.targetingArmy.tile.y}')
            self.targetingArmy = self.get_army_at(self.parse_tile_str(resume_data[f'bot_targeting_army']))
        else:
            self.targetingArmy = None
        if f'bot_cur_path' in resume_data:  # ={str(self.curPath)}')
            self.curPath = TextMapLoader.parse_path(self._map, resume_data[f'bot_cur_path'])
        else:
            self.curPath = None

        for player in self._map.players:
            char = PLAYER_CHAR_BY_INDEX[player.index]
            if f'{char}Emergences' in resume_data:
                self.armyTracker.emergenceLocationMap[player.index] = self.convert_string_to_float_map_matrix(resume_data[f'{char}Emergences'])
            elif f'targetPlayerExpectedGeneralLocation' in resume_data and player.index == self.targetPlayer and len(self._map.players[self.targetPlayer].tiles) > 0:
                # only do the old behavior when explicit emergences arent available.
                self.armyTracker.emergenceLocationMap[self.targetPlayer][self.targetPlayerExpectedGeneralLocation] = 5
            if f'{char}ValidGeneralPos' in resume_data:
                self.armyTracker.valid_general_positions_by_player[player.index] = self.convert_string_to_bool_map_matrix_set(resume_data[f'{char}ValidGeneralPos'])
            if f'{char}TilesEverOwned' in resume_data:
                self.armyTracker.tiles_ever_owned_by_player[player.index] = self.convert_string_to_tile_set(resume_data[f'{char}TilesEverOwned'])
            if f'{char}UneliminatedEmergences' in resume_data:
                self.armyTracker.uneliminated_emergence_events[player.index] = self.convert_string_to_tile_int_dict(resume_data[f'{char}UneliminatedEmergences'])
            if f'{char}UneliminatedEmergenceCityPerfectInfo' in resume_data:
                self.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index] = self.convert_string_to_tile_set(resume_data[f'{char}UneliminatedEmergenceCityPerfectInfo'])
            else:
                self.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index] = {t for t in self.armyTracker.uneliminated_emergence_events[player.index].keys()}
            if f'{char}UnrecapturedEmergences' in resume_data:
                self.armyTracker.unrecaptured_emergence_events[player.index] = self.convert_string_to_tile_set(resume_data[f'{char}UnrecapturedEmergences'])
            else:
                pUnelim = self.armyTracker.uneliminated_emergence_events[player.index]
                pUnrecaptured = self.armyTracker.unrecaptured_emergence_events[player.index]
                for t in self._map.get_all_tiles():
                    if t in pUnelim:
                        pUnrecaptured.add(t)

        if f'TempFogTiles' in resume_data:
            tiles = self.convert_string_to_tile_set(resume_data[f'TempFogTiles'])
            for tile in tiles:
                tile.isTempFogPrediction = True
        if f'DiscoveredNeutral' in resume_data:
            tiles = self.convert_string_to_tile_set(resume_data[f'DiscoveredNeutral'])
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
        #
        # for player in self._map.players:
        #     char = PLAYER_CHAR_BY_INDEX[player.index]
        #
        #     # if f'{char}StandingArmy' in resume_data:  # ={player.standingArmy}')
        #     #     self.something = int(resume_data[f'{char}StandingArmy'])
        #     # if f'{char}KnowsKingLocation' in resume_data:  # ={player.knowsKingLocation}')
        #     #     self._map.players[player.index].knowsKingLocation = self.parse_bool(resume_data[f'{char}KnowsKingLocation'])
        #     # if self._map.is_2v2:
        #     #     if f'{char}KnowsAllyKingLocation' in resume_data:  # ={player.knowsAllyKingLocation}')
        #     #         self.something = int(resume_data[f'{char}KnowsAllyKingLocation'])
        #     # if f'{char}Dead' in resume_data:  # ={player.dead}')
        #     #     self.something = int(resume_data[f'{char}Dead'])
        #     # if f'{char}LeftGame' in resume_data:  # ={player.leftGame}')
        #     #     self.something = int(resume_data[f'{char}LeftGame'])
        #     # if f'{char}LeftGameTurn' in resume_data:  # ={player.leftGameTurn}')
        #     #     self.something = int(resume_data[f'{char}LeftGameTurn'])
        #     # if f'{char}AggressionFactor' in resume_data:  # ={player.aggression_factor}')
        #     #     self.something = int(resume_data[f'{char}AggressionFactor'])
        #     # if f'{char}Delta25Tiles' in resume_data:  # ={player.delta25tiles}')
        #     #     self.something = int(resume_data[f'{char}Delta25Tiles'])
        #     # if f'{char}Delta25Score' in resume_data:  # ={player.delta25score}')
        #     #     self.something = int(resume_data[f'{char}Delta25Score'])
        #     # if f'{char}CityGainedTurn' in resume_data:  # ={player.cityGainedTurn}')
        #     #     self.something = int(resume_data[f'{char}CityGainedTurn'])
        #     # if f'{char}CityLostTurn' in resume_data:  # ={player.cityLostTurn}')
        #     #     self.something = int(resume_data[f'{char}CityLostTurn'])
        #     # if f'{char}LastSeenMoveTurn' in resume_data:  # ={player.last_seen_move_turn}')
        #     #     self.something = int(resume_data[f'{char}LastSeenMoveTurn'])
        #     # if len(self.generalApproximations) > player.index:
        #     #     if self.generalApproximations[player.index][3] is not None:
        #     #         if f'{char}_bot_general_approx' in resume_data:  # ={str(self.generalApproximations[player.index][3])}')
        #     #             self.something = int(resume_data[f'{char}_bot_general_approx'])

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.is_move_safe_against_threats. Small defensive validation helper against current kill threats.
    def is_move_safe_against_threats(self, move: Move):
        return BotDefense.is_move_safe_against_threats(self, move)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_gather_to_threat_path. Thin single-threat adapter into the multi-threat defensive gather planner.
    def get_gather_to_threat_path(
            self,
            threat: ThreatObj,
            force_turns_up_threat_path=0,
            gatherMax: bool = True,
            shouldLog: bool = False,
            addlTurns: int = 0,
            requiredContribution: int | None = None,
            additionalNegatives: typing.Set[Tile] | None = None,
            interceptArmy: bool = False,
            timeLimit: float | None = None
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        return BotDefense.get_gather_to_threat_path(
            self,
            threat,
            force_turns_up_threat_path,
            gatherMax,
            shouldLog,
            addlTurns,
            requiredContribution,
            additionalNegatives,
            interceptArmy=interceptArmy,
            timeLimit=timeLimit
        )

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_gather_to_threat_paths. Main defensive gather entrypoint for one or more threat paths; keep with defense/interception logic.
    def get_gather_to_threat_paths(
            self,
            threats: typing.List[ThreatObj],
            force_turns_up_threat_path=0,
            gatherMax: bool = True,
            shouldLog: bool = False,
            addlTurns: int = 0,
            requiredContribution: int | None = None,
            additionalNegatives: typing.Set[Tile] | None = None,
            interceptArmy: bool = False,
            timeLimit: float | None = None
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        return BotDefense.get_gather_to_threat_paths(self, threats, force_turns_up_threat_path, gatherMax, shouldLog, addlTurns, requiredContribution, additionalNegatives, interceptArmy, timeLimit)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.try_threat_gather. Core defensive gather implementation for intercept/survival contribution planning.
    def try_threat_gather(
            self,
            threats: typing.List[ThreatObj],
            distDict,
            gatherDepth,
            force_turns_up_threat_path,
            requiredContribution,
            gatherMax,
            additionalNegatives,
            timeLimit,
            pruneDepth: int | None = None,
            shouldLog: bool = False,
            fastMode: bool = False
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        return BotDefense.try_threat_gather(self, threats, distDict, gatherDepth, force_turns_up_threat_path, requiredContribution, gatherMax, additionalNegatives, timeLimit, pruneDepth, shouldLog, fastMode)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_gather_to_threat_path_greedy. Greedy/faster defensive gather fallback for threat interception.
    def get_gather_to_threat_path_greedy(
            self,
            threat: ThreatObj,
            force_turns_up_threat_path=0,
            gatherMax: bool = True,
            shouldLog: bool = False
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        return BotDefense.get_gather_to_threat_path_greedy(self, threat, force_turns_up_threat_path, gatherMax, shouldLog)

    # STEP2: Stay in EklipZBotV2.py initially, then potentially split across BotTargeting/BotTimings/BotComms later. This recalculates shared target/gather/flank state used by many modules.
    def recalculate_player_paths(self, force: bool = False):
        self.ensure_reachability_matrix_built()
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

            self.shortest_path_to_target_player = self.get_path_to_target_player(isAllIn=self.is_all_in(), cutLength=None)
            self.info(f'DEBUG: shortest_path_to_target_player {self.shortest_path_to_target_player}')
            if self.shortest_path_to_target_player is None:
                self.shortest_path_to_target_player = Path()
                self.shortest_path_to_target_player.add_next(self.general)
                self.shortest_path_to_target_player.add_next(next(iter(self.general.movableNoObstacles)))

            self.enemy_attack_path = self.get_enemy_probable_attack_path(self.targetPlayer)

            self.target_player_gather_path = self.shortest_path_to_target_player

            # limit = max(self._map.cols, self._map.rows)
            # if self.target_player_gather_path is not None and self.target_player_gather_path.length > limit and self._map.players[self.general.player].cityCount > 1:
            #     self.target_player_gather_path = self.target_player_gather_path.get_subsegment(limit, end=True)

            if self.teammate_communicator is not None and self.teammate_general is not None:
                self.teammate_communicator.determine_leads(self._gen_distances, self._ally_distances, self.targetPlayerExpectedGeneralLocation)

        if self.targetPlayer != -1 and self.target_player_gather_path is not None:
            with self.perf_timer.begin_move_event(f'find sketchiest fog flank'):
                self.sketchiest_potential_inbound_flank_path = self.find_sketchiest_fog_flank_from_enemy()
            if self.sketchiest_potential_inbound_flank_path is not None:
                self.viewInfo.add_stats_line(f'skFlank: {self.sketchiest_potential_inbound_flank_path}')
                self.viewInfo.color_path(PathColorer(
                    self.sketchiest_potential_inbound_flank_path, 0, 0, 0
                ))

        spawnDist = 12
        if self.target_player_gather_path is not None:
            pathTillVisibleToTarget = self.target_player_gather_path
            if self.targetPlayer != -1 and self.is_ffa_situation():
                pathTillVisibleToTarget = self.target_player_gather_path.get_subsegment_until_visible_to_player(self._map.get_teammates(self.targetPlayer))
            self.target_player_gather_targets = {t for t in pathTillVisibleToTarget.tileList if not t.isSwamp and (not t.isDesert or self._map.is_tile_friendly(t))}
            if len(self.target_player_gather_targets) == 0:
                self.info(f'WARNING, BAD GATHER TARGETS, CANT AVOID DESERTS AND SWAMPS...')
                self.target_player_gather_targets = self.target_player_gather_path.tileSet
            spawnDist = self.shortest_path_to_target_player.length
        else:
            self.target_player_gather_targets = None

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
    #                 logbook.info(f"Adjacent kill on general lul :^) {enemyGeneral.x},{enemyGeneral.y}")
    #                 return Move(adj, enemyGeneral)
    #
    #     return None

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.check_for_king_kills_and_races. Major combat/race evaluation routine that decides enemy-general kill and race actions.
    def check_for_king_kills_and_races(self, threat: ThreatObj | None, force: bool = False) -> typing.Tuple[Move | None, Path | None, float]:
        return BotCombatOps.check_for_king_kills_and_races(self, threat, force)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.determine_fog_defense_amount_available_for_tiles. Estimates how much fog defense can actually reach a tile set after excluding unreachable hidden armies.
    def determine_fog_defense_amount_available_for_tiles(self, targetTiles, enPlayer, fogDefenseTurns: int = 0, fogReachTurns: int = 8) -> int:
        return BotDefense.determine_fog_defense_amount_available_for_tiles(self, targetTiles, enPlayer, fogDefenseTurns, fogReachTurns)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.calculate_target_player. Main opponent-selection heuristic across visibility, aggression, economy, and distance.
    def calculate_target_player(self) -> int:
        return BotTargeting.calculate_target_player(self)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_gather_tiebreak_matrix. Core gather tie-break matrix builder based on terrain, expansion plan, and play-area posture.
    def get_gather_tiebreak_matrix(self) -> MapMatrixInterface[float]:
        return BotGatherOps.get_gather_tiebreak_matrix(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.check_defense_intercept_move. Primary defense-intercept chooser that selects or rejects interception plans against a threat.
    def check_defense_intercept_move(self, threat: ThreatObj) -> typing.Tuple[Move | None, Path | None, InterceptionOptionInfo | None, bool]:
        return BotDefense.check_defense_intercept_move(self, threat)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.check_kill_threat_only_defense_interception. Fallback solo interception search for direct general-kill threats.
    def check_kill_threat_only_defense_interception(self, threat: ThreatObj) -> typing.Tuple[Move | None, Path | None, InterceptionOptionInfo | None, bool]:
        return BotDefense.check_kill_threat_only_defense_interception(self, threat)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.check_defense_hybrid_intercept_moves. Hybrid planner that combines interception value with a pruned defense gather tree.
    def check_defense_hybrid_intercept_moves(self, threat: ThreatObj, defensePlan: typing.List[GatherTreeNode], missingDefense: int, defenseNegatives: typing.Set[Tile]) -> typing.Tuple[Move | None, Path | None, bool, typing.List[GatherTreeNode]]:
        return BotDefense.check_defense_hybrid_intercept_moves(self, threat, defensePlan, missingDefense, defenseNegatives)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense._is_invalid_defense_intercept_for_threat. Tiny validator preventing intercepts that originate from the threatened path itself.
    def _is_invalid_defense_intercept_for_threat(self, interceptPath: TilePlanInterface | Path | None, threat: ThreatObj) -> bool:
        return BotDefense._is_invalid_defense_intercept_for_threat(self, interceptPath, threat)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_defense_path_option_from_options_if_available. Selects a usable intercept option from expansion/intercept plan state for a given threat.
    def get_defense_path_option_from_options_if_available(self, threatInterceptionPlan: ArmyInterception, threat: ThreatObj) -> typing.Tuple[InterceptionOptionInfo | None, TilePlanInterface | None]:
        return BotDefense.get_defense_path_option_from_options_if_available(self, threatInterceptionPlan, threat)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_defense_moves. Main defense orchestrator combining threat gathers, intercepts, pruning, fallback races, and ally coordination.
    def get_defense_moves(
            self,
            defenseCriticalTileSet: typing.Set[Tile],
            raceEnemyKingKillPath: Path | None,
            raceChance: float
    ) -> typing.Tuple[Move | None, Path | None]:
        return BotDefense.get_defense_moves(self, defenseCriticalTileSet, raceEnemyKingKillPath, raceChance)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.attempt_first_25_collision_reroute. Early-game expansion replanning helper for collision/no-op rerouting.
    def attempt_first_25_collision_reroute(
            self,
            curPath: Path,
            move: Move,
            distMap: MapMatrixInterface[int]
    ) -> Path | None:
        return BotExpansionOps.attempt_first_25_collision_reroute(self, curPath, move, distMap)

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

        self.initialize_logging()
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

        self._map.notify_city_found.append(self.handle_city_found)
        self._map.notify_tile_captures.append(self.handle_tile_captures)
        self._map.notify_tile_deltas.append(self.handle_tile_deltas)
        self._map.notify_tile_discovered.append(self.handle_tile_discovered)
        self._map.notify_tile_vision_changed.append(self.handle_tile_vision_change)
        self._map.notify_player_captures.append(self.handle_player_captures)
        if self.territories is None:
            self.territories = TerritoryClassifier(self._map)

        self.armyTracker = ArmyTracker(self._map, self.perf_timer)
        self.armyTracker.notify_unresolved_army_emerged.append(self.handle_tile_vision_change)
        self.armyTracker.notify_army_moved.append(self.handle_army_moved)
        self.armyTracker.notify_army_moved.append(self.opponent_tracker.notify_army_moved)
        self.targetPlayerExpectedGeneralLocation = self.general.movable[0]
        self.tileIslandBuilder = TileIslandBuilder(self._map)
        self.tileIslandBuilder.recalculate_tile_islands(enemyGeneralExpectedLocation=self.targetPlayerExpectedGeneralLocation)
        self.launchPoints.append(self.general)
        self.board_analysis = BoardAnalyzer(self._map, self.general, self.teammate_general)
        self.army_interceptor = ArmyInterceptor(self._map, self.board_analysis)
        self.win_condition_analyzer = WinConditionAnalyzer(self._map, self.opponent_tracker, self.cityAnalyzer, self.territories, self.board_analysis)
        self.capture_line_tracker = CaptureLineTracker(self._map)
        self.timing_cycle_ended()
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

    # DONE STEP2: Move to BotModules/BotRendering.py as BotRendering.add_city_score_to_view_info or keep as a static rendering utility. Pure view-info formatting helper.
    @staticmethod
    def add_city_score_to_view_info(score: CityScoreData, viewInfo: ViewInfo):
        return BotRendering.add_city_score_to_view_info(score, viewInfo)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.get_quick_kill_on_enemy_cities. Quick tactical city-kill and opportunistic city-capture planner.
    def get_quick_kill_on_enemy_cities(self, defenseCriticalTileSet: typing.Set[Tile]) -> Path | None:
        return BotCityOps.get_quick_kill_on_enemy_cities(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotRendering.py as BotRendering.prep_view_info_for_render. Large render-prep routine that populates view/debug overlays only.
    def prep_view_info_for_render(self, move: Move | None = None):
        return BotRendering.prep_view_info_for_render(self, move)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_move_if_afk_player_situation. Special-case AFK-opponent targeting/exploration behavior.
    def get_move_if_afk_player_situation(self) -> Move | None:
        return BotTargeting.get_move_if_afk_player_situation(self)

    # DONE STEP2: Move to BotModules/BotEventHandlers.py as BotEventHandlers.clear_fog_armies_around or BotTargeting late. Tracker cleanup helper around known enemy-general locations.
    def clear_fog_armies_around(self, enemyGeneral: Tile):
        return BotEventHandlers.clear_fog_armies_around(self, enemyGeneral)

    # DONE STEP2: Move to BotModules/BotLifecycle.py as BotLifecycle.initialize_logging. Small logging bootstrap helper tied to replay/user context.
    def initialize_logging(self):
        return BotLifecycle.initialize_logging(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_max_explorable_undiscovered_tile. Selects the best cached undiscovered tile candidate for exploration/targeting.
    def get_max_explorable_undiscovered_tile(self, minSpawnDist: int):
        return BotTargeting.get_max_explorable_undiscovered_tile(self, minSpawnDist)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_safe_per_tile_bfs_depth. Small map-size-based BFS depth policy helper.
    def get_safe_per_tile_bfs_depth(self):
        return BotTargeting.get_safe_per_tile_bfs_depth(self)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.try_gather_tendrils_towards_enemy. Experimental/fallback expansion-gather helper toward enemy territory.
    def try_gather_tendrils_towards_enemy(self, turns: int | None = None) -> Move | None:
        return BotExpansionOps.try_gather_tendrils_towards_enemy(self, turns)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_army_scrim_move. Thin wrapper converting scrim simulation output into a move decision.
    def get_army_scrim_move(
            self,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            friendlyHasKillThreat: bool | None = None,
            forceKeepMove=False
    ) -> Move | None:
        return BotCombatOps.get_army_scrim_move(self, friendlyArmyTile, enemyArmyTile, friendlyHasKillThreat, forceKeepMove)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_army_scrim_paths. Scrim simulation wrapper returning rendered friendly/enemy path projections.
    def get_army_scrim_paths(
            self,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            enemyCannotMoveAway: bool = True,
            friendlyHasKillThreat: bool | None = None
    ) -> typing.Tuple[Path | None, Path | None, ArmySimResult]:
        return BotCombatOps.get_army_scrim_paths(self, friendlyArmyTile, enemyArmyTile, enemyCannotMoveAway, friendlyHasKillThreat)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_army_scrim_result. Builds army lists and invokes the scrim engine for one primary friendly/enemy pairing.
    def get_army_scrim_result(
            self,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            enemyCannotMoveAway: bool = False,
            enemyHasKillThreat: bool | None = None,
            friendlyHasKillThreat: bool | None = None,
            friendlyPrecomputePaths: typing.List[Move | None] | None = None
    ) -> ArmySimResult:
        return BotCombatOps.get_army_scrim_result(self, friendlyArmyTile, enemyArmyTile, enemyCannotMoveAway, enemyHasKillThreat, friendlyHasKillThreat, friendlyPrecomputePaths)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_armies_scrim_result. Main ArmyEngine/MCTS scrim evaluation entrypoint; keep intact as a combat-engine cluster.
    def get_armies_scrim_result(
            self,
            friendlyArmies: typing.List[Army],
            enemyArmies: typing.List[Army],
            enemyCannotMoveAway: bool = False,
            enemyHasKillThreat: bool | None = None,
            friendlyHasKillThreat: bool | None = None,
            time_limit: float = 0.05,
            friendlyPrecomputePaths: typing.List[Move | None] | None = None
    ) -> ArmySimResult:
        return BotCombatOps.get_armies_scrim_result(self, friendlyArmies, enemyArmies, enemyCannotMoveAway, enemyHasKillThreat, friendlyHasKillThreat, time_limit, friendlyPrecomputePaths)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.extend_interspersed_path_moves. Small scrim-render helper for reconstructing per-side paths from interleaved move sequences.
    def extend_interspersed_path_moves(self, paths: typing.List[Path], move: Move | None):
        return BotCombatOps.extend_interspersed_path_moves(self, paths, move)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.extract_engine_result_paths_and_render_sim_moves. Converts scrim engine output into representative paths and view rendering.
    def extract_engine_result_paths_and_render_sim_moves(self, result: ArmySimResult) -> typing.Tuple[Path | None, Path | None]:
        return BotCombatOps.extract_engine_result_paths_and_render_sim_moves(self, result)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.is_tile_in_range_from. Generic distance/range utility with cached-general fast paths.
    def is_tile_in_range_from(self, source: Tile, target: Tile, maxDist: int, minDist: int = 0) -> bool:
        return BotPathingUtils.is_tile_in_range_from(self, source, target, maxDist, minDist)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.continue_killing_target_army. Ongoing targeted-army pursuit/intercept continuation logic.
    def continue_killing_target_army(self) -> Move | None:
        return BotCombatOps.continue_killing_target_army(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.build_intercept_plans. Main interception-plan builder over current danger analyzer threats and army-interceptor outputs.
    def build_intercept_plans(self, negTiles: typing.Set[Tile] | None = None) -> typing.Dict[Tile, ArmyInterception]:
        return BotDefense.build_intercept_plans(self, negTiles)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.should_bypass_army_danger_due_to_last_move_turn. Small stale-threat filtering helper for intercept planning.
    def should_bypass_army_danger_due_to_last_move_turn(self, tile: Tile) -> bool:
        return BotDefense.should_bypass_army_danger_due_to_last_move_turn(self, tile)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.try_find_counter_army_scrim_path_killpath. Thin wrapper around scrim-based counter-army kill evaluation.
    def try_find_counter_army_scrim_path_killpath(
            self,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> Path | None:
        return BotCombatOps.try_find_counter_army_scrim_path_killpath(self, threatPath, allowGeneral, forceEnemyTowardsGeneral)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.try_find_counter_army_scrim_path_kill. Scrim-based counter-army kill evaluator that may retarget targetingArmy.
    def try_find_counter_army_scrim_path_kill(
            self,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> typing.Tuple[Path | None, ArmySimResult | None]:
        return BotCombatOps.try_find_counter_army_scrim_path_kill(self, threatPath, allowGeneral, forceEnemyTowardsGeneral)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.try_find_counter_army_scrim_path. Core scrim-based counterplay planner against an incoming threat path.
    def try_find_counter_army_scrim_path(
            self,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> typing.Tuple[Path | None, ArmySimResult | None]:
        return BotCombatOps.try_find_counter_army_scrim_path(self, threatPath, allowGeneral, forceEnemyTowardsGeneral)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.find_large_tiles_near. Shared tile-selection utility for nearby large armies used by combat/defense/scrim logic.
    def find_large_tiles_near(
            self,
            fromTiles: typing.List[Tile],
            distance: int,
            forPlayer=-2,
            allowGeneral: bool = True,
            limit: int = 5,
            minArmy: int = 10,
            addlFilterFunc: typing.Callable[[Tile, int], bool] | None = None,
            allowTeam: bool = False
    ) -> typing.List[Tile]:
        return BotCombatOps.find_large_tiles_near(self, fromTiles, distance, forPlayer, allowGeneral, limit, minArmy, addlFilterFunc, allowTeam)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.check_for_army_movement_scrims. Tactical scrim continuation/search over armies observed moving this turn.
    def check_for_army_movement_scrims(self, econCutoff=2.0) -> Move | None:
        return BotCombatOps.check_for_army_movement_scrims(self, econCutoff)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.should_force_gather_to_enemy_tiles. Small policy helper deciding whether local enemy territory pressure near general requires forced cleanup.
    def should_force_gather_to_enemy_tiles(self) -> bool:
        return BotDefense.should_force_gather_to_enemy_tiles(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.check_for_danger_tile_moves. Short-range tactical cleanup of immediate danger tiles near the general/path.
    def check_for_danger_tile_moves(self) -> Move | None:
        return BotDefense.check_for_danger_tile_moves(self)

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
    #     GatherTreeNode.iterate_tree_nodes(pruned, largestGatherTreeNodeFunc)
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

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.get_optimal_city_or_general_plan_move. Early expansion/city-plan optimization entrypoint for start-game planning.
    def get_optimal_city_or_general_plan_move(self, timeLimit: float = 4.0) -> Move | None:
        return BotExpansionOps.get_optimal_city_or_general_plan_move(self, timeLimit)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.look_for_ffa_turtle_move. Narrow FFA-specific turtle/city-take opportunistic behavior.
    def look_for_ffa_turtle_move(self) -> Move | None:
        return BotExpansionOps.look_for_ffa_turtle_move(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.plan_city_capture. Main city capture planner covering direct kills, gathers, pruning, and follow-up path generation.
    def plan_city_capture(
            self,
            targetCity: Tile,
            cityGatherPath: Path | None,
            allowGather: bool,
            targetKillArmy: int,
            targetGatherArmy: int,
            killSearchDist: int,
            gatherMaxDuration: int,
            negativeTiles: typing.Set[Tile],
            gatherMinDuration: int = 0,
    ) -> typing.Tuple[Path | None, Move | None]:
        return BotCityOps.plan_city_capture(self, targetCity, cityGatherPath, allowGather, targetKillArmy, targetGatherArmy, killSearchDist, gatherMaxDuration, negativeTiles, gatherMinDuration)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_timing_gather_negatives_unioned. Policy helper that builds the negative-tile set for timing gathers.
    def get_timing_gather_negatives_unioned(
            self,
            gatherNegatives: typing.Set[Tile],
            additional_offset: int = 0,
            forceAllowCities: bool = False,
    ) -> typing.Set[Tile]:
        return BotGatherOps.get_timing_gather_negatives_unioned(self, gatherNegatives, additional_offset, forceAllowCities)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.is_path_moving_mostly_away. Small path-direction heuristic used to reject bad gathers/paths.
    def is_path_moving_mostly_away(self, path: Path, bMap: MapMatrixInterface[int]):
        return BotPathingUtils.is_path_moving_mostly_away(self, path, bMap)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.check_army_out_of_play_ratio. Core heuristic for detecting and reacting to army being too far out of the main play area.
    def check_army_out_of_play_ratio(self) -> bool:
        return BotExpansionOps.check_army_out_of_play_ratio(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.should_allow_neutral_city_capture. Main neutral-city policy gate combining defense risk, economy posture, and forced-city logic.
    def should_allow_neutral_city_capture(
            self,
            genPlayer: Player,
            forceNeutralCapture: bool,
            targetCity: Tile | None = None
    ) -> bool:
        return BotCityOps.should_allow_neutral_city_capture(self, genPlayer, forceNeutralCapture, targetCity)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.find_hacky_path_to_find_target_player_spawn_approx. Fallback spawn-approximation search through undiscovered space.
    def find_hacky_path_to_find_target_player_spawn_approx(self, minSpawnDist: int):
        return BotTargeting.find_hacky_path_to_find_target_player_spawn_approx(self, minSpawnDist)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.should_rapid_capture_neutral_cities. Policy heuristic for switching into rapid city-capture mode.
    def should_rapid_capture_neutral_cities(self) -> bool:
        return BotCityOps.should_rapid_capture_neutral_cities(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.find_rapid_city_path. Fast opportunistic city path finder used when rapid city-capture mode is active.
    def find_rapid_city_path(self) -> Path | None:
        return BotCityOps.find_rapid_city_path(self)

    # DONE STEP2: Stay in EklipZBotV2.py or move late to BotTimings as a tiny perf-budget helper. Computes remaining safe time budget for the move.
    def get_remaining_move_time(self) -> float:
        return BotTimings.get_remaining_move_time(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.should_abandon_king_defense. Tiny defense-policy predicate for when defense can be relaxed.
    def should_abandon_king_defense(self) -> bool:
        return BotDefense.should_abandon_king_defense(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.block_neutral_captures. Small stateful helper that cancels/blocks ongoing neutral-city plans.
    def block_neutral_captures(self, reason: str = ''):
        return BotCityOps.block_neutral_captures(self, reason)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.continue_cur_path or keep late on shell. Stateful curPath execution/cleanup with safety checks across domains.
    def continue_cur_path(self, threat: ThreatObj | None, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotPathingUtils.continue_cur_path(self, threat, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.try_find_gather_move. High-level gather policy selector for all-in, enemy-gather, and neutral-gather cases.
    def try_find_gather_move(
            self,
            threat: ThreatObj | None,
            defenseCriticalTileSet: typing.Set[Tile],
            leafMoves: typing.List[Move],
            needToKillTiles: typing.List[Tile],
    ) -> Move | None:
        return BotGatherOps.try_find_gather_move(self, threat, defenseCriticalTileSet, leafMoves, needToKillTiles)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_main_gather_move. Main gather planner/policy routine coordinating gather targets, negatives, and timing logic.
    def get_main_gather_move(
            self,
            defenseCriticalTileSet: typing.Set[Tile],
            leafMoves: typing.List[Move] | None,
            enemyGather: bool = False,
            neutralGather: bool = False,
            needToKillTiles: typing.List[Tile] | None = None,
    ) -> Move | None:
        return BotGatherOps.get_main_gather_move(self, defenseCriticalTileSet, leafMoves, enemyGather, neutralGather, needToKillTiles)

    # DONE STEP2: Move to BotModules/BotRendering.py as BotRendering.render_tile_deltas_in_view_info. Static debug-render helper for per-tile delta overlays.
    @staticmethod
    def render_tile_deltas_in_view_info(viewInfo: ViewInfo, map: MapBase):
        return BotRendering.render_tile_deltas_in_view_info(viewInfo, map)

    # DONE STEP2: Move to BotModules/BotRendering.py as BotRendering.render_tile_state_in_view_info. Static debug-render helper for tile/pathability state overlays.
    @staticmethod
    def render_tile_state_in_view_info(viewInfo: ViewInfo, map: MapBase):
        return BotRendering.render_tile_state_in_view_info(viewInfo, map)


    # def check_if_need_to_gather_longer_to_hold_fresh_cities(self):
    #     freshCityCount = 0
    #     sketchiestCity: Tile = self.general
    #     contestCity: Tile | None = None
    #
    #     offset = 8
    #
    #     for city in self._map.players[self.general.player].cities:
    #         if not self._map.is_player_on_team_with(city.delta.oldOwner, self.general.player):
    #             freshCityCount += 1
    #
    #             nearerToUs = self.board_analysis.intergeneral_analysis.aMap[city] < self.board_analysis.intergeneral_analysis.bMap[city]
    #             nearerToEnemyThanSketchiest = self.board_analysis.intergeneral_analysis.bMap[city] < self.board_analysis.intergeneral_analysis.bMap[sketchiestCity]
    #             enemyTilesVisionRange = self.count_enemy_tiles_near_tile(city, 2)
    #             enemyTilesNear = self.count_enemy_tiles_near_tile(city, self.shortest_path_to_target_player.length // 5)
    #             if nearerToUs and nearerToEnemyThanSketchiest and (enemyTilesNear > 5 or enemyTilesVisionRange > 0):
    #                 sketchiestCity = city
    #             elif city.delta.oldOwner >= 0 and (contestCity is None or self.board_analysis.intergeneral_analysis.aMap[city] < self.board_analysis.intergeneral_analysis.aMap[contestCity]):
    #                 contestCity = city
    #
    #             if city.delta.oldOwner >= 0:
    #                 offset = 7
    #
    #     earlyCycleSlightlyWinning = self.timings is not None and self.timings.get_turn_in_cycle(self._map.turn) < 15 and self.opponent_tracker.winning_on_economy(byRatio=1.05)
    #     heavilyWinning = self.opponent_tracker.winning_on_economy(byRatio=1.25, cityValue=35, offset=-5)
    #
    #     if (heavilyWinning or earlyCycleSlightlyWinning) and self.all_in_city_behind and self.opponent_tracker.even_or_up_on_cities():
    #         self.all_in_city_behind = False
    #         self.is_all_in_losing = False
    #         self.is_all_in_army_advantage = False
    #
    #     if freshCityCount > 0 and (earlyCycleSlightlyWinning or heavilyWinning) and not self._map.remainingPlayers > 2:
    #         self.flanking = False
    #         winningEcon = self.opponent_tracker.winning_on_economy(byRatio=1.2)
    #         # todo need same for 2v2
    #         d25 = self._map.players[self.targetPlayer].delta25tiles - self._map.players[self.general.player].delta25tiles
    #         if d25 < 5 and self.opponent_tracker.up_on_cities() and self.opponent_tracker.winning_on_tiles():
    #             offset += 10
    #         elif d25 < 7 and self.opponent_tracker.up_on_cities():
    #             offset += 5
    #         if winningEcon and self._map.remainingPlayers == 2:
    #             offset += 5
    #         if heavilyWinning and self.opponent_tracker.winning_on_army():
    #             offset += 7
    #
    #         if offset < 15:
    #             return
    #
    #         self.locked_launch_point = sketchiestCity
    #         if contestCity is not None:
    #             self.locked_launch_point = contestCity
    #         self.recalculate_player_paths(force=True)
    #         curTurn = self.timings.get_turn_in_cycle(self._map.turn)
    #         self.timings.splitTurns = min(self.timings.cycleTurns - 14, max(curTurn + offset, self.timings.splitTurns + offset))
    #         self.viewInfo.add_info_line(f'CCAP GATH, d25 {d25}, offset {offset} winningEcon 1.2 {str(winningEcon)[0]} heavilyWinning {str(heavilyWinning)[0]}')
    #         self.timings.launchTiming = max(self.timings.splitTurns, self.timings.launchTiming)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_scrim_cached. Tiny cache accessor for previously computed scrim results.
    def get_scrim_cached(self, friendlyArmies: typing.List[Army], enemyArmies: typing.List[Army]) -> ArmySimResult | None:
        return BotCombatOps.get_scrim_cached(self, friendlyArmies, enemyArmies)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_scrim_cache_key. Small stable cache-key builder for scrim army sets.
    def get_scrim_cache_key(self, friendlyArmies: typing.List[Army], enemyArmies: typing.List[Army]) -> str:
        return BotCombatOps.get_scrim_cache_key(self, friendlyArmies, enemyArmies)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.find_sketchy_fog_flank_from_enemy_in_play_area. Defensive flank-risk probe constrained to the in-play area.
    def find_sketchy_fog_flank_from_enemy_in_play_area(self) -> Path | None:
        return BotDefense.find_sketchy_fog_flank_from_enemy_in_play_area(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.find_sketchiest_fog_flank_from_enemy. Main sketchy flank discovery routine over fog launch points and flankable territory.
    def find_sketchiest_fog_flank_from_enemy(self) -> Path | None:
        return BotDefense.find_sketchiest_fog_flank_from_enemy(self)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.check_for_attack_launch_move. Attack-launch decision gate that turns gather path value into an actual launch move.
    def check_for_attack_launch_move(self, outLaunchPlanNegatives: typing.Set[Tile]) -> Move | None:
        return BotCombatOps.check_for_attack_launch_move(self, outLaunchPlanNegatives)

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings.set_all_in_cycle_to_hit_with_current_timings. Small timing helper for extending all-in through a chosen cycle.
    def set_all_in_cycle_to_hit_with_current_timings(self, cycle: int, bufferTurnsEndOfCycle: int = 5):
        return BotTimings.set_all_in_cycle_to_hit_with_current_timings(self, cycle, bufferTurnsEndOfCycle)

    # DONE STEP2: Move to BotModules/BotCombatOps.py or BotExpansionOps late. Currently a stub for flank all-in launch behavior; keep grouped with all-in combat logic.
    def try_find_flank_all_in(self, hitGeneralAtTurn: int) -> Move | None:
        return BotCombatOps.try_find_flank_all_in(self, hitGeneralAtTurn)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.find_flank_opportunity. Generic flank-opportunity search used by defensive flank risk analysis.
    def find_flank_opportunity(
            self,
            targetPlayer: int,
            flankingPlayer: int,
            flankPlayerLaunchPoints: typing.List[Tile],
            depth: int,
            targetDistMap: MapMatrixInterface[int],
            validEmergencePointMatrix: MapMatrixSet | None,
            maxFogRange: int = -1
    ) -> Path | None:
        return BotDefense.find_flank_opportunity(self, targetPlayer, flankingPlayer, flankPlayerLaunchPoints, depth, targetDistMap, validEmergencePointMatrix, maxFogRange)

    # DONE STEP2: Move to BotModules/BotTimings.py or BotTargeting late. Small hook that drops/rebuilds timings when the current target team gains a city.
    def check_target_player_just_took_city(self):
        return BotTargeting.check_target_player_just_took_city(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_2v2_launch_point. Chooses the 2v2 launch/rally point between self, ally, and contested tiles.
    def get_2v2_launch_point(self) -> Tile:
        return BotTargeting.get_2v2_launch_point(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py or BotCityOps late. Small contested-target bookkeeping helper that increments per-tile attack counts.
    def increment_attack_counts(self, tile: Tile):
        return BotTargeting.increment_attack_counts(self, tile)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_contested_targets. Returns recently contested tiles for target selection and launch heuristics.
    def get_contested_targets(
            self,
            shortTermContestCutoff: int = 25,
            longTermContestCutoff: int = 60,
            numToInclude=3,
            excludeGeneral: bool = False
    ) -> typing.List[ContestData]:
        return BotTargeting.get_contested_targets(self, shortTermContestCutoff, longTermContestCutoff, numToInclude, excludeGeneral)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.send_teammate_communication. Main team-chat send helper with cooldown and optional tile ping support.
    def send_teammate_communication(self, message: str, pingTile: Tile | None = None, cooldown: int = 10, detectOnMessageAlone: bool = False, detectionKey: str | None = None):
        return BotComms.send_teammate_communication(self, message, pingTile, cooldown, detectOnMessageAlone, detectionKey)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.send_all_chat_communication. Thin global-chat send helper.
    def send_all_chat_communication(self, message: str):
        return BotComms.send_all_chat_communication(self, message)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.send_teammate_path_ping. Thin helper that pings every tile in a path for teammate coordination.
    def send_teammate_path_ping(self, path: Path, cooldown: int = 0, cooldownKey: str | None = None):
        return BotComms.send_teammate_path_ping(self, path, cooldown, cooldownKey)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.send_teammate_tile_ping. Core teammate tile-ping sender with cooldown handling and render side effects.
    def send_teammate_tile_ping(self, pingTile: Tile, cooldown: int = 0, cooldownKey: str | None = None):
        return BotComms.send_teammate_tile_ping(self, pingTile, cooldown, cooldownKey)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.get_queued_tile_pings. Queue-drain helper for outbound teammate tile pings.
    def get_queued_tile_pings(self) -> typing.List[Tile]:
        return BotComms.get_queued_tile_pings(self)

    # STEP2: Stay in EklipZBotV2.py only as an inert/debug backdoor. Non-domain randomizer/debug stub; do not migrate with normal gameplay logic.
    def do_thing(self):
        time.sleep(8)
        lastSwapped = []
        for tile in self._map.get_all_tiles():
            if random.randint(1, 300) > 250:
                h = tile.movable
                tile.movable = lastSwapped
                lastSwapped = h
            if random.randint(1, 300) > 298:
                tile.isMountain = True
                tile.army = 0
            if random.randint(1, 300) > 275 and not tile.visible:
                tile.player = -1
                tile.army = 0

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.get_queued_teammate_messages. Queue-drain helper for outbound team chat messages.
    def get_queued_teammate_messages(self) -> typing.List[str]:
        return BotComms.get_queued_teammate_messages(self)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.get_queued_all_chat_messages. Queue-drain helper for outbound all-chat messages.
    def get_queued_all_chat_messages(self) -> typing.List[str]:
        return BotComms.get_queued_all_chat_messages(self)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.notify_chat_message. Inbound chat queue hook plus legacy easter-egg/debug trigger handling.
    def notify_chat_message(self, chatUpdate: ChatUpdate):
        return BotComms.notify_chat_message(self, chatUpdate)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.notify_tile_ping. Inbound teammate tile-ping queue hook.
    def notify_tile_ping(self, pingedTile: Tile):
        return BotComms.notify_tile_ping(self, pingedTile)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.determine_should_defend_ally. 2v2 ally-defense decision helper coordinating comms and self-save estimation.
    def determine_should_defend_ally(self) -> bool:
        return BotDefense.determine_should_defend_ally(self)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.find_end_of_turn_sim_result. End-of-turn scrim setup/orchestration across largest armies and engine parameters.
    def find_end_of_turn_sim_result(self, threat: ThreatObj | None, kingKillPath: Path | None, time_limit: float | None = None) -> ArmySimResult | None:
        return BotCombatOps.find_end_of_turn_sim_result(self, threat, kingKillPath, time_limit)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.find_end_of_turn_scrim_move. Thin wrapper converting the end-of-turn scrim result into an actual move.
    def find_end_of_turn_scrim_move(self, threat: ThreatObj | None, kingKillPath: Path | None, time_limit: float | None = None) -> Move | None:
        return BotCombatOps.find_end_of_turn_scrim_move(self, threat, kingKillPath, time_limit)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_largest_tiles_as_armies. Helper that materializes the top army tiles for scrim simulation.
    def get_largest_tiles_as_armies(self, player: int, limit: int) -> typing.List[Army]:
        return BotCombatOps.get_largest_tiles_as_armies(self, player, limit)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_defense_tree_move_prio_func_old. Legacy defense tree move-priority heuristic kept for comparison/debugging.
    def get_defense_tree_move_prio_func_old(
            self,
            threat: ThreatObj,
            anyLeafIsSameDistAsThreat: bool = False,
            printDebug: bool = False
    ) -> typing.Callable[[Tile, typing.Any], typing.Any]:
        return BotDefense.get_defense_tree_move_prio_func_old(self, threat, anyLeafIsSameDistAsThreat, printDebug)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_defense_tree_move_prio_func. Active defense tree move-priority heuristic for selecting gather moves under threat.
    def get_defense_tree_move_prio_func(
            self,
            threat: ThreatObj,
            anyLeafIsSameDistAsThreat: bool = False,
            printDebug: bool = False
    ) -> typing.Callable[[Tile, typing.Any], typing.Any]:
        return BotDefense.get_defense_tree_move_prio_func(self, threat, anyLeafIsSameDistAsThreat, printDebug)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_capture_first_tree_move_prio_func. Capture-first gather tree tie-break heuristic used by defense/vision planners.
    def get_capture_first_tree_move_prio_func(
        self
    ) -> typing.Callable[[Tile, typing.Any], typing.Any]:
        return BotGatherOps.get_capture_first_tree_move_prio_func(self)

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
            move, valueGathered, turnsUsed, gatherNodes = self.get_gather_to_target_tiles(keyAreas, 0.1, self._map.turn % 5 + 1, negativeTiles, targetArmy=1, useTrueValueGathered=True, maximizeArmyGatheredPerTurn=True)

        if move is not None:
            self.gatherNodes = gatherNodes
            self.info(f'Hunting for fog neutral cities: {move}')
            return None, move

        return None, None

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.try_find_exploration_move. High-level exploration/hunt move selector for unfinished enemy discovery.
    def try_find_exploration_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotExpansionOps.try_find_exploration_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.handle_chat_message. Chat-routing entrypoint delegating to teammate bot/human handlers.
    def handle_chat_message(self, chatUpdate: ChatUpdate):
        return BotComms.handle_chat_message(self, chatUpdate)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.is_2v2_teammate_still_alive. Small shell/team-mode helper.
    def is_2v2_teammate_still_alive(self) -> bool:
        return BotComms.is_2v2_teammate_still_alive(self)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.handle_bot_chat. Thin teammate-bot coordination message handler.
    def handle_bot_chat(self, chatUpdate: ChatUpdate):
        return BotComms.handle_bot_chat(self, chatUpdate)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.handle_human_chat. Placeholder human teammate chat handler.
    def handle_human_chat(self, chatUpdate: ChatUpdate):
        return BotComms.handle_human_chat(self, chatUpdate)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.communicate_threat_to_ally. Ally-defense communication helper for threat/gather-plan coordination.
    def communicate_threat_to_ally(self, threat: ThreatObj, valueGathered: int, defensePlan: typing.List[GatherTreeNode]):
        return BotComms.communicate_threat_to_ally(self, threat, valueGathered, defensePlan)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.try_find_main_timing_expansion_move_if_applicable. Main expansion-or-launch chooser during the timing window.
    def try_find_main_timing_expansion_move_if_applicable(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotExpansionOps.try_find_main_timing_expansion_move_if_applicable(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.try_find_expansion_move. Primary expansion move planner with launch gating, first-25 reuse, and safety checks.
    def try_find_expansion_move(self, defenseCriticalTileSet: typing.Set[Tile], timeLimit: float, forceBypassLaunch: bool = False, overrideTurns: int = -1) -> Move | None:
        return BotExpansionOps.try_find_expansion_move(self, defenseCriticalTileSet, timeLimit, forceBypassLaunch, overrideTurns)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps._add_expansion_threat_negs. Helper that augments expansion negatives using the current threat path.
    def _add_expansion_threat_negs(self, negs: typing.Set[Tile]):
        return BotExpansionOps._add_expansion_threat_negs(self, negs)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.try_find_army_out_of_position_move. Scrim-based correction for large armies stranded out of position.
    def try_find_army_out_of_position_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotCombatOps.try_find_army_out_of_position_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.are_more_teams_alive_than. Small game-mode/team-count helper used by FFA/targeting logic.
    def are_more_teams_alive_than(self, numTeams: int) -> bool:
        return BotTargeting.are_more_teams_alive_than(self, numTeams)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_potential_threat_movement_negatives. Computes tiles that should be treated as negative due to a potential threat path.
    def get_potential_threat_movement_negatives(self, targetTile: Tile | None = None) -> typing.Set[Tile]:
        return BotDefense.get_potential_threat_movement_negatives(self, targetTile)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.get_target_player_possible_general_location_tiles_sorted. Core ranked candidate-generator for possible enemy general locations.
    def get_target_player_possible_general_location_tiles_sorted(
            self,
            elimNearbyRange: int = 2,
            player: int = -2,
            cutoffEmergenceRatio: float = 0.333,
            includeCities: bool = False,
            limitNearbyTileRange: int = -1
    ) -> typing.List[Tile]:
        return BotTargeting.get_target_player_possible_general_location_tiles_sorted(self, elimNearbyRange, player, cutoffEmergenceRatio, includeCities, limitNearbyTileRange)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.get_first_25_expansion_distance_priority_map. Early-game expansion priority matrix and teammate skip-tile builder.
    def get_first_25_expansion_distance_priority_map(self) -> typing.Tuple[MapMatrixInterface[int], typing.Set[Tile]]:
        return BotExpansionOps.get_first_25_expansion_distance_priority_map(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.is_still_ffa_and_non_dominant. Small strategic classification helper for non-dominant FFA posture.
    def is_still_ffa_and_non_dominant(self) -> bool:
        return BotTargeting.is_still_ffa_and_non_dominant(self)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.get_expansion_weight_matrix. Cached expansion-value matrix entrypoint switching between standard and FFA-safe variants.
    def get_expansion_weight_matrix(self, copy: bool = False, mult: int = 1) -> MapMatrixInterface[float]:
        return BotExpansionOps.get_expansion_weight_matrix(self, copy, mult)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps._get_avoid_other_players_expansion_matrix. FFA-oriented expansion weighting matrix that avoids overcommitting into other players.
    def _get_avoid_other_players_expansion_matrix(self) -> MapMatrixInterface[float]:
        return BotExpansionOps._get_avoid_other_players_expansion_matrix(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting._get_furthest_apart_3_enemy_general_locations. Helper for selecting spaced enemy-general candidates and their combined distance map.
    def _get_furthest_apart_3_enemy_general_locations(self, player) -> typing.Tuple[typing.List[Tile], MapMatrixInterface[int]]:
        return BotTargeting._get_furthest_apart_3_enemy_general_locations(self, player)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps._get_standard_expansion_capture_weight_matrix. Main expansion scoring heuristic matrix for standard games.
    def _get_standard_expansion_capture_weight_matrix(self) -> MapMatrixInterface[float]:
        return BotExpansionOps._get_standard_expansion_capture_weight_matrix(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.is_ffa_situation. Small cached game-mode classifier used by many policy branches.
    def is_ffa_situation(self) -> bool:
        return BotTargeting.is_ffa_situation(self)

    # DONE STEP2: Stay in EklipZBotV2.py or move late to BotEventHandlers/BotTimings. Small post-capture reevaluation hook that can flip all-in posture.
    def reevaluate_after_player_capture(self):
        return BotEventHandlers.reevaluate_after_player_capture(self)

    # DONE STEP2: Move to BotModules/BotTargeting.py as BotTargeting.find_fog_bisection_targets. Finds fog bisection targets that cut through enemy territory growth.
    def find_fog_bisection_targets(self) -> typing.Set[Tile]:
        return BotTargeting.find_fog_bisection_targets(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_enemy_probable_attack_path. Predictive fog-path reconstruction for likely enemy attack lanes.
    def get_enemy_probable_attack_path(self, enemyPlayer: int) -> Path | None:
        return BotDefense.get_enemy_probable_attack_path(self, enemyPlayer)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.build_expansion_plan. Main expansion-plan builder integrating intercept options, flow expansion, and launch competition.
    def build_expansion_plan(
            self,
            timeLimit: float,
            expansionNegatives: typing.Set[Tile],
            pathColor: typing.Tuple[int, int, int],
            overrideTurns: int = -1,
            includeExtraGenAndCityArmy: bool = False
    ) -> ExpansionPotential:
        return BotExpansionOps.build_expansion_plan(self, timeLimit, expansionNegatives, pathColor, overrideTurns, includeExtraGenAndCityArmy)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.build_enemy_expansion_plan. Mirrors expansion planning from the opponent perspective for heuristics/rendering.
    def build_enemy_expansion_plan(
            self,
            timeLimit: float,
            pathColor: typing.Tuple[int, int, int]
    ) -> ExpansionPotential:
        return BotExpansionOps.build_enemy_expansion_plan(self, timeLimit, pathColor)

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings.get_opponent_cycle_stats. Thin accessor for cached opponent cycle statistics.
    def get_opponent_cycle_stats(self) -> CycleStatsData | None:
        return BotTimings.get_opponent_cycle_stats(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.check_should_defend_economy_based_on_cycle_behavior. Main defend-economy trigger based on cycle behavior, threat paths, and fog risk.
    def check_should_defend_economy_based_on_cycle_behavior(self, defenseCriticalTileSet: typing.Set[Tile]) -> bool:
        return BotDefense.check_should_defend_economy_based_on_cycle_behavior(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.is_move_towards_enemy. Tiny directional helper comparing move progress toward enemy territory.
    def is_move_towards_enemy(self, move: Move | None) -> bool:
        return BotPathingUtils.is_move_towards_enemy(self, move)

    # DONE STEP2: Move to BotModules/BotStateQueries.py late or keep as a tiny utility. Small tile-list string formatter used for logs/debugging.
    def str_tiles(self, tiles) -> str:
        return BotStateQueries.str_tiles(self, tiles)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_path_subsegment_to_closest_enemy_team_territory. Utility for trimming a path to its closest point to enemy team territory.
    def get_path_subsegment_to_closest_enemy_team_territory(self, path: Path) -> Path | None:
        return BotPathingUtils.get_path_subsegment_to_closest_enemy_team_territory(self, path)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.check_launch_against_expansion_plan. Compares direct launch value against the current expansion plan and may replace it.
    def check_launch_against_expansion_plan(self, existingPlan: ExpansionPotential, expansionNegatives: typing.Set[Tile]) -> ExpansionPotential:
        return BotExpansionOps.check_launch_against_expansion_plan(self, existingPlan, expansionNegatives)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.calculate_path_capture_econ_values. Shared path-evaluation helper for launch/expansion econ and capture counts.
    def calculate_path_capture_econ_values(self, launchPath, turnsLeftInCycle, negativeTiles: typing.Set[Tile] | None = None) -> typing.Tuple[int, int, int, int, int, int, int]:
        return BotExpansionOps.calculate_path_capture_econ_values(self, launchPath, turnsLeftInCycle, negativeTiles)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.make_second_25_move. Specialized second-25-turn expansion/gather transition logic for early 1v1 openings.
    def make_second_25_move(self) -> Move | None:
        return BotExpansionOps.make_second_25_move(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.get_enemy_cities_by_priority. Priority ordering helper for enemy-city targets based on active threat context and city scores.
    def get_enemy_cities_by_priority(self, cutoffDistanceRatio=100.0) -> typing.List[Tile]:
        return BotCityOps.get_enemy_cities_by_priority(self, cutoffDistanceRatio)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.did_player_just_take_fog_city. Small fog-city inference helper using unexplained score deltas.
    def did_player_just_take_fog_city(self, player: int) -> bool:
        return BotCityOps.did_player_just_take_fog_city(self, player)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.get_city_contestation_all_in_move. Offensive city-contestation gather planner for all-in style pressure.
    def get_city_contestation_all_in_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> typing.Tuple[Move | None, int, int, typing.List[GatherTreeNode]]:
        return BotCityOps.get_city_contestation_all_in_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.get_number_of_captures_in_gather_tree. Small gather-tree statistic helper counting capture nodes.
    def get_number_of_captures_in_gather_tree(self, gatherNodes: typing.List[GatherTreeNode], asPlayer: int = -2) -> int:
        return BotGatherOps.get_number_of_captures_in_gather_tree(self, gatherNodes, asPlayer)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps.get_city_preemptive_defense_move. Preemptive city-defense gather/flank-vision logic for protecting vulnerable cities.
    def get_city_preemptive_defense_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotCityOps.get_city_preemptive_defense_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.find_flank_defense_move. Main proactive flank-defense selector combining leaf vision and gather-based responses.
    def find_flank_defense_move(self, defenseCriticalTileSet: typing.Set[Tile], highPriority: bool = False) -> Move | None:
        return BotDefense.find_flank_defense_move(self, defenseCriticalTileSet, highPriority)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense._get_flank_defense_leafmove. Leaf-move heuristic for cheaply expanding vision along a risky flank.
    def _get_flank_defense_leafmove(self, flankPath: Path, coreNegs: typing.Set[Tile]) -> Move | None:
        return BotDefense._get_flank_defense_leafmove(self, flankPath, coreNegs)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense._get_vision_expanding_available_move. Searches for low-cost vision-expanding moves along risky hidden paths.
    def _get_vision_expanding_available_move(self, coreNegs: typing.Set[Tile], pathToCheckForVisionOf: Path | None = None) -> Move | None:
        return BotDefense._get_vision_expanding_available_move(self, coreNegs, pathToCheckForVisionOf)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense._get_flank_vision_defense_move_internal. Gather-based internal helper for revealing risky flank paths.
    def _get_flank_vision_defense_move_internal(self, flankThreatPath: Path, negativeTiles: typing.Set[Tile], atDist: int) -> Move | None:
        return BotDefense._get_flank_vision_defense_move_internal(self, flankThreatPath, negativeTiles, atDist)

    # DONE STEP2: Move to BotModules/BotStateQueries.py as BotStateQueries.get_n_closest_team_tiles_near. Small BFS helper for nearby team/neutral tile collection.
    def get_n_closest_team_tiles_near(self, nearTiles: typing.List[Tile], player: int, distance: int, limit: int, includeNeutral: bool = False) -> typing.List[Tile]:
        return BotStateQueries.get_n_closest_team_tiles_near(self, nearTiles, player, distance, limit, includeNeutral)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_int_tile_2d_array_to_string. Tiny matrix/string serialization helper for int grids.
    def convert_int_tile_2d_array_to_string(self, rows: typing.List[typing.List[int]]) -> str:
        return BotSerialization.convert_int_tile_2d_array_to_string(self, rows)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_float_tile_2d_array_to_string. Tiny matrix/string serialization helper for float grids.
    def convert_float_tile_2d_array_to_string(self, rows: typing.List[typing.List[float]]) -> str:
        return BotSerialization.convert_float_tile_2d_array_to_string(self, rows)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_int_map_matrix_to_string. Tiny matrix/string serialization helper for int map matrices.
    def convert_int_map_matrix_to_string(self, mapMatrix: MapMatrixInterface[int]) -> str:
        return BotSerialization.convert_int_map_matrix_to_string(self, mapMatrix)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_float_map_matrix_to_string. Tiny matrix/string serialization helper for float map matrices.
    def convert_float_map_matrix_to_string(self, mapMatrix: MapMatrixInterface[float]) -> str:
        return BotSerialization.convert_float_map_matrix_to_string(self, mapMatrix)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_bool_map_matrix_to_string. Tiny matrix/string serialization helper for boolean map matrices/sets.
    def convert_bool_map_matrix_to_string(self, mapMatrix: MapMatrixInterface[bool] | MapMatrixSet) -> str:
        return BotSerialization.convert_bool_map_matrix_to_string(self, mapMatrix)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_tile_set_to_string. Tiny tile-set serializer.
    def convert_tile_set_to_string(self, tiles: typing.Set[Tile]) -> str:
        return BotSerialization.convert_tile_set_to_string(self, tiles)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_tile_int_dict_to_string. Tiny tile->int dict serializer.
    def convert_tile_int_dict_to_string(self, tiles: typing.Dict[Tile, int]) -> str:
        return BotSerialization.convert_tile_int_dict_to_string(self, tiles)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_int_tile_2d_array. Tiny int-grid deserializer.
    def convert_string_to_int_tile_2d_array(self, data: str) -> typing.List[typing.List[int]]:
        return BotSerialization.convert_string_to_int_tile_2d_array(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_float_tile_2d_array. Tiny float-grid deserializer.
    def convert_string_to_float_tile_2d_array(self, data: str) -> typing.List[typing.List[float]]:
        return BotSerialization.convert_string_to_float_tile_2d_array(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_bool_map_matrix. Tiny boolean-map deserializer.
    def convert_string_to_bool_map_matrix(self, data: str) -> MapMatrixInterface[bool]:
        return BotSerialization.convert_string_to_bool_map_matrix(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_bool_map_matrix_set. Tiny boolean-map-set deserializer.
    def convert_string_to_bool_map_matrix_set(self, data: str) -> MapMatrixSet:
        return BotSerialization.convert_string_to_bool_map_matrix_set(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_int_map_matrix. Tiny int-map deserializer.
    def convert_string_to_int_map_matrix(self, data: str) -> MapMatrixInterface[int]:
        return BotSerialization.convert_string_to_int_map_matrix(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_float_map_matrix. Tiny float-map deserializer.
    def convert_string_to_float_map_matrix(self, data: str) -> MapMatrixInterface[float]:
        return BotSerialization.convert_string_to_float_map_matrix(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_tile_set. Tiny tile-set deserializer.
    def convert_string_to_tile_set(self, data: str) -> typing.Set[Tile]:
        return BotSerialization.convert_string_to_tile_set(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_string_to_tile_int_dict. Tiny tile->int dict deserializer.
    def convert_string_to_tile_int_dict(self, data: str) -> typing.Dict[Tile, int]:
        return BotSerialization.convert_string_to_tile_int_dict(self, data)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.get_tile_by_tile_index. Fundamental tile-index lookup helper used across the shell and many helper modules.
    def get_tile_by_tile_index(self, tileIndex: int) -> Tile:
        return BotSerialization.get_tile_by_tile_index(self, tileIndex)

    # DONE STEP2: Move to BotModules/BotSerialization.py as BotSerialization.convert_tile_server_index_to_friendly_x_y. Fundamental server-index conversion helper used broadly by serialization/debug utilities.
    def convert_tile_server_index_to_friendly_x_y(self, tileIndex: int) -> typing.Tuple[int, int]:
        return BotSerialization.convert_tile_server_index_to_friendly_x_y(self, tileIndex)

    # DONE STEP2: Move to BotModules/BotTimings.py as BotTimings._get_approximate_greedy_turns_available. Main heuristic for how many greedy expansion turns remain before pressure arrives.
    def _get_approximate_greedy_turns_available(self) -> int:
        return BotTimings._get_approximate_greedy_turns_available(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.get_approximate_fog_risk_deficit. Small fog-risk minus path-worth heuristic used by defensive decisions.
    def get_approximate_fog_risk_deficit(self) -> int:
        return BotDefense.get_approximate_fog_risk_deficit(self)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.try_get_cyclic_all_in_move. Cyclic all-in gather planner for winning or desperation attack cycles.
    def try_get_cyclic_all_in_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotCombatOps.try_get_cyclic_all_in_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.try_get_enemy_territory_exploration_continuation_move. Continues expansion paths that also reveal enemy territory/city/general information.
    def try_get_enemy_territory_exploration_continuation_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotExpansionOps.try_get_enemy_territory_exploration_continuation_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps._get_expansion_plan_exploration_move. Filters expansion-plan paths for exploration-worthy fog-revealing continuations.
    def _get_expansion_plan_exploration_move(self, armyCutoff: int, negativeTiles: typing.Set[Tile]) -> Move | None:
        return BotExpansionOps._get_expansion_plan_exploration_move(self, armyCutoff, negativeTiles)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps._get_expansion_plan_quick_capture_move. Opportunistic greedy pre-gather capture selection from the expansion plan.
    def _get_expansion_plan_quick_capture_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotExpansionOps._get_expansion_plan_quick_capture_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_euclid_shortest_from_tile_towards_target. Tiny geometric fallback helper for stepping toward a target.
    def get_euclid_shortest_from_tile_towards_target(self, sourceTile: Tile, towardsTile: Tile) -> Move:
        return BotPathingUtils.get_euclid_shortest_from_tile_towards_target(self, sourceTile, towardsTile)

    # DONE STEP2: Move to BotModules/BotRendering.py as BotRendering.render_intercept_plan. Debug/render helper for displaying intercept-plan choke data and options.
    def render_intercept_plan(self, plan: ArmyInterception, colorIndex: int = 0):
        return BotRendering.render_intercept_plan(self, plan, colorIndex)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.check_fog_risk. Main fog-risk evaluator over target gather path and opponent cycle stats.
    def check_fog_risk(self):
        return BotDefense.check_fog_risk(self)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.get_path_subsegment_starting_from_last_move. CurPath/launch helper trimming a path to continue after the last observed move.
    def get_path_subsegment_starting_from_last_move(self, launchPath: Path) -> Path:
        return BotPathingUtils.get_path_subsegment_starting_from_last_move(self, launchPath)

    # DONE STEP2: Move to BotModules/BotPathingUtils.py as BotPathingUtils.check_cur_path or keep late on shell. Defensive validation/scrubbing of stateful curPath objects.
    def check_cur_path(self):
        return BotPathingUtils.check_cur_path(self)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.send_2v2_tip_to_ally. Small teammate-tip broadcaster for 2v2 openings.
    def send_2v2_tip_to_ally(self):
        return BotComms.send_2v2_tip_to_ally(self)

    # DONE STEP2: Move to BotModules/BotComms.py as BotComms.cooldown_allows. Generic communication cooldown gate for chat and pings.
    def cooldown_allows(self, detectionKey: str, cooldown: int, doNotUpdate: bool = False) -> bool:
        return BotComms.cooldown_allows(self, detectionKey, cooldown, doNotUpdate)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_all_in_move. Primary all-in gather/launch planner against enemy general and city targets.
    def get_all_in_move(self, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        return BotCombatOps.get_all_in_move(self, defenseCriticalTileSet)

    # DONE STEP2: Move to BotModules/BotGatherOps.py as BotGatherOps.convert_gather_to_move_list_path. Converts gather root nodes into a replayable MoveListPath.
    def convert_gather_to_move_list_path(self, gatherNodes, turnsUsed, value, moveOrderPriorityMinFunc) -> MoveListPath:
        return BotGatherOps.convert_gather_to_move_list_path(self, gatherNodes, turnsUsed, value, moveOrderPriorityMinFunc)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense._get_defensive_spanning_tree. Core defensive spanning-tree builder around general, teammate, and city anchors.
    def _get_defensive_spanning_tree(self, negativeTiles: TileSet, gatherPrioMatrix: MapMatrixInterface[float] | None = None) -> typing.Set[Tile]:
        return BotDefense._get_defensive_spanning_tree(self, negativeTiles, gatherPrioMatrix)

    # DONE STEP2: Move to BotModules/BotCombatOps.py as BotCombatOps.get_kill_race_chance. Computes probability of winning a general hunt race across candidate enemy spawn locations.
    def get_kill_race_chance(self, generalHuntPath: Path, enGenProbabilityCutoff: float = 0.4, turnsToDeath: int | None = None, cutoffKillArmy: int = 0, againstPlayer: int = None) -> float:
        return BotCombatOps.get_kill_race_chance(self, generalHuntPath, enGenProbabilityCutoff, turnsToDeath, cutoffKillArmy, againstPlayer)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps.get_unexpandable_ratio. Heuristic for how boxed-in the current army is by bad expansion terrain.
    def get_unexpandable_ratio(self) -> float:
        return BotExpansionOps.get_unexpandable_ratio(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py or BotExpansionOps late. Thin wrapper ensuring city reachability matrices are built before downstream planning.
    def ensure_reachability_matrix_built(self):
        return BotCityOps.ensure_reachability_matrix_built(self)

    # DONE STEP2: Move to BotModules/BotCityOps.py as BotCityOps._check_should_wait_city_capture. Small early city-wait heuristic returning either a quick path or defer signal.
    def _check_should_wait_city_capture(self) -> typing.Tuple[Path | None, bool]:
        return BotCityOps._check_should_wait_city_capture(self)

    # DONE STEP2: Move to BotModules/BotDefense.py as BotDefense.set_defensive_blocks_against. Marks tiles and destinations that must stay reserved to block a threat path.
    def set_defensive_blocks_against(self, threat: ThreatObj):
        return BotDefense.set_defensive_blocks_against(self, threat)

    # DONE STEP2: Move to BotModules/BotExpansionOps.py as BotExpansionOps._should_use_iterative_negative_expand. Tiny expansion-policy toggle for iterative negative-tile usage.
    def _should_use_iterative_negative_expand(self) -> bool:
        return BotExpansionOps._should_use_iterative_negative_expand(self)

