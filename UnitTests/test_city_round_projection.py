import typing

from unittest.mock import patch

from bot_ek0x45 import EklipZBot

from BotModules.BotExpansionOps import BotExpansionOps
from Interfaces.TilePlanInterface import TilePlanInterface, PathMove
from Strategy.RoundProjection import project_round_outcome
from StrategyModels.ExpansionPotential import ExpansionPotential
from TestBase import TestBase
from base.client.map import MapBase, TeamStats
from BotModules.BotKillTiming import BotKillTiming
from BotModules.BotStateQueries import BotStateQueries
from Models import Move
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Strategy.OpponentTracker import OpponentTracker
from Strategy.WinConditionAnalyzer import WinCondition
from base.client.tile import Tile, TILE_EMPTY


class _StubPlanOption(TilePlanInterface):
    """Minimal concrete TilePlanInterface for RoundProjection unit tests."""
    __slots__ = ('_length', '_econValue', '_tileSet', '_delay', '_tail', '_start')

    def __init__(
            self,
            length: int,
            tileSet: typing.Set[Tile],
            requiredDelay: int = 0,
            econValue: float = 0.0,
            tail: PathMove | None = None) -> None:
        self._length = length
        self._econValue = econValue
        self._tileSet = tileSet
        self._delay = requiredDelay
        self._tail = tail
        self._start = None

    @property
    def length(self) -> int:
        return self._length

    @property
    def econValue(self) -> float:
        return self._econValue

    @property
    def tileSet(self) -> typing.Set[Tile]:
        return self._tileSet

    def __iter__(self) -> typing.Iterable[PathMove]:
        return iter(())

    @property
    def tiles(self) -> typing.Iterable[Tile]:
        return iter(self._tileSet)

    @property
    def tileList(self) -> typing.List[Tile]:
        return list(self._tileSet)

    @property
    def requiredDelay(self) -> int:
        return self._delay

    def get_first_move(self) -> Move | None:
        """No executable move is needed for material projection."""
        return None

    def pop_first_move(self) -> Move | None:
        """The projection-only option has no moves to consume."""
        return None

    def clone(self) -> '_StubPlanOption':
        return _StubPlanOption(self._length, self._tileSet, self._delay, self._econValue, self._tail)

    @property
    def tail(self) -> PathMove | None:
        return self._tail

    @property
    def start(self) -> PathMove | None:
        return self._start

    def get_move_list(self) -> typing.List[Move | None]:
        """Expose the empty executable move list."""
        return []


