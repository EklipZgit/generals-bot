import time
from dataclasses import dataclass

import logbook

import ArmyTracker as ArmyTrackerModule
from ArmyTracker import ArmyTracker
from BotModules.BotRendering import BotRendering
from BotModules.BotSerialization import BotSerialization
from MapMatrix import MapMatrix
from Sim.GameSimulator import GameSimulatorHost, generate_player_map
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
import base.client.map as MapModule
from base.client.map import MapBase


@dataclass(slots=True)
class SpawnFairnessReferenceCase:
    name: str
    rows: tuple[str, ...]
    our_score: float
    candidates: tuple[
        tuple[
            tuple[int, int],
            tuple[int, ...],
            float,
            float,
            bool,
            bool],
        ...]


@dataclass(slots=True)
class MapMatrixSerializationAdapter:
    """Expose the map field used by the shared matrix text converters."""
    _map: MapBase


SERVER_REFERENCE_CASES: tuple[SpawnFairnessReferenceCase, ...] = (
    SpawnFairnessReferenceCase(
        name='mountain-pocket',
        rows=(
            'A..##..',
            '.#.##..',
            '.......',
            '...#...',
            '..#....',
            '..#...B',
            '.......'),
        our_score=65.33732307978472,
        candidates=(
            (
                (6, 0),
                (1, 2, 2, 2, 3, 4, 4, 6, 5, 5, 4, 2, 1, 0, 0),
                63.35548593013007,
                0.9696676102381087,
                True,
                True),
            (
                (5, 5),
                (1, 4, 6, 5, 4, 4, 4, 5, 4, 3, 1, 0, 0, 0, 0),
                103.70143043441057,
                0.6300522838121263,
                False,
                False))),
    SpawnFairnessReferenceCase(
        name='split-valley',
        rows=(
            'A..#...',
            '.#..#..',
            '...##..',
            '...#...',
            '..#..#.',
            '...#..B',
            '.......'),
        our_score=60.00123713385683,
        candidates=(
            (
                (6, 0),
                (1, 2, 3, 2, 2, 2, 3, 3, 1, 1, 1, 2, 2, 2, 2),
                59.22521412364687,
                0.987066549836652,
                True,
                True),
            (
                (0, 6),
                (1, 2, 3, 4, 3, 5, 5, 5, 4, 2, 2, 2, 2, 0, 0),
                73.6763169497294,
                0.8143897471801786,
                False,
                False))),
    SpawnFairnessReferenceCase(
        name='narrow-corridor',
        rows=(
            'A#.....',
            '.#..##.',
            '.#.....',
            '...###.',
            '......#',
            '##...#B',
            '.......'),
        our_score=40.03187674579351,
        candidates=(
            (
                (6, 0),
                (1, 2, 2, 3, 3, 2, 1, 1, 2, 4, 5, 5, 3, 1, 1),
                60.37390098303028,
                0.663065929051786,
                False,
                False),
            (
                (0, 6),
                (1, 1, 1, 2, 3, 5, 5, 5, 4, 3, 3, 3, 1, 0, 0),
                45.87146741248265,
                0.8726966675345542,
                False,
                True))))


