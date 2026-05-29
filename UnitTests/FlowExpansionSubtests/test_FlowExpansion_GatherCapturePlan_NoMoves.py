"""
Tests for GatherCapturePlan no-moves error scenarios.

These tests document the contract for convert_contiguous_capture_tiles_to_gather_capture_plan:
- The gather tile set must have sufficient total army to execute all captures
- The root tiles must be adjacent to capture tiles
- All tiles must be contiguous

The BUG is UPSTREAM in FlowExpansion._materialize_plans which may produce
tile sets violating these constraints. The fix belongs there, not in this function.
"""

import typing

import logbook

from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
from BoardAnalyzer import BoardAnalyzer
from Gather import GatherDebug
from Tests.TestBase import TestBase
from base.client.map import MapBase, Tile
from Gather.GatherCapturePlan import GatherCapturePlan
from Gather import GatherUtils
from Sim.TextMapLoader import TextMapLoader


class GatherCapturePlanNoMovesTests(TestBase):
    """Tests documenting GCP contract and army sufficiency requirements."""

    def __init__(self, methodName: str = ...):
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    def _log_flow_expansion_details(self, expander, plans, map):
        """Log detailed information about flow expansion plans and lookup tables."""
        logbook.info("\n" + "="*70)
        logbook.info("FLOW EXPANSION DETAILS")
        logbook.info("="*70)

        logbook.info(f"\nNumber of plans generated: {len(plans.flow_plans)}")

        # Log lookup tables if available
        if hasattr(expander, 'last_lookup_tables') and expander.last_lookup_tables:
            logbook.info(f"\nLookup tables: {len(expander.last_lookup_tables)} border pairs")
            for i, table in enumerate(expander.last_lookup_tables):
                logbook.info(f"\n  Table {i}:")
                logbook.info(f"    Border pair: {table.border_pair.friendly_island_id} -> {table.border_pair.target_island_id}")
                logbook.info(f"    Capture entries by turn: {len(table.capture_entries_by_turn)}")
                for turn, entry in enumerate(table.capture_entries_by_turn):
                    if entry:
                        logbook.info(f"      Turn {turn}: required_army={entry.required_army}, "
                              f"gathered_army={entry.gathered_army}")

        # Log each plan
        for i, plan in enumerate(plans.flow_plans):
            logbook.info(f"\n  Plan {i}:")
            logbook.info(f"    Type: {type(plan).__name__}")
            logbook.info(f"    Length: {plan.length}")
            if hasattr(plan, 'root_nodes'):
                logbook.info(f"    Root nodes: {len(plan.root_nodes)}")
                for root in plan.root_nodes:
                    logbook.info(f"      Root at {root.tile}: army={root.tile.army}")
                    if hasattr(root, 'children') and root.children:
                        for child in root.children:
                            if child:
                                logbook.info(f"        Child at {child.tile}: army={child.tile.army}")
            if hasattr(plan, 'tile_set'):
                logbook.info(f"    Tile set: {len(plan.tile_set)} tiles")
                for tile in sorted(plan.tile_set, key=lambda t: (t.x, t.y)):
                    logbook.info(f"      ({tile.x},{tile.y}): army={tile.army}, player={tile.player}")

        # Log island information
        if expander.island_builder:
            logbook.info(f"\nIslands: {len(expander.island_builder.all_tile_islands)} total")
            for island in sorted(expander.island_builder.all_tile_islands, key=lambda i: i.unique_id):
                logbook.info(f"  Island {island.unique_id}: {island.tile_count} tiles, "
                      f"team={island.team}, army={island.sum_army}")
                sample_tiles = list(island.tile_set)[:3]
                tile_strs = [f"({t.x},{t.y})" for t in sample_tiles]
                if island.tile_count > 3:
                    tile_strs.append(f"...({island.tile_count-3} more)")
                logbook.info(f"    Tiles: {', '.join(tile_strs)}")

        logbook.info("="*70)

    def test_convert_contiguous_capture_tiles_should_work_with_connected_tiles(self):
        """
        Verifies that when tiles ARE properly connected, the plan works correctly.

        This is the positive case - tiles are contiguous and path exists.

        Map layout:
        |    |    |    |    |    |    |    |
        aG1  a5   a1   a1   b1   b1   bG1
        |    |    |    |    |    |    |    |

        The friendly tiles (0-3) are contiguous with enemy tiles (4-6).
        """
        map_data = """
|    |    |    |    |    |    |    |
aG1  a5   a1   a1   b1   b1   bG1
|    |    |    |    |    |    |    |
player_index=0
bot_target_player=1
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=100, fill_out_tiles=True
        )
        self.begin_capturing_logging()

        # Friendly tiles to gather from (columns 1-3)
        gathing = {
            map.GetTile(1, 0),  # a5
            map.GetTile(2, 0),  # a1
            map.GetTile(3, 0),  # a1 - this connects to enemy tile at (4,0)
        }

        # Root tiles (must be friendly and adjacent to first capture tile)
        root_tiles = {
            map.GetTile(3, 0),  # a1 (adjacent to enemy at 4,0)
        }

        # Enemy tiles to capture (columns 4-6)
        capping = {
            map.GetTile(4, 0),  # b1
            map.GetTile(5, 0),  # b1
            map.GetTile(6, 0),  # bG1
        }

        # This should work fine - tiles are contiguous (friendly at 3,0 touches enemy at 4,0)
        plan = GatherUtils.convert_contiguous_capture_tiles_to_gather_capture_plan(
            map,
            rootTiles=root_tiles,
            tiles=gathing,
            negativeTiles=None,
            searchingPlayer=general.player,
            priorityMatrix=None,
            useTrueValueGathered=False,
            captures=capping,
        )

        # Plan should have valid moves
        first_move = plan.get_first_move()
        self.assertIsNotNone(first_move, "Plan should have a valid first move")
        self.assertGreater(len(plan.root_nodes), 0, "Plan should have root nodes")

        # At least one root node should have children
        has_children = any(
            len(node.children) > 0 for node in plan.root_nodes
        )
        self.assertTrue(has_children, "At least one root node should have children")

    def test_sufficient_army_produces_valid_plan(self):
        """
        Tests that sufficient army (2) vs enemy (1) produces a valid plan.

        This is a positive test case - the gather tile has exactly enough army
        to capture the enemy tile (2 > 1 required).
        """
        map_data = """
