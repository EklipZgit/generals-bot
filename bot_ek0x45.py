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
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
# from ArmyEngine import ArmyEngine, ArmySimResult
from Behavior.ArmyInterceptor import ArmyInterceptor, ArmyInterception, ThreatBlockInfo, InterceptionOptionInfo
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander, FlowExpansionPlanOptionCollection
from CityAnalyzer import CityAnalyzer, CityScoreData
from Communication import TeammateCommunicator, TileCompressor
from DistanceMapperImpl import DistanceMapperImpl
from FfaGeneralPlacement import FfaGeneralPlacement
from Gather import GatherCapturePlan
from GatherAnalyzer import GatherAnalyzer
from Interfaces import TilePlanInterface, MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet, TileSet
# from MctsLudii import MctsDUCT
from Path import Path, MoveListPath
from PerformanceTimer import PerformanceTimer
from BoardAnalyzer import BoardAnalyzer
from BotModules.BotCityCaptureControl import BotCityCaptureControl
from BotModules.BotCentralDefense import BotCentralDefense
from BotModules.BotCityOps import BotCityOps
from BotModules.BotCombatOps import BotCombatOps
from BotModules.BotComms import BotComms
from BotModules.BotDefense import BotDefense
from BotModules.BotEventHandlers import BotEventHandlers
from BotModules.BotExplorationOps import BotExplorationOps
from BotModules import BotFfaKillGather
from BotModules import BotFfaEndgame
from BotModules import BotGeneralSafety
from BotModules.BotExpansionOps import BotExpansionOps
from BotModules.BotGatherOps import BotGatherOps
from BotModules.BotKillTiming import BotKillTiming
from BotModules.BotLifecycle import BotLifecycle
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotRendering import BotRendering
from BotModules.BotRepetition import BotRepetition
from BotModules.BotSerialization import BotSerialization
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotStealthAllIn import (
    BotStealthAllIn,
    StealthRouteDefenseInterrupt,
    StealthAllInState,
    StealthWrpJob,
    WrpWorkerProcess,
)
from BotModules.BotTimings import BotTimings
from BotModules.BotTargeting import BotTargeting
from Sim.TextMapLoader import TextMapLoader
from Strategy import OpponentTracker, WinConditionAnalyzer, CaptureLineTracker
from Strategy.GeneralTradeEvaluator import GeneralTradeEvaluation
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


