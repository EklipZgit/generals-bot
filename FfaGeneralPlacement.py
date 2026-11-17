"""
Joint FFA enemy-general placement.

Solves the multi-player version of 'where can each living player's general be' that
the old target-centric predictor could not: every living player's predicted general
seed is chosen JOINTLY so that no two seeds sit closer than the map's spawn distance,
each seed is scored only from that player's own evidence (emergence events, the
emergence distance bonus, and frozen-weight observed-land centroid),
and players with no information are packed around the informed placements without
influencing their scores.

Tests: UnitTests/test_FfaGeneralPlacement.py,
Tests/test_FogLandBuilder.py::FogLandBuilderTests.test_should_separate_ffa_fog_land_from_predicted_generals
(the confirmed old bug: every player's fog-land build received the TARGET player's
predicted general location as its seed, so one player's fog land anchored to the
target's prediction; per-player joint placement seeds fix the anchor mixup).
"""

from __future__ import annotations

import random
import typing
from dataclasses import dataclass

import logbook

if typing.TYPE_CHECKING:
    from ArmyTracker import ArmyTracker
    from base.client.map import MapBase, Player
    from base.client.tile import Tile


# Score penalty applied to an informed player's total loss when it cannot be placed
# at all. Large enough that any legal placement beats a missing one, small enough to
# keep score_loss readable in logs.
_MISSING_PLACEMENT_SCORE_LOSS: float = 1000.0

# Node budget for the bounded backtracking pass used to recover no-information
# packings that simple greedy orderings miss.
_NO_INFO_BACKTRACK_NODE_BUDGET: int = 4096

# Manhattan distance an alternative-pass conflict causer must move away from its
# first-pass seed for the second joint placement attempt to count as 'moved'.
_CONFLICT_CAUSER_MIN_MOVE: int = 4

# A no-info candidate whose fillable component is smaller than this many tiles
# cannot be a real spawn: the component must hold the general AND at least one
# land tile. Below it the candidate is impossible for every no-info player and
# is removed from all their pools (hard elimination).
_NO_INFO_MIN_FILL_CAPACITY: int = 2

# Weight of the emergence-event proximity term in informed scoring. Each
# surviving emergence event contributes 1/(1+Manhattan distance) to a
# candidate, so ~100 puts a candidate adjacent to its player's own emergence
# clearly ahead of a distant candidate, comparable to the dominance the old
# 10*emergenceLocationMap term gave concentrated flood values.
_EMERGENCE_EVENT_PROXIMITY_WEIGHT: float = 100.0

# Weight of the residual emergenceLocationMap value in informed scoring. The
# matrix is demoted to a weak tilt: legitimate residue (emergence flood values
# that outlive their consumed event sets) still nudges a seed, but the
# concentrated pollution other systems write into the matrix (cross-player
# discovery spread, uniform fog-frontier deposits) can no longer dominate an
# informed pick the way 10*matrix did.
_EMERGENCE_MATRIX_RESIDUE_WEIGHT: float = 1.0


@dataclass(slots=True)
class GeneralLandEvidence:
    """
    One tile observed owned by an enemy player, frozen at first observation.

    player_tile_count is the owner's scoreboard tile count at the moment THIS tile
    was first observed (not the player's first-ever observation), so land seen while
    the player was small weighs more than land seen after they grew. transferred is
    True when the tile changed hands in a witnessed player-to-player transfer (or an
    observed general trade / dead-old-owner bulk flip); such observations carry zero
    positional weight because the recipient did not grow there organically.
    """
    tile: Tile
    first_seen_turn: int
    player_tile_count: int
    transferred: bool

    def weight(self) -> float:
        """Return the frozen inverse-tile-count weight, or 0 for observed transfers."""
        if self.transferred:
            return 0.0
        return 1.0 / max(1, self.player_tile_count)


@dataclass(slots=True)
class GeneralPlacementConflict:
    """
    Diagnostic record of one earlier placement that blocked an informed player's
    preferred (unrestricted fixed-legal best) seed. score_loss carries that player's
    total preferred-minus-chosen loss; the placement-level score_loss accumulates each
    informed player's loss exactly once regardless of how many players blocked it.
    """
    conflicted_player: int
    conflicted_tile: Tile
    conflicted_by_player: int
    conflicted_gen_pos: Tile
    score_loss: float


@dataclass(slots=True)
class _CandidateScore:
    """One scored placement candidate for an informed player."""
    tile: Tile
    score: float


@dataclass(slots=True)
class _InformedPassResult:
    """Result of one greedy informed-placement pass."""
    positions: typing.Dict[int, Tile]
    score_loss: float
    conflicts: typing.List[GeneralPlacementConflict]
    missing_players: typing.List[int]


@dataclass(frozen=True, slots=True)
class _PlayerSignature:
    """Per-player slice of the placement cache signature: candidate mask,
    emergence events, unrecaptured emergences, and the emergence score matrix."""
    valid_positions: typing.Tuple[bool, ...]
    uneliminated_events: typing.Tuple[typing.Tuple[int, int], ...]
    unrecaptured_events: typing.Tuple[int, ...]
    emergence_map: typing.Tuple[float, ...]


@dataclass(frozen=True, slots=True)
class _PlacementSignature:
    """Frozen snapshot of every input the joint placement depends on. Turn number,
    scoreboard tile/army growth, and temporary fog predictions are deliberately
    excluded so pure growth never triggers a rescore."""
    target_player: int
    player_count: int
    dead_players: typing.Tuple[bool, ...]
    captured_players: typing.Tuple[bool, ...]
    general_positions: typing.Tuple[int, ...]
    seen_players: typing.Tuple[bool, ...]
    player_signatures: typing.Tuple[_PlayerSignature, ...]
    land_evidence_revision: int
    ex_general_blockers: typing.Tuple[int, ...]
    neutral_discoveries: typing.Tuple[int, ...]


