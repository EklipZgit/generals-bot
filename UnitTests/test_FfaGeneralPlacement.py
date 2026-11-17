"""
Unit tests for FfaGeneralPlacement - the joint FFA predicted-general placement
subsystem that keeps every living player's predicted general seed legal
(>= min_spawn_distance apart, hard-valid, non-neutral-discovered) and scores each
seed only from that player's own evidence.

Regression context: Tests/test_FogLandBuilder.py::FogLandBuilderTests.
test_should_separate_ffa_fog_land_from_predicted_generals - at turn 31 of the
Human.exe FFA replay, treasurecritter8's (player 4) candidate region
{(16,7),(17,7),(18,8),(18,9)} sat next to an 'e' fog-land strip at x=17,y=4..8.
The proven defect was that the pre-joint code passed the TARGET player's
predicted seed to EVERY player's fog build, so each player's speculative land
anchored to player 4's prediction rather than their own.
"""

import os
import random
import typing
import unittest
from dataclasses import dataclass
from multiprocessing import Queue
from unittest.mock import patch

from ArmyTracker import ArmyTracker
import ArmyTracker as ArmyTrackerModule
from BotModules.BotRendering import BotRendering
from BotModules.BotSerialization import BotSerialization
from BotModules.BotTargeting import BotTargeting
from FfaGeneralPlacement import (
    FfaGeneralPlacement,
    GeneralLandEvidence,
    _NoInfoPackResult)
from Sim.TextMapLoader import PLAYER_CHAR_INDEX_PAIRS
from TestBase import TestBase
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile
from base.viewer import GeneralsViewer

_PLAYER_CHAR_BY_INDEX = {index: char for char, index in PLAYER_CHAR_INDEX_PAIRS}


@dataclass(slots=True)
class _PlacementPositionsStub:
    """Minimal FfaGeneralPlacement stub exposing only .positions for the
    FFAPredictedGeneralPositions serializer."""
    positions: typing.List[Tile | None]


@dataclass(slots=True)
class _SerializationArmyTrackerStub:
    """Minimal ArmyTracker stub for BotSerialization position converters."""
    ffa_general_placement: _PlacementPositionsStub


@dataclass(slots=True)
class _SerializationBotStub:
    """Minimal duck-typed bot for BotSerialization converters: they read
    bot._map and, for the positions codec, bot.armyTracker.ffa_general_placement.positions."""
    _map: MapBase
    armyTracker: _SerializationArmyTrackerStub


class _NoChoiceRandom(random.Random):
    """random.Random whose choice() always raises: proves a placement refresh
    retained every still-legal prior without needing a single random pick."""

    __slots__ = ()

    def choice(self, seq: typing.Sequence[Tile]) -> Tile:
        """Fail loudly if any code path still needs a random pick."""
        raise AssertionError('rng.choice must not run when every no-info prior survives')


class _RecordingRandom(random.Random):
    """random.Random subclass that records every choice() pool and result so
    tests can assert exactly which legal pool was offered (deterministic seeded
    instance injected via patch('random.Random'))."""

    __slots__ = ('choice_calls',)

    def __init__(
            self,
            seed: int,
            choice_calls: typing.List[typing.Tuple[typing.List[Tile], Tile]],
    ) -> None:
        """Seed the PRNG and share the caller's call log."""
        super().__init__(seed)
        self.choice_calls = choice_calls

    def choice(self, seq: typing.Sequence[Tile]) -> Tile:
        """Record the exact pool offered, then delegate to Random.choice."""
        result = super().choice(seq)
        self.choice_calls.append((list(seq), result))
        return result


def _build_map_string(
        width: int,
        height: int,
        cells: typing.Dict[typing.Tuple[int, int], str],
        tile_counts: typing.Dict[int, int],
        turn: int = 100,
        dead_players: typing.Optional[typing.Set[int]] = None,
) -> str:
    """Build a txtmap string for a synthetic FFA map (no teams key => every player
    is their own team). cells maps (x,y) to cell text like 'aG1', 'b1', 'M';
    missing cells are empty neutral land."""
    cellWidth = 4
    lines = ['|' + (' ' * (cellWidth - 1) + '|') * (width - 1)]
    for y in range(height):
        rowCells = []
        for x in range(width):
            rowCells.append(cells.get((x, y), ' ').ljust(cellWidth))
        lines.append(''.join(rowCells).rstrip())
    lines.append('|' + (' ' * (cellWidth - 1) + '|') * (width - 1))
    lines.append(f'turn={turn}')
    lines.append('player_index=0')
    for playerIndex, count in tile_counts.items():
        char = _PLAYER_CHAR_BY_INDEX[playerIndex]
        lines.append(f'{char}Tiles={count}')
        if dead_players is not None and playerIndex in dead_players:
            lines.append(f'{char}Dead=true')
    return '\n'.join(lines) + '\n'


