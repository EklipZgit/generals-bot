from TestBase import TestBase


class EnsurePlayerTilesAndScoresTests(TestBase):
    def test_increments_enemy_fog_farthest_from_player_general(self):
        rawMap = """
|    |    |    |    |
     aG1



               bG1
|    |    |    |    |
player_index=0
bot_target_player=1
"""

        map, general, enemyGen = self.load_map_and_generals_from_string(rawMap, 1)

        playerFrontier = map.GetTile(3, 3)
        closerToPlayerGeneralFogTile = map.GetTile(1, 1)
        fartherFromPlayerGeneralFogTile = map.GetTile(4, 3)

        playerFrontier.player = general.player
        playerFrontier.army = 1

        closerToPlayerGeneralFogTile.player = enemyGen.player
        closerToPlayerGeneralFogTile.army = 1

        fartherFromPlayerGeneralFogTile.player = enemyGen.player
        fartherFromPlayerGeneralFogTile.army = 1

        map.update(bypassDeltas=True)

        self.ensure_player_tiles_and_scores(
            map,
            general,
            generalTileCount=-1,
            generalTargetScore=-1,
            enemyGeneral=enemyGen,
            enemyGeneralTileCount=-1,
            enemyGeneralTargetScore=4,
            protectedFileVisibleTiles={enemyGen})

        self.assertEqual(1, closerToPlayerGeneralFogTile.army)
        self.assertEqual(2, fartherFromPlayerGeneralFogTile.army)
