import time
import typing

import logbook
import networkx as nx

from Path import Path
from base.client.map import MapBase
from base.client.tile import Tile


def solve_tsp_path_nx_raw(map: MapBase, nxGraph: nx.Graph, toReach: typing.Iterable[Tile], startTile: Tile | None = None, returnToStart: bool = False) -> typing.List[int] | None:
    start = time.perf_counter()

    # method=nx.approximation.christofides
    method = nx.approximation.greedy_tsp
    # method=nx.approximation.simulated_annealing_tsp
    # method=nx.approximation.threshold_accepting_tsp
    # method=nx.approximation.asadpour_atsp  # NOT IMPLEMENTED FOR UNDIRECTED

    nodes = []
    if startTile:
        nodes.append(startTile.tile_index)
    nodes.extend(t.tile_index for t in toReach)

    # hack in a 0-weight edge from the start tile to all other tiles, so that our final 'cycle closure' is really just jumping back to the start.
    addedEdges = []
    if startTile and not returnToStart:
        for tile in toReach:
            if tile is startTile:
                continue

            if nxGraph.has_edge(startTile.tile_index, tile.tile_index):
                continue

            nxGraph.add_edge(startTile.tile_index, tile.tile_index, weight=map.get_distance_between(startTile, tile))
            addedEdges.append((startTile.tile_index, tile.tile_index))

    tspTiles = nx.approximation.traveling_salesman_problem(nxGraph, cycle=True, method=method, nodes=nodes)

    # UN-hack in a 0-weight edge from the start tile to all other tiles, so that our final 'cycle closure' is really just jumping back to the start.

    for edgeStart, edgeEnd in addedEdges:
        nxGraph.remove_edge(edgeStart, edgeEnd)

    if startTile:
        tspTiles = correct_tsp_output_to_start_tile_raw(map, nxGraph, tspTiles, startTile)

    logbook.info(f' tsp calced {len(tspTiles) - 1} path in {time.perf_counter() - start:.4f}s. Returned {" -> ".join(str(map.get_tile_by_tile_index(t)) for t in tspTiles)}')
    if not tspTiles:
        return None

    return tspTiles


def correct_tsp_output_to_start_tile_raw(map: MapBase, nxGraph: nx.Graph, tspTiles: typing.List[int], startTile: Tile):
    startIdx = -1
    for i, t in enumerate(tspTiles):
        tile = map.get_tile_by_tile_index(t)
        if tile == startTile:
            startIdx = i
            break

    startPrevIdx = startIdx - 1
    startNextIdx = startIdx + 1
    if startNextIdx == len(tspTiles):
        startNextIdx = 0
    if startPrevIdx == -1:
        startPrevIdx = len(tspTiles) - 1

    tspOutput: typing.List[int]
    if nxGraph.has_edge(tspTiles[startPrevIdx], tspTiles[startIdx]):
        if nxGraph.has_edge(tspTiles[startIdx], tspTiles[startNextIdx]):
            raise AssertionError(f'Start tile was ACTUALLY connected to both next and previous...? ')
        tspOutput = tspTiles[startIdx::-1] + tspTiles[:startIdx:-1]
    elif nxGraph.has_edge(tspTiles[startIdx], tspTiles[startNextIdx]):
        tspOutput = tspTiles[startIdx:] + tspTiles[:startIdx]
    else:
        raise AssertionError(f'Could not find start point in tsp tile list...?')

    return tspOutput


def solve_tsp_path_nx(map: MapBase, nxGraph: nx.Graph, toReach: typing.Iterable[Tile], startTile: Tile | None = None, returnToStart: bool = False) -> Path | None:
    tspTiles = solve_tsp_path_nx_raw(map, nxGraph, toReach, startTile, returnToStart)

    if not tspTiles:
        return None

    path = Path()
    for t in tspTiles:
        path.add_next(t)

    # if startTile:
    #     path.calculate_value()

    return path
