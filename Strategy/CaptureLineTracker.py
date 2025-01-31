from __future__ import annotations

import logbook
import typing

from ArmyTracker import Army
from Interfaces import TilePlanInterface
from Path import Path
from StrategyModels import CycleStatsData, PlayerMoveCategory, ExpansionPotential
from ViewInfo import ViewInfo, TargetStyle
from base.client.map import MapBase, TeamStats, Tile, Player, PLAYER_CHAR_BY_INDEX

ENABLE_DEBUG_ASSERTS = False


class CaptureLineOption(object):
    def __init__(self, basePlan: TilePlanInterface, capturableTiles: typing.Set[int], minTurns: int, maxTurns: int, finalCapSequenceLength: int):
        self.plan: TilePlanInterface = basePlan

        self.all_tiles: typing.Set[int] = capturableTiles.union(t.tile_index for t in basePlan.tileList)

        self.max_turns: int = maxTurns
        """The maximum number of turns before the path runs out of captures"""

        self.min_turns: int = minTurns
        """The minimum number of capture turns for this to beat either leafmoves (if capturing enemy)"""

        self.final_cap_sequence_length: int = finalCapSequenceLength
        """The number of turns this will spend capturing tiles at the same final econ val per turn"""

        self.length: int = maxTurns
        """The number of fog tiles the player has in queue. Includes 1s."""


class CaptureLineTracker(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self.targetPlayer: int = -1
        self.options_by_tile: typing.Dict[int, typing.List[CaptureLineOption]] = {}

    def process_plan(self, targetPlayer: int, expansionOptions: ExpansionPotential):
        self.options_by_tile: typing.Dict[int, typing.List[CaptureLineOption]] = {}
        self.targetPlayer = targetPlayer

        byTile: typing.Dict[int, typing.List[TilePlanInterface]] = {}
        for thing in expansionOptions.all_paths:
            startTile = thing.get_first_move().source
            if not startTile.isCity and not startTile.isGeneral:
                continue

            opts = byTile.get(startTile.tile_index, [])
            if len(opts) == 0:
                byTile[startTile.tile_index] = opts

            opts.append(thing)

        frPlayers = self.map.get_teammates(self.map.player_index)
        tgPlayers = self.map.get_teammates(self.targetPlayer)

        for tIdx, opts in byTile.items():
            tile = self.map.tiles_by_index[tIdx]
            try:
                clOpts = self.options_by_tile[tIdx]
            except KeyError:
                clOpts = []
                self.options_by_tile[tIdx] = clOpts

            # TODO just include the longest "short" option and longest "long" option..?
            maxOptShort = None
            shortVal = 0.0

            maxOptLong = None
            longVal = 0.0

            for opt in opts:
                if opt.length == 0:
                    continue
                optVt = opt.econValue / opt.length
                timeToFirstCap = -1
                turn = 0
                finalCapSequenceLength = 0
                cappable = set()
                for mv in opt.get_move_list():
                    caps = mv.dest.player in tgPlayers
                    if caps:
                        if timeToFirstCap == -1:
                            timeToFirstCap = turn
                        finalCapSequenceLength += 1
                        cappable.add(mv.dest.tile_index)
                    else:
                        finalCapSequenceLength = 0

                    turn += 1

                clOpts.append(CaptureLineOption(opt, cappable, minTurns=timeToFirstCap, maxTurns=opt.length, finalCapSequenceLength=finalCapSequenceLength))