class EklipZBot(object):
    def __init__(self):
        self.blocking_tile_info: typing.Dict[Tile, ThreatBlockInfo] = {}
        # Tiles that already donated a half-split to hold a threat block (see
        # BotDefense.apply_threat_blocking_split_hint_to_move). Their remainder is the
        # committed garrison - forward planning may not drain it again while the tile is
        # still a threat-blocking tile.
        self.block_split_garrison_sources: typing.Set[Tile] = set()
        # Last turn each committed garrison appeared in blocking_tile_info - the checker
        # flickers (a tile can drop out for a single turn while threats reroute), so a
        # garrison stays pinned for a couple turns past its last sighting instead of
        # being freed the first turn the checker misses it.
        self.block_split_garrison_last_turn: typing.Dict[Tile, int] = {}
        # Tiles currently holding the army that split OFF a committed garrison. Tracked
        # turn-to-turn as it marches so a pending city/contest option continuing it gets
        # beeline priority over unrelated picks (the recapture must not stall out).
        self.block_split_outbound_tiles: typing.Set[Tile] = set()
        # Every tile a committed outbound army has occupied - the directions a committed
        # garrison must never take (moving into the trail IS abandoning the block, even
        # on turns when the checker doesn't currently flag that destination).
        self.block_split_outbound_trail: typing.Set[Tile] = set()
        # The mission target the committed outbound is marching on (the threatened city
        # the split was defending/recapturing) - lets the beeline compute the next hop
        # even on turns when no pending plan option wants to continue the army.
        self.block_split_outbound_target: Tile | None = None
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
        self.was_defending_economy = False
        self._spawn_cramped: bool = False
        self.general_safe_func_set = {}
        self.clear_moves_func: typing.Union[None, typing.Callable] = None
        self.stop_holding_clear_moves_func: typing.Union[None, typing.Callable] = None
        self.surrender_func: typing.Union[None, typing.Callable] = None
        self.holding_clear_moves: bool = False
        self._map: MapBase = None
        self.curPath: Path | None = None
        self.last_move: Move | None = None
        self.curPathPrio = -1
        self.gathers = 0
        self.attacks = 0

        self.leafMoves: typing.List[Move] = []
        """All leaves that border an enemy or neutral tile, regardless of whether the tile has enough army to capture the adjacent."""
        self.captureLeafMoves: typing.List[Move] = []
        """All leaf moves that can capture the adjacent."""

        self.targetPlayerLeafMoves: typing.List[Move] = []
        """All moves by the target player that could capture adjacent."""

        self.ffa_exclusive_target_lock: int = -1
        """While BotStateQueries.is_ffa_exclusive_targeting_active holds, the one enemy player we are
        committed to attacking exclusively (Tests/test_FFA.py FFA pacifism tests). -1 = nobody."""

        # FFA (>2 living teams) certified kill-gather feature (BotModules/BotFfaKillGather.py).
        # ffa_kill_gather_state holds the committed literal schedule once a certified option is
        # selected by flow expansion; _ffa_kill_gather_cache holds per-game search/WRP artifacts.
        self.ffa_kill_gather_state: BotFfaKillGather.FfaKillGatherState | None = None
        self._ffa_kill_gather_cache: BotFfaKillGather.FfaKillGatherCache = BotFfaKillGather.FfaKillGatherCache()

        # 3-player FFA endgame policy state (BotModules/BotFfaEndgame.py); the decision is
        # recomputed each turn and only retaliation_target is serialized into txtmaps.
        self.ffa_endgame: BotFfaEndgame.FfaEndgameState | None = None

        # General-reveal defense reservation (BotModules/BotGeneralSafety.py).
        # Always instantiated; every consumer no-ops while GENERAL_SAFETY_ENABLED
        # is False, so live behavior is unchanged by default.
        self.general_safety_state: BotGeneralSafety.GeneralSafetyState = BotGeneralSafety.GeneralSafetyState()
        # Per-selection tag set ONLY at true core defensive returns inside
        # pick_move_after_prep (threat defense, survival, danger tile, flank,
        # city-preemptive, general-adjacent nuke, delayed own-kill race). The
        # general-safety final guard uses it to allow urgent defense spends.
        self.defense_override_move: bool = False

        self.attackFailedTurn = 0
        self.countFailedQuickAttacks = 0
        self.countFailedHighDepthAttacks = 0
        self.largeTilesNearEnemyKings = {}
        self.no_file_logging: bool = False
        self.enemyCities = []
        self.enemy_city_approxed_attacks: typing.Dict[Tile, typing.Tuple[int, int, int]] = {}
        """Contains a mapping from an enemy city, to the approximate (turns, ourAttack, theirDefense)"""

        self.dangerAnalyzer: DangerAnalyzer = None
        self.cityAnalyzer: CityAnalyzer = None
        self.gatherAnalyzer: GatherAnalyzer = None
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
        # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
        # simulation must run background WRP work synchronously for deterministic route assertions.
        self.run_background_work_synchronously: bool = False
        # Feature flag for BotStealthAllIn (stealth losing all-in + undefendable WRP hunt). Enabled for live
        # games per user request; Tests/test_AllIn.py stealth/hunt tests also turn it on explicitly.
        self.enable_stealth_all_in: bool = True
        self.stealth_all_in: StealthAllInState | None = None
        self.stealth_all_in_generation: int = 0
        # Tests/test_AllIn.py::AllInTests.test_should_all_in_along_short_top_path_instead_of_long_bottom_flank:
        # when the direct attack route beats every hidden flank on the 3:1 surprise-vs-delay
        # cost model, suppress the flank search for a few turns instead of re-running it each turn.
        self.stealth_all_in_direct_preferred_until_turn: int = -1
        # Tests/test_AllIn.py::AllInTests.test_should_finish_losing_all_in_attack_instead_of_replanning_forever:
        # consecutive projected-launch-kill-failure turns for the current uncommitted stealth
        # plan; when it reaches BotStealthAllIn.CANNOT_KILL_GATHER_TURNS_BEFORE_DIVE the plan
        # stops demanding a verified kill and dives the assembled stack anyway.
        self.stealth_all_in_cannot_kill_counter: int = 0
        # Tests/test_AllIn.py::AllInTests.test_should_continue_committed_kill_attack_instead_of_slow_gather:
        # the quick-kill eval re-runs from scratch every turn against a pessimistic
        # fog-defense cutoff, so one turn of estimate drift used to drop an in-flight
        # kill attack and leave the stack parked while a 3x slower gather replanned.
        # Once a kill path commits we remember it (and the cutoff accepted at commit
        # time) and let the fresh eval continue the march unless hard new information
        # - a dead route or a visibly reinforced general - says the attack is dead.
        self.committed_quick_kill: Path | None = None
        self.committed_quick_kill_cutoff: int = 0
        # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
        # keep the asynchronous undefendable-hunt job and per-turn throttle on the bot instance.
        self.stealth_hunt_job: StealthWrpJob | None = None
        self.stealth_hunt_target_player: int = -1
        self.stealth_hunt_last_evaluation_turn: int = -1
        self.stealth_hunt_last_evaluated_army: int = 0
        self.stealth_hunt_excluded_start_tile_indexes: set[int] = set()
        self.stealth_hunt_render_path: Path | None = None
        self.last_stealth_route_defense_interrupt: StealthRouteDefenseInterrupt | None = None
        self.wrp_worker_process: WrpWorkerProcess | None = None
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

        self._flow_expander: ArmyFlowExpanderV2 | None = None

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
        self.city_capture_plan_option: TilePlanInterface | None = None
        self.contest_city_plan_option: TilePlanInterface | None = None
        self.quick_kill_city_plan_option: TilePlanInterface | None = None
        self._expansion_value_matrix: MapMatrixInterface[float] | None = None
        self.targetPlayer = -1
        self.failedUndiscoveredSearches = 0
        self.largePlayerTiles: typing.List[Tile] = []
        """The large tiles owned by us."""

        self.largeNegativeNeutralTiles: typing.List[Tile] = []
        """Large negative neutral tiles (less than or equal to -2), ordered from most-negative to least-negative."""
        self.playerTargetScores = [0 for i in range(16)]
        self.general: Tile = None
        self.gatherNodes = None
        self.redGatherTreeNodes = None
        self.isInitialized = False
        self.last_init_turn: int = 0
        self.is_pre_resume_init_turn: bool = False
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
        """
        This path may be from the general, or from a forward city, or from the central_defense_point etc, and will often be shorter than the true distance between generals.
        """

        self.shortest_path_to_target_player: Path | None = None
        """
        This path should always be from the general to the opponents general.
        """

        self.defensive_spanning_tree: typing.Set[Tile] = set()
        """Main defensive spanning tree using cities_in_play (cities not further from enemy than our gen is)."""
        self.last_central_defense_signature: tuple[int | None, tuple[tuple[int, int], ...]] | None = None

        self.friendly_city_spanning_tree: typing.Set[Tile] = set()
        """Secondary spanning tree connecting ALL friendly cities (for broader defensive coverage)."""

        self.enemy_attack_path: Path | None = None
        """The probable enemy attack path."""

        self.likely_kill_push: bool = False
        """True ONLY when the enemy is likely to push AND the enemy has enough to kill us. If we could already defend the kill push in spite of the likely kill push path, it will be false (even though the push path will be populated)"""

        self.viewInfo: ViewInfo | None = None

        self._minAllowableArmy = -1
        self.threat: ThreatObj | None = None
        self.threats_we_care_about_by_tile: dict[Tile, list[ThreatObj]] | None = None
        self.best_defense_leaves: typing.List[GatherTreeNode] = []
        self.has_defenseless_modifier: bool = False
        self.has_watchtower_modifier: bool = False
        self.has_misty_veil_modifier: bool = False

        self.is_weird_custom: bool = False

        self.history = History()
        self.timings: Timings | None = None
        self.tileIslandBuilder: TileIslandBuilder = None
        self._should_recalc_tile_islands: bool = False
        self.last_flow_expander: ArmyFlowExpander | None = None
        self.last_flow_opt_collection: FlowExpansionPlanOptionCollection | None = None
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

        self.undiscovered_priorities: MapMatrixInterface[float] = None
        self._undisc_prio_turn: int = -1
        self._afk_players: typing.List[Player] | None = None
        self._is_ffa_situation: bool | None = None

        self.explored_this_turn = False
        self.board_analysis: BoardAnalyzer | None = None

        # engine stuff
        self.targetingArmy: Army | None = None
        self.cached_scrims = {} #: typing.Dict[str, ArmySimResult]
        self.next_scrimming_army_tile: Tile | None = None

        # configuration
        self.disable_engine: bool = True

        self.engine_use_mcts: bool = True
        # self.mcts_engine: MctsDUCT = MctsDUCT()
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
        self.gather_include_distance_from_enemy_TILES_as_negatives: int = 2  # 3 is definitely too much, confirmed in lots of games. ACTUALLY SEEMS TO BE CONTESTED NOW 3 WON 500 GAME MATCH, won another 500 game match, using 3...

        self.gather_include_distance_from_enemy_general_as_negatives: float = 0.0
        self.gather_include_distance_from_enemy_general_large_map_as_negatives: float = 0.0
        self.gather_use_pcst: bool = False
        # swaps between max iterative and max set, now
        self.gather_use_max_set: bool = True
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

        self.expansion_use_iterative_flow: bool = True
        self.expansion_use_legacy: bool = False
        self.expansion_use_tile_islands: bool = False
        self.expansion_full_time_limit: float = 0.1
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
        self.info_render_pathway_distances: bool = False
        self.info_render_leaf_move_values: bool = False
        self.info_render_army_emergence_values: bool = True
        self.info_render_board_analysis_choke_widths: bool = False
        self.info_render_board_analysis_zones: bool = True
        self.info_render_city_priority_debug_info: bool = False
        self.info_render_general_undiscovered_prediction_values: bool = False
        self.info_render_general_prediction_spawn_fairness_weights: bool = True
        """Print the spawn fairness contribution in the bottom left corner of tiles, one decimal place"""
        self.info_render_general_prediction_emergence_locality_weights: bool = True
        """Print the value in the top right corner of tiles for the emergence locality contribution of general prediction weight, one decimal place"""
        self.info_render_tile_deltas: bool = False
        self.info_render_tile_states: bool = False
        self.info_render_expansion_matrix_values: bool = False
        self.info_render_intercept_data: bool = False
        self.info_render_tile_islands: bool = False
        self.info_render_defense_spanning_tree: bool = True
        self.info_render_friendly_city_spanning_tree: bool = False
        self.info_render_flow_expand: bool = True
        self.info_render_enemy_vision_data: bool = True

    # STEP2: Stay in EklipZBotV2.py. Tiny object-display helper with no domain logic; keep on the outer bot shell unchanged.
    def __repr__(self):
        return str(self)

    # STEP2: Stay in EklipZBotV2.py. Tiny object-display helper with no domain logic; keep on the outer bot shell unchanged.
    def __str__(self):
        return f'[eklipz_bot {str(self._map)}]'

    @property
    def flow_expander(self) -> ArmyFlowExpanderV2:
        if self._flow_expander is None:
            if self._map is None:
                raise AssertionError('flow_expander unavailable before bot map initialization')
            self._flow_expander = ArmyFlowExpanderV2(self._map, self.perf_timer)
        return self._flow_expander

    @flow_expander.setter
    def flow_expander(self, value: ArmyFlowExpanderV2 | None) -> None:
        self._flow_expander = value

    # STEP2: Stay in EklipZBotV2.py. Lifecycle stub with no body today; preserve on the shell for compatibility with existing callers.
    def spawnWorkerThreads(self):
        return

    # STEP2: Stay in EklipZBotV2.py. Top-level move orchestration/error handling/history/render prep spanning many modules; keep on shell and have it call extracted helpers.
    def find_move(self, is_lag_move=False) -> Move | None:
        move: Move | None = None
        try:
            move = self.select_move(is_lag_move=is_lag_move)

            # BotGeneralSafety: a certified gather offer that sources from the
            # general is exempt from the generic death-move heuristic - the
            # safety certificate already prices the retained garrison, and the
            # heuristic cannot model a half donation reinforcing the reserve.
            if (move is not None and move.source.isGeneral
                    and not BotGeneralSafety.is_pending_gather_move(self, move)
                    and not BotPathingUtils.is_move_safe_valid(self, move, allowNonKill=True)):
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

            # Tests/test_FFA.py::FFATests.test_should_attack_aggressor_without_overgathering_or_abandoning_general
            # The find_move safety fallback above can substitute a fresh general move after
            # select_move already reconciled; re-apply the ordinary-all-in reserve on the final
            # move so a replaced general departure still retains the required garrison.
            move = BotFfaEndgame.reconcile_general_reserve_move(self, move)
            # BotGeneralSafety consumption must observe the TRUE executed move:
            # the isGeneral death-move fallback above can still substitute a
            # different move after select_move returned, so re-apply the
            # anchor/general guard and only then consume the pending offer.
            # No-op while GENERAL_SAFETY_ENABLED is False.
            move = BotGeneralSafety.reconcile_anchor_move(self, move, self.defense_override_move)
            BotGeneralSafety.note_final_move(self, move)

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
                if curPathMove is None:
                    self.info("Returned a move while curPath had no next move. Resetting path...")
                    self.curPath = None
                    self.curPathPrio = -1
                elif curPathMove.source == move.source and curPathMove.dest != move.dest:
                    self.info("Returned a move using the tile that was curPath, but wasn't the next path move. Resetting path...")
                    self.curPath = None
                    self.curPathPrio = -1

            if self._map.turn not in self.history.move_history:
                self.history.move_history[self._map.turn] = []
            self.history.move_history[self._map.turn].append(move)

            BotRendering.prep_view_info_for_render(self, move)

        return move

    # STEP2: Stay in EklipZBotV2.py. Tiny shell utility used broadly for perf/log timing display; keep local on the bot.
    def get_elapsed(self):
        if self._map.is_chess_clock and self.lastTurnStartTime != 0 and self.last_init_turn == self._map.turn:
            return round(time.perf_counter() - self.lastTurnStartTime, 3)
        return round(self.perf_timer.get_elapsed_since_update(self._map.turn), 3)

    # STEP2: Stay in EklipZBotV2.py. Core turn initialization/orchestration entrypoint spanning trackers, analyzers, communications, targeting, and caches; keep on shell and delegate sub-steps later.
    def init_turn(self, secondAttempt=False):
        if self.last_init_turn == self._map.turn:
            return

        # Tests: Tests/test_GeneralTrade.py - a mutual general capture detected
        # by MapBase.update must rebind all general-dependent bot state BEFORE
        # any general-dependent calculations run this turn.
        trade = self._map.general_trade
        if trade is not None:
            # reconcile every traded pair's tracked army state for ANY
            # detected trade - an observed trade between other players still
            # requires the pair's stale tracked armies to be rebuilt.
            for detectedTrade in self._map.general_trades:
                self.armyTracker.handle_general_trade(detectedTrade)
                self.opponent_tracker.handle_general_trade(detectedTrade)
                # Tests: Tests/test_FfaGeneralTrade.py - observed trades need
                # bot-level spatial caches (territory, alt gen positions,
                # target expectations) swapped too; self trades are handled
                # by the rebind below.
                if detectedTrade.player != self._map.player_index and detectedTrade.opponent != self._map.player_index:
                    BotEventHandlers.handle_observer_general_trade(self, detectedTrade)
            if trade.player == self._map.player_index and self.general is not self._map.generals[self._map.player_index]:
                BotEventHandlers.handle_general_trade(self)

        self.quick_kill_city_plan_option = None
        self.contest_city_plan_option = None

        self.was_defending_economy = self.defend_economy
        self.defend_economy = False

        self._alt_en_gen_position_distances: typing.List[MapMatrixInterface[int] | None] = [None for _ in self._map.players]

        self._afk_players = None
        self._is_ffa_situation = None

        self.gathers = None
        self.gatherNodes = None
        self.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0, self._map.turn)

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

        if self.board_analysis.central_defense_point and self.board_analysis.intergeneral_analysis:
            centralPoint = self.board_analysis.central_defense_point
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

        if not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 3) % 5 == 0:
            with self.perf_timer.begin_move_event('Inter-general analysis'):
                # also rescans chokes, now.
                BotCentralDefense.rebuild_intergeneral_analysis_for_central_defense(self)

        if not self.is_pre_resume_init_turn:
            # Joint FFA predicted-general placement refreshes AFTER this turn's
            # movement/emergence processing and BEFORE any fog-land build, so every
            # player's fog anchors to their OWN jointly-placed seed instead of the
            # target player's prediction that used to be passed to every builder.
            # Regression:
            # Tests/test_FogLandBuilder.py::FogLandBuilderTests.test_should_separate_ffa_fog_land_from_predicted_generals
            self.armyTracker.ffa_general_placement.refresh(self.armyTracker, self.targetPlayer)
            targetSeedChanged = False
            if FfaGeneralPlacement.is_original_ffa(self._map) and self.targetPlayer != -1:
                if self.targetPlayer < len(self.armyTracker.ffa_general_placement.positions):
                    targetSeed = self.armyTracker.ffa_general_placement.positions[self.targetPlayer]
                    if targetSeed is not None and targetSeed != self.targetPlayerExpectedGeneralLocation:
                        self.targetPlayerExpectedGeneralLocation = targetSeed
                        targetSeedChanged = True
            # Clear stale temp fog guesses for every player about to rebuild BEFORE
            # the per-player fills run, so an earlier fill cannot see a later
            # player's previous-seed blob as still-owned land.
            self.armyTracker.clear_temp_fog_predictions_for_pending_rebuilds()

            with self.perf_timer.begin_move_event('ArmyTracker fog land builder'):
                fogTileCounts = self.opponent_tracker.get_all_player_fog_tile_count_dict()
                isOriginalFfa = FfaGeneralPlacement.is_original_ffa(self._map)
                ffaPositions = self.armyTracker.ffa_general_placement.positions
                for player in self._map.players:
                    fogSeed = self.targetPlayerExpectedGeneralLocation
                    if isOriginalFfa and player.index < len(ffaPositions):
                        fogSeed = ffaPositions[player.index]
                    self.armyTracker.update_fog_prediction(player.index, fogTileCounts[player.index], fogSeed)

            # Tests/test_FogLandBuilder.py::FogLandBuilderTests.test_should_separate_ffa_fog_land_from_predicted_generals:
            # path recalculation must run only AFTER every player's fog land has been
            # rebuilt around the new seeds, so island/land anchoring observes the
            # freshly seeded ownership rather than last turn's stale blobs.
            if targetSeedChanged:
                self.recalculate_player_paths(force=True)

            self._evaluatedUndiscoveredCache = []
            with self.perf_timer.begin_move_event('get_predicted_target_player_general_location'):
                if self.targetPlayerExpectedGeneralLocation is None:
                    maxTile: Tile = BotTargeting.get_predicted_target_player_general_location(self)
                    logbook.info(f'DEBUG: en tile {maxTile} get_predicted_target_player_general_location')
                    if maxTile is not None:
                        self.targetPlayerExpectedGeneralLocation = maxTile
                        self.recalculate_player_paths(force=True)
                    else:
                        self.targetPlayerExpectedGeneralLocation = self.general
                elif self.targetPlayerExpectedGeneralLocation.visible and not self.targetPlayerExpectedGeneralLocation.isGeneral:
                    maxTile: Tile = BotTargeting.get_predicted_target_player_general_location(self)
                    logbook.info(f'DEBUG: en tile {maxTile} get_predicted_target_player_general_location')
                    if self.targetPlayerExpectedGeneralLocation != maxTile and maxTile is not None:
                        self.targetPlayerExpectedGeneralLocation = maxTile
                        self.recalculate_player_paths(force=True)
                elif self.targetPlayer != -1 and not self.armyTracker.valid_general_positions_by_player[self.targetPlayer][self.targetPlayerExpectedGeneralLocation]:
                    # Tests/test_BotBehavior.py::BotBehaviorTests.test_should_update_general_prediction_when_emergence_invalidates_it
                    # Current prediction is no longer valid (eliminated by emergence events), recalculate
                    logbook.info(f'targetPlayerExpectedGeneralLocation {self.targetPlayerExpectedGeneralLocation} is no longer valid due to emergence, recalculating...')
                    maxTile: Tile = BotTargeting.get_predicted_target_player_general_location(self)
                    logbook.info(f'DEBUG: en tile {maxTile} get_predicted_target_player_general_location (invalidated)')
                    if maxTile is not None:
                        self.targetPlayerExpectedGeneralLocation = maxTile
                        self.recalculate_player_paths(force=True)
                elif self.shortest_path_to_target_player is None:
                    # Tests/test_BotBehavior.py::BotBehaviorTests.test_should_not_gather_against_likely_kill_threat_when_must_attack_especially_when_up_on_gathered_army:
                    # Resume data can restore an existing predicted enemy general while path caches are empty. Rebuild paths to that prediction instead of treating the empty cache as permission to replace it with a fresh density guess.
                    self.recalculate_player_paths(force=True)

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
                            altEnGenPositions = BotTargeting.get_target_player_possible_general_location_tiles_sorted(self, elimNearbyRange=2, player=player.index, cutoffEmergenceRatio=0.3, limitNearbyTileRange=limitNearbyTileRange, requirePredictedFogTeamTile=True)
                            self.alt_en_gen_positions[player.index] = altEnGenPositions
                            self._alt_en_gen_position_distances[player.index] = None

        self.tileIslandBuilder.intergeneral_analysis = self.board_analysis.intergeneral_analysis
        if self._map.is_army_bonus_turn or self._should_recalc_tile_islands:
            with self.perf_timer.begin_move_event('TileIsland recalc'):
                self.tileIslandBuilder.recalculate_tile_islands(self.targetPlayerExpectedGeneralLocation)
                self._should_recalc_tile_islands = False
        else:
            # EXPANSION RELIES ON TILE ISLANDS BEING ACCURATE OR ELSE IT WILL DIVE INTO CORNERS WHERE IT ALREADY CUT OFF ITS RECAPTURE PATH BECAUSE IT THINKS IT CAN RECAPTURE USING THE TILES ITS COMING FROM
            with self.perf_timer.begin_move_event('TileIsland update'):
                self.tileIslandBuilder.update_tile_islands(self.targetPlayerExpectedGeneralLocation)

        self.armyTracker.verify_player_tile_and_army_counts_valid()

        # Calculate defensive spanning trees early for win condition analysis
        if self._map.is_army_bonus_turn or self.defensive_spanning_tree is None or len(self.defensive_spanning_tree) == 0:
            with self.perf_timer.begin_move_event('defensive spanning trees (early)'):
                # Main spanning tree using cities_in_play (centralized defense)
                self.defensive_spanning_tree = BotDefense._get_defensive_spanning_tree(
                    self, set(), BotGatherOps.get_gather_tiebreak_matrix(self), use_cities_in_play_only=True, require_min_distance=True
                )
                # Secondary spanning tree using ALL friendly cities (broader coverage)
                self.friendly_city_spanning_tree = BotDefense._get_defensive_spanning_tree(
                    self, set(), BotGatherOps.get_gather_tiebreak_matrix(self), use_cities_in_play_only=False
                )

        if not BotStateQueries.is_all_in(self) and (not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 5) % 5 == 0):
            with self.perf_timer.begin_move_event('WinConditionAnalyzer Analyze'):
                self.win_condition_analyzer.analyze(self.targetPlayer, self.targetPlayerExpectedGeneralLocation, self.perf_timer)

            # Calculate fog risk using opponent tracker
            if self.targetPlayer != -1:

                with self.perf_timer.begin_move_event('Fog Risk spot 2'):
                    city_spanning_tree_tile_count = len(self.friendly_city_spanning_tree)
                    fog_risk, fog_army_comp, city_comp, expected_city_spanning_offset = self.opponent_tracker.get_immediate_fog_risk(self.targetPlayer, city_spanning_tree_tile_count)
                    self.viewInfo.add_stats_line(f'FogRisk {fog_risk} ({fog_army_comp}a/{city_comp}c -{expected_city_spanning_offset}c)')


                with self.perf_timer.begin_move_event('Calc basic general defense'):
                    # Calculate basic defense against general and forward spanning tree
                    self.win_condition_analyzer.calculate_basic_defense_against_general(
                        self.defensive_spanning_tree,
                        self.general,
                        self.sketchiest_potential_inbound_flank_path
                    )

                # Use central defense point as the forward point, or most forward defense city
                forward_point = self.board_analysis.central_defense_point
                if forward_point is None:
                    forward_point = self.win_condition_analyzer.most_forward_defense_city

                with self.perf_timer.begin_move_event('Calc basic spanning tree defense'):
                    self.win_condition_analyzer.calculate_basic_defense_against_forward_spanning_tree(
                        self.defensive_spanning_tree,
                        forward_point
                    )

                # Add basic defense stats line - show defense against general
                gen_def = self.win_condition_analyzer
                self.viewInfo.add_stats_line(
                    f'Basic Defense {gen_def.basic_defense_general_army}a ({gen_def.basic_defense_general_moves}m), {gen_def.basic_defense_general_turns}t'
                )
                # Mark tiles necessary for that defensive gather
                for tile in gen_def.basic_defense_general_tiles:
                    self.viewInfo.add_targeted_tile(tile, TargetStyle.BLUE, radiusReduction=5)

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

        # TEMPORARY DIAGNOSTIC (general-coloring investigation): per-turn dump
        # of generals[]/player.general/predicted-position state; remove once
        # the miscoloring source is identified.
        BotEventHandlers.log_general_state_debug(self)

        self.cached_scrims = {}

    # STEP2: Stay in EklipZBotV2.py. High-level pre-move orchestration that coordinates timings, path recalculation, out-of-play mode, all-in state, and dropped-move recovery across many domains.
    def perform_move_prep(self, is_lag_move: bool = False):
        with self.perf_timer.begin_move_event('scan_map_for_large_tiles_and_leaf_moves()'):
            self.scan_map_for_large_tiles_and_leaf_moves()

        # BotGeneralSafety: refresh reveal episodes/forecasts AFTER the scan so
        # fresh king-location knowledge and opponent-tracker state are current.
        # No-op while GENERAL_SAFETY_ENABLED is False.
        BotGeneralSafety.update(self)

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left:
        # a forced FFA all-in commits a survivable route to the selected enemy's general
        # corridor; the generic timing-cycle reset must not erase that committed spear and
        # restart the attack several turns behind.
        preservedFfaPath = self.curPath if BotFfaEndgame.is_forced_all_in(self) else None
        if self.timings and self.timings.get_turn_in_cycle(self._map.turn) == 0:
            BotTimings.timing_cycle_ended(self, )
            if preservedFfaPath is not None and self.curPath is None:
                self.curPath = preservedFfaPath
                self.viewInfo.add_info_line(
                    f'FFA3 preserve committed all-in route across timing reset: {preservedFfaPath.get_first_move()}')

        if self.curPath is not None:
            nextMove = self.curPath.get_first_move()

            if nextMove is None:
                self.viewInfo.add_info_line(f'Killing curPath because it has no next move.')
                self.curPath = None
            elif nextMove.dest is not None and nextMove.dest.isMountain:
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

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # Refresh the endgame policy after the scan so army-advantage all-in selection below
        # sees the current neutral-city priority flag.
        BotFfaEndgame.update_policy(self)

        if BotCombatOps.determine_should_winning_all_in(self):
            wasAllIn = self.is_all_in_army_advantage
            self.is_all_in_army_advantage = True
            if not wasAllIn:
                self.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0, self._map.turn)
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
            # In chess clock mode we explicitly manage clear_moves through BotHost and cannot send clear_moves
            # while start_holding_clear_moves is active, so never treat a previous turn as a dropped move.
            dropped = False if self._map.is_chess_clock else BotRepetition.dropped_move(self)
            if dropped:
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
                curPathNext = None
                if self.curPath is not None:
                    curPathNext = self.curPath.get_first_move()
                if lastMove is not None:
                    gatheredTilesBeforeMove = self.tiles_gathered_to_this_cycle.copy()
                    if self._map.is_player_on_team_with(lastMove.dest.delta.oldOwner, self.general.player):
                        self.tiles_gathered_to_this_cycle.add(lastMove.dest)
                        if lastMove.dest.isCity:
                            self.cities_gathered_this_cycle.discard(lastMove.dest)
                    elif lastMove.dest.player == self.general.player:
                        self.tiles_captured_this_cycle.add(lastMove.dest)
                        if lastMove.dest.isCity:
                            self.friendly_city_spanning_tree = None
                            self.defensive_spanning_tree = None
                            if lastMove.dest.delta.oldOwner == -1:
                                self.was_allowing_neutral_cities_last_turn = False

                    if not lastMove.move_half:
                        self.tiles_gathered_to_this_cycle.discard(lastMove.source)
                        self.tiles_evacuated_this_cycle.add(lastMove.source)
                        if lastMove.source.isCity:
                            self.cities_gathered_this_cycle.add(lastMove.source)
                    if lastMove.dest.isCity and lastMove.dest.delta.oldOwner == -1:
                        amountSpentToCapCity = min(lastMove.army_moved, lastMove.dest.delta.oldArmy)
                        self.opponent_tracker.record_neutral_city_capture_army_spent(self.general.player, amountSpentToCapCity)

                        ourCycleStats = self.opponent_tracker.get_current_cycle_stats_by_player(self.general.player)
                        if ourCycleStats is not None:
                            gatherMoveCount = ourCycleStats.moves_spent_gathering_fog_tiles + ourCycleStats.moves_spent_gathering_visible_tiles
                            gatheredArmyAmount = sum(tile.army for tile in gatheredTilesBeforeMove) - len(gatheredTilesBeforeMove)
                            self.opponent_tracker.record_neutral_city_capture_gather_time(
                                self.general.player,
                                amountSpentToCapCity,
                                gatherMoveCount,
                                gatheredArmyAmount)
                    if self.curPath and curPathNext and curPathNext.source == lastMove.source:
                        self.curPath.pop_first_move()
                elif self.curPath is not None and curPathNext is None:
                    self.curPath.pop_first_move()
                if self.force_far_gathers:
                    self.force_far_gathers_turns -= 1
                else:
                    self.force_far_gathers_sleep_turns -= 1

    def _stop_holding_clear_moves(self, move: Move | None) -> Move | None:
        """If the server is still holding clear-moves for us and we are about to return a real move, release the hold first."""
        if move is not None and self.holding_clear_moves:
            self.holding_clear_moves = False
            if self.stop_holding_clear_moves_func is not None:
                self.stop_holding_clear_moves_func()
        return move

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

        if self._map.turn == 0 or (self._map.turn <= 1 and not self._map.is_chess_clock):
            # bypass divide by 0 error instead of fixing it
            return self._stop_holding_clear_moves(None)

        if self._map.remainingPlayers == 1:
            return self._stop_holding_clear_moves(None)

        self.perform_move_prep(is_lag_move=is_lag_move)

        if is_lag_move and self.curPath and self.is_lag_massive_map:
            moves = self.curPath.get_move_list()
            for move in moves:
                if move is None:
                    self.info(f'LAG CONTINUING NONE MOVE PLANNED')
                    return self._stop_holding_clear_moves(None)
                if move.source.player == self.general.player and move.source.army > 3:
                    self.info(f'LAG CONTINUING PLANNED MOVES {move}')
                    return self._stop_holding_clear_moves(move)

        if self._map.turn - 1 in self.history.move_history:
            lastMove = self.history.move_history[self._map.turn - 1][0]
            if BotRepetition.dropped_move(self) and self._map.turn <= 50 and lastMove is not None:
                if lastMove.source != self.general:
                    self.viewInfo.add_info_line(f're-performing dropped first-25 non-general move {str(lastMove)}')
                    return self._stop_holding_clear_moves(lastMove)
                else:
                    # force reset the expansion plan so we recalculate from general.
                    self.city_expand_plan = None

        if not is_lag_move and not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 2) % 5 == 0:
            with self.perf_timer.begin_move_event("recalculating player path"):
                self.recalculate_player_paths()

        if not BotStateQueries.is_still_ffa_and_non_dominant(self):
            BotTimings.prune_timing_split_if_necessary(self)

        # BotGeneralSafety: reset the per-selection defense-override tag; only
        # true core defensive returns inside pick_move_after_prep set it True.
        self.defense_override_move = False
        move = self.pick_move_after_prep(is_lag_move)

        if move and self.curPath and move.source in self.curPath.tileSet:
            pathNext = self.curPath.get_first_move()
            if move != pathNext and pathNext is not None and move.dest != pathNext.source:
                self.curPath = None

        # Tests/test_CityContestation.py::test_should_split_army_to_recapture_city_and_still_block_threat:
        # central chokepoint so ANY chosen move that would drag a threat-blocking tile
        # through one of its blocked_destinations leaves the required garrison behind via
        # move_half instead of abandoning the block (the oscillation the defense gather
        # then had to yank back). Applied after the curPath check so a converted split
        # does not falsely invalidate the in-flight path.
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # RETALIATE ignores defense entirely, so the threat-blocking half-move reconciliation
        # must not constrain its attack move (the move itself is still produced legally).
        if not BotFfaEndgame.is_retaliating(self):
            move = BotDefense.apply_threat_blocking_split_hint_to_move(self, move)

        self.last_move = move
        final_move = self._stop_holding_clear_moves(move)
        # Tests/test_FFA.py::FFATests.test_should_attack_aggressor_without_overgathering_or_abandoning_general
        # Enforce the ordinary-all-in general reserve on the ACTUAL final move (post split-hint and
        # holding-clear) so early QK/stealth/curPath/policy moves cannot strip the required garrison.
        final_move = BotFfaEndgame.reconcile_general_reserve_move(self, final_move)
        # BotGeneralSafety final-move backstop: protect the retained general AND
        # the reserve anchor from ordinary offense (full->half offer, else
        # block). True defense overrides and the certified safety-gather step
        # itself are allowed; no-op while GENERAL_SAFETY_ENABLED is False.
        final_move = BotGeneralSafety.reconcile_anchor_move(self, final_move, self.defense_override_move)
        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible
        # Record the ACTUAL returned move (post split-hint + holding-clear) for the
        # committed FFA kill-gather schedule. The feature consumes its pending offer
        # only when this confirmed move matches; a defense preemption or pass leaves
        # the cursor untouched so the same step is re-offered next turn. Non-FFA
        # behavior is untouched (no-op when no kill-gather state is committed).
        BotFfaKillGather.note_final_move(self, final_move)
        return final_move

    # STEP2: Stay in EklipZBotV2.py. Central post-prep decision tree coordinating combat, defense, city capture, expansion, and continuation logic; keep on shell and delegate subroutines out.
    def pick_move_after_prep(self, is_lag_move=False):
        BotStealthAllIn.poll_wrp_worker_results(self)
        BotFfaKillGather.poll_wrp_worker(self)
        with self.perf_timer.begin_move_event('calculating general danger / threats'):
            BotDefense.calculate_general_danger(self)

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # Refresh kill-threat retaliation now that danger analysis is current, then let TURTLE
        # (owned-only gather to our general, deliberate pass) preempt every later branch.
        BotFfaEndgame.update_retaliation(self)
        # Tests/test_FFA.py::FFATests.test_should_attack_aggressor_without_overgathering_or_abandoning_general
        # Compute the ordinary-all-in general reserve now that danger analysis and the forced
        # mode/target are current; reconcile_general_reserve_move enforces it on the final move.
        BotFfaEndgame.update_general_reserve(self)
        ffaEndgameCityPriority = BotFfaEndgame.is_prioritizing_neutral_city(self)
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # Under a forced all-in (or ECONOMY neutral-city priority) only a lethal own-general Kill
        # threat may preempt the attack/city branch; opportunistic king-kills/hunts must also only
        # ever target the policy enemy, never a bystander.
        ffaForcedTarget = -1
        if BotFfaEndgame.is_forced_all_in(self):
            ffaForcedTarget = BotFfaEndgame.get_state(self).decision.target_player
        if BotFfaEndgame.get_mode(self) == BotFfaEndgame.FfaEndgameMode.TURTLE:
            return BotFfaEndgame.get_move(self)

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # RETALIATE throws every resource at the latched offender and preempts EVERY defense,
        # king-kill, city, and economy branch - including committed-route defense interrupts.
        # get_retaliate_move routes committed/stealth/curPath/generic attack then a deterministic
        # forward fallback, all evaluated with threat=None and an empty defense set.
        if BotFfaEndgame.is_retaliating(self):
            return BotFfaEndgame.get_retaliate_move(self, None, None, 0.0, set())

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

        # BotGeneralSafety: while a general-reveal reserve stage is unmet, every
        # nondefensive branch below must not steal the execution window (same
        # contract as the committed FFA kill-gather guards). No-op while the
        # feature flag is False.
        generalSafetyReserving = BotGeneralSafety.is_reserving(self)

        #  # # # #   ENEMY KING KILLS
        stealthRouteCommittedAtStart = (
            self.stealth_all_in is not None
            and self.stealth_all_in.committed_route is not None)
        with self.perf_timer.begin_move_event('Checking for king kills and races'):
            killMove, kingKillPath, raceChance = BotCombatOps.check_for_king_kills_and_races(self, threat)
            # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
            # defer to QK whenever it has a move, but never interrupt a committed stealth route.
            # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible
            # While an FFA kill-gather is committed, unrelated opportunistic king-kills must
            # not waste the execution window; is_committed validates/clears stale state.
            if (killMove is not None and not stealthRouteCommittedAtStart
                    and not BotFfaKillGather.is_committed(self)
                    and not generalSafetyReserving
                    and not ffaEndgameCityPriority
                    and (ffaForcedTarget == -1 or killMove.dest.player == ffaForcedTarget)):
                return killMove

        defenseCriticalTileSet = set()
        if self.teammate_general is not None and self.teammate_general.player in self._map.teammates:
            for army in self.armyTracker.armies.values():
                if army.player in self._map.teammates:
                    if army.last_moved_turn > self._map.turn - 3:
                        if army.tile not in defenseCriticalTileSet:
                            logbook.info(f'DEFENSE_NEG_ADD source=teammate_recent_army tile={army.tile} army={army} lastMovedTurn={army.last_moved_turn}')
                            defenseCriticalTileSet.add(army.tile)
                    if army.tile.delta.armyDelta != 0 and (army.tile.delta.oldOwner != army.player or army.tile.delta.oldArmy < army.tile.army):
                        if army.tile not in defenseCriticalTileSet:
                            logbook.info(f'DEFENSE_NEG_ADD source=teammate_army_delta tile={army.tile} army={army} oldOwner={army.tile.delta.oldOwner} oldArmy={army.tile.delta.oldArmy} armyDelta={army.tile.delta.armyDelta}')
                            defenseCriticalTileSet.add(army.tile)

        self.threat = threat

        BotCombatOps.check_should_be_all_in_losing(self)

        if self.is_all_in_losing:
            logbook.info(f"~~~ ___ {self.get_elapsed()}\n   YO WE ALL IN DAWG\n~~~ ___")

        stealthRouteAborted = False
        if stealthRouteCommittedAtStart:
            committedRouteMove = BotStealthAllIn.get_committed_route_move(
                self,
                threat,
                defenseCriticalTileSet,
                kingKillPath,
                raceChance)
            if committedRouteMove is not None:
                return committedRouteMove
            stealthRouteAborted = self.stealth_all_in is None
        elif not BotStealthAllIn.is_stealth_all_in_active(self):
            BotStealthAllIn.clear_uncommitted_state(self)

        # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
        # evaluate an undefendable hunt before city, expansion, and later QK planning can take over.
        if not ffaEndgameCityPriority and not stealthRouteAborted and not stealthRouteCommittedAtStart:
            huntMove = BotStealthAllIn.get_undefendable_hunt_move(
                self,
                threat,
                defenseCriticalTileSet,
                kingKillPath,
                raceChance)
            # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible
            # unrelated stealth hunts are nondefensive opportunism - skip while committed.
            if (huntMove is not None and not BotFfaKillGather.is_committed(self)
                    and not generalSafetyReserving
                    and not ffaEndgameCityPriority
                    and (ffaForcedTarget == -1 or huntMove.dest.player == ffaForcedTarget)):
                return huntMove
        # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
        # fall back to the precomputed QK move when no undefendable hunt commits.
        if (killMove is not None
                and (not stealthRouteCommittedAtStart
                     or self.stealth_all_in is None)
                and not BotFfaKillGather.is_committed(self)
                and not generalSafetyReserving
                and not ffaEndgameCityPriority
                and (ffaForcedTarget == -1 or killMove.dest.player == ffaForcedTarget)):
            return killMove

        # if not self.isAllIn() and (threat.turns > -1 and self.dangerAnalyzer.anyThreat):
        #    armyAmount = (self.general_min_army_allowable() + enemyNearGen) * 1.1 if threat is None else threat.threatValue + general.army + 1

        if not BotStateQueries.is_all_in(self) and (not is_lag_move and not self.is_lag_massive_map or self._map.turn < 3 or (self._map.turn + 2) % 5 == 0):
            with self.perf_timer.begin_move_event('ENEMY Expansion quick check'):
                self.enemy_expansion_plan = BotExpansionOps.build_enemy_expansion_plan(self, timeLimit=0.007, pathColor=(255, 150, 130))

        self.intercept_plans = BotDefense.build_intercept_plans(self, defenseCriticalTileSet)
        for i, interceptPlan in enumerate(self.intercept_plans.values()):
            BotRendering.render_intercept_plan(self, interceptPlan, colorIndex=i)

        # Tests/test_CityContestation.py::test_should_split_army_to_recapture_city_and_still_block_threat:
        # a tile that already donated a half-split to hold a threat block must keep its
        # remainder; flagging it defense-critical keeps every forward gather (city /
        # contestation / expansion) from sourcing it, so the only thing it can do is hold.
        # Done AFTER build_intercept_plans so these tiles do not enter the negTiles blocking
        # set (which would pin them even after the threat leaves). The pin survives a
        # couple turns past the tile's last blocking_tile_info sighting because the
        # checker flickers (a tile can drop out for a single turn while threats reroute);
        # it frees itself once the threat genuinely stops needing it.
        for garrisonTile in self.block_split_garrison_sources:
            if garrisonTile in self.blocking_tile_info:
                self.block_split_garrison_last_turn[garrisonTile] = self._map.turn
            if self._map.turn - self.block_split_garrison_last_turn.get(garrisonTile, -99) <= 2 and garrisonTile not in defenseCriticalTileSet:
                defenseCriticalTileSet.add(garrisonTile)
                logbook.info(f'DEFENSE_NEG_ADD source=block_split_garrison tile={str(garrisonTile)}')

        if not BotStateQueries.is_all_in(self) and not is_lag_move:
            with self.perf_timer.begin_move_event('Expansion quick check'):
                redoTimings = False
                if self.expansion_plan is None or self.timings is None or self._map.turn >= self.timings.nextRecalcTurn:
                    redoTimings = True

                negs = {t for t in defenseCriticalTileSet if not self._map.is_tile_on_team_with(t, self.targetPlayer)}
                logbook.info(f'DEFENSE_NEG_COPY context=quick_expansion_check source=defenseCriticalTileSet sourceTiles={[str(t) for t in defenseCriticalTileSet]} copiedTiles={[str(t) for t in negs]}')
                BotExpansionOps._add_expansion_threat_negs(self, negs)
                checkCityRoundEndPlans = self._map.is_army_bonus_turn
                with self.perf_timer.begin_move_event('quick kill city pre-expansion option'):
                    self.quick_kill_city_plan_option = None
                    quickKillNegs = defenseCriticalTileSet.copy()
                    logbook.info(f'DEFENSE_NEG_COPY context=quick_kill_city source=defenseCriticalTileSet copiedTiles={[str(t) for t in quickKillNegs]}')
                    quickKillNegs.update(self.cityAnalyzer.owned_contested_cities)
                    logbook.info(f'DEFENSE_NEG_UPDATE context=quick_kill_city source=owned_contested_cities addedTiles={[str(t) for t in self.cityAnalyzer.owned_contested_cities]} resultTiles={[str(t) for t in quickKillNegs]}')
                    self.quick_kill_city_plan_option = BotCityOps.get_quick_kill_on_enemy_cities_plan_option(self, quickKillNegs)
                with self.perf_timer.begin_move_event('capture_cities pre-expansion option'):
                    self.contest_city_plan_option = BotCityOps.get_city_contestation_plan_option(self)
                    self.city_capture_plan_option = BotCityOps.capture_cities_plan_option(
                        self,
                        negs,
                        includeContestOption=False,
                        ignoreContestSuppressionForNeutral=True,
                        preferNeutralCapture=True,
                    )
                self.expansion_plan = BotExpansionOps.build_expansion_plan(self, timeLimit=0.01, expansionNegatives=negs, pathColor=(150, 100, 150), includeExtraGenAndCityArmy=checkCityRoundEndPlans)

                self.capture_line_tracker.process_plan(self.targetPlayer, self.expansion_plan)

                if self.enemy_expansion_plan is not None:
                    with self.perf_timer.begin_move_event('WCA projected round loss check'):
                        self.win_condition_analyzer.force_kill_all_in_if_projected_round_loss(
                            self,
                            self.expansion_plan,
                            self.enemy_expansion_plan
                        )

                if redoTimings:
                    self.timings = BotTimings.get_timings(self)

        defenseSavePath: Path | None = None
        # Tests/test_GeneralTradeStrategy.py
        # test__e2e__all_in_losing_still_defends_unfavorable: a VALID mutual
        # general capture backup must still trigger the defense search even
        # when all_in_losing would otherwise skip it entirely - a viable
        # defense beats an unfavorable trade. Evaluated once before the
        # defense block so the fallback below can reuse it.
        mutualCaptureEval: GeneralTradeEvaluation | None = None
        if kingKillPath is not None and threat is not None and threat.threatType == ThreatType.Kill:
            mutualCaptureEval = BotCombatOps.evaluate_general_trade(self, kingKillPath, threat, threat.threatPlayer)
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # under a forced all-in or an active neutral-city economy priority, only a lethal
        # own-general Kill threat may trigger defense; econ/city/vision threats must not
        # preempt the attack/city branch.
        lethalGeneralThreat = (threat is not None and threat.threatType == ThreatType.Kill
                               and threat.path is not None and threat.path.tail is not None
                               and threat.path.tail.tile is not None and threat.path.tail.tile.isGeneral
                               and threat.path.tail.tile.player == self.general.player)
        ffaLethalDefenseOnly = ffaForcedTarget != -1 or ffaEndgameCityPriority
        # Tests/test_FFA.py::FFATests.test_should_defend_general_during_ffa_all_in:
        # FFA ALL_IN reuses is_all_in_losing as a forced-mode marker, so it cannot be the
        # defense-bypass test. A forced policy attack still evaluates a lethal own-general
        # threat; only true non-FFA losing all-ins (or no viable defense) may skip it.
        ffaForcedLethalDefense = ffaForcedTarget != -1 and lethalGeneralThreat
        if ((not ffaLethalDefenseOnly or lethalGeneralThreat)
                and threat is not None and threat.threatType != ThreatType.Vision
                and (not self.is_all_in_losing or ffaForcedLethalDefense
                     or (mutualCaptureEval is not None and not mutualCaptureEval.favorable))):
            with self.perf_timer.begin_move_event(f'THREAT DEFENSE {threat.turns} {str(threat.path.start.tile)}'):
                defenseMove, defenseSavePath = BotDefense.get_defense_moves(self, defenseCriticalTileSet, kingKillPath, raceChance)

                if defenseSavePath is not None:
                    self.viewInfo.color_path(PathColorer(defenseSavePath, 255, 100, 255, 200))
                if defenseMove is not None:
                    if not BotRepetition.detect_repetition(self, defenseMove, turns=6, numReps=3) or (threat.threatType == ThreatType.Kill and threat.path.tail.tile.isGeneral):
                        if defenseMove.source in self.largePlayerTiles and self.targetingArmy is None:
                            logbook.info(f'threatDefense overriding targetingArmy with {str(threat.path.start.tile)}')
                            self.targetingArmy = self.get_army_at(threat.path.start.tile)
                        if ffaForcedLethalDefense:
                            self.viewInfo.add_info_line(
                                f'FFA3 defend general during all-in target=p{ffaForcedTarget} '
                                f'threat=p{threat.threatPlayer}: {defenseMove}')
                        self.defense_override_move = True
                        return defenseMove
                    else:
                        self.viewInfo.add_info_line(f'BYPASSING DEF REP {str(defenseMove)} :(')
                elif ffaForcedLethalDefense:
                    self.viewInfo.add_info_line(
                        f'FFA3 no viable general defense vs p{threat.threatPlayer}; continue all-in p{ffaForcedTarget}')
        elif lethalGeneralThreat and self.is_all_in_losing:
            self.viewInfo.add_info_line(
                f'ALL_IN_LOSING bypass lethal defense vs p{threat.threatPlayer}')

        # Tests/test_GeneralTradeStrategy.py
        # test__e2e__unfavorable_trade_forced_survival_fallback: when a Kill
        # threat produced no adequate defense, a mutual general capture
        # backup (incl. an UNFAVORABLE general trade, which check_for_king
        # _kills deliberately returns at chance 0) is the only line where we
        # survive. Take it before the expansion/city branches below can burn
        # the source tile on a non-defensive move and before the
        # attackingWithSelectedExpansionPlan veto in the delayed block can
        # suppress it. Narrow to VALID evaluated mutual captures only so
        # ordinary chance-0 backup paths keep their old delayed ordering.
        if ((not ffaLethalDefenseOnly or lethalGeneralThreat)
                and kingKillPath is not None and threat is not None and threat.threatType == ThreatType.Kill
                and kingKillPath.start.next is not None
                and mutualCaptureEval is not None):
            blocks = self.blocking_tile_info.get(kingKillPath.start.tile)
            if not (blocks and kingKillPath.start.next.tile in blocks.blocked_destinations):
                self.info(f"    Survival mutual-capture fallback {str(kingKillPath)} (no adequate defense)")
                self.viewInfo.color_path(PathColorer(kingKillPath, 158, 158, 158, 255, 10, 200))
                # get_first_move preserves the evaluated path's move_half -
                # a half-move trade sends a different stack than a full move
                # and was priced accordingly
                self.defense_override_move = True
                return kingKillPath.get_first_move()

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # Forced ALL_IN routes committed/stealth/generic attack right after lethal general
        # defense and before any neutral-city pass-through; it never falls through to city
        # economy. ECONOMY with a reachable neutral city takes/gathers it here instead.
        ffaEndgameMode = BotFfaEndgame.get_mode(self)
        if ffaEndgameMode == BotFfaEndgame.FfaEndgameMode.ALL_IN:
            return BotFfaEndgame.get_attack_move(self, threat, defenseCriticalTileSet, kingKillPath, raceChance)
        if ffaEndgameMode == BotFfaEndgame.FfaEndgameMode.ECONOMY and ffaEndgameCityPriority:
            economyMove = BotFfaEndgame.get_move(self)
            if economyMove is not None:
                return economyMove
            # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
            # a reachable neutral city exists but capture/gather is not ready: deliberately wait
            # rather than fall through to unrelated offense while city priority remains active.
            return None

        # While a certified FFA kill-gather is committed, every nondefensive move must be a
        # literal gather/launch/search/finish step - skip the unrelated expansion/opportunism
        # returns below so they cannot waste the execution window. Defense gates (THREAT
        # DEFENSE, survival fallback, DANGER TILES, flank defense, city-preemptive) still run
        # first and keep priority; the committed move itself is issued after city-preemptive.
        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible
        ffaKillGatherCommitted = BotFfaKillGather.is_committed(self)

        if self._map.turn < 100 and not ffaKillGatherCommitted and not generalSafetyReserving:
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

        if self._map.turn < 50 and not ffaKillGatherCommitted and not generalSafetyReserving:
            if not self._map.is_low_cost_city_game and not self._map.modifiers_by_id[MODIFIER_CITY_STATE]:
                return BotExpansionOps.make_first_25_move(self)
            else:
                self.info(f'Byp f25 bc weird_custom {self.is_weird_custom} (walled_city {self._map.is_walled_city_game} or low_cost_city {self._map.is_low_cost_city_game}) or cityState {self._map.modifiers_by_id[MODIFIER_CITY_STATE]}')

        if self._map.turn < 250 and self._map.remainingPlayers > 3 and not ffaKillGatherCommitted and not generalSafetyReserving:
            with self.perf_timer.begin_move_event('Ffa Turtle Move'):
                move = BotExpansionOps.look_for_ffa_turtle_move(self)
            if move is not None:
                return move
        if self.expansion_plan:
            for t in self.expansion_plan.blocking_tiles:
                if t not in defenseCriticalTileSet:
                    logbook.info(f'DEFENSE_NEG_ADD source=expansion_plan.blocking_tiles tile={t}')
                    defenseCriticalTileSet.add(t)
                    self.viewInfo.add_info_line(f'{t} added to defense crit from expPlan.blocking')

        if self.win_condition_analyzer.defend_cities:
            for t in self.win_condition_analyzer.defend_cities:
                if t not in defenseCriticalTileSet:
                    logbook.info(f'DEFENSE_NEG_ADD source=win_condition_analyzer.defend_cities tile={t}')
                    defenseCriticalTileSet.add(t)
        if self.win_condition_analyzer.most_forward_defense_city and self.armyTracker.has_player_seen(self.targetPlayer, self.win_condition_analyzer.most_forward_defense_city):
            closeToEnemyThresh = self.board_analysis.inter_general_distance * 2 / 3
            forwardCityDistToEnemy = self.board_analysis.intergeneral_analysis.bMap.raw[self.win_condition_analyzer.most_forward_defense_city.tile_index]
            if self.win_condition_analyzer.most_forward_defense_city not in defenseCriticalTileSet and closeToEnemyThresh > forwardCityDistToEnemy:
                logbook.info(f'DEFENSE_NEG_ADD source=win_condition_analyzer.most_forward_defense_city tile={self.win_condition_analyzer.most_forward_defense_city}')
                defenseCriticalTileSet.add(self.win_condition_analyzer.most_forward_defense_city)

        # Note: defensive spanning trees are now calculated early in init_turn() for win condition analysis
        # This later calculation incorporates defenseCriticalTileSet and expansion plan blocking tiles
        if self._map.is_army_bonus_turn or self.defensive_spanning_tree is None:
            with self.perf_timer.begin_move_event('defensive spanning trees with defense critical'):
                # Main spanning tree using cities_in_play (centralized defense)
                self.defensive_spanning_tree = BotDefense._get_defensive_spanning_tree(
                    self, defenseCriticalTileSet, BotGatherOps.get_gather_tiebreak_matrix(self), use_cities_in_play_only=True, require_min_distance=True
                )
                # Secondary spanning tree using ALL friendly cities (broader coverage)
                self.friendly_city_spanning_tree = BotDefense._get_defensive_spanning_tree(
                    self, defenseCriticalTileSet, BotGatherOps.get_gather_tiebreak_matrix(self), use_cities_in_play_only=False
                )

                self.viewInfo.add_targeted_tiles_with_legend(self.defensive_spanning_tree, 'DefenseTree', TargetStyle.WHITE, radiusReduction=-1)

        BotCentralDefense.calculate_central_defense_point_if_needed(self)
        if self.board_analysis.central_defense_point is not None:
            self.viewInfo.add_targeted_tile(self.board_analysis.central_defense_point, TargetStyle.TEAL, radiusReduction=2)

        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible
        # ThreatType.Kill is URGENT DEFENSE (an enemy is killing our general) - the
        # delayed defense kingKillPath is a legitimate survival trade, NOT the
        # unrelated opportunism the kill-gather commit suppresses, so it must NOT be
        # gated by ffaKillGatherCommitted. Defense always keeps priority over the
        # committed offense move issued later. `threat is not None` matches the
        # sibling kingKill guards above - kingKillPath can be non-None while threat
        # is None (e.g. late FFA), which previously crashed on threat.threatType.
        # Tests/test_GeneralPrediction.py::GeneralPredictionTests.test_should_infer_bottom_right_spawn_from_emergence_direction:
        # while a stealth all-in / undefendable hunt is in scope the stealth planner owns
        # the forward stack's direction. This fallback's kingKillPath is a SEPARATE
        # PivotIterativeWRP tour over the same candidates, so its first step can pick the
        # opposite direction from the route stealth commits a turn later (once moved the
        # 115-stack down 15,7->15,8 here, then the committed route walked it back up
        # 15,8->15,7->15,6 - the down-then-up flip-flop). Suppress the fallback while the
        # stealth planner can engage; the survival mutual-capture fallback above stays
        # ungated and committed-route defense interrupts still fire.
        # determine_should_winning_all_in has hysteresis, so is_all_in_army_advantage can
        # hold True for a turn mid-episode and release the stack to this tour for exactly
        # one step before stealth re-engages - the same flip-flop through a narrower door
        # (observed at t291: 15,7->15,8 then committed 15,8->15,7). The gate therefore keys
        # on the episode OWNING THE TILE, not on the active predicates.
        stealthPlannerOwnsDiveStack = False
        if kingKillPath is not None and threat is not None and threat.threatType == ThreatType.Kill:
            # The fallback may still fire on OTHER stacks during a losing episode - only the
            # tile the stealth planner actually owns is reserved. Pre-state the dive candidate
            # set is exactly _get_forward_dive_stack's eligibility filter (own non-general
            # tiles with army > predicted fog general army): if this path's start tile is
            # dive-eligible, moving it lets the QK tour order the same candidates differently
            # and the stealth route then walks it back (down->up->down flip-flop).
            stealthDiveTile: Tile | None = None
            if self.stealth_all_in is not None:
                if (self.stealth_all_in.committed_route is not None
                        and self.stealth_all_in.committed_route.start is not None):
                    stealthDiveTile = self.stealth_all_in.committed_route.start.tile
                else:
                    stealthDiveTile = self.stealth_all_in.launch_tile
            else:
                # (losing or not advantage) covers BOTH transient-flag flickers: a losing
                # episode holding through a one-turn advantage=True, and the not-losing
                # undefendable-hunt window (hunt itself requires not advantage). Only a
                # genuine winning-advantage turn lets the fallback take the dive stack.
                stealthEpisodeInScope = (
                    self.enable_stealth_all_in
                    and not self.targetPlayerExpectedGeneralLocation.isGeneral
                    and self.targetPlayer != -1
                    and not BotStateQueries.is_still_ffa_and_non_dominant(self)
                    and (self.is_all_in_losing or not self.is_all_in_army_advantage))
                if stealthEpisodeInScope:
                    predictedGenArmy = max(
                        1,
                        self.opponent_tracker.get_current_cycle_stats_by_player(
                            self.targetPlayer).approximate_fog_army_available_total)
                    if (kingKillPath.start.tile.army > predictedGenArmy
                            and not kingKillPath.start.tile.isGeneral):
                        stealthDiveTile = kingKillPath.start.tile
            stealthPlannerOwnsDiveStack = (
                stealthDiveTile is not None
                and kingKillPath.start.tile == stealthDiveTile)
            if stealthPlannerOwnsDiveStack:
                logbook.info(
                    f'DELAYED_DEF_KK_GATE turn={self._map.turn} suppressed diveStack={stealthDiveTile} '
                    f'kkStart={kingKillPath.start.tile} losing={self.is_all_in_losing} '
                    f'advantage={self.is_all_in_army_advantage} stealthState={self.stealth_all_in is not None}')
        if (kingKillPath is not None and threat is not None and threat.threatType == ThreatType.Kill
                and not stealthPlannerOwnsDiveStack):
            attackingWithSavePath = defenseSavePath is not None and defenseSavePath.start.tile == kingKillPath.start.tile
            attackingWithSelectedExpansionPlan = (
                    self.expansion_plan is not None
                    and self.expansion_plan.selected_option is not None
                    and self.expansion_plan.selected_option.start is not None
                    and self.expansion_plan.selected_option.start.tile == kingKillPath.start.tile
            )
            attackingWithRestrictedArmyMovement = False
            blocks = self.blocking_tile_info.get(kingKillPath.start.tile)
            if blocks:
                if kingKillPath.start.next.tile in blocks.blocked_destinations:
                    attackingWithRestrictedArmyMovement = True
            if not attackingWithSavePath and not attackingWithSelectedExpansionPlan and not attackingWithRestrictedArmyMovement:
                if defenseSavePath is not None:
                    logbook.info(f"savePath was {str(defenseSavePath)}")
                else:
                    logbook.info("savePath was NONE")
                threatInf = ''
                if threat is not None:
                    threatInf = f' @{threat.path.start.tile}->{threat.path.tail.tile}'
                self.info(f"    Delayed defense kingKillPath{threatInf}.  {str(kingKillPath)}")
                self.viewInfo.color_path(PathColorer(kingKillPath, 158, 158, 158, 255, 10, 200))

                self.defense_override_move = True
                return Move(kingKillPath.start.tile, kingKillPath.start.next.tile)
            else:
                if defenseSavePath is not None:
                    logbook.info(f"savePath was {str(defenseSavePath)}")
                else:
                    logbook.info("savePath was NONE")
                logbook.info(
                    f"savePath or expansion plan tile was also kingKillPath tile, skipped kingKillPath {str(kingKillPath)}")

        # with self.perf_timer.begin_move_event('ARMY SCRIMS'):
        #     armyScrimMove = BotCombatOps.check_for_army_movement_scrims(self)
        #     if armyScrimMove is not None:
        #         # already logged
        #         return armyScrimMove

        with self.perf_timer.begin_move_event('DANGER TILES'):
            dangerTileKillMove = BotDefense.check_for_danger_tile_moves(self)
            if dangerTileKillMove is not None:
                self.defense_override_move = True
                return dangerTileKillMove  # already logged to info

        with self.perf_timer.begin_move_event('Flank defense / Vision expansion HIGH PRI'):
            flankDefMove = BotExplorationOps.find_flank_defense_move(self, defenseCriticalTileSet, highPriority=True)
            if flankDefMove:
                if self.timings.in_gather_split(self._map.turn):
                    self.timings.splitTurns += 1
                    if self.timings.splitTurns > self.timings.launchTiming:
                        self.timings.launchTiming = self.timings.splitTurns
                self.defense_override_move = True
                return flankDefMove

        fog_risk, fog_army_comp, city_comp, expected_city_spanning_offset = self.opponent_tracker.get_immediate_fog_risk(self.targetPlayer, len(self.friendly_city_spanning_tree))

        # we were prioritizing shuffling around between enemy cities rather than defending against an all in in an already won position
        # if not self.is_all_in_losing and (self.win_condition_analyzer.basic_defense_general_army > fog_risk or (WinCondition.DefendContestedFriendlyCity not in self.win_condition_analyzer.viable_win_conditions and WinCondition.DefendEconomicLead not in self.win_condition_analyzer.viable_win_conditions)):
        #     with self.perf_timer.begin_move_event('get_quick_kill_on_enemy_cities'):
        #         negs = defenseCriticalTileSet.copy()
        #         negs.update(self.cityAnalyzer.owned_contested_cities)
        #         path = BotCityOps.get_quick_kill_on_enemy_cities(self, negs)
        #     if path is not None:
        #         self.info(f'Quick Kill on enemy city: {str(path)}')
        #         self.curPath = path
        #         if self.curPath.length > 1:
        #             self.curPath = self.curPath.get_subsegment(path.length - 2)
        #         move = BotPathingUtils.get_first_path_move(self, path)
        #         if not BotRepetition.detect_repetition(self, move):
        #             return move

        # Tests/test_AllIn.py::test_should_keep_timed_all_in_over_far_gathers
        # A timed all-in / cyclic winning gather intentionally positions army far
        # from the shortest inter-general path; FFG must not override it even if
        # force_far_gathers was left enabled from an earlier turn.
        if self.force_far_gathers and self.force_far_gathers_turns > 0 \
                and not ffaKillGatherCommitted \
                and not generalSafetyReserving \
                and not BotStateQueries.is_timed_all_in_or_cyclic_active(self):
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
                minTurns = roughTurns - 10
                maxTurns = roughTurns + 10

                if isinstance(self.curPath, GatherCapturePlan):
                    firstMove = self.curPath.get_first_move()

                    if firstMove is not None and firstMove.source.isSwamp or maxTurns >= self.curPath.length >= minTurns:
                        self.info(f'CONTINUING FFG ({self.force_far_gathers_turns}t) maxTurns {maxTurns} >= curPath.length {self.curPath.length} >= minTurns {minTurns}')
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

        if not self.is_weird_custom and not ffaKillGatherCommitted and not generalSafetyReserving:
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
                    if largestAdjTile and (largestAdjTile.army - 1 > annoyingTile.army):
                        nukeMove = Move(largestAdjTile, annoyingTile)
                        self.info(f'Nuking general-adjacent vision tile {str(nukeMove)}, targeting it as targeting army.')
                        self.targetingArmy = self.get_army_at(annoyingTile)
                        self.defense_override_move = True
                        return nukeMove

        afkPlayerMove = None if (ffaKillGatherCommitted or generalSafetyReserving) else BotExplorationOps.get_move_if_afk_player_situation(self)
        if afkPlayerMove:
            return afkPlayerMove

        BotPathingUtils.check_cur_path(self)

        # needs to happen before defend_economy because defend_economy uses the properties set by this method.
        BotDefense.check_fog_risk(self, )

        # if ahead on economy, but not %30 ahead on army we should play defensively
        self.defend_economy = BotDefense.should_defend_economy(self, defenseCriticalTileSet)

        self.approximate_greedy_turns_avail = BotTimings.calculate_greedy_turns_available(self)

        if WinCondition.DefendContestedFriendlyCity in self.win_condition_analyzer.viable_win_conditions:
            with self.perf_timer.begin_move_event(f'Getting city preemptive defense {str(self.win_condition_analyzer.defend_cities)}'):
                cityDefenseMove = BotCityOps.get_city_preemptive_defense_move(self, defenseCriticalTileSet)
            if cityDefenseMove is not None:
                self.info(f'City preemptive defense move! {str(cityDefenseMove)}')
                self.defense_override_move = True
                return cityDefenseMove

        # BotGeneralSafety reserve gather. Reached only after THREAT DEFENSE,
        # survival fallback, DANGER TILES, flank defense, and city-preemptive
        # defense have all had priority; every earlier nondefensive return was
        # skipped while a stage is unmet. A handled result with move=None is a
        # deliberate wait/pass; READY falls through so normal offense resumes
        # with the anchor still protected by negatives + the final guard.
        safetyResult = BotGeneralSafety.get_move(self, defenseCriticalTileSet)
        if safetyResult.handled:
            if safetyResult.move is not None:
                self.info(f'GENERAL SAFETY {safetyResult.reason} {safetyResult.move}')
                return safetyResult.move
            return None

        # Offensive consumers below get defenseCriticalTileSet UNION the
        # reserved anchor + remaining owned gather sources so offense plans
        # cannot spend the reservation. Defense inputs above keep the original
        # set - defense is supposed to use the reserved army. Identical to
        # defenseCriticalTileSet while the feature is off or fully READY with
        # no remaining sources.
        offenseNegativeTileSet = BotGeneralSafety.offense_negatives(self, defenseCriticalTileSet)

        # Committed FFA kill-gather execution. Reached only after THREAT DEFENSE,
        # survival fallback, DANGER TILES, flank defense, and city-preemptive defense
        # have all had priority; every earlier nondefensive return was skipped while
        # committed. A handled result with move=None is a deliberate wait/pass; an
        # abort clears state and falls through to normal selection below.
        # Tests/test_FFA.py::FFATests.test_should_all_in_nearby_players_as_fast_as_possible
        if ffaKillGatherCommitted:
            committedResult = BotFfaKillGather.get_committed_move(self, defenseCriticalTileSet)
            if committedResult.handled:
                if committedResult.move is not None:
                    self.info(f'FFA KILL GATHER {committedResult.reason} {committedResult.move}')
                    return committedResult.move
                return None

        if self.expansion_plan and self.expansion_plan.selected_option is not None:
            selectedCityOption = self.expansion_plan.selected_option
            selectedTargetCity = None
            if isinstance(selectedCityOption, GatherCapturePlan):
                selectedTargetCity = selectedCityOption.gather_target
            else:
                selectedTargetCity = selectedCityOption.tail.tile
                if selectedTargetCity is None and selectedCityOption.tail.prev is not None:
                    self.info(f"BUG BUG BUG expansion plan selected option tail had no tile {selectedCityOption}")
                    selectedTargetCity = selectedCityOption.tail.prev.tile
            cityCaptureTarget = None
            if self.city_capture_plan_option is not None:
                if isinstance(self.city_capture_plan_option, GatherCapturePlan):
                    cityCaptureTarget = self.city_capture_plan_option.gather_target
                else:
                    cityCaptureTarget = self.city_capture_plan_option.tail.tile
            contestCityTarget = None
            if self.contest_city_plan_option is not None:
                if isinstance(self.contest_city_plan_option, GatherCapturePlan):
                    contestCityTarget = self.contest_city_plan_option.gather_target
                else:
                    contestCityTarget = self.contest_city_plan_option.tail.tile
            quickKillTarget = None
            if self.quick_kill_city_plan_option is not None:
                if isinstance(self.quick_kill_city_plan_option, GatherCapturePlan):
                    quickKillTarget = self.quick_kill_city_plan_option.gather_target
                else:
                    quickKillTarget = self.quick_kill_city_plan_option.tail.tile
            selectedMatchesCityOption = (
                    selectedCityOption is self.city_capture_plan_option
                    or selectedCityOption is self.contest_city_plan_option
                    or selectedCityOption is self.quick_kill_city_plan_option
                    or selectedTargetCity is not None and selectedTargetCity == cityCaptureTarget
                    or selectedTargetCity is not None and selectedTargetCity == contestCityTarget
                    or selectedTargetCity is not None and selectedTargetCity == quickKillTarget
            )
            move = selectedCityOption.get_first_move()
            if selectedMatchesCityOption and move is not None and not BotRepetition.detect_repetition(self, move):
                targetCity = selectedTargetCity
                if targetCity is not None and (targetCity.isCity or targetCity.isGeneral):
                    self.info(f'Pass thru EXP city option! {move} targeting {targetCity}')
                    if targetCity is None:
                        self.info(f"BUG BUG BUG expansion plan selected option tail had no tile {selectedCityOption}")
                        return None
                    if targetCity.isNeutral:
                        self.cityAnalyzer.last_targeted_neut_city = targetCity
                    return move

        # with self.perf_timer.begin_move_event(f'capture_cities'):
        #     (cityPath, gatherMove) = BotCityOps.capture_cities(self, defenseCriticalTileSet)
        # if gatherMove is not None:
        #     logbook.info(f"{self.get_elapsed()} returning capture_cities gatherMove {str(gatherMove)}")
        #     if cityPath is not None:
        #         self.curPath = cityPath
        #     return gatherMove
        # elif cityPath is not None:
        #     logbook.info(f"{self.get_elapsed()} returning capture_cities cityPath {str(cityPath)}")
        #     # self.curPath = cityPath
        #     return BotPathingUtils.get_first_path_move(self, cityPath)

        # AFTER city capture because of test_should_contest_city_not_intercept_it. If this causes problems, then NEED to feed city attack/defense into the RoundPlanner and stop this hacky order shit...
        if self.expansion_plan and self.expansion_plan.includes_intercept and not self.is_all_in_losing and not self.win_condition_analyzer.projected_loss_all_in_active:
            move = self.expansion_plan.selected_option.get_first_move()
            if not BotRepetition.detect_repetition(self, move):
                self.info(f'Pass thru EXP int! {move} {self.expansion_plan.selected_option}')
                return move

        # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
        # run hidden gathering before exploration and immediately execute any newly committed route.
        if (not stealthRouteAborted
                and BotStealthAllIn.is_stealth_all_in_active(self)
                and (self.stealth_all_in is None
                     or self.stealth_all_in.committed_route is None)):
            stealthMove = BotStealthAllIn.get_stealth_all_in_move(
                self,
                offenseNegativeTileSet)
            if stealthMove is not None:
                return stealthMove
            if (self.stealth_all_in is not None
                    and self.stealth_all_in.committed_route is not None
                    and self.stealth_all_in.committed_turn == self._map.turn):
                committedMove = BotStealthAllIn.get_committed_route_move(
                    self,
                    threat,
                    defenseCriticalTileSet,
                    kingKillPath,
                    raceChance)
                if committedMove is not None:
                    return committedMove
                stealthRouteAborted = self.stealth_all_in is None

        with self.perf_timer.begin_move_event('try_get_enemy_territory_exploration_continuation_move'):
            expNegs = set(offenseNegativeTileSet)
            logbook.info(f'DEFENSE_NEG_COPY context=enemy_territory_exploration_continuation source=offenseNegativeTileSet copiedTiles={[str(t) for t in expNegs]}')
            if WinCondition.DefendEconomicLead in self.win_condition_analyzer.viable_win_conditions:
                for t in self.win_condition_analyzer.defend_cities:
                    if t not in expNegs:
                        logbook.info(f'DEFENSE_NEG_ADD context=enemy_territory_exploration_continuation source=defend_cities tile={t}')
                        expNegs.add(t)
                for t in self.win_condition_analyzer.contestable_cities:
                    if t not in expNegs:
                        logbook.info(f'DEFENSE_NEG_ADD context=enemy_territory_exploration_continuation source=contestable_cities tile={t}')
                        expNegs.add(t)
            largeArmyExpContinuationMove = BotExplorationOps.try_get_enemy_territory_exploration_continuation_move(self, expNegs)

        if largeArmyExpContinuationMove is not None and not BotRepetition.detect_repetition(self, largeArmyExpContinuationMove):
            # already logged
            return largeArmyExpContinuationMove

        projectedLossAllInMove = BotKillTiming.get_projected_loss_all_in_move(self, offenseNegativeTileSet)
        if projectedLossAllInMove is not None:
            return projectedLossAllInMove

        if 50 <= self._map.turn < 75:
            move = BotExpansionOps.try_gather_tendrils_towards_enemy(self)
            if move is not None:
                return move

        if self.win_condition_analyzer.projected_loss_all_in_active:
            self.curPath = None

        if self.curPath is not None:
            (foundMove, move) = BotPathingUtils.continue_cur_path(self, threat, defenseCriticalTileSet)
            if foundMove:
                return move  # already logged

        exploreMove = BotExplorationOps.try_find_exploration_move(self, offenseNegativeTileSet)
        if exploreMove is not None:
            return exploreMove  # already logged

        allInMove = BotCombatOps.get_all_in_move(self, offenseNegativeTileSet)
        if allInMove:
            # already logged
            return allInMove

        # Tests/test_BotBehavior.py::BotBehaviorTests.test_should_attack_early_without_gather_repetition
        # (QaFHRLrxn t213) + UnitTests/test_BotExpansionOps.py::BotExpansionOpsDefensiveFlowPathTests:
        # likely_kill_push flickers as our own gathered army grows; while a stable defensive
        # corridor exists, iterative flow expansion may still run so the planner does not
        # alternate between skipping and entering expansion (which pulled the stack back off
        # the corridor -> 5,17 repetition, first attack t237 vs proof t222). The helper
        # returns None for non-iterative flow, so legacy flow stays suppressed under LKP.
        # Defense priority, all-in, and emergency intercept handling are unchanged.
        if not self.defend_economy and (not self.likely_kill_push or BotExpansionOps.get_defensive_flow_path(self) is not None):
            expMove = BotExpansionOps.try_find_main_timing_expansion_move_if_applicable(self, offenseNegativeTileSet)
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
                    negativeTiles=offenseNegativeTileSet,
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
            flankDefMove = BotExplorationOps.find_flank_defense_move(self, defenseCriticalTileSet, highPriority=False)
            if flankDefMove:
                if self.timings.in_gather_split(self._map.turn):
                    self.timings.splitTurns += 1
                    if self.timings.splitTurns > self.timings.launchTiming:
                        self.timings.launchTiming = self.timings.splitTurns
                self.defense_override_move = True
                return flankDefMove

        # if self.defend_economy:
        #     move = BotCombatOps.try_find_army_out_of_position_move(self, defenseCriticalTileSet)
        #     if move is not None:
        #         return move  # already logged

        cyclicAllInMove = BotCombatOps.try_get_cyclic_all_in_move(self, offenseNegativeTileSet)
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

        expMove = BotExpansionOps._get_expansion_plan_quick_capture_move(self, offenseNegativeTileSet)
        if expMove:
            self.info(f"quickCap move {expMove}")
            return expMove

        with self.perf_timer.begin_move_event(f'MAIN GATHER OUTER, negs {[str(t) for t in offenseNegativeTileSet]}'):
            gathMove = BotGatherOps.try_find_gather_move(self, threat, offenseNegativeTileSet, self.leafMoves, needToKillTiles)

        if gathMove is not None:
            # already logged / perf countered internally
            return gathMove

        isFfaAfkScenario = self._map.remainingCycleTurns > 14 and BotStateQueries.is_still_ffa_and_non_dominant(self) and self._map.cycleTurn < self.timings.launchTiming and not self._map.is_walled_city_game
        if isFfaAfkScenario:
            self.info(f'FFA AFK')
            return None

        # NOTE NOTHING PAST THIS POINT CAN TAKE ANY EXTRA TIME

        if self.expansion_plan and self.expansion_plan.selected_option:
            deferred = []
            deferring = False
            if self.expansion_plan.turns_used < self._map.remainingCycleTurns - 1:
                deferring = True

            move = self.expansion_plan.selected_option.get_first_move()
            if move is not None:
                if move.source.player == self._map.player_index and move.source.army > 1 and BotPathingUtils.is_move_safe_valid(self, move):
                    self.info(f'Fallback to selected expansion plan opt {self.expansion_plan.selected_option}: {move}')
                    return move
                logbook.info(
                    f'Skipping stale selected expansion plan opt {self.expansion_plan.selected_option}: {move} '
                    f'sourcePlayer={move.source.player} sourceArmy={move.source.army} '
                    f'destPlayer={move.dest.player} destArmy={move.dest.army}')


            for opt in self.expansion_plan.all_paths:
                move = opt.get_first_move()
                if move is not None and move.source.player == self._map.player_index and move.source.army > 1:
                    if deferring and SearchUtils.any_where(opt.tileList, lambda t: t.player == self._map.player_index and (t.isGeneral or t.isCity)):
                        self.info(f'Deferred exp opt {opt} due to gen/city movement')
                        deferred.append(move)
                    else:
                        self.info(f'Fallback Fallback move using expansion plan opt {opt}: {move}')
                        return move
            if deferred:
                self.info(f'Playing deferred opt {deferred[0]} because no non-deferred found')
                return deferred[0]

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
                negatives = offenseNegativeTileSet.copy()
                negatives.update(self.target_player_gather_targets)
                # Tests/test_AllIn.py::test_should_not_idle_during_projected_loss_all_in_with_uncertain_enemy_general
                # launchTiming - turnInCycle goes negative once the cycle is past
                # launch; roll the horizon to the NEXT launch so the emergency
                # gather always gets a positive turn budget instead of depth<=0.
                turns = max(1, (self.timings.launchTiming - self.timings.get_turn_in_cycle(self._map.turn)) % self.timings.cycleTurns)
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
                # BotGeneralSafety (Tests/test_FFA.py t179 general-safety cases):
                # stamp the turn each enemy (and same-team player) first learns our
                # general location so general-safety episodes trigger only on a FRESH
                # reveal. Old fixtures loading knowsKingLocation=True directly never
                # transition here and keep king_location_revealed_turn=-1 (no-op).
                revealedPlayers = [self._map.players[tile.player]]
                if self._map.teams is not None:
                    revealedPlayers = [
                        teamPlayer for teamPlayer in self._map.players
                        if self._map.teams[teamPlayer.index] == self._map.teams[tile.player]]
                for revealPlayer in revealedPlayers:
                    wasKnown = revealPlayer.knowsKingLocation
                    revealPlayer.knowsKingLocation = True
                    if not wasKnown and revealPlayer.king_location_revealed_turn == -1:
                        revealPlayer.king_location_revealed_turn = self._map.turn

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

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # Refresh the endgame policy BEFORE the exclusive-lock/unattackable queries below so they
        # see this turn's mode/target; city-priority evaluation is deferred to the authoritative
        # pre-pick refresh so the expensive neutral-city path search runs only once per turn.
        BotFfaEndgame.update_policy(self, evaluateCityPriority=False)

        # Tests/test_FFA.py::test_should_not_attack_unprovoked_enemies_in_early_ffa: refresh the
        # exclusive-FFA lock BEFORE scanning leaf/city moves and BEFORE target recalculation below,
        # so every producer this turn agrees on which revealed enemies are unattackable.
        BotStateQueries.update_ffa_exclusive_target_lock(self)
        ffaUnattackablePlayers = BotStateQueries.get_ffa_unattackable_players(self)

        # Tests/test_FFA.py::test_should_snap_kill_nearby_ffa_general_after_enemy_army_loss:
        # when the exclusive lock is an enemy whose general location is unknown, seed
        # largeTilesNearEnemyKings with a representative predicted-general candidate (already
        # owned by the locked player in the fog prediction, added as-is) so the quick-kill
        # evaluator below checks that inferred target instead of only the possibly unrelated
        # targetPlayerExpectedGeneralLocation entry added above.
        lockedTargetPlayer = self.ffa_exclusive_target_lock
        if lockedTargetPlayer != -1:
            lockedTargetGeneral = self._map.generals[lockedTargetPlayer]
            if (lockedTargetGeneral is None or not lockedTargetGeneral.isGeneral) and self.alt_en_gen_positions[lockedTargetPlayer]:
                inferredGeneralTile = self.alt_en_gen_positions[lockedTargetPlayer][0]
                if inferredGeneralTile.player == lockedTargetPlayer and inferredGeneralTile not in self.largeTilesNearEnemyKings:
                    self.largeTilesNearEnemyKings[inferredGeneralTile] = []

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
                        # Tests/test_FFA.py FFA pacifism tests: leaf moves are non-attack expansion
                        # moves and must never capture tiles of unattackable revealed enemies.
                        if ffaUnattackablePlayers is not None and nextTile.player in ffaUnattackablePlayers:
                            continue
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
                    # Tests/test_FFA.py FFA pacifism tests: unattackable enemies' cities are not
                    # valid capture targets for city kill/contest plans either.
                    if ffaUnattackablePlayers is not None and tile.player in ffaUnattackablePlayers:
                        continue
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

        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # Refresh the 3-player FFA endgame policy now that general approximations are current
        # so calculate_target_player below and the unattackable-player query see this turn's mode.
        # City-priority evaluation is deferred to the single authoritative pre-pick refresh.
        BotFfaEndgame.update_policy(self, evaluateCityPriority=False)

        # UnitTests/test_TargetPlayerRetargeting.py::TargetPlayerRetargetingTests covers dead-target retargeting and all-in reset here because stale all-in state must not survive changing from a killed FFA target to their living teammate or a newly calculated target.
        oldTgPlayer = self.targetPlayer
        self.targetPlayer = self._calculate_target_player_considering_dead_current_target()
        self.opponent_tracker.targetPlayer = self.targetPlayer

        self.targetPlayerObj = self._map.players[self.targetPlayer]

        if self.targetPlayer != oldTgPlayer:
            if oldTgPlayer != -1:
                self._reset_all_in_state_after_target_player_change(oldTgPlayer, self.targetPlayer)
                # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
                # the target reset above clears the forced all-in flags; re-assert the endgame
                # policy immediately so target-relative state stays consistent until the
                # authoritative pre-pick refresh re-evaluates city priority.
                BotFfaEndgame.update_policy(self, evaluateCityPriority=False)
            self._lastTargetPlayerCityCount = 0
            if self.targetPlayer >= 0:
                self._lastTargetPlayerCityCount = self.opponent_tracker.get_current_team_scores_by_player(self.targetPlayer).cityCount

        self.captureLeafMoves = BotExpansionOps.prioritize_expansion_leaves(self, self.captureLeafMoves, distPriorityMap=self.board_analysis.shortest_path_distances)

    def _calculate_target_player_considering_dead_current_target(self) -> int:
        """Return the next target player, preferring the current dead target's living teammate before normal targeting."""
        if self.targetPlayer != -1 and self._map.players[self.targetPlayer].dead:
            livingTeammate = self._get_living_teammate_for_dead_target_player(self.targetPlayer)
            if livingTeammate != -1:
                return livingTeammate

        return BotTargeting.calculate_target_player(self)

    def _get_living_teammate_for_dead_target_player(self, deadTargetPlayer: int) -> int:
        """Return a living enemy teammate for a dead target player, or -1 when none is available."""
        targetTeam = self._map.team_ids_by_player_index[deadTargetPlayer]
        for player in self._map.players:
            if player.index == deadTargetPlayer:
                continue
            if player.index == self.general.player or player.index in self._map.teammates:
                continue
            if player.dead:
                continue
            if self._map.team_ids_by_player_index[player.index] == targetTeam:
                return player.index

        return -1

    def _reset_all_in_state_after_target_player_change(self, oldTargetPlayer: int, newTargetPlayer: int) -> None:
        """Clear target-specific all-in state after moving from one target player to another."""
        logbook.info(
            f'ALL_IN_TARGET_RESET turn={self._map.turn} '
            f'oldTargetPlayer={oldTargetPlayer} newTargetPlayer={newTargetPlayer} '
            f'oldTargetDead={self._map.players[oldTargetPlayer].dead} '
            f'is_all_in_losing={self.is_all_in_losing} '
            f'is_all_in_army_advantage={self.is_all_in_army_advantage} '
            f'all_in_city_behind={self.all_in_city_behind} '
            f'projected_loss_all_in_active={self.win_condition_analyzer.projected_loss_all_in_active}'
        )
        self.is_all_in_losing = False
        self.all_in_losing_counter = 0
        self.is_all_in_army_advantage = False
        self.all_in_army_advantage_counter = 0
        self.all_in_city_behind = False
        self.win_condition_analyzer.projected_loss_all_in_active = False
        self.win_condition_analyzer.projected_loss_all_in_target = None
        self.win_condition_analyzer.all_in_plan = None
        self.shortest_path_to_target_player = None
        self.target_player_gather_path = None
        self.target_player_gather_targets = None
        # Tests/test_AllIn.py::AllInTests.test_should_stealth_flank_all_in_when_enemy_general_unknown:
        # discard pending target-specific gathers but leave an already committed route untouched.
        BotStealthAllIn.clear_uncommitted_state(self)
        # Tests/test_AllIn.py::AllInTests.test_should_commit_wrp_hunt_when_enemy_cannot_defend:
        # discard WRP jobs that were planned for the previous target player.
        BotStealthAllIn.clear_pending_hunt_job(self)
        self.stealth_hunt_excluded_start_tile_indexes.clear()
        self.stealth_all_in_cannot_kill_counter = 0
        # Tests/test_AllIn.py::AllInTests.test_should_continue_committed_kill_attack_instead_of_slow_gather:
        # a committed kill attack against the old target is meaningless for the new one.
        self.committed_quick_kill = None
        self.committed_quick_kill_cutoff = 0


    # STEP2: Stay in EklipZBotV2.py or move to a dedicated resume/debug module late. This restores broad bot/runtime state across trackers, timings, paths, and debug serialization.
    def load_resume_data(self, resume_data: typing.Dict[str, str], skip_island_restore: bool = False):
        result = BotSerialization.load_resume_data(self, resume_data, skip_island_restore=skip_island_restore)
        # Tests/test_AllIn.py resume support: a committed WRP route saved mid-all-in must keep
        # executing after load; restored here (not inside BotSerialization) to avoid a module cycle.
        BotStealthAllIn.load_committed_route_from_resume_data(self, resume_data)
        # FFA kill-gather committed state resumes the same literal schedule.
        BotFfaKillGather.load_state(self, resume_data)
        # General-safety reservation episodes/anchor/gather resume likewise;
        # missing fields in old fixtures restore the default inactive state.
        BotGeneralSafety.load_state(self, resume_data)
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # the latched retaliation target survives mid-route txtmap resumes.
        BotFfaEndgame.load_state(self, resume_data)
        return result

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

            self.shortest_path_to_target_player = BotTargeting.get_path_to_target_player(self, isAllIn=BotStateQueries.is_all_in(self), cutLength=None, fromTile=self.general)
            logbook.info(f'DEBUG: shortest_path_to_target_player {self.shortest_path_to_target_player}')
            if self.shortest_path_to_target_player is None:
                self.shortest_path_to_target_player = Path()
                self.shortest_path_to_target_player.add_next(self.general)
                self.shortest_path_to_target_player.add_next(next(iter(self.general.movableNoObstacles)))

            self.enemy_attack_path = BotDefense.get_enemy_probable_attack_path(self, self.targetPlayer)

            self.target_player_gather_path = BotTargeting.get_path_to_target_player(self, isAllIn=BotStateQueries.is_all_in(self), cutLength=None)
            if self.target_player_gather_path is None:
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
        tile = self._map.At(x, y)
        return self.get_army_at(tile)

    def get_army_at_x_y_or_none(self, x: int, y: int) -> Army | None:
        return self.armyTracker.armies.get(self._map.At(x, y), None)

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
        self.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0, self._map.turn)

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
        self._map.notify_player_captures.append(lambda capturee, capturer: BotEventHandlers.handle_player_captures(self, capturee, capturer))
        if self.territories is None:
            self.territories = TerritoryClassifier(self._map)

        self.armyTracker = ArmyTracker(self._map, self.perf_timer, self.opponent_tracker)
        self.armyTracker.notify_unresolved_army_emerged.append(lambda tile: BotEventHandlers.handle_tile_vision_change(self, tile))
        self.armyTracker.notify_army_moved.append(lambda move: BotEventHandlers.handle_army_moved(self, move))
        self.armyTracker.notify_army_moved.append(self.opponent_tracker.notify_army_moved)
        self.targetPlayerExpectedGeneralLocation = self.general.movable[0]
        self.board_analysis = BoardAnalyzer(self._map, self.general, self.teammate_general)
        self.tileIslandBuilder = TileIslandBuilder(self._map, self.board_analysis.intergeneral_analysis)
        self.tileIslandBuilder.recalculate_tile_islands(enemyGeneralExpectedLocation=self.targetPlayerExpectedGeneralLocation)
        self.launchPoints.append(self.general)
        self.army_interceptor = ArmyInterceptor(self._map, self.board_analysis, viewInfo=self.viewInfo)
        self.win_condition_analyzer = WinConditionAnalyzer(self._map, self.opponent_tracker, self.cityAnalyzer, self.territories, self.board_analysis)
        self.win_condition_analyzer.info = self.info
        self.cityAnalyzer.win_condition_analyzer = self.win_condition_analyzer
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