|    |    |    |
aG1  a2   b1   bG1
|    |    |    |
player_index=0
bot_target_player=1
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=144, fill_out_tiles=False
        )
        self.begin_capturing_logging()

        # Friendly tile with sufficient army (2) to capture enemy tile (1)
        gathing = {
            map.GetTile(1, 0),  # a2 - friendly tile with 2 army
        }

        # Root tiles - the tile we're gathering from
        root_tiles = {
            map.GetTile(1, 0),  # a2
        }

        # Enemy tiles to capture
        capping = {
            map.GetTile(2, 0),  # b1
        }

        # This produces a valid plan - sufficient army
        plan = GatherUtils.convert_contiguous_capture_tiles_to_gather_capture_plan(
            map,
            rootTiles=root_tiles,
            tiles=gathing,
            negativeTiles=None,
            searchingPlayer=general.player,
            priorityMatrix=None,
            useTrueValueGathered=False,
            captures=capping,
        )

        # Plan should have a valid first move
        first_move = plan.get_first_move()
        self.assertIsNotNone(first_move, "Plan should have a valid first move")

    def test_total_army_across_multiple_tiles_produces_valid_plan(self):
        """
        Tests that total army across multiple tiles produces valid plan.

        When gather set includes both tiles (1 army + 2 army = 3 total),
        the plan succeeds even though the root tile only has 1 army.
        The gather tree pulls from the supporting tile first.
        """
        map_data = """
|    |    |    |    |    |
aG1  a0   b1   b2   bG1
|    |    |    |    |    |
player_index=1
bot_target_player=0
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=73, fill_out_tiles=False
        )
        self.begin_capturing_logging()

        # Include BOTH tiles in the gather set - total 3 army available
        # This mimics the flow algorithm behavior where island tiles are included
        gathing = {
            map.GetTile(2, 0),  # b1 - 1 army, adjacent to neutral
            map.GetTile(3, 0),  # b2 - 2 army, can provide army
        }

        # Root tile is the one adjacent to capture target
        root_tiles = {
            map.GetTile(2, 0),  # b1 - the tile trying to capture
        }

        # Neutral tile to capture - requires 2 army (1 to move + 1 to capture)
        capping = {
            map.GetTile(1, 0),  # a0 - neutral with 0 army
        }

        # This SHOULD produce a valid plan because we have 3 total army
        # and only need 2 to capture. But the bug causes it to fail because
        # the root tile (2,0) alone only has 1 army.
        plan = GatherUtils.convert_contiguous_capture_tiles_to_gather_capture_plan(
            map,
            rootTiles=root_tiles,
            tiles=gathing,
            negativeTiles=None,
            searchingPlayer=general.player,  # player 1
            priorityMatrix=None,
            useTrueValueGathered=False,
            captures=capping,
        )

        # The plan should have a valid first move
        first_move = plan.get_first_move()
        self.assertIsNotNone(first_move, "Plan should have valid first move - "
                            "total army (3) > required (2), gather tree works.")

    def test_team_game_gcp_does_not_start_from_allied_land(self):
        map_data = """