class SpawnFairnessTests(TestBase):
    def __init__(self, methodName: str = ...) -> None:
        """Initialize deterministic tile indices for spawn-fairness fixtures."""
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    @staticmethod
    def _build_map_text(rows: tuple[str, ...]) -> str:
        """Build a txtmap from plain land, mountain, and general markers."""
        width = len(rows[0])
        border = '|  ' * width
        tileTextByCell = {
            '.': '   ',
            '#': 'M  ',
            'A': 'aG1',
            'B': 'bG1',
            'C': 'cG1',
        }
        mapRows = [
            ''.join(tileTextByCell[cell] for cell in row)
            for row in rows
        ]
        dataLines = [
            'aTiles=1',
            'bTiles=1',
        ]
        if any('C' in row for row in rows):
            dataLines.append('cTiles=1')
        return '\n'.join((border, *mapRows, border, *dataLines))

    def _load_map(
            self,
            rows: tuple[str, ...],
            customMap: bool = False) -> MapBase:
        """Load a hand-built map while retaining its tile terrain."""
        rawMap = self._build_map_text(rows)
        gameMap, _ = self.load_map_and_general_from_string(
            rawMap,
            turn=1,
            player_index=0,
            respect_undiscovered=True)
        gameMap.is_custom_map = customMap
        return gameMap

    def _load_tracker(self, rows: tuple[str, ...]) -> tuple[MapBase, ArmyTracker]:
        """Load a 1v1 map and construct its tracker."""
        gameMap = self._load_map(rows)
        gameMap.resume_data = {}
        gameMap.resume_data_is_txtmap = False
        return gameMap, ArmyTracker(gameMap)

    @staticmethod
    def _build_large_rows(cols: int, rows: int) -> tuple[str, ...]:
        """Create a reproducible land map with a realistic mountain density."""
        outputRows: list[str] = []
        for y in range(rows):
            outputRow = []
            for x in range(cols):
                if (x, y) == (0, 0):
                    outputRow.append('A')
                elif (x, y) == (cols - 1, rows - 1):
                    outputRow.append('B')
                elif 0 < x < cols - 1 and 0 < y < rows - 1 and (x * 17 + y * 11) % 5 < 1:
                    outputRow.append('#')
                else:
                    outputRow.append('.')
            outputRows.append(''.join(outputRow))
        return tuple(outputRows)

    def test_server_reference_scores_and_acceptance(self) -> None:
        """Match copied server BFS scores, ratios, and acceptance decisions."""
        for referenceCase in SERVER_REFERENCE_CASES:
            gameMap, tracker = self._load_tracker(referenceCase.rows)
            ourGeneral = gameMap.generals[0]
            ourScore = tracker.score_spawn_fairness_tile(ourGeneral)
            self.assertAlmostEqual(
                referenceCase.our_score,
                ourScore,
                places=11,
                msg=referenceCase.name)

            for (
                    candidateCoords,
                    expectedCounts,
                    expectedScore,
                    expectedRatio,
                    acceptedAtDefault,
                    acceptedAt20) in referenceCase.candidates:
                candidate = gameMap.At(*candidateCoords)
                self.assertEqual(
                    list(expectedCounts),
                    tracker.count_spawn_fairness_distances(candidate),
                    referenceCase.name)
                candidateScore = tracker.score_spawn_fairness_tile(candidate)
                self.assertAlmostEqual(
                    expectedScore,
                    candidateScore,
                    places=11,
                    msg=referenceCase.name)
                ratio = ArmyTrackerModule.spawn_fairness_ratio(
                    candidateScore,
                    ourScore)
                self.assertAlmostEqual(
                    expectedRatio,
                    ratio,
                    places=12,
                    msg=referenceCase.name)
                self.assertEqual(
                    acceptedAtDefault,
                    ArmyTrackerModule.spawn_fairness_pair_is_accepted(
                        candidateScore,
                        ourScore,
                        0.5,
                        0),
                    referenceCase.name)
                self.assertEqual(
                    acceptedAt20,
                    ArmyTrackerModule.spawn_fairness_pair_is_accepted(
                        candidateScore,
                        ourScore,
                        0.5,
                        20),
                    referenceCase.name)

    def test_threshold_option_semantics_and_relaxation(self) -> None:
        """Check the default threshold and JS-style zero option fallback."""
        self.assertEqual(0.5, MapModule.normalize_spawn_fairness_option(None))
        self.assertEqual(0.5, MapModule.normalize_spawn_fairness_option(0.0))
        self.assertEqual(0.8, MapModule.normalize_spawn_fairness_option(0.8))
        self.assertAlmostEqual(
            0.9175,
            ArmyTrackerModule.spawn_fairness_threshold(0.5, 0))
        self.assertAlmostEqual(
            0.8504,
            ArmyTrackerModule.spawn_fairness_threshold(0.5, 20))
        self.assertAlmostEqual(
            0.9784,
            ArmyTrackerModule.spawn_fairness_threshold(0.8, 0))
        self.assertAlmostEqual(
            0.66359375,
            ArmyTrackerModule.spawn_fairness_threshold(0.25, 0))

    def test_prediction_contribution_clamps_negative_weights(self) -> None:
        """Apply the configured scale only to positive fairness weights."""
        self.assertEqual(
            0.0,
            ArmyTrackerModule.spawn_fairness_prediction_value(-0.25))
        self.assertEqual(
            10.0,
            ArmyTrackerModule.spawn_fairness_prediction_value(0.5))

    def test_weight_band_and_negative_weights_eliminate_candidates(self) -> None:
        """Verify the unbounded linear weight and candidate elimination."""
        thresholdBase = ArmyTrackerModule.spawn_fairness_threshold(0.5, 0)
        thresholdMin = ArmyTrackerModule.spawn_fairness_threshold(0.5, 20)
        self.assertEqual(
            1.0,
            ArmyTrackerModule.spawn_fairness_weight(
                thresholdBase,
                thresholdBase,
                thresholdMin))
        self.assertEqual(
            1.0,
            ArmyTrackerModule.spawn_fairness_weight(
                1.0,
                thresholdBase,
                thresholdMin))
        self.assertAlmostEqual(
            0.5,
            ArmyTrackerModule.spawn_fairness_weight(
                (thresholdBase + thresholdMin) / 2,
                thresholdBase,
                thresholdMin))
        self.assertEqual(
            0.0,
            ArmyTrackerModule.spawn_fairness_weight(
                thresholdMin,
                thresholdBase,
                thresholdMin))
        negativeWeight = ArmyTrackerModule.spawn_fairness_weight(
            thresholdMin - 0.1,
            thresholdBase,
            thresholdMin)
        self.assertLess(negativeWeight, 0)
        eliminationMargin = ArmyTrackerModule.SPAWN_FAIRNESS_ELIMINATION_MARGIN
        self.assertEqual(0.1, eliminationMargin)

        gameMap, tracker = self._load_tracker(SERVER_REFERENCE_CASES[0].rows)
        rejectedTile = gameMap.At(5, 5)
        marginTile = gameMap.At(6, 0)
        validPositions = tracker.valid_general_positions_by_player[1]
        weights = tracker.spawn_fairness_weights_by_player[1]
        validPositions.raw[rejectedTile.tile_index] = True
        validPositions.raw[marginTile.tile_index] = True
        weights.raw[rejectedTile.tile_index] = negativeWeight
        weights.raw[marginTile.tile_index] = -0.05

        tracker.eliminate_negative_spawn_fairness_positions()

        self.assertFalse(validPositions.raw[rejectedTile.tile_index])
        self.assertTrue(validPositions.raw[marginTile.tile_index])

    def test_hunting_contribution_uses_two_emergence_scale(self) -> None:
        """Scale positive fairness weights like two unit emergence increments."""
        self.assertEqual(
            1.0,
            ArmyTrackerModule.spawn_fairness_hunting_value(0.5))
        self.assertEqual(
            0.0,
            ArmyTrackerModule.spawn_fairness_hunting_value(-0.5))

    def test_fairness_is_inactive_for_ffa_and_custom_maps(self) -> None:
        """Leave every weight and valid position untouched outside 1v1."""
        threePlayerRows = (
            'A......',
            '.......',
            '.......',
            '.......',
            '.......',
            '.......',
            '......C')
        ffaMap = self._load_map(threePlayerRows)
        ffaMap.resume_data = {}
        ffaTracker = ArmyTracker(ffaMap)
        self.assertFalse(ffaTracker.spawn_fairness_active)
        ffaCandidate = ffaMap.At(1, 0)
        ffaTracker.valid_general_positions_by_player[1].raw[
            ffaCandidate.tile_index] = True
        ffaTracker.eliminate_negative_spawn_fairness_positions()
        self.assertTrue(
            ffaTracker.valid_general_positions_by_player[1].raw[
                ffaCandidate.tile_index])
        self.assertTrue(all(
            weight == 0.0
            for matrix in ffaTracker.spawn_fairness_weights_by_player
            for weight in matrix.raw))

        customMap = self._load_map(SERVER_REFERENCE_CASES[0].rows, customMap=True)
        customMap.resume_data = {}
        customTracker = ArmyTracker(customMap)
        self.assertFalse(customTracker.spawn_fairness_active)
        self.assertTrue(all(
            weight == 0.0
            for matrix in customTracker.spawn_fairness_weights_by_player
            for weight in matrix.raw))

    def test_general_trade_swaps_spawn_fairness_matrices(self) -> None:
        """Keep fairness matrices attached to their traded player state."""
        gameMap, tracker = self._load_tracker(SERVER_REFERENCE_CASES[0].rows)
        firstWeights = tracker.spawn_fairness_weights_by_player[0]
        secondWeights = tracker.spawn_fairness_weights_by_player[1]
        firstWeights.raw[0] = 0.25
        secondWeights.raw[0] = -0.5

        tracker._swap_traded_player_state(0, 1)

        self.assertIs(
            secondWeights,
            tracker.spawn_fairness_weights_by_player[0])
        self.assertIs(
            firstWeights,
            tracker.spawn_fairness_weights_by_player[1])

    def test_serialization_round_trip_and_missing_matrix_rebuild(self) -> None:
        """Preserve negative weights and rebuild marked resumes missing the field."""
        gameMap, tracker = self._load_tracker(SERVER_REFERENCE_CASES[0].rows)
        serializationAdapter = MapMatrixSerializationAdapter(gameMap)
        target = gameMap.At(5, 5)
        savedWeights = MapMatrix(gameMap, 0.0)
        savedWeights.raw[target.tile_index] = -0.37
        serialized = BotSerialization.convert_float_map_matrix_to_string(
            serializationAdapter,
            savedWeights)
        loadedWeights = BotSerialization.convert_string_to_float_map_matrix(
            serializationAdapter,
            serialized)
        self.assertAlmostEqual(
            -0.37,
            loadedWeights.raw[target.tile_index])

        simHost = GameSimulatorHost(
            gameMap,
            player_with_viewer=gameMap.player_index,
            playerMapVision=gameMap,
            botInitOnly=True)
        bot = self.get_debug_render_bot(simHost, gameMap.player_index)
        bot.armyTracker.spawn_fairness_weights_by_player[1].raw[
            target.tile_index] = -0.37
        botData = BotRendering.dump_turn_data_to_string(bot)
        botResumeData = TextMapLoader.load_data_from_string(botData)
        self.assertIn('bSpawnFairness', botResumeData)
        dumpedWeights = BotSerialization.convert_string_to_float_map_matrix(
            bot,
            botResumeData['bSpawnFairness'])
        self.assertAlmostEqual(
            -0.37,
            dumpedWeights.raw[target.tile_index])

        BotSerialization.load_spawn_fairness_weights(
            tracker,
            1,
            loadedWeights,
            {'bSpawnFairness': serialized})
        self.assertIs(
            loadedWeights,
            tracker.spawn_fairness_weights_by_player[1])

        expectedAnalysis = tracker.build_spawn_fairness_analysis()
        tracker.spawn_fairness_initialized = False
        tracker.spawn_fairness_weights_by_player[1].raw[target.tile_index] = 123.0
        validPositions = tracker.valid_general_positions_by_player[1]
        for tile in gameMap.get_all_tiles():
            validPositions.raw[tile.tile_index] = True

        BotSerialization.load_spawn_fairness_weights(
            tracker,
            1,
            None,
            {'island_ids': '', 'bValidGeneralPos': ''})

        actualWeights = tracker.spawn_fairness_weights_by_player[1]
        self.assertEqual(
            expectedAnalysis.weights.raw[target.tile_index],
            actualWeights.raw[target.tile_index])
        self.assertTrue(tracker.spawn_fairness_initialized)

    def test_island_ids_resume_recomputes_and_reapplies_eliminations(self) -> None:
        """Use the current fairness model for resumes marked with island IDs."""
        rows = self._build_large_rows(20, 21)
        gameMap = self._load_map(rows)
        resumeData = {
            'island_ids': '',
            'bValidGeneralPos': '',
        }
        gameMap.resume_data = resumeData
        tracker = ArmyTracker(gameMap)
        validPositions = tracker.valid_general_positions_by_player[1]
        for tile in gameMap.get_all_tiles():
            validPositions.raw[tile.tile_index] = True
        tracker.spawn_fairness_weights_by_player[1].raw[0] = 123.0

        BotSerialization.load_spawn_fairness_weights(
            tracker,
            1,
            None,
            resumeData)

        self.assertTrue(tracker.spawn_fairness_active)
        self.assertTrue(tracker.spawn_fairness_initialized)
        weights = tracker.spawn_fairness_weights_by_player[1]
        rejectedTileIndexes = [
            tileIndex
            for tileIndex, weight in enumerate(weights.raw)
            if weight < -ArmyTrackerModule.SPAWN_FAIRNESS_ELIMINATION_MARGIN
        ]
        self.assertGreater(len(rejectedTileIndexes), 0)
        self.assertTrue(all(
            not validPositions.raw[tileIndex]
            for tileIndex in rejectedTileIndexes))

    def test_legacy_resume_without_island_ids_disables_fairness(self) -> None:
        """Do not apply the newer spawn rule to maps predating island IDs."""
        gameMap = self._load_map(SERVER_REFERENCE_CASES[0].rows)
        resumeData: dict[str, str] = {}
        gameMap.resume_data = resumeData
        tracker = ArmyTracker(gameMap)
        target = gameMap.At(5, 5)
        validPositions = tracker.valid_general_positions_by_player[1]
        validPositions.raw[target.tile_index] = True
        tracker.spawn_fairness_weights_by_player[1].raw[target.tile_index] = -0.5

        BotSerialization.load_spawn_fairness_weights(
            tracker,
            1,
            None,
            resumeData)

        self.assertFalse(tracker.spawn_fairness_active)
        self.assertTrue(validPositions.raw[target.tile_index])
        self.assertTrue(all(
            weight == 0.0
            for matrix in tracker.spawn_fairness_weights_by_player
            for weight in matrix.raw))
        self.assertEqual(
            0.0,
            ArmyTrackerModule.spawn_fairness_prediction_value(
                tracker.spawn_fairness_weights_by_player[1].raw[
                    target.tile_index]))

    def test_simulator_player_map_retains_resume_markers(self) -> None:
        """Preserve old txtmap markers when GameSimulator creates a player map."""
        sourceMap = self._load_map(SERVER_REFERENCE_CASES[0].rows)
        self.assertNotIn('island_ids', sourceMap.resume_data)
        self.assertTrue(sourceMap.resume_data_is_txtmap)

        playerMap = generate_player_map(sourceMap.player_index, sourceMap)

        self.assertEqual(sourceMap.resume_data, playerMap.resume_data)
        self.assertTrue(playerMap.resume_data_is_txtmap)

    def test_spawn_fairness_option_txtmap_round_trip(self) -> None:
        """Persist and reload the non-default spawn-fairness option."""
        gameMap = self._load_map(SERVER_REFERENCE_CASES[0].rows)
        gameMap.spawn_fairness_option = 0.73
        serialized = TextMapLoader.dump_map_to_string(gameMap)
        data = TextMapLoader.load_data_from_string(serialized)
        self.assertEqual('0.73', data['spawn_fairness'])

        loadedMap, _ = self.load_map_and_general_from_string(
            serialized,
            turn=1,
            player_index=0,
            respect_undiscovered=True)
        self.assertEqual(0.73, loadedMap.spawn_fairness_option)

    def test_turn_one_computation_stays_below_150ms(self) -> None:
        """Measure the full analysis cost on representative generated maps."""
        for cols, rows in ((20, 21), (25, 25)):
            gameMap = self._load_map(self._build_large_rows(cols, rows))
            gameMap.resume_data = {'bValidGeneralPos': ''}
            tracker = ArmyTracker(gameMap)
            started = time.perf_counter()
            analysis = tracker.initialize_spawn_fairness_weights()
            elapsedSeconds = time.perf_counter() - started
            logbook.info(
                f'SPAWN_FAIRNESS_BENCHMARK cols={cols} rows={rows} '
                f'elapsedMs={elapsedSeconds * 1000:.3f}')
            self.assertTrue(analysis.active)
            self.assertLess(elapsedSeconds, 0.15)
