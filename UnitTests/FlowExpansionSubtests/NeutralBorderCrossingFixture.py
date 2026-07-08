from dataclasses import dataclass

import SearchUtils
from Algorithms import TileIslandBuilder
from BehaviorAlgorithms.FlowExpansion import ArmyFlowExpanderV2
from BehaviorAlgorithms.IterativeExpansion import FlowGraphMethod
from BoardAnalyzer import BoardAnalyzer
from base.client.map import MapBase
from base.client.tile import Tile


@dataclass(slots=True)
class NeutralBorderCrossingScenario:
    test_case: object
    map: MapBase
    general: Tile
    enemy_general: Tile
    analysis: BoardAnalyzer
    builder: TileIslandBuilder
    expander: ArmyFlowExpanderV2
    target_crossable: set[int]
    border_pairs: list
    lookup_tables: list


def get_neutral_border_crossing_map_data() -> str:
    """Return the neutral-border-crossing regression fixture map data.

    Built from an explicit newline-joined list of rows so that the exact
    trailing whitespace (which the map parser depends on for column widths)
    is preserved byte-for-byte from the original
    test_builds_flow_plan_gathering_through_neutral_border_crossings fixture.
    """
    rows = [
        "",
        "|    |    |    |    |    |    |",
        "aG1       a3   a3   M    M    M",
        "     M         a2   M    M    M",
        "     M         a2   M    M    M",
        "     M    b2   M    b2   b2   ",
        "     M    b2   M    b2   M     ",
        "     M    b2   b2   b2   M   ",
        "     M    M    M    M    M",
        "                              bG1",
        "|    |    |    |    |",
        "        ",
    ]
    return "\n".join(rows)


def build_neutral_border_crossing_scenario(test_case: object, turns: int = 5) -> NeutralBorderCrossingScenario:
    """Build the shared neutral-border-crossing scenario through lookup generation."""
    map, general, enemy_general = test_case.load_map_and_generals_from_string(
        get_neutral_border_crossing_map_data(),
        102,
    )
    test_case.begin_capturing_logging()

    analysis = BoardAnalyzer(map, general)
    analysis.rebuild_intergeneral_analysis(enemy_general, possibleSpawns=None)
    builder = TileIslandBuilder(map, analysis.intergeneral_analysis)
    builder.desired_tile_island_size = 5
    builder.recalculate_tile_islands(enemy_general)

    expander = ArmyFlowExpanderV2(map)
    expander.method = FlowGraphMethod.OrToolsSimpleMinCost
    expander.target_team = map.team_ids_by_player_index[enemy_general.player]
    expander.enemyGeneral = enemy_general
    expander.island_builder = builder
    expander._ensure_flow_graph_exists(builder, turns=turns)

    target_crossable = expander._detect_target_crossable_friendly_islands(
        builder,
        expander.flow_graph,
        expander.team,
        expander.target_team,
    )
    border_pairs = expander._enumerate_border_pairs(
        expander.flow_graph,
        builder,
        expander.team,
        expander.target_team,
        target_crossable,
    )
    lookup_tables = expander._process_flow_into_flow_army_turns(
        border_pairs,
        expander.flow_graph,
        target_crossable,
        turns,
    )

    return NeutralBorderCrossingScenario(
        test_case=test_case,
        map=map,
        general=general,
        enemy_general=enemy_general,
        analysis=analysis,
        builder=builder,
        expander=expander,
        target_crossable=target_crossable,
        border_pairs=border_pairs,
        lookup_tables=lookup_tables,
    )


def assert_has_enemy_capture_option(test_case: object, options: list, enemy_player: int) -> object:
    """Assert the final option set contains the five-turn enemy-capturing plan."""
    test_case.assertNotEqual(0, len(options))
    options_with_captures = SearchUtils.where(
        options,
        lambda option: SearchUtils.any_where(option.tileSet, lambda tile: tile.player == enemy_player),
    )
    test_case.assertEqual(1, len(options_with_captures))
    option = options_with_captures[0]
    test_case.assertEqual(5, option.length)
    test_case.assertGreater(option.econValue, 0.8)
    return option
