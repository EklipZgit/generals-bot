import typing

from Behavior.ArmyInterceptor import InterceptionOptionInfo
from Interfaces import TilePlanInterface
from base.client.tile import Tile


class ExpansionPotential(object):
    def __init__(
            self,
            turnsUsed: int,
            enTilesCaptured: int,
            neutTilesCaptured: int,
            selectedOption: TilePlanInterface | None,
            allOptions: typing.List[TilePlanInterface],
            cumulativeEconVal: float
    ):
        self.turns_used: int = turnsUsed
        self.en_tiles_captured: int = enTilesCaptured
        self.neut_tiles_captured: int = neutTilesCaptured
        self.selected_option: TilePlanInterface = selectedOption
        self.all_paths: typing.List[TilePlanInterface] = allOptions
        self.plan_tiles: typing.Set[Tile] = set()
        self.preferred_tiles: typing.Set[Tile] = set()
        self.blocking_tiles: typing.Set[Tile] = set()
        self.intercept_waiting: typing.List[InterceptionOptionInfo] = []
        """Tiles who are part of the required plan, but which have a required delay on them."""

        self.includes_intercept: bool = False
        for selectedOption in allOptions:
            self.plan_tiles.update(selectedOption.tileSet)

        self.cumulative_econ_value: float = cumulativeEconVal
