import copy
import typing
from dataclasses import dataclass
from enum import Enum
from unittest.mock import patch

import logbook

import SearchUtils
from BotModules import BotFfaKillGather
from BotModules import BotFfaEndgame
from BotModules import BotGeneralSafety
from BotModules.BotRendering import BotRendering
from bot_ek0x45 import EklipZBot
from base.client.map import MapBase, Tile
from Directives import Timings
from Path import Path
from SearchUtils import Counter
from Models.Move import Move
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from StrategyModels.CaptureArmyAccounting import CaptureFogSnapshot
from TestBase import TestBase


class FfaCaptureOrdering(Enum):
    """Event orderings exercised by the FFA enemy-capture fog-transfer regressions."""

    TEXT_BEFORE_UPDATE = 1  # capture text arrives during move resolution, before the map update (normal sim order)
    UPDATE_THEN_TEXT = 2    # victim scoreboard zeroes on the map update, then the text arrives before the next analyze
    ANALYZE_THEN_TEXT = 3   # a full analyze_turn runs on the zeroed victim scoreboard, then the capture text arrives


@dataclass(slots=True)
class FfaCaptureExpectation(object):
    """
    Frozen ground truth plus conservative-loss arithmetic for one imported FFA
    capture. admissibleLossMin/Max are the production scoreboard-delta bounds on
    the annihilated army widened by expectedOtherArmyLossBudget (the hidden
    ceil-halving parity makes the exact loss non-identifiable, so only the
    lower bound drives expected transfers); trueAnnihilatedArmy and
    trueTransferredArmy are replay ground truth kept for interval/physical
    validation only and must never be fed to the tracker.
    """

    victimPlayer: int
    killerPlayer: int
    killerScoreBefore: int
    killerScoreAfter: int
    victimScoreBefore: int
    victimTiles: int
    defenderArmy: int
    generalAfterArmy: int
    victimGeneralPos: tuple[int, int]
    fogArmyBefore: int
    fogArmyTrueBefore: int
    fogCityArmyBefore: int
    queueAmountsBefore: dict[int, int]
    admissibleLossMin: int
    admissibleLossMax: int
    trueAnnihilatedArmy: int
    trueTransferredArmy: int
    expectedIncome: int
    expectedOtherArmyLossBudget: int
    expectedCityTransfer: int
    expectedFogArmyTransfer: int
    expectedFogArmyTrueTransfer: int


@dataclass(slots=True)
class FfaCaptureSnapshot(object):
    """Compact victim/killer fog pools, gather queues, and scores for ordering asserts."""

    victimScore: int
    victimTileCount: int
    victimCityCount: int
    killerScore: int
    killerTileCount: int
    killerCityCount: int
    victimFogArmy: int
    victimFogArmyTrue: int
    victimFogCityArmy: int
    victimQueueAmounts: dict[int, int]
    killerFogArmy: int
    killerFogArmyTrue: int
    killerFogCityArmy: int
    killerQueueAmounts: dict[int, int]
    killerPlaceholderCount: int
    killerFogNonCityCount: int


@dataclass(slots=True)
class FfaCaptureTransfer(object):
    """Entry/exit snapshots around one _transfer_captured_player_fog_state call."""

    capturee: int
    capturer: int
    entry: FfaCaptureSnapshot
    exit: FfaCaptureSnapshot


@dataclass(slots=True)
class FfaCapturePlaceholderRemoval(object):
    """Observed _remove_capture_placeholder_ones effect for one capture transfer."""

    capturee: int
    capturer: int
    recordedBefore: int
    recordedAfter: int
    onesBefore: int
    onesAfter: int


@dataclass(slots=True)
class FfaCaptureSim(object):
    """Handles for one freshly built FFA capture-ordering sim."""

    simHost: GameSimulatorHost
    bot: EklipZBot
    playerMap: MapBase
    simMap: MapBase


@dataclass(slots=True)
class FfaCaptureDestState(object):
    """Capture-destination tile fields read off the sim truth map post-capture."""

    player: int
    army: int
    isCity: bool
    isGeneral: bool


@dataclass(slots=True)
class FfaCaptureRunResult(object):
    """Everything one driven ordering case produces for the asserts."""

    hookSnapshots: list[FfaCaptureSnapshot]
    transferRecords: list[FfaCaptureTransfer]
    placeholderRecords: list[FfaCapturePlaceholderRemoval]
    postCapture: FfaCaptureSnapshot
    destState: FfaCaptureDestState
    preKillVictimTiles: list[Tile]
    actualTrueTransferredArmy: int


@dataclass(slots=True)
class FfaKillGatherResumeSnapshot(object):
    """Frozen kill-gather resume point captured inside one run_between_turns hook.

    Holds the full production txtmap (vision board + BotRendering bot_* resume
    keys), the deep-copied turn-T ground-truth map, the move queued in
    sim.moves[player] that was about to execute at the dump turn (PRE-apply), and
    the WRITTEN feature cursors/head/phase - i.e. the PREMOVE-aligned values
    save_state emitted, which may legitimately differ from the live post-consume
    state by exactly one step. The resumed bot must restore the WRITTEN values
    and re-decide the queued move, not skip it.
    """

    dump_turn: int
    resume_txtmap: str
    truth_map: MapBase
    queued_src_index: int
    queued_dst_index: int
    queued_half: bool
    written_phase: str
    written_gather_cursor: int
    written_hunt_cursor: int
    written_head_index: int
    written_enemy_index: int
    written_launch_index: int
    written_deadline_turn: int
    written_owns_lock: bool


@dataclass(slots=True)
class FfaEndgamePlacedMove(object):
    """The bot's final dispatched move captured at the place_move boundary, before the sim
    applies it, so destPreOwner/destIsCity describe the destination tile pre-capture."""
    sourceX: int
    sourceY: int
    destX: int
    destY: int
    destPreOwner: int
    destIsCity: bool
    moveHalf: bool


@dataclass(slots=True)
class FfaEndgameTurnObservation(object):
    """One turn of the imported FFA endgame: the policy mode/target/all-in flag plus the final
    dispatched move (None move fields on a deliberate pass) with the destination's pre-move
    owner so enemy and neutral-city captures are caught."""
    turn: int
    mode: str
    targetPlayer: int
    reason: str
    isAllInLosing: bool
    p7Alive: bool
    moveSource: tuple[int, int] | None
    moveDest: tuple[int, int] | None
    moveDestPreOwner: int | None
    moveDestIsCity: bool
    moveHalf: bool


@dataclass(slots=True)
class FfaEndgameReservePlacedMove(object):
    """The t391 bot's final dispatched move captured pre-apply at the place_move boundary:
    whether it left our general, the source stack's pre-move army, and the destination's
    pre-owner/isCity so p1 captures and reserve retention are both observable."""
    fromGeneral: bool
    sourceArmy: int
    destX: int
    destY: int
    destPreOwner: int
    destIsCity: bool
    moveHalf: bool


@dataclass(slots=True)
class FfaEndgameReserveObservation(object):
    """One turn of the t391 aggressor all-in: the policy mode/target/reason/all-in flag, the
    computed general reserve, p1 liveness, and this turn's dispatched move summary."""
    turn: int
    mode: str
    targetPlayer: int
    reason: str
    isAllInLosing: bool
    p1Alive: bool
    reserveRequired: int
    reserveSatisfied: bool
    moveFromGeneral: bool
    moveSourceArmy: int
    moveDestPreOwner: int | None
    moveHalf: bool
    moveDestIsCity: bool
    moveDest: tuple[int, int] | None


@dataclass(slots=True)
class FfaEndgameDetailedMove(object):
    """The HSio7 all-in's final dispatched move plus source context captured pre-apply."""
    fromGeneral: bool
    sourceX: int
    sourceY: int
    sourceArmy: int
    destX: int
    destY: int
    destPreOwner: int
    destIsCity: bool
    moveHalf: bool


@dataclass(slots=True)
class FfaEndgameDetailedObservation(object):
    """One HSio7 endgame turn: policy state, expected target-general route endpoint,
    reserve requirement, and the dispatched move's source/destination summary."""
    turn: int
    mode: str
    targetPlayer: int
    reason: str
    isAllInLosing: bool
    defenseOverride: bool
    reserveRequired: int
    reserveSatisfied: bool
    predictedGeneral: tuple[int, int] | None
    routeDest: tuple[int, int] | None
    moveFromGeneral: bool
    moveSource: tuple[int, int] | None
    moveSourceArmy: int
    moveDest: tuple[int, int] | None
    moveDestPreOwner: int | None
    moveDestIsCity: bool
    moveHalf: bool


# Frozen coherent active-defender queues for Bruddah (p7, true general 12,18),
# taken verbatim from the lead-authored probe_strong_defender.py runs proven in
# strong_defender20_proof.txt / strong_defender34_proof.txt. Each is an
# owned-only BFS gather pruned to `budget` moves and postordered front-first so
# every retained node legally converges on the enemy general; the remaining
# turns the defender passes. p0 is NEVER scripted - these only make p7 defend.
_STRONG_DEFENDER_20_QUEUE = (
    '15,18->15,19  16,19->15,19  15,19->14,19  14,19->13,19  13,22->13,21  '
    '13,21->13,20  13,20->13,19  13,19->12,19  11,21->11,20  11,20->12,20  '
    '12,21->12,20  12,20->12,19  12,19->12,18  12,16->12,17  11,17->12,17  '
    '12,17->12,18  10,20->10,19  10,19->10,18  10,18->11,18  11,18->12,18')
_STRONG_DEFENDER_34_QUEUE = (
    '15,18->15,19  16,19->15,19  15,19->14,19  14,19->13,19  13,22->13,21  '
    '13,21->13,20  13,20->13,19  13,19->12,19  11,21->11,20  11,20->12,20  '
    '12,21->12,20  12,20->12,19  12,19->12,18  10,15->11,15  11,15->12,15  '
    '12,15->12,16  9,16->10,16  10,16->11,16  11,16->12,16  12,16->12,17  '
    '8,17->9,17  9,17->10,17  10,17->11,17  11,17->12,17  12,17->12,18  '
    '10,21->10,20  10,20->10,19  10,19->10,18  8,20->9,20  9,20->9,19  '
    '9,19->9,18  9,18->10,18  10,18->11,18  11,18->12,18')
# Frozen p0 proof queue (FIRST_GATHER 28 + 6-step hunt path) that physically
# captures Bruddah within 34 turns against defender budgets 20/34/35 - documented
# in strong_defender{20,34}_proof.txt; used only as a commented proof line, the
# real tests drive the production bot with no p0 scripting.
_STRONG_ATTACK_34_PROOF = (
    '18,26->18,25  19,25->18,25  17,25->17,24  20,24->20,23  16,24->17,24  '
    '21,23->20,23  17,24->18,24  20,23->20,22  19,23->18,23  20,22->20,21  '
    '20,21->20,20  19,18->19,19  18,18->18,19  17,18->17,19  18,25->18,24  '
    '18,24->18,23  18,23->18,22  18,22->17,22  17,22->17,21  17,21->17,20  '
    '17,20->17,19  22,19->22,20  22,20->21,20  21,20->20,20  20,20->19,20  '
    '19,20->19,19  19,19->18,19  18,19->17,19  17,19->16,19->15,19->14,19->13,19->12,19->12,18')


class FfaKillGatherCommittedObserver:
    """Shared pre-apply note_final_move observer for committed kill-gather tests.

    Wraps the REAL production BotFfaKillGather.note_final_move so EVERY return
    while a kill-gather is committed - including a None idle pass - is recorded
    with the pending offered key/phase and the PRE-APPLY destination owner read
    from bot._map before the move applies (a post-hoc moves_history read sees the
    post-capture owner and cannot detect neutral/third-party attacks). Only our
    bot instance is observed; the untouched original is always called, so this
    sees the genuine production pipeline with no recert mocking.
    """

    __slots__ = (
        'bot', 'sim_host', 'real_note_final_move', 'committed_events',
        'commit_turn', 'phases_seen', 'committed_enemy_index', 'abort_recorded',
    )

    def __init__(self, bot: EklipZBot, sim_host: GameSimulatorHost) -> None:
        self.bot: EklipZBot = bot
        self.sim_host: GameSimulatorHost = sim_host
        self.real_note_final_move: typing.Callable[[EklipZBot, Move | None], None] = (
            BotFfaKillGather.note_final_move)
        # (turn, phase, offered_key, actual_base, matched, pre_owner, enemy_index, was_none)
        self.committed_events: list[tuple[int, str, str, str, bool, int, int, bool]] = []
        self.commit_turn: list[int] = []
        self.phases_seen: set[str] = set()
        # enemy_index of the first observed commit (-1 = never committed) plus a
        # once-only flag so a post-commit abort records exactly one unmatched
        # 'aborted' marker instead of letting later unrelated moves escape.
        self.committed_enemy_index: int = -1
        self.abort_recorded: bool = False

    def observe_turn(self) -> None:
        """run_between_turns hook: record first commit turn + every phase seen."""
        state = self.bot.ffa_kill_gather_state
        if state is None:
            return
        if not self.commit_turn:
            self.commit_turn.append(self.sim_host.sim.turn)
        self.phases_seen.add(state.phase)

    def note_final_move_wrapper(self, bot_arg: EklipZBot, move: Move | None) -> None:
        """patch.object target: observe OUR bot's committed returns pre-apply."""
        state = bot_arg.ffa_kill_gather_state
        if bot_arg is self.bot and state is not None:
            if self.committed_enemy_index == -1:
                self.committed_enemy_index = state.enemy_index
            if not self.commit_turn:
                self.commit_turn.append(self.sim_host.sim.turn)
            self.phases_seen.add(state.phase)
            offered_key = state.pending_offered_key
            offered_base = offered_key.rsplit(':', 1)[0] if offered_key else ''
            last_consumed_before = state.last_consumed_turn
            if move is None:
                self.committed_events.append((
                    self.sim_host.sim.turn, state.phase, offered_key, '',
                    False, -2, state.enemy_index, True))
            else:
                dest_tile = bot_arg._map.GetTile(move.dest.x, move.dest.y)
                pre_owner = dest_tile.player if dest_tile is not None else -2
                actual_base = f"{move.source.tile_index}>{move.dest.tile_index}"
                matched = bool(offered_base) and offered_base == actual_base
                enemy_index = state.enemy_index
                phase = state.phase
                self.real_note_final_move(bot_arg, move)
                # A defense/city branch may preempt the committed return yet still
                # execute the identical scheduled step; note_final_move resyncs and
                # consumes it, which still counts as an on-plan move.
                state_after = bot_arg.ffa_kill_gather_state
                if not matched and state_after is not None and state_after.last_consumed_turn != last_consumed_before:
                    matched = True
                self.committed_events.append((
                    self.sim_host.sim.turn, phase, offered_key, actual_base,
                    matched, pre_owner, enemy_index, False))
                return
        elif bot_arg is self.bot and self.committed_enemy_index != -1 and not self.abort_recorded:
            score = bot_arg._map.scores[self.committed_enemy_index]
            if not score.dead and score.tiles > 0:
                self.abort_recorded = True
                self.committed_events.append((
                    self.sim_host.sim.turn, 'aborted', '', '', False, -2,
                    self.committed_enemy_index, move is None))
        return self.real_note_final_move(bot_arg, move)


