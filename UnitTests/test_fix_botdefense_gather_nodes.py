import typing
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from BotModules.BotDefense import BotDefense
from BotModules.BotGatherOps import BotGatherOps
from Models.GatherTreeNode import GatherTreeNode
from Models.Move import Move
from Path import Path
from base.client.tile import Tile


class BotDefenseFlankGatherNodesCrashFixTests(unittest.TestCase):
    """
    Regression tests for a live-game IndexError in
    BotDefense._get_flank_vision_defense_move_internal, observed in FFA games
    Human.exe-ffa-2026-09-30_04-58-56---89J4KldN3 (t519) and
    Human.exe-ffa-2026-09-30_08-12-26---33G7fylbN (repeated t792-t796):

      File "BotModules/BotDefense.py", line ~2493
        n = SearchUtils.where(gatherNodes, lambda n: n.gatherTurns > 0)[0]
      IndexError: list index out of range

    Root cause: when the flank gather's wasteWeight <= 0 (every gather turn is
    also a capture, so the gather is 'free'), the gather tree is pruned down to
    army=1 before building the bot.curPath visualization path.
    Gather.prune_mst_to_army_with_values can legitimately prune EVERY non-root
    node out of the tree - invalid leaves (army <= 1 or enemy tiles) are pruned
    regardless of the untilFunc - leaving only bare root nodes whose gatherTurns
    have all decremented to 0. Indexing [0] on the filtered root list then
    explodes. Matches the preceding crash log line:
    'Flank Gath valGathered 0.0(...) / (gatherTurns 0(7) - caps 7)'.

    These tests stub the bot surface and patch
    BotGatherOps.get_gather_to_target_tiles to return hand-built gather trees,
    but run the REAL Gather.prune_mst_to_army_with_values inside the function
    under test so the all-gatherTurns-0 root state is produced the same way it
    is produced in the live game.
    """

    @staticmethod
    def _build_bot(flank_danger_tiles: typing.Set[Tile]) -> SimpleNamespace:
        """
        Builds the minimum bot surface _get_flank_vision_defense_move_internal
        touches. The target-player gather path is a real Path so that
        .adjacentSet (empty, our tiles have no adjacents) and .length
        (path length - 1 = 4 -> maxOffs = 1, a single gather iteration) behave
        exactly as in live code.
        """
        gatherPath = Path()
        for i in range(5):
            gatherPath.add_next(Tile(20, i, tileIndex=1000 + i))

        return SimpleNamespace(
            _map=SimpleNamespace(
                turn=519,
                team_ids_by_player_index=[0, 1],
                is_tile_friendly=lambda tile: tile.player == 0),
            board_analysis=SimpleNamespace(
                flank_danger_play_area_matrix=set(flank_danger_tiles)),
            viewInfo=SimpleNamespace(
                add_targeted_tile=lambda *args, **kwargs: None,
                add_info_line=lambda *args, **kwargs: None,
                midRightGridText={},
                bottomMidRightGridText={},
                bottomRightGridText={},
                bottomMidLeftGridText={},
                bottomLeftGridText={}),
            target_player_gather_path=gatherPath,
            player=SimpleNamespace(standingArmy=100, tileCount=10),
            general=SimpleNamespace(player=0),
            curPath=None)

    @staticmethod
    def _build_flank_threat_path() -> typing.Tuple[Path, typing.Set[Tile]]:
        """
        A 12-tile (length 11) enemy flank threat path. tileList[:9] is scanned
        for flank-danger fog tiles (all 9 returned in the danger set), and
        tileList[5:] keeps all 7 tiles (>= 11 // 5 + 1 = 3 required) since the
        gather path's adjacentSet is empty and discards nothing.
        """
        tiles = [Tile(30 + i, 0, player=1, army=3, tileIndex=2000 + i) for i in range(12)]
        path = Path()
        for t in tiles:
            path.add_next(t)
        dangerTiles = set(tiles[:9])
        return path, dangerTiles

    @staticmethod
    def _build_fully_prunable_gather_nodes() -> typing.List[GatherTreeNode]:
        """
        One gather tree: enemy-tile root <- friendly 1-army leaf. The leaf is an
        invalid gather move (army <= 1), so prune_mst_to_army_with_values strips
        it unconditionally, leaving the root bare with gatherTurns == 0 - the
        exact post-prune state that produced the live IndexError.
        """
        rootTile = Tile(40, 0, player=1, army=3, tileIndex=3000)
        leafTile = Tile(41, 0, player=0, army=1, tileIndex=3001)
        root = GatherTreeNode(rootTile, None)
        root.value = 1
        root.gatherTurns = 1
        leaf = GatherTreeNode(leafTile, rootTile)
        leaf.value = 1
        leaf.gatherTurns = 1
        leaf.trunkDistance = 1
        leaf.trunkValue = 1
        leaf.toGather = root
        root.children.append(leaf)
        return [root]

    @staticmethod
    def _build_surviving_gather_nodes() -> typing.Tuple[typing.List[GatherTreeNode], Tile, Tile]:
        """
        One gather tree: enemy-tile root <- friendly 21-army leaf. The leaf is a
        valid gather move, and pruning it would leave 0 army < the army=1
        target, so untilFunc stops the prune and the root keeps gatherTurns > 0.
        """
        rootTile = Tile(40, 0, player=1, army=3, tileIndex=3100)
        leafTile = Tile(41, 0, player=0, army=21, tileIndex=3101)
        root = GatherTreeNode(rootTile, None)
        root.value = 20
        root.gatherTurns = 1
        leaf = GatherTreeNode(leafTile, rootTile)
        leaf.value = 20
        leaf.gatherTurns = 1
        leaf.trunkDistance = 1
        leaf.trunkValue = 20
        leaf.toGather = root
        root.children.append(leaf)
        return [root], leafTile, rootTile

    def test_flank_vision_defense_does_not_crash_when_prune_strips_all_gather_turns(self):
        """
        Reproduces the live IndexError: wasteWeight <= 0 (returned gatherTurns 1
        == caps 1, the single non-friendly node with children) enters the
        prune-to-army-1 branch, the real prune strips the invalid leaf, and
        every surviving root has gatherTurns == 0. Before the fix this raised
        IndexError on `SearchUtils.where(...)[0]`; after the fix the function
        skips the curPath assignment (a path with nothing to gather is not a
        flank defense path) and returns None.
        """
        flankThreatPath, dangerTiles = self._build_flank_threat_path()
        bot = self._build_bot(dangerTiles)

        def fake_gather_to_target_tiles(botArg, targets, **kwargs) -> typing.Tuple[Move | None, int, int, typing.List[GatherTreeNode]]:
            return None, 1, 1, self._build_fully_prunable_gather_nodes()

        with patch.object(BotGatherOps, 'get_gather_to_target_tiles', side_effect=fake_gather_to_target_tiles):
            move = BotDefense._get_flank_vision_defense_move_internal(bot, flankThreatPath, set(), atDist=5)

        self.assertIsNone(move)
        self.assertIsNone(bot.curPath)

    def test_flank_vision_defense_still_sets_curpath_when_pruned_tree_has_gather_turns(self):
        """
        Guard test for the surviving-tree case: the valid 21-army leaf cannot be
        pruned without dropping below the army=1 target, so the root keeps
        gatherTurns > 0 and curPath is still built from the root's child chain
        (deepest node first via add_start), exactly as before the fix.
        """
        flankThreatPath, dangerTiles = self._build_flank_threat_path()
        bot = self._build_bot(dangerTiles)

        def fake_gather_to_target_tiles(botArg, targets, **kwargs) -> typing.Tuple[Move | None, int, int, typing.List[GatherTreeNode]]:
            gatherNodes, leafTile, rootTile = self._build_surviving_gather_nodes()
            return Move(leafTile, rootTile, False), 20, 1, gatherNodes

        with patch.object(BotGatherOps, 'get_gather_to_target_tiles', side_effect=fake_gather_to_target_tiles):
            move = BotDefense._get_flank_vision_defense_move_internal(bot, flankThreatPath, set(), atDist=5)

        self.assertIsNotNone(move)
        self.assertIsNotNone(bot.curPath)
        # path is built leaf-first via add_start: [leafTile, rootTile]
        self.assertEqual(2, len(bot.curPath.tileList))
        self.assertEqual(3101, bot.curPath.tileList[0].tile_index)
        self.assertEqual(3100, bot.curPath.tileList[1].tile_index)


if __name__ == '__main__':
    unittest.main()