class NeutralDamageAccountingTests(TestBase):
    """
    Unit coverage for MapBase._get_known_neutral_damage_from_last_move
    (Tests/test_CityRoundDecisions.py game replay; the TtVz86M3i t132 city-count
    invention). Drives the helper directly with delta-populated tiles.
    """
    __slots__ = ()

    def _build_1v1_map(self) -> typing.Tuple[MapBase, typing.List[typing.List[Tile]]]:
        """Build a small real map for raw movement-delta accounting."""
        width = 3
        board = [
            [Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * width + x) for x in range(width)]
            for y in range(2)
        ]
        map = self.get_test_map(board, turn=32, num_players=2)
        map.is_army_bonus_turn = False
        map.is_city_bonus_turn = False
        return map, board

    def _prepare_neutral_chip(self, map: MapBase, board: typing.List[typing.List[Tile]]) -> typing.Tuple[Tile, Tile]:
        """src 2,6-equivalent: our tile with 5 army; dst neutral city with 36 -> sent 4."""
        src, dst = board[0][0], board[0][1]
        src.player = map.player_index
        src.army = 1  # 5 - 4 sent
        src.delta.oldOwner = map.player_index
        src.delta.oldArmy = 5
        src.delta.expectedDelta = 0
        dst.player = -1
        dst.army = 32
        dst.isCity = True
        dst.delta.oldOwner = -1
        dst.delta.oldArmy = 36
        src.visible = True
        dst.visible = True
        src.movable = [dst]
        map.last_player_index_submitted_move = (src, dst, False)
        return src, dst

    def test_partial_neutral_city_chip_credits_sent_damage(self) -> None:
        """T132 fixture shape: 5-army source sends 4 into a 36-army neutral city."""
        map, board = self._build_1v1_map()
        self._prepare_neutral_chip(map, board)
        self.assertEqual(4, map._get_known_neutral_damage_from_last_move())

    def test_full_neutral_capture_credits_city_old_army(self) -> None:
        """Capturing a 4-army neutral tile with 5 sent credits the 4 paid."""
        map, board = self._build_1v1_map()
        src, dst = self._prepare_neutral_chip(map, board)
        src.delta.oldArmy = 6
        src.army = 1  # 6 - 5 sent
        dst.player = map.player_index
        dst.isCity = False
        dst.delta.oldArmy = 4
        dst.army = 1  # 5 - 4 remainder
        self.assertEqual(4, map._get_known_neutral_damage_from_last_move())

    def test_full_neutral_city_capture_adds_city_bonus_tick(self) -> None:
        """On a city bonus turn the newly-owned city produces +1 in the same update."""
        map, board = self._build_1v1_map()
        map.is_city_bonus_turn = True
        src, dst = self._prepare_neutral_chip(map, board)
        src.delta.oldArmy = 6
        src.army = 1
        dst.player = map.player_index
        dst.delta.oldArmy = 4
        dst.army = 2  # 5 - 4 remainder + 1 city tick
        self.assertEqual(4, map._get_known_neutral_damage_from_last_move())

    def test_stale_source_delta_is_ignored(self) -> None:
        """Source army inconsistent with the send -> stale reference, attribute nothing."""
        map, board = self._build_1v1_map()
        src, dst = self._prepare_neutral_chip(map, board)
        src.army = 3  # expected 1
        self.assertEqual(0, map._get_known_neutral_damage_from_last_move())

    def test_stale_destination_damage_is_ignored(self) -> None:
        """Dest still neutral but damage != sent -> not our move's doing, attribute nothing."""
        map, board = self._build_1v1_map()
        src, dst = self._prepare_neutral_chip(map, board)
        dst.army = 30  # damage 6 != sent 4
        self.assertEqual(0, map._get_known_neutral_damage_from_last_move())

    def test_non_adjacent_destination_is_ignored(self) -> None:
        map, board = self._build_1v1_map()
        src, dst = self._prepare_neutral_chip(map, board)
        src.movable = []
        self.assertEqual(0, map._get_known_neutral_damage_from_last_move())

    def test_enemy_tile_destination_is_not_neutral_damage(self) -> None:
        """A submitted attack on an enemy tile stays in friendlyFightDelta as combat."""
        map, board = self._build_1v1_map()
        src, dst = self._prepare_neutral_chip(map, board)
        dst.player = 0
        dst.delta.oldOwner = 0
        self.assertEqual(0, map._get_known_neutral_damage_from_last_move())