@dataclass(slots=True)
class _NoInfoPackResult:
    """Result of packing the no-information players around a fixed informed layout."""
    positions: typing.Dict[int, Tile]
    complete: bool
    placed_count: int


class FfaGeneralPlacement:
    """
    Joint per-player predicted-general placement for original FFA maps.

    positions[player.index] is the chosen seed Tile (or None when the player is dead
    or no legal candidate exists). conflicts/score_loss/complete describe the last
    recompute; conflicts always reflects the FIRST greedy pass so diagnostics survive
    even when the constrained second pass is adopted.
    """

    __slots__ = (
        'positions',
        'conflicts',
        'score_loss',
        'complete',
        'ex_general_blockers',
        'fill_capacity_eliminated_hard',
        'soft_eliminated_by_player',
        '_signature',
        '_evidence_bootstrapped',
        '_fill_capacity_by_tile',
    )

    def __init__(self) -> None:
        """Initialize empty placement state; refresh() populates it on first use."""
        self.positions: typing.List[Tile | None] = []
        self.conflicts: typing.List[GeneralPlacementConflict] = []
        self.score_loss: float = 0.0
        self.complete: bool = True
        # Confirmed former-general tiles (dead players' retained map.generals entries
        # and discoveredExGeneralCity discoveries) that constrain every candidate set
        # exactly like living known generals do.
        self.ex_general_blockers: typing.Set[Tile] = set()
        # No-info fill-capacity eliminations, recomputed every recompute (never
        # serialized): candidates whose fillable component holds <2 tiles are
        # impossible spawns for every no-info player; candidates whose component
        # is smaller than the player's scoreboard tileCount are deprioritized
        # per-player but remain placeable when nothing better exists.
        self.fill_capacity_eliminated_hard: typing.Set[Tile] = set()
        self.soft_eliminated_by_player: typing.Dict[int, typing.Set[Tile]] = {}
        self._signature: _PlacementSignature | None = None
        self._evidence_bootstrapped: bool = False
        self._fill_capacity_by_tile: typing.Dict[Tile, int] | None = None

    @staticmethod
    def _is_out_of_play(player: Player) -> bool:
        """
        Return True for players who get no predicted general: dead players and
        players captured by another player (capturedBy set even while dead=False
        for the turns before the death flag propagates).
        Tests: UnitTests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.test_captured_player_gets_no_placement
        """
        return player.dead or player.capturedBy is not None

    @staticmethod
    def is_original_ffa(map: MapBase) -> bool:
        """
        Return True only for genuine free-for-all maps: more than two players, not a
        2v2, and every player on their own team. Still applies once only two players
        remain alive (dead players simply get positions[player] == None).
        """
        return (
            len(map.players) > 2
            and not map.is_2v2
            and len(map.unique_teams) == len(map.players))

    def invalidate(self) -> None:
        """Force the next refresh() to recompute (used by general-trade state swaps)."""
        self._signature = None

    def refresh(self, tracker: ArmyTracker, target_player: int) -> bool:
        """
        Recompute joint placements when any tracked input changed.

        @param tracker: the ArmyTracker owning all evidence/matrices.
        @param target_player: the bot's current target player index (-1 allowed);
            informed ordering places the target first when it has any evidence.
        @return: True when any player's chosen position changed.
        """
        map = tracker.map
        if not self.is_original_ffa(map):
            if self._signature is not None or len(self.positions) > 0:
                self.positions = [None for _ in map.players]
                self.conflicts = []
                self.score_loss = 0.0
                self.complete = True
                self.fill_capacity_eliminated_hard = set()
                self.soft_eliminated_by_player = {}
                self._signature = None
                self._fill_capacity_by_tile = None
            return False

        self._bootstrap_land_evidence(tracker)
        signature = self._build_signature(tracker, target_player)
        if signature == self._signature:
            return False

        oldPositions = list(self.positions)
        # begin_move_event requires an active move timer; placement refresh also runs
        # from contexts with none (unit tests, early init), so only wrap when live.
        if tracker.perf_timer.current_move is not None:
            with tracker.perf_timer.begin_move_event('FFA general placement'):
                self._recompute(tracker, target_player)
        else:
            self._recompute(tracker, target_player)
        # _recompute may add dead players' retained generals to ex_general_blockers;
        # snapshot the signature AFTER that mutation so the stored signature already
        # contains them and the next unchanged refresh does not recompute needlessly.
        self._signature = self._build_signature(tracker, target_player)

        changed = (
            len(oldPositions) != len(self.positions)
            or any(
                (old is None) != (new is None)
                or (old is not None and new is not None and old.tile_index != new.tile_index)
                for old, new in zip(oldPositions, self.positions)))

        if changed:
            # Spatial Voronoi ownership shifts when any seed moves, so every living
            # non-friendly player's fog land must rebuild even if only one seed moved.
            for player in map.players:
                if player.dead:
                    continue
                if map.is_player_on_team_with(map.player_index, player.index):
                    continue
                tracker.should_recalc_fog_land_by_player[player.index] = True

        return changed

    # ------------------------------------------------------------------ evidence

    def _bootstrap_land_evidence(self, tracker: ArmyTracker) -> None:
        """
        One-time top-up of land evidence from tiles that are already discovered and
        enemy-owned on the loaded/resumed map. Only actual observations are imported
        (discovered, non-temp, enemy-owned); fog-inferred ownership is never used, and
        serialized evidence entries are never overwritten because bootstrap only fills
        missing keys. This is also the legacy-resume path: fixtures written before
        GeneralLandEvidence existed simply have no keys to restore.
        """
        if self._evidence_bootstrapped:
            return
        self._evidence_bootstrapped = True
        map = tracker.map
        for tile in map.get_all_tiles():
            playerIndex = tile.player
            if playerIndex < 0 or playerIndex == map.player_index:
                continue
            if map.is_player_on_team_with(playerIndex, map.player_index):
                continue
            if tile.isTempFogPrediction or not tile.discovered:
                continue
            evidence = tracker.ffa_general_land_evidence[playerIndex]
            if tile in evidence:
                continue
            # Tests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.test_bootstrap_marks_witnessed_transfer_zero_weight:
            # a tile whose CURRENT delta still proves a witnessed transfer must not
            # bootstrap with fabricated positive weight - reuse the tracker's proven
            # transfer semantics instead of assuming False.
            evidence[tile] = GeneralLandEvidence(
                tile=tile,
                first_seen_turn=map.turn,
                player_tile_count=map.players[playerIndex].tileCount,
                transferred=tracker._is_witnessed_land_transfer(tile))
            tracker.ffa_land_evidence_revision += 1

    @staticmethod
    def _land_evidence_stats(
            tracker: ArmyTracker,
            player: int
    ) -> typing.Tuple[bool, float, float]:
        """
        Return (hasPositiveEvidence, centroidX, centroidY) for a player. Weights are
        the frozen 1/max(1, tileCount-at-first-observation) values; transferred
        observations weigh zero and cannot move the centroid.
        """
        totalWeight = 0.0
        sumX = 0.0
        sumY = 0.0
        for evidence in tracker.ffa_general_land_evidence[player].values():
            weight = evidence.weight()
            if weight <= 0.0:
                continue
            totalWeight += weight
            sumX += weight * evidence.tile.x
            sumY += weight * evidence.tile.y
        if totalWeight <= 0.0:
            return False, 0.0, 0.0
        return True, sumX / totalWeight, sumY / totalWeight

    # ------------------------------------------------------------------ signature

    def _build_signature(self, tracker: ArmyTracker, target_player: int) -> _PlacementSignature:
        """
        Cheap change detector covering every input the placement depends on: target
        selection, deaths/captures, known general positions, per-player candidate
        masks, emergence events AND the emergence score matrix, land-evidence
        revision, retained ex-general blockers, and neutral discoveries.
        """
        map = tracker.map
        playerCount = len(map.players)
        playerSignatures: typing.List[_PlayerSignature] = []
        for p in range(playerCount):
            validPositions = tracker.valid_general_positions_by_player[p]
            uneliminated = tracker.uneliminated_emergence_events[p]
            unrecaptured = tracker.unrecaptured_emergence_events[p]
            emergenceMap = tracker.emergenceLocationMap[p]
            playerSignatures.append(_PlayerSignature(
                valid_positions=tuple(validPositions.raw),
                uneliminated_events=tuple(sorted(
                    (tile.tile_index, value) for tile, value in uneliminated.items())),
                unrecaptured_events=tuple(sorted(tile.tile_index for tile in unrecaptured)),
                emergence_map=tuple(emergenceMap.raw)))
        return _PlacementSignature(
            target_player=target_player,
            player_count=playerCount,
            dead_players=tuple(p.dead for p in map.players),
            captured_players=tuple(p.capturedBy is not None for p in map.players),
            general_positions=tuple(
                map.generals[i].tile_index if map.generals[i] is not None else -1
                for i in range(playerCount)),
            seen_players=tuple(tracker.seen_player_lookup),
            player_signatures=tuple(playerSignatures),
            land_evidence_revision=tracker.ffa_land_evidence_revision,
            ex_general_blockers=tuple(sorted(tile.tile_index for tile in self.ex_general_blockers)),
            neutral_discoveries=tuple(sorted(
                tile.tile_index for tile in map.get_all_tiles() if tile.discoveredAsNeutral)))

    # ------------------------------------------------------------------ recompute

    def _recompute(self, tracker: ArmyTracker, target_player: int) -> None:
        """Run the full joint placement and store positions/conflicts/loss/complete."""
        map = tracker.map
        playerCount = len(map.players)
        minDistance = tracker.min_spawn_distance

        positions: typing.List[Tile | None] = [None for _ in range(playerCount)]
        anchorTiles: typing.Set[Tile] = set(self.ex_general_blockers)

        # UnitTests/test_FfaGeneralPlacement.py fill-capacity elimination tests:
        # per-recompute state for the no-info spawn-elimination feature. The
        # fillable-component capacity map is labelled lazily by the first no-info
        # pack call (one O(map) pass) and shared across every greedy ordering
        # attempt and the bounded backtracking fallback; tileCount-only changes
        # do not bust the signature, so the sets simply apply at the next
        # recompute.
        self._fill_capacity_by_tile = None
        self.fill_capacity_eliminated_hard = set()
        self.soft_eliminated_by_player = {}

        # Known living generals are authoritative fixed placements (including our
        # own); dead or captured players' retained former-general tiles become
        # exclusion anchors and the player itself gets no placement.
        for p in range(playerCount):
            player = map.players[p]
            general = map.generals[p]
            if self._is_out_of_play(player):
                if general is not None:
                    anchorTiles.add(general)
                    self.ex_general_blockers.add(general)
                continue
            if general is not None and general.isGeneral:
                positions[p] = general
                anchorTiles.add(general)

        # Build per-unknown-player candidate lists and informed classification.
        candidates: typing.Dict[int, typing.List[Tile]] = {}
        candidateScores: typing.Dict[int, typing.Dict[Tile, float]] = {}
        bestFixedLegal: typing.Dict[int, _CandidateScore] = {}
        informedPlayers: typing.Set[int] = set()

        for p in range(playerCount):
            if positions[p] is not None or self._is_out_of_play(map.players[p]):
                continue
            playerCandidates = self._build_candidates(tracker, p, anchorTiles, minDistance)
            candidates[p] = playerCandidates
            hasLandEvidence, centroidX, centroidY = self._land_evidence_stats(tracker, p)
            # Tests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.test_emergence_matrix_signal_alone_marks_player_informed:
            # the emergence LOCATION matrix can retain positive signal after its
            # event sets have been consumed/cleared, so genuine positive matrix
            # values count as information even with zero surviving events.
            emergenceMap = tracker.emergenceLocationMap[p]
            hasEmergence = bool(
                tracker.uneliminated_emergence_events[p]
                or tracker.unrecaptured_emergence_events[p]
                or any(value > 0.0 for value in emergenceMap.raw))
            if not hasLandEvidence and not hasEmergence:
                continue
            informedPlayers.add(p)
            scores = self._score_candidates(
                tracker, p, playerCandidates, hasLandEvidence, centroidX, centroidY, minDistance)
            candidateScores[p] = scores
            if len(scores) > 0:
                bestTile = min(scores.keys(), key=lambda t: (-scores[t], t.tile_index))
                bestFixedLegal[p] = _CandidateScore(tile=bestTile, score=scores[bestTile])

        order = self._informed_order(tracker, target_player, informedPlayers)
        firstPass = self._run_informed_pass(
            map, order, candidates, candidateScores, bestFixedLegal, minDistance, None)
        self.conflicts = firstPass.conflicts

        # Second pass: constrain every movable conflict causer to be at least
        # _CONFLICT_CAUSER_MIN_MOVE Manhattan away from its first-pass seed, then
        # re-run the same greedy. Fixed known generals can never be causers because
        # their positions were never available as conflict blockers.
        causerOverrides: typing.Dict[int, typing.List[Tile]] | None = None
        causers = {conflict.conflicted_by_player for conflict in firstPass.conflicts}
        if len(causers) > 0:
            causerOverrides = {}
            for causer in causers:
                firstPos = firstPass.positions.get(causer)
                if firstPos is None or causer not in candidates:
                    continue
                causerOverrides[causer] = [
                    tile for tile in candidates[causer]
                    if map.manhattan_dist(tile, firstPos) >= _CONFLICT_CAUSER_MIN_MOVE]
            if len(causerOverrides) == 0:
                causerOverrides = None

        candidateResults: typing.List[_InformedPassResult] = [firstPass]
        secondPass: _InformedPassResult | None = None
        if causerOverrides is not None:
            secondPass = self._run_informed_pass(
                map, order, candidates, candidateScores, bestFixedLegal, minDistance, causerOverrides)
            candidateResults.append(secondPass)

        noInfoPlayers = [
            p for p in range(playerCount)
            if positions[p] is None and not self._is_out_of_play(map.players[p]) and p not in informedPlayers]

        best: typing.Tuple[bool, float, int, _InformedPassResult, _NoInfoPackResult] | None = None
        for resultIndex, passResult in enumerate(candidateResults):
            packResult = self._pack_no_info_players(
                map, noInfoPlayers, passResult.positions, candidates, minDistance)
            allInformedPlaced = len(passResult.missing_players) == 0
            # packResult.complete only covers players that had at least one legal
            # candidate; players with zero candidates must also count as placed for
            # the overall result to be complete.
            packComplete = len(packResult.positions) == len(noInfoPlayers)
            complete = allInformedPlaced and packComplete
            # prefer pass 0 on ties via the resultIndex tiebreak
            candidate = (complete, -passResult.score_loss, -resultIndex, passResult, packResult)
            if best is None or candidate > best:
                best = candidate

        assert best is not None
        _complete, _negLoss, _negIndex, chosenPass, chosenPack = best
        chosenComplete = _complete
        chosenScoreLoss = -_negLoss

        merged: typing.List[Tile | None] = list(positions)
        for playerIndex, tile in chosenPass.positions.items():
            merged[playerIndex] = tile
        for playerIndex, tile in chosenPack.positions.items():
            merged[playerIndex] = tile

        self.positions = merged
        self.score_loss = chosenScoreLoss
        self.complete = chosenComplete

        missing = [p for p in range(playerCount) if merged[p] is None and not self._is_out_of_play(map.players[p])]
        logbook.info(
            f'FFA_GENERAL_PLACEMENT turn={map.turn} target={target_player} '
            f'pass={1 if chosenPass is secondPass else 0} complete={chosenComplete} '
            f'scoreLoss={chosenScoreLoss:.2f} conflicts={len(firstPass.conflicts)} '
            f'positions={{ {", ".join(f"p{p}:{merged[p]}" for p in range(playerCount) if merged[p] is not None)} }}')
        if not chosenComplete:
            logbook.warning(
                f'FFA_GENERAL_PLACEMENT could not place all living players; '
                f'missing={[f"p{p}" for p in missing]} scoreLoss={chosenScoreLoss:.2f}')

    def _build_candidates(
            self,
            tracker: ArmyTracker,
            player: int,
            anchorTiles: typing.Set[Tile],
            minDistance: int
    ) -> typing.List[Tile]:
        """
        Hard-valid, terrain/discovered-filtered, anchor-distance-legal candidates for
        one unknown-general player. Iterates the tracker's valid_general_positions
        matrix (tile_index order) so candidate order is deterministic.
        """
        map = tracker.map
        validPositions = tracker.valid_general_positions_by_player[player]
        candidates: typing.List[Tile] = []
        for tile in validPositions:
            if tile.discovered or tile.discoveredAsNeutral or tile.isMountain or tile.isNotPathable or tile.isCity:
                continue
            # Tests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.test_temp_fog_ownership_never_removes_general_candidates:
            # speculative fog ownership (isTempFogPrediction, including stale
            # guesses anchored to a player's PREVIOUS seed) must never shrink the
            # candidate set - only actually observed/known ownership excludes a
            # tile, because fog fills re-mark candidates every turn and would
            # otherwise force seeds to drift from their last best spots. Unobserved
            # tracked ownership (player>=0 on an unseen tile) is likewise only a
            # guess; the hard validity matrix and discovered/terrain flags are the
            # authority.
            if tile.player >= 0 and not tile.isTempFogPrediction and (tile.discovered or tile.visible):
                continue
            tooCloseToAnchor = False
            for anchor in anchorTiles:
                if map.manhattan_dist(tile, anchor) < minDistance:
                    tooCloseToAnchor = True
                    break
            if tooCloseToAnchor:
                continue
            candidates.append(tile)
        return candidates

    def _score_candidates(
            self,
            tracker: ArmyTracker,
            player: int,
            candidates: typing.List[Tile],
            hasLandEvidence: bool,
            centroidX: float,
            centroidY: float,
            minDistance: int
    ) -> typing.Dict[Tile, float]:
        """
        Score = emergenceMatrixResidue + 100*emergenceEventProximity +
        emergenceDistanceBonus(D) - Manhattan distance to the frozen-weight
        land-evidence centroid. The proximity term sums 1/(1+Manhattan distance)
        over the player's surviving emergence EVENTS (uneliminated +
        unrecaptured); D is the larger of the spawn distance and the minimum
        Manhattan distance from our general to the player's emergence sources,
        and the bonus term is omitted entirely when there are no sources.

        Tests/test_FogLandBuilder.py::FogLandBuilderTests.test_should_not_drag_informed_general_prediction_to_enemy_emergence
        and ...test_should_not_swap_ffa_predictions_to_enemy_land: the raw
        emergenceLocationMap can no longer dominate informed scoring (was
        10*matrix). Other systems write diffuse or cross-player pollution into
        it (the flipped-tile spread historically bumped every player's matrix on
        any enemy-land discovery; incAmount deposits smear +8 across the whole
        fog frontier), and 10*matrix dragged informed seeds onto other players'
        evidence (pink was pulled to (22,15) next to green's reveal; green
        landed at (18,10) under pink's land). Real emergence EVENTS are
        ground-truth per-player and can only pull a seed toward that player's
        own observed emergences; the matrix survives only as a weak residue tilt
        so matrix-only signal still counts (its residue can outlive the event
        sets that produced it).
        """
        map = tracker.map
        emergenceMap = tracker.emergenceLocationMap[player]
        sources = (
            set(tracker.uneliminated_emergence_events[player].keys())
            | tracker.unrecaptured_emergence_events[player])
        distanceBonus = None
        if len(sources) > 0:
            ourGeneral = map.generals[map.player_index]
            if ourGeneral is not None:
                minSourceDistance = min(
                    map.manhattan_dist(ourGeneral, source) for source in sources)
                expectedDistance = max(minDistance, minSourceDistance)
            else:
                expectedDistance = minDistance
            distanceBonus = tracker.build_emergence_distance_bonus_matrix(player, expectedDistance)

        scores: typing.Dict[Tile, float] = {}
        for tile in candidates:
            score = emergenceMap[tile] * _EMERGENCE_MATRIX_RESIDUE_WEIGHT
            score += _EMERGENCE_EVENT_PROXIMITY_WEIGHT * sum(
                1.0 / (1 + map.manhattan_dist(tile, source)) for source in sources)
            if distanceBonus is not None:
                score += distanceBonus.raw[tile.tile_index]
            if hasLandEvidence:
                score -= abs(tile.x - centroidX) + abs(tile.y - centroidY)
            scores[tile] = score
        return scores

    def _informed_order(
            self,
            tracker: ArmyTracker,
            target_player: int,
            informedPlayers: typing.Set[int]
    ) -> typing.List[int]:
        """
        Target first when informed, then emergence holders by descending emergence
        count, then land-only informed players, all with player index as final
        tiebreak.
        """
        def emergenceCount(player: int) -> int:
            return len(
                set(tracker.uneliminated_emergence_events[player].keys())
                | tracker.unrecaptured_emergence_events[player])

        def sortKey(player: int) -> typing.Tuple[int, int, int]:
            count = emergenceCount(player)
            if player == target_player:
                return (0, 0, player)
            if count > 0:
                return (1, -count, player)
            return (2, 0, player)

        return sorted(informedPlayers, key=sortKey)

    def _run_informed_pass(
            self,
            map: MapBase,
            order: typing.List[int],
            candidates: typing.Dict[int, typing.List[Tile]],
            candidateScores: typing.Dict[int, typing.Dict[Tile, float]],
            bestFixedLegal: typing.Dict[int, _CandidateScore],
            minDistance: int,
            candidateOverrides: typing.Dict[int, typing.List[Tile]] | None
    ) -> _InformedPassResult:
        """
        Greedy informed placement: each player in order takes its best-scoring
        candidate that is >= minDistance from every already-placed informed seed.
        Anchor legality was already enforced at candidate build time.
        """
        positions: typing.Dict[int, Tile] = {}
        placedTiles: typing.List[Tile] = []
        for player in order:
            playerCandidates = (
                candidateOverrides[player]
                if candidateOverrides is not None and player in candidateOverrides
                else candidates[player])
            scores = candidateScores[player]
            bestTile: Tile | None = None
            bestScore = 0.0
            for tile in playerCandidates:
                legal = True
                for placed in placedTiles:
                    if map.manhattan_dist(tile, placed) < minDistance:
                        legal = False
                        break
                if not legal:
                    continue
                tileScore = scores[tile]
                if bestTile is None or tileScore > bestScore or (
                        tileScore == bestScore and tile.tile_index < bestTile.tile_index):
                    bestTile = tile
                    bestScore = tileScore
            if bestTile is not None:
                positions[player] = bestTile
                placedTiles.append(bestTile)

        # Loss/conflict accounting is a separate pass so each informed player's
        # preferred-minus-chosen loss is accumulated exactly once, with one conflict
        # row per earlier placement that sits inside the spawn distance of the
        # player's unrestricted fixed-legal best.
        conflicts: typing.List[GeneralPlacementConflict] = []
        missingPlayers: typing.List[int] = []
        scoreLoss = 0.0
        for index, player in enumerate(order):
            bestEntry = bestFixedLegal.get(player)
            if bestEntry is None:
                missingPlayers.append(player)
                scoreLoss += _MISSING_PLACEMENT_SCORE_LOSS
                continue
            preferredTile = bestEntry.tile
            preferredScore = bestEntry.score
            chosen = positions.get(player)
            if chosen is None:
                # Tests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.test_missing_informed_player_records_conflicts_for_alternate_pass:
                # an informed player that could not be placed at all still records
                # which earlier placements block its preferred tile; without those
                # conflict rows no causers exist and the alternative pass can never
                # rescue the dead-end.
                missingPlayers.append(player)
                scoreLoss += _MISSING_PLACEMENT_SCORE_LOSS
                for earlierPlayer in order[:index]:
                    earlierPos = positions.get(earlierPlayer)
                    if earlierPos is None:
                        continue
                    if map.manhattan_dist(preferredTile, earlierPos) < minDistance:
                        conflicts.append(GeneralPlacementConflict(
                            conflicted_player=player,
                            conflicted_tile=preferredTile,
                            conflicted_by_player=earlierPlayer,
                            conflicted_gen_pos=earlierPos,
                            score_loss=_MISSING_PLACEMENT_SCORE_LOSS))
                continue
            chosenScore = candidateScores[player][chosen]
            if chosen.tile_index == preferredTile.tile_index:
                continue
            loss = preferredScore - chosenScore
            scoreLoss += loss
            for earlierPlayer in order[:index]:
                earlierPos = positions.get(earlierPlayer)
                if earlierPos is None:
                    continue
                if map.manhattan_dist(preferredTile, earlierPos) < minDistance:
                    conflicts.append(GeneralPlacementConflict(
                        conflicted_player=player,
                        conflicted_tile=preferredTile,
                        conflicted_by_player=earlierPlayer,
                        conflicted_gen_pos=earlierPos,
                        score_loss=loss))

        return _InformedPassResult(
            positions=positions,
            score_loss=scoreLoss,
            conflicts=conflicts,
            missing_players=missingPlayers)

    # ------------------------------------------------------- no-info packing

    @staticmethod
    def _is_no_info_fillable(tile: Tile) -> bool:
        """
        Return True when a tile could hold a NO-INFORMATION player's land for
        spawn-pocket purposes, matching the bannedTiles semantics of
        ArmyTracker.get_fog_connected_based_on_emergences: anything we can see
        (visible) or have ever sighted neutral (discoveredAsNeutral) is proven
        not theirs; mountains and undiscovered obstacles are never land
        (isNotPathable - tile.movable BFS also cannot cross them since revealed
        mountains are removed from movable lists). Undiscovered cities stay
        fillable - an unseen enemy city can be theirs. The one predicate beyond
        bannedTiles is the real conversion rule from
        ArmyTracker._fill_land_from_connected_tiles_for_player
        (determine_tiles_to_fill_in converts only tile.player == -1): a tile
        last observed owned by another player is known land and cannot belong
        to a no-info player, while isTempFogPrediction ownership is only a
        guess and stays fillable just like in _build_candidates.
        No-info players have empty emergence/evidence sets, so this one shared
        mask is correct for every no-info player; informed players never use it.
        """
        return (
            not tile.visible
            and not tile.discoveredAsNeutral
            and not tile.isNotPathable
            and (tile.player == -1 or tile.isTempFogPrediction))

    def _label_fillable_components(self, map: MapBase) -> typing.Dict[Tile, int]:
        """
        One O(map) pass labelling every 4-connected component of fillable tiles
        over tile.movable adjacency. Returns tile -> size of the fillable
        component containing it; non-fillable tiles are absent from the result.
        A candidate's capacity is its component size (the candidate itself
        counts), i.e. how much contiguous unseen land a general spawning there
        could hold without bleeding into space we can see.
        """
        capacityByTile: typing.Dict[Tile, int] = {}
        visited: typing.Set[Tile] = set()
        for seed in map.get_all_tiles():
            if seed in visited or not self._is_no_info_fillable(seed):
                continue
            component: typing.List[Tile] = []
            stack = [seed]
            visited.add(seed)
            while len(stack) > 0:
                tile = stack.pop()
                component.append(tile)
                for neighbor in tile.movable:
                    if neighbor in visited or not self._is_no_info_fillable(neighbor):
                        continue
                    visited.add(neighbor)
                    stack.append(neighbor)
            size = len(component)
            for tile in component:
                capacityByTile[tile] = size
        return capacityByTile

    def _compute_no_info_fill_eliminations(
            self,
            map: MapBase,
            noInfoPlayers: typing.List[int],
            candidates: typing.Dict[int, typing.List[Tile]]
    ) -> None:
        """
        Compute the shared capacity map, the hard set (capacity < 2, impossible
        spawn removed from every no-info pool), and each no-info player's soft
        set (capacity < scoreboard tileCount, still placeable but only when no
        non-soft candidate exists). Runs once per _recompute; informed players
        are never given elimination sets, so gaining information automatically
        disregards every elimination.
        """
        capacity = self._label_fillable_components(map)
        self._fill_capacity_by_tile = capacity
        for player in noInfoPlayers:
            for tile in candidates[player]:
                if capacity.get(tile, 0) < _NO_INFO_MIN_FILL_CAPACITY:
                    self.fill_capacity_eliminated_hard.add(tile)
        for player in noInfoPlayers:
            tileCount = map.players[player].tileCount
            self.soft_eliminated_by_player[player] = {
                tile for tile in candidates[player]
                if tile not in self.fill_capacity_eliminated_hard
                and capacity.get(tile, 0) < tileCount}
        softCounts = {
            p: len(softSet)
            for p, softSet in self.soft_eliminated_by_player.items()
            if len(softSet) > 0}
        if len(self.fill_capacity_eliminated_hard) > 0 or len(softCounts) > 0:
            logbook.info(
                f'FFA_FILL_CAPACITY turn={map.turn} '
                f'hard={len(self.fill_capacity_eliminated_hard)} '
                f'hardTiles={sorted((t.x, t.y) for t in self.fill_capacity_eliminated_hard)} '
                f'softByPlayer={softCounts}')

    def _pack_no_info_players(
            self,
            map: MapBase,
            noInfoPlayers: typing.List[int],
            informedPositions: typing.Dict[int, Tile],
            candidates: typing.Dict[int, typing.List[Tile]],
            minDistance: int
    ) -> _NoInfoPackResult:
        """
        Pack the no-information players into the space left by the informed
        placements. Every still-legal prior no-info position is reserved before
        any random pick (prior seeds were pairwise legal in the old result, so
        reserving all of them first stops a displaced player stealing a retained
        player's tile); the remainder is filled by uniform random.choice over
        each player's currently-legal pool. A few bounded random attempts run
        before the bounded backtracking fallback; no-info players never
        displace informed ones and contribute nothing to score_loss.
        """
        # UnitTests/test_FfaGeneralPlacement.py fill-capacity elimination tests:
        # label the shared fillable-component capacity map once per recompute
        # (lazy so placements with zero no-info candidates never pay the O(map)
        # pass), then drop every capacity<2 candidate from every no-info pool.
        if (self._fill_capacity_by_tile is None
                and any(len(candidates[player]) > 0 for player in noInfoPlayers)):
            self._compute_no_info_fill_eliminations(map, noInfoPlayers, candidates)

        basePositions = dict(informedPositions)
        available: typing.Dict[int, typing.List[Tile]] = {}
        for player in noInfoPlayers:
            available[player] = [
                tile for tile in candidates[player]
                if tile not in self.fill_capacity_eliminated_hard
                and self._is_legal_vs_positions(map, tile, basePositions.values(), minDistance)]

        priorPositions: typing.Dict[int, Tile] = {}
        for player in noInfoPlayers:
            # self.positions is empty until the first recompute completes.
            prior = self.positions[player] if player < len(self.positions) else None
            if prior is not None:
                priorPositions[player] = prior

        placeable = [p for p in noInfoPlayers if len(available[p]) > 0]
        unplaceableCount = len(noInfoPlayers) - len(placeable)

        orderings: typing.List[typing.List[int]] = [
            sorted(placeable, key=lambda p: len(available[p]))]
        orderingRng = random.Random()
        for _ in range(2):
            ordering = list(placeable)
            orderingRng.shuffle(ordering)
            orderings.append(ordering)

        # UnitTests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.
        # test_no_info_greedy_uses_random_choice_over_currently_legal_pool and
        # test_no_info_random_choice_recovers_greedy_bottleneck: the user
        # rejected row-major first-legal packing (every no-info general landed
        # on the top edge), so EVERY greedy attempt - including the first -
        # draws uniform random.choice from the CURRENT legal pool with an
        # unseeded local Random. refresh() caches the result until relevant
        # inputs change, so placements are stable-but-random with no per-turn
        # jitter; retries only reshuffle player order, and the bounded
        # backtracking fallback tries each player's prior tile first.
        bestPartial: _NoInfoPackResult | None = None
        for ordering in orderings:
            result = self._greedy_pack_no_info(
                map, ordering, available, basePositions, minDistance,
                priorPositions, random.Random())
            if result.complete and unplaceableCount == 0:
                return result
            if bestPartial is None or result.placed_count > bestPartial.placed_count:
                bestPartial = result

        backtrackRng = random.Random()
        backtrackAvailable: typing.Dict[int, typing.List[Tile]] = {}
        for player in placeable:
            tiles = list(available[player])
            prior = priorPositions.get(player)
            softSet = self.soft_eliminated_by_player.get(player)
            if prior is not None and prior in tiles:
                tiles.remove(prior)
                backtrackRng.shuffle(tiles)
                if softSet:
                    # UnitTests/test_FfaGeneralPlacement.py fill-capacity
                    # elimination tests: the backtracker tries non-soft
                    # candidates before soft ones (soft tiles are last-resort
                    # spawns); a surviving prior still leads whichever tier it
                    # belongs to.
                    nonSoft = [tile for tile in tiles if tile not in softSet]
                    softTiles = [tile for tile in tiles if tile in softSet]
                    if prior in softSet:
                        backtrackAvailable[player] = nonSoft + [prior] + softTiles
                    else:
                        backtrackAvailable[player] = [prior] + nonSoft + softTiles
                else:
                    backtrackAvailable[player] = [prior] + tiles
            else:
                backtrackRng.shuffle(tiles)
                if softSet:
                    backtrackAvailable[player] = (
                        [tile for tile in tiles if tile not in softSet]
                        + [tile for tile in tiles if tile in softSet])
                else:
                    backtrackAvailable[player] = tiles
        backtrack = self._backtrack_pack_no_info(
            map,
            sorted(placeable, key=lambda p: len(available[p])),
            backtrackAvailable,
            basePositions,
            minDistance,
            _NO_INFO_BACKTRACK_NODE_BUDGET)
        if backtrack is not None and unplaceableCount == 0:
            return backtrack
        if bestPartial is None:
            bestPartial = backtrack if backtrack is not None else _NoInfoPackResult({}, False, 0)
        return bestPartial

    def _greedy_pack_no_info(
            self,
            map: MapBase,
            ordering: typing.List[int],
            available: typing.Dict[int, typing.List[Tile]],
            basePositions: typing.Dict[int, Tile],
            minDistance: int,
            priorPositions: typing.Dict[int, Tile],
            rng: random.Random
    ) -> _NoInfoPackResult:
        """
        Reserve every still-legal prior no-info position first, then place each
        remaining player by uniform rng.choice over its currently-legal pool.
        Soft-eliminated (fill-capacity) tiles participate only as a last
        resort: a soft prior is reserved only when the player has no non-soft
        candidate left, and Phase 2 offers rng.choice the non-soft legal pool
        before falling back to soft tiles. After every placement, all tiles
        within minDistance of it are dropped from every unplaced player's
        local pool copy so later choices can never violate spawn spacing.
        Input pools and hard masks are never mutated.
        """
        positions = dict(basePositions)
        placed: typing.Dict[int, Tile] = {}
        pools: typing.Dict[int, typing.List[Tile]] = {
            player: list(available[player]) for player in ordering}

        # Phase 1: reserve all surviving prior positions before any random pick.
        # A prior is kept only when it is still inside the base-filtered pool
        # (hard-valid candidate AND legal vs the fixed/informed seeds) and
        # legal vs every earlier reservation; priors were pairwise legal in the
        # previous result so reserving all of them first is always consistent.
        for player in ordering:
            prior = priorPositions.get(player)
            if prior is None or prior not in pools[player]:
                continue
            if not self._is_legal_vs_positions(map, prior, positions.values(), minDistance):
                continue
            # UnitTests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.
            # test_fill_capacity_soft_prior_replaced_by_non_soft_alternative and
            # test_fill_capacity_soft_prior_sticks_when_all_alternatives_soft:
            # a soft-eliminated prior is only sticky when the player has no
            # non-soft candidate left; with a non-soft alternative the prior is
            # re-placed randomly so impossible/suspicious spawns stop lingering.
            softSet = self.soft_eliminated_by_player.get(player)
            if softSet and prior in softSet:
                if any(tile not in softSet for tile in pools[player]):
                    continue
            positions[player] = prior
            placed[player] = prior
            pools[player] = []
            for other in ordering:
                if other == player or other in placed:
                    continue
                pools[other] = [
                    tile for tile in pools[other]
                    if map.manhattan_dist(tile, prior) >= minDistance]

        # Phase 2: uniform random choice over each remaining player's legal pool.
        for player in ordering:
            if player in placed:
                continue
            legal = [
                tile for tile in pools[player]
                if self._is_legal_vs_positions(map, tile, positions.values(), minDistance)]
            if len(legal) == 0:
                continue
            # UnitTests/test_FfaGeneralPlacement.py::FfaGeneralPlacementTests.
            # test_fill_capacity_soft_candidates_only_offered_when_no_better:
            # soft-eliminated tiles are only offered to rng.choice once every
            # currently-legal non-soft candidate is gone.
            softSet = self.soft_eliminated_by_player.get(player)
            if softSet:
                nonSoft = [tile for tile in legal if tile not in softSet]
                if len(nonSoft) > 0:
                    legal = nonSoft
            chosen = rng.choice(legal)
            positions[player] = chosen
            placed[player] = chosen
            for other in ordering:
                if other == player or other in placed:
                    continue
                pools[other] = [
                    tile for tile in pools[other]
                    if map.manhattan_dist(tile, chosen) >= minDistance]

        return _NoInfoPackResult(
            positions=placed,
            complete=len(placed) == len(ordering),
            placed_count=len(placed))

    def _backtrack_pack_no_info(
            self,
            map: MapBase,
            ordering: typing.List[int],
            available: typing.Dict[int, typing.List[Tile]],
            basePositions: typing.Dict[int, Tile],
            minDistance: int,
            nodeBudget: int
    ) -> _NoInfoPackResult | None:
        """
        Depth-first packing over the most-constrained-first ordering with a hard node
        budget. Returns a complete result or None when the budget is exhausted or no
        legal completion exists.
        """
        positions = dict(basePositions)
        placed: typing.Dict[int, Tile] = {}
        nodes = [0]

        def search(index: int) -> bool:
            if index >= len(ordering):
                return True
            if nodes[0] >= nodeBudget:
                return False
            player = ordering[index]
            for tile in available[player]:
                if nodes[0] >= nodeBudget:
                    return False
                nodes[0] += 1
                if not self._is_legal_vs_positions(map, tile, positions.values(), minDistance):
                    continue
                positions[player] = tile
                placed[player] = tile
                if search(index + 1):
                    return True
                del positions[player]
                del placed[player]
            return False

        if search(0):
            return _NoInfoPackResult(positions=placed, complete=True, placed_count=len(placed))
        return None

    @staticmethod
    def _is_legal_vs_positions(
            map: MapBase,
            tile: Tile,
            positions: typing.Iterable[Tile],
            minDistance: int
    ) -> bool:
        """Return True when tile is at least minDistance Manhattan from every position."""
        for placed in positions:
            if map.manhattan_dist(tile, placed) < minDistance:
                return False
        return True
