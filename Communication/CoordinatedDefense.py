from __future__ import annotations

import logging
import typing

import GatherUtils
from Communication import TileCompressor, CommunicationConstants, TeammateCommunication
from DangerAnalyzer import ThreatObj
from DataModels import GatherTreeNode
from base.client.map import Tile, MapBase


class DefensePlan(object):
    def __init__(
            self,
            defendingTile: Tile,
            threatTile: Tile,
            remainingTurns: int,
            teammateRequiredArmy: int
    ):
        self.tile: Tile = defendingTile
        self.threat_tile: Tile = threatTile
        self.remaining_turns: int = remainingTurns
        self.required_army: int = teammateRequiredArmy
        self.not_updated_since: int = 0


class CoordinatedDefense(object):
    """This object should have the same data in both bots, in the team lead this is the communicated requirements, in the supporter this is the requirements it will try to meet."""
    def __init__(
            self,
            defendingTile: Tile | None = None,
            threatTile: Tile | None = None,
            remainingTurns: int | None = None,
            teammateRequiredArmy: int | None = None,
            isDefenseLead: bool = False
    ):
        self.defenses: typing.List[DefensePlan] = []
        if defendingTile is not None:
            self.defenses.append(DefensePlan(defendingTile, threatTile, remainingTurns, teammateRequiredArmy))

        self.is_defense_lead: bool = isDefenseLead

        self.blocked_tiles: typing.Set[Tile] = set()
        """The tiles blocked as negative by our ally as they will already use them."""

        self.last_blocked_tiles: typing.Set[Tile] = set()
        """This is what our ally things the blocked tiles still are."""

    def get_as_bot_communication(
            self,
            map: MapBase,
            tileCompressor: TileCompressor,
            teammateTileDistanceMap: typing.List[typing.List[int]],
            charsLeft: int = CommunicationConstants.TEAM_CHAT_CHARACTER_LIMIT
    ) -> TeammateCommunication | None:
        """Compress the defense as much as possible, dropping tiles that are furthest from ally tiles as they are least likely to interact with those"""

        if len(self.defenses) == 0:
            return None

        # !D = Defense plan,
        # F = From tile (so they can make sure they're defending same threats)
        # I = in turns,
        # W = required army from partner

        builtMsg = []

        for defense in self.defenses:
            defenseBotChatDeclaration = self._compress_threat_defense_message(defense.tile, defense.threat_tile, defense.remaining_turns, defense.required_army, self.is_defense_lead, tileCompressor)

            charsLeft -= len(defenseBotChatDeclaration)
            builtMsg.append(defenseBotChatDeclaration)

        negativeTilesOrderedByDist = list(sorted(self.blocked_tiles, key=lambda t: teammateTileDistanceMap[t.x][t.y]))

        builtMsg.append('N')
        charsLeft -= 1

        builtMsg.append(tileCompressor.compress_tile_list(negativeTilesOrderedByDist, charsLeft))

        rawMessage = ''.join(builtMsg)

        return TeammateCommunication(rawMessage, None, cooldown=0)  # we ALWAYS send this

    def read_coordination_message(self, message: str, tileCompressor: TileCompressor):
        try:
            threatInfo, tiles = message.split('N')
        except:
            tiles = ''
            threatInfo = message

        if message.lstrip('!').startswith('D*') and self.is_defense_lead:
            # D* means other bot is taking over defense lead forcibly??

            self.is_defense_lead = False

        threatInfos = threatInfo.lstrip('!').split('!')

        blockedTiles = tileCompressor.decompress_tile_list(tiles)

        for threatInfo in threatInfos:
            defensePlan = CoordinatedDefense._parse_defense_data(threatInfo, tileCompressor)
            self.include_defense_plan(defensePlan.tile, defensePlan.threat_tile, defensePlan.remaining_turns, defensePlan.required_army, [], markLivePlan=False)

        self.blocked_tiles.update(blockedTiles)

    @staticmethod
    def _compress_threat_defense_message(tile: Tile, threatTile: Tile, remainingTurns: int, required_army: int, is_defense_lead: bool, tileCompressor: TileCompressor) -> str:
        defLeadChar = ''
        if is_defense_lead:
            defLeadChar = '*'
        return f'!D{defLeadChar}{tileCompressor.compress_tile(tile)}F{tileCompressor.compress_tile(threatTile)}I{remainingTurns}W{required_army}'

    @staticmethod
    def _parse_defense_data(threatInfo: str | None, tileCompressor: TileCompressor) -> DefensePlan | None:
        if threatInfo is None:
            return None
        compressedTile, remaining = threatInfo.lstrip('D*').split('F')
        compressedThreat, remaining = remaining.split('I')
        turnsStr, requiredArmyStr = remaining.split('W')

        return DefensePlan(
            tileCompressor.decompress_tile(compressedTile),
            tileCompressor.decompress_tile(compressedThreat),
            int(turnsStr),
            int(requiredArmyStr)
        )

    def include_defense_plan(self, threatTarget: Tile, threatTile: Tile, threatTurns: int, requiredArmy: int, defensePlanGatherNodes: typing.List[Tile], markLivePlan: bool = False):

        foundMatch = False
        for defPlan in self.defenses:
            if threatTile == defPlan.threat_tile or threatTile in defPlan.threat_tile.movable:
                foundMatch = True
                # then we're updating defense plan A
                if threatTurns == defPlan.remaining_turns - 1:
                    # then this is the same defense we already have planned :)
                    logging.info(f'Threat {str(threatTile)}->{str(threatTarget)} behaving as expected')
                    pass
                else:
                    # defense has changed?
                    logging.info(
                        f'Threat {str(threatTile)}->{str(threatTarget)} not behaving as expected, turns {threatTurns} vs expected {defPlan.remaining_turns - 1}, is it targeting something other than what we expect...?')
                    pass
                # update the plan either way
                defPlan.tile = threatTarget
                defPlan.threat_tile = threatTile
                defPlan.remaining_turns = threatTurns
                defPlan.required_army = requiredArmy
                if markLivePlan:
                    defPlan.not_updated_since = 0

        if not foundMatch:
            # new threat, tack it on!
            self.defenses.append(
                DefensePlan(
                    threatTarget,
                    threatTile,
                    threatTurns,  # intentionally not -1 so we can use the path below for 'already handled threat...?'
                    requiredArmy
                )
            )

        if defensePlanGatherNodes is not None:
            self.blocked_tiles.update(defensePlanGatherNodes)