class RoundProjectionTests(TestBase):
    """
    Physics checks for Strategy.RoundProjection.project_round_outcome
    (Tests/test_CityRoundDecisions.py; WCA projected-loss and
    CITY_ROUND_OPPORTUNITY_COST consumers).
    """
    __slots__ = ()

    def _build_map(self, turn: int = 40) -> typing.Tuple[MapBase, typing.List[typing.List[Tile]]]:
        width = 5
        board = [
            [Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * width + x) for x in range(width)]
            for y in range(4)
        ]
        map = self.get_test_map(board, turn=turn, num_players=2)
        return map, board

    def _team_stats(self, tiles: int, cities: int, score: int, teamPlayers: typing.List[int], army: int = 0) -> TeamStats:
        """Direct TeamStats construction; bare test maps don't populate team lookups."""
        return TeamStats(
            tileCount=tiles, score=score, standingArmy=army, cityCount=cities,
            fightingDiff=0, unexplainedTileDelta=0, teamId=teamPlayers[0],
            teamPlayers=teamPlayers, livingPlayers=teamPlayers, turn=40, deserts=0)

    def _pot(
            self,
            options: typing.List[_StubPlanOption],
            selected: _StubPlanOption | None = None,
            turn: int = 40) -> ExpansionPotential:
        """Package the supplied options without inventing expansion income."""
        return ExpansionPotential(
            0, 0, 0,
            selected if selected is not None else (options[0] if options else None),
            options, 0.0, turn)

    def test_econ_value_does_not_mint_physical_tiles_or_army(self) -> None:
        """An option's econValue=1000 contributes nothing physical; only real tiles count."""
        map, board = self._build_map()
        neutTile = board[0][1]
        option = _StubPlanOption(2, {neutTile}, econValue=1000.0)
        friendly = self._team_stats(tiles=60, cities=2, score=100, teamPlayers=[1])
        enemy = self._team_stats(tiles=83, cities=1, score=130, teamPlayers=[0])
        outcome = project_round_outcome(
            map, friendly, enemy, self._pot([option]), ExpansionPotential(0, 0, 0, None, [], 0.0, 40), 50)
        # tile_count = 60 + 1 neutral capture; income = 61 + 2*25; no econValue minted
        self.assertEqual(61, outcome.friendly.tile_count)
        self.assertEqual(111, outcome.friendly.next_cycle_income)
        self.assertEqual(108, outcome.enemy.next_cycle_income)

    def test_options_and_tiles_are_not_double_counted(self) -> None:
        """selected_option deduped vs all_paths; shared tiles counted once."""
        map, board = self._build_map()
        t1, t2 = board[0][1], board[0][2]
        shared = board[0][3]
        optSel = _StubPlanOption(2, {t1})
        optA = _StubPlanOption(2, {t2, shared})
        optB = _StubPlanOption(2, {shared})  # duplicate-object dedup + tile dedup
        friendly = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[1])
        enemy = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[0])
        outcome = project_round_outcome(
            map, friendly, enemy, self._pot([optA, optB, optA], selected=optSel), ExpansionPotential(0, 0, 0, None, [], 0.0, 40), 50)
        # completions: sel 0+2=2, A 2+2=4, B 4+2=6 all within 10; tiles {t1,t2,shared} once
        self.assertEqual(13, outcome.friendly.tile_count)

    def test_neutral_city_costs_old_army_and_grows_only_after_completion(self) -> None:
        """A captured neutral city costs its old army and grows from the capture update."""
        map, board = self._build_map(turn=40)
        cityTile = board[1][0]
        cityTile.isCity = True
        cityTile.army = 40
        option = _StubPlanOption(6, {cityTile})  # completes at 46; growth ticks 46,48,50 = 3
        friendly = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[1])
        enemy = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[0])
        outcome = project_round_outcome(
            map, friendly, enemy, self._pot([option]), ExpansionPotential(0, 0, 0, None, [], 0.0, 40), 50)
        self.assertEqual(2, outcome.friendly.city_count)
        # army = 50 + 1*baseTicks(5) + 3 - 40 neutral cost - 0 deserts
        self.assertEqual(18, outcome.friendly.army)
        # income counts the city: (10+1) + 2*25
        self.assertEqual(61, outcome.friendly.next_cycle_income)

    def test_odd_completion_also_ticks_on_capture_turn(self) -> None:
        """Completion at odd turn 45: the first growth tick is 46, then 48 and 50."""
        map, board = self._build_map(turn=40)
        cityTile = board[1][0]
        cityTile.isCity = True
        cityTile.army = 10
        option = _StubPlanOption(5, {cityTile})  # completes at 45; growth 46,48,50 = 3
        friendly = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[1])
        enemy = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[0])
        outcome = project_round_outcome(
            map, friendly, enemy, self._pot([option]), ExpansionPotential(0, 0, 0, None, [], 0.0, 40), 50)
        # army = 50 + 5 base + 3 captured - 10 neutral cost
        self.assertEqual(48, outcome.friendly.army)

    def test_option_completing_after_round_boundary_is_not_credited(self) -> None:
        """An option whose delay+length exceeds remainingCycleTurns contributes nothing."""
        map, board = self._build_map(turn=40)
        farTile = board[1][1]
        option = _StubPlanOption(20, {farTile}, requiredDelay=0)  # 20 > 10 remaining
        friendly = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[1])
        enemy = self._team_stats(tiles=10, cities=1, score=50, teamPlayers=[0])
        outcome = project_round_outcome(
            map, friendly, enemy, self._pot([option]), ExpansionPotential(0, 0, 0, None, [], 0.0, 40), 50)
        self.assertEqual(10, outcome.friendly.tile_count)
        self.assertEqual(35, outcome.friendly.next_cycle_income)

    def test_moderate_army_deficit_with_income_advantage_is_not_a_round_loss(self) -> None:
        """60t/2c vs 83t/1c -> next cycle 110 vs 108: no economy loss despite army deficit."""
        map, board = self._build_map()
        friendly = self._team_stats(tiles=60, cities=2, score=60, teamPlayers=[1])
        enemy = self._team_stats(tiles=83, cities=1, score=140, teamPlayers=[0])
        outcome = project_round_outcome(
            map, friendly, enemy,
            ExpansionPotential(0, 0, 0, None, [], 0.0, 40),
            ExpansionPotential(0, 0, 0, None, [], 0.0, 40), 50)
        self.assertEqual(110, outcome.friendly.next_cycle_income)
        self.assertEqual(108, outcome.enemy.next_cycle_income)
        economyLost = (outcome.friendly.next_cycle_income < outcome.enemy.next_cycle_income * 0.90
                       and outcome.enemy.next_cycle_income - outcome.friendly.next_cycle_income >= 10)
        self.assertFalse(economyLost)
        # army deficit still real: buying nothing leaves us behind on material
        self.assertLess(outcome.friendly.army, outcome.enemy.army)

    def test_genuine_round_loss_still_detected(self) -> None:
        """60t/1c vs 100t/3c with army deficit -> both economy and army lost."""
        map, board = self._build_map()
        friendly = self._team_stats(tiles=60, cities=1, score=80, teamPlayers=[1], army=20)
        enemy = self._team_stats(tiles=100, cities=3, score=200, teamPlayers=[0])
        outcome = project_round_outcome(
            map, friendly, enemy,
            ExpansionPotential(0, 0, 0, None, [], 0.0, 40),
            ExpansionPotential(0, 0, 0, None, [], 0.0, 40), 50)
        self.assertEqual(85, outcome.friendly.next_cycle_income)
        self.assertEqual(175, outcome.enemy.next_cycle_income)
        economyLost = (outcome.friendly.next_cycle_income < outcome.enemy.next_cycle_income * 0.90
                       and outcome.enemy.next_cycle_income - outcome.friendly.next_cycle_income >= 10)
        armyLost = outcome.friendly.army < outcome.enemy.army * 0.90
        self.assertTrue(economyLost)
        self.assertTrue(armyLost)

