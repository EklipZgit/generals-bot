from MapMatrix import MapMatrixSet
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from base.client.map import MapBase
from bot_ek0x45 import EklipZBot


class MapMatrixUnitTests(TestBase):
    def __init__(self, methodName: str = ...):
        super().__init__(methodName)

    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        # bot.info_render_tile_deltas = True
        # bot.info_render_army_emergence_values = True
        # bot.info_render_general_undiscovered_prediction_values = True

        return bot

    def test_map_matrix_set_iterator(self):
        mapFile = 'GameContinuationEntries/should_recognize_army_collision_from_fog___BlpaDuBT2---b--136.txtmap'

        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 136)

        matrix = MapMatrixSet(map)
        tileIn1 = map.GetTile(1, 3)
        tileIn2 = map.GetTile(6, 9)

        matrix.add(tileIn1)
        matrix.add(tileIn2)

        self.assertIn(tileIn1, matrix)
        self.assertIn(tileIn2, matrix)

        tilesIn = [t for t in matrix]
        self.assertEqual(2, len(tilesIn))
        for t in tilesIn:
            self.assertTrue(t == tileIn1 or t == tileIn2)