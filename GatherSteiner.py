import time
import typing

import networkx as nx

import logbook
from pcst_fast import pcst_fast

from MapMatrix import MapMatrix, MapMatrixSet
from base.client.map import MapBase, Tile


def build_network_x_steiner_tree(
        map: MapBase,
        includingTiles: typing.Iterable[Tile],
        searchingPlayer=-2,
        weightMod: MapMatrix[float] | None = None,
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None
) -> typing.List[Tile]:
    # bannedTiles = None
    start = time.perf_counter()
    g = build_networkX_graph(map, weightMod, baseWeight, bannedTiles=bannedTiles)

    terminalNodes = [map.get_tile_index(t) for t in includingTiles]
    steinerTree: nx.Graph = nx.algorithms.approximation.steiner_tree(g, terminal_nodes=terminalNodes, method='mehlhorn')  # kou or mehlhorn. kou is just bad...?
    # steinerTree: nx.Graph = nx.algorithms.approximation.steiner_tree(g, terminal_nodes=terminalNodes)

    nodes = [map.get_tile_by_tile_index(n) for n in steinerTree.nodes]

    complete = time.perf_counter() - start

    logbook.info(f'networkX steiner calculated {len(nodes)} node subtree in {complete:.5f}s')

    return nodes


def plot_mst(g: nx.Graph):
    import matplotlib.pyplot as plt
    # Find the minimum spanning tree
    T = nx.minimum_spanning_tree(g)

    # Visualize the graph and the minimum spanning tree
    pos = nx.spring_layout(g)
    nx.draw_networkx_nodes(g, pos, node_color="lightblue", node_size=500)
    nx.draw_networkx_edges(g, pos, edge_color="grey")
    nx.draw_networkx_labels(g, pos, font_size=12, font_family="sans-serif")
    nx.draw_networkx_edge_labels(
        g, pos, edge_labels={(u, v): d["weight"] for u, v, d in g.edges(data=True)}
    )
    nx.draw_networkx_edges(T, pos, edge_color="green", width=2)
    plt.axis("off")
    plt.show()


def build_networkX_graph(
        map: MapBase,
        weightMod: MapMatrix[float] | None = None,
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None
) -> nx.Graph:
    def _tree_edges() -> typing.Generator[typing.Tuple[int, int, typing.Dict[str, typing.Any]], None, None]:
        for tileIndex in range(map.cols * map.rows):
            tile = map.get_tile_by_tile_index(tileIndex)

            if tile.isMountain:
                continue
            # if tile.isObstacle:
            #     continue

            fromWeight = baseWeight
            if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
                fromWeight += baseWeight * 1000

            if weightMod:
                fromWeight -= weightMod[tile]

            right = map.GetTile(tile.x + 1, tile.y)
            down = map.GetTile(tile.x, tile.y + 1)
            if right and not right.isObstacle:
                weight = fromWeight
                if right.isObstacle or (bannedTiles is not None and right in bannedTiles):
                    weight += baseWeight * 1000

                if weightMod:
                    weight -= weightMod[right]

                yield tileIndex, map.get_tile_index(right), {"weight": weight}
            if down and not down.isObstacle:
                weight = fromWeight
                if down.isObstacle or (bannedTiles is not None and down in bannedTiles):
                    weight += baseWeight * 1000

                if weightMod:
                    weight -= weightMod[down]

                yield tileIndex, map.get_tile_index(down), {"weight": weight}

    g = nx.Graph(_tree_edges())
    return g