@dataclass(slots=True)
class FfaKillGatherRunResult:
    """Bundles one committed kill-gather fixture run for shared assertions."""
    sim_host: GameSimulatorHost
    bot: EklipZBot
    observer: FfaKillGatherCommittedObserver
    game_map: MapBase
    general: Tile
    target_general: Tile


@dataclass(slots=True)
class FfaGeneralSafetySnapshot(object):
    """Per-turn physical + fog snapshot for the t179 general-reveal defense fixture.

    mobile_near7/5 are the STRONGEST SINGLE other owned tile (max army, lowest
    tile_index tiebreak) reachable from our general through owned pathable
    .movable tiles within 7/5 BFS steps on the TRUE sim map - the general tile
    itself is excluded so the starting garrison cannot trivially satisfy the
    thresholds. Fog fields read the bot's real opponent_tracker; fog_risk_25 is
    get_approximate_fog_army_risk(target, inTurns=25); enemy_knows_general reads
    the target's actual fogged player map (generals[our_index] discovered).
    """

    turn: int
    general_army: int
    mobile_near7: int
    mobile_near7_index: int
    mobile_near5: int
    mobile_near5_index: int
    enemy_knows_general: bool
    fog_army: int
    fog_city_army: int
    fog_risk_25: int
    target_player: int
    all_in_advantage: bool
    all_in_losing: bool


@dataclass(slots=True)
class FfaGeneralSafetyRunResult(object):
    """Bundles one general-reveal defense fixture run for shared assertions."""
    simHost: GameSimulatorHost
    bot: EklipZBot
    simMap: MapBase
    general: Tile
    meemoGeneral: Tile
    snapshots: dict[int, FfaGeneralSafetySnapshot]


class FfaGeneralSafetyObserver:
    """run_between_turns observer for the t179 general-reveal defense fixture.

    Each between-turns callback reads the ACTUAL sim ground truth
    (simHost.sim.sim_map): our live general tile (re-read from sim_map.generals
    each turn since the general moves), a BFS from it through owned pathable
    .movable tiles (depth <= 7) to find the strongest single other owned tile
    within 7 and within 5 steps, plus the target's real fog state from
    bot.opponent_tracker and whether the target's own fogged player map has
    discovered our general. Snapshots are keyed by sim.turn - a duplicate turn
    evaluation simply overwrites since the physical board is unchanged between
    callbacks of the same turn.
    """

    __slots__ = (
        'sim_host', 'bot', 'player_index', 'target_player', 'snapshots',
    )

    def __init__(
            self,
            sim_host: GameSimulatorHost,
            bot: EklipZBot,
            player_index: int,
            target_player: int) -> None:
        self.sim_host: GameSimulatorHost = sim_host
        self.bot: EklipZBot = bot
        self.player_index: int = player_index
        self.target_player: int = target_player
        self.snapshots: dict[int, FfaGeneralSafetySnapshot] = {}

    def observe_turn(self) -> None:
        """run_between_turns hook: record one typed snapshot for sim.turn."""
        sim = self.sim_host.sim
        sim_map = sim.sim_map
        turn = sim.turn
        general = sim_map.generals[self.player_index]
        if general is None:
            return
        general_army = general.army

        # BFS from the general through OWNED pathable tiles only, depth <= 7.
        # depths maps tile_index -> BFS depth; the general itself sits at 0 and
        # is excluded from candidacy below.
        depths: dict[int, int] = {general.tile_index: 0}
        queue: list[tuple[Tile, int]] = [(general, 0)]
        head = 0
        while head < len(queue):
            tile, depth = queue[head]
            head += 1
            if depth >= 7:
                continue
            for nxt in tile.movable:
                if nxt.player != self.player_index:
                    continue
                if nxt.tile_index in depths:
                    continue
                depths[nxt.tile_index] = depth + 1
                queue.append((nxt, depth + 1))

        # Strongest SINGLE other owned tile within 7 / within 5 steps: max army,
        # lowest tile_index on ties (stable deterministic pick).
        best7_key: tuple[int, int] | None = None
        best7_index = -1
        best5_key: tuple[int, int] | None = None
        best5_index = -1
        for tile_index, depth in depths.items():
            if depth == 0:
                continue
            tile = sim_map.tiles_by_index[tile_index]
            if tile.isGeneral:
                continue
            key = (tile.army, -tile_index)
            if depth <= 5 and (best5_key is None or key > best5_key):
                best5_key = key
                best5_index = tile_index
            if best7_key is None or key > best7_key:
                best7_key = key
                best7_index = tile_index
        mobile_near7 = best7_key[0] if best7_key is not None else 0
        mobile_near5 = best5_key[0] if best5_key is not None else 0

        stats = self.bot.opponent_tracker.get_current_cycle_stats_by_player(self.target_player)
        fog_army = stats.approximate_fog_army_available_total if stats is not None else 0
        fog_city_army = stats.approximate_fog_city_army if stats is not None else 0
        fog_risk_25 = self.bot.opponent_tracker.get_approximate_fog_army_risk(
            self.target_player, inTurns=25)
        target_map = sim.players[self.target_player].map
        enemy_knows_general = (
            target_map is not None and target_map.generals[self.player_index] is not None)

        self.snapshots[turn] = FfaGeneralSafetySnapshot(
            turn=turn,
            general_army=general_army,
            mobile_near7=mobile_near7,
            mobile_near7_index=best7_index,
            mobile_near5=mobile_near5,
            mobile_near5_index=best5_index,
            enemy_knows_general=enemy_knows_general,
            fog_army=fog_army,
            fog_city_army=fog_city_army,
            fog_risk_25=fog_risk_25,
            target_player=self.target_player,
            all_in_advantage=self.bot.is_all_in_army_advantage,
            all_in_losing=self.bot.is_all_in_losing)
        logbook.info(
            f'GENERAL_SAFETY_TEST turn={turn} gen={general_army} '
            f'mobile7={mobile_near7}@{best7_index} mobile5={mobile_near5}@{best5_index} '
            f'fog={fog_army} city={fog_city_army} knows={enemy_knows_general} '
            f'risk25={fog_risk_25} adv={self.bot.is_all_in_army_advantage} '
            f'lose={self.bot.is_all_in_losing}')


