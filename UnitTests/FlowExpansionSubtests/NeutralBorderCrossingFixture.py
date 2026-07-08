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
    # Mirror TestBase.run_army_flow_expansion (used by the source
    # test_builds_flow_plan_gathering_through_neutral_border_crossings) exactly: the
    # tile-island size must be passed via the constructor's averageTileIslandSize (=5),
    # not set on desired_tile_island_size afterward, or the islands group differently
    # and the flow graph produces tiny 1-turn options instead of the 5-turn neutral crossing.
    builder = TileIslandBuilder(map, analysis.intergeneral_analysis, averageTileIslandSize=5)
    builder.recalculate_tile_islands(enemy_general)

    expander = ArmyFlowExpanderV2(map)
    expander.method = FlowGraphMethod.OrToolsSimpleMinCost
    expander.friendlyGeneral = general
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


# Column x=2 is the neutral-border-crossing corridor the plan must pull army down through:
#   friendly a3 (2,0) -> neutral (2,1) -> neutral (2,2) -> enemy b2 (2,3) -> enemy b2 (2,4) -> enemy b2 (2,5)
# The friendly a2 tiles at (3,1) and (3,2) must be pulled sideways into the corridor to fund the captures.
CROSSING_SOURCE_TILE: tuple[int, int] = (2, 0)
CROSSING_FIRST_NEUTRAL_TILE: tuple[int, int] = (2, 1)
CROSSING_CORRIDOR_TILES: tuple[tuple[int, int], ...] = ((2, 1), (2, 2), (2, 3), (2, 4))
CROSSING_ENEMY_TILES: tuple[tuple[int, int], ...] = ((2, 3), (2, 4))
CROSSING_SIDE_GATHER_TILES: tuple[tuple[int, int], ...] = ((3, 1), (3, 2))


def tile_coords(tiles) -> set[tuple[int, int]]:
    """Return the set of (x, y) coordinates for an iterable of tiles."""
    return {(tile.x, tile.y) for tile in tiles}


def get_island_id_for_coord(scenario: NeutralBorderCrossingScenario, coord: tuple[int, int]) -> int:
    """Return the tile-island unique_id that owns the tile at the given (x, y) coordinate."""
    tile = scenario.map.GetTile(coord[0], coord[1])
    return scenario.builder.tile_island_lookup.raw[tile.tile_index].unique_id


def find_crossing_border_pair(scenario: NeutralBorderCrossingScenario) -> object:
    """Return the border pair that seeds the x=2 corridor: friendly (2,0) -> neutral (2,1).

    This is the border pair whose gather/capture streams must pull army down through the
    neutral crossing into the enemy b2 stack.
    """
    source_island_id = get_island_id_for_coord(scenario, CROSSING_SOURCE_TILE)
    first_neutral_island_id = get_island_id_for_coord(scenario, CROSSING_FIRST_NEUTRAL_TILE)
    matches = [
        border_pair for border_pair in scenario.border_pairs
        if border_pair.friendly_island_id == source_island_id
        and border_pair.target_island_id == first_neutral_island_id
    ]
    scenario.test_case.assertEqual(
        1, len(matches),
        f'Expected exactly one border pair from friendly {CROSSING_SOURCE_TILE} '
        f'(island {source_island_id}) to neutral {CROSSING_FIRST_NEUTRAL_TILE} '
        f'(island {first_neutral_island_id})',
    )
    return matches[0]


def target_entry_coords(entry) -> set[tuple[int, int]]:
    """Return the (x, y) coordinates of every tile captured by a capture FlowTurnsEntry."""
    coords: set[tuple[int, int]] = set()
    for node in entry.included_target_flow_nodes:
        coords.update(tile_coords(node.island.tile_set))
    return coords


def gather_entry_coords(entry) -> set[tuple[int, int]]:
    """Return the (x, y) coordinates of every friendly tile in a gather FlowTurnsEntry."""
    coords: set[tuple[int, int]] = set()
    for node in entry.included_friendly_flow_nodes:
        coords.update(tile_coords(node.island.tile_set))
    return coords


def assert_captures_enemy_corridor(test_case: object, captured_coords: set[tuple[int, int]]) -> None:
    """Assert that the given captured coordinates include the enemy tiles down column x=2."""
    for enemy_coord in CROSSING_ENEMY_TILES:
        test_case.assertIn(
            enemy_coord, captured_coords,
            f'Expected the plan to capture enemy tile {enemy_coord} by pulling army down the x=2 '
            f'neutral corridor. Captured coords: {sorted(captured_coords)}',
        )


def assert_has_enemy_capture_option(test_case: object, options: list, enemy_player: int) -> object:
    """Assert the final option set contains the five-turn plan pulling army down the x=2 corridor.

    This encodes the desired behaviour of
    test_builds_flow_plan_gathering_through_neutral_border_crossings: exactly one option captures
    enemy tiles, it is five turns long, has meaningful econ value, pulls army down the neutral
    corridor (2,1)->(2,4), and pulls the side a2 tiles at (3,1)/(3,2) in to fund the captures.
    """
    test_case.assertNotEqual(0, len(options))
    options_with_captures = SearchUtils.where(
        options,
        lambda option: SearchUtils.any_where(option.tileSet, lambda tile: tile.player == enemy_player),
    )
    test_case.assertEqual(1, len(options_with_captures))
    option = options_with_captures[0]
    test_case.assertEqual(5, option.length)
    test_case.assertGreater(option.econValue, 0.8)

    plan_coords = tile_coords(option.tileSet)
    assert_captures_enemy_corridor(test_case, plan_coords)
    for corridor_coord in CROSSING_CORRIDOR_TILES:
        test_case.assertIn(
            corridor_coord, plan_coords,
            f'Expected the plan to traverse the full x=2 corridor tile {corridor_coord}. '
            f'Plan coords: {sorted(plan_coords)}',
        )
    for side_coord in CROSSING_SIDE_GATHER_TILES:
        test_case.assertIn(
            side_coord, plan_coords,
            f'Expected the plan to pull the side a2 tile {side_coord} into the corridor gather. '
            f'Plan coords: {sorted(plan_coords)}',
        )
    return option