def build_prize_collecting_steiner_tree(
        map: MapBase,
        searchingPlayer=-2,
        toTile: Tile | None = None
) -> MapMatrixSet:
    """
    Does black magic and shits out a spiderweb with numbers in it, sometimes the numbers are even right

    @param map:
    startTiles is list of tiles that will be weighted with baseCaseFunc, OR dict (startPriorityObject, distance) = startTiles[tile]
    valueFunc is (currentTile, priorityObject) -> POSITIVELY weighted value object
    @param searchingPlayer:
    priorityFunc is (nextTile, currentPriorityobject) -> nextPriorityObject NEGATIVELY weighted
    @return:
    """

    """
    The pcst_fast package contains the following function:

    vertices, edges = pcst_fast(edges, prizes, costs, root, num_clusters, pruning, verbosity_level)
    The parameters are:

    edges: a 2D int64 array. Each row (of length 2) specifies an undirected edge in the input graph. The nodes are labeled 0 to n-1, where n is the number of nodes.
    prizes: the node prizes as a 1D float64 array.
    costs: the edge costs as a 1D float64 array.
    root: the root note for rooted PCST. For the unrooted variant, this parameter should be -1.
    num_clusters: the number of connected components in the output.
    pruning: a string value indicating the pruning method. Possible values are 'none', 'simple', 'gw', and 'strong' (all literals are case-insensitive). 'none' and 'simple' return intermediate stages of the algorithm and do not have approximation guarantees. They are only intended for development. The standard GW pruning method is 'gw', which is also the default. 'strong' uses "strong pruning", which was introduced in [JMP00]. It has the same theoretical guarantees as GW pruning but better empirical performance in some cases. For the PCSF problem, the output of strong pruning is at least as good as the output of GW pruning.
    verbosity_level: an integer indicating how much debug output the function should produce.
    The output variables are:

    vertices: the vertices in the solution as a 1D int64 array.
    edges: the edges in the output as a 1D int64 array. The list contains indices into the list of edges passed into the function.
    """

    start = time.perf_counter()

    edges = []
    """ edges: a 2D int64 array. Each row (of length 2) specifies an undirected edge in the input graph. The nodes are labeled 0 to n-1, where n is the number of nodes."""
    prizes = []
    """ prizes: the node prizes as a 1D float64 array."""
    costs = []
    """ costs: the edge costs as a 1D float64 array."""
    root = -1  # or a node # if we want to root somewhere specific
    if toTile is not None:
        root = map.get_tile_index(toTile)
    """ root: the root note for rooted PCST. For the unrooted variant, this parameter should be -1."""
    num_clusters = 1  # we want exactly one subtree...?
    """ num_clusters: the number of connected components in the output."""

    pruning = 'strong'
    """ pruning: a string value indicating the pruning method. 
    Possible values are 'none', 'simple', 'gw', and 'strong' (all literals are case-insensitive). 
    'none' and 'simple' return intermediate stages of the algorithm and do not have approximation guarantees. They are only intended for development. 
    The standard GW pruning method is 'gw', which is also the default. 
    'strong' uses "strong pruning", which was introduced in [JMP00]. It has the same theoretical guarantees as GW pruning but better empirical performance in some cases. 
    For the PCSF problem, the output of strong pruning is at least as good as the output of GW pruning."""

    verbosity_level = 0
    """ verbosity_level: an integer indicating how much debug output the function should produce."""

    for tileIndex in range(map.cols * map.rows):
        tile = map.get_tile_by_tile_index(tileIndex)

        prize = 0
        extraCost = 0
        if map.is_tile_on_team_with(tile, searchingPlayer):
            prize = float(tile.army)
        else:
            # prize = float(0 - tile.army)
            extraCost = tile.army

        prizes.append(prize)

        if tile.isObstacle:
            continue

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        if right and not right.isObstacle:
            edges.append([tileIndex, right.tile_index])
            costs.append(2.0 + extraCost)
        if down and not down.isObstacle:
            edges.append([tileIndex, down.tile_index])
            costs.append(2.0 + extraCost)

    vertices, edges = pcst_fast(edges, prizes, costs, root, num_clusters, pruning, verbosity_level)

    outTiles = [map.get_tile_by_tile_index(v) for v in vertices]

    outMatrix = MapMatrixSet(map, outTiles)
    logbook.info(f'pcst took {time.perf_counter() - start:.5f}s, output {len(outTiles)} nodes')

    # ???
    return outMatrix