|    |    |    |    |    |    |
aG5  a3   c2   c2   b1   bG1  dG1
|    |    |    |    |    |    |
player_index=0
bot_target_player=1
teams=0,1,0,1
mode=team
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=51, fill_out_tiles=False
        )
        self.begin_capturing_logging()

        gathing = {
            map.GetTile(1, 0),
            map.GetTile(2, 0),
            map.GetTile(3, 0),
        }
        capping = {
            map.GetTile(4, 0),
        }

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemy_general, possibleSpawns=None)

        plan = GatherUtils.convert_contiguous_capture_tiles_to_gather_capture_plan(
            map,
            rootTiles={map.GetTile(1, 0)},
            tiles=gathing,
            negativeTiles=None,
            searchingPlayer=general.player,
            priorityMatrix=None,
            useTrueValueGathered=False,
            captures=capping,
            intergeneral_analysis=analysis.intergeneral_analysis,
        )

        first_move = plan.get_first_move()
        self.assertIsNotNone(first_move, "Plan should gather through allied land from owned land")
        self.assertEqual(first_move.source.player, general.player)
        self.assertNotEqual(first_move.source.player, map.GetTile(2, 0).player)

    def test_team_game_gcp_does_not_gather_through_allied_general(self):
        map_data = """
|    |    |    |    |    |
aG5  a3   cG2  b1   bG1  dG1
|    |    |    |    |    |
player_index=0
bot_target_player=1
teams=0,1,0,1
mode=team
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=51, fill_out_tiles=False
        )
        self.begin_capturing_logging()

        gathing = {
            map.GetTile(1, 0),
        }
        capping = {
            map.GetTile(3, 0),
        }

        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemy_general, possibleSpawns=None)

        with self.assertRaises(Exception):
            GatherUtils.convert_contiguous_capture_tiles_to_gather_capture_plan(
                map,
                rootTiles={map.GetTile(1, 0)},
                tiles=gathing,
                negativeTiles=None,
                searchingPlayer=general.player,
                priorityMatrix=None,
                useTrueValueGathered=False,
                captures=capping,
                allowedReconnectTiles=gathing | capping,
                intergeneral_analysis=analysis.intergeneral_analysis,
            )

    def test_flow_materialization_connects_disconnected_allied_gather_component(self):
        map_data = """
