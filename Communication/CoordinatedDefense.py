from __future__ import annotations

import logbook
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
        self.is_live_and_managed_by_us: bool = False


class CoordinatedDefense(object):
    """This object should have the same data in both bots, in the team lead this is the communicated requirements, in the supporter this is the requirements it will try to meet."""
    def __init__(
            self,
            isDefenseLead: bool = False
    ):
        self.defenses: typing.List[DefensePlan] = []

        self.is_defense_lead: bool = isDefenseLead

        self.blocked_tiles: typing.Set[Tile] = set()
        """The tiles blocked by allies defense."""

        # self.blocked_tiles_by_ally: typing.Set[Tile] = set()
        # """The tiles blocked as negative by our ally as they will already use them."""

        self.blocked_tiles_by_us: typing.Set[Tile] = set()
        """The tiles blocked as negative by us to tell our ally not to use."""

        self.last_blocked_tiles_by_us: typing.Set[Tile] = set()
        """This is what our ally thinks the blocked tiles still are."""

    def get_as_bot_communication(
            self,
            map: MapBase,
            tileCompressor: TileCompressor,
            teammateTileDistanceMap: typing.List[typing.List[int]],
            charsLeft: int = CommunicationConstants.TEAM_CHAT_CHARACTER_LIMIT
    ) -> TeammateCommunication | None:
        """Compress the defense as much as possible, dropping tiles that are furthest from ally tiles as they are least likely to interact with those"""

        # !D = Defense plan,
        # F = From tile (so they can make sure they're defending same threats)
        # I = in turns,
        # W = required army from partner

        builtMsg = []

        for defense in self.defenses:
            if defense.is_live_and_managed_by_us:
                defenseBotChatDeclaration = self._compress_threat_defense_message(defense.tile, defense.threat_tile, defense.remaining_turns, defense.required_army, self.is_defense_lead, tileCompressor)

                charsLeft -= len(defenseBotChatDeclaration)
                builtMsg.append(defenseBotChatDeclaration)

        if len(builtMsg) == 0:
            return None

        negativeTilesOrderedByDist = list(sorted(self.blocked_tiles_by_us, key=lambda t: teammateTileDistanceMap[t.x][t.y]))

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
            matchesThreatTile = threatTile == defPlan.threat_tile or threatTile in defPlan.threat_tile.movable
            matchesDefTile = threatTarget == defPlan.tile
            if matchesThreatTile and matchesDefTile:
                foundMatch = True
                # then we're updating defense plan A
                if threatTurns == defPlan.remaining_turns:
                    # then this is the same defense we already have planned :)
                    logbook.info(f'Threat {str(threatTile)}->{str(threatTarget)} behaving as expected')
                    pass
                else:
                    # defense has changed?
                    logbook.info(
                        f'Threat {str(threatTile)}->{str(threatTarget)} not behaving as expected, turns {threatTurns} vs expected {defPlan.remaining_turns - 1}, is it targeting something other than what we expect...?')
                    pass
                # update the plan either way
                defPlan.tile = threatTarget
                defPlan.threat_tile = threatTile
                defPlan.remaining_turns = threatTurns
                defPlan.required_army = requiredArmy
                if markLivePlan:
                    defPlan.is_live_and_managed_by_us = True

        if not foundMatch:
            # new threat, tack it on!
            plan = DefensePlan(
                threatTarget,
                threatTile,
                threatTurns,  # intentionally not -1 so we can use the path below for 'already handled threat...?'
                requiredArmy
            )
            plan.is_live_and_managed_by_us = markLivePlan
            self.defenses.append(plan)

        if defensePlanGatherNodes is not None:
            if markLivePlan:
                self.blocked_tiles_by_us.update(defensePlanGatherNodes)
            else:
                self.blocked_tiles.update(defensePlanGatherNodes)
