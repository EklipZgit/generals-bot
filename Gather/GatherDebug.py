import typing
from collections import deque

import logbook

from base.client.tile import Tile

USE_DEBUG_ASSERTS = False
USE_DEBUG_LOGGING = False


def assertConnected(tiles: typing.Set[Tile]):
    seedTile = next(iter(tiles))

    visited = set()

    q = deque()
    q.append(seedTile)

    while q:
        tile = q.pop()
        if tile in visited:
            continue

        visited.add(tile)

        for mv in tile.movable:
            if mv in tiles:
                q.append(mv)

    if len(visited) != len(tiles):
        raise Exception(f'tiles were not connected to seed tile {seedTile}. Disconnected tiles:\r\n   {" | ".join([str(t) for t in tiles.difference(visited)])}')