|    |    |    |    |    |    |
aG5  a3   c2   c2   b1   bG1  dG1
|    |    |    |    |    |    |
player_index=0
bot_target_player=1
teams=0,1,0,1
mode=team
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=51, fill_out_tiles=False
        )
        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemy_general, possibleSpawns=None)

        expander = ArmyFlowExpanderV2(map)
        expander.island_builder = TileIslandBuilder(map, analysis.intergeneral_analysis)

        connected = expander._connect_allied_gather_components_to_owned_tiles(
            {
                map.GetTile(0, 0),
                map.GetTile(3, 0),
            },
            general.player
        )

        self.assertEqual(
            {
                map.GetTile(0, 0),
                map.GetTile(1, 0),
                map.GetTile(2, 0),
                map.GetTile(3, 0),
            },
            connected
        )


    def test_insufficient_army_raises_error(self):
        """
        CONTRACT TEST: Function raises error for insufficient army scenarios.

        A tile with 0 army cannot execute a capture. The gather tree will
        have no valid moves after pruning. This should raise a "no moves" error.

        Map: aG1  a0   b1   b2   bG1
             0    1    2    3    4
        Player 1 at (2,0) has 0 army, trying to capture neutral at (1,0).
        This should fail with "plan created with no moves" error due to insufficient army.
        """
        map_data = """
|    |    |    |    |
aG1  a0   b1   b2   bG1
|    |    |    |    |
player_index=1
bot_target_player=0
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=73, fill_out_tiles=False
        )
        self.begin_capturing_logging()

        # Gather set with 1 army tile - will be pruned as invalid
        gathing = {
            map.GetTile(2, 0),  # b1 - only 1 army
        }

        root_tiles = {map.GetTile(2, 0)}

        # Neutral to capture
        capping = {map.GetTile(1, 0)}  # a0

        # Should raise Exception for disconnected/insufficient gather tiles
        with self.assertRaises(Exception) as context:
            GatherUtils.convert_contiguous_capture_tiles_to_gather_capture_plan(
                map,
                rootTiles=root_tiles,
                tiles=gathing,
                negativeTiles=None,
                searchingPlayer=general.player,
                priorityMatrix=None,
                useTrueValueGathered=False,
                captures=capping,
            )

        # Error should mention no moves due to insufficient army
        self.assertIn("plan created with no moves", str(context.exception).lower())


    def test_flow_expander_produces_valid_gather_capture_plans(self):
        """
        REGRESSION TEST: FlowExpansion must produce valid GatherCapturePlans.

        This test goes through the FULL flow expansion pipeline and verifies
        that all produced plans have valid moves (not GATHER_CAPTURE_PLAN_NO_MOVE_ERROR).

        Map reproduces the turn 73 bug scenario:
        - Player 0 (a) general at (0,0), army tiles at (1,0)=3, (2,0)=1
        - Player 1 (b) general at (5,0), army tiles at (3,0)=1, (4,0)=5
        - Player 1 trying to capture player 0's tile at (2,0) with 1 army

        BUG: _materialize_plans may select tile (3,0) with only 1 army
        (adjacent to capture target), ignoring (4,0) with 5 army.

        BUG: _select_partial_gather_tiles picks by proximity, not army value.
        Result: Plan has no valid moves.

        TODO: This test WILL FAIL until the bug is fixed.
        """
        map_data = """
