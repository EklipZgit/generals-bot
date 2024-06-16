from .GatherTreeNode import *
from .Move import *


class ContestData(object):
    def __init__(self, tile: Tile):
        self.tile: Tile = tile
        self.last_attacked_turn: int = 0
        self.attacked_count: int = 0

    def __str__(self) -> str:
        return f'Contested {str(self.tile)}: last{self.last_attacked_turn} atk#{self.attacked_count}'

    def __repr__(self) -> str:
        return str(self)