"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

from __future__ import annotations

import GatherUtils
from ArmyAnalyzer import *
from BoardAnalyzer import BoardAnalyzer
from Communication import TileCompressor, CoordinatedDefense, DefensePlan, CommunicationConstants, TeammateCommunication
from DangerAnalyzer import ThreatObj
from SearchUtils import *
from DataModels import *

from base.client.generals import ChatUpdate
from base.client.map import Player


class CoordinatedLaunch(object):
    def __init__(
            self,
            allyAttackPath: Path,
            allyAttackTiming: int,
    ):
        self.coordinated_launch_path: Path = allyAttackPath
        self.coordinated_launch_timing: int = allyAttackTiming

        self.teammate_gathering_tiles: typing.Set[Tile] = set()
        """We can gather army to these tiles and leave them for the teammate to finish gathering as part of their existing plan"""

        self.teammate_gathering_leaves: typing.Set[Tile] = set()
        """If we gather to these tiles then we will prevent the teammate from executing the gather they had planned, don't gather to these."""

        # self._queued_communications: typing.List[Communicatable]


class TeammateCommunicator(object):
    def __init__(self, map: MapBase, tileCompressor: TileCompressor, boardAnalysis: BoardAnalyzer):
        self.map: MapBase = map
        self.is_2v2: bool = map.is_2v2
        self.is_teammate_coordinated_bot: bool = False
        self.tile_compressor: TileCompressor = tileCompressor
        self.teammate_player: Player | None = None
        # todo once enemies discovered, bot closest to enemies becomes team lead?
        self.is_team_lead: bool = False
        """Bot closest on offense should be offense lead"""

        self.is_defense_lead: bool = False
        """Bot furthest on offense should be defense lead, so offense can use tiles more effectively"""

        for teammate in self.map.teammates:
            if self._is_teammate_known_coordinated_bot_username(teammate):
                self.is_teammate_coordinated_bot = True
                self.is_team_lead = self.map.player_index < teammate
                self.is_defense_lead = self.map.player_index > teammate
            self.teammate_player = self.map.players[teammate]

        self.coordinated_defense: CoordinatedDefense = CoordinatedDefense(isDefenseLead=self.is_defense_lead)

        self.board_analysis: BoardAnalyzer = boardAnalysis

    def handle_coordination_update(self, chatUpdate: ChatUpdate):
        communicationTypes = chatUpdate.message.split('&')
        for comm in communicationTypes:
            if comm.startswith('!D'):
                # defense comm
                self.coordinated_defense.read_coordination_message(comm, self.tile_compressor)
                if self.coordinated_defense.is_defense_lead:
                    self.is_defense_lead = True

    def _is_teammate_known_coordinated_bot_username(self, teammate: int):
        username = self.map.usernames[teammate]
        isPublicServer = 'bot' not in self.map.usernames[self.map.player_index].lower()

        if not isPublicServer and 'EklipZ' in username and 'ai' in username.lower():
            return True

        if 'Human.exe' == username:
            return True

        if 'Exe.human' == username:
            return True

        if 'Teammate.exe' == username:
            return True

        return False

    def begin_next_turn(self):
        if self.coordinated_defense is not None:
            if self.is_defense_lead:
                self.coordinated_defense.last_blocked_tiles = self.coordinated_defense.blocked_tiles
                # we'll re-block all the tiles this turn, as the lead

            self.coordinated_defense.blocked_tiles = set()

            # for plan in list(self.coordinated_defense.defenses):
            #     plan.not_updated_since += 1
            #     if plan.not_updated_since > 5:
            #         self.coordinated_defense.defenses.remove(plan)
            self.coordinated_defense.defenses.clear()

    def produce_teammate_communications(self) -> typing.List[TeammateCommunication]:
        if self.is_teammate_coordinated_bot:
            return self.produce_bot_communications()
        else:
            return self.produce_human_communications()

    def produce_bot_communications(self) -> typing.List[TeammateCommunication]:
        messages = []
        curMessage: TeammateCommunication | None = None
        if self.coordinated_defense is not None and self.is_teammate_coordinated_bot:
            teammateTileDistMap = SearchUtils.build_distance_map(self.map, self.teammate_player.tiles)
            nextMessage = self.coordinated_defense.get_as_bot_communication(self.map, self.tile_compressor, teammateTileDistMap)
            curMessage = self._try_combine_messages(messages, curMessage, nextMessage)

        # if self.coordinated_launch is not None:
        #     curMessage = self.coordinated_defense.get_as_bot_communication(self.map, self.tile_compressor)

        if curMessage is not None:
            messages.append(curMessage)

        return messages

    def produce_human_communications(self) -> typing.List[TeammateCommunication]:
        messages = []

        return messages

    def communicate_defense_plan(self, threat: ThreatObj, valueGathered: int, defensePlanGatherNodes: typing.List[GatherTreeNode]):
        threatTile = threat.path.start.tile
        threatTarget = threat.path.tail.tile
        threatTurns = threat.turns - 1
        requiredArmy = threat.threatValue - valueGathered

        gatherTiles = []
        if self.is_defense_lead and defensePlanGatherNodes is not None:
            GatherUtils.iterate_tree_nodes(defensePlanGatherNodes, lambda n: gatherTiles.append(n.tile))

        self.coordinated_defense.include_defense_plan(threatTarget, threatTile, threatTurns, requiredArmy, gatherTiles, markLivePlan=True)

    @staticmethod
    def _try_combine_messages(messages: typing.List[TeammateCommunication], curMessage: TeammateCommunication | None, nextMessage: TeammateCommunication | None) -> TeammateCommunication:
        """
        If the combined message length is shorter than the message char limit, combines them. Otherwise, appends the previous message to the list and starts a new one.
        @param messages:
        @param curMessage:
        @param nextMessage:
        @return:
        """

        if curMessage is None:
            return nextMessage

        if nextMessage is None:
            return curMessage

        if len(curMessage.message) + len(nextMessage.message) < CommunicationConstants.TEAM_CHAT_CHARACTER_LIMIT:
            curMessage.message += nextMessage.message
            return curMessage

        messages.append(curMessage)

        return nextMessage

    def get_additional_defense_negatives_and_contribution_requirement(self, threat: ThreatObj) -> typing.Tuple[int, typing.Set[Tile]]:
        if not self.is_teammate_coordinated_bot:
            return threat.threatValue, set()

        threatTile = threat.path.start.tile
        for defense in self.coordinated_defense.defenses:
            if threatTile == defense.threat_tile or threatTile in defense.threat_tile.movable:
                if self.is_defense_lead:  # defense leads are responsible for the main defense of the threat and should tell the offensive player when to help out, so try to defend the full threat.
                    return threat.threatValue, set()
                else:
                    return defense.required_army, self.coordinated_defense.blocked_tiles

        return threat.threatValue, set()

    def determine_leads(
            self,
            gen_distance_map: typing.List[typing.List[int]],
            ally_distances: typing.List[typing.List[int]],
            targetPlayerExpectedGeneralLocation: Tile
    ):
        usDist = gen_distance_map[targetPlayerExpectedGeneralLocation.x][targetPlayerExpectedGeneralLocation.y]
        allyDist = ally_distances[targetPlayerExpectedGeneralLocation.x][targetPlayerExpectedGeneralLocation.y]
        if usDist > allyDist + 2:
            if not self.is_defense_lead or not self.coordinated_defense.is_defense_lead:
                self.is_defense_lead = True
                self.coordinated_defense.is_defense_lead = True
                logging.info(f'swapping TO defense lead.')
        elif usDist < allyDist - 2:
            if self.is_defense_lead or self.coordinated_defense.is_defense_lead:
                self.is_defense_lead = False
                self.coordinated_defense.is_defense_lead = False
                logging.info(f'swapping OFF of defense lead.')





