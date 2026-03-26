from __future__ import annotations

import typing
from collections import deque

from Path import Path
from base.client.map import MapBase, Tile


class _SearchNode(object):
    __slots__ = (
        'tile_index',
        'parent_node_index',
        'dist',
        'origin_tile_index',
        'enemy_count',
        'last_enemy_parent_node_index',
        'max_enemy_depth',
    )

    def __init__(
            self,
            tile_index: int,
            parent_node_index: int,
            dist: int,
            origin_tile_index: int,
            enemy_count: int,
            last_enemy_parent_node_index: int,
            max_enemy_depth: int,
    ):
        self.tile_index: int = tile_index
        self.parent_node_index: int = parent_node_index
        self.dist: int = dist
        self.origin_tile_index: int = origin_tile_index
        self.enemy_count: int = enemy_count
        self.last_enemy_parent_node_index: int = last_enemy_parent_node_index
        self.max_enemy_depth: int = max_enemy_depth


class _CandidatePath(object):
    __slots__ = (
        'origin',
        'path',
        'enemy_tile_indices',
        'max_enemy_depth',
    )

    def __init__(self, origin: Tile, path: Path, enemy_tile_indices: typing.List[int], max_enemy_depth: int):
        self.origin: Tile = origin
        self.path: Path = path
        self.enemy_tile_indices: typing.List[int] = enemy_tile_indices
        self.max_enemy_depth: int = max_enemy_depth


def find_city_expansion_paths(map: MapBase, searching_player: int = -2, max_range: int = 15) -> typing.Dict[Tile, typing.List[Path]]:
    if searching_player == -2:
        searching_player = map.player_index

    start_tiles = _get_city_expansion_starts(map, searching_player)
    results: typing.Dict[Tile, typing.List[Path]] = {start: [] for start in start_tiles}
    if not start_tiles or max_range <= 0:
        return results

    enemy_depths = _build_enemy_territory_depths(map, searching_player)
    candidates = _find_candidate_paths(map, searching_player, start_tiles, enemy_depths, max_range)

    claimed_enemy_tile_indices: typing.Set[int] = set()
    selected_origins: typing.Set[Tile] = set()
    for candidate in sorted(candidates, key=_candidate_sort_key):
        if candidate.origin in selected_origins:
            continue
        unique_enemy_tile_indices = [tile_index for tile_index in candidate.enemy_tile_indices if tile_index not in claimed_enemy_tile_indices]
        if not unique_enemy_tile_indices:
            continue

        claimed_enemy_tile_indices.update(unique_enemy_tile_indices)
        candidate.path.econValue = float(len(unique_enemy_tile_indices))
        candidate.path.value = len(unique_enemy_tile_indices)
        results[candidate.origin].append(candidate.path)
        selected_origins.add(candidate.origin)

    return results


def _get_city_expansion_starts(map: MapBase, searching_player: int) -> typing.List[Tile]:
    player = map.players[searching_player]
    starts: typing.List[Tile] = []
    if player.general is not None:
        starts.append(player.general)
    for city in player.cities:
        if city is not None and city is not player.general:
            starts.append(city)
    return starts


def _is_enemy_tile(map: MapBase, searching_player: int, tile: Tile) -> bool:
    return tile.player >= 0 and not map.is_player_on_team_with(searching_player, tile.player)


def _is_blocked(tile: Tile) -> bool:
    return tile.isMountain or tile.isUndiscoveredObstacle or tile.isCostlyNeutral


def _build_enemy_territory_depths(map: MapBase, searching_player: int) -> typing.List[int]:
    depths = [-1] * (map.rows * map.cols)
    enemy_tiles = [tile for tile in map.pathable_tiles if _is_enemy_tile(map, searching_player, tile)]
    if not enemy_tiles:
        return depths

    queue = deque()
    for tile in enemy_tiles:
        is_boundary = False
        for adj in tile.movable:
            if _is_blocked(adj) or not _is_enemy_tile(map, searching_player, adj):
                is_boundary = True
                break
        if is_boundary:
            depths[tile.tile_index] = 0
            queue.append(tile)

    if not queue:
        for tile in enemy_tiles:
            depths[tile.tile_index] = 0
            queue.append(tile)

    while queue:
        current = queue.popleft()
        next_depth = depths[current.tile_index] + 1
        for adj in current.movable:
            if _is_blocked(adj) or not _is_enemy_tile(map, searching_player, adj):
                continue
            if depths[adj.tile_index] != -1:
                continue
            depths[adj.tile_index] = next_depth
            queue.append(adj)

    return depths