|    |    |    |    |    |    |
aG1  a3   a1   b1   b5   bG1
|    |    |    |    |    |    |
player_index=1
bot_target_player=0
"""
        map, general, enemy_general = self.load_map_and_generals_from_string(
            map_data, turn=73, fill_out_tiles=False
        )
        self.begin_capturing_logging()

        # Build the island builder
        analysis = BoardAnalyzer(map, general)
        analysis.rebuild_intergeneral_analysis(enemy_general, possibleSpawns=None)
        builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
        builder.recalculate_tile_islands(enemy_general)

        # Run flow expansion
        expander = ArmyFlowExpanderV2(map)
        expander.friendlyGeneral = general
        expander.enemyGeneral = enemy_general
        expander.target_team = map.team_ids_by_player_index[enemy_general.player]
        expander.island_builder = builder
        expander.log_debug = False

        # This triggers _materialize_plans internally
        plans = expander.get_expansion_options(
            builder,
            general.player,
            enemy_general.player,
            turns=10,
            boardAnalysis=None,
            territoryMap=None,
            negativeTiles=None
        )

        # DEBUG: Log detailed flow plan information
        self._log_flow_expansion_details(expander, plans, map)

        # ASSERT: All plans must have valid first moves
        # This will FAIL until the bug is fixed
        self.assertGreater(len(plans.flow_plans), 0, "Expected at least one plan to be generated")
        for i, plan in enumerate(plans.flow_plans):
            first_move = plan.get_first_move()
            self.assertIsNotNone(
                first_move,
                f"Plan {i} has no valid first move! "
                f"This is the GATHER_CAPTURE_PLAN_NO_MOVE_ERROR bug. "
                f"_materialize_plans produced a plan with insufficient army."
            )


    def test_exact_error_scenario_turn64_263_to_185(self):
        """
        HYPER-SPECIFIC TEST: Disconnected tiles should raise an exception.

        Error scenario from turn 64:
        - Border pair 263->185 (friendly island 263 to target island 185)
        - Tiles: (11,14), (12,12), (12,13), (13,10), (13,11), (13,12), (14,9), (14,10), (15,9)
        - Root tile: (15,9) - island 263, 1 army
        - Capture: (15,8) - island 185 (neutral), 0 army

        THE REAL BUG: These tiles are DISCONNECTED. (11,14) is on island 199,
        while (12,12) and (12,13) are on island 269. The islands are not adjacent.
        The flow expansion selected partial tiles from disconnected islands without
        including bridge tiles, which is an upstream bug in _select_partial_gather_tiles.

        This test verifies that providing disconnected tiles to
        convert_contiguous_capture_tiles_to_gather_capture_plan raises an exception.
        We should NEVER get disconnected inputs - upstream should ensure connectivity.
        """
        # Load the exact map from the error scenario
        map_file = 'GameContinuationEntries/should_not_attempt_to_expand_a_1_to_a_neutral___6NZ3PpIvT---1--64.txtmap'
        map, general, enemy_general = self.load_map_and_generals(map_file, turn=64, fill_out_tiles=True)
        self.begin_capturing_logging()

        # Exact tiles from error log - NOTE: These are DISCONNECTED
        # (11,14) is on island 199, while (12,12) and (12,13) are on island 269
        # They are not adjacent and cannot form a contiguous gather tree
        gathing = {
            map.GetTile(11, 14),  # island 199, 2 army - NOT connected to rest!
            map.GetTile(12, 12),  # island 269, 1 army
            map.GetTile(12, 13),  # island 269, 1 army
            map.GetTile(13, 10),  # island 201, 1 army
            map.GetTile(13, 11),  # island 201, 1 army
            map.GetTile(13, 12),  # island 198, 1 army
            map.GetTile(14, 9),   # island 305, 1 army
            map.GetTile(14, 10),  # island 305, 1 army
            map.GetTile(15, 9),   # island 263, 1 army (root tile, adjacent to capture)
        }

        root_tiles = {map.GetTile(15, 9)}  # The tile adjacent to capture

        capping = {map.GetTile(15, 8)}  # island 185 (neutral), 0 army

        # Disconnected tiles should raise an exception immediately
        # We should NEVER receive disconnected inputs from upstream code
        with self.assertRaises(Exception) as context:
            GatherUtils.convert_contiguous_capture_tiles_to_gather_capture_plan(
                map,
                rootTiles=root_tiles,
                tiles=gathing,
                negativeTiles=None,
                searchingPlayer=general.player,
                priorityMatrix=None,
                useTrueValueGathered=False,
                captures=capping,
            )

        # Verify the exception mentions disconnected tiles
        self.assertIn("not fully connected", str(context.exception).lower(),
                      "Should raise exception for disconnected tiles")


if __name__ == '__main__':
    import unittest
    unittest.main()
