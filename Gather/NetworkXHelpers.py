import time
import typing

import logbook
import networkx as nx

from Gather import GatherDebug
from Interfaces import MapMatrixInterface
from ViewInfo import ViewInfo
from base.client.map import MapBase
from base.client.tile import Tile


def build_networkX_graph_no_obstacles_no_weights(
        map: MapBase,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None
) -> nx.Graph:
    """
    Uses a base weight and then subtracts the value from the 'weightModeMatrix' for creating the edge weights between tiles.

    @param map:
    @param bannedTiles:
    @param validTiles:
    @return:
    """
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    for tile in validTiles:
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            continue

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and right in validTiles:
            if not right.isObstacle and (not bannedTiles or right not in bannedTiles):
                g.add_edge(tileIndex, right.tile_index)
        if down and down in validTiles:
            if not down.isObstacle and (not bannedTiles or down not in bannedTiles):
                g.add_edge(tileIndex, down.tile_index)

    nextTime = time.perf_counter()
    logbook.info(f'networkX basic graph itself built in {1000.0 * (nextTime - start):.2f}ms')
    return g


def build_networkX_graph_flat_weight_mod_subtract(
        map: MapBase,
        weightModMatrix: MapMatrixInterface[float],
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None,
        viewInfo: ViewInfo | None = None
) -> nx.Graph:
    """
    Uses a base weight and then subtracts the value from the 'weightModeMatrix' for creating the edge weights between tiles.

    @param map:
    @param weightModMatrix:
    @param baseWeight:
    @param bannedTiles:
    @param validTiles:
    @return:
    """
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    for tile in validTiles:
        fromWeight = baseWeight
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            fromWeight += baseWeight * 1000

        fromWeight -= weightModMatrix.raw[tile.tile_index]

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and right in validTiles:
            weight = fromWeight
            if right.isObstacle or (bannedTiles and right in bannedTiles):
                weight += baseWeight * 1000

            weight -= weightModMatrix.raw[right.tile_index]

            g.add_edge(tileIndex, right.tile_index, weight=weight)
            if viewInfo:
                viewInfo.bottomMidRightGridText.raw[tileIndex] = f'{weight:.2f}'.lstrip('0')
        if down and down in validTiles:
            weight = fromWeight
            if down.isObstacle or (bannedTiles and down in bannedTiles):
                weight += baseWeight * 1000

            weight -= weightModMatrix.raw[down.tile_index]

            g.add_edge(tileIndex, down.tile_index, weight=weight)
            if viewInfo:
                viewInfo.bottomLeftGridText.raw[tileIndex] = f'{weight:.2f}'.lstrip('0')

    nextTime = time.perf_counter()
    logbook.info(f'networkX weight graph itself built in {nextTime - start:.5f}s')
    return g


def build_networkX_graph_flat_weight_mod_divide_min_offset(
        map: MapBase,
        weightModMatrix: MapMatrixInterface[float],
        baseOffset: float = 0,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None,
        viewInfo: ViewInfo | None = None
) -> nx.Graph:
    """
    Divides 1 over the offset adjusted value of the two tiles crossed via edges, plus baseWeight.
    So with baseOffset 3, and tileA value 10 and tileB value -5, when the min value is -10 and the max value is 100 would result in:
    offset = (-minValue) = +10
    1 / (3 + (10 + 10) + (-5 + 10))
    =
    1/28

    In the same setup,
    C val 30 and D val 20 would be
    1 / (3 + 40 + 30) or 1/73

    @param map:
    @param weightModMatrix:
    @param baseOffset:
    @param bannedTiles:
    @param validTiles:
    @param viewInfo: if provided, will update the viewInfo with the connection values.
    @return:
    """
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    # maxW = max(weightModMatrix.raw[t.tile_index] for t in validTiles)
    minW = min(weightModMatrix.raw[t.tile_index] for t in validTiles)
    offset = -minW
    logbook.info(f'minW was {minW:.3f}')

    for tile in validTiles:
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            continue
        fromWeight = baseOffset

        fromWeight += weightModMatrix.raw[tile.tile_index] + offset

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and right in validTiles:
            weight = fromWeight
            if not right.isObstacle and (not bannedTiles or right not in bannedTiles):
                weight += weightModMatrix.raw[right.tile_index] + offset
                if weight <= 0.0:
                    weight = 0.0000000001
                divided = 1/weight
                g.add_edge(tileIndex, right.tile_index, weight=divided)
                if viewInfo:
                    viewInfo.bottomMidRightGridText.raw[tileIndex] = f'{divided:.3f}'.lstrip('0')
        if down and down in validTiles:
            weight = fromWeight
            if not down.isObstacle and (not bannedTiles or down not in bannedTiles):
                weight += weightModMatrix.raw[down.tile_index] + offset
                if weight <= 0.0:
                    weight = 0.0000000001
                divided = 1/weight
                g.add_edge(tileIndex, down.tile_index, weight=divided)
                if viewInfo:
                    viewInfo.bottomLeftGridText.raw[tileIndex] = f'{divided:.3f}'.lstrip('0')

    nextTime = time.perf_counter()
    logbook.info(f'networkX weight divis graph itself built in {nextTime - start:.5f}s')
    return g



