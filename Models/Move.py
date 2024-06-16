from base.client.tile import Tile


class Move(object):
    def __init__(self, source: Tile, dest: Tile, move_half=False):
        self.source: Tile = source
        self.dest: Tile = dest
        self.move_half = move_half
        self.army_moved: int = source.army - 1
        if self.move_half:
            self.army_moved = (source.army - 1) // 2
        self.non_friendly = self.source.player != self.dest.player

    def __gt__(self, other):
        if other is None:
            return True
        return self.source.army - self.dest.army > other.source.army - other.dest.army

    def __lt__(self, other):
        if other is None:
            return False
        return self.source.army - self.dest.army < other.source.army - other.dest.army

    def __str__(self):
        moveHalfString = ""
        if self.move_half:
            moveHalfString = 'z'
        return f"{self.source.x},{self.source.y} -{moveHalfString}> {self.dest.x},{self.dest.y}"

    def __repr__(self):
        return str(self)

    def __hash__(self):
        return hash((self.source.x, self.source.y, self.dest.x, self.dest.y, self.move_half))

    def __eq__(self, other):
        if isinstance(other, Move):
            return self.source.x == other.source.x and self.source.y == other.source.y and self.dest.x == other.dest.x and self.dest.y == other.dest.y and self.move_half == other.move_half

        return False

    def toString(self) -> str:
        return str(self)