class FFATests(TestBase):
    def test_should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_defensively_when_just_captured_3rd_player_and_winning_on_econ_and_last_player_doesnt_know_gen_pos___j4GQjpuy4---0--379.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 379, fill_out_tiles=True)
        enemyGeneral = self.move_enemy_general(map, enemyGeneral, 6, 20)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=379)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '9,6->9,4->14,4->14,5->15,5->15,6->17,6->17,5->20,5->20,4->22,4->22,7->21,7->21,8->10,8')
        bot = self.get_debug_render_bot(simHost, general.player)

        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=100)
        self.assertIsNone(winner)

    def test_should_find_kill_in_ffa_position(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_find_kill_in_ffa_position___eW64nZ8rZ---2--69.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 69, fill_out_tiles=True)
        enemyGeneral.army = 10

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=69)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=7)
        self.assertIsNone(winner)

        self.assertEqual(general.player, enemyGeneral.player, 'should have captured fincher')

    # 0f 2p
    def test_should_not_time_out_on_win_condition_in_ffa(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_time_out_on_win_condition_in_ffa___uu_dzfs6v---1--1275.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 1275, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=1275)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, '17,21->18,21->18,17->20,17->20,6->18,6->18,4->20,4->20,0->21,0')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=35)
        self.assertIsNone(winner)

    def test_should_gather_for_large_attacks_out_of_vision_range_in_rounds(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_gather_for_large_attacks_out_of_vision_range_in_rounds___EklipZ_ai-SUlNa6E3r---7--50.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 50, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=50)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        bot.timings = None
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=15)
        # 12 moves minimum to gather out of vision
        self.assertNoFriendliesKilled(map, general)

        self.assertEqual(1, playerMap.GetTile(23, 15).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22,15).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22,16).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22, 17).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(22, 18).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 17).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 18).army, 'should have gathered everything')
        self.assertEqual(1, playerMap.GetTile(23, 20).army, 'should have gathered everything')
        self.assertEqual(15, playerMap.players[general.player].tileCount, "should not have captured land")


    def test_should_not_attack_unprovoked_enemies_in_early_ffa(self):
        """
        Live repro: Human.exe-ffa-2026-11-13_04-17-56---IPhAP7nUw turn 45.
        Multiple enemy players were revealed early (c and g border us, others in fog),
        nobody had attacked us, yet the bot captured player d's tile at 10,19 on t47
        while nominally targeting g. When multiple enemies are revealed in a
        non-dominant FFA and nobody is attacking us, we must refuse to attack any of them.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_attack_unprovoked_ffa_players___IPhAP7nUw---0--45.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 45, fill_out_tiles=True)

        # Arm our frontier so captures into revealed enemy land are immediately
        # available: player c owns 6,11 / 6,12 and player g owns 15,15. Without the
        # fix the bot eats them opportunistically within a few turns.
        # Keep each tile at exactly 3 (enough to take the adjacent 1-army enemy
        # tiles): inflating our total score too far flips
        # is_still_ffa_and_non_dominant to dominant, which legitimately disables
        # the pacifism gate. In the live game our score was ~equal to everyone.
        map.GetTile(7, 11).army = 3
        map.GetTile(7, 12).army = 3
        map.GetTile(7, 13).army = 3
        map.GetTile(14, 16).army = 3

        ownersBefore = [t.player for t in map.tiles_by_index]

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=45)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=15)
        self.assertIsNone(winner)

        violations = []
        for t in map.tiles_by_index:
            oldOwner = ownersBefore[t.tile_index]
            if oldOwner >= 0 and oldOwner != general.player and t.player == general.player:
                violations.append((t.x, t.y, oldOwner))
        self.assertEqual([], violations, 'unprovoked FFA bot must not capture tiles of players that are not attacking us')

        # player.tileCount / player.tiles are not maintained on the sim ground-truth
        # map; count live ownership through tiles_by_index instead.
        ourTileCount = sum(1 for t in map.tiles_by_index if t.player == general.player)
        self.assertGreater(ourTileCount, 20, 'bot should still be expanding into neutral land')

    def test_should_exclusively_attack_player_that_attacks_us_in_early_ffa(self):
        """
        Same live repro state. When an enemy player attacks us in a non-dominant FFA
        with multiple revealed enemies, we must lock onto that player exclusively and
        must not take tiles owned by any other player.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_attack_unprovoked_ffa_players___IPhAP7nUw---0--45.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 45, fill_out_tiles=True)

        # player 2 (c) borders us at 6,11 / 6,12. Beef it up so its queued attack
        # can actually overrun a big chunk of our territory and cross the
        # aggression_factor > 120 provocation threshold.
        map.GetTile(6, 11).army = 45
        map.GetTile(6, 12).army = 45

        ownersBefore = [t.player for t in map.tiles_by_index]

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=45)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(
            enemyGeneral.player,
            '6,11->7,11->7,12->7,13->7,14->7,15->6,15->6,16->5,16->4,16  6,12->7,12->7,13->7,14->8,14->8,15->9,15->10,15->10,16->11,16->12,16->13,16->14,16')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=40)

        self.assertGreater(playerMap.players[enemyGeneral.player].aggression_factor, 0, 'player c overran our territory and should be flagged as the aggressor')
        self.assertEqual(enemyGeneral.player, bot.targetPlayer, 'the player attacking us must become our exclusive target')

        violations = []
        for t in map.tiles_by_index:
            oldOwner = ownersBefore[t.tile_index]
            if oldOwner >= 0 and oldOwner != general.player and oldOwner != enemyGeneral.player and t.player == general.player:
                violations.append((t.x, t.y, oldOwner))
        self.assertEqual([], violations, 'after locking onto the aggressor we must not capture tiles of other players')

    def test_should_not_ffg_forever(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_not_ffg_forever___ZEaJK2oWZ---2--359.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 359, fill_out_tiles=False)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=359)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(enemyGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=25)
        self.assertNoFriendliesKilled(map, general)

    def test_should_snap_kill_nearby_ffa_general_after_enemy_army_loss(self) -> None:
        """
        Live FFA turn 146: pink (p5) lost 41 army in fog and her general location is unknown,
        but our 28-army stack at (10,4) sits next to her small valid-general region. The bot
        must infer the clear kill, lock p5 as the exclusive FFA target, and capture her true
        general (6,5) within 8 sim turns.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_snap_kill_nearby_ffa_general_after_enemy_army_loss___1qEuiySOGo---3--146.txtmap'
        # The sibling truemap is replay ground truth aligned to bot-view coordinates
        # (25x26); verified against all bot-visible cells in the fog snapshot.
        trueMapFile = 'GameContinuationEntries/should_snap_kill_nearby_ffa_general_after_enemy_army_loss___1qEuiySOGo---3--146.truemap.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 146, fill_out_tiles=True)
        # Pink is player 5 (Chico462); her true general is not the helper's default enemy pick.
        pinkGeneral = map.generals[5]
        self.assertIsNotNone(pinkGeneral)
        self.assertTrue(pinkGeneral.isGeneral)
        self.assertEqual(5, pinkGeneral.player)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=146)
        # Tests/test_FFA.py::test_should_snap_kill_nearby_ffa_general_after_enemy_army_loss:
        # serialized island_ids orphan fog tile (15,12) p0 and crash island rebuild
        # (full_island None); dropping the key rebuilds islands fresh, other resume state kept.
        rawMap.resume_data.pop('island_ids', None)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        simHost.queue_player_moves_str(pinkGeneral.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # Capture the bot's FIRST pending move decision (including a pass) and the exclusive
        # FFA target lock in effect when it was picked, so the kill cannot pass via lucky
        # late wandering unrelated to p5.
        observedFirstDecision = False
        firstDecisionMove: tuple[int, int, int, int] | None = None
        firstDecisionLock = -1

        def watchFirstPinkDecision() -> None:
            """Snapshots the bot's first picked move (or pass) from sim.moves before it resolves."""
            nonlocal observedFirstDecision, firstDecisionMove, firstDecisionLock
            if observedFirstDecision:
                return
            observedFirstDecision = True
            firstDecisionLock = bot.ffa_exclusive_target_lock
            move = simHost.sim.moves[general.player]
            if move is not None:
                firstDecisionMove = (move.source.x, move.source.y, move.dest.x, move.dest.y)

        simHost.run_between_turns(watchFirstPinkDecision)

        # proof: scripted route for our 28-army stack at (10,4) through pink's forward tiles to
        # her true general at (6,5); captures the general on the 5th move (sim turn 151).
        # simHost.queue_player_moves_str(general.player, '10,4->9,4->8,4->8,5->7,5->6,5')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=8)
        self.assertTrue(observedFirstDecision, 'bot never produced a first move decision')
        self.assertEqual((10, 4, 9, 4), firstDecisionMove)
        self.assertEqual(5, firstDecisionLock, 'first bot decision was not made while p5 was the exclusive FFA target')
        self.assertOwned(general.player, pinkGeneral)
        self.assertNoFriendliesKilled(map, general)

    def _run_general_reveal_defense_case(
            self, turns: int, own_proof_queue: str | None = None) -> FfaGeneralSafetyRunResult:
        """Shared t179 general-reveal defense fixture for the safety tests.

        Live FFA turn 179 (replay 50ZwYtndy): Meemo (p3, 'd') moves 24,18 ->
        23,18 on the first post-import turn, revealing our general at (22,19).
        Loads the imported ground truth + bot vision UNCHANGED (resume state
        preserved apart from the standard island_ids pop documented below),
        patches ONLY MapBase.DO_NOT_RANDOMIZE for repeatable island ids across
        BOTH loads and the whole case plus BotGeneralSafety.GENERAL_SAFETY_ENABLED
        locally (the live-tree flag stays False), queues every non-self player
        'None' EXCEPT Meemo's single reveal move (then AFK), and drives the REAL
        GameSimulator for `turns` turns while the typed FfaGeneralSafetyObserver
        records per-turn snapshots. p0 is NEVER scripted unless own_proof_queue
        is passed - that parameter exists ONLY for the lead's separate external
        physical proof runner; the acceptance tests pass None.

        # proof: the lead's frozen physical proof
        # (ffa_general_safety_t179/physical_reserve_proof.json/.txt, PASS) shows
        # one real owned-army schedule physically delivers mobile_near7>=30 by
        # t188 and mobile_near5>=60 by t214 with Meemo AFK after the reveal:
        #   22,20->22,19->22,20z  11,17->11,18->12,18->12,19->13,19->14,19->15,19
        #   ->16,19->17,19->18,19->19,19->19,20->20,20->21,20->22,20  + 19x none

        Real replay continuation for reference (importer -MovesTurns 65, all
        preserved as comments; trailing idle turns are trimmed by the tool so
        each queue ends at that player's last applied move):
          # simHost.queue_player_moves_str(general.player, '22,20->22,19  25,17->25,18  15,21->14,21  22,19->22,18  22,17->22,18->23,18  13,23->12,23  24,25->24,26  17,26->17,27  23,23->23,24->24,24->25,24  22,19->22,18  23,18->24,18  22,18->23,18  24,18->24,17  23,17->24,17->24,16->24,15->24,14->23,14  11,17->11,18  21,27->20,27  20,28->19,28  20,27->19,27  19,28->19,27->18,27->18,26->18,25  15,23->16,23->17,23  18,25->17,25->17,24->17,23->17,22->17,21->17,20->17,19->17,18->18,18->18,17->18,16->18,15->18,14->18,13->18,12->19,12->19,11->18,11->18,10->18,9->18,8->18,7->18,6->17,6->17,5->17,4->17,3->17,2->18,2->18,1->18,0->18,1->19,1->20,1')  # replay line for Human.exe
          # simHost.queue_player_moves_str(3, '24,18->23,18  none  23,18->22,18  none  none  none  none  none  none  none  none  none  none  none  1,0->2,0->2,1->2,2->3,2->3,1->4,1->4,2->5,2->6,2->7,2->8,2->8,1->9,1->9,2->10,2->11,2->12,2->13,2->14,2->15,2->16,2->17,2->18,2->19,2->20,2->21,2->21,1->22,1->23,1->24,1->25,1->25,2  20,6->20,5->20,4->21,4->22,4  25,2->25,1->24,1->23,1->22,1->21,1->20,1->20,2  none  17,1->18,1->19,1  none  19,1->19,2  none  19,2->19,1')  # replay moves: Meemo
          # simHost.queue_player_moves_str(4, '12,12->11,12  none  11,12->12,12->13,12->13,11->13,10->13,9->13,8->13,7->13,6->12,6->12,5->13,5->14,5->14,6->15,6->15,7->15,8->15,9->15,10->15,11->14,11->13,11  none  13,9->13,10->13,11->13,12->13,13->12,13->11,13->10,13->9,13->9,12->9,11->9,10->9,9->9,8->8,8->7,8->6,8->5,8->5,9->5,10->6,10->6,11->6,12->5,12->5,13->4,13->3,13->2,13->1,13->2,13->2,12->2,13->2,14->2,15->2,16->1,16->0,16->0,17->1,17->1,18->0,18->0,19')  # replay moves: al.Ghazali
          # simHost.queue_player_moves_str(5, 'none  none  6,27->5,27->4,27  none  none  none  none  none  none  none  none  none  none  none  none  none  none  none  10,27->11,27  none  none  none  none  none  none  11,27->11,26->11,25z  11,26->11,25->11,24  none  none  none  none  none  8,24->8,23  none  none  none  none  none  none  none  none  none  7,25->8,25  none  none  8,25->7,25->6,25z  5,24->5,25->4,25->3,25  none  none  none  none  none  7,27->7,26z->7,25  2,25->3,25z  none  1,24->2,24->3,24->2,24')  # replay moves: qwerttyuuiipp
          # simHost.queue_player_moves_str(6, '5,12->6,12->6,11->6,10->6,9->6,8->7,8->7,7->7,6->7,5->7,4->7,3  none  7,3->6,3->5,3->4,3  none  4,3->5,3->5,4->6,4->5,4->5,5->5,6->4,6  none  none  none  none  0,19->1,19  none  none  none  none  none  none  0,18->0,17->0,16->1,16->2,16->2,15->2,14->2,13->2,12->3,12  none  none  none  none  none  3,12->2,12->2,13  none  none  none  0,13->0,12  none  0,12->0,13->0,12->0,11->0,12->0,13  0,18->0,17')  # replay moves: blacksabbath
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_reserve_nearby_defense_after_enemy_finds_general___50ZwYtndy---0--179.txtmap'
        trueMapFile = 'GameContinuationEntries/should_reserve_nearby_defense_after_enemy_finds_general___50ZwYtndy---0--179.truemap.txtmap'

        with patch.object(MapBase, 'DO_NOT_RANDOMIZE', True), \
                patch.object(BotGeneralSafety, 'GENERAL_SAFETY_ENABLED', True):
            map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 179, fill_out_tiles=True)
            self.assertEqual(3, enemyGeneral.player)
            meemoGeneral = map.generals[3]
            self.assertIsNotNone(meemoGeneral)
            self.assertTrue(meemoGeneral.isGeneral)
            self.assertEqual(3, meemoGeneral.player)

            rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=179)

            # The serialized island_ids resume matrix can group fog-tracked tiles
            # whose resumed ownership the vision map no longer reproduces, leaving
            # rebuild_islands_from_ids with islands that never join a full island
            # (AttributeError on island.full_island.tile_count - observed on the
            # first run of this fixture). Let the standard fresh island build from
            # map init stand instead of the serialized override, same as the other
            # FFA continuation tests (e.g. should_attack_aggressor... t391).
            rawMap.resume_data.pop('island_ids', None)

            self.enable_search_time_limits_and_disable_debug_asserts()
            simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
            for enemyIndex in range(len(simHost.sim.players)):
                if enemyIndex == general.player:
                    continue
                if enemyIndex == meemoGeneral.player:
                    simHost.queue_player_moves_str(enemyIndex, '24,18->23,18')
                else:
                    simHost.queue_player_moves_str(enemyIndex, 'None')
            if own_proof_queue is not None:
                simHost.queue_player_moves_str(general.player, own_proof_queue)
            bot = self.get_debug_render_bot(simHost, general.player)

            observer = FfaGeneralSafetyObserver(
                sim_host=simHost, bot=bot,
                player_index=general.player, target_player=meemoGeneral.player)
            simHost.run_between_turns(observer.observe_turn)

            self.begin_capturing_logging()
            simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=turns)

        return FfaGeneralSafetyRunResult(
            simHost=simHost, bot=bot, simMap=map, general=general,
            meemoGeneral=meemoGeneral, snapshots=observer.snapshots)

    def _run_committed_kill_gather_case(
            self, enemy_move_queue: str | None) -> FfaKillGatherRunResult:
        """Shared 35-turn committed kill-gather fixture for the acceptance tests.

        Loads the imported t100 ground truth + bot vision UNCHANGED, queues every
        non-viewer enemy 'None' except player 7 (Bruddah) which receives
        `enemy_move_queue` (None = also AFK 'None'), patches ONLY
        FFA_KILL_GATHER_ENABLED locally, and drives the REAL GameSimulator for
        exactly 35 turns while the shared pre-apply note_final_move observer
        records every committed return. p0 is never scripted.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_nearby_players_as_fast_as_possible___50ZwYtndy---0--100.txtmap'
        # Replay ground truth aligned to bot-view coordinates; 522 visible cells checked.
        trueMapFile = 'GameContinuationEntries/should_all_in_nearby_players_as_fast_as_possible___50ZwYtndy---0--100.truemap.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 100, fill_out_tiles=True)
        # Bruddah is player 7 (h); her true general is not the helper's default enemy pick.
        bruddahGeneral = map.generals[7]
        self.assertIsNotNone(bruddahGeneral)
        self.assertTrue(bruddahGeneral.isGeneral)
        self.assertEqual(7, bruddahGeneral.player)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        for enemyIndex in range(len(simHost.sim.players)):
            if enemyIndex == general.player:
                continue
            if enemyIndex == 7 and enemy_move_queue is not None:
                simHost.queue_player_moves_str(enemyIndex, enemy_move_queue)
            else:
                simHost.queue_player_moves_str(enemyIndex, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)

        observer = FfaKillGatherCommittedObserver(bot, simHost)
        simHost.run_between_turns(observer.observe_turn)

        self.begin_capturing_logging()
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True), \
                patch.object(BotFfaKillGather, 'note_final_move', observer.note_final_move_wrapper):
            simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=35)
        for event in observer.committed_events:
            if not event[4]:
                logbook.info(f"FFA Kill Gather TEST-OFFPLAN event={event}")
        return FfaKillGatherRunResult(simHost, bot, observer, map, general, bruddahGeneral)

    def _assert_committed_kill_gather_clean(self, result: FfaKillGatherRunResult) -> None:
        """Shared no-waste assertions for the committed kill-gather cases.

        These fixtures have NO urgent third-party defense, so EVERY return while
        committed must be the offered plan step - a None idle pass or an unoffered
        move is a failure. Neutral captures are only legitimate as offered
        on-route connectors; attacking any non-target player never is.
        """
        observer = result.observer
        self.assertTrue(observer.commit_turn, 'kill-gather never committed during the 35-turn window')
        self.assertEqual(7, observer.committed_enemy_index)
        self.assertIn('gather', observer.phases_seen)
        self.assertIn('hunt', observer.phases_seen)
        events = observer.committed_events
        self.assertTrue(events, 'no committed move events recorded')
        self.assertTrue(all(event[6] == 7 for event in events), 'commitment changed victims before the kill')
        unmatched = [e for e in events if not e[4]]
        self.assertEqual([], unmatched, f'committed returns that were not the offered plan step (incl idle None): {unmatched[:5]}')
        bad_third = [e for e in events if e[5] >= 0 and e[5] not in (result.general.player, e[6])]
        self.assertEqual([], bad_third, f'committed moves attacking a non-target player: {bad_third[:5]}')
        bad_neutral = [e for e in events if e[5] == -1 and not e[4]]
        self.assertEqual([], bad_neutral, f'unrelated neutral captures while committed: {bad_neutral[:5]}')

    def test_should_all_in_nearby_players_as_fast_as_possible(self) -> None:
        """
        Live FFA turn 100: with >2 living teams the bot should commit to killing nearby
        players as fast as possible. Bruddah (p7) is the closest living enemy - her true
        general sits at (12,18) near our (22,19) army-20 general.
        """
        # proof: the frozen FIRST_GATHER28 + 6-step hunt path physically captures
        # Bruddah within 34 turns (strong_defender_proof.txt, no army boost, no
        # general-truth leak):
        # simHost.queue_player_moves_str(general.player, _STRONG_ATTACK_34_PROOF)
        result = self._run_committed_kill_gather_case(None)
        self.assertOwned(result.general.player, result.target_general)
        self.assertNoFriendliesKilled(result.game_map, result.general)
        self._assert_committed_kill_gather_clean(result)

    def test_should_all_in_nearby_players_as_fast_as_possible_vs_defender20(self) -> None:
        """Same t100 acceptance but Bruddah actively defends with a coherent
        20-move owned gather (strong_defender20_proof.txt physical capture PASS)."""
        # proof: identical frozen FIRST_GATHER28 + 6-step path captures within 34
        # turns even against the 20-move defender (strong_defender20_proof.txt):
        # simHost.queue_player_moves_str(general.player, _STRONG_ATTACK_34_PROOF)
        result = self._run_committed_kill_gather_case(_STRONG_DEFENDER_20_QUEUE)
        self.assertOwned(result.general.player, result.target_general)
        self.assertNoFriendliesKilled(result.game_map, result.general)
        self._assert_committed_kill_gather_clean(result)

    def test_should_all_in_nearby_players_as_fast_as_possible_vs_defender34(self) -> None:
        """Same t100 acceptance but Bruddah actively defends with a coherent
        34-move owned gather (strong_defender34_proof.txt physical capture PASS)."""
        # proof: identical frozen FIRST_GATHER28 + 6-step path captures within 34
        # turns even against the 34-move defender (strong_defender34_proof.txt):
        # simHost.queue_player_moves_str(general.player, _STRONG_ATTACK_34_PROOF)
        result = self._run_committed_kill_gather_case(_STRONG_DEFENDER_34_QUEUE)
        self.assertOwned(result.general.player, result.target_general)
        self.assertNoFriendliesKilled(result.game_map, result.general)
        self._assert_committed_kill_gather_clean(result)

    def test_should_execute_committed_kill_gather_to_capture(self) -> None:
        """
        EXECUTION component test (NOT the 35-turn acceptance): same imported t100
        ground truth + bot vision, but a 41-turn window sized for the VERIFIED
        selected plan (~40 turns: 33 literal gather moves + 7-turn WRP hunt/finish
        from a turn-101 commit). Proves the committed state machine actually drives
        gather -> hunt -> reveal -> capture through the REAL GameSimulator move
        pipeline (every move is the production pick_move_after_prep output, so
        defense gates keep priority and only certified gather/search/finish steps
        run while committed - no unrelated expansion). No artificial army, no fog
        truth leak: identical mapFile/trueMapFile/queue-'None' opponent setup.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_nearby_players_as_fast_as_possible___50ZwYtndy---0--100.txtmap'
        trueMapFile = 'GameContinuationEntries/should_all_in_nearby_players_as_fast_as_possible___50ZwYtndy---0--100.truemap.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 100, fill_out_tiles=True)
        bruddahGeneral = map.generals[7]
        self.assertIsNotNone(bruddahGeneral)
        self.assertTrue(bruddahGeneral.isGeneral)
        self.assertEqual(7, bruddahGeneral.player)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        for enemyIndex in range(len(simHost.sim.players)):
            if enemyIndex != general.player:
                simHost.queue_player_moves_str(enemyIndex, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # run_between_turns observer: records ONLY commit timing + phase
        # transitions (cheap state read, no move inspection). Move-level no-waste
        # proof is done by the note_final_move wrapper below, which sees the
        # PRE-APPLY destination owner that a post-hoc moves_history read cannot.
        commit_turn: list[int] = []
        phases_seen: set[str] = set()

        def _observe_committed_execution() -> None:
            state = bot.ffa_kill_gather_state
            if state is None:
                return
            if not commit_turn:
                commit_turn.append(simHost.sim.turn)
            phases_seen.add(state.phase)

        simHost.run_between_turns(_observe_committed_execution)

        # note_final_move wrapper: intercepts the REAL production reconcile call
        # (bot_ek0x45.py:1223 -> BotFfaKillGather.note_final_move) at decision
        # time, BEFORE the move is applied, so move.dest still carries the
        # PRE-CAPTURE owner via bot._map. It records the outstanding offered
        # key/phase plus the actual returned move for OUR bot only, then calls
        # the untouched original. patch.object swaps the module attribute the
        # call site uses, so this observes the genuine pipeline - no recert mock.
        real_note_final_move = BotFfaKillGather.note_final_move
        plan_phases = {'gather', 'hunt', 'finish', 'known_general'}
        committed_events: list[tuple[int, str, str, str, bool, int, int]] = []

        def _observe_note_final_move(bot_arg: EklipZBot, move: Move | None) -> None:
            state = bot_arg.ffa_kill_gather_state
            if (bot_arg is bot and state is not None and state.phase in plan_phases
                    and move is not None):
                dest_tile = bot_arg._map.GetTile(move.dest.x, move.dest.y)
                pre_owner = dest_tile.player if dest_tile is not None else -2
                offered_key = state.pending_offered_key
                offered_base = offered_key.rsplit(':', 1)[0] if offered_key else ''
                actual_base = f"{move.source.tile_index}>{move.dest.tile_index}"
                matched = bool(offered_base) and offered_base == actual_base
                committed_events.append((
                    simHost.sim.turn, state.phase, offered_key, actual_base, matched,
                    pre_owner, state.enemy_index))
            return real_note_final_move(bot_arg, move)

        # proof: the certified option committed at sim turn 101 is
        # launch=17,19 gatherMoves=33 routeTurns=7 deadline=141 margin=+1
        # (t100_r2.txt COMMIT line). 41 turns covers the full window through t141.
        # The process-local flag patch makes this test self-contained: a plain
        # unittest run (flag False) would otherwise pass via normal bot play and
        # never exercise the feature at all.
        # proof (literal p0 queue verified to capture Bruddah via
        # proof_extract.py PASS2 - same fixture, moves scripted, assertOwned OK):
        # simHost.queue_player_moves_str(general.player, 'none  16,24->16,23  18,27->18,26  19,26->19,25  20,25->20,24  16,23->16,24  18,26->18,25  19,25->18,25  17,25->17,24  20,24->20,23  16,24->17,24  21,23->20,23  22,18->22,19  17,24->18,24  20,23->20,22  19,23->18,23  20,22->20,21  20,21->20,20  19,18->18,18  18,18->17,18  17,18->17,19  18,25->18,24  18,24->18,23  18,23->18,22  18,22->17,22  17,22->17,21  17,21->17,20  17,20->17,19  22,19->22,20  22,20->21,20  21,20->20,20  20,20->19,20  19,20->19,19  19,19->18,19  18,19->17,19  17,19->16,19  16,19->15,19  15,19->14,19  14,19->13,19  13,19->12,19  12,19->12,18  14,25->13,25')
        self.begin_capturing_logging()
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True), \
                patch.object(BotFfaKillGather, 'note_final_move', _observe_note_final_move):
            winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=41)
        self.assertOwned(general.player, bruddahGeneral)
        self.assertNoFriendliesKilled(map, general)
        # committed execution actually happened and stayed on-plan
        self.assertTrue(commit_turn, 'kill-gather never committed during the 41-turn window')
        self.assertIn('gather', phases_seen)
        self.assertIn('hunt', phases_seen)
        # Every move executed while committed must be the offered plan step. All
        # enemies are AFK 'None' here so no defense preemption is expected: any
        # committed move that is NOT the offered key is unrelated expansion or a
        # phantom consume. Neutral captures are only legitimate as offered
        # on-route connectors; attacking any non-target third party is never ok.
        self.assertTrue(committed_events, 'no committed move events recorded')
        unmatched = [e for e in committed_events if not e[4]]
        self.assertEqual([], unmatched, f'committed moves that were not the offered plan step: {unmatched[:5]}')
        bad_third = [e for e in committed_events if e[5] >= 0 and e[5] not in (general.player, e[6])]
        self.assertEqual([], bad_third, f'committed moves attacking a non-target player: {bad_third[:5]}')
        bad_neutral = [e for e in committed_events if e[5] == -1 and not e[4]]
        self.assertEqual([], bad_neutral, f'unrelated neutral captures while committed: {bad_neutral[:5]}')

    def _ffa_kill_gather_resume_roundtrip(
            self,
            turns: int,
            want_phase: str,
            min_live_gather_cursor: int,
            case_label: str) -> None:
        """Real mid-commit serialization roundtrip for one committed phase.

        Runs the imported t100 fixture once under the process-local flag, freezes
        a FfaKillGatherResumeSnapshot inside run_between_turns at the first turn
        matching want_phase (map is PRE-move, cursor is POST-consume - the exact
        BotHost.make_move -> place_move_func(ASYNC) -> save_txtmap ordering), then
        reloads the dumped txtmap through load_map_and_general_from_string and
        re-decides ONE turn via execute_turn (never a second run_sim). Asserts the
        resumed bot restores the WRITTEN PREMOVE-aligned cursors/head/phase (which
        save_state emits one step behind live post-consume state) and reproduces
        the exact move queued in sim.moves[player] at the dump turn - i.e. resume
        re-executes the step the pre-move board expects rather than skipping it.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_all_in_nearby_players_as_fast_as_possible___50ZwYtndy---0--100.txtmap'
        trueMapFile = 'GameContinuationEntries/should_all_in_nearby_players_as_fast_as_possible___50ZwYtndy---0--100.truemap.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 100, fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=100)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        for enemyIndex in range(len(simHost.sim.players)):
            if enemyIndex != general.player:
                simHost.queue_player_moves_str(enemyIndex, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)

        holder: dict[str, FfaKillGatherResumeSnapshot] = {}

        def _observe() -> None:
            if 'snap' in holder:
                return
            state = bot.ffa_kill_gather_state
            if state is None or state.phase != want_phase:
                return
            if want_phase == 'gather' and state.gather_cursor < min_live_gather_cursor:
                return
            if general.player >= len(simHost.sim.moves):
                return
            queued = simHost.sim.moves[general.player]
            if queued is None:
                return
            # Full production txtmap: vision board + BotRendering bot_* resume
            # keys. dump_turn_data_to_string -> BotFfaKillGather.save_state emits
            # the PREMOVE-aligned cursors (pre-consume) for this same-turn consume.
            vision_map = simHost.get_player_map(general.player)
            resume_txtmap = (
                TextMapLoader.dump_map_to_string(vision_map) + '\n'
                + BotRendering.dump_turn_data_to_string(bot))
            written = BotFfaKillGather.save_state(bot)
            # Freeze turn-T ground truth. dump_map_to_string on the live sim_map
            # drops player/general metadata the txtmap loader needs, so deepcopy
            # the authoritative object instead of re-serializing it.
            holder['snap'] = FfaKillGatherResumeSnapshot(
                dump_turn=simHost.sim.turn,
                resume_txtmap=resume_txtmap,
                truth_map=copy.deepcopy(simHost.sim.sim_map),
                queued_src_index=queued.source.tile_index,
                queued_dst_index=queued.dest.tile_index,
                queued_half=bool(queued.move_half),
                written_phase=written['bot_ffa_kill_phase'],
                written_gather_cursor=int(written['bot_ffa_kill_gather_cursor']),
                written_hunt_cursor=int(written['bot_ffa_kill_route_cursor_base']),
                written_head_index=int(written['bot_ffa_kill_head']),
                written_enemy_index=int(written['bot_ffa_kill_enemy']),
                written_launch_index=int(written['bot_ffa_kill_launch']),
                written_deadline_turn=int(written['bot_ffa_kill_deadline']),
                written_owns_lock=(written['bot_ffa_kill_owns_lock'] == '1'))

        simHost.run_between_turns(_observe)

        self.begin_capturing_logging()
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=turns)
        self.assertNoFriendliesKilled(map, general)
        self.assertIn('snap', holder, f'{case_label}: never reached a committed {want_phase} step with a queued move')
        snap = holder['snap']

        # Reload the dumped txtmap through the real resume path (resume_data ->
        # BotFfaKillGather.load_state). Ground truth is the deep-copied turn-T map.
        vision_map_T, _genV = self.load_map_and_general_from_string(
            snap.resume_txtmap, snap.dump_turn, player_index=general.player, respect_undiscovered=True)

        # Flag must be patched during bot CONSTRUCTION: load_state runs inside
        # load_resume_data at EklipZBot init (bot_ek0x45.py:2313), before any move.
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            reloadHost = GameSimulatorHost(
                snap.truth_map, player_with_viewer=general.player, playerMapVision=vision_map_T,
                allAfkExceptMapPlayer=True)
            for enemyIndex in range(len(reloadHost.sim.players)):
                if enemyIndex != general.player:
                    reloadHost.queue_player_moves_str(enemyIndex, 'None')
            reloadBot = self.get_debug_render_bot(reloadHost, general.player)

        # Resumed cursors/head/phase must equal the WRITTEN PREMOVE-aligned values
        # (one step behind live post-consume state), never the skipped post value.
        rs = reloadBot.ffa_kill_gather_state
        self.assertIsNotNone(rs, f'{case_label}: resumed bot lost ffa_kill_gather_state')
        self.assertEqual(snap.written_phase, rs.phase, f'{case_label}: phase')
        self.assertEqual(snap.written_gather_cursor, rs.gather_cursor, f'{case_label}: gather_cursor')
        self.assertEqual(snap.written_hunt_cursor, rs.hunt_cursor, f'{case_label}: hunt_cursor')
        self.assertEqual(snap.written_head_index, rs.head_tile_index, f'{case_label}: head')
        self.assertEqual(snap.written_enemy_index, rs.enemy_index, f'{case_label}: enemy')
        self.assertEqual(snap.written_launch_index, rs.launch_tile_index, f'{case_label}: launch')
        self.assertEqual(snap.written_deadline_turn, rs.deadline_turn, f'{case_label}: deadline (never extended)')
        self.assertEqual(snap.written_owns_lock, rs.owns_exclusive_lock, f'{case_label}: lock ownership')

        # The FIRST resumed decision must reproduce the exact move that was
        # queued (pre-apply) at the dump turn - resume re-executes the step the
        # serialized pre-move board expects, it does not skip ahead one step.
        resumed_first: list[tuple[int, int, bool]] = []

        def _cap_reload_move() -> None:
            if general.player < len(reloadHost.sim.moves):
                qm = reloadHost.sim.moves[general.player]
                if qm is not None:
                    resumed_first.append((qm.source.tile_index, qm.dest.tile_index, bool(qm.move_half)))

        reloadHost.run_between_turns(_cap_reload_move)
        with patch.object(BotFfaKillGather, 'FFA_KILL_GATHER_ENABLED', True):
            reloadHost.execute_turn(run_real_time=False, turn_time=0.0)
        self.assertTrue(resumed_first, f'{case_label}: resumed sim produced no move')
        self.assertEqual(
            (snap.queued_src_index, snap.queued_dst_index, snap.queued_half),
            resumed_first[0],
            f'{case_label}: resumed first move {resumed_first[0]} != queued move at t{snap.dump_turn} '
            f'{(snap.queued_src_index, snap.queued_dst_index, snap.queued_half)}')

    def test_should_resume_committed_kill_gather_state_mid_gather(self) -> None:
        """Mid-GATHER serialization roundtrip (turns=20 reaches ~t120, inside the
        33-move gather window). Verifies the PREMOVE-aligned cursor/head/phase
        written by save_state round-trips and the resumed bot re-decides the exact
        queued gather step rather than recert-failing or skipping it."""
        self._ffa_kill_gather_resume_roundtrip(
            turns=20, want_phase='gather', min_live_gather_cursor=3,
            case_label='mid-gather')

    def test_should_resume_committed_kill_gather_state_mid_hunt(self) -> None:
        """Mid-HUNT serialization roundtrip (turns=41 reaches the hunt phase before
        the target dies). Exercises the vital head_tile_index rewind: during hunt
        the attack-stack head tracks the last confirmed step, so the PREMOVE
        pre-consume head must be what gets written or resume re-derives from the
        wrong stack position."""
        self._ffa_kill_gather_resume_roundtrip(
            turns=41, want_phase='hunt', min_live_gather_cursor=0,
            case_label='mid-hunt')

    def test_should_nonstop_all_in_weaker_player_when_three_left(self) -> None:
        """
        Live FFA turn 345 (replay CHZf7CtWk, bot p2 Human.exe): three players remain -
        us (c, 243), just terrible (f, 743, runaway leader), and Hckfjxjdn (h, 203).
        With f already winning the economy war, the only play is a nonstop losing-style
        all-in on the weaker remaining player h: keep h as the target and force
        is_all_in_losing every decision instead of wandering/gather-looping.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_nonstop_all_in_weaker_player_when_three_left___CHZf7CtWk---2--345.txtmap'
        # Replay ground truth aligned to bot-view coordinates (25x26 rot90cw view);
        # verified against all bot-visible cells in the fog snapshot.
        trueMapFile = 'GameContinuationEntries/should_nonstop_all_in_weaker_player_when_three_left___CHZf7CtWk---2--345.truemap.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 345, fill_out_tiles=True)
        # Hckfjxjdn is player 7 (h); bot_target_player=7 makes her the helper's enemy pick.
        hGeneral = map.generals[7]
        self.assertIsNotNone(hGeneral)
        self.assertTrue(hGeneral.isGeneral)
        self.assertEqual(7, hGeneral.player)
        self.assertEqual(7, enemyGeneral.player)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=345)
        # Tests/test_FFA.py::test_should_nonstop_all_in_weaker_player_when_three_left:
        # serialized island_ids orphan fog tiles and crash island rebuild
        # (full_island None); dropping the key rebuilds islands fresh, other resume state kept.
        rawMap.resume_data.pop('island_ids', None)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # Replay moves for the two living enemies (a,b,d,e,g are dead at turn 345).
        simHost.queue_player_moves_str(5, '6,20->7,20->7,19->8,19->9,19->10,19->11,19->12,19->12,18->13,18->14,18  15,19->14,19->14,18->14,17->15,17  1,24->0,24->0,25  3,24->3,25  5,24->5,25  6,24->6,25  2,23->2,22->2,21->3,21->3,20  1,22->0,22->0,21')
        simHost.queue_player_moves_str(7, 'none  none  2,6->2,5->2,4  none  2,4->1,4->0,4->0,5->0,6  none  0,6->0,7->0,8->1,8->1,9->1,10  none  1,10->1,9->2,9->3,9->4,9->5,9->6,9->6,8')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # Capture the bot's per-turn endgame decision AND the final dispatched move at the
        # place_move boundary (after split-hint/holding-clear), recording the destination
        # tile's pre-move owner/isCity so enemy and neutral-city captures are caught.
        # run_between_turns sees the pending map post-work, so the committed move is observed
        # where the bot actually places it rather than re-derived from post-turn state.
        placedMoves: list[FfaEndgamePlacedMove] = []
        botHost = simHost.bot_hosts[general.player]
        originalPlaceMoveFunc = botHost.place_move_func

        def recordPlacedMove(source: Tile, dest: Tile, move_half: bool = False) -> None:
            """Snapshots the bot's final dispatched move plus the destination's pre-move owner."""
            placedMoves.append(FfaEndgamePlacedMove(
                sourceX=source.x, sourceY=source.y,
                destX=dest.x, destY=dest.y,
                destPreOwner=dest.player, destIsCity=dest.isCity, moveHalf=move_half))
            originalPlaceMoveFunc(source, dest, move_half)

        botHost.place_move_func = recordPlacedMove

        observations: dict[int, FfaEndgameTurnObservation] = {}

        def watchEndgameDecisions() -> None:
            """Records this turn's endgame mode/target/all-in flag plus its dispatched move."""
            turn = simHost.sim.turn
            if turn in observations:
                return
            placed = placedMoves.pop(0) if placedMoves else None
            decision = BotFfaEndgame.get_state(bot).decision
            observations[turn] = FfaEndgameTurnObservation(
                turn=turn,
                mode=decision.mode.name,
                targetPlayer=decision.target_player,
                reason=decision.reason,
                isAllInLosing=bot.is_all_in_losing,
                p7Alive=not map.players[7].dead,
                moveSource=(placed.sourceX, placed.sourceY) if placed is not None else None,
                moveDest=(placed.destX, placed.destY) if placed is not None else None,
                moveDestPreOwner=placed.destPreOwner if placed is not None else None,
                moveDestIsCity=placed.destIsCity if placed is not None else False,
                moveHalf=placed.moveHalf if placed is not None else False)

        simHost.run_between_turns(watchEndgameDecisions)

        # proof: our a30 general garrison at (23,4) marches the 29-step west corridor,
        # absorbing border armies and punching h's thin h1-h4 tiles, capturing
        # Hckfjxjdn's general at (1,5) on move 29 (sim turn ~374, inside a 30-turn budget).
        # The scripted route needs correct general intel the fog view lacks, so this
        # regression instead asserts the fog-compatible forward all-in trajectory below.
        # simHost.queue_player_moves_str(general.player, '23,4->23,5->22,5->21,5->21,4->20,4->19,4->18,4->17,4->17,5->16,5->15,5->14,5->13,5->12,5->11,5->10,5->10,4->9,4->8,4->8,5->7,5->6,5->5,5->5,4->4,4->3,4->2,4->1,4->1,5')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=12)

        ordered = [observations[t] for t in sorted(observations)]
        self.assertGreater(len(ordered), 0, 'bot never produced an endgame decision')
        first = ordered[0]
        self.assertEqual('ALL_IN', first.mode, 'first bot decision must enter forced ALL_IN endgame mode')
        self.assertEqual('all_in_weaker', first.reason, 'first bot decision must pick the weaker-player all-in rule')
        self.assertEqual(7, first.targetPlayer, 'first bot decision must target Hckfjxjdn (p7/h), the weaker of the three remaining players')
        self.assertTrue(first.isAllInLosing, 'first bot decision must force is_all_in_losing: continuous losing-style all-in on the weaker player')
        self.assertIsNotNone(first.moveSource, 'first bot decision must produce a move, not a pass')
        # the forced all-in on p7 must hold on every decision while all three players remain alive
        for obs in ordered:
            if not obs.p7Alive:
                continue
            self.assertEqual('ALL_IN', obs.mode, f't{obs.turn}: endgame mode must stay ALL_IN while p7 lives')
            self.assertEqual(7, obs.targetPlayer, f't{obs.turn}: endgame target must stay Hckfjxjdn while she lives')
            self.assertTrue(obs.isAllInLosing, f't{obs.turn}: is_all_in_losing must stay forced while p7 lives')
        # the all-in must not detour: no neutral city and no runaway-leader (p5) tile captured
        for obs in ordered:
            if obs.moveDest is None:
                continue
            self.assertFalse(
                obs.moveDestIsCity and obs.moveDestPreOwner == -1,
                f't{obs.turn}: all-in must not capture a neutral city at {obs.moveDest}')
            self.assertNotEqual(
                5, obs.moveDestPreOwner,
                f't{obs.turn}: all-in must not capture runaway-leader p5 tiles at {obs.moveDest}')
        self.assertIsNone(winner)
        self.assertNoFriendliesKilled(map, general)
        # trajectory: within 12 turns the all-in must field a substantial committed stack
        # (>=20 army) in the west corridor x<=15,y<=8 (proof route reaches (14,5) by move 12).
        # The strongest viable spear may be our general after reserve accounting, so the
        # assertion is about a meaningful stack reaching the target corridor, not whether the
        # source tile happened to be the general.
        # h's general stays hidden in fog, so this asserts forward progress, not the capture.
        simMap = simHost.sim.sim_map
        reachedWest = any(
            tile.player == general.player and tile.army >= 20
            and tile.x <= 15 and tile.y <= 8
            for tile in simMap.get_all_tiles())
        self.assertTrue(
            reachedWest,
            'by turn 12 the all-in must field a >=20 stack at x<=15,y<=8')

    def _setup_ffa_capture_sim(
            self,
            mapFile: str,
            trueMapFile: str,
            turn: int,
            replayMoves: dict[int, str]) -> FfaCaptureSim:
        """
        Builds one fresh capture-ordering sim from the imported bot/true map
        pair. replayMoves queues each player's real replay move string; key -1
        is our own player whose line reproduces the live move as the active
        proof line. The true map is sim ground truth; the bot txtmap supplies
        vision/resume state.
        """
        simMap, general, _ = self.load_map_and_generals(trueMapFile, turn, fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=turn)

        # The serialized island_ids resume matrix can group fog-tracked tiles
        # whose resumed ownership the vision map no longer reproduces, leaving
        # rebuild_islands_from_ids with islands that never join a full island
        # (AttributeError on island.full_island.tile_count). Capture accounting
        # does not depend on island identity, so let the standard fresh island
        # build from map init stand instead of the serialized override.
        rawMap.resume_data.pop('island_ids', None)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # Resume-fidelity gap: on maps over 1000 tiles the periodic
        # inter-general rebuild is skipped 4 turns out of 5, so the fresh
        # pre-resume init_turn can reach get_gather_tiebreak_matrix with
        # intergeneral_analysis still None (a live bot carries it across turns;
        # resume cannot serialize it). Force the rebuild for the throwaway
        # init turn only, then restore the live throttle for the driven turns.
        originalInitialize = EklipZBot.initialize_from_map_for_first_time

        def initializeWithIntergeneralRebuild(bot: EklipZBot, map: MapBase) -> None:
            originalInitialize(bot, map)
            bot.is_lag_massive_map = False

        with patch.object(EklipZBot, 'initialize_from_map_for_first_time', initializeWithIntergeneralRebuild):
            simHost = GameSimulatorHost(
                simMap,
                player_with_viewer=general.player,
                playerMapVision=rawMap,
                allAfkExceptMapPlayer=True)
        simHost.get_bot(general.player).is_lag_massive_map = simMap.rows * simMap.cols > 1000
        for playerIndex, movesStr in replayMoves.items():
            simHost.queue_player_moves_str(general.player if playerIndex == -1 else playerIndex, movesStr)
        # our bot still analyzes every driven turn (required for the ordering
        # cases) but must not board-diverge after the replay move is consumed,
        # so pad its queue with no-ops for the extra ordering turns.
        for _ in range(3):
            simHost.queue_player_moves_str(general.player, 'None')
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)
        simHost.give_players_perfect_initial_city_information()
        return FfaCaptureSim(simHost=simHost, bot=bot, playerMap=playerMap, simMap=simMap)

    def _snapshot_ffa_capture(
            self,
            bot: EklipZBot,
            playerMap: MapBase,
            expectation: FfaCaptureExpectation) -> FfaCaptureSnapshot:
        """Reads the compact victim/killer fog pools, gather queues, and scores."""
        opponentTracker = bot.opponent_tracker
        victimTeam = opponentTracker._team_lookup_by_player[expectation.victimPlayer]
        killerTeam = opponentTracker._team_lookup_by_player[expectation.killerPlayer]
        victimStats = opponentTracker.current_team_cycle_stats[victimTeam]
        killerStats = opponentTracker.current_team_cycle_stats[killerTeam]
        victimPlayer = playerMap.players[expectation.victimPlayer]
        killerPlayer = playerMap.players[expectation.killerPlayer]
        victimQueue = opponentTracker.get_player_gather_queue(expectation.victimPlayer)
        killerQueue = opponentTracker.get_player_gather_queue(expectation.killerPlayer)
        killerFogTileCount, _, killerFogCityCount = opponentTracker.calculate_player_fog_tile_data(expectation.killerPlayer)
        return FfaCaptureSnapshot(
            victimScore=victimPlayer.score,
            victimTileCount=victimPlayer.tileCount,
            victimCityCount=victimPlayer.cityCount,
            killerScore=killerPlayer.score,
            killerTileCount=killerPlayer.tileCount,
            killerCityCount=killerPlayer.cityCount,
            victimFogArmy=victimStats.approximate_fog_army_available_total,
            victimFogArmyTrue=victimStats.approximate_fog_army_available_total_true,
            victimFogCityArmy=victimStats.approximate_fog_city_army,
            victimQueueAmounts=dict(victimQueue.get_amount_dict()),
            killerFogArmy=killerStats.approximate_fog_army_available_total,
            killerFogArmyTrue=killerStats.approximate_fog_army_available_total_true,
            killerFogCityArmy=killerStats.approximate_fog_city_army,
            killerQueueAmounts=dict(killerQueue.get_amount_dict()),
            killerPlaceholderCount=opponentTracker._capture_placeholder_counts[expectation.killerPlayer],
            killerFogNonCityCount=killerFogTileCount - killerFogCityCount)

    def _install_ffa_capture_transfer_spy(
            self,
            bot: EklipZBot,
            playerMap: MapBase,
            expectation: FfaCaptureExpectation,
            records: list[FfaCaptureTransfer],
            placeholderRecords: list[FfaCapturePlaceholderRemoval]) -> None:
        """
        Wraps _transfer_captured_player_fog_state to record entry/exit compact
        snapshots for the fixture's capturee/capturer pair, and wraps
        _remove_capture_placeholder_ones to record how many placeholder gather
        1s the delayed-transfer path consumed for the same pair.
        """
        opponentTracker = bot.opponent_tracker
        originalTransfer = opponentTracker._transfer_captured_player_fog_state
        originalRemovePlaceholders = opponentTracker._remove_capture_placeholder_ones

        def transferSpy(capturee: int, capturer: int) -> None:
            entry = self._snapshot_ffa_capture(bot, playerMap, expectation)
            originalTransfer(capturee, capturer)
            exitSnapshot = self._snapshot_ffa_capture(bot, playerMap, expectation)
            logbook.info(
                f'OT_FFA_CAPTURE_TRANSFER capturee={capturee} capturer={capturer} '
                f'victimFog entry={entry.victimFogArmy}/{entry.victimFogArmyTrue}/{entry.victimFogCityArmy} '
                f'exit={exitSnapshot.victimFogArmy}/{exitSnapshot.victimFogArmyTrue}/{exitSnapshot.victimFogCityArmy} '
                f'victimQueue entry={entry.victimQueueAmounts} exit={exitSnapshot.victimQueueAmounts}')
            records.append(FfaCaptureTransfer(
                capturee=capturee, capturer=capturer, entry=entry, exit=exitSnapshot))

        def placeholderSpy(capturee: int, capturer: int, snapshot: CaptureFogSnapshot) -> None:
            recordedBefore = opponentTracker._capture_placeholder_counts[capturer]
            onesBefore = opponentTracker.get_player_gather_queue(capturer).get_count(1)
            originalRemovePlaceholders(capturee, capturer, snapshot)
            placeholderRecords.append(FfaCapturePlaceholderRemoval(
                capturee=capturee,
                capturer=capturer,
                recordedBefore=recordedBefore,
                recordedAfter=opponentTracker._capture_placeholder_counts[capturer],
                onesBefore=onesBefore,
                onesAfter=opponentTracker.get_player_gather_queue(capturer).get_count(1)))

        opponentTracker._transfer_captured_player_fog_state = transferSpy
        opponentTracker._remove_capture_placeholder_ones = placeholderSpy

    def _make_ffa_deferred_capture_handler(
            self,
            playerMap: MapBase,
            deferredCaptures: list[tuple[int, int]],
            expectation: FfaCaptureExpectation,
            orderingName: str) -> typing.Callable[[int, int], None]:
        """
        Returns a handle_player_capture replacement that defers only the
        fixture's (killer -> victim) capture event and forwards every other
        capture with the real (capturerIdx, captureeIdx) signature.
        """
        originalHandleCapture = playerMap.handle_player_capture

        def deferredCaptureHandler(capturerIdx: int, captureeIdx: int) -> None:
            if capturerIdx == expectation.killerPlayer and captureeIdx == expectation.victimPlayer:
                deferredCaptures.append((capturerIdx, captureeIdx))
                logbook.info(
                    f'OT_FFA_CAPTURE_ORDER deferred handle_player_capture '
                    f'capturer={capturerIdx} capturee={captureeIdx} ordering={orderingName}')
                return
            originalHandleCapture(capturerIdx, captureeIdx)

        return deferredCaptureHandler

    def _drive_ffa_capture_ordering(
            self,
            sim: FfaCaptureSim,
            ordering: FfaCaptureOrdering,
            expectation: FfaCaptureExpectation) -> FfaCaptureRunResult:
        """
        Drives the import turn(s) for one event ordering and returns the hook
        snapshots, transfer records, post-capture physical outcome, and capture
        destination state. TEXT_BEFORE_UPDATE runs 2 turns, UPDATE_THEN_TEXT 2,
        and ANALYZE_THEN_TEXT 3 (the extra turn lets a full analyze run on the
        zeroed victim scoreboard before the capture text arrives).
        """
        bot = sim.bot
        playerMap = sim.playerMap
        simHost = sim.simHost

        # Preserve the victim's pre-kill non-general tile references on the sim
        # truth map BEFORE the first execute_turn resolves the capture; the
        # Tile objects persist and mutate, so their post-capture army sums give
        # the replay ground-truth transferred army.
        preKillVictimTiles: list[Tile] = [
            tile for tile in sim.simMap.tiles_by_index
            if tile.player == expectation.victimPlayer and not tile.isGeneral]

        hookSnapshots: list[FfaCaptureSnapshot] = []
        deferredCaptures: list[tuple[int, int]] = []
        transferRecords: list[FfaCaptureTransfer] = []
        placeholderRecords: list[FfaCapturePlaceholderRemoval] = []
        self._install_ffa_capture_transfer_spy(
            bot, playerMap, expectation, transferRecords, placeholderRecords)
        simHost.run_between_turns(
            lambda: hookSnapshots.append(self._snapshot_ffa_capture(bot, playerMap, expectation)))
        deferredHandler = self._make_ffa_deferred_capture_handler(
            playerMap, deferredCaptures, expectation, ordering.name)

        if ordering == FfaCaptureOrdering.TEXT_BEFORE_UPDATE:
            winner = simHost.execute_turn(run_real_time=False, turn_time=0.25)
            self.assertIsNone(winner)
        else:
            with patch.object(playerMap, 'handle_player_capture', deferredHandler):
                winner = simHost.execute_turn(run_real_time=False, turn_time=0.25)
            self.assertIsNone(winner)
            self.assertEqual(
                [(expectation.killerPlayer, expectation.victimPlayer)],
                deferredCaptures,
                'the fixture capture must be the only deferred event')

        # The capture turn has fully resolved (scores/tiles updated, turn
        # increments applied). Snapshot the physical outcome NOW: later driven
        # turns cross bonus-turn boundaries whose +1 city/general armies would
        # otherwise pollute the frozen ground-truth score asserts.
        postCapture = self._snapshot_ffa_capture(bot, playerMap, expectation)
        actualTrueTransferredArmy = sum(
            tile.army for tile in preKillVictimTiles
            if tile.player == expectation.killerPlayer)
        destTile = sim.simMap.GetTile(*expectation.victimGeneralPos)
        destState = FfaCaptureDestState(
            player=destTile.player,
            army=destTile.army,
            isCity=destTile.isCity,
            isGeneral=destTile.isGeneral)

        if ordering == FfaCaptureOrdering.TEXT_BEFORE_UPDATE:
            winner = simHost.execute_turn(run_real_time=False, turn_time=0.25)
            self.assertIsNone(winner)
        elif ordering == FfaCaptureOrdering.UPDATE_THEN_TEXT:
            for capturerIdx, captureeIdx in deferredCaptures:
                playerMap.handle_player_capture(capturerIdx, captureeIdx)
            deferredCaptures.clear()
            winner = simHost.execute_turn(run_real_time=False, turn_time=0.25)
            self.assertIsNone(winner)
        elif ordering == FfaCaptureOrdering.ANALYZE_THEN_TEXT:
            # a full analyze_turn runs on the zeroed victim scoreboard with no pending capture
            winner = simHost.execute_turn(run_real_time=False, turn_time=0.25)
            self.assertIsNone(winner)
            self.assertEqual(0, len(transferRecords), 'no transfer may run before the capture text arrives')
            for capturerIdx, captureeIdx in deferredCaptures:
                playerMap.handle_player_capture(capturerIdx, captureeIdx)
            deferredCaptures.clear()
            winner = simHost.execute_turn(run_real_time=False, turn_time=0.25)
            self.assertIsNone(winner)
        return FfaCaptureRunResult(
            hookSnapshots=hookSnapshots,
            transferRecords=transferRecords,
            placeholderRecords=placeholderRecords,
            postCapture=postCapture,
            destState=destState,
            preKillVictimTiles=preKillVictimTiles,
            actualTrueTransferredArmy=actualTrueTransferredArmy)

    def _assert_ffa_imported_state_matches_frozen(
            self,
            expectation: FfaCaptureExpectation,
            importedSnapshot: FfaCaptureSnapshot) -> None:
        """
        Validates the import reproduced the frozen live tracker footer: victim
        and killer scores, the victim's three fog pools, and its gather queue.
        Also sanity-checks that the frozen true annihilation sits inside the
        scoreboard-delta admissible interval.
        """
        self.assertEqual(expectation.victimScoreBefore, importedSnapshot.victimScore)
        self.assertEqual(expectation.killerScoreBefore, importedSnapshot.killerScore)
        self.assertEqual(expectation.fogArmyBefore, importedSnapshot.victimFogArmy)
        self.assertEqual(expectation.fogArmyTrueBefore, importedSnapshot.victimFogArmyTrue)
        self.assertEqual(expectation.fogCityArmyBefore, importedSnapshot.victimFogCityArmy)
        self.assertEqual(expectation.queueAmountsBefore, importedSnapshot.victimQueueAmounts)
        self.assertTrue(
            expectation.admissibleLossMin <= expectation.trueAnnihilatedArmy <= expectation.admissibleLossMax,
            'frozen true annihilation must sit inside the scoreboard-delta admissible interval')

    def _assert_ffa_capture_physical_outcome(
            self,
            result: FfaCaptureRunResult,
            expectation: FfaCaptureExpectation) -> None:
        """
        Asserts the replay ground-truth physical outcome captured right after
        the capture turn resolved: the victim's scoreboard zeroes, the killer's
        score matches the frozen post-capture value, every victim tile
        transfers, and the capture destination on the sim truth map is the
        killer's new city holding the surviving army. Reads the post-capture
        snapshot rather than end-state values so later driven turns cannot
        pollute the asserts with bonus-turn +1 armies.
        """
        postCapture = result.postCapture
        self.assertEqual(0, postCapture.victimScore)
        self.assertEqual(0, postCapture.victimTileCount)
        self.assertEqual(expectation.killerScoreAfter, postCapture.killerScore)
        self.assertEqual(
            expectation.victimTiles,
            postCapture.killerTileCount - result.hookSnapshots[0].killerTileCount,
            'every victim tile should transfer to the killer')
        self.assertEqual(expectation.killerPlayer, result.destState.player)
        self.assertTrue(result.destState.isCity)
        self.assertFalse(result.destState.isGeneral)
        self.assertEqual(expectation.generalAfterArmy, result.destState.army)

        # replay ground truth on the sim map itself: every pre-kill victim tile
        # (general excluded - it becomes the destination city asserted above)
        # is now killer-owned and holds the halved transferred army in total.
        self.assertTrue(
            all(tile.player == expectation.killerPlayer for tile in result.preKillVictimTiles),
            'every pre-kill victim tile should be killer-owned after the capture')
        self.assertEqual(
            expectation.trueTransferredArmy,
            result.actualTrueTransferredArmy,
            'halved army sitting on inherited tiles must equal replay ground truth')
        # transferred army minus the killer's score gain (income already zero
        # for both odd capture turns) is the true annihilation this update.
        self.assertEqual(
            expectation.trueAnnihilatedArmy,
            result.actualTrueTransferredArmy
            - (postCapture.killerScore - expectation.killerScoreBefore - expectation.expectedIncome),
            'transferred army minus killer score gain must equal the true annihilated army')

    def _assert_ffa_fog_state_preserved_pre_zero(
            self,
            expectation: FfaCaptureExpectation,
            beforeZero: FfaCaptureSnapshot,
            transferRecords: list[FfaCaptureTransfer]) -> None:
        """
        Asserts the fog-state transfer consumed the frozen pre-zero victim pools
        (the value a normal-order capture would have read) and cleared them.
        This is the ordering invariant the delayed-text cases must preserve; it
        currently fails for ANALYZE_THEN_TEXT because a zero-scoreboard analyze
        corrupts the pools before the capture text arrives.
        """
        self.assertEqual(1, len(transferRecords))
        record = transferRecords[0]
        self.assertEqual(expectation.victimPlayer, record.capturee)
        self.assertEqual(expectation.killerPlayer, record.capturer)
        entry = record.entry
        with self.subTest(field='fogArmy'):
            self.assertEqual(beforeZero.victimFogArmy, entry.victimFogArmy,
                             'transfer must read the pre-zero fog army pool')
        with self.subTest(field='fogArmyTrue'):
            self.assertEqual(beforeZero.victimFogArmyTrue, entry.victimFogArmyTrue,
                             'transfer must read the pre-zero true fog army pool')
        with self.subTest(field='fogCityArmy'):
            self.assertEqual(beforeZero.victimFogCityArmy, entry.victimFogCityArmy,
                             'transfer must read the pre-zero fog city army pool')
        with self.subTest(field='queue'):
            self.assertEqual(beforeZero.victimQueueAmounts, entry.victimQueueAmounts,
                             'transfer must read the pre-zero gather queue')
        exitSnapshot = record.exit
        self.assertEqual(0, exitSnapshot.victimFogArmy)
        self.assertEqual(0, exitSnapshot.victimFogArmyTrue)
        self.assertEqual(0, exitSnapshot.victimFogCityArmy)
        self.assertEqual({}, exitSnapshot.victimQueueAmounts)

    def _assert_ffa_capture_combat_accounting(
            self,
            ordering: FfaCaptureOrdering,
            expectation: FfaCaptureExpectation,
            bot: EklipZBot,
            playerMap: MapBase,
            result: FfaCaptureRunResult) -> None:
        """
        Asserts the production combat-aware transfer accounting for one ordering:
        the recorded loss interval matches the frozen admissible bounds with the
        true replay annihilation inside it, the killer's three fog pools gain
        exactly the conservative expected transfers (missed bonus ticks are 0
        for both fixtures: capture turns 137/131 are odd and the last analyzed
        turn equals the capture turn), the victim queue moves per-entry ceil-
        halved with placeholder 1s removed first, and the final killer queue
        does not double-count the inherited fog land.
        """
        opponentTracker = bot.opponent_tracker
        self.assertEqual(1, len(result.transferRecords))
        record = result.transferRecords[0]

        lossEstimate = opponentTracker.last_capture_army_losses.get(expectation.victimPlayer)
        self.assertIsNotNone(lossEstimate, 'transfer must record a capture army loss estimate')
        with self.subTest(field='lossMinimum'):
            self.assertEqual(expectation.admissibleLossMin, lossEstimate.minimum)
        with self.subTest(field='lossMaximum'):
            self.assertEqual(expectation.admissibleLossMax, lossEstimate.maximum)
        with self.subTest(field='lossAssumed'):
            self.assertEqual(expectation.admissibleLossMin, lossEstimate.assumed)
        with self.subTest(field='lossConsistent'):
            self.assertTrue(lossEstimate.consistent)
        with self.subTest(field='trueLossInsideInterval'):
            self.assertTrue(
                lossEstimate.minimum <= expectation.trueAnnihilatedArmy <= lossEstimate.maximum,
                'replay ground-truth annihilation must sit inside the production interval')

        entry = record.entry
        exitSnapshot = record.exit
        with self.subTest(field='fogArmyTransfer'):
            self.assertEqual(
                expectation.expectedFogArmyTransfer,
                exitSnapshot.killerFogArmy - entry.killerFogArmy,
                'killer fog army delta must equal the conservative transferred amount')
        with self.subTest(field='fogArmyTrueTransfer'):
            self.assertEqual(
                expectation.expectedFogArmyTrueTransfer,
                exitSnapshot.killerFogArmyTrue - entry.killerFogArmyTrue,
                'killer true fog army delta must equal the conservative transferred amount')
        with self.subTest(field='fogCityTransfer'):
            self.assertEqual(
                expectation.expectedCityTransfer,
                exitSnapshot.killerFogCityArmy - entry.killerFogCityArmy,
                'killer fog city delta must equal the conservative transferred amount')

        # per-entry ceil halving: every victim queue size maps to exactly one
        # halved size on the killer, never an aggregate rounding of the sum.
        expectedHalvedCounts: dict[int, int] = {}
        for tileSize, count in expectation.queueAmountsBefore.items():
            halvedSize = tileSize - tileSize // 2
            expectedHalvedCounts[halvedSize] = expectedHalvedCounts.get(halvedSize, 0) + count
        for size in set(entry.killerQueueAmounts) | set(exitSnapshot.killerQueueAmounts):
            expectedDelta = expectedHalvedCounts.get(size, 0)
            actualDelta = exitSnapshot.killerQueueAmounts.get(size, 0) - entry.killerQueueAmounts.get(size, 0)
            with self.subTest(field=f'queueSize{size}'):
                self.assertEqual(expectedDelta, actualDelta,
                                 'killer queue delta must be exactly the per-entry ceil-halved victim queue')

        # the removal helper is invoked for every snapshot transfer but only does
        # work once the zero update has been analyzed; filter to effective removals.
        effectiveRemovals = [
            removal for removal in result.placeholderRecords
            if removal.recordedBefore != removal.recordedAfter]
        if ordering == FfaCaptureOrdering.ANALYZE_THEN_TEXT:
            # the zeroed-victim analyze already ran, so the killer's missing-tile
            # check topped up placeholder 1s for inherited land; the transfer
            # must consume them before inserting the real halved entries.
            self.assertEqual(1, len(effectiveRemovals))
            removal = effectiveRemovals[0]
            self.assertEqual(expectation.victimPlayer, removal.capturee)
            self.assertEqual(expectation.killerPlayer, removal.capturer)
            with self.subTest(field='placeholderOnesRemoved'):
                self.assertEqual(
                    removal.onesBefore - removal.onesAfter,
                    removal.recordedBefore - removal.recordedAfter,
                    'removed placeholder ones must match the decremented recorded count')
                self.assertGreater(removal.onesBefore, removal.onesAfter,
                                   'the zeroed-victim analyze must have appended placeholder ones')
            with self.subTest(field='transferEntryOnesPostRemoval'):
                self.assertEqual(
                    removal.onesAfter,
                    entry.killerQueueAmounts.get(1, 0),
                    'transfer entry must observe the killer queue after placeholder removal')
        else:
            self.assertEqual(
                0, len(effectiveRemovals),
                'normal-order captures must not remove placeholder ones (zero update not yet analyzed)')

        # final state: queue length minus the killer's fog non-city tile count is
        # the stale-entry excess. The halved victim entries legitimately carry the
        # victim's own queue staleness across, so the meaningful no-double-count
        # invariant is that the excess does not keep GROWING after the transfer
        # exit snapshot: later analyzes may only top the queue up to the real fog
        # tile count, never pile placeholder 1s on top of the halved entries.
        finalHook = result.hookSnapshots[-1]
        excessAtExit = (
            sum(exitSnapshot.killerQueueAmounts.values()) - exitSnapshot.killerFogNonCityCount)
        excessAtEnd = (
            sum(finalHook.killerQueueAmounts.values()) - finalHook.killerFogNonCityCount)
        with self.subTest(field='noDoubleCountedInheritedLand'):
            self.assertLessEqual(
                excessAtEnd,
                excessAtExit + 2,
                f'killer queue excess grew post-transfer {excessAtExit} -> {excessAtEnd} '
                f'(queue {sum(finalHook.killerQueueAmounts.values())} vs fog non-city {finalHook.killerFogNonCityCount}) '
                '- inherited land must not be queued twice (placeholders + halved entries)')

    def test_should_preserve_captured_fog_army_after_late_capture_message(self) -> None:
        """
        Live FFA capture-ordering regression (replay bVK2OP478, observer p2,
        turns 136->137). p0's 44-stack at 6,15 captures victim p6's fog-hidden
        general at 6,16 (defense 34, sent 43, surviving city army 9). Ground
        truth: killer score 132->152, victim 114->0 across 52 tiles, true
        transferred army 54, odd remaining transferred tiles 28. The victim's
        frozen tracker footer pools are fog29/true30/city22 with queue
        4x2|41x1; third-party score deficits total 4 so the production
        conservative interval widens to 22..44 (true 34 inside). All
        eight players' real replay moves are scripted so the board reproduces
        exactly, and our own queued 2,11->2,12 line IS the live move kept as
        the active proof line. The ordering cases assert the frozen pre-zero
        fog state survives and the combat-aware loss/transfer math lands.
        """
        expectation = FfaCaptureExpectation(
            victimPlayer=6,
            killerPlayer=0,
            killerScoreBefore=132,
            killerScoreAfter=152,
            victimScoreBefore=114,
            victimTiles=52,
            defenderArmy=34,
            generalAfterArmy=9,
            victimGeneralPos=(6, 16),
            fogArmyBefore=29,
            fogArmyTrueBefore=30,
            fogCityArmyBefore=22,
            queueAmountsBefore={1: 41, 2: 4},
            admissibleLossMin=22,
            admissibleLossMax=44,
            trueAnnihilatedArmy=34,
            trueTransferredArmy=54,
            expectedIncome=0,
            expectedOtherArmyLossBudget=4,
            expectedCityTransfer=0,
            expectedFogArmyTransfer=15,
            expectedFogArmyTrueTransfer=15)
        logbook.info(
            f'OT_FFA_CAPTURE_EXPECTATION victim={expectation.victimPlayer} killer={expectation.killerPlayer} '
            f'admissibleLoss={expectation.admissibleLossMin}..{expectation.admissibleLossMax} '
            f'trueAnnihilated={expectation.trueAnnihilatedArmy} trueTransferred={expectation.trueTransferredArmy} '
            f'income={expectation.expectedIncome} otherLossBudget={expectation.expectedOtherArmyLossBudget} '
            f'expectedTransfers city={expectation.expectedCityTransfer} '
            f'fog={expectation.expectedFogArmyTransfer} true={expectation.expectedFogArmyTrueTransfer}')

        mapFile = 'GameContinuationEntries/should_preserve_captured_fog_army_after_late_capture_message___bVK2OP478---2--136.txtmap'
        trueMapFile = 'GameContinuationEntries/should_preserve_captured_fog_army_after_late_capture_message___bVK2OP478---2--136.truemap.txtmap'
        replayMoves = {
            0: '6,15->6,16',
            1: '7,7->6,7z',
            -1: '2,11->2,12',
            3: '25,26->25,27',
            4: '20,2->20,1',
            7: '22,9->22,10'}

        for ordering in FfaCaptureOrdering:
            with self.subTest(ordering=ordering):
                sim = self._setup_ffa_capture_sim(mapFile, trueMapFile, 136, replayMoves)
                importedSnapshot = self._snapshot_ffa_capture(sim.bot, sim.playerMap, expectation)
                result = self._drive_ffa_capture_ordering(sim, ordering, expectation)
                self._assert_ffa_imported_state_matches_frozen(expectation, importedSnapshot)
                self._assert_ffa_capture_physical_outcome(result, expectation)
                self._assert_ffa_fog_state_preserved_pre_zero(
                    expectation, result.hookSnapshots[0], result.transferRecords)
                self._assert_ffa_capture_combat_accounting(
                    ordering, expectation, sim.bot, sim.playerMap, result)

    def test_should_account_for_annihilated_army_before_ffa_capture_transfer(self) -> None:
        """
        Live FFA capture regression (replay 2ou8wZEPy, observer p3, turns
        130->131) covering annihilated-army-before-transfer accounting. p1's
        26-stack at 24,18 captures victim p4's fog-hidden general at 24,17
        (defense 3, sent 25, surplus 22) while victim p4 simultaneously spends
        1 army attacking p1 elsewhere, so total victim/killer annihilation this
        update is 4, not 3. Ground truth: killer score 64->90, victim 53->0
        across 18 tiles, true transferred army 30, odd remaining transferred
        tiles 10. The victim's frozen tracker footer pools are fog9/true16/
        city19 with queue 25x1; third-party score deficits total 8 so the
        production conservative interval widens to 0..11 (true 4 inside). All
        eight players' real replay moves are scripted so the board
        reproduces exactly, including the victim's own counterattack move, and
        our own queued 5,9->5,8 line IS the live move kept as the active proof
        line. The ordering cases share the same driver and assert the
        annihilation-subtracted transfer math against the frozen interval.
        """
        expectation = FfaCaptureExpectation(
            victimPlayer=4,
            killerPlayer=1,
            killerScoreBefore=64,
            killerScoreAfter=90,
            victimScoreBefore=53,
            victimTiles=18,
            defenderArmy=3,
            generalAfterArmy=22,
            victimGeneralPos=(24, 17),
            fogArmyBefore=9,
            fogArmyTrueBefore=16,
            fogCityArmyBefore=19,
            queueAmountsBefore={1: 25},
            admissibleLossMin=0,
            admissibleLossMax=11,
            trueAnnihilatedArmy=4,
            trueTransferredArmy=30,
            expectedIncome=0,
            expectedOtherArmyLossBudget=8,
            expectedCityTransfer=10,
            expectedFogArmyTransfer=5,
            expectedFogArmyTrueTransfer=8)
        logbook.info(
            f'OT_FFA_CAPTURE_EXPECTATION victim={expectation.victimPlayer} killer={expectation.killerPlayer} '
            f'admissibleLoss={expectation.admissibleLossMin}..{expectation.admissibleLossMax} '
            f'trueAnnihilated={expectation.trueAnnihilatedArmy} trueTransferred={expectation.trueTransferredArmy} '
            f'income={expectation.expectedIncome} otherLossBudget={expectation.expectedOtherArmyLossBudget} '
            f'expectedTransfers city={expectation.expectedCityTransfer} '
            f'fog={expectation.expectedFogArmyTransfer} true={expectation.expectedFogArmyTrueTransfer}')

        mapFile = 'GameContinuationEntries/should_account_for_annihilated_army_before_ffa_capture_transfer___2ou8wZEPy---3--130.txtmap'
        trueMapFile = 'GameContinuationEntries/should_account_for_annihilated_army_before_ffa_capture_transfer___2ou8wZEPy---3--130.truemap.txtmap'
        replayMoves = {
            1: '24,18->24,17',
            2: '17,3->16,3',
            -1: '5,9->5,8',
            4: '22,17->22,18',
            6: '11,16->10,16',
            7: '3,19->3,18'}

        for ordering in FfaCaptureOrdering:
            with self.subTest(ordering=ordering):
                sim = self._setup_ffa_capture_sim(mapFile, trueMapFile, 130, replayMoves)
                importedSnapshot = self._snapshot_ffa_capture(sim.bot, sim.playerMap, expectation)
                result = self._drive_ffa_capture_ordering(sim, ordering, expectation)
                self._assert_ffa_imported_state_matches_frozen(expectation, importedSnapshot)
                self._assert_ffa_capture_physical_outcome(result, expectation)
                self._assert_ffa_fog_state_preserved_pre_zero(
                    expectation, result.hookSnapshots[0], result.transferRecords)
                self._assert_ffa_capture_combat_accounting(
                    ordering, expectation, sim.bot, sim.playerMap, result)

    def test_should_attack_aggressor_without_overgathering_or_abandoning_general(self):
        """
        Live FFA turn 391 (replay nPZSvoa1I, bot p5 Human.exe): three players remain -
        us (f, 908, econ 260), roastedtomatoes (b, p1, aggression 590, econ 151), and
        Eason_ (d, p3, passive, econ 189). Ahead of each enemy but behind their combined
        economy, the policy must ALL_IN the aggressive p1 (all_in_middle), reserve only
        enough defense at the general against p3, then attack p1 with the excess - not
        hoard ~1000 army onto the general until p1 strips and kills it.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_attack_aggressor_without_overgathering_or_abandoning_general___nPZSvoa1I---5--391.txtmap'
        # Replay ground truth aligned to bot-view coordinates (25x32 transpose view).
        trueMapFile = 'GameContinuationEntries/should_attack_aggressor_without_overgathering_or_abandoning_general___nPZSvoa1I---5--391.truemap.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 391, fill_out_tiles=True)
        p1General = map.generals[1]
        self.assertIsNotNone(p1General)
        self.assertEqual(1, p1General.player)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=391)

        # The serialized island_ids resume matrix can group fog-tracked tiles
        # whose resumed ownership the vision map no longer reproduces, leaving
        # rebuild_islands_from_ids with islands that never join a full island
        # (AttributeError on island.full_island.tile_count). Let the standard
        # fresh island build from map init stand instead of the serialized
        # override, same as the other FFA continuation tests.
        rawMap.resume_data.pop('island_ids', None)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # replay moves for the 25 turns after turn 391
        simHost.queue_player_moves_str(1, '12,28->12,27->13,27  16,22->15,22->15,21  13,27->13,26->14,26->15,26->16,26->17,26->18,26->19,26->20,26  21,20->22,20  20,26->19,26->18,26->17,26->16,26->16,25->16,24->16,23->15,23->15,22  14,22->15,22->15,21->15,20')  # replay moves: roastedtomatoes
        simHost.queue_player_moves_str(3, 'None')  # Eason_ recorded no successful moves (passive p3)
        # simHost.queue_player_moves_str(general.player, '24,17->24,18  10,15->11,15->11,14  15,14->16,14  15,15->16,15  24,12->24,13->23,13  23,26->23,25->23,24->23,23->23,22->23,21->24,21  24,22->24,21->24,20->24,19->24,18  10,14->11,14->12,14->12,13->12,12->13,12->14,12->15,12->16,12')  # replay line for Human.exe
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # Fixture correctness: every cell the bot can currently see (playerMap.visible,
        # the live fog-of-war vision the sim computed from the true map) must match the
        # transpose-emitted true map at the same coords on terrain/ownership/army. The
        # bot's recorded belief lives in rawMap; fog-'D'/inferred cells are excluded
        # because the bot legitimately guesses them. Guards the transpose orientation.
        mismatches: list[str] = []
        visibleChecked = 0
        for trueTile in map.tiles_by_index:
            if trueTile is None:
                continue
            visionTile = playerMap.tiles_by_index[trueTile.tile_index]
            if visionTile is None or not visionTile.visible:
                continue
            botTile = rawMap.tiles_by_index[trueTile.tile_index]
            visibleChecked += 1
            if (trueTile.player != botTile.player or trueTile.army != botTile.army
                    or trueTile.isCity != botTile.isCity or trueTile.isMountain != botTile.isMountain):
                mismatches.append(f'{trueTile.x},{trueTile.y}')
        self.assertEqual([], mismatches,
                         f'{len(mismatches)} visible-cell mismatches vs truemap: {mismatches[:10]}')
        self.assertGreater(visibleChecked, 0, 'no bot-visible cells compared; transpose fixture unverified')

        # Capture the bot's per-turn endgame decision + computed general reserve AND the
        # final dispatched move at the place_move boundary (pre-apply), recording the
        # source stack's army/general flag and the destination's pre-owner so p1 attacks,
        # p3 non-target captures, and reserve retention are all observable.
        placedMoves: list[FfaEndgameReservePlacedMove] = []
        botHost = simHost.bot_hosts[general.player]
        originalPlaceMoveFunc = botHost.place_move_func

        def recordPlacedMove(source: Tile, dest: Tile, move_half: bool = False) -> None:
            """Snapshots the bot's final dispatched move plus source army and dest pre-owner."""
            placedMoves.append(FfaEndgameReservePlacedMove(
                fromGeneral=source.isGeneral,
                sourceArmy=source.army,
                destX=dest.x, destY=dest.y,
                destPreOwner=dest.player, destIsCity=dest.isCity, moveHalf=move_half))
            originalPlaceMoveFunc(source, dest, move_half)

        botHost.place_move_func = recordPlacedMove

        observations: dict[int, FfaEndgameReserveObservation] = {}

        def watchEndgameDecisions() -> None:
            """Records this turn's endgame mode/target/reserve plus its dispatched move."""
            turn = simHost.sim.turn
            if turn in observations:
                return
            placed = placedMoves.pop(0) if placedMoves else None
            decision = BotFfaEndgame.get_state(bot).decision
            # force this turn's reserve so the retention assert is meaningful even before
            # the production call sites are fully wired; same-turn it is a cache hit.
            BotFfaEndgame.update_general_reserve(bot)
            reserve = BotFfaEndgame.get_general_reserve(bot)
            observations[turn] = FfaEndgameReserveObservation(
                turn=turn,
                mode=decision.mode.name,
                targetPlayer=decision.target_player,
                reason=decision.reason,
                isAllInLosing=bot.is_all_in_losing,
                p1Alive=not map.players[1].dead,
                reserveRequired=reserve.required_army,
                reserveSatisfied=reserve.satisfied,
                moveFromGeneral=placed.fromGeneral if placed is not None else False,
                moveSourceArmy=placed.sourceArmy if placed is not None else 0,
                moveDestPreOwner=placed.destPreOwner if placed is not None else None,
                moveHalf=placed.moveHalf if placed is not None else False,
                moveDestIsCity=placed.destIsCity if placed is not None else False,
                moveDest=(placed.destX, placed.destY) if placed is not None else None)

        simHost.run_between_turns(watchEndgameDecisions)

        # proof: pending - the lead's sketched route (gen 61 + adjacent 287-stack donate to
        # the general, then a forward stack advances into p1) needs the real computed
        # reserve before a scripted kill line can be derived; not pinned yet.

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=12)

        ordered = [observations[t] for t in sorted(observations)]
        self.assertGreater(len(ordered), 0, 'bot never produced an endgame decision')
        first = ordered[0]
        self.assertEqual('ALL_IN', first.mode, 'first bot decision must enter forced ALL_IN')
        self.assertEqual('all_in_middle', first.reason, 'ahead of each but behind sum -> middle all-in')
        self.assertEqual(1, first.targetPlayer, 'must target roastedtomatoes (p1), the aggressor')
        self.assertTrue(first.isAllInLosing, 'must force is_all_in_losing')
        # the forced all-in on p1 must hold on every decision while p1 lives
        for obs in ordered:
            if not obs.p1Alive:
                continue
            self.assertEqual('ALL_IN', obs.mode, f't{obs.turn}: mode must stay ALL_IN while p1 lives')
            self.assertEqual(1, obs.targetPlayer, f't{obs.turn}: target must stay roastedtomatoes p1')
            self.assertEqual('all_in_middle', obs.reason, f't{obs.turn}: reason must stay all_in_middle')
            self.assertTrue(obs.isAllInLosing, f't{obs.turn}: is_all_in_losing must stay forced')
        # the forced attack must never capture a non-target (p3 Eason_) tile
        for obs in ordered:
            self.assertNotEqual(
                3, obs.moveDestPreOwner,
                f't{obs.turn}: must not capture non-target p3 tile at {obs.moveDest}')
        # every general-sourced move must retain the computed reserve (anti general-strip)
        for obs in ordered:
            if not obs.moveFromGeneral or obs.moveDestPreOwner is None:
                continue
            retained = obs.moveSourceArmy - (
                (obs.moveSourceArmy - 1) // 2 if obs.moveHalf else obs.moveSourceArmy - 1)
            self.assertGreaterEqual(
                retained, obs.reserveRequired,
                f't{obs.turn}: general move must retain reserve {obs.reserveRequired} (retained {retained})')
        # trajectory: by <=12 turns a substantial (>=20 army) stack must attack a p1 tile,
        # not just gather-hoard or send forward crumbs - the anti-overgathering signal.
        substantialP1Attack = any(
            obs.moveDestPreOwner == 1 and obs.moveSourceArmy >= 20 for obs in ordered)
        self.assertTrue(
            substantialP1Attack,
            'by turn 12 the all-in must send a >=20 stack into p1-owned territory')
        self.assertIsNone(winner)
        self.assertNoFriendliesKilled(map, general)

    def test_should_reserve_nearby_defense_after_enemy_finds_general(self) -> None:
        """
        Live FFA t179 (replay 50ZwYtndy): Meemo (p3) reveals our general at
        (22,19) by moving 24,18 -> 23,18 on the first post-import turn. With
        >2 living teams the bot should reserve nearby defense - a mobile stack
        within 7 owned steps of the general - once the enemy knows our
        general, then return to offense. Runs 9 turns (through t188); p0 is
        never scripted, the bot chooses its own moves through the real
        pipeline. mobile_near7 excludes the general tile itself so the initial
        garrison cannot trivially satisfy the threshold.
        """
        result = self._run_general_reveal_defense_case(turns=9)
        self.assertNoFriendliesKilled(result.simMap, result.general)
        snapshot = result.snapshots[188]
        self.assertGreaterEqual(
            snapshot.mobile_near7, 30,
            f't188 strongest single mobile tile within 7 of general too small: {snapshot}')
        self.assertTrue(
            snapshot.enemy_knows_general,
            f't188 enemy should know our general after the 24,18->23,18 reveal: {snapshot}')

    def test_should_reinforce_nearby_defense_for_delayed_all_in(self) -> None:
        """
        Same t179 fixture over 35 turns (through t214): the early reinforcement
        (t188 mobile_near7 >= 30) must be followed by a SINGLE COMBINED mobile
        stack - strongest one tile, not an army sum - of >= 60 within 5 owned
        steps of the general for the delayed all-in, with all friendlies
        alive. p0 unscripted.
        """
        result = self._run_general_reveal_defense_case(turns=35)
        self.assertNoFriendliesKilled(result.simMap, result.general)
        early = result.snapshots[188]
        self.assertGreaterEqual(
            early.mobile_near7, 30,
            f't188 strongest single mobile tile within 7 of general too small: {early}')
        final = result.snapshots[214]
        self.assertGreaterEqual(
            final.mobile_near5, 60,
            f't214 strongest single COMBINED mobile tile within 5 of general too small: {final}')

    def test_should_attack_predicted_general_during_ffa_all_in(self):
        """Live FFA t307 (HSio7TqPf): only p3/p5/p6 remain; we are economically ahead
        of pink (p5) but behind pink+Squid combined, so the policy must stay in ALL_IN
        on p5 and route its strongest stack to the predicted p5 general at (3,16), not
        spend the all-in nibbling whichever pink/non-target tile is nearest. The first
        imported move replays the real t307 gather so production resumes from the same
        t308 state the live bot had."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_attack_predicted_general_during_ffa_all_in___HSio7TqPf---3--307.txtmap'
        trueMapFile = 'GameContinuationEntries/should_attack_predicted_general_during_ffa_all_in___HSio7TqPf---3--307.truemap.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 307, fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=307)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # Replay the real t307 move once; the production bot chooses every move after t308.
        simHost.queue_player_moves_str(general.player, '5,0->4,0')
        simHost.queue_player_moves_str(5, '2,23->2,22->2,21->2,20->1,20->1,19->1,18->1,17->1,16->2,16->3,16->3,15->4,15->4,14->4,13->3,13->3,12->3,11->3,10->3,9->4,9->3,9->3,10->2,10->1,10->0,10')  # replay moves: sjpsjpsjp
        simHost.queue_player_moves_str(6, 'none  19,24->20,24->20,23->20,22->20,23->19,23->18,23  none  18,23->19,23->19,22->19,21  none  none  none  none  none  none  none  none  none  14,8->15,8->15,7->15,6->15,5->14,5')  # replay moves: Squid
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        # Capture the endgame decision plus the committed route's current endpoint and the
        # final dispatched move. routeDest is the production curPath tail, so it detects
        # the live failure where a nominally target-pinned all-in actually commits to the
        # closest arbitrary pink frontier instead of the predicted-general hunt route.
        placedMoves: list[FfaEndgameDetailedMove] = []
        botHost = simHost.bot_hosts[general.player]
        originalPlaceMoveFunc = botHost.place_move_func

        def recordPlacedMove(source: Tile, dest: Tile, move_half: bool = False) -> None:
            """Snapshots the bot's final dispatched move plus source army and dest pre-owner."""
            placedMoves.append(FfaEndgameDetailedMove(
                fromGeneral=source.isGeneral,
                sourceX=source.x, sourceY=source.y, sourceArmy=source.army,
                destX=dest.x, destY=dest.y,
                destPreOwner=dest.player, destIsCity=dest.isCity, moveHalf=move_half))
            originalPlaceMoveFunc(source, dest, move_half)

        botHost.place_move_func = recordPlacedMove
        observations: dict[int, FfaEndgameDetailedObservation] = {}

        def watchEndgameDecisions() -> None:
            """Records this turn's endgame mode/target/reserve, route endpoint, and move."""
            turn = simHost.sim.turn
            if turn in observations:
                return
            placed = placedMoves.pop(0) if placedMoves else None
            state = BotFfaEndgame.get_state(bot)
            decision = state.decision
            reserve = BotFfaEndgame.get_general_reserve(bot)
            predicted = bot.targetPlayerExpectedGeneralLocation
            routeDest = bot.curPath.tail.tile if bot.curPath is not None and bot.curPath.tail is not None else None
            observations[turn] = FfaEndgameDetailedObservation(
                turn=turn,
                mode=decision.mode.name,
                targetPlayer=decision.target_player,
                reason=decision.reason,
                isAllInLosing=bot.is_all_in_losing,
                defenseOverride=bot.defense_override_move,
                reserveRequired=reserve.required_army,
                reserveSatisfied=reserve.satisfied,
                predictedGeneral=(predicted.x, predicted.y) if predicted is not None else None,
                routeDest=(routeDest.x, routeDest.y) if routeDest is not None else None,
                moveFromGeneral=placed.fromGeneral if placed is not None else False,
                moveSource=(placed.sourceX, placed.sourceY) if placed is not None else None,
                moveSourceArmy=placed.sourceArmy if placed is not None else 0,
                moveDest=(placed.destX, placed.destY) if placed is not None else None,
                moveDestPreOwner=placed.destPreOwner if placed is not None else None,
                moveDestIsCity=placed.destIsCity if placed is not None else False,
                moveHalf=placed.moveHalf if placed is not None else False)

        simHost.run_between_turns(watchEndgameDecisions)

        # proof: after the scripted t307 gather, the 30-stack on (4,0) walks through the
        # general and down the west corridor to the predicted p5 general at (3,16). The
        # real bot should choose this same committed line in fog; it must not stop at the
        # first pink frontier at (5,4) and wander nearby target land.
        # simHost.queue_player_moves_str(general.player, '5,0->4,0  4,0->4,1->4,2->4,3->4,4->5,4->6,4->6,5->6,6->6,7->5,7->4,7->4,8->4,9->3,9->3,10->3,11->3,12->3,13->3,14->3,15->3,16')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=21)

        ordered = [observations[t] for t in sorted(observations) if t >= 308]
        self.assertGreater(len(ordered), 0, 'bot never produced an endgame decision after the t307 replay move')
        first = ordered[0]
        self.assertEqual('ALL_IN', first.mode, 'first production decision must stay in forced ALL_IN')
        self.assertEqual('all_in_weaker', first.reason, 'ahead of p5 but behind p5+p6 -> weaker-player all-in')
        self.assertEqual(5, first.targetPlayer, 'must target pink sjpsjpsjp (p5), not Squid p6')
        self.assertEqual((3, 16), first.predictedGeneral, 'must keep the fog p5 general prediction at (3,16)')
        self.assertEqual(
            (3, 16), first.routeDest,
            'the committed all-in route must hunt the predicted p5 general, not the nearest pink tile')
        for obs in ordered:
            self.assertEqual('ALL_IN', obs.mode, f't{obs.turn}: mode must stay ALL_IN while p5 lives')
            self.assertEqual(5, obs.targetPlayer, f't{obs.turn}: target must stay pink p5')
            if obs.routeDest is not None:
                self.assertEqual(
                    (3, 16), obs.routeDest,
                    f't{obs.turn}: every committed attack route must stay pinned to the predicted p5 general')
            self.assertNotEqual(
                6, obs.moveDestPreOwner,
                f't{obs.turn}: forced p5 all-in must not capture non-target p6 tile at {obs.moveDest}')
            self.assertFalse(
                obs.moveDestPreOwner == -1 and obs.moveDestIsCity,
                f't{obs.turn}: forced p5 all-in must not detour to neutral city at {obs.moveDest}')
            if obs.moveFromGeneral and obs.moveDestPreOwner is not None:
                retained = obs.moveSourceArmy - (
                    (obs.moveSourceArmy - 1) // 2 if obs.moveHalf else obs.moveSourceArmy - 1)
                self.assertGreaterEqual(
                    retained, obs.reserveRequired,
                    f't{obs.turn}: general move must retain reserve {obs.reserveRequired} (retained {retained})')
        self.assertTrue(
            any(obs.moveDestPreOwner == 5 and obs.moveSourceArmy >= 20 for obs in ordered),
            'a substantial stack must attack p5 along the predicted-general route, not wander target land')
        self.assertIsNone(winner)
        self.assertNoFriendliesKilled(map, general)

    def test_should_defend_general_during_ffa_all_in(self):
        """Live FFA t344 (HSio7TqPf): p5's stack at (6,4) has a three-turn kill path
        to our (4,3) general. The mode is still the ordinary p5 all-in, so the bot
        must answer the threat - moving the (6,3) city stack to the (5,3) block -
        instead of sending the unrelated (0,11)->(0,10) FFA advance and dying. Only
        true losing/all-hopeless cases may skip this defense."""
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'GameContinuationEntries/should_defend_general_during_ffa_all_in___HSio7TqPf---3--344.txtmap'
        trueMapFile = 'GameContinuationEntries/should_defend_general_during_ffa_all_in___HSio7TqPf---3--344.truemap.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, 344, fill_out_tiles=True)

        rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=344)

        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # replay moves for the 25 turns after turn 344
        # simHost.queue_player_moves_str(general.player, '0,11->0,10  6,3->6,4->6,5')  # replay line for Human.exe
        simHost.queue_player_moves_str(5, '6,4->5,4->5,3->4,3->5,3->6,3  none  5,1->6,1->6,2->6,3  none  none  none  none  5,23->4,23->3,23->2,23->2,22->2,21->1,21  1,16->1,17->1,18->1,19->1,20->1,21')  # replay moves: sjpsjpsjp
        simHost.queue_player_moves_str(6, '20,2->20,3->19,3->19,2->18,2->18,3->17,3->16,3->15,3->14,3->14,4->13,4->12,4->11,4->11,5->11,6->12,6->13,6->14,6->15,6->15,7->15,8->14,8->13,8->13,9->13,10')  # replay moves: Squid
        bot = self.get_debug_render_bot(simHost, general.player)
        playerMap = simHost.get_player_map(general.player)

        placedMoves: list[FfaEndgameDetailedMove] = []
        botHost = simHost.bot_hosts[general.player]
        originalPlaceMoveFunc = botHost.place_move_func

        def recordPlacedMove(source: Tile, dest: Tile, move_half: bool = False) -> None:
            """Snapshots the final dispatched move, including whether defense was preempted."""
            placedMoves.append(FfaEndgameDetailedMove(
                fromGeneral=source.isGeneral,
                sourceX=source.x, sourceY=source.y, sourceArmy=source.army,
                destX=dest.x, destY=dest.y,
                destPreOwner=dest.player, destIsCity=dest.isCity, moveHalf=move_half))
            originalPlaceMoveFunc(source, dest, move_half)

        botHost.place_move_func = recordPlacedMove
        observations: dict[int, FfaEndgameDetailedObservation] = {}

        def watchEndgameDecisions() -> None:
            """Records policy state plus the final move chosen after defense/FFA ordering."""
            turn = simHost.sim.turn
            if turn in observations:
                return
            placed = placedMoves.pop(0) if placedMoves else None
            state = BotFfaEndgame.get_state(bot)
            decision = state.decision
            reserve = BotFfaEndgame.get_general_reserve(bot)
            predicted = bot.targetPlayerExpectedGeneralLocation
            routeDest = bot.curPath.tail.tile if bot.curPath is not None and bot.curPath.tail is not None else None
            observations[turn] = FfaEndgameDetailedObservation(
                turn=turn,
                mode=decision.mode.name,
                targetPlayer=decision.target_player,
                reason=decision.reason,
                isAllInLosing=bot.is_all_in_losing,
                defenseOverride=bot.defense_override_move,
                reserveRequired=reserve.required_army,
                reserveSatisfied=reserve.satisfied,
                predictedGeneral=(predicted.x, predicted.y) if predicted is not None else None,
                routeDest=(routeDest.x, routeDest.y) if routeDest is not None else None,
                moveFromGeneral=placed.fromGeneral if placed is not None else False,
                moveSource=(placed.sourceX, placed.sourceY) if placed is not None else None,
                moveSourceArmy=placed.sourceArmy if placed is not None else 0,
                moveDest=(placed.destX, placed.destY) if placed is not None else None,
                moveDestPreOwner=placed.destPreOwner if placed is not None else None,
                moveDestIsCity=placed.destIsCity if placed is not None else False,
                moveHalf=placed.moveHalf if placed is not None else False)

        simHost.run_between_turns(watchEndgameDecisions)

        # proof: blocking the known kill corridor from the 14-army (6,3) city into (5,3)
        # survives the scripted p5 sequence; the general is never exposed as the blocker.
        # simHost.queue_player_moves_str(general.player, '6,3->5,3')

        self.begin_capturing_logging()
        winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=5)

        ordered = [observations[t] for t in sorted(observations)]
        self.assertGreater(len(ordered), 0, 'bot never produced an endgame decision')
        first = ordered[0]
        self.assertEqual('ALL_IN', first.mode, 'must remain in the p5 all-in policy while defending')
        self.assertEqual('all_in_weaker', first.reason)
        self.assertEqual(5, first.targetPlayer, 'must stay locked on pink p5 while defending our own general')
        # is_all_in_losing is reused by FfaEndgame as the forced-all-in marker; it is not,
        # by itself, authorization to ignore a defendable lethal threat.
        self.assertTrue(
            first.defenseOverride,
            'the first move must come from the defense pipeline, not FFA_ENDGAME_ADVANCE')
        self.assertNotEqual(
            (0, 10), first.moveDest,
            'must not send the unrelated live-game 0,11->0,10 forward move while the kill path exists')
        self.assertFalse(first.moveFromGeneral, 'must not spend the general itself as the blocker')
        self.assertTrue(
            any(obs.moveSource == (6, 3) and obs.moveDest == (5, 3) and obs.defenseOverride
                for obs in ordered[:2]),
            'the nearby city stack must block the 6,4->5,4->5,3->4,3 kill path at 5,3')
        self.assertIsNone(winner)
        self.assertNoFriendliesKilled(map, general)