def build_networkX_graph_flat_weight_mod_divide_min_offset_squared(
        map: MapBase,
        weightModMatrix: MapMatrixInterface[float],
        baseOffset: float = 0,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None,
        viewInfo: ViewInfo | None = None
) -> nx.Graph:
    """
    Divides 1 over the offset adjusted value of the two tiles crossed via edges, plus baseWeight.
    So with baseOffset 3, and tileA value 10 and tileB value -5, when the min value is -10 and the max value is 100 would result in:
    offset = (-minValue) = +10
    1 / (3 + (10 + 10) + (-5 + 10))
    =
    1/28

    In the same setup,
    C val 30 and D val 20 would be
    1 / (3 + 40 + 30) or 1/73

    @param map:
    @param weightModMatrix:
    @param baseOffset:
    @param bannedTiles:
    @param validTiles:
    @param viewInfo: if provided, will update the viewInfo with the connection values.
    @return:
    """
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    # maxW = max(weightModMatrix.raw[t.tile_index] for t in validTiles)
    minW = min(weightModMatrix.raw[t.tile_index] for t in validTiles)
    offset = -minW
    logbook.info(f'minW was {minW:.3f}')

    for tile in validTiles:
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            continue
        fromWeight = baseOffset

        fromWeight += weightModMatrix.raw[tile.tile_index] + offset

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and right in validTiles:
            weight = fromWeight
            if not right.isObstacle and (not bannedTiles or right not in bannedTiles):
                weight += weightModMatrix.raw[right.tile_index] + offset
                if weight <= 0.0:
                    weight = 0.0000001
                divided = 1000/weight/weight
                g.add_edge(tileIndex, right.tile_index, weight=divided)
                if viewInfo:
                    viewInfo.bottomMidRightGridText.raw[tileIndex] = f'{divided:.3f}'.lstrip('0')
        if down and down in validTiles:
            weight = fromWeight
            if not down.isObstacle and (not bannedTiles or down not in bannedTiles):
                weight += weightModMatrix.raw[down.tile_index] + offset
                if weight <= 0.0:
                    weight = 0.0000001
                divided = 1000/weight/weight
                g.add_edge(tileIndex, down.tile_index, weight=divided)
                if viewInfo:
                    viewInfo.bottomLeftGridText.raw[tileIndex] = f'{divided:.3f}'.lstrip('0')

    nextTime = time.perf_counter()
    logbook.info(f'networkX weight divis graph itself built in {nextTime - start:.5f}s')
    return g


