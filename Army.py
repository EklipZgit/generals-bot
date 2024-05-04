from __future__ import annotations
import typing

import logbook

import SearchUtils
from Path import Path
from base.client.tile import Tile


class Army(object):
    start = 'A'
    end = 'z'
    curLetter = start

    @staticmethod
    def get_letter():
        ch = Army.curLetter
        if ord(ch) + 1 > ord(Army.end):
            Army.curLetter = Army.start
        else:
            Army.curLetter = chr(ord(ch) + 1)
            while Army.curLetter in ['[', '\\', ']', '^', '_', '`']:
                Army.curLetter = chr(ord(Army.curLetter) + 1)
        return ch

    def __init__(self, tile: Tile, name: str | None = None):
        self.tile: Tile = tile
        self.path: Path = Path()
        self.player: int = tile.player
        self.visible: bool = tile.visible
        self.value: int = 0
        """Always the value of the tile, minus one. For some reason."""
        self.update_tile(tile)
        self.expectedPaths: typing.List[Path] = []
        self.entangledArmies: typing.List[Army] = []
        self.name: str = name
        if not name:
            self.name = Army.get_letter()

        self.entangledValue = None
        self.scrapped = False
        self.last_moved_turn: int = 0
        self.last_seen_turn: int = 0

    def update_tile(self, tile):
        if self.path.tail is None or self.path.tail.tile != tile:
            self.path.add_next(tile)

        if self.tile != tile:
            self.tile = tile

        self.update()

    def update(self):
        if self.tile.visible:
            self.value = self.tile.army - 1
        self.visible = self.tile.visible

    def get_split_for_fog(self, fogTiles: typing.List[Tile]) -> typing.List[Army]:
        split = []
        for tile in fogTiles:
            splitArmy = self.clone()
            splitArmy.entangledValue = self.value
            if self.entangledValue is not None:
                splitArmy.entangledValue = self.entangledValue
            split.append(splitArmy)
        # entangle the armies
        for existingEntangled in self.entangledArmies:
            existingEntangled.entangledArmies.extend(split)
        for splitBoi in split:
            splitBoi.entangledArmies.extend(SearchUtils.where(split, lambda army: army != splitBoi))
        logbook.info(f"for army {str(self)} set self as scrapped because splitting for fog")
        self.scrapped = True
        return split

    def clone(self):
        newDude = Army(self.tile, self.name)
        if self.path is not None:
            newDude.path = self.path.clone()
        newDude.player = self.player
        newDude.visible = self.visible
        newDude.value = self.value
        newDude.last_moved_turn = self.last_moved_turn
        newDude.last_seen_turn = self.last_seen_turn
        for path in self.expectedPaths:
            newDude.expectedPaths.append(path.clone())
        newDude.entangledArmies = list(self.entangledArmies)
        newDude.scrapped = self.scrapped
        return newDude

    def toString(self):
        return f"[{self.name} {self.tile} p{self.player} v{self.value}{' scr' if self.scrapped else ''}]"

    def __str__(self):
        return self.toString()

    def __repr__(self):
        return self.toString()

    def include_path(self, path: Path):
        if path is None:
            return

        foundMatch = False
        for existingPath in self.expectedPaths:
            pathNode = path.start
            existingPathNode = existingPath.start

            isPathMatch = True
            while pathNode is not None and existingPathNode is not None:
                if pathNode.tile != existingPathNode.tile:
                    isPathMatch = False
                    break

                pathNode = pathNode.next
                existingPathNode = existingPathNode.next

            if pathNode is not None or existingPathNode is not None:
                # then one was longer than the other, also false
                isPathMatch = False

            if isPathMatch:
                foundMatch = True
                break

        if not foundMatch:
            self.expectedPaths.append(path)