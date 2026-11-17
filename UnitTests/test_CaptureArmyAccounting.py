import dataclasses

from Strategy.OpponentTracker import OpponentTracker
from StrategyModels.CaptureArmyAccounting import (
    CaptureFogSnapshot,
    CapturePlayerScoreSnapshot,
    estimate_capture_army_loss,
    get_capture_fog_pool_transfer,
    get_capture_score_uncertainty)
from TestBase import TestBase
from base.client.map import MapBase


@dataclasses.dataclass(slots=True)
class MissedBonusWindowResult(object):
    """Killer fog-city pool delta and gather-queue delta for one missed-bonus window scenario."""

    cityArmyDelta: int
    queueDelta: dict[int, int]


class CaptureArmyAccountingTests(TestBase):
    """
    Pure-math coverage for the conservative capture-combat loss interval and the
    fog-pool transfer derived from it. Expected values are the lead-authored
    frozen cases verified against the two live FFA capture replays
    (Tests/test_FFA.py::test_should_preserve_captured_fog_army_after_late_capture_message
    and ::test_should_account_for_annihilated_army_before_ffa_capture_transfer).
    """

    __slots__ = ()

    def test_should_bound_first_ffa_capture_loss_at_25_to_41(self) -> None:
        """bVK2OP478 t136->137: victim 114 score / 52 tiles, killer 132->152, no income."""
        estimate = estimate_capture_army_loss(
            victimScore=114,
            victimTiles=52,
            killerScoreBefore=132,
            killerScoreAfter=152,
            killerIncome=0,
            visibleDefense=0)

        self.assertEqual(25, estimate.minimum)
        self.assertEqual(41, estimate.maximum)
        self.assertEqual(25, estimate.assumed)
        self.assertTrue(estimate.consistent)
        self.assertTrue(estimate.minimum <= 34 <= estimate.maximum)

    def test_should_bound_second_ffa_capture_loss_at_1_to_6(self) -> None:
        """2ou8wZEPy t130->131: victim 53 score / 18 tiles, killer 64->90, no income."""
        estimate = estimate_capture_army_loss(
            victimScore=53,
            victimTiles=18,
            killerScoreBefore=64,
            killerScoreAfter=90,
            killerIncome=0,
            visibleDefense=0)

        self.assertEqual(1, estimate.minimum)
        self.assertEqual(6, estimate.maximum)
        self.assertEqual(1, estimate.assumed)
        self.assertTrue(estimate.consistent)
        self.assertTrue(estimate.minimum <= 4 <= estimate.maximum)

    def test_should_keep_same_loss_interval_when_income_is_accounted(self) -> None:
        """A +3 killer income tick shifts the observed score by the same +3, leaving delta (and the interval) unchanged."""
        estimate = estimate_capture_army_loss(
            victimScore=114,
            victimTiles=52,
            killerScoreBefore=132,
            killerScoreAfter=155,
            killerIncome=3,
            visibleDefense=0)

        self.assertEqual(25, estimate.minimum)
        self.assertEqual(41, estimate.maximum)
        self.assertEqual(25, estimate.assumed)
        self.assertTrue(estimate.consistent)

    def test_should_flag_inconsistent_score_evidence_without_inventing_loss(self) -> None:
        """Impossible killer gain vs victim score must return the bounded fallback with consistent=False."""
        estimate = estimate_capture_army_loss(
            victimScore=10,
            victimTiles=2,
            killerScoreBefore=0,
            killerScoreAfter=100,
            killerIncome=0,
            visibleDefense=0)

        self.assertFalse(estimate.consistent)
        self.assertEqual(0, estimate.minimum)
        self.assertEqual(10, estimate.maximum)
        self.assertEqual(0, estimate.assumed)

    def test_should_use_visible_general_defense_as_physical_lower_bound(self) -> None:
        """A previously visible captured general raises the loss floor to its defense army."""
        estimate = estimate_capture_army_loss(
            victimScore=114,
            victimTiles=52,
            killerScoreBefore=132,
            killerScoreAfter=152,
            killerIncome=0,
            visibleDefense=34)

        self.assertEqual(34, estimate.minimum)
        self.assertEqual(41, estimate.maximum)
        self.assertTrue(estimate.consistent)

    def test_should_transfer_first_ffa_fog_pools_after_conservative_and_true_loss(self) -> None:
        """Pools 29/30/22 burning assumed 25 (conservative) and true 34 must give fog 13/14 and city 0."""
        conservative = get_capture_fog_pool_transfer(
            fogArmy=29,
            fogArmyTrue=30,
            fogCityArmy=22,
            annihilatedArmy=25,
            visibleDefense=0)
        self.assertEqual(13, conservative.gatheredArmyTransferred)
        self.assertEqual(14, conservative.gatheredArmyTrueTransferred)
        self.assertEqual(0, conservative.cityArmyTransferred)

        trueLoss = get_capture_fog_pool_transfer(
            fogArmy=29,
            fogArmyTrue=30,
            fogCityArmy=22,
            annihilatedArmy=34,
            visibleDefense=0)
        self.assertEqual(9, trueLoss.gatheredArmyTransferred)
        self.assertEqual(9, trueLoss.gatheredArmyTrueTransferred)
        self.assertEqual(0, trueLoss.cityArmyTransferred)

    def test_should_transfer_second_ffa_fog_pools_after_conservative_and_true_loss(self) -> None:
        """Pools 9/16/19 burning assumed 1 (conservative) and true 4 must give 5/8/9 and the true-loss variant."""
        conservative = get_capture_fog_pool_transfer(
            fogArmy=9,
            fogArmyTrue=16,
            fogCityArmy=19,
            annihilatedArmy=1,
            visibleDefense=0)
        self.assertEqual(5, conservative.gatheredArmyTransferred)
        self.assertEqual(8, conservative.gatheredArmyTrueTransferred)
        self.assertEqual(9, conservative.cityArmyTransferred)

        trueLoss = get_capture_fog_pool_transfer(
            fogArmy=9,
            fogArmyTrue=16,
            fogCityArmy=19,
            annihilatedArmy=4,
            visibleDefense=0)
        self.assertEqual(5, trueLoss.gatheredArmyTransferred)
        self.assertEqual(8, trueLoss.gatheredArmyTrueTransferred)
        self.assertEqual(8, trueLoss.cityArmyTransferred)

    def test_should_not_reduce_fog_pools_when_annihilation_is_fully_visible_defense(self) -> None:
        """annihilatedArmy == visibleDefense leaves hiddenLoss 0, so pools 18/15/6 halve untouched to 9/8/3."""
        transfer = get_capture_fog_pool_transfer(
            fogArmy=18,
            fogArmyTrue=15,
            fogCityArmy=6,
            annihilatedArmy=12,
            visibleDefense=12)

        self.assertEqual(0, transfer.cityArmyLost)
        self.assertEqual(0, transfer.gatheredArmyLost)
        self.assertEqual(9, transfer.gatheredArmyTransferred)
        self.assertEqual(8, transfer.gatheredArmyTrueTransferred)
        self.assertEqual(3, transfer.cityArmyTransferred)

    def test_should_clamp_transfers_at_zero_when_burn_exceeds_all_pools(self) -> None:
        """A burn larger than every pool must floor all transfers at 0 with no negatives."""
        transfer = get_capture_fog_pool_transfer(
            fogArmy=5,
            fogArmyTrue=3,
            fogCityArmy=2,
            annihilatedArmy=100,
            visibleDefense=0)

        self.assertEqual(2, transfer.cityArmyLost)
        self.assertEqual(98, transfer.gatheredArmyLost)
        self.assertEqual(0, transfer.cityArmyTransferred)
        self.assertEqual(0, transfer.gatheredArmyTransferred)
        self.assertEqual(0, transfer.gatheredArmyTrueTransferred)

    def test_should_widen_interval_for_third_party_combat_budget(self) -> None:
        """Other players may have fought the same update: X=20 must widen V100/N11 K100->129 to 1..30 (closed pair alone would claim min 14)."""
        estimate = estimate_capture_army_loss(
            victimScore=100,
            victimTiles=11,
            killerScoreBefore=100,
            killerScoreAfter=129,
            killerIncome=0,
            visibleDefense=0,
            otherPlayerArmyLossBudget=20,
            killerIncomeUpper=0)

        self.assertEqual(1, estimate.minimum)
        self.assertEqual(30, estimate.maximum)
        self.assertTrue(estimate.consistent)
        self.assertTrue(estimate.minimum <= 1 <= estimate.maximum)

    def test_should_not_inflate_assumed_loss_when_only_income_upper_is_known(self) -> None:
        """First FFA scores with income bounded 0..3 and X=0 give 25..43: unknown income widens the top of the interval, never the chosen lower bound."""
        estimate = estimate_capture_army_loss(
            victimScore=114,
            victimTiles=52,
            killerScoreBefore=132,
            killerScoreAfter=152,
            killerIncome=0,
            visibleDefense=0,
            otherPlayerArmyLossBudget=0,
            killerIncomeUpper=3)

        self.assertEqual(25, estimate.minimum)
        self.assertEqual(43, estimate.maximum)
        self.assertEqual(25, estimate.assumed)
        self.assertTrue(estimate.consistent)

    def test_should_bound_score_uncertainty_from_third_party_deficits(self) -> None:
        """Odd capture turn: no income ticks; a -5 third-party score deficit becomes the whole external loss budget."""
        previous = (
            CapturePlayerScoreSnapshot(100, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0))
        final = (
            CapturePlayerScoreSnapshot(0, 0, 0, 0, 0, 0),
            CapturePlayerScoreSnapshot(80, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(45, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0))

        uncertainty = get_capture_score_uncertainty(previous, final, captureTurn=51, victim=0, killer=1)

        self.assertEqual(0, uncertainty.killerIncomeMinimum)
        self.assertEqual(0, uncertainty.killerIncomeMaximum)
        self.assertEqual(5, uncertainty.otherPlayerArmyLossBudget)

    def test_should_use_broad_budget_and_tile_income_bound_on_multiple_deaths(self) -> None:
        """Even non-bonus turn: income bounds by final tile count; two simultaneous deaths switch to the total pre-update army budget."""
        previous = (
            CapturePlayerScoreSnapshot(100, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0))
        final = (
            CapturePlayerScoreSnapshot(0, 0, 0, 0, 0, 0),
            CapturePlayerScoreSnapshot(80, 10, 1, 0, 0, 0),
            CapturePlayerScoreSnapshot(0, 0, 0, 0, 0, 0),
            CapturePlayerScoreSnapshot(45, 10, 1, 0, 0, 0))

        uncertainty = get_capture_score_uncertainty(previous, final, captureTurn=52, victim=0, killer=1)

        self.assertEqual(0, uncertainty.killerIncomeMinimum)
        self.assertEqual(10, uncertainty.killerIncomeMaximum)
        # deaths=2 -> broad budget = sum(prev.score + final.tiles * incomeTicks=1) over all players
        # = (100+0) + (50+10) + (50+0) + (50+10) = 270
        self.assertEqual(270, uncertainty.otherPlayerArmyLossBudget)


class CaptureTransferIdempotenceTests(TestBase):
    """
    Focused OpponentTracker coverage for duplicate capture notifications and
    ot_capture_state serialization round-trips while a zeroed victim still
    awaits its capture text. Uses the same p9lH7ucI t243 capture fixture as
    Tests/test_OpponentTracker.py's enemy-capture tests with the victim
    scoreboard zeroed directly (no full resim).
    """

    __slots__ = ()

    _MAP_FILE = 'GameContinuationEntries/should_transfer_gather_queue_and_fog_pools_on_enemy_capture___p9lH7ucI----1--243.txtmap'
    _VICTIM = 2
    _KILLER = 4

    def _zero_victim_team_scoreboard(self, rawMap: MapBase, tracker: OpponentTracker, playerIdx: int | None = None) -> None:
        """Zeroes score/tileCount for every player on the given (default victim's) team so the dead-team path applies."""
        # get_team_stats_by_team_id caches per turn; advancing the turn both
        # invalidates the constructor's alive-state cache and mirrors the real
        # post-capture turn the zeroed scoreboard belongs to.
        rawMap.turn += 1
        victimIdx = self._VICTIM if playerIdx is None else playerIdx
        victimTeam = tracker._team_lookup_by_player[victimIdx]
        for teamPlayerIdx in tracker.get_team_players(victimTeam):
            rawMap.players[teamPlayerIdx].score = 0
            rawMap.players[teamPlayerIdx].tileCount = 0

    @staticmethod
    def _balanced_score_pair(
            playerCount: int,
            captureTurn: int) -> tuple[list[CapturePlayerScoreSnapshot], list[CapturePlayerScoreSnapshot]]:
        """
        Builds prev/final score lists where every player earns exactly their
        turn income, so get_capture_score_uncertainty computes a zero
        third-party loss budget for the crafted capture.
        """
        incomeTicks = int(captureTurn % 2 == 0) + int(captureTurn % 50 == 0)
        previous = [CapturePlayerScoreSnapshot(50, 10, 1, 0, 0, 0) for _ in range(playerCount)]
        final = [CapturePlayerScoreSnapshot(50 + 10 * incomeTicks, 10, 1, 0, 0, 0) for _ in range(playerCount)]
        return previous, final

    @staticmethod
    def _parse_resume_data(dump: str) -> dict[str, str]:
        """Parses dump_to_string_data key=value lines into the resume-data dict shape."""
        data = {}
        for line in dump.splitlines():
            if '=' in line:
                key, _, value = line.partition('=')
                data[key] = value
        return data

    def test_should_transfer_only_once_for_duplicate_capture_notifications(self) -> None:
        """Repeated notify_player_capture calls for the same pair must queue once and transfer once."""
        rawMap, _ = self.load_map_and_general(self._MAP_FILE, respect_undiscovered=True, turn=243)
        tracker = OpponentTracker(rawMap)
        self._zero_victim_team_scoreboard(rawMap, tracker)
        tracker._snapshot_zero_score_transitions()

        tracker.notify_player_capture(self._VICTIM, self._KILLER)
        tracker.notify_player_capture(self._VICTIM, self._KILLER)
        tracker.notify_player_capture(self._VICTIM, self._KILLER)
        self.assertEqual(
            [(self._VICTIM, self._KILLER)],
            tracker._pending_player_captures,
            'duplicate notifications must not re-queue the capture pair')

        tracker._process_pending_player_captures()

        self.assertEqual(0, tracker.get_player_gather_queue(self._VICTIM).length)
        self.assertIn((self._VICTIM, self._KILLER), tracker._completed_player_captures)
        self.assertNotIn(self._VICTIM, tracker._unresolved_player_captures)
        self.assertIn(self._VICTIM, tracker.last_capture_army_losses)

        killerTeam = tracker._team_lookup_by_player[self._KILLER]
        killerStats = tracker.current_team_cycle_stats[killerTeam]
        poolsAfterTransfer = (
            killerStats.approximate_fog_army_available_total,
            killerStats.approximate_fog_army_available_total_true,
            killerStats.approximate_fog_city_army)
        killerQueueAfterTransfer = tracker.get_player_gather_queue(self._KILLER).get_amount_dict()

        # a second process pass and a post-completion re-notification are both no-ops
        tracker._process_pending_player_captures()
        tracker.notify_player_capture(self._VICTIM, self._KILLER)
        self.assertEqual(0, len(tracker._pending_player_captures))
        tracker._process_pending_player_captures()

        self.assertEqual(poolsAfterTransfer, (
            killerStats.approximate_fog_army_available_total,
            killerStats.approximate_fog_army_available_total_true,
            killerStats.approximate_fog_city_army))
        self.assertEqual(killerQueueAfterTransfer, tracker.get_player_gather_queue(self._KILLER).get_amount_dict())

    def test_should_round_trip_unresolved_capture_state_through_serialization(self) -> None:
        """ot_capture_state must preserve the frozen bank so a resumed tracker transfers identically."""
        rawMap, _ = self.load_map_and_general(self._MAP_FILE, respect_undiscovered=True, turn=243)
        tracker1 = OpponentTracker(rawMap)
        self._zero_victim_team_scoreboard(rawMap, tracker1)

        # seed a distinctive victim queue + pools so the surviving transfer is observable
        victimTeam = tracker1._team_lookup_by_player[self._VICTIM]
        victimQueue = tracker1.get_player_gather_queue(self._VICTIM)
        for tileSize in list(victimQueue.get_amount_dict()):
            victimQueue.set_amount_for_size(tileSize, 0)
        victimQueue.append(3)
        victimQueue.append(3)
        victimQueue.append(7)
        victimStats = tracker1.current_team_cycle_stats[victimTeam]
        victimStats.approximate_fog_army_available_total = 60
        victimStats.approximate_fog_army_available_total_true = 50
        victimStats.approximate_fog_city_army = 30
        victimStats.fog_city_count = 2

        tracker1._snapshot_zero_score_transitions()
        tracker1.notify_player_capture(self._VICTIM, self._KILLER)

        dump = tracker1.dump_to_string_data()
        data = self._parse_resume_data(dump)
        self.assertIn('ot_capture_state', data)

        tracker2 = OpponentTracker(rawMap)
        tracker2.load_from_map_data(data)

        self.assertEqual(tracker1._capture_previous_scores, tracker2._capture_previous_scores)
        self.assertEqual(tracker1._capture_previous_turn, tracker2._capture_previous_turn)
        self.assertEqual(tracker1._unresolved_player_captures, tracker2._unresolved_player_captures)
        self.assertEqual(tracker1._pending_player_captures, tracker2._pending_player_captures)
        self.assertEqual(tracker1._completed_player_captures, tracker2._completed_player_captures)
        self.assertEqual(tracker1._capture_placeholder_counts, tracker2._capture_placeholder_counts)

        killerTeam = tracker1._team_lookup_by_player[self._KILLER]

        def killerPools(tracker: OpponentTracker) -> tuple[int, int, int]:
            stats = tracker.current_team_cycle_stats[killerTeam]
            return (
                stats.approximate_fog_army_available_total,
                stats.approximate_fog_army_available_total_true,
                stats.approximate_fog_city_army)

        poolsBefore1 = killerPools(tracker1)
        poolsBefore2 = killerPools(tracker2)
        killerQueueBefore2 = tracker2.get_player_gather_queue(self._KILLER).get_amount_dict()
        tracker1._process_pending_player_captures()
        tracker2._process_pending_player_captures()

        # identical loss interval and identical surviving pool transfers after resume
        self.assertEqual(tracker1.last_capture_army_losses, tracker2.last_capture_army_losses)
        poolDelta1 = tuple(after - before for after, before in zip(killerPools(tracker1), poolsBefore1))
        poolDelta2 = tuple(after - before for after, before in zip(killerPools(tracker2), poolsBefore2))
        self.assertNotEqual((0, 0, 0), poolDelta1, 'seeded pools must produce a nonzero surviving transfer')
        self.assertEqual(poolDelta1, poolDelta2)

        # victim queue/pools cleared and killer queue received the halved entries on both
        self.assertEqual(0, tracker1.get_player_gather_queue(self._VICTIM).length)
        self.assertEqual(0, tracker2.get_player_gather_queue(self._VICTIM).length)
        self.assertEqual(
            tracker1.get_player_gather_queue(self._KILLER).get_amount_dict(),
            tracker2.get_player_gather_queue(self._KILLER).get_amount_dict())
        # victim queue {3:2, 7:1} transfers per-entry ceil-halved as {2:2, 4:1}
        killerQueueAfter2 = tracker2.get_player_gather_queue(self._KILLER).get_amount_dict()
        for halvedSize, expectedAdded in ((2, 2), (4, 1)):
            self.assertEqual(
                killerQueueBefore2.get(halvedSize, 0) + expectedAdded,
                killerQueueAfter2.get(halvedSize, 0))

    def test_should_not_charge_vacated_visible_general_stack_to_fog_loss(self) -> None:
        """
        Tests/test_FFA.py::FFATests capture accounting: the victim's previously
        visible 100-army general stack may have moved off the general before the
        kill, so the estimator must see visibleDefense=0 (the interval floor
        stays the proven bound, never 100) while the pool helper still credits
        the stack and burns zero fog army.
        """
        rawMap, _ = self.load_map_and_general(self._MAP_FILE, respect_undiscovered=True, turn=243)
        tracker = OpponentTracker(rawMap)
        self._zero_victim_team_scoreboard(rawMap, tracker)
        tracker._snapshot_zero_score_transitions()
        bank = tracker._unresolved_player_captures[self._VICTIM]
        self.assertIsNotNone(bank)

        # craft the frozen scoreboard: victim 150 score / 11 tiles with a vacated
        # visible 100 stack, killer 200->274, every other player exactly
        # income-balanced so the third-party budget stays 0.
        captureTurn = bank.captureTurn
        previous, final = self._balanced_score_pair(len(rawMap.players), captureTurn)
        previous[self._VICTIM] = dataclasses.replace(
            previous[self._VICTIM], score=150, tiles=11, cities=1,
            visibleGeneralArmy=100, visibleOwnedTiles=5, fogCityCount=1)
        final[self._VICTIM] = dataclasses.replace(
            final[self._VICTIM], score=0, tiles=0, cities=0,
            visibleGeneralArmy=0, visibleOwnedTiles=0, fogCityCount=0)
        previous[self._KILLER] = dataclasses.replace(previous[self._KILLER], score=200, tiles=30, cities=2)
        final[self._KILLER] = dataclasses.replace(final[self._KILLER], score=274, tiles=30, cities=2)
        craftedBank = dataclasses.replace(
            bank,
            fogArmy=60,
            fogArmyTrue=50,
            fogCityArmy=30,
            fogCityCount=2,
            previousScores=tuple(previous),
            finalScores=tuple(final))
        tracker._unresolved_player_captures[self._VICTIM] = craftedBank

        killerTeam = tracker._team_lookup_by_player[self._KILLER]
        killerStats = tracker.current_team_cycle_stats[killerTeam]
        fogBefore = killerStats.approximate_fog_army_available_total
        fogTrueBefore = killerStats.approximate_fog_army_available_total_true
        cityBefore = killerStats.approximate_fog_city_army

        tracker.notify_player_capture(self._VICTIM, self._KILLER)
        tracker._process_pending_player_captures()

        estimate = tracker.last_capture_army_losses[self._VICTIM]
        self.assertTrue(estimate.consistent)
        self.assertEqual(1, estimate.minimum,
                         'the vacated 100-army visible stack must not floor the loss estimate')
        self.assertNotEqual(100, estimate.minimum)

        # assumed=1 is fully covered by the credited visible stack, so the fog
        # pools halve untouched: 60->30, 50->25, 30->15.
        self.assertEqual(fogBefore + 30, killerStats.approximate_fog_army_available_total)
        self.assertEqual(fogTrueBefore + 25, killerStats.approximate_fog_army_available_total_true)
        self.assertEqual(cityBefore + 15, killerStats.approximate_fog_city_army)

    def _run_missed_bonus_window(self, previousTurn: int) -> MissedBonusWindowResult:
        """
        Seeds the crafted turn-50 capture bank (queue {3:2,7:1}, pools 60/50/30,
        fogCityCount 2, consistent zero-assumed loss), round-trips it through
        ot_capture_state, and returns the resumed tracker's killer fog-city
        delta and queue delta for the given _capture_previous_turn window.
        """
        rawMap, _ = self.load_map_and_general(self._MAP_FILE, respect_undiscovered=True, turn=243)
        tracker = OpponentTracker(rawMap)
        self._zero_victim_team_scoreboard(rawMap, tracker)
        # the current turn's own bonuses belong to the normal analyze loop and
        # must not be counted by the transfer; direct _process calls never run it.
        rawMap.turn = 52
        tracker._capture_previous_turn = previousTurn
        tracker._snapshot_zero_score_transitions()
        nativeBank = tracker._unresolved_player_captures[self._VICTIM]

        previous, final = self._balanced_score_pair(len(rawMap.players), 50)
        previous[self._VICTIM] = CapturePlayerScoreSnapshot(10, 5, 1, 0, 0, 0)
        final[self._VICTIM] = CapturePlayerScoreSnapshot(0, 0, 0, 0, 0, 0)
        previous[self._KILLER] = CapturePlayerScoreSnapshot(100, 20, 1, 0, 0, 0)
        final[self._KILLER] = CapturePlayerScoreSnapshot(105, 20, 1, 0, 0, 0)
        bank = dataclasses.replace(
            nativeBank,
            captureTurn=50,
            queueAmounts={3: 2, 7: 1},
            fogArmy=60,
            fogArmyTrue=50,
            fogCityArmy=30,
            fogCityCount=2,
            previousScores=tuple(previous),
            finalScores=tuple(final))
        tracker._unresolved_player_captures[self._VICTIM] = bank
        tracker.notify_player_capture(self._VICTIM, self._KILLER)

        # the resumed copy must transfer identically; run both and compare
        dump = tracker.dump_to_string_data()
        data = self._parse_resume_data(dump)
        tracker2 = OpponentTracker(rawMap)
        tracker2.load_from_map_data(data)

        cityDelta1, queueDelta1 = self._measure_killer_capture_deltas(tracker)
        cityDelta2, queueDelta2 = self._measure_killer_capture_deltas(tracker2)
        self.assertEqual(cityDelta1, cityDelta2, 'resumed tracker must transfer the same fog city delta')
        self.assertEqual(queueDelta1, queueDelta2, 'resumed tracker must transfer the same queue delta')
        return MissedBonusWindowResult(cityArmyDelta=cityDelta2, queueDelta=queueDelta2)

    def _measure_killer_capture_deltas(self, tracker: OpponentTracker) -> tuple[int, dict[int, int]]:
        """Runs pending captures and returns (killer fog-city delta, per-size killer queue delta)."""
        killerTeam = tracker._team_lookup_by_player[self._KILLER]
        killerStats = tracker.current_team_cycle_stats[killerTeam]
        cityBefore = killerStats.approximate_fog_city_army
        queueBefore = tracker.get_player_gather_queue(self._KILLER).get_amount_dict()
        tracker._process_pending_player_captures()
        cityDelta = killerStats.approximate_fog_city_army - cityBefore
        queueAfter = tracker.get_player_gather_queue(self._KILLER).get_amount_dict()
        queueDelta = {
            size: queueAfter.get(size, 0) - queueBefore.get(size, 0)
            for size in set(queueAfter) | set(queueBefore)
            if queueAfter.get(size, 0) - queueBefore.get(size, 0) != 0}
        return cityDelta, queueDelta

    def test_should_add_missed_capture_window_bonuses_only_for_analyzed_turns(self) -> None:
        """
        A capture frozen at turn 50 whose zero update was already analyzed
        through turn 51 missed one city-bonus tick and one army-bonus tick:
        each halved queue entry gains +1 army and each of the 2 inherited fog
        cities gains +2 army on top of the pool transfer (+4 city total). The
        same bank analyzed only through turn 49 (window not yet elapsed) gets
        neither, and turn-52 bonuses stay with the normal analyze loop.
        """
        noElapsed = self._run_missed_bonus_window(49)
        elapsed = self._run_missed_bonus_window(51)

        # baseline: pure halving of city 30 -> 15, queue {3:2,7:1} -> {2:2,4:1}
        self.assertEqual(15, noElapsed.cityArmyDelta)
        self.assertEqual({2: 2, 4: 1}, noElapsed.queueDelta)

        # elapsed window: +2*(1 city bonus + 1 army bonus) = +4 city army and
        # +1 army on every halved queue entry -> {3:2,5:1}
        self.assertEqual(19, elapsed.cityArmyDelta)
        self.assertEqual({3: 2, 5: 1}, elapsed.queueDelta)

    def test_should_reset_placeholder_counts_once_capture_banks_are_consumed(self) -> None:
        """
        Placeholder-1 credits accrued for a pending capture must reset to zero
        once every frozen bank is consumed, so a later unrelated capture's
        removal pass cannot spend them on legitimate size-1 gather entries.
        """
        rawMap, _ = self.load_map_and_general(self._MAP_FILE, respect_undiscovered=True, turn=243)
        tracker = OpponentTracker(rawMap)
        self._zero_victim_team_scoreboard(rawMap, tracker)
        tracker._snapshot_zero_score_transitions()
        tracker.notify_player_capture(self._VICTIM, self._KILLER)

        # credits the pending capture's zeroed-victim analyzes would have accrued
        tracker._capture_placeholder_counts[self._KILLER] = 7
        tracker._capture_placeholder_counts[0] = 3
        tracker._process_pending_player_captures()

        self.assertEqual(0, len(tracker._unresolved_player_captures))
        self.assertEqual(
            [0 for _ in rawMap.players],
            tracker._capture_placeholder_counts,
            'placeholder credits must reset to zero once every capture bank is consumed')

        # second unrelated capture (p6 -> p4): make removal fully eligible and
        # prove the helper sees recorded == 0 so nothing is consumed.
        self._zero_victim_team_scoreboard(rawMap, tracker, playerIdx=6)
        tracker._snapshot_zero_score_transitions()
        tracker._update_capture_previous_scores()
        secondBank = tracker._unresolved_player_captures[6]
        previousVictim = secondBank.previousScores[6]
        inheritedFogNonCity = max(
            0, previousVictim.tiles - previousVictim.visibleOwnedTiles - secondBank.fogCityCount)
        self.assertGreater(inheritedFogNonCity, 0, 'removal eligibility requires inherited fog non-city land')

        killerQueue = tracker.get_player_gather_queue(self._KILLER)
        for _ in range(4):
            killerQueue.append(1)
        self.assertGreater(killerQueue.get_count(1), 0)

        recordedSeen: list[int] = []
        onesDeltaSeen: list[int] = []
        originalRemove = tracker._remove_capture_placeholder_ones

        def removalSpy(capturee: int, capturer: int, snapshot: CaptureFogSnapshot) -> None:
            recordedSeen.append(tracker._capture_placeholder_counts[capturer])
            onesBefore = tracker.get_player_gather_queue(capturer).get_count(1)
            originalRemove(capturee, capturer, snapshot)
            onesDeltaSeen.append(tracker.get_player_gather_queue(capturer).get_count(1) - onesBefore)

        tracker._remove_capture_placeholder_ones = removalSpy
        tracker.notify_player_capture(6, self._KILLER)
        tracker._process_pending_player_captures()

        self.assertEqual([0], recordedSeen, 'spent placeholder credits must not leak into the next capture')
        self.assertEqual([0], onesDeltaSeen, 'no placeholder ones may be removed without recorded credits')
        self.assertEqual(0, len(tracker._unresolved_player_captures))

    def test_should_reject_malformed_capture_state_lengths(self) -> None:
        """A present ot_capture_state must carry exact per-player lengths; padding would hide corruption."""
        rawMap, _ = self.load_map_and_general(self._MAP_FILE, respect_undiscovered=True, turn=243)
        tracker = OpponentTracker(rawMap)
        validState = {
            'prev_scores': [score.to_dict() for score in tracker._capture_previous_scores],
            'prev_turn': tracker._capture_previous_turn,
            'unresolved': {},
            'completed': [],
            'placeholder_counts': [0 for _ in rawMap.players],
            'last_losses': {},
            'pending': [],
        }
        # sanity: the well-formed state loads cleanly
        tracker._deserialize_capture_state(validState)

        malformedPlaceholders = dict(validState)
        malformedPlaceholders['placeholder_counts'] = [0]
        with self.assertRaises(ValueError):
            tracker._deserialize_capture_state(malformedPlaceholders)

        malformedScores = dict(validState)
        malformedScores['prev_scores'] = validState['prev_scores'][:-1]
        with self.assertRaises(ValueError):
            tracker._deserialize_capture_state(malformedScores)

        missingSection = dict(validState)
        del missingSection['pending']
        with self.assertRaises(KeyError):
            tracker._deserialize_capture_state(missingSection)