def build_networkX_graph_flat_weight_mod_divide_neg_scale(
        map: MapBase,
        weightModMatrix: MapMatrixInterface[float],
        baseOffset: float = 0,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None,
        viewInfo: ViewInfo | None = None
) -> nx.Graph:
    """
    Divides 1 over the offset adjusted value of the two tiles crossed via edges, plus baseWeight.
    So with baseOffset 3, and tileA value 10 and tileB value -5, when the min value is -10 and the max value is 100 would result in:
    offset = (-minValue) = +10
    1 / (3 + (10 + 10) + (-5 + 10))
    =
    1/28

    In the same setup,
    C val 30 and D val 20 would be
    1 / (3 + 40 + 30) or 1/73

    @param map:
    @param weightModMatrix:
    @param baseOffset:
    @param bannedTiles:
    @param validTiles:
    @param viewInfo: if provided, will update the viewInfo with the connection values.
    @return:
    """
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    # maxW = max(weightModMatrix.raw[t.tile_index] for t in validTiles)
    minW = min(weightModMatrix.raw[t.tile_index] for t in validTiles) * 2
    # offset = -minW
    logbook.info(f'minW was {minW:.3f}')

    for tile in validTiles:
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            continue
        fromWeight = baseOffset

        fromWeight += weightModMatrix.raw[tile.tile_index]

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and right in validTiles:
            weight = fromWeight
            if not right.isObstacle and (not bannedTiles or right not in bannedTiles):
                weight += weightModMatrix.raw[right.tile_index]
                if weight > 0:
                    divided = 1/weight
                else:
                    divided = -weight
                g.add_edge(tileIndex, right.tile_index, weight=divided)
                if viewInfo:
                    viewInfo.bottomMidRightGridText.raw[tileIndex] = f'{divided:.3f}'.lstrip('0')
        if down and down in validTiles:
            weight = fromWeight
            if not down.isObstacle and (not bannedTiles or down not in bannedTiles):
                weight += weightModMatrix.raw[down.tile_index]
                if weight > 0:
                    divided = 1/weight
                else:
                    divided = -weight
                g.add_edge(tileIndex, down.tile_index, weight=divided)
                if viewInfo:
                    viewInfo.bottomLeftGridText.raw[tileIndex] = f'{divided:.3f}'.lstrip('0')

    nextTime = time.perf_counter()
    logbook.info(f'networkX weight divis graph itself built in {nextTime - start:.5f}s')
    return g


def build_networkX_graph_flat_weight_mod_scale(
        map: MapBase,
        weightModMatrix: MapMatrixInterface[float],
        scaleToMin: float = 0.0,
        scaleToMax: float = 1.0,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None,
        negate: bool = True,
        viewInfo: ViewInfo | None = None
) -> nx.Graph:
    """
    Divides 1 over the offset adjusted value of the two tiles crossed via edges, plus baseWeight.
    So with baseOffset 3, and tileA value 10 and tileB value -5, when the min value is -10 and the max value is 100 would result in:
    offset = (-minValue) = +10
    1 / (3 + (10 + 10) + (-5 + 10))
    =
    1/28

    In the same setup,
    C val 30 and D val 20 would be
    1 / (3 + 40 + 30) or 1/73

    @param map:
    @param weightModMatrix:
    @param scaleToMin:
    @param scaleToMax:
    @param bannedTiles:
    @param validTiles:
    @param negate: if True (the default) higher value matrix values will result in lower weight.
    @return:
    """
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    maxW = max(weightModMatrix.raw[t.tile_index] * 2 for t in validTiles)
    minW = min(weightModMatrix.raw[t.tile_index] * 2 for t in validTiles)
    width = maxW - minW

    if negate:
        (scaleToMin, scaleToMax) = (scaleToMax, scaleToMin)

    targetWidth = scaleToMax - scaleToMin

    for tile in validTiles:
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            continue

        fromWeight = weightModMatrix.raw[tile.tile_index]

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index
        if right and right in validTiles:
            weight = fromWeight
            if not right.isObstacle and (not bannedTiles or right not in bannedTiles):
                weight += weightModMatrix.raw[right.tile_index] - minW
                scaled = weight / width
                scaledUp = scaled * targetWidth
                scaledVal = scaledUp + scaleToMin

                if GatherDebug.USE_DEBUG_LOGGING:
                    logbook.info(f'scaled {weightModMatrix.raw[tile.tile_index]:.2f} + {weightModMatrix.raw[right.tile_index]:.2f} to {scaledVal:.3f}')
                g.add_edge(tileIndex, right.tile_index, weight=scaledVal)
                if viewInfo:
                    viewInfo.bottomMidRightGridText.raw[tileIndex] = f'{scaledVal:.3f}'.lstrip('0')

        if down and down in validTiles:
            weight = fromWeight
            if not down.isObstacle and (not bannedTiles or down not in bannedTiles):
                weight += weightModMatrix.raw[down.tile_index] - minW
                scaled = weight / width
                scaledUp = scaled * targetWidth
                scaledVal = scaledUp + scaleToMin

                if GatherDebug.USE_DEBUG_LOGGING:
                    logbook.info(f'scaled {weightModMatrix.raw[tile.tile_index]:.2f} + {weightModMatrix.raw[down.tile_index]:.2f} to {scaledVal:.3f}')
                g.add_edge(tileIndex, down.tile_index, weight=scaledVal)
                if viewInfo:
                    viewInfo.bottomLeftGridText.raw[tileIndex] = f'{scaledVal:.3f}'.lstrip('0')

    nextTime = time.perf_counter()
    logbook.info(f'networkX weight scaled graph itself built in {nextTime - start:.5f}s | toMin {scaleToMin:.2f} toMax {scaleToMax:.2f}  (sourceMin {minW:.2f} sourceMax {maxW:.2f})')

    return g


