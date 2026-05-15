from TestBase import TestBase


class TestMapLoadingTests(TestBase):
    def test_fill_out_tiles_does_not_change_visible_enemy_armies(self):
        testData = """
|    |    |    |    |
aG1  b10  b5D


               bG1D
|    |    |    |    |
player_index=0
aTiles=1
aScore=1
bTiles=3
bScore=20
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, fill_out_tiles=True)

        self.assertEqual(10, map.GetTile(1, 0).army)
        self.assertEqual(9, map.GetTile(2, 0).army)
        self.assertEqual(20, map.players[enemyGeneral.player].score)
