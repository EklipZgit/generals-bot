import typing

from Gather.GatherDepthIterative import _add_tree_nodes_to_start_tiles_dict_recurse, _extend_tree_node_lookup
from Gather.GatherPrune import prune_mst_to_turns_with_values, recalculate_tree_values
from Models import GatherTreeNode
from Path import Path
from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile


class GatherFromDistCrashFixTests(TestBase):
    """
    Reproductions for a live-game crash observed in FFA game
    Human.exe-ffa-2026-09-29_12-13-47---85TYBCqWs (repeated every turn t489-t499):

      AssertionError at GatherDepthIterative.py::_extend_tree_node_lookup:
      'curGatherTreeNode [13,10->14,10 t7 v148.0189 tv23, ch1] HAD A FROM TILE
       (14,10 a3) fromDist [None] curDist [25] THAT WAS NOT IN THE gatherTreeNodeLookup...?'

    Root cause: _extend_tree_node_lookup unconditionally created a NEW GatherTreeNode for
    every non-start tile of every knapsack path, even when that tile already had a node in
    gatherTreeNodeLookup (dedup only checked the current parent's children list).
    Duplicate tile nodes break the bijection between the tile-keyed gatherTreeNodeLookup
    and the actual gather tree: prune_mst_until pops a pruned subtree's tiles out of
    gatherTreeNodeLookupToPrune by tile key, so pruning EITHER duplicate unregisters the
    tile entirely while the other duplicate is still in the tree - leaving that duplicate's
    children with a toTile that no longer resolves in the lookup, which trips the
    'HAD A FROM TILE' assert on the next _extend_tree_node_lookup call's value bubble-up.

    These tests construct the node/lookup state directly (per the algorithm's own
    _knapsack_levels_gather_iterative_depth_prune seeding), add paths through
    _extend_tree_node_lookup, prune via prune_mst_to_turns_with_values, then extend again.
    """

    def _load_map(self) -> MapBase:
        testData = """
|    |    |    |    |    |
aG1  a20  a5   a5   a50
a2   a20  a5   a5   bG1
|    |    |    |    |    |
player_index=0
        """
        map, _, _ = self.load_map_and_generals_from_string(testData, 100)
        return map

    @staticmethod
    def _path(value: float, tiles: typing.List[Tile]) -> Path:
        path = Path(value)
        for tile in tiles:
            path.add_next(tile)
        return path

    @staticmethod
    def _base_case(_tile: Tile, _dist: int) -> None:
        return None

    def test_extend_does_not_duplicate_nodes_for_tiles_already_in_tree(self):
        """
        A knapsack path that passes through a tile already present in the gather tree must
        reuse the existing GatherTreeNode instead of registering a second node for the same
        tile (the tile-keyed gatherTreeNodeLookup can only ever hold one of them).
        """
        map = self._load_map()
        teams = MapBase.get_teams_array(map)
        tRoot = map.GetTile(1, 0)
        tP1 = map.GetTile(2, 0)
        tT = map.GetTile(0, 1)
        tC = map.GetTile(1, 1)
        tP2 = map.GetTile(3, 0)

        gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {tRoot: GatherTreeNode(tRoot, None, 0)}
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]] = {tRoot: (None, 0)}
        logEntries: typing.List[str] = []

        # path values are the gathered army contributions of their non-start tiles
        # (friendly tile contributes army - 1): 4 + 1 + 19 = 24 and 4 + 1 = 5.
        path1 = self._path(24, [tRoot, tP1, tT, tC])
        path2 = self._path(5, [tRoot, tP2, tT])

        _extend_tree_node_lookup([path1, path2], gatherTreeNodeLookup, startTilesDict, 0, teams, set(), logEntries)

        rootNode = gatherTreeNodeLookup[tRoot]
        allNodes = [n for n in GatherTreeNode.iterate_tree_nodes([rootNode])]
        nodeTiles = [n.tile for n in allNodes]
        # every tree tile maps to exactly one node, and the lookup agrees with the tree
        self.assertEqual(len(set(nodeTiles)), len(nodeTiles),
                         f'duplicate tree nodes for tiles: {[str(n) for n in allNodes]}')
        nodeT = gatherTreeNodeLookup[tT]
        # tT's node must be the one already in the tree (under tP1), not a new duplicate
        self.assertEqual(tP1, nodeT.toTile)
        self.assertIn(nodeT, gatherTreeNodeLookup[tP1].children)

    def test_extend_reuses_existing_nodes_when_path_rewalks_same_branch(self):
        """
        Even when the path hits an existing tile under the SAME parent node, the old code
        skipped the children.append (tile-eq) but still overwrote gatherTreeNodeLookup with
        a fresh orphan node that was not in the tree at all - its tail children then also
        lived outside the tree. Reusing the existing node fixes both cases at once.
        """
        map = self._load_map()
        teams = MapBase.get_teams_array(map)
        tRoot = map.GetTile(1, 0)
        tP1 = map.GetTile(2, 0)
        tT = map.GetTile(0, 1)
        tE = map.GetTile(3, 1)

        gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {tRoot: GatherTreeNode(tRoot, None, 0)}
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]] = {tRoot: (None, 0)}
        logEntries: typing.List[str] = []

        path1 = self._path(5, [tRoot, tP1, tT])
        _extend_tree_node_lookup([path1], gatherTreeNodeLookup, startTilesDict, 0, teams, set(), logEntries)
        nodeP1 = gatherTreeNodeLookup[tP1]
        nodeT = gatherTreeNodeLookup[tT]

        path2 = self._path(9, [tRoot, tP1, tT, tE])
        _extend_tree_node_lookup([path2], gatherTreeNodeLookup, startTilesDict, 0, teams, set(), logEntries)

        # the existing nodes must still be the registered ones (no orphan overwrite)
        self.assertIs(nodeP1, gatherTreeNodeLookup[tP1])
        self.assertIs(nodeT, gatherTreeNodeLookup[tT])
        # the new tail tile must hang off the existing tT node inside the tree
        nodeE = gatherTreeNodeLookup[tE]
        self.assertIn(nodeE, nodeT.children)
        self.assertEqual(tT, nodeE.toTile)
        # and value/turn bookkeeping must still satisfy the subtree-sum invariant
        recalcTurns, recalcValue = recalculate_tree_values(
            logEntries, [gatherTreeNodeLookup[tRoot]], set(), 0, teams,
            onlyCalculateFriendlyArmy=True, shouldAssert=True)
        self.assertEqual(3, recalcTurns)
        self.assertEqual(9, recalcValue)

    def test_extend_after_pruning_duplicate_does_not_hit_dangling_from_tile(self):
        """
        Full crash repro: a second path duplicates tile tT's node; the leaf duplicate gets
        pruned, which pops tT's key from gatherTreeNodeLookup while the OTHER duplicate's
        child (tC) is still registered - the next extension bubbles up through tC and hits
        the dangling toTile, firing the live-game assert.
        """
        map = self._load_map()
        teams = MapBase.get_teams_array(map)
        tRoot = map.GetTile(1, 0)
        tP1 = map.GetTile(2, 0)
        tT = map.GetTile(0, 1)
        tC = map.GetTile(1, 1)
        tP2 = map.GetTile(3, 0)
        tD = map.GetTile(2, 1)

        gatherTreeNodeLookup: typing.Dict[Tile, GatherTreeNode] = {tRoot: GatherTreeNode(tRoot, None, 0)}
        startTilesDict: typing.Dict[Tile, typing.Tuple[typing.Any, int]] = {tRoot: (None, 0)}
        logEntries: typing.List[str] = []

        path1 = self._path(24, [tRoot, tP1, tT, tC])
        path2 = self._path(5, [tRoot, tP2, tT])
        _extend_tree_node_lookup([path1, path2], gatherTreeNodeLookup, startTilesDict, 0, teams, set(), logEntries)

        rootNode = gatherTreeNodeLookup[tRoot]
        # mirrors _knapsack_levels_gather_iterative_depth_prune: all tree tiles become
        # searchable start tiles between iterations
        _add_tree_nodes_to_start_tiles_dict_recurse(rootNode, startTilesDict, 0, 20, self._base_case, dist=0)

        prune_mst_to_turns_with_values(
            [rootNode],
            turns=3,
            searchingPlayer=0,
            gatherTreeNodeLookupToPrune=gatherTreeNodeLookup,
            tileDictToPrune=startTilesDict,
            noLog=True)

        # pre-fix this next extension raises the live-game AssertionError:
        # 'curGatherTreeNode [tC->tT ...] HAD A FROM TILE tT ... THAT WAS NOT IN THE
        #  gatherTreeNodeLookup'
        path3 = self._path(4, [tC, tD])
        _extend_tree_node_lookup([path3], gatherTreeNodeLookup, startTilesDict, 0, teams, set(), logEntries)

        # every registered node's toTile must resolve inside the lookup
        for tile, node in gatherTreeNodeLookup.items():
            self.assertTrue(node.toTile is None or node.toTile in gatherTreeNodeLookup,
                            f'node {str(node)} has dangling toTile {str(node.toTile)}')

        # and the whole tree's value/gatherTurns bookkeeping must satisfy the
        # subtree-sum invariant that recalculate_tree_values verifies
        recalcTurns, recalcValue = recalculate_tree_values(
            logEntries, [rootNode], set(), 0, teams,
            onlyCalculateFriendlyArmy=True, shouldAssert=True)
        self.assertEqual(4, recalcTurns)
        self.assertEqual(28, recalcValue)