def build_networkX_graph_flat_value_and_weight_mod(
        map: MapBase,
        weightModMatrix: MapMatrixInterface[float],
        valueMatrix: MapMatrixInterface[float],
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None,
        valuePropName: str = 'value',
        viewInfo: ViewInfo | None = None
) -> nx.Graph:
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    for tile in validTiles:
        fromWeight = baseWeight
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            fromWeight += baseWeight * 1000

        fromWeight -= weightModMatrix.raw[tile.tile_index]

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index

        props = {valuePropName: valueMatrix.raw[tileIndex]}
        g.add_node(tileIndex, **props)

        if right and right in validTiles:
            weight = fromWeight
            if right.isObstacle or (bannedTiles and right in bannedTiles):
                weight += baseWeight * 1000

            weight -= weightModMatrix.raw[right.tile_index]

            g.add_edge(tileIndex, right.tile_index, weight=weight)
            if viewInfo:
                viewInfo.bottomMidRightGridText.raw[tileIndex] = f'{weight:.2f}'.lstrip('0')
        if down and down in validTiles:
            weight = fromWeight
            if down.isObstacle or (bannedTiles and down in bannedTiles):
                weight += baseWeight * 1000

            weight -= weightModMatrix.raw[down.tile_index]

            g.add_edge(tileIndex, down.tile_index, weight=weight)
            if viewInfo:
                viewInfo.bottomLeftGridText.raw[tileIndex] = f'{weight:.2f}'.lstrip('0')

    nextTime = time.perf_counter()
    logbook.info(f'networkX weight/value graph itself built in {nextTime - start:.5f}s')
    return g


def build_networkX_graph_flat_value(
        map: MapBase,
        valueMatrix: MapMatrixInterface[float],
        baseWeight: int = 1,
        bannedTiles: typing.Container[Tile] | None = None,
        validTiles: typing.Set[Tile] | None = None,
        valuePropName: str = 'value',
        viewInfo: ViewInfo | None = None
) -> nx.Graph:
    start = time.perf_counter()

    g = nx.Graph()
    if not validTiles:
        validTiles = map.pathable_tiles

    for tile in validTiles:
        fromWeight = baseWeight
        if tile.isObstacle or (bannedTiles is not None and tile in bannedTiles):
            fromWeight += baseWeight * 1000

        right = map.GetTile(tile.x + 1, tile.y)
        down = map.GetTile(tile.x, tile.y + 1)
        tileIndex = tile.tile_index

        props = {valuePropName: valueMatrix.raw[tileIndex]}
        g.add_node(tileIndex, **props)

        if right and right in validTiles:
            weight = fromWeight
            if right.isObstacle or (bannedTiles and right in bannedTiles):
                weight += baseWeight * 1000

            g.add_edge(tileIndex, right.tile_index, weight=weight)
            if viewInfo:
                viewInfo.bottomMidRightGridText.raw[tileIndex] = f'{weight:.2f}'.lstrip('0')
        if down and down in validTiles:
            weight = fromWeight
            if down.isObstacle or (bannedTiles and down in bannedTiles):
                weight += baseWeight * 1000

            g.add_edge(tileIndex, down.tile_index, weight=weight)
            if viewInfo:
                viewInfo.bottomLeftGridText.raw[tileIndex] = f'{weight:.2f}'.lstrip('0')

    nextTime = time.perf_counter()
    logbook.info(f'networkX w=1 value graph itself built in {nextTime - start:.5f}s')
    return g