class _BudgetTimings:
    """Slotted timings stub exposing only cycleTurns for the affordability helper."""
    __slots__ = ('cycleTurns',)

    def __init__(self, cycleTurns: int) -> None:
        self.cycleTurns: int = cycleTurns


class _BudgetMap:
    """
    Slotted map stub for _reject_unaffordable_neutral_city_capture_plan; the shared
    projection only reads map.turn, and the helper reads the four fields below
    plus get_team_stats which returns the authored TeamStats per player.
    """
    __slots__ = ('turn', 'player_index', 'remainingPlayers', 'is_2v2', '_statsByPlayer')

    def __init__(
            self,
            turn: int,
            playerIndex: int,
            friendlyStats: TeamStats,
            enemyStats: TeamStats) -> None:
        self.turn: int = turn
        self.player_index: int = playerIndex
        self.remainingPlayers: int = 2
        self.is_2v2: bool = False
        self._statsByPlayer: typing.Dict[int, TeamStats] = {
            playerIndex: friendlyStats,
            friendlyStats.teamPlayers[0]: friendlyStats,
            enemyStats.teamPlayers[0]: enemyStats}

    def get_team_stats(self, player: int) -> TeamStats:
        """Returns the authored TeamStats for the queried player index."""
        return self._statsByPlayer[player]