def _find_candidate_paths(
        map: MapBase,
        searching_player: int,
        start_tiles: typing.List[Tile],
        enemy_depths: typing.List[int],
        max_range: int,
) -> typing.List[_CandidatePath]:
    queue = deque()
    best_branch_metric: typing.Dict[typing.Tuple[int, int], typing.Tuple[int, int, int]] = {}
    best_candidate_metric: typing.Dict[typing.Tuple[int, int], typing.Tuple[int, int, int]] = {}
    candidates_by_key: typing.Dict[typing.Tuple[int, int], _CandidatePath] = {}
    search_nodes: typing.List[_SearchNode] = []

    for start in start_tiles:
        node_index = len(search_nodes)
        search_nodes.append(_SearchNode(start.tile_index, -1, 0, start.tile_index, 0, -1, -1))
        queue.append(node_index)
        best_branch_metric[(start.tile_index, start.tile_index)] = (0, 0, 0)

    while queue:
        node_index = queue.popleft()
        node = search_nodes[node_index]
        if node.dist >= max_range:
            continue

        current_tile = map.tiles_by_index[node.tile_index]
        origin_tile = map.tiles_by_index[node.origin_tile_index]
        for next_tile in current_tile.movable:
            if _is_blocked(next_tile):
                continue
            next_tile_index = next_tile.tile_index
            if _path_contains_tile_index(search_nodes, node_index, next_tile_index):
                continue

            enemy_count = node.enemy_count
            last_enemy_parent_node_index = node.last_enemy_parent_node_index
            max_enemy_depth = node.max_enemy_depth
            if _is_enemy_tile(map, searching_player, next_tile):
                enemy_count += 1
                last_enemy_parent_node_index = node_index
                max_enemy_depth = max(max_enemy_depth, enemy_depths[next_tile_index])

            next_node_index = len(search_nodes)
            search_nodes.append(_SearchNode(
                tile_index=next_tile_index,
                parent_node_index=node_index,
                dist=node.dist + 1,
                origin_tile_index=node.origin_tile_index,
                enemy_count=enemy_count,
                last_enemy_parent_node_index=last_enemy_parent_node_index,
                max_enemy_depth=max_enemy_depth,
            ))

            next_node = search_nodes[next_node_index]
            branch_metric = _get_branch_metric(next_node)
            branch_key = (node.origin_tile_index, next_tile_index)
            current_branch_metric = best_branch_metric.get(branch_key)
            if current_branch_metric is not None and branch_metric >= current_branch_metric:
                continue
            best_branch_metric[branch_key] = branch_metric
            queue.append(next_node_index)

            if enemy_count == 0:
                continue

            candidate_key = (node.origin_tile_index, next_tile_index)
            current_candidate_metric = best_candidate_metric.get(candidate_key)
            if current_candidate_metric is not None and branch_metric >= current_candidate_metric:
                continue

            path = _build_path_from_node(map, search_nodes, next_node_index)
            best_candidate_metric[candidate_key] = branch_metric
            candidates_by_key[candidate_key] = _CandidatePath(origin_tile, path, _build_enemy_tile_indices(search_nodes, next_node_index), max_enemy_depth)

    return list(candidates_by_key.values())


def _path_contains_tile_index(search_nodes: typing.List[_SearchNode], node_index: int, tile_index: int) -> bool:
    while node_index != -1:
        node = search_nodes[node_index]
        if node.tile_index == tile_index:
            return True
        node_index = node.parent_node_index
    return False


def _build_path_from_node(map: MapBase, search_nodes: typing.List[_SearchNode], node_index: int) -> Path:
    tile_indices: typing.List[int] = []
    while node_index != -1:
        node = search_nodes[node_index]
        tile_indices.append(node.tile_index)
        node_index = node.parent_node_index
    tile_indices.reverse()

    path = Path()
    for tile_index in tile_indices:
        path.add_next(map.tiles_by_index[tile_index])
    return path


def _build_enemy_tile_indices(search_nodes: typing.List[_SearchNode], node_index: int) -> typing.List[int]:
    enemy_tile_indices: typing.List[int] = []
    while node_index != -1:
        node = search_nodes[node_index]
        if node.enemy_count > len(enemy_tile_indices):
            enemy_tile_indices.append(node.tile_index)
        node_index = node.last_enemy_parent_node_index
    enemy_tile_indices.reverse()
    return enemy_tile_indices


def _get_branch_metric(branch: _SearchNode) -> typing.Tuple[int, int, int]:
    return branch.dist, 0 - branch.max_enemy_depth, 0 - branch.enemy_count


def _candidate_sort_key(candidate: _CandidatePath) -> typing.Tuple[int, int, int, int, int, int]:
    return (
        0 - candidate.max_enemy_depth,
        candidate.path.length,
        0 - len(candidate.enemy_tile_indices),
        candidate.origin.tile_index,
        candidate.path.tail.tile.tile_index,
        candidate.path.start.tile.tile_index,
    )