class FfaGeneralPlacementTests(TestBase):
    __slots__ = ()

    def _load_tracker(
            self,
            width: int = 40,
            height: int = 30,
            cells: typing.Optional[typing.Dict[typing.Tuple[int, int], str]] = None,
            players: typing.Optional[typing.List[int]] = None,
            dead_players: typing.Optional[typing.Set[int]] = None,
            turn: int = 100,
    ) -> typing.Tuple[MapBase, ArmyTracker]:
        """Load a synthetic FFA map (all tiles fogged) with a fresh ArmyTracker.
        Player 0 is 'us' with a known general at (1,1) unless cells override it."""
        if cells is None:
            cells = {}
        cells = dict(cells)
        cells.setdefault((1, 1), 'aG1')
        if players is None:
            players = [0, 1, 2, 3]
        tileCounts = {p: 10 for p in players}
        rawMap = _build_map_string(width, height, cells, tileCounts, turn=turn, dead_players=dead_players)
        map, _general = self.load_map_and_general_from_string(rawMap, turn=turn, player_index=0, respect_undiscovered=True)
        return map, ArmyTracker(map)

    def _set_candidates(self, tracker: ArmyTracker, player: int, tiles: typing.List[Tile]) -> None:
        """Replace a player's valid-general-position matrix with exactly these tiles."""
        matrix = tracker.valid_general_positions_by_player[player]
        matrix.raw[:] = [False] * len(matrix.raw)
        for tile in tiles:
            matrix.raw[tile.tile_index] = True

    def _only_candidates(
            self,
            map: MapBase,
            tracker: ArmyTracker,
            player: int,
            tiles: typing.List[Tile],
    ) -> typing.List[Tile]:
        """Restrict a player's candidates to exactly these tiles."""
        self._set_candidates(tracker, player, tiles)
        return tiles

    def _add_evidence(
            self,
            tracker: ArmyTracker,
            player: int,
            tile: Tile,
            firstSeenTurn: int,
            tileCount: int,
            transferred: bool = False,
    ) -> None:
        """Insert a GeneralLandEvidence entry directly and bump the evidence
        revision, modeling an observation already recorded by the tracker."""
        tracker.ffa_general_land_evidence[player][tile] = GeneralLandEvidence(
            tile=tile, first_seen_turn=firstSeenTurn, player_tile_count=tileCount, transferred=transferred)
        tracker.ffa_land_evidence_revision += 1

    def _add_emergence(
            self,
            tracker: ArmyTracker,
            player: int,
            tile: Tile,
            emergenceValue: float = 5.0,
            uneliminatedValue: int = 10,
    ) -> None:
        """Seed both emergence stores for a player: the event dict used for
        informed classification/ordering and the score matrix used for scoring."""
        tracker.uneliminated_emergence_events[player][tile] = uneliminatedValue
        tracker.emergenceLocationMap[player].raw[tile.tile_index] = emergenceValue

    # --------------------------------------------------------------- spacing

    def test_distance_9_legal_and_distance_8_rejected(self) -> None:
        """Two unknown players whose only candidates sit 8 Manhattan apart cannot
        both be placed (complete=False, one seed missing); at distance 9 both
        placements are legal."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        bTiles = self._only_candidates(map, tracker, 1, [map.At(20, 10)])
        cTiles = self._only_candidates(map, tracker, 2, [map.At(20, 18)])  # dist 8 from b

        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=1)

        self.assertEqual(placement.positions[1], bTiles[0])
        self.assertIsNone(placement.positions[2], 'distance-8 placement must be rejected')
        self.assertFalse(placement.complete)

        # same setup at distance 9 is fully legal
        map2, tracker2 = self._load_tracker(players=[0, 1, 2])
        bTiles2 = self._only_candidates(map2, tracker2, 1, [map2.At(20, 10)])
        cTiles2 = self._only_candidates(map2, tracker2, 2, [map2.At(20, 19)])  # dist 9
        placement2 = tracker2.ffa_general_placement
        placement2.refresh(tracker2, target_player=1)

        self.assertEqual(placement2.positions[1], bTiles2[0])
        self.assertEqual(placement2.positions[2], cTiles2[0])
        self.assertTrue(placement2.complete)

    def test_distance_8_rejected_near_known_general(self) -> None:
        """A candidate 8 tiles from a KNOWN living enemy general is illegal even
        though it is hard-valid and undiscovered."""
        map, tracker = self._load_tracker(
            players=[0, 1, 2],
            cells={(20, 10): 'bG1', (20, 18): ' ', (20, 19): ' '})
        # player 1's general is the bG1 tile -> known fixed placement. The tile is
        # fogged under respect_undiscovered so the loader leaves map.generals[1]
        # unset; assign it directly to model the already-seen general.
        knownGen = map.At(20, 10)
        self.assertTrue(knownGen.isGeneral)
        map.generals[1] = knownGen
        map.players[1].general = knownGen
        cTiles = self._only_candidates(map, tracker, 2, [map.At(20, 18)])  # dist 8 from (20,10)

        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=2)

        self.assertEqual(placement.positions[1], knownGen)
        self.assertIsNone(placement.positions[2], 'candidate 8 from known general must be rejected')
        self.assertFalse(placement.complete)

    def test_distance_8_rejected_near_ex_general_blocker(self) -> None:
        """A dead player's retained former-general position is a fixed exclusion
        anchor: candidates within spawn distance of it are rejected."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3], dead_players={3})
        # simulate a retained former general for the dead player
        exGen = map.At(25, 25)
        exGen.isGeneral = True
        exGen.player = 3
        map.generals[3] = exGen
        map.players[3].general = exGen
        map.players[3].dead = True

        self._only_candidates(map, tracker, 1, [map.At(25, 20)])  # dist 5 -> rejected
        self._set_candidates(tracker, 2, [map.At(25, 4)])  # dist 21 -> legal

        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=1)

        self.assertIsNone(placement.positions[1], 'candidate 5 from ex-general must be rejected')
        self.assertIsNotNone(placement.positions[2])
        self.assertIn(exGen, placement.ex_general_blockers)

    # --------------------------------------------------------------- ordering

    def test_target_orders_first_when_informed(self) -> None:
        """The target player places before emergence holders even when it only has
        land evidence; contested tile goes to the target."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        contested = map.At(20, 10)
        # target=1 (land-only evidence), player 2 has emergence events
        self._only_candidates(map, tracker, 1, [map.At(20, 10), map.At(20, 25)])
        self._only_candidates(map, tracker, 2, [map.At(20, 10), map.At(35, 10)])
        self._only_candidates(map, tracker, 3, [map.At(35, 25)])
        self._add_evidence(tracker, 1, map.At(19, 11), 90, 5)
        # p2's emergence at (25,12) keeps its contested-vs-alternative score gap
        # (~4.8) below p1's pass-2 move cost (~13), so the alternative pass is
        # rejected and first-come order decides the contested tile for the
        # target. An emergence at (21,11) would make p2's loss ~27 and the
        # alternative pass would legitimately evict p1.
        self._add_emergence(tracker, 2, map.At(25, 12), emergenceValue=5.0)

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            placement.refresh(tracker, target_player=1)

        self.assertEqual(placement.positions[1], contested)
        self.assertNotEqual(placement.positions[2], contested)

    def test_emergence_count_orders_players(self) -> None:
        """Among non-target informed players, more emergence events place first."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        contested = map.At(20, 10)
        # player 2: two emergence sources; player 3: one. Neither is target.
        self._only_candidates(map, tracker, 2, [map.At(20, 10), map.At(35, 10)])
        self._only_candidates(map, tracker, 3, [map.At(20, 10), map.At(10, 25)])
        self._only_candidates(map, tracker, 1, [map.At(35, 25)])
        self._add_emergence(tracker, 2, map.At(21, 10), emergenceValue=5.0)
        self._add_emergence(tracker, 2, map.At(19, 12), emergenceValue=5.0)
        self._add_emergence(tracker, 3, map.At(21, 12), emergenceValue=5.0)

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            placement.refresh(tracker, target_player=-1)

        self.assertEqual(placement.positions[2], contested)
        self.assertNotEqual(placement.positions[3], contested)

    # --------------------------------------------------------------- scoring/conflicts

    def _two_player_conflict_setup(
            self,
            map: MapBase,
            tracker: ArmyTracker,
            bAltScore: float,
    ) -> typing.Tuple[Tile, Tile, Tile, Tile]:
        """Target=1 prefers T1; player 2 prefers C1 (within 9 of T1) over C2.
        Returns (T1, T2, C1, C2)."""
        T1 = map.At(20, 10)
        T2 = map.At(20, 25)
        C1 = map.At(20, 15)   # manhattan 5 from T1 -> conflict
        C2 = map.At(35, 15)   # far from everything
        self._only_candidates(map, tracker, 1, [T1, T2])
        self._only_candidates(map, tracker, 2, [C1, C2])
        # player 1: emergence-driven scores (informed via events)
        tracker.emergenceLocationMap[1].raw[T1.tile_index] = 100.0
        tracker.emergenceLocationMap[1].raw[T2.tile_index] = bAltScore
        tracker.uneliminated_emergence_events[1][map.At(5, 5)] = 10
        # player 2: emergence-driven scores
        tracker.emergenceLocationMap[2].raw[C1.tile_index] = 90.0
        tracker.emergenceLocationMap[2].raw[C2.tile_index] = 10.0
        tracker.uneliminated_emergence_events[2][map.At(30, 5)] = 10
        return T1, T2, C1, C2

    def test_conflict_alternative_improves_total_loss_is_selected(self) -> None:
        """When moving the blocker >=4 Manhattan away costs less total score loss
        than the victim's displacement, the alternative placement is adopted."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        T1, T2, C1, C2 = self._two_player_conflict_setup(map, tracker, bAltScore=50.0)

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            changed = placement.refresh(tracker, target_player=1)

        # scores under event-proximity + matrix residue: T1=104.76, T2=52.78,
        # C1=94.76, C2=16.25. pass1: p1->T1, p2->C2 (loss 78.51). pass2:
        # p1->T2 (loss 51.98), p2->C1 (loss 0) -> total 51.98 < 78.51 ->
        # alternative wins.
        self.assertTrue(changed)
        self.assertEqual(placement.positions[1], T2)
        self.assertEqual(placement.positions[2], C1)
        self.assertTrue(placement.complete)
        self.assertAlmostEqual(placement.score_loss, 51.984, places=3)

    def test_worse_alternative_retains_original_placement(self) -> None:
        """When the blocker's alternative costs more than the victim's loss, the
        original greedy placement is kept."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        T1, T2, C1, C2 = self._two_player_conflict_setup(map, tracker, bAltScore=1.0)

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            placement.refresh(tracker, target_player=1)

        # pass2 loss for p1 = 104.76-3.78=100.98 > pass1 loss 78.51 -> keep pass1.
        self.assertEqual(placement.positions[1], T1)
        self.assertEqual(placement.positions[2], C2)
        self.assertAlmostEqual(placement.score_loss, 78.512, places=3)

    def test_movement_loss_counted_once_with_multiple_blockers(self) -> None:
        """A victim blocked by two earlier placements records one conflict row per
        blocker but its score loss is accumulated exactly once, and the alternative
        pass (which would cost more) is rejected."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        # Order: p1 target first, p2 emergence, p3 land-only last.
        # p1 -> B1=(20,16), p2 -> B2=(14,10): both within 9 of p3's preferred V=(20,10)
        # but >=9 from each other, so both legally block V for p3.
        B1 = map.At(20, 16)
        alt1 = map.At(20, 26)   # pass-2 escape for p1 (dist 10 from B1)
        B2 = map.At(14, 10)
        alt2 = map.At(35, 10)   # pass-2 escape for p2 (dist 21 from B2)
        V = map.At(20, 10)      # p3's preferred tile, dist 6 from both B1 and B2
        alt3 = map.At(10, 25)   # p3's fallback, legal vs everything
        self._only_candidates(map, tracker, 1, [B1, alt1])
        self._only_candidates(map, tracker, 2, [B2, alt2])
        self._only_candidates(map, tracker, 3, [V, alt3])
        tracker.emergenceLocationMap[1].raw[B1.tile_index] = 100.0
        tracker.emergenceLocationMap[1].raw[alt1.tile_index] = 1.0
        tracker.uneliminated_emergence_events[1][map.At(5, 5)] = 10
        tracker.emergenceLocationMap[2].raw[B2.tile_index] = 90.0
        tracker.emergenceLocationMap[2].raw[alt2.tile_index] = 10.0
        tracker.uneliminated_emergence_events[2][map.At(30, 5)] = 10
        # p3: land-only informed; V outscores alt3 via emergence map, centroid near V.
        tracker.emergenceLocationMap[3].raw[V.tile_index] = 95.0
        tracker.emergenceLocationMap[3].raw[alt3.tile_index] = 10.0
        self._add_evidence(tracker, 3, map.At(19, 11), 90, 5)

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            placement.refresh(tracker, target_player=1)

        p3Conflicts = [c for c in placement.conflicts if c.conflicted_player == 3]
        self.assertEqual(len(p3Conflicts), 2, 'expected one conflict row per blocker')
        blockers = {c.conflicted_by_player for c in p3Conflicts}
        self.assertEqual(blockers, {1, 2})
        # p3 loss = (95 - 2) - (10 - 23) = 93 + 13 = 106, counted ONCE despite two
        # blockers. Pass 2 would move both blockers (loss ~100 + ~75) for p3's 106 -
        # worse, so the original placement is kept.
        self.assertEqual(placement.positions[1], B1)
        self.assertEqual(placement.positions[2], B2)
        self.assertEqual(placement.positions[3], alt3)
        self.assertAlmostEqual(placement.score_loss, 106.0, places=3)

    def test_no_info_players_do_not_affect_score_loss(self) -> None:
        """No-information players pack around informed placements and contribute
        nothing to score_loss."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        # p1 informed via emergence; p2 informed; p3 no-info
        T1 = map.At(20, 10)
        T2 = map.At(20, 25)
        self._only_candidates(map, tracker, 1, [T1, T2])
        self._only_candidates(map, tracker, 2, [map.At(35, 10), map.At(35, 25)])
        self._only_candidates(map, tracker, 3, [map.At(10, 10), map.At(10, 25)])
        tracker.emergenceLocationMap[1].raw[T1.tile_index] = 100.0
        tracker.emergenceLocationMap[1].raw[T2.tile_index] = 50.0
        tracker.uneliminated_emergence_events[1][map.At(5, 5)] = 10
        tracker.emergenceLocationMap[2].raw[map.At(35, 10).tile_index] = 90.0
        tracker.uneliminated_emergence_events[2][map.At(30, 5)] = 10

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            placement.refresh(tracker, target_player=1)

        self.assertTrue(placement.complete)
        self.assertIsNotNone(placement.positions[3])
        self.assertEqual(placement.score_loss, 0.0)

    # --------------------------------------------------------------- no-info packing

    def test_no_info_backtracking_recovers_greedy_dead_end(self) -> None:
        """Greedy first-candidate packing can dead-end; bounded backtracking must
        still find the complete legal packing."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        A = map.At(20, 10)
        B = map.At(20, 25)   # dist 15 from A
        C = map.At(35, 10)   # dist 15+ from both
        # p1={A,B}, p2={A,C}, p3={C}: greedy count-order tries p3->C, p1->A, p2 fails;
        # backtracking finds p1->B, p2->A, p3->C.
        self._only_candidates(map, tracker, 1, [A, B])
        self._only_candidates(map, tracker, 2, [A, C])
        self._only_candidates(map, tracker, 3, [C])

        placement = tracker.ffa_general_placement
        # direct backtracking check: the instance exists and completes the packing
        available = {1: [A, B], 2: [A, C], 3: [C]}
        base = {0: map.generals[0]}
        result = placement._backtrack_pack_no_info(map, [3, 1, 2], available, base, 9, 4096)
        self.assertIsNotNone(result)
        self.assertTrue(result.complete)
        self.assertEqual(result.positions[1], B)
        self.assertEqual(result.positions[2], A)
        self.assertEqual(result.positions[3], C)

        # and through the full refresh the packing also completes
        placement.refresh(tracker, target_player=-1)
        self.assertTrue(placement.complete)
        self.assertIsNotNone(placement.positions[1])
        self.assertIsNotNone(placement.positions[2])
        self.assertIsNotNone(placement.positions[3])

    def test_impossible_packing_returns_explicit_incomplete(self) -> None:
        """Two no-info players sharing a single candidate tile can never both be
        placed; the result is explicitly incomplete but still legal."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        only = map.At(20, 10)
        self._only_candidates(map, tracker, 1, [only])
        self._only_candidates(map, tracker, 2, [only])
        self._only_candidates(map, tracker, 3, [map.At(35, 25)])

        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)

        self.assertFalse(placement.complete)
        placed = [p for p in (1, 2, 3) if placement.positions[p] is not None]
        self.assertEqual(len(placed), 2, 'exactly one of the two conflicting players should place')
        for p in placed:
            self.assertIsNotNone(placement.positions[p])

    # --------------------------------------------------------------- land evidence weighting

    def test_older_small_land_observation_outweighs_later_large_land(self) -> None:
        """Weight = 1/max(1, tileCount at first observation of THAT tile), frozen.
        An early observation at tileCount 5 (w=0.2) must dominate a later one at
        tileCount 50 (w=0.02) when centering the land-evidence centroid."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        nearEarly = map.At(12, 10)
        nearLate = map.At(32, 10)
        self._only_candidates(map, tracker, 1, [nearEarly, nearLate])
        self._only_candidates(map, tracker, 2, [map.At(35, 25)])
        earlyTile = map.At(12, 12)
        lateTile = map.At(32, 12)
        self._add_evidence(tracker, 1, earlyTile, firstSeenTurn=20, tileCount=5)
        self._add_evidence(tracker, 1, lateTile, firstSeenTurn=90, tileCount=50)

        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)

        # centroid x = (0.2*12 + 0.02*32)/0.22 = 13.8 -> nearEarly (dist ~3.8) beats
        # nearLate (dist ~18.2); equal weights would center at x=22 and tie-break.
        self.assertEqual(placement.positions[1], nearEarly)

    def test_witnessed_transfer_and_temp_predictions_never_shift_centroid(self) -> None:
        """Transferred observations weigh zero; isTempFogPrediction tiles are never
        recorded as evidence at all."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        nearTransfer = map.At(12, 10)
        nearReal = map.At(32, 10)
        self._only_candidates(map, tracker, 1, [nearTransfer, nearReal])
        self._only_candidates(map, tracker, 2, [map.At(35, 25)])
        transferTile = map.At(12, 12)
        realTile = map.At(32, 12)
        self._add_evidence(tracker, 1, transferTile, 20, 5, transferred=True)
        self._add_evidence(tracker, 1, realTile, 20, 5, transferred=False)

        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)

        # only realTile counts -> centroid exactly at (32,12) -> nearReal wins
        self.assertEqual(placement.positions[1], nearReal)

        # temp fog tiles must not create evidence via notify_seen_player_tile
        tempTile = map.At(15, 15)
        tempTile.player = 1
        tempTile.isTempFogPrediction = True
        tempTile.visible = True
        tempTile.delta.gainedSight = True
        tracker.notify_seen_player_tile(tempTile)
        self.assertNotIn(tempTile, tracker.ffa_general_land_evidence[1])

    def test_witnessed_transfer_marked_via_notify(self) -> None:
        """A tile seen flipping from enemy A to enemy B while visible is recorded
        for B with transferred=True (zero weight)."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        tile = map.At(20, 10)
        tile.player = 2
        tile.visible = True
        tile.delta.oldOwner = 1
        tile.delta.newOwner = 2
        tile.delta.gainedSight = False
        # was_visible_last_turn() == visible and not gainedSight -> True
        tracker.notify_seen_player_tile(tile)

        evidence = tracker.ffa_general_land_evidence[2].get(tile)
        self.assertIsNotNone(evidence)
        self.assertTrue(evidence.transferred)
        self.assertEqual(evidence.weight(), 0.0)

    def test_reacquired_sight_is_not_misclassified_as_transfer(self) -> None:
        """Regained vision (gainedSight) whose remembered old owner is a different
        LIVING player must NOT be marked transferred - we did not witness the flip."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        tile = map.At(20, 10)
        tile.player = 2
        tile.visible = True
        tile.delta.oldOwner = 1   # stale remembered owner, player 1 alive
        tile.delta.newOwner = 2
        tile.delta.gainedSight = True   # was_visible_last_turn() -> False
        tracker.notify_seen_player_tile(tile)

        evidence = tracker.ffa_general_land_evidence[2].get(tile)
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence.transferred)
        self.assertGreater(evidence.weight(), 0.0)

    def test_dead_old_owner_counts_as_witnessed_transfer(self) -> None:
        """A flip whose old owner is dead/captured is a bulk observed transfer even
        without last-turn visibility."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3], dead_players={1})
        tile = map.At(20, 10)
        tile.player = 2
        tile.visible = True
        tile.delta.oldOwner = 1
        tile.delta.newOwner = 2
        tile.delta.gainedSight = True
        map.players[1].capturedBy = 2
        tracker.notify_seen_player_tile(tile)

        evidence = tracker.ffa_general_land_evidence[2].get(tile)
        self.assertIsNotNone(evidence)
        self.assertTrue(evidence.transferred)

    # --------------------------------------------------------------- cache signature

    def _cached_setup(self) -> typing.Tuple[MapBase, ArmyTracker]:
        """Cached-placement fixture: p1 land-influenced near (20,10), p2/p3 placed."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        self._only_candidates(map, tracker, 1, [map.At(20, 10), map.At(20, 25)])
        self._only_candidates(map, tracker, 2, [map.At(35, 10)])
        self._only_candidates(map, tracker, 3, [map.At(10, 25)])
        self._add_evidence(tracker, 1, map.At(19, 11), 90, 5)
        tracker.ffa_general_placement.refresh(tracker, target_player=1)
        return map, tracker

    def test_cache_unchanged_on_pure_growth(self) -> None:
        """Turn growth, army growth, scoreboard tile growth, and temporary fog
        prediction changes must not invalidate the placement cache."""
        map, tracker = self._cached_setup()
        placement = tracker.ffa_general_placement
        sigBefore = placement._signature
        positionsBefore = list(placement.positions)

        map.turn += 1
        someTile = map.At(5, 5)
        someTile.army = 999
        map.players[1].tileCount = 500
        otherTile = map.At(6, 6)
        otherTile.isTempFogPrediction = True
        otherTile.player = 2

        changed = placement.refresh(tracker, target_player=1)
        self.assertFalse(changed)
        self.assertEqual(placement._signature, sigBefore)
        self.assertEqual(
            [t.tile_index if t is not None else None for t in placement.positions],
            [t.tile_index if t is not None else None for t in positionsBefore])

    def test_cache_invalidates_on_reveal_neutral_emergence_general_death_trade_target(self) -> None:
        """Each evidence-bearing input change must bust the signature so the next
        refresh recomputes (asserted via signature inequality, since positions may
        legitimately stay identical)."""
        map, tracker = self._cached_setup()
        placement = tracker.ffa_general_placement

        def assert_invalidated(mutate: typing.Callable[[], None]) -> None:
            sigBefore = placement._signature
            mutate()
            placement.refresh(tracker, target_player=1)
            self.assertNotEqual(
                placement._signature, sigBefore,
                f'signature did not change after {mutate.__name__}')

        def revealEnemy() -> None:
            tracker.seen_player_lookup[2] = True
        assert_invalidated(revealEnemy)
        tracker.seen_player_lookup[2] = False

        neutralTile = map.At(20, 10)
        def discoverNeutral() -> None:
            neutralTile.discoveredAsNeutral = True
        assert_invalidated(discoverNeutral)
        def undiscoverNeutral() -> None:
            neutralTile.discoveredAsNeutral = False
        assert_invalidated(undiscoverNeutral)

        def addEmergence() -> None:
            self._add_emergence(tracker, 2, map.At(30, 20), emergenceValue=4.0)
        assert_invalidated(addEmergence)

        genTile = map.At(30, 20)
        def discoverGeneral() -> None:
            genTile.isGeneral = True
            genTile.player = 2
            map.generals[2] = genTile
            map.players[2].general = genTile
        assert_invalidated(discoverGeneral)
        def undiscoverGeneral() -> None:
            map.generals[2] = None
            map.players[2].general = None
            genTile.isGeneral = False
            genTile.player = -1
        assert_invalidated(undiscoverGeneral)

        def killPlayer() -> None:
            map.players[3].dead = True
        assert_invalidated(killPlayer)
        def revivePlayer() -> None:
            map.players[3].dead = False
        assert_invalidated(revivePlayer)

        sigBefore = placement._signature
        placement.refresh(tracker, target_player=2)
        self.assertNotEqual(placement._signature, sigBefore)
        placement.refresh(tracker, target_player=1)

    def test_cache_invalidates_on_trade_swap(self) -> None:
        map, tracker = self._cached_setup()
        placement = tracker.ffa_general_placement
        sigBefore = placement._signature
        tracker._swap_traded_player_state(1, 2)
        placement.refresh(tracker, target_player=1)
        self.assertNotEqual(placement._signature, sigBefore)

    # --------------------------------------------------------------- serialization

    def test_evidence_serialization_roundtrip(self) -> None:
        """GeneralLandEvidence entries round-trip through the BotSerialization
        converters preserving weights (tileCount) and transferred flags."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        tileA = map.At(10, 10)
        tileB = map.At(20, 20)
        tracker.ffa_general_land_evidence[1][tileA] = GeneralLandEvidence(tileA, 30, 7, False)
        tracker.ffa_general_land_evidence[1][tileB] = GeneralLandEvidence(tileB, 40, 12, True)
        tracker.ffa_land_evidence_revision += 2

        bot = self._minimal_bot_for_serialization(map)
        serialized = BotSerialization.convert_general_land_evidence_to_string(bot, tracker.ffa_general_land_evidence[1])
        restored = BotSerialization.convert_string_to_general_land_evidence(bot, serialized)

        self.assertEqual(len(restored), 2)
        evA = restored[tileA]
        self.assertEqual(evA.first_seen_turn, 30)
        self.assertEqual(evA.player_tile_count, 7)
        self.assertFalse(evA.transferred)
        self.assertAlmostEqual(evA.weight(), 1.0 / 7.0)
        evB = restored[tileB]
        self.assertEqual(evB.player_tile_count, 12)
        self.assertTrue(evB.transferred)
        self.assertEqual(evB.weight(), 0.0)

    def test_general_positions_serialization_roundtrip(self) -> None:
        """FFAPredictedGeneralPositions codec: exactly one row-major tile_index
        slot per player in player.index order, '-1' for empty slots; the parse
        side resolves real Tile objects on the given map."""
        map, _tracker = self._load_tracker(players=[0, 1, 2, 3])
        tileA = map.At(10, 10)
        tileB = map.At(20, 20)
        positions: typing.List[Tile | None] = [tileA, None, tileB, None]
        bot = self._minimal_bot_for_serialization(map, positions=positions)

        serialized = BotSerialization.convert_general_positions_to_string(bot)
        self.assertEqual(
            f'{tileA.tile_index},-1,{tileB.tile_index},-1', serialized)

        restored = BotSerialization.convert_string_to_general_positions(bot, serialized)
        self.assertEqual(4, len(restored))
        self.assertIs(map.At(10, 10), restored[0])
        self.assertIsNone(restored[1])
        self.assertIs(map.At(20, 20), restored[2])
        self.assertIsNone(restored[3])

    def test_general_positions_empty_vector_serializes_all_minus_one(self) -> None:
        """positions == [] (placement never refreshed) still emits one '-1'
        slot per map player so the footer vector stays well-formed."""
        map, _tracker = self._load_tracker(players=[0, 1, 2, 3])
        bot = self._minimal_bot_for_serialization(map, positions=[])

        serialized = BotSerialization.convert_general_positions_to_string(bot)
        self.assertEqual('-1,-1,-1,-1', serialized)

        restored = BotSerialization.convert_string_to_general_positions(bot, serialized)
        self.assertEqual([None, None, None, None], restored)

    def test_general_positions_codec_rejects_malformed_vectors(self) -> None:
        """Strict parse: exactly len(players) slots, each '-1' or a valid
        row-major tile_index; wrong counts, non-integers, values below -1, and
        out-of-range indices all raise ValueError."""
        map, _tracker = self._load_tracker(players=[0, 1, 2, 3])
        bot = self._minimal_bot_for_serialization(map)
        maxIndex = map.cols * map.rows - 1

        badVectors = [
            '1,2,3',
            '1,2,3,4,5',
            '1,2,x,4',
            '1,2,-2,4',
            f'1,2,{maxIndex + 1},4',
        ]
        for data in badVectors:
            with self.assertRaises(ValueError, msg=f'vector {data!r} must raise ValueError'):
                BotSerialization.convert_string_to_general_positions(bot, data)

    def test_serialized_positions_restore_as_sticky_priors_without_choice(self) -> None:
        """Stage6 resume path: a serialized position vector parsed onto a fresh
        placement becomes sticky no-info priors - after invalidate() the first
        refresh keeps every still-legal prior with ZERO rng.choice calls while
        informed seeds still follow current evidence."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        seedA = map.At(30, 20)
        seedB = map.At(10, 20)
        self._only_candidates(map, tracker, 1, [seedA, seedB])
        tracker.emergenceLocationMap[1].raw[seedA.tile_index] = 100.0
        tracker.emergenceLocationMap[1].raw[seedB.tile_index] = 50.0
        tracker.uneliminated_emergence_events[1][map.At(5, 5)] = 10
        # no-info pools legal vs BOTH possible p1 seeds so priors survive the flip
        self._set_candidates(tracker, 2, [
            map.At(20, 10), map.At(20, 14), map.At(22, 10)])
        self._set_candidates(tracker, 3, [
            map.At(15, 15), map.At(25, 15), map.At(18, 8)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(777, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)
        self.assertTrue(placement.complete)
        self.assertEqual(placement.positions[1], seedA)
        prior2 = placement.positions[2]
        prior3 = placement.positions[3]
        self.assertIsNotNone(prior2)
        self.assertIsNotNone(prior3)

        # serialize -> parse -> fresh placement, exactly like a txtmap resume
        bot = self._minimal_bot_for_serialization(map, positions=placement.positions)
        serialized = BotSerialization.convert_general_positions_to_string(bot)
        restored = BotSerialization.convert_string_to_general_positions(bot, serialized)
        restoredPlacement = FfaGeneralPlacement()
        restoredPlacement.positions = restored
        restoredPlacement.invalidate()

        # unrelated evidence change flips the informed seed; no-info priors stay legal
        tracker.emergenceLocationMap[1].raw[seedA.tile_index] = 10.0
        tracker.emergenceLocationMap[1].raw[seedB.tile_index] = 200.0
        with patch('random.Random', _NoChoiceRandom):
            changed = restoredPlacement.refresh(tracker, target_player=1)

        self.assertTrue(changed)
        self.assertEqual(
            restoredPlacement.positions[1], seedB,
            'informed seed must follow new evidence after resume')
        self.assertEqual(
            restoredPlacement.positions[2], prior2,
            'still-legal restored no-info prior must be retained without re-roll')
        self.assertEqual(
            restoredPlacement.positions[3], prior3,
            'still-legal restored no-info prior must be retained without re-roll')

    def test_serialized_stale_prior_is_replaced_while_legal_priors_stick(self) -> None:
        """A restored no-info slot that is no longer hard-valid must be
        re-placed through rng.choice on a still-legal tile; every other
        still-legal restored prior stays exactly put (Stage6 resume path)."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        anchor = map.At(30, 20)
        self._only_candidates(map, tracker, 1, [anchor])
        self._add_emergence(tracker, 1, map.At(29, 21), emergenceValue=5.0)
        self._set_candidates(tracker, 2, [
            map.At(20, 10), map.At(20, 14), map.At(22, 12), map.At(33, 5)])
        self._set_candidates(tracker, 3, [map.At(15, 15), map.At(25, 15)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(99, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)
        self.assertTrue(placement.complete)
        prior2 = placement.positions[2]
        prior3 = placement.positions[3]
        self.assertIsNotNone(prior2)
        self.assertIsNotNone(prior3)

        # codec roundtrip onto a fresh placement (resume simulation)
        bot = self._minimal_bot_for_serialization(map, positions=placement.positions)
        serialized = BotSerialization.convert_general_positions_to_string(bot)
        restored = BotSerialization.convert_string_to_general_positions(bot, serialized)
        restoredPlacement = FfaGeneralPlacement()
        restoredPlacement.positions = restored
        restoredPlacement.invalidate()

        # hard-eliminate p2's restored prior -> it must re-place; p3's stays
        tracker.valid_general_positions_by_player[2].raw[prior2.tile_index] = False
        choiceCalls.clear()
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            changed = restoredPlacement.refresh(tracker, target_player=1)

        self.assertTrue(changed)
        self.assertIsNotNone(restoredPlacement.positions[2])
        self.assertNotEqual(
            restoredPlacement.positions[2], prior2,
            'eliminated restored prior must be replaced by a random legal pick')
        self.assertTrue(
            tracker.valid_general_positions_by_player[2][restoredPlacement.positions[2]],
            'replacement must be a hard-valid candidate')
        self.assertEqual(
            restoredPlacement.positions[3], prior3,
            'still-legal restored p3 prior must be retained while p2 repacks')
        self.assertTrue(choiceCalls, 're-placement must go through random choice')

    def test_known_general_outranks_serialized_position_slot(self) -> None:
        """A serialized slot conflicting with a KNOWN living general is ignored:
        map.generals stays authoritative and the refreshed position for that
        player is always the known general tile (Stage6 resume path)."""
        map, tracker = self._load_tracker(
            players=[0, 1, 2, 3],
            cells={(20, 10): 'bG1'})
        knownGen = map.At(20, 10)
        self.assertTrue(knownGen.isGeneral)
        map.generals[1] = knownGen
        map.players[1].general = knownGen
        self._set_candidates(tracker, 2, [map.At(30, 20), map.At(10, 20)])
        self._set_candidates(tracker, 3, [map.At(15, 15), map.At(25, 15)])
        placement = tracker.ffa_general_placement

        spyRng = _RecordingRandom(555, [])
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)
        self.assertEqual(placement.positions[1], knownGen)
        realPositions = list(placement.positions)

        # forge a conflicting saved slot for the known-general player
        conflicting = map.At(8, 8)
        tampered: typing.List[Tile | None] = [
            realPositions[0], conflicting, realPositions[2], realPositions[3]]
        bot = self._minimal_bot_for_serialization(map, positions=tampered)
        serialized = BotSerialization.convert_general_positions_to_string(bot)
        restored = BotSerialization.convert_string_to_general_positions(bot, serialized)
        restoredPlacement = FfaGeneralPlacement()
        restoredPlacement.positions = restored
        restoredPlacement.invalidate()

        with patch('random.Random', lambda *args, **kwargs: spyRng):
            restoredPlacement.refresh(tracker, target_player=1)

        self.assertEqual(
            restoredPlacement.positions[1], knownGen,
            'known living general must outrank the serialized slot')
        self.assertEqual(restoredPlacement.positions[2], realPositions[2])
        self.assertEqual(restoredPlacement.positions[3], realPositions[3])

    def _minimal_bot_for_serialization(
            self,
            map: MapBase,
            positions: typing.Optional[typing.List[Tile | None]] = None,
    ) -> _SerializationBotStub:
        """Duck-typed bot stub for BotSerialization converter tests."""
        placement = _PlacementPositionsStub(
            positions=positions if positions is not None else [])
        armyTracker = _SerializationArmyTrackerStub(ffa_general_placement=placement)
        return _SerializationBotStub(_map=map, armyTracker=armyTracker)

    def test_legacy_resume_bootstraps_from_discovered_tiles_only(self) -> None:
        """A tracker whose evidence keys were never serialized (old fixture) must
        bootstrap from actually-discovered enemy-owned tiles only - never from
        fog-inferred (isTempFogPrediction) or undiscovered ownership."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        # player 1 owns two tiles: one discovered (real observation), one temp fog guess
        seenTile = map.At(10, 10)
        seenTile.player = 1
        seenTile.discovered = True
        seenTile.visible = False
        tempTile = map.At(11, 10)
        tempTile.player = 1
        tempTile.isTempFogPrediction = True
        tempTile.discovered = False
        # an undiscovered enemy-owned tile that is NOT temp (should not happen in
        # practice, but bootstrap must still require discovered=True)
        hiddenTile = map.At(12, 10)
        hiddenTile.player = 1
        hiddenTile.discovered = False
        hiddenTile.isTempFogPrediction = False

        self._only_candidates(map, tracker, 1, [map.At(20, 10)])
        self._only_candidates(map, tracker, 2, [map.At(30, 25)])
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)

        evidence = tracker.ffa_general_land_evidence[1]
        self.assertIn(seenTile, evidence)
        self.assertNotIn(tempTile, evidence)
        self.assertNotIn(hiddenTile, evidence)

    def test_general_trade_swaps_placement_state(self) -> None:
        """_swap_traded_player_state must exchange land evidence between the pair
        and invalidate the placement cache."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        tileA = map.At(10, 10)
        tileB = map.At(30, 25)
        tracker.ffa_general_land_evidence[1][tileA] = GeneralLandEvidence(tileA, 30, 7, False)
        tracker.ffa_general_land_evidence[2][tileB] = GeneralLandEvidence(tileB, 40, 12, False)
        tracker.ffa_land_evidence_revision += 2
        self._only_candidates(map, tracker, 1, [map.At(20, 10)])
        self._only_candidates(map, tracker, 2, [map.At(35, 10)])
        self._only_candidates(map, tracker, 3, [map.At(10, 25)])
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)
        sigBefore = placement._signature

        tracker._swap_traded_player_state(1, 2)

        self.assertIn(tileA, tracker.ffa_general_land_evidence[2])
        self.assertIn(tileB, tracker.ffa_general_land_evidence[1])
        self.assertIsNone(placement._signature)
        self.assertTrue(placement.refresh(tracker, target_player=-1))

    # --------------------------------------------------------------- fog seeding

    def test_fog_seeding_empty_emergence_uses_own_seed(self) -> None:
        """With no emergence events, get_fog_connected_based_on_emergences must seed
        the spanning tree and genDistMap from the player's own placement seed, not
        from every valid general candidate."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        seed = map.At(20, 15)
        otherCandidate = map.At(30, 20)
        # give player 1 a broad valid set but a chosen placement seed
        self._set_candidates(tracker, 1, [seed, otherCandidate, map.At(10, 25)])
        tracker.ffa_general_placement.positions = [None, seed, None, None]
        # mark as FFA-consistent state: placement.positions[player] is the seed

        with tracker.perf_timer.begin_move(map.turn):
            banned, connected, core, pathToUnelim, genDistMap, maxGenReach = (
                tracker.get_fog_connected_based_on_emergences(1, seed))

        self.assertIn(seed, connected)
        self.assertIsNotNone(genDistMap)
        self.assertEqual(genDistMap.raw[seed.tile_index], 0,
                         'genDistMap must originate BFS at the player seed')
        # a tile near the seed but far from otherCandidate must have small genDist
        nearSeed = map.At(21, 15)
        self.assertLess(genDistMap.raw[nearSeed.tile_index], 1000)

    def test_fog_seeding_non_ffa_unchanged_uses_valid_spots(self) -> None:
        """Non-FFA maps keep the legacy genDistMap over all valid general positions."""
        map, tracker = self._load_tracker(players=[0, 1])
        # 2 players -> not original FFA
        seed = map.At(20, 15)
        with tracker.perf_timer.begin_move(map.turn):
            banned, connected, core, pathToUnelim, genDistMap, maxGenReach = (
                tracker.get_fog_connected_based_on_emergences(1, seed))
        self.assertIsNotNone(genDistMap)

    # ------------------------------------------- stage3 review regression tests

    def test_temp_fog_ownership_never_removes_general_candidates(self) -> None:
        """Speculative fog ownership (isTempFogPrediction + player>=0, including
        stale guesses anchored to a previous seed) must NEVER shrink the candidate
        set: seeds stay at their last best spots across recomputes."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        T1 = map.At(20, 10)
        T2 = map.At(20, 25)
        self._only_candidates(map, tracker, 1, [T1, T2])
        self._only_candidates(map, tracker, 2, [map.At(35, 10)])
        self._only_candidates(map, tracker, 3, [map.At(10, 25)])
        self._add_evidence(tracker, 1, map.At(19, 11), 90, 5)
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)
        seedBefore = placement.positions[1]
        self.assertIsNotNone(seedBefore)

        # fog fills mark every p1 candidate temp-owned by another player's guess
        for tile in tracker.valid_general_positions_by_player[1]:
            tile.isTempFogPrediction = True
            tile.player = 2
        # unrelated neutral discovery forces a signature change + recompute
        map.At(5, 5).discoveredAsNeutral = True

        placement.refresh(tracker, target_player=-1)
        self.assertEqual(
            placement.positions[1], seedBefore,
            'temp fog ownership must not move the chosen seed')
        self.assertTrue(placement.complete)

    def test_transfer_marking_busts_evidence_cache(self) -> None:
        """Flipping an EXISTING evidence entry to transferred must bump
        ffa_land_evidence_revision so the next refresh rescores the centroid."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        nearA = map.At(12, 10)
        nearB = map.At(32, 10)
        self._only_candidates(map, tracker, 1, [nearA, nearB])
        self._only_candidates(map, tracker, 2, [map.At(35, 25)])
        tileX = map.At(12, 12)   # heavy early evidence near nearA
        tileB = map.At(32, 12)   # light late evidence near nearB
        self._add_evidence(tracker, 1, tileX, 20, 5)
        self._add_evidence(tracker, 1, tileB, 90, 50)
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)
        self.assertEqual(placement.positions[1], nearA,
                         'heavy early evidence should pull the seed to nearA')
        sigBefore = placement._signature
        revBefore = tracker.ffa_land_evidence_revision

        # witnessed transfer 2->1 while visible: existing entry flips to zero weight
        tileX.player = 1
        tileX.visible = True
        tileX.delta.oldOwner = 2
        tileX.delta.newOwner = 1
        tileX.delta.gainedSight = False
        tracker.notify_seen_player_tile(tileX)

        self.assertTrue(tracker.ffa_general_land_evidence[1][tileX].transferred)
        self.assertGreater(
            tracker.ffa_land_evidence_revision, revBefore,
            'transfer flip on an existing entry must bump the evidence revision')
        placement.refresh(tracker, target_player=-1)
        self.assertNotEqual(placement._signature, sigBefore)
        self.assertEqual(
            placement.positions[1], nearB,
            'with tileX zeroed the centroid must move to nearB')

    def test_late_finalize_transfer_busts_cache(self) -> None:
        """The dead/captured-old-owner finalize path marking an existing entry
        transferred must also bump the revision."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3], dead_players={2})
        tileX = map.At(20, 20)
        self._add_evidence(tracker, 1, tileX, 20, 5)
        revBefore = tracker.ffa_land_evidence_revision

        tileX.player = 1
        tileX.visible = True
        tileX.delta.oldOwner = 2
        tileX.delta.newOwner = 1
        tileX.delta.gainedSight = True
        tracker._flipped_tiles.add(tileX)
        tracker._finalize_general_land_evidence_transfers()

        self.assertTrue(tracker.ffa_general_land_evidence[1][tileX].transferred)
        self.assertGreater(
            tracker.ffa_land_evidence_revision, revBefore,
            'late finalize transfer must bump the evidence revision')

    def test_bootstrap_marks_witnessed_transfer_zero_weight(self) -> None:
        """First-refresh bootstrap must apply witnessed-transfer semantics: a
        discovered enemy tile whose current delta proves a transfer gets weight 0
        instead of fabricated positive weight."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        tile = map.At(10, 10)
        tile.player = 1
        tile.discovered = True
        tile.visible = True
        tile.delta.oldOwner = 2
        tile.delta.newOwner = 1
        tile.delta.gainedSight = False

        self._only_candidates(map, tracker, 1, [map.At(20, 10)])
        self._only_candidates(map, tracker, 2, [map.At(35, 25)])
        self._only_candidates(map, tracker, 3, [map.At(10, 25)])
        tracker.ffa_general_placement.refresh(tracker, target_player=-1)

        evidence = tracker.ffa_general_land_evidence[1].get(tile)
        self.assertIsNotNone(evidence)
        self.assertTrue(evidence.transferred)
        self.assertEqual(evidence.weight(), 0.0)

    def test_missing_informed_player_records_conflicts_for_alternate_pass(self) -> None:
        """p2's ONLY candidate sits <9 from the target's preferred T1 but >=9 from
        T2; pass 1 leaves p2 unplaced, and the recorded conflicts must still let
        pass 2 move the target to T2 and complete."""
        map, tracker = self._load_tracker(players=[0, 1, 2])
        T1 = map.At(20, 10)
        T2 = map.At(20, 25)
        C1 = map.At(20, 15)   # dist 5 from T1, dist 10 from T2
        self._only_candidates(map, tracker, 1, [T1, T2])
        self._only_candidates(map, tracker, 2, [C1])
        tracker.emergenceLocationMap[1].raw[T1.tile_index] = 100.0
        tracker.emergenceLocationMap[1].raw[T2.tile_index] = 50.0
        tracker.uneliminated_emergence_events[1][map.At(5, 5)] = 10
        tracker.emergenceLocationMap[2].raw[C1.tile_index] = 90.0
        tracker.uneliminated_emergence_events[2][map.At(30, 5)] = 10

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            placement.refresh(tracker, target_player=1)

        self.assertTrue(placement.complete)
        self.assertEqual(placement.positions[1], T2)
        self.assertEqual(placement.positions[2], C1)
        self.assertGreater(len(placement.conflicts), 0,
                           'missing informed player must still record blocking conflicts')

    def test_emergence_matrix_signal_alone_marks_player_informed(self) -> None:
        """Positive emergenceLocationMap values with EMPTY event sets still make a
        player informed: it is scored and placed before no-info packing."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        A = map.At(20, 5)    # lower tile_index -> natural candidate order first
        B = map.At(20, 15)   # higher score via emergence map
        F = map.At(35, 15)
        self._only_candidates(map, tracker, 1, [A, B])
        self._only_candidates(map, tracker, 2, [B, F])
        self._only_candidates(map, tracker, 3, [map.At(10, 25)])
        # matrix-only signal: NO uneliminated/unrecaptured events, NO land evidence
        tracker.emergenceLocationMap[1].raw[B.tile_index] = 50.0
        tracker.emergenceLocationMap[1].raw[A.tile_index] = 10.0

        with patch.object(ArmyTrackerModule, 'EMERGENCE_DISTANCE_BONUS_ENABLED', False):
            placement = tracker.ffa_general_placement
            placement.refresh(tracker, target_player=-1)

        self.assertTrue(placement.complete)
        self.assertEqual(
            placement.positions[1], B,
            'matrix-only informed player must take its scored best before no-info packing')
        self.assertEqual(placement.positions[2], F)

    def test_refresh_reports_no_change_when_positions_identical(self) -> None:
        """Both-None positions (dead player) must not count as 'changed': a
        recompute with identical outcomes returns False and sets no rebuild flags."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3], dead_players={3})
        self._only_candidates(map, tracker, 1, [map.At(20, 10), map.At(20, 25)])
        self._only_candidates(map, tracker, 2, [map.At(35, 10)])
        self._add_evidence(tracker, 1, map.At(19, 11), 90, 5)
        placement = tracker.ffa_general_placement
        self.assertTrue(placement.refresh(tracker, target_player=1))
        for p in map.players:
            tracker.should_recalc_fog_land_by_player[p.index] = False

        placement.invalidate()
        changed = placement.refresh(tracker, target_player=1)
        self.assertFalse(
            changed, 'identical positions including the dead player must report no change')
        self.assertFalse(any(tracker.should_recalc_fog_land_by_player))

    def test_dead_general_blocker_signature_stable_across_refreshes(self) -> None:
        """A dead player's retained general added to ex_general_blockers during
        recompute must already be inside the stored signature, so an immediate
        second refresh does not recompute."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3], dead_players={3})
        exGen = map.At(25, 25)
        exGen.isGeneral = True
        exGen.player = 3
        map.generals[3] = exGen
        map.players[3].general = exGen
        self._only_candidates(map, tracker, 1, [map.At(20, 10)])
        self._only_candidates(map, tracker, 2, [map.At(35, 10)])
        placement = tracker.ffa_general_placement
        self.assertTrue(placement.refresh(tracker, target_player=-1))
        self.assertFalse(
            placement.refresh(tracker, target_player=-1),
            'second refresh with unchanged inputs must not recompute')

    def test_captured_player_gets_no_placement(self) -> None:
        """capturedBy!=None with dead=False excludes the player from positions,
        packing, completeness, and the renderer; its former general stays an
        exclusion anchor."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        gen3 = map.At(30, 20)
        gen3.isGeneral = True
        gen3.player = 3
        map.generals[3] = gen3
        map.players[3].general = gen3
        map.players[3].capturedBy = 1
        self._only_candidates(map, tracker, 1, [map.At(20, 10)])
        self._only_candidates(map, tracker, 2, [map.At(35, 10)])
        self._only_candidates(map, tracker, 3, [map.At(25, 25)])
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)

        self.assertIsNone(placement.positions[3])
        self.assertTrue(placement.complete, 'captured player must not count as missing')
        self.assertIn(gen3, placement.ex_general_blockers)
        viewInfo = ViewInfo(5, map)
        BotRendering.populate_predicted_general_targets(viewInfo, map, placement)
        self.assertFalse(
            any(t.player == 3 for t in viewInfo.predicted_general_targets),
            'captured player must not get a prediction ring')

    def test_clear_temp_fog_gated_to_original_ffa(self) -> None:
        """The pending-rebuild temp-guess pre-clear only runs for original FFA;
        1v1/2v2 keep their existing temp guesses untouched."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3], turn=30)
        tempTile = map.At(20, 20)
        tempTile.player = 1
        tempTile.isTempFogPrediction = True
        tempTile.discovered = False
        map.players[1].tiles.append(tempTile)
        tracker.should_recalc_fog_land_by_player[1] = True
        tracker.clear_temp_fog_predictions_for_pending_rebuilds()
        self.assertNotIn(tempTile, map.players[1].tiles)

        map2, tracker2 = self._load_tracker(players=[0, 1], turn=30)
        tempTile2 = map2.At(20, 20)
        tempTile2.player = 1
        tempTile2.isTempFogPrediction = True
        tempTile2.discovered = False
        map2.players[1].tiles.append(tempTile2)
        tracker2.should_recalc_fog_land_by_player[1] = True
        tracker2.clear_temp_fog_predictions_for_pending_rebuilds()
        self.assertIn(tempTile2, map2.players[1].tiles)

    def test_targeting_returns_sentinel_when_ffa_placement_incomplete(self) -> None:
        """BotTargeting returns the existing bot.general sentinel (never an
        independent illegal guess) when the joint FFA placement has no seed for
        the target player."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        self._set_candidates(tracker, 1, [])
        self._only_candidates(map, tracker, 2, [map.At(35, 10)])
        self._only_candidates(map, tracker, 3, [map.At(10, 25)])
        tracker.ffa_general_placement.refresh(tracker, target_player=1)
        self.assertIsNone(tracker.ffa_general_placement.positions[1])

        class _BotStub:
            __slots__ = ('targetPlayer', '_map', 'armyTracker', 'general')

            def __init__(self, m: MapBase, t: ArmyTracker) -> None:
                self.targetPlayer = 1
                self._map = m
                self.armyTracker = t
                self.general = m.generals[0]

        bot = _BotStub(map, tracker)
        result = BotTargeting.get_predicted_target_player_general_location(bot)
        self.assertIs(result, bot.general)

    def test_stale_ffa_seed_never_seeds_fog_land(self) -> None:
        """A cached placement seed disproved after refresh (neutral-discovered and
        eliminated from the hard matrix) must NOT enter requiredTiles or become
        the genDistMap BFS source."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        seed = map.At(20, 15)
        self._set_candidates(tracker, 1, [seed, map.At(30, 20), map.At(10, 25)])
        tracker.ffa_general_placement.positions = [None, seed, None, None]
        seed.discoveredAsNeutral = True
        tracker.valid_general_positions_by_player[1].raw[seed.tile_index] = False

        with tracker.perf_timer.begin_move(map.turn):
            banned, connected, core, pathToUnelim, genDistMap, maxGenReach = (
                tracker.get_fog_connected_based_on_emergences(1, seed))

        self.assertNotIn(seed, connected)
        self.assertNotIn(seed, core)
        self.assertNotEqual(
            genDistMap.raw[seed.tile_index], 0,
            'disproved seed must not be a genDistMap BFS source (distance 0)')

    def test_ffa_fog_connects_observed_land_evidence_without_emergence(self) -> None:
        """With no emergence events the spanning web must still connect the
        player's own seed AND two old observed enemy land tiles (positive
        non-transferred evidence) - the seed alone must not satisfy the required
        set."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        seed = map.At(20, 15)
        self._set_candidates(tracker, 1, [seed, map.At(30, 20), map.At(10, 25)])
        tracker.ffa_general_placement.positions = [None, seed, None, None]
        evA = map.At(18, 14)
        evB = map.At(22, 16)
        self._add_evidence(tracker, 1, evA, 50, 5)
        self._add_evidence(tracker, 1, evB, 50, 5)

        with tracker.perf_timer.begin_move(map.turn):
            banned, connected, core, pathToUnelim, genDistMap, maxGenReach = (
                tracker.get_fog_connected_based_on_emergences(1, seed))

        self.assertIn(seed, connected)
        self.assertIn(evA, connected)
        self.assertIn(evB, connected)

    def test_no_info_random_choice_recovers_greedy_bottleneck(self) -> None:
        """Shared candidate masks that dead-ended every deterministic
        first-legal greedy must be recovered by randomized legal-pool choice
        BEFORE the bounded backtracking pass is needed. The rng is seeded here
        only to keep the test deterministic; production uses unseeded entropy."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        # no-info players 1,2,3 share a bottleneck verified by exhaustive search:
        # every player-ordering x natural-candidate-order greedy dead-ends, so
        # recovery depends on the randomized legal-pool choice drawing a
        # non-dead-ending pick within the bounded attempts. Seed 7 was verified
        # to complete on a greedy attempt (0 backtracking calls).
        self._set_candidates(tracker, 1, [map.At(12, 12)])
        self._set_candidates(tracker, 2, [map.At(19, 10), map.At(22, 10)])
        self._set_candidates(tracker, 3, [map.At(8, 12), map.At(18, 15)])
        placement = tracker.ffa_general_placement
        backtrackCalls: typing.List[int] = []
        originalBacktrack = FfaGeneralPlacement._backtrack_pack_no_info

        def spyBacktrack(
                placementSelf: FfaGeneralPlacement,
                mapArg: MapBase,
                orderingArg: typing.List[int],
                availableArg: typing.Dict[int, typing.List[Tile]],
                baseArg: typing.Dict[int, Tile],
                minDistanceArg: int,
                nodeBudgetArg: int,
        ) -> _NoInfoPackResult | None:
            """Records the invocation, then delegates to the real bounded backtracker."""
            backtrackCalls.append(1)
            return originalBacktrack(
                placementSelf, mapArg, orderingArg, availableArg,
                baseArg, minDistanceArg, nodeBudgetArg)

        packRng = random.Random(7)
        with (
            patch('random.Random', lambda *args, **kwargs: packRng),
            patch.object(FfaGeneralPlacement, '_backtrack_pack_no_info', spyBacktrack)
        ):
            placement.refresh(tracker, target_player=-1)

        self.assertTrue(placement.complete)
        placed = [placement.positions[p] for p in (1, 2, 3)]
        self.assertTrue(all(t is not None for t in placed))
        self.assertEqual(
            backtrackCalls, [],
            'randomized legal-pool choice should recover the greedy bottleneck '
            'without needing bounded backtracking')

    # --------------------------------------------------------------- random no-info packing

    def test_no_info_greedy_uses_random_choice_over_currently_legal_pool(self) -> None:
        """First-attempt no-info packing must offer random.choice the CURRENT
        legal pool rather than taking the first row-major candidate: a
        distance-8 tile is pruned from later players' pools while a
        distance-9 tile survives, hard candidate masks stay unmutated, and the
        informed anchor keeps its seed. Guards the user's 'top-edge line'
        report where every no-info general clustered on the first legal row."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        anchor = map.At(35, 22)
        self._only_candidates(map, tracker, 1, [anchor])
        self._add_emergence(tracker, 1, map.At(34, 21), emergenceValue=5.0)
        aTiles = [
            map.At(20, 10), map.At(22, 10), map.At(24, 10),
            map.At(20, 12), map.At(22, 12), map.At(24, 12)]
        self._set_candidates(tracker, 2, aTiles)
        bTiles: typing.List[Tile] = []
        for a in aTiles:
            bTiles.append(map.At(a.x + 8, a.y))  # manhattan 8 from a
            bTiles.append(map.At(a.x + 9, a.y))  # manhattan 9 from a
        self._set_candidates(tracker, 3, bTiles)

        rawBefore = {
            p: tracker.valid_general_positions_by_player[p].raw[:]
            for p in (1, 2, 3)}
        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(0xC0FFEE, choiceCalls)
        placement = tracker.ffa_general_placement
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)

        self.assertTrue(placement.complete)
        self.assertEqual(placement.positions[1], anchor, 'informed anchor must keep its seed')
        for p in (0, 1, 2, 3):
            self.assertIsNotNone(placement.positions[p])
        for i, idxA in enumerate((0, 1, 2, 3)):
            for idxB in (0, 1, 2, 3)[i + 1:]:
                self.assertGreaterEqual(
                    map.manhattan_dist(placement.positions[idxA], placement.positions[idxB]),
                    tracker.min_spawn_distance)
        for p in (1, 2, 3):
            self.assertEqual(
                tracker.valid_general_positions_by_player[p].raw, rawBefore[p],
                f'p{p} hard candidate mask must not be mutated by packing')
        self.assertGreaterEqual(len(choiceCalls), 2, 'random choice must drive no-info packing')
        self.assertTrue(
            any(pick != pool[0] for pool, pick in choiceCalls),
            'no-info packing must not always take the first row-major candidate')
        firstPick = choiceCalls[0][1]
        nearTile = map.At(firstPick.x + 8, firstPick.y)
        farTile = map.At(firstPick.x + 9, firstPick.y)
        secondPool = choiceCalls[1][0]
        self.assertNotIn(nearTile, secondPool, 'distance-8 tile must be pruned from later pools')
        self.assertIn(farTile, secondPool, 'distance-9 tile must remain legal')
        for pool, _pick in choiceCalls:
            for t in pool:
                self.assertGreaterEqual(
                    map.manhattan_dist(t, anchor), tracker.min_spawn_distance,
                    f'offered pool tile {t} violates spacing vs the informed anchor')

    def test_no_info_prior_positions_stick_across_evidence_recompute(self) -> None:
        """When evidence changes force a recompute, every still-legal prior
        no-info seed must be RESERVED before any random placement: retained
        players keep their exact tiles and random.choice is never invoked for
        them, so evidence refreshes cannot jitter packed positions."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        seedA = map.At(30, 20)
        seedB = map.At(10, 20)
        self._only_candidates(map, tracker, 1, [seedA, seedB])
        tracker.emergenceLocationMap[1].raw[seedA.tile_index] = 100.0
        tracker.emergenceLocationMap[1].raw[seedB.tile_index] = 50.0
        tracker.uneliminated_emergence_events[1][map.At(5, 5)] = 10
        # no-info pools legal vs BOTH possible p1 seeds so priors survive the flip
        self._set_candidates(tracker, 2, [
            map.At(20, 10), map.At(20, 14), map.At(22, 10)])
        self._set_candidates(tracker, 3, [
            map.At(15, 15), map.At(25, 15), map.At(18, 8)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(777, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)
        self.assertTrue(placement.complete)
        self.assertEqual(placement.positions[1], seedA)
        prior2 = placement.positions[2]
        prior3 = placement.positions[3]
        self.assertIsNotNone(prior2)
        self.assertIsNotNone(prior3)
        self.assertGreaterEqual(len(choiceCalls), 2, 'first pack must use random choice')

        # unrelated evidence change flips the informed seed; no-info priors stay legal
        tracker.emergenceLocationMap[1].raw[seedA.tile_index] = 10.0
        tracker.emergenceLocationMap[1].raw[seedB.tile_index] = 200.0
        choiceCalls.clear()
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            changed = placement.refresh(tracker, target_player=1)

        self.assertTrue(changed)
        self.assertEqual(placement.positions[1], seedB, 'informed seed must follow new evidence')
        self.assertEqual(
            placement.positions[2], prior2,
            'still-legal prior no-info seed must be retained, not re-rolled')
        self.assertEqual(
            placement.positions[3], prior3,
            'still-legal prior no-info seed must be retained, not re-rolled')
        self.assertEqual(
            choiceCalls, [],
            'retained no-info positions must be reserved without any random choice')

    def test_no_info_displaced_player_cannot_steal_retained_prior(self) -> None:
        """When a moved informed seed invalidates ONE no-info player's prior,
        reservation must still protect every OTHER retained prior: the
        displaced player's random pool must not contain a retained player's
        old tile even when that tile is one of its own candidates."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        seedA = map.At(30, 20)
        p3Tiles = [map.At(15, 15), map.At(25, 15), map.At(18, 8)]
        self._only_candidates(map, tracker, 1, [seedA])
        self._add_emergence(tracker, 1, map.At(29, 21), emergenceValue=5.0)
        self._set_candidates(tracker, 3, p3Tiles)
        # p2's pool includes every p3 candidate so a displaced p2 could steal
        # p3's retained prior without reservation-first ordering.
        self._set_candidates(tracker, 2, p3Tiles + [
            map.At(12, 15), map.At(20, 10), map.At(20, 14),
            map.At(5, 25), map.At(35, 5)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(4242, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)
        self.assertTrue(placement.complete)
        prior2 = placement.positions[2]
        prior3 = placement.positions[3]
        self.assertIsNotNone(prior2)
        self.assertIsNotNone(prior3)
        self.assertNotEqual(prior2, prior3)

        # pick a new informed seed <9 from p2's prior but >=9 from p3's prior
        blocker = self._find_seed_displacing_one_prior(map, tracker, prior2, prior3)
        self._set_candidates(tracker, 1, [seedA, blocker])
        tracker.emergenceLocationMap[1].raw[blocker.tile_index] = 500.0
        tracker.emergenceLocationMap[1].raw[seedA.tile_index] = 1.0
        choiceCalls.clear()
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            changed = placement.refresh(tracker, target_player=1)

        self.assertTrue(changed)
        self.assertEqual(placement.positions[1], blocker)
        self.assertEqual(
            placement.positions[3], prior3,
            'retained prior must be reserved before the displaced player repacks')
        self.assertIsNotNone(placement.positions[2])
        self.assertNotEqual(
            placement.positions[2], prior2,
            'displaced player must move off its now-illegal prior')
        self.assertNotEqual(
            placement.positions[2], prior3,
            'displaced player must not steal the retained prior tile')
        self.assertTrue(choiceCalls, 'displaced player must be re-placed via random choice')
        for pool, _pick in choiceCalls:
            self.assertNotIn(
                prior3, pool,
                'retained prior tile must be pruned from the displaced player pools')

    def _find_seed_displacing_one_prior(
            self,
            map: MapBase,
            tracker: ArmyTracker,
            displacedTile: Tile,
            retainedTile: Tile,
    ) -> Tile:
        """Find a hard-plain-land tile inside spawn distance of displacedTile
        (so it invalidates that prior) but at least min_spawn_distance from
        retainedTile's prior and from our known general."""
        ownGeneral = map.generals[0]
        minDistance = tracker.min_spawn_distance
        for dx in range(-8, 9):
            for dy in range(-8, 9):
                dist = abs(dx) + abs(dy)
                if dist == 0 or dist >= minDistance:
                    continue
                nx, ny = displacedTile.x + dx, displacedTile.y + dy
                if not (0 <= nx < map.cols and 0 <= ny < map.rows):
                    continue
                q = map.At(nx, ny)
                if map.manhattan_dist(q, retainedTile) < minDistance:
                    continue
                if map.manhattan_dist(q, ownGeneral) < minDistance:
                    continue
                return q
        self.fail('no tile satisfies the required distances')

    def test_no_info_hard_eliminated_prior_gets_random_replacement(self) -> None:
        """A prior no-info tile removed from the hard candidate mask must not
        be retained: the player is randomly re-placed on a still-legal tile
        while other still-legal priors stay put."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        anchor = map.At(30, 20)
        self._only_candidates(map, tracker, 1, [anchor])
        self._add_emergence(tracker, 1, map.At(29, 21), emergenceValue=5.0)
        self._set_candidates(tracker, 2, [
            map.At(20, 10), map.At(20, 14), map.At(22, 12), map.At(33, 5)])
        self._set_candidates(tracker, 3, [map.At(15, 15), map.At(25, 15)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(99, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)
        self.assertTrue(placement.complete)
        prior2 = placement.positions[2]
        prior3 = placement.positions[3]
        self.assertIsNotNone(prior2)
        self.assertIsNotNone(prior3)
        self.assertGreaterEqual(len(choiceCalls), 2, 'first pack must use random choice')

        # hard-eliminate p2's prior from the candidate mask -> signature recompute
        tracker.valid_general_positions_by_player[2].raw[prior2.tile_index] = False
        choiceCalls.clear()
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            changed = placement.refresh(tracker, target_player=1)

        self.assertTrue(changed)
        self.assertIsNotNone(placement.positions[2])
        self.assertNotEqual(
            placement.positions[2], prior2,
            'eliminated prior must be replaced by a random legal pick')
        self.assertTrue(
            tracker.valid_general_positions_by_player[2][placement.positions[2]],
            'replacement must be a hard-valid candidate')
        self.assertEqual(
            placement.positions[3], prior3,
            'still-legal p3 prior must be retained while p2 repacks')
        self.assertTrue(choiceCalls, 're-placement must go through random choice')

    def test_no_info_prior_never_blocks_informed_target_best(self) -> None:
        """No-info prior reservation happens only AFTER informed placement: a
        no-info player's old tile sitting on the target's new best seed must be
        displaced, never reserved over the informed choice."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        t1 = map.At(30, 20)
        t2 = map.At(10, 20)
        self._only_candidates(map, tracker, 1, [t2])
        tracker.emergenceLocationMap[1].raw[t2.tile_index] = 100.0
        tracker.uneliminated_emergence_events[1][map.At(5, 5)] = 10
        # p2's only refresh-1 candidate IS the tile the target will later prefer
        self._only_candidates(map, tracker, 2, [t1])
        self._set_candidates(tracker, 3, [map.At(15, 15), map.At(25, 15)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(31337, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=1)
        self.assertEqual(placement.positions[1], t2)
        self.assertEqual(placement.positions[2], t1, 'p2 prior should sit on t1')

        # target's evidence flips its best to t1; give p2 replacement candidates
        self._set_candidates(tracker, 1, [t1, t2])
        tracker.emergenceLocationMap[1].raw[t1.tile_index] = 500.0
        tracker.emergenceLocationMap[1].raw[t2.tile_index] = 1.0
        self._set_candidates(tracker, 2, [t1, map.At(20, 10), map.At(20, 14)])
        choiceCalls.clear()
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            changed = placement.refresh(tracker, target_player=1)

        self.assertTrue(changed)
        self.assertEqual(
            placement.positions[1], t1,
            'informed target must keep its best seed; no-info priors never override it')
        self.assertIsNotNone(placement.positions[2])
        self.assertNotEqual(
            placement.positions[2], t1,
            'p2 prior on the target seed must be displaced, not retained')
        self.assertTrue(
            tracker.valid_general_positions_by_player[2][placement.positions[2]],
            'displaced p2 must land on a hard-valid candidate')
        self.assertTrue(choiceCalls, 'displaced p2 must re-place via random choice')

    # --------------------------------------------------------------- fill-capacity elimination

    def _make_fillable_pocket(
            self,
            map: MapBase,
            interior: typing.List[Tile],
    ) -> None:
        """Wall the given interior tiles off from the map's giant fog component by
        marking every movable neighbor outside the interior discoveredAsNeutral,
        modeling replay Human.exe-ffa-2026-11-16_08-52-16---qhHFvFbUi turn 36 where
        a neutral reveal collapsed a predicted spawn's pocket to a single tile."""
        interiorSet = set(interior)
        for tile in interior:
            for neighbor in tile.movable:
                if neighbor not in interiorSet:
                    neighbor.discoveredAsNeutral = True

    def test_fill_capacity_one_tile_pocket_hard_eliminates_for_all_no_info(self) -> None:
        """A candidate whose fillable component holds only itself (every movable
        neighbor sighted neutral/visible) can never contain a real general's
        land: it is HARD-eliminated from EVERY no-info player's pool, recorded
        in fill_capacity_eliminated_hard, and never offered to rng.choice."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        pocket = map.At(20, 10)
        self._make_fillable_pocket(map, [pocket])
        # both no-info players share the pocket as a candidate plus one far tile
        self._set_candidates(tracker, 1, [map.At(35, 25)])
        self._set_candidates(tracker, 2, [pocket, map.At(35, 10)])
        self._set_candidates(tracker, 3, [pocket, map.At(10, 25)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(24601, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=-1)

        self.assertTrue(placement.complete)
        self.assertIn(
            pocket, placement.fill_capacity_eliminated_hard,
            'capacity-1 pocket must be hard-eliminated')
        self.assertNotEqual(
            placement.positions[2], pocket, 'p2 must not place on the pocket')
        self.assertNotEqual(
            placement.positions[3], pocket, 'p3 must not place on the pocket')
        self.assertEqual(placement.positions[2], map.At(35, 10))
        self.assertEqual(placement.positions[3], map.At(10, 25))
        for pool, _pick in choiceCalls:
            self.assertNotIn(
                pocket, pool, 'hard-eliminated tile must never enter a choice pool')

    def test_fill_capacity_hard_eliminated_prior_replaced(self) -> None:
        """A prior no-info seed whose pocket collapses to one tile after a
        neutral reveal (the real replay trigger) must be displaced onto a
        still-legal tile, never retained by sticky-prior reservation."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        pocket = map.At(20, 10)
        alt = map.At(35, 10)
        self._set_candidates(tracker, 1, [map.At(35, 25)])
        self._only_candidates(map, tracker, 2, [pocket])
        self._set_candidates(tracker, 3, [map.At(10, 25)])
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)
        self.assertEqual(placement.positions[2], pocket, 'pre-reveal seed sits on the tile')

        # reveal collapses the pocket to a single tile -> signature change -> recompute
        self._make_fillable_pocket(map, [pocket])
        self._set_candidates(tracker, 2, [pocket, alt])
        placement.refresh(tracker, target_player=-1)

        self.assertIn(pocket, placement.fill_capacity_eliminated_hard)
        self.assertEqual(
            placement.positions[2], alt,
            'hard-eliminated prior must be displaced onto the legal alternative')

    def test_fill_capacity_soft_candidates_only_offered_when_no_better(self) -> None:
        """A candidate whose fillable component is smaller than the player's
        scoreboard tileCount is SOFT-eliminated: it stays placeable but
        rng.choice is only offered non-soft tiles while any exist; a player
        whose pool is entirely soft still completes over the soft pool."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        # 2x2 pocket (capacity 4 < tileCount 10) for p2's soft candidate
        pocketTiles = [map.At(30, 10), map.At(30, 11), map.At(31, 10), map.At(31, 11)]
        self._make_fillable_pocket(map, pocketTiles)
        softTile = pocketTiles[0]
        bigTile = map.At(15, 15)
        # second 2x2 pocket for p3's all-soft pool
        pocket3 = [map.At(30, 20), map.At(30, 21), map.At(31, 20), map.At(31, 21)]
        self._make_fillable_pocket(map, pocket3)
        self._set_candidates(tracker, 1, [map.At(10, 5)])
        self._set_candidates(tracker, 2, [softTile, bigTile])
        self._set_candidates(tracker, 3, [pocket3[0], pocket3[1]])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(1357, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=-1)

        self.assertTrue(placement.complete)
        self.assertIn(
            softTile, placement.soft_eliminated_by_player[2],
            'capacity-4 tile must be soft-eliminated for tileCount-10 p2')
        self.assertNotIn(softTile, placement.fill_capacity_eliminated_hard)
        self.assertEqual(
            placement.positions[2], bigTile,
            'non-soft alternative must be chosen over the soft candidate')
        self.assertIn(
            placement.positions[3], {pocket3[0], pocket3[1]},
            'all-soft pool must still place the player')
        p2Pools = [
            pool for pool, _pick in choiceCalls
            if bigTile in pool or softTile in pool]
        self.assertTrue(p2Pools, 'p2 must have been offered a choice pool')
        for pool in p2Pools:
            self.assertNotIn(
                softTile, pool,
                'soft tile must not be offered while a non-soft candidate exists')
        p3Pools = [
            pool for pool, _pick in choiceCalls
            if pocket3[0] in pool or pocket3[1] in pool]
        self.assertTrue(p3Pools, 'p3 must have been offered a choice pool')
        for pool in p3Pools:
            self.assertTrue(
                all(t in {pocket3[0], pocket3[1]} for t in pool),
                'all-soft player must be offered its soft pool')

    def test_fill_capacity_soft_prior_replaced_by_non_soft_alternative(self) -> None:
        """Sticky-prior rule for soft seeds: a soft-eliminated prior is only
        kept when the player has no non-soft candidate; with a non-soft
        alternative the prior is re-placed randomly."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        pocketTiles = [map.At(30, 10), map.At(30, 11), map.At(31, 10), map.At(31, 11)]
        self._make_fillable_pocket(map, pocketTiles)
        softTile = pocketTiles[0]
        altTile = map.At(15, 15)
        self._set_candidates(tracker, 1, [map.At(10, 5)])
        self._only_candidates(map, tracker, 2, [softTile])
        self._set_candidates(tracker, 3, [map.At(35, 25)])
        placement = tracker.ffa_general_placement

        choiceCalls: typing.List[typing.Tuple[typing.List[Tile], Tile]] = []
        spyRng = _RecordingRandom(4242, choiceCalls)
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=-1)
        self.assertEqual(
            placement.positions[2], softTile,
            'all-soft pool must still place the prior seed')

        # a non-soft candidate appears -> soft prior must be re-placed
        self._set_candidates(tracker, 2, [softTile, altTile])
        choiceCalls.clear()
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            changed = placement.refresh(tracker, target_player=-1)

        self.assertTrue(changed)
        self.assertEqual(
            placement.positions[2], altTile,
            'soft prior with a non-soft alternative must be re-placed')
        self.assertTrue(choiceCalls, 're-placement must go through random choice')
        for pool, _pick in choiceCalls:
            self.assertNotIn(
                softTile, pool,
                'soft prior must not be offered once a non-soft candidate exists')

    def test_fill_capacity_soft_prior_sticks_when_all_alternatives_soft(self) -> None:
        """A soft-eliminated prior with ONLY soft alternatives is retained for
        stability - re-rolling between equally-bad tiles would jitter the
        packing for no benefit. No rng.choice may run for that player."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        pocketTiles = [map.At(30, 10), map.At(30, 11), map.At(31, 10), map.At(31, 11)]
        self._make_fillable_pocket(map, pocketTiles)
        self._set_candidates(tracker, 1, [map.At(10, 5)])
        self._set_candidates(tracker, 2, [map.At(15, 15)])
        self._set_candidates(tracker, 3, [pocketTiles[0], pocketTiles[1]])
        placement = tracker.ffa_general_placement

        spyRng = _RecordingRandom(777, [])
        with patch('random.Random', lambda *args, **kwargs: spyRng):
            placement.refresh(tracker, target_player=-1)
        self.assertTrue(placement.complete)
        prior3 = placement.positions[3]
        self.assertIn(prior3, {pocketTiles[0], pocketTiles[1]})
        prior1 = placement.positions[1]
        prior2 = placement.positions[2]

        # identical inputs, forced recompute: every prior must be reserved
        placement.invalidate()
        with patch('random.Random', _NoChoiceRandom):
            placement.refresh(tracker, target_player=-1)

        self.assertEqual(
            placement.positions[3], prior3,
            'soft prior with only-soft alternatives must be retained')
        self.assertEqual(placement.positions[1], prior1)
        self.assertEqual(placement.positions[2], prior2)

    def test_fill_capacity_eliminations_ignore_informed_players(self) -> None:
        """Eliminations are a no-info-only concept: an informed player whose
        evidence prefers a capacity-1 pocket tile is placed on it through the
        evidence path even while the same tile is hard-eliminated for no-info
        players."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        pocket = map.At(20, 10)
        self._make_fillable_pocket(map, [pocket])
        self._only_candidates(map, tracker, 1, [pocket])
        self._add_emergence(tracker, 1, map.At(19, 12), emergenceValue=5.0)
        self._set_candidates(tracker, 2, [pocket, map.At(35, 10)])
        self._set_candidates(tracker, 3, [map.At(10, 25)])
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)

        self.assertIn(
            pocket, placement.fill_capacity_eliminated_hard,
            'pocket still hard-eliminated for the no-info players')
        self.assertEqual(
            placement.positions[1], pocket,
            'informed player must place on the capacity-1 tile from evidence')
        self.assertNotEqual(
            placement.positions[2], pocket,
            'no-info player must not place on the eliminated tile')

    def test_fill_capacity_soft_set_irrelevant_after_emergence_gained(self) -> None:
        """A player that gains emergence information leaves the no-info path:
        its soft-elimination set is recomputed empty and a soft-tagged tile can
        be chosen purely on emergence score."""
        map, tracker = self._load_tracker(players=[0, 1, 2, 3])
        pocketTiles = [map.At(30, 10), map.At(30, 11), map.At(31, 10), map.At(31, 11)]
        self._make_fillable_pocket(map, pocketTiles)
        softTile = pocketTiles[0]
        self._set_candidates(tracker, 1, [map.At(10, 5)])
        self._set_candidates(tracker, 2, [softTile, map.At(15, 15)])
        self._set_candidates(tracker, 3, [map.At(35, 25)])
        placement = tracker.ffa_general_placement
        placement.refresh(tracker, target_player=-1)
        self.assertEqual(
            placement.positions[2], map.At(15, 15),
            'pre-emergence the soft tile must be skipped')

        # emergence info arrives preferring the soft-tagged tile
        self._add_emergence(tracker, 2, map.At(29, 12), emergenceValue=5.0)
        tracker.emergenceLocationMap[2].raw[softTile.tile_index] = 500.0
        placement.refresh(tracker, target_player=-1)

        self.assertEqual(
            placement.positions[2], softTile,
            'informed player must reach the soft-tagged tile on evidence')
        self.assertNotIn(
            2, placement.soft_eliminated_by_player,
            'informed player must not keep a soft-elimination set')


class FfaGeneralPlacementRenderingTests(TestBase):
    __slots__ = ()

    def test_known_general_not_rendered_as_prediction(self) -> None:
        """populate_predicted_general_targets must emit rings only for living
        players whose general is still UNKNOWN; known generals, dead players, and
        our own general get no marker."""
        map, tracker = FfaGeneralPlacementTests._load_tracker(self, players=[0, 1, 2, 3])
        # p1 unknown general with a placement; p2 known general; p3 dead
        seed1 = map.At(20, 10)
        gen2 = map.At(30, 10)
        gen2.isGeneral = True
        gen2.player = 2
        map.generals[2] = gen2
        map.players[2].general = gen2
        map.players[3].dead = True
        placement = FfaGeneralPlacement()
        placement.positions = [map.generals[0], seed1, gen2, None]

        viewInfo = ViewInfo(5, map)
        BotRendering.populate_predicted_general_targets(viewInfo, map, placement)

        targets = viewInfo.predicted_general_targets
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].player, 1)
        self.assertEqual(targets[0].tile, seed1)

    def test_predicted_general_ring_uses_per_player_palette_and_radius(self) -> None:
        """GeneralsViewer.draw_targets renders each predicted-general ring with
        THAT player's palette color at radius cellWidth/2+12; a tile.player
        different from target.player proves the palette index is the target's."""
        map, _tracker = FfaGeneralPlacementTests._load_tracker(self, players=[0, 1, 2, 3])
        seed = map.At(20, 10)
        seed.player = 3   # tile tagged to p3, but the prediction target is p1
        seed.isTempFogPrediction = True
        placement = FfaGeneralPlacement()
        placement.positions = [map.generals[0], seed, None, None]

        viewInfo = ViewInfo(5, map)
        BotRendering.populate_predicted_general_targets(viewInfo, map, placement)
        # populating twice must not duplicate markers
        BotRendering.populate_predicted_general_targets(viewInfo, map, placement)
        self.assertEqual(len(viewInfo.predicted_general_targets), 1)

        os.environ['SDL_VIDEODRIVER'] = 'dummy'
        viewer = GeneralsViewer(Queue(), Queue(), self._testMethodName, cell_width=30, cell_height=30)
        viewer.updateGrid(viewInfo, map)
        viewer._initViewier(alignTop=True, alignLeft=True)
        viewer.player_colors = [(1, 2, 3), (200, 100, 50), (9, 9, 9), (7, 7, 7)]

        with patch('pygame.draw.circle') as mockDrawCircle:
            viewer.draw_targets()

        ringCalls = [
            c for c in mockDrawCircle.call_args_list
            if c.kwargs.get('width') == 4]
        self.assertEqual(
            len(ringCalls), 1,
            f'expected exactly one predicted-general ring, got {mockDrawCircle.call_args_list}')
        ringCall = ringCalls[0]
        self.assertEqual(
            ringCall.args[1], (200, 100, 50),
            'ring must use the TARGET player palette entry, not the tile owner')
        self.assertAlmostEqual(ringCall.kwargs['radius'], 30 / 2 + 12)


if __name__ == '__main__':
    unittest.main()