class _CityBudgetBot:
    """
    Slotted bot stub carrying only the fields
    BotExpansionOps._reject_unaffordable_neutral_city_capture_plan touches.
    """
    __slots__ = (
        '_map', 'enemy_expansion_plan', 'targetPlayer', 'timings',
        'city_capture_plan_option', 'city_capture_plan_tiles',
        'curPath', 'curPathPrio', 'flow_expander', 'last_flow_expander',
        'last_flow_opt_collection', 'city_expand_plan')

    def __init__(self, map: _BudgetMap, enemyPlan: ExpansionPotential, targetPlayer: int) -> None:
        self._map: _BudgetMap = map
        self.enemy_expansion_plan: ExpansionPotential | None = enemyPlan
        self.targetPlayer: int = targetPlayer
        self.timings: _BudgetTimings = _BudgetTimings(50)
        self.city_capture_plan_option = None
        self.city_capture_plan_tiles: typing.Set[Tile] = set()
        self.curPath = None
        self.curPathPrio: int = -1
        self.flow_expander = None
        self.last_flow_expander = None
        self.last_flow_opt_collection = None
        self.city_expand_plan = None


class CityAffordabilityHelperTests(TestBase):
    """
    Direct coverage for
    BotExpansionOps._reject_unaffordable_neutral_city_capture_plan with the real
    shared projection: healthy-army candidates keep the city without a rebuild,
    and a vulnerable candidate is kept (with state restored) when the alternative
    does not strictly dominate. No blanket ban.
    """
    __slots__ = ()

    def _stats(
            self,
            tiles: int,
            cities: int,
            score: int,
            teamPlayers: typing.List[int],
            army: int = 0) -> TeamStats:
        """Direct TeamStats construction for the authored scenarios."""
        return TeamStats(
            tileCount=tiles, score=score, standingArmy=army, cityCount=cities,
            fightingDiff=0, unexplainedTileDelta=0, teamId=teamPlayers[0],
            teamPlayers=teamPlayers, livingPlayers=teamPlayers, turn=40, deserts=0)

    def _neutral_city_option(self) -> typing.Tuple[_StubPlanOption, Tile]:
        """A 6-turn option whose tail/tileSet targets a 40-army neutral city."""
        cityTile = Tile(0, 0, tile=-1, army=40, player=-1, tileIndex=0)
        cityTile.isCity = True
        option = _StubPlanOption(6, {cityTile}, tail=PathMove(cityTile))
        return option, cityTile

    def test_affordable_neutral_city_keeps_plan_without_rebuild(self) -> None:
        """Strong friendly army -> affordability gate returns candidate; no rebuild."""
        friendly = self._stats(60, 1, 300, [1], army=240)
        enemy = self._stats(83, 1, 100, [0], army=17)
        map = _BudgetMap(40, 1, friendly, enemy)
        enemyPlan = ExpansionPotential(0, 0, 0, None, [], 0.0, map.turn)
        bot = _CityBudgetBot(map, enemyPlan, 0)
        option, cityTile = self._neutral_city_option()
        candidate = ExpansionPotential(6, 0, 1, option, [option], 27.0, map.turn)
        bot.city_capture_plan_option = option
        bot.city_capture_plan_tiles = {cityTile}
        negatives: typing.Set[Tile] = set()

        with patch.object(BotExpansionOps, 'build_expansion_plan') as rebuild:
            result = BotExpansionOps._reject_unaffordable_neutral_city_capture_plan(
                bot, candidate, negatives, (0, 0, 0), -1, False, False)

        rebuild.assert_not_called()
        self.assertIs(candidate, result)
        self.assertIs(option, bot.city_capture_plan_option)
        self.assertEqual({cityTile}, bot.city_capture_plan_tiles)

    def test_vulnerable_candidate_kept_when_alternative_not_dominating(self) -> None:
        """Vulnerable army + non-dominating alternative -> candidate kept, all state restored."""
        friendly = self._stats(10, 1, 90, [1])
        enemy = self._stats(10, 1, 200, [0])
        map = _BudgetMap(40, 1, friendly, enemy)
        enemyPlan = ExpansionPotential(0, 0, 0, None, [], 0.0, map.turn)
        bot = _CityBudgetBot(map, enemyPlan, 0)
        option, cityTile = self._neutral_city_option()
        candidate = ExpansionPotential(6, 0, 1, option, [option], 27.0, map.turn)
        bot.city_capture_plan_option = option
        bot.city_capture_plan_tiles = {cityTile}
        savedFlow = object()
        savedLastFlow = object()
        savedOptCollection = object()
        savedCityExpand = object()
        bot.flow_expander = savedFlow
        bot.last_flow_expander = savedLastFlow
        bot.last_flow_opt_collection = savedOptCollection
        bot.city_expand_plan = savedCityExpand
        negatives: typing.Set[Tile] = set()
        savedNegatives = set(negatives)

        # alternative with zero captures projects fewer tiles than the candidate
        # -> strict dominance (tiles AND army) fails -> candidate kept.
        alternative = ExpansionPotential(0, 0, 0, None, [], 0.0, map.turn)
        mutationMarker = Tile(1, 1, tile=-1, army=0, player=-1, tileIndex=1)

        def _mutating_build(
                buildBot: _CityBudgetBot,
                timeLimit: float,
                expansionNegatives: typing.Set[Tile],
                pathColor: typing.Tuple[int, int, int],
                overrideTurns: int = -1,
                includeExtraGenAndCityArmy: bool = False,
                skip_remaining_time_check: bool = False,
                includeNeutralCityCapture: bool = True) -> ExpansionPotential:
            """Mimic the exploratory builder's published-state mutations."""
            bot.flow_expander = object()
            bot.last_flow_expander = object()
            bot.last_flow_opt_collection = object()
            bot.city_expand_plan = object()
            negatives.add(mutationMarker)
            return alternative

        with patch.object(BotExpansionOps, 'build_expansion_plan', side_effect=_mutating_build):
            result = BotExpansionOps._reject_unaffordable_neutral_city_capture_plan(
                bot, candidate, negatives, (0, 0, 0), -1, False, False)

        self.assertIs(candidate, result)
        self.assertIs(savedFlow, bot.flow_expander)
        self.assertIs(savedLastFlow, bot.last_flow_expander)
        self.assertIs(savedOptCollection, bot.last_flow_opt_collection)
        self.assertIs(savedCityExpand, bot.city_expand_plan)
        self.assertEqual(savedNegatives, negatives)
        self.assertIs(option, bot.city_capture_plan_option)

