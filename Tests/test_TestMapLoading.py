from TestBase import TestBase
from base.client.map import MapBase


class TestMapLoadingTests(TestBase):
    def __init__(self, methodName: str = ...):
        super().__init__(methodName)
        MapBase.DO_NOT_RANDOMIZE = True
        self.begin_capturing_logging()

    def test_fill_out_tiles_respects_resume_enemy_tile_count_after_generating_fog_cities(self):
        mapFile = 'GameContinuationEntries/should_not_gather_against_likely_kill_threat_when_must_attack_especially_when_up_on_gathered_army___DbXfAlcFV---0--271.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 271, fill_out_tiles=True)

        self.assertEqual(80, map.players[enemyGeneral.player].tileCount)
        self.assertEqual(80, len(map.players[enemyGeneral.player].tiles))
        self.assertEqual(80, sum(1 for tile in map.get_all_tiles() if tile.player == enemyGeneral.player))
        self.assertEqual(4, map.players[enemyGeneral.player].cityCount)
        self.assertEqual(3, len(map.players[enemyGeneral.player].cities))
        self.assertEqual(240, map.players[enemyGeneral.player].score)

    def test_fill_out_tiles_preserves_target_score_when_enemy_already_has_target_tiles(self):
        mapFile = 'GameContinuationEntries/should_play_defensively_when_equalizing_on_cities_and_up_massively_on_tiles___aRLuObTKX---1--214.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 214, fill_out_tiles=True)

        self.assertEqual(185, map.players[enemyGeneral.player].score)

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

    def test_fill_out_tiles_preserves_player_score_from_txtmap(self):
        """Repro for issue where fill_out_tiles crashed because player 1's score didn't match txtmap.

        Error was: load_map_and_generals fill_out_tiles player 1 player.score 440 != txtmap bScore 438

        This txtmap is internally inconsistent: the friendly player's VISIBLE tiles (untouchable ground
        truth - fill_out_tiles may never modify visible tiles) genuinely sum to 440 army on the board,
        while the scoreboard data says bScore=438 (scoreboard lagged the board by a move at save time).
        When the visible board contradicts the scoreboard, THE BOARD WINS: the load must succeed and
        keep the actual visible army values rather than corrupting visible tiles to chase the scoreboard.
        """
        mapFile = 'GameContinuationEntries/should_be_able_to_complete_city_capture_against_non_moving_threat___SejdBT5Vp---1--392.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 392, fill_out_tiles=True)

        # player_index=1 is 'b' player (us); the visible board sums to 440 even though bScore=438
        self.assertEqual(440, map.players[general.player].score)
        self.assertEqual(100, map.players[general.player].tileCount)

    def test_fill_out_tiles_preserves_enemy_score_from_txtmap(self):
        """Repro for issue where fill_out_tiles causes player 0 (enemy) score to not match txtmap.

        Error was: load_map_and_generals fill_out_tiles player 0 player.score 223 != txtmap aScore 222
        """
        mapFile = 'GameContinuationEntries/should_barely_save_against_no_known_king_loc___SepnLTq6h---b--537.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 537, fill_out_tiles=True)

        # player_index=1 is 'b' player (us), 'a' is enemy player 0
        self.assertEqual(222, map.players[enemyGeneral.player].score)

    def test_fill_out_tiles_handles_dead_player_city_count(self):
        """Repro for issue where fill_out_tiles caused dead player 3 cityCount validation to fail.

        Error was: load_map_and_generals fill_out_tiles player 3 player.cityCount 0 != txtmap dCityCount 1
        Dead players should not have their city count validated since they don't control tiles anymore.
        """
        mapFile = 'GameContinuationEntries/should_defend_against_defensable_threat___mSR6Tg1Wg---2--586.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 586, fill_out_tiles=True)

        # player 3 ('d') is dead - should have 0 tiles/cities, validation should skip them
        self.assertTrue(map.players[3].dead)
        self.assertEqual(0, map.players[3].tileCount)
        self.assertEqual(0, map.players[3].cityCount)

    def test_fill_out_tiles_preserves_player_tile_count(self):
        """Repro for issue where fill_out_tiles causes player 1 (friendly) tileCount to not match txtmap.

        Error was: load_map_and_generals fill_out_tiles player 1 len(player.tiles) 123 != txtmap bTiles 122
        """
        mapFile = 'GameContinuationEntries/should_defend_city_and_not_get_weird_trunkvalue_zeros___74QU5HBYT---1--479.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 479, fill_out_tiles=True)

        # player_index=1 is 'b' player (us), bTiles=122 in txtmap
        self.assertEqual(122, map.players[general.player].tileCount)

    def test_fill_out_tiles_handles_dead_player_city_count_2v2(self):
        """Repro for 2v2 where fill_out_tiles caused dead player 2 cityCount validation to fail.

        Error was: load_map_and_generals fill_out_tiles player 2 player.cityCount 0 != txtmap cCityCount 1
        """
        mapFile = 'GameContinuationEntries/should_not_defense_loop___5v5zuNmVX---3--266.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 266, fill_out_tiles=True)

        # player_index=3 is 'd' player (us), player 2 ('c') is dead teammate
        self.assertTrue(map.players[2].dead)
        self.assertEqual(0, map.players[2].tileCount)
        self.assertEqual(0, map.players[2].cityCount)

    def test_fill_out_tiles_handles_dead_enemy_city_count_2v2(self):
        """Repro for 2v2 where fill_out_tiles caused dead enemy player 1 cityCount validation to fail.

        Error was: load_map_and_generals fill_out_tiles player 1 player.cityCount 0 != txtmap bCityCount 1
        """
        mapFile = 'GameContinuationEntries/should_not_early_gather_defense_leaf_dist_move___FzaOG3k1f---0--410.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 410, fill_out_tiles=True)

        # player_index=0 is 'a' player (us), player 1 ('b') is dead enemy
        self.assertTrue(map.players[1].dead)
        self.assertEqual(0, map.players[1].tileCount)
        self.assertEqual(0, map.players[1].cityCount)

    def test_fill_out_tiles_adds_missing_enemy_tiles(self):
        """Repro for case where enemy has fewer tiles than txtmap says.

        Error was: load_map_and_generals fill_out_tiles player 0 len(player.tiles) 107 != txtmap aTiles 121
        """
        mapFile = 'GameContinuationEntries/should_path_large_tile_through_flank_cities____H2EL3yXK---1--952.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 952, fill_out_tiles=True)

        # player_index=1 is 'b' player (us), 'a' is enemy player 0, aTiles=121
        self.assertEqual(121, map.players[enemyGeneral.player].tileCount)

    def test_fill_out_tiles_handles_extra_friendly_tiles(self):
        """Repro for case where friendly player has more tiles than txtmap says.

        Error was: load_map_and_generals fill_out_tiles player 1 len(player.tiles) 74 != txtmap bTiles 73
        But actually player_index=0 is 'a' player (us) with aTiles=91, aScore=319
        """
        mapFile = 'GameContinuationEntries/should_gather_into_threat___XAIaeetAk---0--383.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 383, fill_out_tiles=True)

        # player_index=0 is 'a' player (us), aTiles=91, aScore=319 in txtmap
        self.assertEqual(91, map.players[general.player].tileCount)
        self.assertEqual(319, map.players[general.player].score)

    def test_fill_out_tiles_handles_extra_ally_tiles_2v2(self):
        """Repro for 2v2 case where an enemy has more tiles on the board than the txtmap scoreboard says.

        Error was: load_map_and_generals fill_out_tiles player 2 len(player.tiles) 41 != txtmap cTiles 34

        teams=1,1,2,2 with player_index=0, so the ALLY is player 1 ('b', bTiles=23) and players 2/3
        ('c'/'d') are the enemy team. Player 2's board tiles (41, mostly fog guesses) exceed cTiles=34,
        so 7 fog tiles must be dropped - without ever touching tiles visible to the friendly team.
        """
        mapFile = 'GameContinuationEntries/should_defend_ally_in_2v2___brs1WYHiG---0--132.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

        # ally is player 1 ('b'), bTiles=23 in the txtmap
        self.assertEqual(1, allyGen.player)
        self.assertEqual(23, map.players[allyGen.player].tileCount)
        # enemy team: cTiles=34 and dTiles=45 must be reconciled from fog only
        self.assertEqual(34, map.players[2].tileCount)
        self.assertEqual(45, map.players[3].tileCount)

    def test_fill_out_tiles_all_living_players_have_generals_2v2(self):
        """Verify all living 2v2 players have non-null generals after fill_out_tiles.

        Error was: test_should_defend_2v2_ally failed with 'NoneType' object has no attribute 'player'
        """
        mapFile = 'GameContinuationEntries/should_defend_ally_in_2v2___brs1WYHiG---0--132.txtmap'
        map, general, allyGen, enemyGeneral, enemyAllyGen = self.load_map_and_generals_2v2(mapFile, 132, fill_out_tiles=True)

        # All living players should have non-null generals
        for player in map.players:
            if not player.dead:
                self.assertIsNotNone(player.general, f"Player {player.index} should have a general")

    def test_fill_out_tiles_preserves_enemy_city_count(self):
        """Repro for enemy city count mismatch.

        Error was: load_map_and_generals fill_out_tiles player 1 player.cityCount 3 != txtmap bCityCount 2
        """
        mapFile = 'GameContinuationEntries/should_intercept_before_split_choke___wCipq_zxN---0--339.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 339, fill_out_tiles=True)

        # player_index=0 is 'a' player (us), 'b' is enemy player 1, bCityCount=2
        self.assertEqual(2, map.players[enemyGeneral.player].cityCount)
