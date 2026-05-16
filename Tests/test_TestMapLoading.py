from TestBase import TestBase


class TestMapLoadingTests(TestBase):
    def test_fill_out_tiles_does_not_change_visible_enemy_armies(self):
        testData = """
|    |    |    |    |    |
aG1  b10  b5D


               b1D  bG1D
|    |    |    |    |    |
player_index=0
aTiles=1
aScore=1
bTiles=4
bScore=21
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, fill_out_tiles=True)

        self.assertEqual(10, map.GetTile(1, 0).army)
        self.assertEqual(5, map.GetTile(2, 0).army)
        self.assertEqual(1, map.GetTile(3, 3).army)
        self.assertEqual(5, enemyGeneral.army)
        self.assertEqual(21, map.players[enemyGeneral.player].score)

    def test_fill_out_tiles_adds_missing_enemy_army_to_furthest_fog_first(self):
        testData = """
|    |    |    |    |    |
aG1  b10  b5D


               b1D  bG1D
|    |    |    |    |    |
player_index=0
aTiles=1
aScore=1
bTiles=4
bScore=22
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, fill_out_tiles=True)

        self.assertEqual(10, map.GetTile(1, 0).army)
        self.assertEqual(5, map.GetTile(2, 0).army)
        self.assertEqual(1, map.GetTile(3, 3).army)
        self.assertEqual(6, enemyGeneral.army)
        self.assertEqual(22, map.players[enemyGeneral.player].score)

    def test_fill_out_tiles_can_add_missing_enemy_army_to_fog_general(self):
        testData = """
|    |    |    |    |    |
aG1  b10  b5D


               b1D  bG1D
|    |    |    |    |    |
player_index=0
aTiles=1
aScore=1
bTiles=4
bScore=22
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 1, fill_out_tiles=True)

        self.assertEqual(10, map.GetTile(1, 0).army)
        self.assertEqual(5, map.GetTile(2, 0).army)
        self.assertEqual(1, map.GetTile(3, 3).army)
        self.assertEqual(6, enemyGeneral.army)
        self.assertEqual(22, map.players[enemyGeneral.player].score)