class NeutralDamageBonusCasesTests(TestBase):
    """
    Additional exact-consistency cases for
    MapBase._get_known_neutral_damage_from_last_move:
    army-bonus capture, city+army double-bonus capture, and half-send chip.
    """
    __slots__ = ()

    def _build_map(self, turn: int) -> typing.Tuple[MapBase, typing.List[typing.List[Tile]]]:
        """Build a real map with bonus flags controlled by each test."""
        width = 3
        board = [
            [Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * width + x) for x in range(width)]
            for y in range(2)
        ]
        map = self.get_test_map(board, turn=turn, num_players=2)
        map.is_army_bonus_turn = False
        map.is_city_bonus_turn = False
        return map, board

    def _neutral_chip(
            self,
            map: MapBase,
            board: typing.List[typing.List[Tile]],
            srcOld: int,
            srcNow: int,
            srcExp: int,
            dstOld: int,
            dstNow: int,
            half: bool) -> typing.Tuple[Tile, Tile]:
        """Populate the submitted move and exact source/destination deltas."""
        src, dst = board[0][0], board[0][1]
        src.player = map.player_index
        src.army = srcNow
        src.delta.oldOwner = map.player_index
        src.delta.oldArmy = srcOld
        src.delta.expectedDelta = srcExp
        dst.army = dstNow
        dst.delta.oldOwner = -1
        dst.delta.oldArmy = dstOld
        src.visible = True
        dst.visible = True
        src.movable = [dst]
        map.last_player_index_submitted_move = (src, dst, half)
        return src, dst

    def test_regular_neutral_capture_on_army_bonus_turn(self) -> None:
        """turn50: source old6 -> sends5, neutral 4 taken, +1 tile bonus -> credited 4."""
        map, board = self._build_map(turn=50)
        map.is_army_bonus_turn = True
        src, dst = self._neutral_chip(map, board, 6, 2, 1, 4, 0, False)
        dst.player = map.player_index
        dst.army = 2  # 5 - 4 remainder + 1 army-bonus on the new tile
        self.assertEqual(4, map._get_known_neutral_damage_from_last_move())

    def test_neutral_city_capture_on_army_and_city_bonus_turn(self) -> None:
        """turn50 city: sends5 -> 4, remainder1 +1 tile +1 city tick -> credited 4."""
        map, board = self._build_map(turn=50)
        map.is_army_bonus_turn = True
        map.is_city_bonus_turn = True
        src, dst = self._neutral_chip(map, board, 6, 2, 1, 4, 0, False)
        dst.player = map.player_index
        dst.isCity = True
        dst.army = 3  # 5 - 4 + 1 army-bonus + 1 city tick
        self.assertEqual(4, map._get_known_neutral_damage_from_last_move())

    def test_half_send_neutral_chip(self) -> None:
        """move_half: source old9 sends 4 -> dest 36->32, damage == sent -> credited 4."""
        map, board = self._build_map(turn=32)
        self._neutral_chip(map, board, 9, 5, 0, 36, 32, True)
        self.assertEqual(4, map._get_known_neutral_damage_from_last_move())

