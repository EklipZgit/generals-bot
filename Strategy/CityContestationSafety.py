"""Safety helpers for contests against undiscovered fog-predicted cities.

Regression: Tests/test_CityGather.py
CityGatherTests.test_should_take_nearby_city_instead_of_attacking_predicted_city_through_cave
(continuation of live replay turn 163, 3VENGPUNO). At t168 the bot abandoned
the nearby neutral city (13,5) and committed a large FlowExpansion gather
through the cave corridor toward the undiscovered isTempFogPrediction city
predicted at (5,6). Every contest against such a speculative city must carry
an army reserve, and may only be entered through a "safe" approach tile that
still has alternate capture targets nearby — a lone speculative wall with no
easy alternatives must not soak a giant army.
"""

import typing
from collections import deque

from base.client.map import MapBase
from base.client.tile import Tile

PREDICTED_CITY_ARMY_RESERVE: int = 15
"""Additional army required to contest an undiscovered isTempFogPrediction city."""

_PREDICTED_CITY_SAFE_APPROACH_MAX_DEPTH: int = 3
"""BFS depth (approach tile counts as depth 0) used to find alternate targets."""

_PREDICTED_CITY_SAFE_APPROACH_MIN_TARGETS: int = 3
"""Alternate same-team nonfriendly target tiles required for an approach to be safe."""

_PREDICTED_CITY_SAFE_APPROACH_NODE_CAP: int = 25
"""Hard cap on BFS nodes visited per approach evaluation."""


def is_speculative_predicted_city(city: Tile) -> bool:
    """Return True when city is an owned city reconstructed from fog prediction.

    Speculative cities are enemy/neutral-owned tiles marked
    isTempFogPrediction that the bot has never actually seen
    (discovered=False). Known fog cities (discovered=True) and generals are
    not speculative.

    @param city: Tile to classify.
    @return: True for undiscovered isTempFogPrediction cities owned by a player.
    """
    return (city.isCity
            and city.player >= 0
            and not city.discovered
            and city.isTempFogPrediction
            and not city.isGeneral)


def get_predicted_city_army_reserve(city: Tile) -> int:
    """Return the extra army reserve required to contest city.

    @param city: Tile to evaluate.
    @return: PREDICTED_CITY_ARMY_RESERVE for speculative predicted cities, else 0.
    """
    return PREDICTED_CITY_ARMY_RESERVE if is_speculative_predicted_city(city) else 0


def _is_approachable(tile: Tile) -> bool:
    """True for tiles usable as a city approach (pathable, not obstacle/costly)."""
    return not tile.isObstacle and not tile.isNotPathable


def _is_bfs_traversable(tile: Tile) -> bool:
    """True for tiles BFS may expand through when counting alternate targets.

    Never traverses any city (the speculative city itself, known cities, or
    other undiscovered predicted cities) nor obstacles/not-pathable tiles.
    """
    return not tile.isCity and not tile.isObstacle and not tile.isNotPathable


def _counts_as_alternate_target(map: MapBase, tile: Tile, city_team: int) -> bool:
    """True when tile is a same-team nonfriendly capture target for the city contest.

    Counts ordinary enemy land even when it is undiscovered fog (normal fog
    land is still a valid alternate target), but never counts speculative
    predicted cities themselves.
    """
    if tile.player < 0:
        return False
    tile_team = map.team_ids_by_player_index[tile.player]
    if tile_team != city_team:
        return False
    if tile_team == map.team_ids_by_player_index[map.player_index]:
        return False
    return not is_speculative_predicted_city(tile)


def _count_alternate_targets_within_depth(map: MapBase, start: Tile, city_team: int) -> int:
    """BFS from start up to _PREDICTED_CITY_SAFE_APPROACH_MAX_DEPTH, counting targets.

    The start tile itself counts at depth 0. Traversal never crosses cities,
    undiscovered predicted cities, obstacles, or not-pathable tiles, and the
    search is capped at _PREDICTED_CITY_SAFE_APPROACH_NODE_CAP visited tiles.

    @param map: The (fogged) map the city contest is being evaluated on.
    @param start: Approach tile to start BFS from (counts as depth 0).
    @param city_team: Team id of the speculative city's owner.
    @return: Number of qualifying alternate target tiles found.
    """
    count = 0
    visited: typing.Set[Tile] = {start}
    queue: deque[typing.Tuple[Tile, int]] = deque([(start, 0)])
    while queue and len(visited) <= _PREDICTED_CITY_SAFE_APPROACH_NODE_CAP:
        tile, depth = queue.popleft()
        if _counts_as_alternate_target(map, tile, city_team):
            count += 1
        if depth >= _PREDICTED_CITY_SAFE_APPROACH_MAX_DEPTH:
            continue
        for nxt in tile.movable:
            if nxt in visited or not _is_bfs_traversable(nxt):
                continue
            visited.add(nxt)
            queue.append((nxt, depth + 1))
    return count


def get_safe_predicted_city_approaches(map: MapBase, city: Tile) -> set[Tile]:
    """Return the approach neighbors of city that are safe to contest through.

    For a speculative predicted city, each pathable neighbor of the city is
    evaluated as an approach: BFS to depth 3 counts same-team nonfriendly
    alternate capture targets (speculative cities excluded, never traversed).
    An approach is safe only when it still offers at least
    _PREDICTED_CITY_SAFE_APPROACH_MIN_TARGETS alternate targets, so a lone
    speculative wall cannot soak a committed army.

    For non-speculative cities every pathable approach neighbor is returned so
    known-city behavior is unchanged.

    @param map: The (fogged) map the city contest is being evaluated on.
    @param city: City tile whose approaches are evaluated.
    @return: Set of safe approach tiles adjacent to city.
    """
    pathable_approaches = {t for t in city.movable if _is_approachable(t)}
    if not is_speculative_predicted_city(city):
        return pathable_approaches

    city_team = map.team_ids_by_player_index[city.player]
    safe: set[Tile] = set()
    for approach in pathable_approaches:
        target_count = _count_alternate_targets_within_depth(map, approach, city_team)
        if target_count >= _PREDICTED_CITY_SAFE_APPROACH_MIN_TARGETS:
            safe.add(approach)
    return safe
