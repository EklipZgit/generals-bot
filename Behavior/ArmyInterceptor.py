from __future__ import  annotations

import typing

from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DangerAnalyzer import ThreatObj
from DataModels import Move
from Engine.ArmyEngineModels import ArmySimState
from base.client.map import MapBase


class ArmyInterception(object):
    def __init__(
        self,
        threats: typing.List[ThreatObj]
    ):
        self.threats: typing.List[ThreatObj] = threats
        self.best_enemy_threat: ThreatObj | None = None
        self.best_defense: typing.List[Move]
        self.best_board_state: ArmySimState
        self.threat_econ_value: int = 0
        self.response_econ_value: int = 0


class ArmyInterceptor(object):
    def __init__(
        self,
        map: MapBase,
        boardAnalysis: BoardAnalyzer
    ):
        self.map: MapBase = map
        self.board_analysis: BoardAnalyzer = boardAnalysis

    def get_interception_plan(
        self,
        threats: typing.List[ThreatObj]
    ) -> ArmyInterception:
        interception = ArmyInterception(threats)

        commonChokes = {}
        common2Chokes = {}

        for threat in threats:
            for tile in threat.path.tileList:
                if tile in threat.armyAnalysis.pathChokes:
                    curCount = commonChokes.get(tile, 0)
                    commonChokes[tile] = curCount + 1

                if threat.armyAnalysis.chokeWidths[tile] < 3:
                    curCount = common2Chokes.get(tile, 0)
                    common2Chokes[tile] = curCount + 1