class WCAProjectedLossBehaviorTests(TestBase):
    """
    Drives the REAL WinConditionAnalyzer.force_kill_all_in_if_projected_round_loss
    on a real bot/analyzer/opponent-tracker built from the t115 TtVz86M3i
    snapshot (allAfkExceptMapPlayer sim host, no sim turns run). Only
    OpponentTracker.get_current_team_scores_by_player (authored TeamStats) and
    BotKillTiming.find_all_in_option (viable path; viability itself is covered
    elsewhere) are stubbed. Proves the production recovery/loss decisions, not
    a copy of the threshold math.
    """
    __slots__ = ()

    MAP_FILE_115 = 'GameContinuationEntries/should_expand_instead_of_committing_to_slow_neutral_city___TtVz86M3i---1--115.txtmap'

    def _load_wca_bot(self) -> typing.Tuple[GameSimulatorHost, EklipZBot, Tile, Tile]:
        """
        Loads the t115 fixture with the real debug bot and points the analyzer at
        the enemy general.

        @return: (simHost, bot, general, enemyGeneral) tuple.
        """
        map, general, enemyGeneral = self.load_map_and_generals(self.MAP_FILE_115, 115, fill_out_tiles=True)
        rawMap, _ = self.load_map_and_general(self.MAP_FILE_115, respect_undiscovered=True, turn=115)
        self.enable_search_time_limits_and_disable_debug_asserts()
        simHost = GameSimulatorHost(
            map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        bot = self.get_debug_render_bot(simHost, general.player)
        bot.win_condition_analyzer.target_player = enemyGeneral.player
        return simHost, bot, general, enemyGeneral

    @staticmethod
    def _stats(
            tiles: int,
            score: int,
            standingArmy: int,
            cities: int,
            teamPlayer: int,
            turn: int) -> TeamStats:
        """Authored TeamStats for the projected-loss scenarios."""
        return TeamStats(
            tileCount=tiles, score=score, standingArmy=standingArmy, cityCount=cities,
            fightingDiff=0, unexplainedTileDelta=0, teamId=teamPlayer,
            teamPlayers=[teamPlayer], livingPlayers=[teamPlayer], turn=turn, deserts=0)

    def _viable_path(self, general: Tile, enemyGeneral: Tile) -> Path:
        """A minimal real viable all-in Path from our general to the enemy general."""
        viablePath = Path()
        viablePath.add_start(general)
        viablePath.add_next(enemyGeneral)
        return viablePath

    def test_moderate_army_deficit_with_income_advantage_returns_false(self) -> None:
        """60t/2c vs 83t/1c -> next cycle 110 vs 108: recovery, no all-in, no finder call."""
        simHost, bot, general, enemyGeneral = self._load_wca_bot()
        analyzer = bot.win_condition_analyzer
        bot.is_all_in_losing = False
        bot.all_in_losing_counter = 0
        analyzer.projected_loss_all_in_active = False
        ourIndex = general.player
        friendly = self._stats(60, 60, 0, 2, ourIndex, bot._map.turn)
        enemy = self._stats(83, 140, 57, 1, enemyGeneral.player, bot._map.turn)

        def _get_stats(player: int) -> TeamStats:
            return friendly if player == ourIndex else enemy

        empty = ExpansionPotential(0, 0, 0, None, [], 0.0, bot._map.turn)
        with patch.object(OpponentTracker, 'get_current_team_scores_by_player', side_effect=_get_stats), \
                patch.object(BotKillTiming, 'find_all_in_option', return_value=self._viable_path(general, enemyGeneral)) as finder:
            result = analyzer.force_kill_all_in_if_projected_round_loss(bot, empty, empty)

        self.assertFalse(result)
        finder.assert_not_called()
        self.assertFalse(analyzer.projected_loss_all_in_active)
        self.assertFalse(BotStateQueries.is_all_in(bot))

    def test_genuine_round_loss_forces_all_in_via_real_method(self) -> None:
        """60t/1c vs 100t/3c + army deficit -> 85 vs 175: all-in forced, flag latched."""
        simHost, bot, general, enemyGeneral = self._load_wca_bot()
        analyzer = bot.win_condition_analyzer
        bot.is_all_in_losing = False
        bot.all_in_losing_counter = 0
        analyzer.projected_loss_all_in_active = False
        ourIndex = general.player
        friendly = self._stats(60, 80, 20, 1, ourIndex, bot._map.turn)
        enemy = self._stats(100, 200, 100, 3, enemyGeneral.player, bot._map.turn)

        def _get_stats(player: int) -> TeamStats:
            return friendly if player == ourIndex else enemy

        empty = ExpansionPotential(0, 0, 0, None, [], 0.0, bot._map.turn)
        with patch.object(OpponentTracker, 'get_current_team_scores_by_player', side_effect=_get_stats), \
                patch.object(BotKillTiming, 'find_all_in_option', return_value=self._viable_path(general, enemyGeneral)) as finder:
            result = analyzer.force_kill_all_in_if_projected_round_loss(bot, empty, empty)

        self.assertTrue(result)
        finder.assert_called_once_with(bot)
        self.assertTrue(analyzer.projected_loss_all_in_active)
        self.assertTrue(bot.is_all_in_losing)
        self.assertIn(WinCondition.KillAllIn, analyzer.viable_win_conditions)
